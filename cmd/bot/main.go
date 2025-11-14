package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"dr_mind_go/internal/config"
	"dr_mind_go/internal/handlers"
	"dr_mind_go/internal/scheduler"
	"dr_mind_go/internal/services"
	"dr_mind_go/pkg/telegram"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
	"github.com/sirupsen/logrus"
)

func main() {
	// Настраиваем логирование
	logrus.SetLevel(logrus.DebugLevel)
	logrus.SetFormatter(&logrus.JSONFormatter{})

	logrus.Info("Starting bot...")

	// Загружаем конфигурацию
	cfg, err := config.Load()
	if err != nil {
		logrus.WithError(err).Fatal("Failed to load config")
	}

	// Инициализируем Telegram клиент
	tgClient, err := telegram.New(cfg.BotToken)
	if err != nil {
		logrus.WithError(err).Fatal("Failed to create Telegram client")
	}

	// Инициализируем сервисы
	claudeService := services.NewClaudeService(cfg.ClaudeAPIKey, cfg.ClaudeModel)
	openaiService := services.NewOpenAIService(cfg.OpenAIAPIKey, cfg.TTSModel)
	posthogService := services.NewPosthogService(cfg.PosthogAPIKey)
	
	supabaseService, err := services.NewSupabaseService(cfg.SupabaseURL, cfg.SupabaseKey)
	if err != nil {
		logrus.WithError(err).Fatal("Failed to create Supabase service")
	}

	userService := services.NewUserService(supabaseService, claudeService, posthogService, cfg)

	// Инициализируем обработчики
	commandHandler := handlers.NewCommandHandler(tgClient, userService, posthogService, cfg)
	messageHandler := handlers.NewMessageHandler(tgClient, userService, openaiService, posthogService)
	audioHandler := handlers.NewAudioHandler(tgClient, userService, openaiService, posthogService)
	paymentHandler := handlers.NewPaymentHandler(tgClient, userService, posthogService)

	// Настраиваем команды бота
	err = setupBotCommands(tgClient, cfg)
	if err != nil {
		logrus.WithError(err).Error("Failed to setup bot commands")
	}

	// Настраиваем планировщик
	schedulerService := scheduler.New(tgClient, supabaseService, posthogService)
	err = schedulerService.Start()
	if err != nil {
		logrus.WithError(err).Error("Failed to start scheduler")
	}
	defer schedulerService.Stop()

	// Настраиваем graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Обрабатываем сигналы для graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		<-sigChan
		logrus.Info("Received shutdown signal")
		cancel()
	}()

	// Запускаем обработку обновлений
	logrus.Info("Starting polling...")
	updatesChan := tgClient.GetUpdatesChan()

	for {
		select {
		case <-ctx.Done():
			logrus.Info("Shutting down...")
			posthogService.Close()
			return

		case update := <-updatesChan:
			// Обрабатываем обновления в горутинах
			go func(update tgbotapi.Update) {
				if err := handleUpdate(ctx, update, tgClient, commandHandler, messageHandler, audioHandler, paymentHandler); err != nil {
					logrus.WithError(err).Error("Failed to handle update")
				}
			}(update)
		}
	}
}

func handleUpdate(ctx context.Context, update tgbotapi.Update, tgClient *telegram.Client, commandHandler *handlers.CommandHandler, messageHandler *handlers.MessageHandler, audioHandler *handlers.AudioHandler, paymentHandler *handlers.PaymentHandler) error {
	// Обрабатываем callback queries
	if update.CallbackQuery != nil {
		return commandHandler.HandleCallbackQuery(ctx, update)
	}

	// Обрабатываем pre-checkout queries
	if update.PreCheckoutQuery != nil {
		return paymentHandler.HandlePreCheckoutQuery(ctx, update)
	}

	// Обрабатываем сообщения
	if update.Message == nil {
		return nil
	}

	// Обрабатываем успешные платежи
	if update.Message.SuccessfulPayment != nil {
		return paymentHandler.HandleSuccessfulPayment(ctx, update)
	}

	// Обрабатываем команды
	if update.Message.IsCommand() {
		command := update.Message.Command()
		switch command {
		case "start":
			return commandHandler.HandleStart(ctx, update)
		case "help":
			return commandHandler.HandleHelp(ctx, update)
		case "startvoice":
			return commandHandler.HandleStartVoice(ctx, update)
		case "stopvoice":
			return commandHandler.HandleStopVoice(ctx, update)
		case "balance":
			return commandHandler.HandleBalance(ctx, update)
		case "buy":
			return commandHandler.HandleBuy(ctx, update)
		default:
			// Неизвестная команда
			msg := tgbotapi.NewMessage(update.Message.Chat.ID, "Извини, я не знаю такой команды. Используй /help чтобы увидеть список доступных команд 😊")
			_, err := tgClient.Bot.Send(msg)
			return err
		}
	}

	// Обрабатываем аудио сообщения
	if update.Message.Voice != nil || update.Message.Audio != nil || update.Message.VideoNote != nil {
		return audioHandler.HandleAudioMessage(ctx, update)
	}

	// Обрабатываем текстовые сообщения
	if update.Message.Text != "" {
		return messageHandler.HandleTextMessage(ctx, update)
	}

	// TODO: Обрабатываем изображения
	if len(update.Message.Photo) > 0 {
		logrus.Info("Photo message received (not implemented yet)")
		msg := tgbotapi.NewMessage(update.Message.Chat.ID, "Обработка изображений пока не реализована")
		_, err := tgClient.Bot.Send(msg)
		return err
	}

	return nil
}

func setupBotCommands(tgClient *telegram.Client, cfg *config.Config) error {
	// Команды для всех пользователей
	commands := []tgbotapi.BotCommand{
		{Command: "start", Description: "Начать диалог"},
		{Command: "help", Description: "Показать справку"},
		{Command: "balance", Description: "Проверить баланс сообщений"},
		{Command: "buy", Description: "Купить дополнительные сообщения"},
		{Command: "startvoice", Description: "Включить голосовой режим"},
		{Command: "stopvoice", Description: "Отключить голосовой режим"},
	}

	// Устанавливаем команды для всех пользователей
	err := tgClient.SetMyCommands(commands)
	if err != nil {
		return err
	}

	return nil
}