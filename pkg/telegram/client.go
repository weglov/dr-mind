package telegram

import (
	"fmt"
	"strings"
	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

const maxMessageLength = 4096

type Client struct {
	Bot *tgbotapi.BotAPI
}

func New(botToken string) (*Client, error) {
	bot, err := tgbotapi.NewBotAPI(botToken)
	if err != nil {
		return nil, fmt.Errorf("failed to create bot: %w", err)
	}

	return &Client{
		Bot: bot,
	}, nil
}

// splitMessage splits a long message into chunks that fit within Telegram's limit
// It tries to split at sentence boundaries (., !, ?) or paragraph boundaries (\n\n)
// If that's not possible, it splits at the character limit
func splitMessage(text string, maxLen int) []string {
	if len(text) <= maxLen {
		return []string{text}
	}

	var chunks []string
	remaining := text

	for len(remaining) > maxLen {
		// Try to find a good split point
		chunk := remaining[:maxLen]
		
		// Try to split at paragraph boundary
		if idx := strings.LastIndex(chunk, "\n\n"); idx > maxLen/2 {
			chunks = append(chunks, remaining[:idx+2])
			remaining = remaining[idx+2:]
			continue
		}
		
		// Try to split at sentence boundary
		sentenceEndings := []string{". ", "! ", "? ", ".\n", "!\n", "?\n"}
		bestIdx := -1
		for _, ending := range sentenceEndings {
			if idx := strings.LastIndex(chunk, ending); idx > maxLen/2 && (bestIdx == -1 || idx > bestIdx) {
				bestIdx = idx + len(ending)
			}
		}
		
		if bestIdx > 0 {
			chunks = append(chunks, remaining[:bestIdx])
			remaining = remaining[bestIdx:]
			continue
		}
		
		// Try to split at newline
		if idx := strings.LastIndex(chunk, "\n"); idx > maxLen/2 {
			chunks = append(chunks, remaining[:idx+1])
			remaining = remaining[idx+1:]
			continue
		}
		
		// Try to split at space
		if idx := strings.LastIndex(chunk, " "); idx > maxLen/2 {
			chunks = append(chunks, remaining[:idx+1])
			remaining = remaining[idx+1:]
			continue
		}
		
		// No good split point, just split at maxLen
		chunks = append(chunks, remaining[:maxLen])
		remaining = remaining[maxLen:]
	}

	if len(remaining) > 0 {
		chunks = append(chunks, remaining)
	}

	return chunks
}

func (c *Client) SendMessage(chatID int64, text string) error {
	chunks := splitMessage(text, maxMessageLength)
	
	for _, chunk := range chunks {
		msg := tgbotapi.NewMessage(chatID, chunk)
		msg.ParseMode = "Markdown"
		_, err := c.Bot.Send(msg)
		if err != nil {
			return fmt.Errorf("failed to send message chunk: %w", err)
		}
	}
	
	return nil
}

func (c *Client) SendMessagePlain(chatID int64, text string) error {
	chunks := splitMessage(text, maxMessageLength)
	
	for _, chunk := range chunks {
		msg := tgbotapi.NewMessage(chatID, chunk)
		_, err := c.Bot.Send(msg)
		if err != nil {
			return fmt.Errorf("failed to send message chunk: %w", err)
		}
	}
	
	return nil
}
