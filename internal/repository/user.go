package repository

import (
	"context"
	"dr_mind/internal/crypto"
	"fmt"
	"time"

	"github.com/sirupsen/logrus"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

type Repository struct {
	db     *gorm.DB
	crypto *crypto.EncryptionService
}

func NewRepository(dsn string, encryptionKey string) (*Repository, error) {
	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
	if err != nil {
		return nil, fmt.Errorf("failed to connect to database: %w", err)
	}

	// Авто-миграция
	err = db.AutoMigrate(&User{}, &Conversation{}, &Summary{})
	if err != nil {
		return nil, fmt.Errorf("failed to migrate database: %w", err)
	}

	cryptoService, err := crypto.NewEncryptionService(encryptionKey)
	if err != nil {
		return nil, err
	}

	return &Repository{
		db:     db,
		crypto: cryptoService,
	}, nil
}

// User methods

func (r *Repository) GetUser(ctx context.Context, userID string) (*User, error) {
	var user User
	err := r.db.WithContext(ctx).Where("user_id = ?", userID).First(&user).Error
	if err == gorm.ErrRecordNotFound {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &user, nil
}

func (r *Repository) UpsertUser(ctx context.Context, user *User) error {
	// GORM's Save handles upsert logic if primary key is present
	// But to be explicit about ON CONFLICT behavior matching previous logic:
	return r.db.WithContext(ctx).Save(user).Error
}

func (r *Repository) SetSupervisorMode(ctx context.Context, userID string, isSupervisor bool) error {
	return r.db.WithContext(ctx).Model(&User{}).Where("user_id = ?", userID).Update("is_supervisor_mode", isSupervisor).Error
}

// Conversation methods (зашифрованные)

func (r *Repository) AddConversation(ctx context.Context, userID string, userMsg, assistantMsg string) error {
	// Получаем текущий индекс сообщения
	var currentMax *int
	r.db.WithContext(ctx).Model(&Conversation{}).Where("user_id = ?", userID).Select("MAX(message_index)").Scan(&currentMax)

	nextIndex := 0
	if currentMax != nil {
		nextIndex = *currentMax + 1
	} 

	// Шифруем сообщения
	encryptedUser, err := r.crypto.Encrypt(userMsg)
	if err != nil {
		return err
	}

	encryptedAssistant, err := r.crypto.Encrypt(assistantMsg)
	if err != nil {
		return err
	}

	conv := Conversation{
		UserID:                    userID,
		MessageIndex:              nextIndex,
		EncryptedUserMessage:      encryptedUser,
		EncryptedAssistantMessage: encryptedAssistant,
	}

	return r.db.WithContext(ctx).Create(&conv).Error
}

func (r *Repository) GetConversations(ctx context.Context, userID string, limit int) ([]Message, error) {
	var conversations []Conversation
	err := r.db.WithContext(ctx).
		Where("user_id = ?", userID).
		Order("message_index DESC").
		Limit(limit).
		Find(&conversations).Error

	if err != nil {
		return nil, err
	}

	var messages []Message
	for _, conv := range conversations {
		// Пропускаем пустые значения
		if conv.EncryptedUserMessage == "" || conv.EncryptedAssistantMessage == "" {
			logrus.WithFields(logrus.Fields{
				"user_id": userID,
			}).Warn("Empty encrypted message found, skipping conversation")
			continue
		}

		// Расшифровываем пользовательское сообщение
		userMsg, isUserPlaintext, err := r.crypto.DecryptOrPlaintext(conv.EncryptedUserMessage)
		if err != nil {
			logrus.WithError(err).WithFields(logrus.Fields{
				"user_id":          userID,
				"encrypted_length": len(conv.EncryptedUserMessage),
			}).Warn("Failed to decrypt user message, skipping conversation")
			continue
		}
		if isUserPlaintext {
			logrus.WithFields(logrus.Fields{"user_id": userID}).Debug("User message is plaintext")
		}

		// Расшифровываем сообщение ассистента
		assistantMsg, isAssistantPlaintext, err := r.crypto.DecryptOrPlaintext(conv.EncryptedAssistantMessage)
		if err != nil {
			logrus.WithError(err).WithFields(logrus.Fields{
				"user_id":          userID,
				"encrypted_length": len(conv.EncryptedAssistantMessage),
			}).Warn("Failed to decrypt assistant message, skipping conversation")
			continue
		}
		if isAssistantPlaintext {
			logrus.WithFields(logrus.Fields{"user_id": userID}).Debug("Assistant message is plaintext")
		}

		messages = append(messages, Message{
			User:      userMsg,
			Assistant: assistantMsg,
			Timestamp: conv.CreatedAt,
		})
	}

	// Разворачиваем порядок (последние сообщения в конце)
	for i, j := 0, len(messages)-1; i < j; i, j = i+1, j-1 {
		messages[i], messages[j] = messages[j], messages[i]
	}

	return messages, nil
}

func (r *Repository) GetConversationCount(ctx context.Context, userID string) (int, error) {
	var count int64
	err := r.db.WithContext(ctx).Model(&Conversation{}).Where("user_id = ?", userID).Count(&count).Error
	return int(count), err
}

// Summary methods

func (r *Repository) GetCurrentSummary(ctx context.Context, userID string) (*Summary, error) {
	var summary Summary
	err := r.db.WithContext(ctx).
		Where("user_id = ? AND is_current = ?", userID, true).
		Order("updated_at DESC").
		First(&summary).Error

	if err == gorm.ErrRecordNotFound {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	// Расшифровываем суммаризацию
	summaryText, isPlaintext, err := r.crypto.DecryptOrPlaintext(summary.EncryptedSummaryText)
	if err != nil {
		logrus.WithError(err).WithFields(logrus.Fields{
			"user_id":    userID,
			"summary_id": summary.ID,
		}).Warn("Failed to decrypt summary, using as plaintext")
		summary.SummaryText = summary.EncryptedSummaryText
	} else {
		summary.SummaryText = summaryText
		if isPlaintext {
			logrus.WithFields(logrus.Fields{
				"user_id":    userID,
				"summary_id": summary.ID,
			}).Debug("Summary is plaintext")
		}
	}

	return &summary, nil
}

func (r *Repository) SaveSummary(ctx context.Context, userID string, summaryText string, messageCount int) error {
	return r.db.Transaction(func(tx *gorm.DB) error {
		// Сначала помечаем все старые суммаризации как неактивные
		if err := tx.Model(&Summary{}).
			Where("user_id = ?", userID).
			Update("is_current", false).Error; err != nil {
			return err
		}

		// Шифруем суммаризацию
		encryptedSummary, err := r.crypto.Encrypt(summaryText)
		if err != nil {
			return fmt.Errorf("failed to encrypt summary: %w", err)
		}

		// Сохраняем новую
		newSummary := Summary{
			UserID:                userID,
			EncryptedSummaryText:  encryptedSummary,
			MessageCountAtSummary: messageCount,
			IsCurrent:             true,
		}

		return tx.Create(&newSummary).Error
	})
}

func (r *Repository) UpdateSummary(ctx context.Context, summaryID uint, summaryText string) error {
	encryptedSummary, err := r.crypto.Encrypt(summaryText)
	if err != nil {
		return fmt.Errorf("failed to encrypt summary: %w", err)
	}

	return r.db.WithContext(ctx).Model(&Summary{}).
		Where("id = ?", summaryID).
		Updates(map[string]interface{}{
			"encrypted_summary_text": encryptedSummary,
			"updated_at":             time.Now(),
		}).Error
}

func (r *Repository) GetAllUserIDs(ctx context.Context) ([]string, error) {
	var userIDs []string
	err := r.db.WithContext(ctx).Model(&User{}).Pluck("user_id", &userIDs).Error
	return userIDs, err
}

func (r *Repository) Close() error {
	sqlDB, err := r.db.DB()
	if err != nil {
		return err
	}
	return sqlDB.Close()
}
