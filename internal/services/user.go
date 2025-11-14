package services

import (
	"context"
	"dr_mind/internal/prompts"
	"dr_mind/internal/repository"
	"fmt"
	"strings"
)

type UserService struct {
	repo       *repository.Repository
	claude     *ClaudeService
	summarizer *SummarizerService
}

func NewUserService(repo *repository.Repository, claude *ClaudeService) *UserService {
	return &UserService{
		repo:       repo,
		claude:     claude,
		summarizer: NewSummarizerService(claude, repo),
	}
}

func (s *UserService) InitializeUser(ctx context.Context, userID, firstName string) error {
	user, err := s.repo.GetUser(ctx, userID)
	if err != nil {
		return err
	}

	if user == nil {
		// Создаем нового пользователя
		newUser := &repository.User{
			UserID:       userID,
			Name:         firstName,
			MessageCount: 0,
		}
		return s.repo.UpsertUser(ctx, newUser)
	}

	return nil
}

func (s *UserService) ProcessMessage(ctx context.Context, userID, message string) (string, error) {
	// 1. Получить пользователя
	user, err := s.repo.GetUser(ctx, userID)
	if err != nil {
		return "", err
	}

	if user == nil {
		return "", fmt.Errorf("user not found")
	}

	// 2. Получить историю для контекста
	history, err := s.repo.GetConversations(ctx, userID, 10)
	if err != nil {
		return "", err
	}

	// 3. Проверить релевантность
	contextText := s.getContext(history)
	isRelevant, explanation, err := s.claude.CheckRelevance(ctx, message, contextText)
	if err != nil {
		return "", fmt.Errorf("failed to check relevance: %w", err)
	}

	if !isRelevant {
		return "", fmt.Errorf("irrelevant: %s", explanation)
	}

	// 4. Проверить нужна ли суммаризация
	messageCount, err := s.repo.GetConversationCount(ctx, userID)
	if err != nil {
		return "", err
	}

	shouldSummarize, _ := s.summarizer.ShouldSummarize(ctx, userID, messageCount)
	if shouldSummarize {
		_, err := s.summarizer.IncrementalSummarize(ctx, userID, messageCount)
		if err != nil {
			// Логируем ошибку, но продолжаем
			fmt.Printf("Summary error: %v\n", err)
		}
	}

	// 5. Получить текущую суммаризацию для промпта
	summary, err := s.repo.GetCurrentSummary(ctx, userID)
	if err != nil {
		return "", err
	}

	// 6. Формируем промпт с суммаризацией
	systemPrompt := prompts.TherapistPrompt
	if summary != nil && summary.SummaryText != "" {
		systemPrompt += "\n\nКраткое резюме о пользователе:\n" + summary.SummaryText
	}

	// 7. Форматируем сообщения для Claude
	messages := s.formatMessages(history, message)

	// 8. Отправляем в Claude
	response, err := s.claude.GenerateResponse(ctx, messages, systemPrompt)
	if err != nil {
		return "", err
	}

	// 9. Сохраняем в историю (зашифрованную)
	err = s.repo.AddConversation(ctx, userID, message, response)
	if err != nil {
		return "", err
	}

	// 10. Обновляем счетчик сообщений
	user.MessageCount++
	err = s.repo.UpsertUser(ctx, user)
	if err != nil {
		return "", err
	}

	return response, nil
}

func (s *UserService) getContext(history []repository.Message) string {
	if len(history) == 0 {
		return ""
	}

	// Берем последние 3 сообщения для контекста
	recent := history
	if len(history) > 3 {
		recent = history[len(history)-3:]
	}

	var parts []string
	for _, msg := range recent {
		if msg.User != "" {
			parts = append(parts, "User: "+msg.User)
		}
		if msg.Assistant != "" {
			parts = append(parts, "Assistant: "+msg.Assistant)
		}
	}

	return strings.Join(parts, "\n")
}

func (s *UserService) formatMessages(history []repository.Message, currentMessage string) []Message {
	var messages []Message

	// Добавляем историю
	for _, msg := range history {
		if msg.User != "" {
			messages = append(messages, Message{
				Role:    "user",
				Content: msg.User,
			})
		}
		if msg.Assistant != "" {
			messages = append(messages, Message{
				Role:    "assistant",
				Content: msg.Assistant,
			})
		}
	}

	// Добавляем текущее сообщение
	messages = append(messages, Message{
		Role:    "user",
		Content: currentMessage,
	})

	return messages
}
