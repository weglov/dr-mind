package handlers

import (
	"context"
	"dr_mind/internal/services"
	"dr_mind/pkg/telegram"
	"fmt"
	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

type MessageHandler struct {
	tgClient    *telegram.Client
	userService *services.UserService
}

func NewMessageHandler(tgClient *telegram.Client, userService *services.UserService) *MessageHandler {
	return &MessageHandler{
		tgClient:    tgClient,
		userService: userService,
	}
}

func (h *MessageHandler) HandleTextMessage(ctx context.Context, update tgbotapi.Update) error {
	if update.Message == nil || update.Message.Text == "" {
		return nil
	}

	userID := update.Message.From.ID
	chatID := update.Message.Chat.ID
	firstName := update.Message.From.FirstName
	messageText := update.Message.Text

	// Инициализируем пользователя если нужно
	err := h.userService.InitializeUser(ctx, fmt.Sprintf("%d", userID), firstName)
	if err != nil {
		return fmt.Errorf("failed to initialize user: %w", err)
	}

	// Показываем что печатаем
	_, err = h.tgClient.Bot.Send(tgbotapi.NewChatAction(chatID, "typing"))
	if err != nil {
		// Игнорируем ошибку
	}

	// Обрабатываем сообщение
	response, err := h.userService.ProcessMessage(ctx, fmt.Sprintf("%d", userID), messageText)
	if err != nil {
		// Проверяем на нерелевантный запрос
		errStr := err.Error()
		if len(errStr) > 11 && errStr[:11] == "irrelevant:" {
			explanation := errStr[12:]
			reply := "Извините, но я могу помочь только с вопросами, связанными с психологической помощью и ментальным здоровьем. " + explanation
			return h.tgClient.SendMessagePlain(chatID, reply)
		}

		return fmt.Errorf("failed to process message: %w", err)
	}

	// Отправляем ответ
	return h.tgClient.SendMessage(chatID, response)
}
