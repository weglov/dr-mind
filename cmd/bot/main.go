package main

import (
	"context"
	"dr_mind/internal/config"
	"dr_mind/internal/handlers"
	"dr_mind/internal/repository"
	"dr_mind/internal/scheduler"
	"dr_mind/internal/services"
	"dr_mind/pkg/telegram"
	"os"
	"os/signal"
	"syscall"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
	"github.com/sirupsen/logrus"
)

func main() {
	// Настраиваем логирование
	logrus.SetLevel(logrus.InfoLevel)
	logrus.SetFormatter(&logrus.TextFormatter{
		FullTimestamp: true,
	})

	logrus.Info("Starting bot...")

	// Загрузка конфигурации
	cfg, err := config.Load()
	if err != nil {
		logrus.WithError(err).Fatal("Failed to load config")
	}

	// Инициализация Telegram клиента
	tgClient, err := telegram.New(cfg.BotToken)
	if err != nil {
		logrus.WithError(err).Fatal("Failed to create Telegram client")
	}

	logrus.Infof("Authorized on account %s", tgClient.Bot.Self.UserName)

	// Инициализация репозитория
	repo, err := repository.NewRepository(cfg.DatabaseURL, cfg.EncryptionKey)
	if err != nil {
		logrus.WithError(err).Fatal("Failed to create repository")
	}
	defer repo.Close()

	// Инициализация сервисов
	claudeService := services.NewClaudeService(cfg.ClaudeAPIKey, cfg.ClaudeModel)
	userService := services.NewUserService(repo, claudeService)
	whisperService := services.NewWhisperService(cfg.OpenAIAPIKey)

	// Инициализация обработчиков
	commandHandler := handlers.NewCommandHandler(tgClient, userService, cfg)
	messageHandler := handlers.NewMessageHandler(tgClient, userService)
	audioHandler := handlers.NewAudioHandler(tgClient, userService, whisperService)

	// Инициализация планировщика
	sched := scheduler.NewScheduler(repo, tgClient)
	if err := sched.Start(); err != nil {
		logrus.WithError(err).Error("Failed to start scheduler")
	}
	defer sched.Stop()

	// Настраиваем команды бота
	if err := setupBotCommands(tgClient); err != nil {
		logrus.WithError(err).Error("Failed to setup bot commands")
	}

	// Graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		<-sigChan
		logrus.Info("Received shutdown signal")
		cancel()
	}()

	// Запуск polling
	logrus.Info("Starting polling...")
	u := tgbotapi.NewUpdate(0)
	u.Timeout = 60
	updates := tgClient.Bot.GetUpdatesChan(u)

	for {
		select {
		case <-ctx.Done():
			logrus.Info("Shutting down...")
			return
		case update := <-updates:
			go handleUpdate(ctx, update, commandHandler, messageHandler, audioHandler)
		}
	}
}

func handleUpdate(ctx context.Context, update tgbotapi.Update,
	commandHandler *handlers.CommandHandler,
	messageHandler *handlers.MessageHandler,
	audioHandler *handlers.AudioHandler) {

	// Обрабатываем callback queries
	if update.CallbackQuery != nil {
		if err := commandHandler.HandleCallbackQuery(ctx, update); err != nil {
			logrus.WithError(err).Error("Failed to handle callback query")
		}
		return
	}

	// Обрабатываем сообщения
	if update.Message == nil {
		return
	}

	// Обрабатываем команды
	if update.Message.IsCommand() {
		if err := commandHandler.HandleCommand(ctx, update); err != nil {
			logrus.WithError(err).Error("Failed to handle command")
		}
		return
	}

	// Обрабатываем текстовые сообщения
	if update.Message.Text != "" {
		if err := messageHandler.HandleTextMessage(ctx, update); err != nil {
			logrus.WithError(err).Error("Failed to handle text message")
		}
		return
	}

	// Обрабатываем аудио сообщения
	if update.Message.Voice != nil || update.Message.Audio != nil || update.Message.VideoNote != nil {
		if err := audioHandler.HandleAudioMessage(ctx, update); err != nil {
			logrus.WithError(err).Error("Failed to handle audio message")
		}
		return
	}
}

func setupBotCommands(tgClient *telegram.Client) error {
	commands := []tgbotapi.BotCommand{
		{Command: "start", Description: "Начать диалог"},
		{Command: "help", Description: "Показать справку"},
		{Command: "supervisor", Description: "Переключить режим супервизора"},
	}

	cmdConfig := tgbotapi.NewSetMyCommands(commands...)
	_, err := tgClient.Bot.Request(cmdConfig)
	return err
}
