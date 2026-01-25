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
)

type TranscriptionService struct {
	apiKey string
	model  string
	client *http.Client
	apiURL string
}

type openRouterRequest struct {
	Model    string          `json:"model"`
	Messages []openRouterMsg `json:"messages"`
}

type openRouterMsg struct {
	Role    string        `json:"role"`
	Content []contentPart `json:"content"`
}

type contentPart struct {
	Type       string      `json:"type"`
	Text       string      `json:"text,omitempty"`
	InputAudio *inputAudio `json:"input_audio,omitempty"`
}

type inputAudio struct {
	Data   string `json:"data"`
	Format string `json:"format"`
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

	// Определяем формат по расширению
	ext := strings.TrimPrefix(filepath.Ext(audioFilePath), ".")
	format := mapAudioFormat(ext)

	// Формируем запрос
	reqBody := openRouterRequest{
		Model: s.model,
		Messages: []openRouterMsg{
			{
				Role: "user",
				Content: []contentPart{
					{
						Type: "text",
						Text: "Transcribe the following audio file. Return ONLY the transcribed text, nothing else. No explanations, no formatting, just the exact words spoken in the audio.",
					},
					{
						Type: "input_audio",
						InputAudio: &inputAudio{
							Data:   base64Audio,
							Format: format,
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
		return "", fmt.Errorf("OpenRouter API error: %d - %s", resp.StatusCode, string(body))
	}

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

	return strings.TrimSpace(openRouterResp.Choices[0].Message.Content), nil
}

// mapAudioFormat преобразует расширение файла в формат для OpenRouter
func mapAudioFormat(ext string) string {
	switch strings.ToLower(ext) {
	case "ogg", "oga":
		return "ogg"
	case "mp3":
		return "mp3"
	case "wav":
		return "wav"
	case "m4a":
		return "m4a"
	case "aac":
		return "aac"
	case "flac":
		return "flac"
	case "mp4":
		return "m4a" // video notes в telegram - mp4, но аудио обычно m4a
	default:
		return "ogg" // default для voice messages в Telegram
	}
}
