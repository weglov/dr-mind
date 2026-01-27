package services

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type ClaudeRequest struct {
	Model       string    `json:"model"`
	MaxTokens   int       `json:"max_tokens"`
	Temperature float64   `json:"temperature"`
	System      string    `json:"system,omitempty"`
	Messages    []Message `json:"messages"`
}

type ClaudeResponse struct {
	Content []struct {
		Type string `json:"type"`
		Text string `json:"text"`
	} `json:"content"`
}

type ClaudeService struct {
	apiKey string
	model  string
	client *http.Client
	apiURL string
}

func NewClaudeService(apiKey, model string) *ClaudeService {
	return &ClaudeService{
		apiKey: apiKey,
		model:  model,
		client: &http.Client{
			Timeout: 60 * time.Second,
		},
		apiURL: "https://api.anthropic.com/v1/messages",
	}
}

func (s *ClaudeService) GenerateResponse(ctx context.Context, messages []Message, systemPrompt string) (string, error) {
	reqBody := ClaudeRequest{
		Model:       s.model,
		MaxTokens:   1024,
		Temperature: 0.7,
		Messages:    messages,
	}

	if systemPrompt != "" {
		reqBody.System = systemPrompt
	}

	jsonData, err := json.Marshal(reqBody)
	if err != nil {
		return "", fmt.Errorf("failed to marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, "POST", s.apiURL, bytes.NewBuffer(jsonData))
	if err != nil {
		return "", fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-api-key", s.apiKey)
	req.Header.Set("anthropic-version", "2023-06-01")

	resp, err := s.client.Do(req)
	if err != nil {
		return "", fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("claude API error: %d - %s", resp.StatusCode, string(body))
	}

	var claudeResp ClaudeResponse
	if err := json.NewDecoder(resp.Body).Decode(&claudeResp); err != nil {
		return "", fmt.Errorf("failed to decode response: %w", err)
	}

	if len(claudeResp.Content) == 0 {
		return "", fmt.Errorf("empty response from Claude")
	}

	return claudeResp.Content[0].Text, nil
}

func (s *ClaudeService) CheckRelevance(ctx context.Context, message string, context string) (bool, string, error) {
	var prompt string
	if context != "" {
		prompt = fmt.Sprintf(`Контекст предыдущего диалога:
%s

Определи, является ли следующий запрос психологическим или связанным с ментальным здоровьем.

Запрос: "%s"

Ответь только "yes" если запрос релевантный (включая уточняющие вопросы по предыдущему психологическому контексту), 
или "no" с кратким объяснением, почему запрос не относится к психологической помощи.`, context, message)
	} else {
		prompt = fmt.Sprintf(`Определи, является ли следующий запрос психологическим или связанным с ментальным здоровьем.

Запрос: "%s"

Ответь только "yes" если запрос релевантный, или "no" с кратким объяснением.`, message)
	}

	response, err := s.GenerateResponse(ctx, []Message{
		{Role: "user", Content: prompt},
	}, "Ты эксперт по определению психологических запросов. Твоя задача - определить, является ли запрос пользователя связанным с психологической помощью, психотерапией, ментальным здоровьем или личностным развитием. Учитывай контекст предыдущего диалога, если он есть, если пользователь благодарит или его сообщение связанно с предыдущим контекстом то отвечай yes")

	if err != nil {
		return false, "", err
	}

	cleanedResponse := strings.TrimSpace(strings.ToLower(response))
	cleanedResponse = strings.Trim(cleanedResponse, "*")
	cleanedResponse = strings.TrimSpace(cleanedResponse)

	isRelevant := strings.HasPrefix(cleanedResponse, "yes")
	return isRelevant, response, nil
}
