package handlers

import (
	"context"
	"dr_mind/internal/config"
	"dr_mind/internal/services"
	"dr_mind/pkg/telegram"
	"fmt"
	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

const (
	WelcomeMessage = `Привет! 👋 

Я *Mindy*, и я буду твоим личным помощником и другом в мире психологии!

Что я умею? Да много всего! 🌟
• Поддержу в любой ситуации (честно-честно!)
• Помогу разложить мысли по полочкам
• Подскажу, как справиться с проблемой
• Научу классным техникам против стресса

Хотя я и не настоящий психолог, я знаю много крутых инструментов и техник, которые реально помогают.
А ещё я всегда онлайн и готова прийти на помощь в любое время суток, даже ночью в 3 утра! 

Давай попробуем подружиться? У тебя есть *30 бесплатных* ознакомительных сообщений 🎁`

	HelpMessage = `Отлично! 😊

Я понимаю разные форматы сообщений:
• *Текст* 💬
• *Голосовые сообщения* 🗣️
• *Фотографии* 📸
• *Видео-кружки* 🎥
• *Аудиосообщения* 🎤

Пиши или отправляй что удобно - я всегда пойму тебя!`
)

type CommandHandler struct {
	tgClient   *telegram.Client
	userService *services.UserService
	cfg        *config.Config
}

func NewCommandHandler(tgClient *telegram.Client, userService *services.UserService, cfg *config.Config) *CommandHandler {
	return &CommandHandler{
		tgClient:    tgClient,
		userService: userService,
		cfg:         cfg,
	}
}

func (h *CommandHandler) HandleCommand(ctx context.Context, update tgbotapi.Update) error {
	if update.Message == nil || !update.Message.IsCommand() {
		return nil
	}

	command := update.Message.Command()
	userID := update.Message.From.ID
	chatID := update.Message.Chat.ID

	switch command {
	case "start":
		return h.HandleStart(ctx, userID, chatID, update.Message.From.FirstName)
	case "help":
		return h.HandleHelp(ctx, chatID)
	case "supervisor":
		return h.HandleSupervisor(ctx, userID, chatID)
	default:
		msg := tgbotapi.NewMessage(chatID, "Извини, я не знаю такой команды. Используй /help чтобы увидеть список доступных команд 😊")
		_, err := h.tgClient.Bot.Send(msg)
		return err
	}
}

func (h *CommandHandler) HandleStart(ctx context.Context, userID int64, chatID int64, firstName string) error {
	// Инициализируем пользователя
	err := h.userService.InitializeUser(ctx, fmt.Sprintf("%d", userID), firstName)
	if err != nil {
		return fmt.Errorf("failed to initialize user: %w", err)
	}

	// Создаем кнопку
	keyboard := tgbotapi.NewInlineKeyboardMarkup(
		tgbotapi.NewInlineKeyboardRow(
			tgbotapi.NewInlineKeyboardButtonData("Привет, Mindy!", "hello_mindy"),
		),
	)

	msg := tgbotapi.NewMessage(chatID, WelcomeMessage)
	msg.ParseMode = "Markdown"
	msg.DisableWebPagePreview = true
	msg.ReplyMarkup = keyboard

	_, err = h.tgClient.Bot.Send(msg)
	return err
}

func (h *CommandHandler) HandleHelp(ctx context.Context, chatID int64) error {
	msg := tgbotapi.NewMessage(chatID, HelpMessage)
	msg.ParseMode = "Markdown"
	msg.DisableWebPagePreview = true
	_, err := h.tgClient.Bot.Send(msg)
	return err
}

func (h *CommandHandler) HandleSupervisor(ctx context.Context, userID int64, chatID int64) error {
	isSupervisor, err := h.userService.ToggleSupervisorMode(ctx, fmt.Sprintf("%d", userID))
	if err != nil {
		return fmt.Errorf("failed to toggle supervisor mode: %w", err)
	}

	var text string
	if isSupervisor {
		text = "👩‍⚕️ *Режим супервизора включен!*\n\nТеперь я готова обсуждать ваши профессиональные кейсы, анализировать перенос/контрперенос и помогать в сложных терапевтических ситуациях.\n\nРасскажите о случае, который вас беспокоит."
	} else {
		text = "🧘‍♀️ *Режим супервизора выключен.*\n\nВозвращаюсь к роли вашего поддерживающего собеседника Минди. О чем хотите поговорить?"
	}

	msg := tgbotapi.NewMessage(chatID, text)
	msg.ParseMode = "Markdown"
	_, err = h.tgClient.Bot.Send(msg)
	return err
}

func (h *CommandHandler) HandleCallbackQuery(ctx context.Context, update tgbotapi.Update) error {
	if update.CallbackQuery == nil {
		return nil
	}

	callback := update.CallbackQuery
	chatID := callback.Message.Chat.ID

	if callback.Data == "hello_mindy" {
		callbackConfig := tgbotapi.NewCallback(callback.ID, "")
		_, err := h.tgClient.Bot.Request(callbackConfig)
		if err != nil {
			return err
		}

		msg := tgbotapi.NewMessage(chatID, HelpMessage)
		msg.ParseMode = "Markdown"
		msg.DisableWebPagePreview = true
		_, err = h.tgClient.Bot.Send(msg)
		return err
	}

	return nil
}
