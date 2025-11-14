package services

import (
	"context"
	"dr_mind/internal/repository"
	"fmt"
	"strings"
	"time"
)

const (
	MinMessagesForSummary = 5
	SummaryUpdateInterval  = 15
	MaxSummaryAge          = 7 * 24 * time.Hour
	MaxHistoryForSummary   = 20
)

type SummarizerService struct {
	claude *ClaudeService
	repo   *repository.Repository
}

func NewSummarizerService(claude *ClaudeService, repo *repository.Repository) *SummarizerService {
	return &SummarizerService{
		claude: claude,
		repo:   repo,
	}
}

// ShouldSummarize проверяет, нужно ли делать суммаризацию
func (s *SummarizerService) ShouldSummarize(ctx context.Context, userID string, messageCount int) (bool, string) {
	// 1. Если сообщений меньше минимума - не нужно
	if messageCount < MinMessagesForSummary {
		return false, "not_enough_messages"
	}

	// 2. Получаем текущую суммаризацию
	summary, err := s.repo.GetCurrentSummary(ctx, userID)
	if err != nil {
		return false, fmt.Sprintf("error: %v", err)
	}

	// 3. Если суммаризации нет - нужно создать
	if summary == nil {
		return true, "no_summary"
	}

	// 4. Проверяем возраст суммаризации
	if time.Since(summary.UpdatedAt) > MaxSummaryAge {
		return true, "summary_too_old"
	}

	// 5. Подсчитываем новые сообщения с момента последней суммаризации
	newMessages := messageCount - summary.MessageCountAtSummary
	if newMessages >= SummaryUpdateInterval {
		return true, "new_messages_threshold"
	}

	return false, "not_needed"
}

// IncrementalSummarize делает инкрементальную суммаризацию
func (s *SummarizerService) IncrementalSummarize(ctx context.Context, userID string, messageCount int) (string, error) {
	// Получаем текущую суммаризацию
	currentSummary, err := s.repo.GetCurrentSummary(ctx, userID)
	if err != nil {
		return "", err
	}

	// Получаем историю переписок
	history, err := s.repo.GetConversations(ctx, userID, MaxHistoryForSummary)
	if err != nil {
		return "", err
	}

	// Если суммаризации нет - делаем полную
	if currentSummary == nil {
		return s.createFullSummary(ctx, userID, history, messageCount)
	}

	// Иначе - инкрементальная (обновляем существующую)
	return s.updateSummary(ctx, userID, currentSummary, history, messageCount)
}

// createFullSummary создает полную суммаризацию с нуля
func (s *SummarizerService) createFullSummary(ctx context.Context, userID string, history []repository.Message, messageCount int) (string, error) {
	historyText := s.formatHistory(history)

	prompt := `Ты - эксперт по анализу терапевтических диалогов. 
Создай краткое, но информативное резюме о пользователе на основе этого диалога.

Сфокусируйся на:
- Ключевых проблемах и темах, которые поднимает пользователь
- Эмоциональных паттернах и состояниях
- Важных жизненных обстоятельствах
- Прогрессе и изменениях (если есть)

Формат: структурированное резюме (2-3 абзаца).

Диалог:
` + historyText

	summary, err := s.claude.GenerateResponse(ctx, []Message{
		{Role: "user", Content: prompt},
	}, "Ты эксперт по анализу терапевтических диалогов.")

	if err != nil {
		return "", err
	}

	// Сохраняем в БД
	err = s.repo.SaveSummary(ctx, userID, summary, messageCount)
	if err != nil {
		return "", err
	}

	return summary, nil
}

// updateSummary обновляет существующую суммаризацию новыми данными
func (s *SummarizerService) updateSummary(ctx context.Context, userID string, currentSummary *repository.Summary, history []repository.Message, messageCount int) (string, error) {
	// Получаем только новые сообщения (после последней суммаризации)
	newMessages := s.getNewMessages(history, currentSummary.UpdatedAt)

	if len(newMessages) == 0 {
		return currentSummary.SummaryText, nil
	}

	newHistoryText := s.formatHistory(newMessages)

	prompt := `У тебя есть существующее резюме о пользователе и новые сообщения из диалога.

Твоя задача: обновить резюме, добавив новую информацию, но сохранив важные детали из старого резюме.

Существующее резюме:
` + currentSummary.SummaryText + `

Новые сообщения:
` + newHistoryText + `

Обнови резюме, учитывая:
- Новые темы и проблемы
- Изменения в эмоциональном состоянии
- Прогресс или регресс
- Новые важные обстоятельства

Сохрани структуру и важные детали из старого резюме, но добавь новую информацию.`

	updatedSummary, err := s.claude.GenerateResponse(ctx, []Message{
		{Role: "user", Content: prompt},
	}, "Ты эксперт по обновлению терапевтических резюме.")

	if err != nil {
		return "", err
	}

	// Обновляем существующую суммаризацию
	err = s.repo.UpdateSummary(ctx, currentSummary.ID, updatedSummary)
	if err != nil {
		return "", err
	}

	return updatedSummary, nil
}

// Вспомогательные функции

func (s *SummarizerService) getNewMessages(history []repository.Message, since time.Time) []repository.Message {
	var newMessages []repository.Message
	for _, msg := range history {
		if msg.Timestamp.After(since) {
			newMessages = append(newMessages, msg)
		}
	}
	return newMessages
}

func (s *SummarizerService) formatHistory(messages []repository.Message) string {
	var parts []string
	for _, msg := range messages {
		if msg.User != "" {
			parts = append(parts, "User: "+msg.User)
		}
		if msg.Assistant != "" {
			parts = append(parts, "Assistant: "+msg.Assistant)
		}
	}
	return strings.Join(parts, "\n\n")
}
