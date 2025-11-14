package services

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"time"
)

type WhisperService struct {
	apiKey string
	client *http.Client
	apiURL string
}

type WhisperResponse struct {
	Text string `json:"text"`
}

func NewWhisperService(apiKey string) *WhisperService {
	return &WhisperService{
		apiKey: apiKey,
		client: &http.Client{
			Timeout: 60 * time.Second,
		},
		apiURL: "https://api.openai.com/v1/audio/transcriptions",
	}
}

// Transcribe транскрибирует аудио файл в текст
func (s *WhisperService) Transcribe(ctx context.Context, audioFilePath string) (string, error) {
	if s.apiKey == "" {
		return "", fmt.Errorf("OpenAI API key is not configured")
	}

	// Открываем файл
	file, err := os.Open(audioFilePath)
	if err != nil {
		return "", fmt.Errorf("failed to open audio file: %w", err)
	}
	defer file.Close()

	// Создаем multipart form
	var requestBody bytes.Buffer
	writer := multipart.NewWriter(&requestBody)

	// Добавляем файл
	part, err := writer.CreateFormFile("file", audioFilePath)
	if err != nil {
		return "", fmt.Errorf("failed to create form file: %w", err)
	}
	_, err = io.Copy(part, file)
	if err != nil {
		return "", fmt.Errorf("failed to copy file: %w", err)
	}

	// Добавляем модель
	err = writer.WriteField("model", "whisper-1")
	if err != nil {
		return "", fmt.Errorf("failed to write model field: %w", err)
	}

	// Добавляем язык (опционально, можно определить автоматически)
	// err = writer.WriteField("language", "ru")
	// if err != nil {
	// 	return "", fmt.Errorf("failed to write language field: %w", err)
	// }

	err = writer.Close()
	if err != nil {
		return "", fmt.Errorf("failed to close writer: %w", err)
	}

	// Создаем запрос
	req, err := http.NewRequestWithContext(ctx, "POST", s.apiURL, &requestBody)
	if err != nil {
		return "", fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("Authorization", "Bearer "+s.apiKey)

	// Выполняем запрос
	resp, err := s.client.Do(req)
	if err != nil {
		return "", fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("whisper API error: %d - %s", resp.StatusCode, string(body))
	}

	// Парсим ответ
	var whisperResp WhisperResponse
	if err := json.NewDecoder(resp.Body).Decode(&whisperResp); err != nil {
		return "", fmt.Errorf("failed to decode response: %w", err)
	}

	return whisperResp.Text, nil
}

