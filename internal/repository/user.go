package repository

import (
	"context"
	"database/sql"
	"dr_mind/internal/crypto"
	"fmt"
	"time"

	_ "github.com/lib/pq"
)

type User struct {
	UserID       string
	Name         string
	MessageCount int
	CreatedAt    time.Time
	UpdatedAt    time.Time
}

type Message struct {
	User      string
	Assistant string
	Timestamp time.Time
}

type Summary struct {
	ID                    int
	UserID                string
	SummaryText           string
	MessageCountAtSummary int
	CreatedAt             time.Time
	UpdatedAt             time.Time
	IsCurrent             bool
}

type Repository struct {
	db     *sql.DB
	crypto *crypto.EncryptionService
}

func NewRepository(dsn string, encryptionKey string) (*Repository, error) {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, err
	}

	// Проверяем соединение
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
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
	query := `SELECT user_id, name, message_count, created_at, updated_at 
              FROM users WHERE user_id = $1`

	var user User
	err := r.db.QueryRowContext(ctx, query, userID).Scan(
		&user.UserID,
		&user.Name,
		&user.MessageCount,
		&user.CreatedAt,
		&user.UpdatedAt,
	)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	return &user, nil
}

func (r *Repository) UpsertUser(ctx context.Context, user *User) error {
	query := `INSERT INTO users (user_id, name, message_count, updated_at)
              VALUES ($1, $2, $3, NOW())
              ON CONFLICT (user_id) 
              DO UPDATE SET 
                name = EXCLUDED.name,
                message_count = EXCLUDED.message_count,
                updated_at = NOW()`

	_, err := r.db.ExecContext(ctx, query, user.UserID, user.Name, user.MessageCount)
	return err
}

// Conversation methods (зашифрованные)

func (r *Repository) AddConversation(ctx context.Context, userID string, userMsg, assistantMsg string) error {
	// Получаем текущий индекс сообщения
	var maxIndex sql.NullInt64
	err := r.db.QueryRowContext(ctx,
		"SELECT COALESCE(MAX(message_index), -1) FROM conversations WHERE user_id = $1",
		userID).Scan(&maxIndex)
	if err != nil {
		return err
	}

	nextIndex := int(maxIndex.Int64) + 1

	// Шифруем сообщения
	encryptedUser, err := r.crypto.Encrypt(userMsg)
	if err != nil {
		return err
	}

	encryptedAssistant, err := r.crypto.Encrypt(assistantMsg)
	if err != nil {
		return err
	}

	query := `INSERT INTO conversations (user_id, message_index, encrypted_user_message, encrypted_assistant_message)
              VALUES ($1, $2, $3, $4)`

	_, err = r.db.ExecContext(ctx, query, userID, nextIndex, encryptedUser, encryptedAssistant)
	return err
}

func (r *Repository) GetConversations(ctx context.Context, userID string, limit int) ([]Message, error) {
	query := `SELECT encrypted_user_message, encrypted_assistant_message, created_at
              FROM conversations 
              WHERE user_id = $1 
              ORDER BY message_index DESC 
              LIMIT $2`

	rows, err := r.db.QueryContext(ctx, query, userID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var messages []Message
	for rows.Next() {
		var encryptedUser, encryptedAssistant string
		var createdAt time.Time

		if err := rows.Scan(&encryptedUser, &encryptedAssistant, &createdAt); err != nil {
			return nil, err
		}

		// Расшифровываем
		userMsg, err := r.crypto.Decrypt(encryptedUser)
		if err != nil {
			return nil, err
		}

		assistantMsg, err := r.crypto.Decrypt(encryptedAssistant)
		if err != nil {
			return nil, err
		}

		messages = append(messages, Message{
			User:      userMsg,
			Assistant: assistantMsg,
			Timestamp: createdAt,
		})
	}

	// Разворачиваем порядок (последние сообщения в конце)
	for i, j := 0, len(messages)-1; i < j; i, j = i+1, j-1 {
		messages[i], messages[j] = messages[j], messages[i]
	}

	return messages, nil
}

func (r *Repository) GetConversationCount(ctx context.Context, userID string) (int, error) {
	var count int
	err := r.db.QueryRowContext(ctx,
		"SELECT COUNT(*) FROM conversations WHERE user_id = $1",
		userID).Scan(&count)
	return count, err
}

// Summary methods (отдельная таблица)

func (r *Repository) GetCurrentSummary(ctx context.Context, userID string) (*Summary, error) {
	query := `SELECT id, user_id, summary_text, message_count_at_summary, created_at, updated_at, is_current
              FROM summaries 
              WHERE user_id = $1 AND is_current = TRUE
              ORDER BY updated_at DESC
              LIMIT 1`

	var summary Summary
	err := r.db.QueryRowContext(ctx, query, userID).Scan(
		&summary.ID,
		&summary.UserID,
		&summary.SummaryText,
		&summary.MessageCountAtSummary,
		&summary.CreatedAt,
		&summary.UpdatedAt,
		&summary.IsCurrent,
	)

	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	return &summary, nil
}

func (r *Repository) SaveSummary(ctx context.Context, userID string, summaryText string, messageCount int) error {
	// Сначала помечаем все старые суммаризации как неактивные
	_, err := r.db.ExecContext(ctx,
		"UPDATE summaries SET is_current = FALSE WHERE user_id = $1",
		userID)
	if err != nil {
		return err
	}

	// Сохраняем новую суммаризацию
	query := `INSERT INTO summaries (user_id, summary_text, message_count_at_summary, is_current)
              VALUES ($1, $2, $3, TRUE)`

	_, err = r.db.ExecContext(ctx, query, userID, summaryText, messageCount)
	return err
}

func (r *Repository) UpdateSummary(ctx context.Context, summaryID int, summaryText string) error {
	query := `UPDATE summaries 
              SET summary_text = $1, updated_at = NOW() 
              WHERE id = $2`

	_, err := r.db.ExecContext(ctx, query, summaryText, summaryID)
	return err
}

func (r *Repository) GetAllUserIDs(ctx context.Context) ([]string, error) {
	query := "SELECT user_id FROM users"
	rows, err := r.db.QueryContext(ctx, query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var userIDs []string
	for rows.Next() {
		var userID string
		if err := rows.Scan(&userID); err != nil {
			return nil, err
		}
		userIDs = append(userIDs, userID)
	}

	return userIDs, nil
}

func (r *Repository) Close() error {
	return r.db.Close()
}
