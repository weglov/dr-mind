package services

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/sirupsen/logrus"
)

type TranscriptionService struct {
	apiKey string
	model  string
	client *http.Client
	apiURL string
}

type openRouterResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error,omitempty"`
}

func NewWhisperService(apiKey, model string) *TranscriptionService {
	return &TranscriptionService{
		apiKey: apiKey,
		model:  model,
		client: &http.Client{
			Timeout: 120 * time.Second,
		},
		apiURL: "https://openrouter.ai/api/v1/chat/completions",
	}
}

// Transcribe транскрибирует аудио файл в текст через OpenRouter API
func (s *TranscriptionService) Transcribe(ctx context.Context, audioFilePath string) (string, error) {
	if s.apiKey == "" {
		return "", fmt.Errorf("OpenRouter API key is not configured")
	}

	// Читаем файл
	audioData, err := os.ReadFile(audioFilePath)
	if err != nil {
		return "", fmt.Errorf("failed to read audio file: %w", err)
	}

	// Кодируем в base64
	base64Audio := base64.StdEncoding.EncodeToString(audioData)

	// Определяем MIME тип по расширению
	ext := strings.TrimPrefix(filepath.Ext(audioFilePath), ".")
	mimeType := mapAudioMimeType(ext)

	logrus.WithFields(logrus.Fields{
		"model":     s.model,
		"mime_type": mimeType,
		"file_size": len(audioData),
		"file_path": audioFilePath,
	}).Info("Transcribing audio")

	// Формируем запрос в формате Gemini (inline_data)
	reqBody := map[string]interface{}{
		"model": s.model,
		"messages": []map[string]interface{}{
			{
				"role": "user",
				"content": []map[string]interface{}{
					{
						"type": "text",
						"text": "Прослушай аудио и напиши только слова, которые произнёс человек. Ничего больше - только транскрипцию речи.",
					},
					{
						"type": "file",
						"file": map[string]string{
							"filename":   filepath.Base(audioFilePath),
							"file_data":  "data:" + mimeType + ";base64," + base64Audio,
						},
					},
				},
			},
		},
	}

	jsonBody, err := json.Marshal(reqBody)
	if err != nil {
		return "", fmt.Errorf("failed to marshal request: %w", err)
	}

	// Создаем запрос
	req, err := http.NewRequestWithContext(ctx, "POST", s.apiURL, bytes.NewReader(jsonBody))
	if err != nil {
		return "", fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+s.apiKey)

	// Выполняем запрос
	resp, err := s.client.Do(req)
	if err != nil {
		return "", fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		logrus.WithFields(logrus.Fields{
			"status": resp.StatusCode,
			"body":   string(body),
		}).Error("OpenRouter API error")
		return "", fmt.Errorf("OpenRouter API error: %d - %s", resp.StatusCode, string(body))
	}

	logrus.WithField("response", string(body)).Debug("OpenRouter response")

	// Парсим ответ
	var openRouterResp openRouterResponse
	if err := json.Unmarshal(body, &openRouterResp); err != nil {
		return "", fmt.Errorf("failed to decode response: %w", err)
	}

	if openRouterResp.Error != nil {
		return "", fmt.Errorf("OpenRouter API error: %s", openRouterResp.Error.Message)
	}

	if len(openRouterResp.Choices) == 0 {
		return "", fmt.Errorf("no transcription in response")
	}

	transcribedText := strings.TrimSpace(openRouterResp.Choices[0].Message.Content)
	logrus.WithField("transcribed_text", transcribedText).Info("Transcription result")

	return transcribedText, nil
}

// mapAudioMimeType преобразует расширение файла в MIME тип
func mapAudioMimeType(ext string) string {
	switch strings.ToLower(ext) {
	case "ogg", "oga":
		return "audio/ogg"
	case "mp3":
		return "audio/mp3"
	case "wav":
		return "audio/wav"
	case "m4a":
		return "audio/m4a"
	case "aac":
		return "audio/aac"
	case "flac":
		return "audio/flac"
	case "mp4":
		return "audio/mp4"
	case "webm":
		return "audio/webm"
	default:
		return "audio/ogg"
	}
}
