package handlers

import (
	"context"
	"dr_mind/internal/services"
	"dr_mind/pkg/telegram"
	"fmt"
	"io"
	"net/http"
	"os"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
	"github.com/sirupsen/logrus"
)

type AudioHandler struct {
	tgClient             *telegram.Client
	userService          *services.UserService
	transcriptionService *services.TranscriptionService
}

func NewAudioHandler(tgClient *telegram.Client, userService *services.UserService, transcriptionService *services.TranscriptionService) *AudioHandler {
	return &AudioHandler{
		tgClient:             tgClient,
		userService:          userService,
		transcriptionService: transcriptionService,
	}
}

func (h *AudioHandler) HandleAudioMessage(ctx context.Context, update tgbotapi.Update) error {
	if update.Message == nil {
		return nil
	}

	userID := update.Message.From.ID
	chatID := update.Message.Chat.ID
	firstName := update.Message.From.FirstName

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

	// Определяем тип файла и получаем file_id
	var fileID string
	var localFilePath string

	if update.Message.Voice != nil {
		fileID = update.Message.Voice.FileID
		localFilePath = fmt.Sprintf("audio_%d.ogg", userID)
	} else if update.Message.Audio != nil {
		fileID = update.Message.Audio.FileID
		localFilePath = fmt.Sprintf("audio_%d.ogg", userID)
	} else if update.Message.VideoNote != nil {
		fileID = update.Message.VideoNote.FileID
		localFilePath = fmt.Sprintf("video_%d.mp4", userID)
	} else {
		return fmt.Errorf("unsupported audio type")
	}

	logrus.WithFields(logrus.Fields{
		"file_id":   fileID,
		"user_id":   userID,
		"file_path": localFilePath,
	}).Info("Downloading audio file")

	// Скачиваем файл
	file, err := h.tgClient.Bot.GetFile(tgbotapi.FileConfig{FileID: fileID})
	if err != nil {
		return fmt.Errorf("failed to get file: %w", err)
	}

	logrus.WithField("telegram_file_path", file.FilePath).Info("Got file info from Telegram")

	// Скачиваем файл локально через HTTP
	fileURL := file.Link(h.tgClient.Bot.Token)
	httpClient := &http.Client{}
	resp, err := httpClient.Get(fileURL)
	if err != nil {
		return fmt.Errorf("failed to download file: %w", err)
	}
	defer resp.Body.Close()

	// Сохраняем во временный файл
	outFile, err := os.Create(localFilePath)
	if err != nil {
		return fmt.Errorf("failed to create file: %w", err)
	}
	defer outFile.Close()
	defer os.Remove(localFilePath) // Удаляем после использования

	written, err := io.Copy(outFile, resp.Body)
	if err != nil {
		return fmt.Errorf("failed to save file: %w", err)
	}

	logrus.WithField("bytes_written", written).Info("Audio file saved")

	// Закрываем файл перед транскрибацией
	outFile.Close()

	// Транскрибируем аудио в текст
	if h.transcriptionService == nil {
		reply := "Извините, обработка голосовых сообщений недоступна. Пожалуйста, отправьте ваше сообщение текстом."
		return h.tgClient.SendMessagePlain(chatID, reply)
	}

	transcribedText, err := h.transcriptionService.Transcribe(ctx, localFilePath)
	if err != nil {
		return fmt.Errorf("failed to transcribe audio: %w", err)
	}

	if transcribedText == "" {
		reply := "Не удалось распознать текст в голосовом сообщении. Пожалуйста, попробуйте еще раз или отправьте сообщение текстом."
		return h.tgClient.SendMessagePlain(chatID, reply)
	}

	// Обрабатываем транскрибированный текст как обычное текстовое сообщение
	response, err := h.userService.ProcessMessage(ctx, fmt.Sprintf("%d", userID), transcribedText)
	if err != nil {
		// Проверяем на нерелевантный запрос
		errStr := err.Error()
		if len(errStr) > 11 && errStr[:11] == "irrelevant:" {
			explanation := errStr[12:]
			reply := "Извините, но я могу помочь только с вопросами, связанными с психологической помощью и ментальным здоровьем. " + explanation
			return h.tgClient.SendMessagePlain(chatID, reply)
		}

		return fmt.Errorf("failed to process transcribed message: %w", err)
	}

	// Отправляем ответ
	return h.tgClient.SendMessage(chatID, response)
}
