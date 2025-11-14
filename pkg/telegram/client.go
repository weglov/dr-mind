package telegram

import (
	"fmt"
	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

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

func (c *Client) SendMessage(chatID int64, text string) error {
	msg := tgbotapi.NewMessage(chatID, text)
	msg.ParseMode = "Markdown"
	_, err := c.Bot.Send(msg)
	return err
}

func (c *Client) SendMessagePlain(chatID int64, text string) error {
	msg := tgbotapi.NewMessage(chatID, text)
	_, err := c.Bot.Send(msg)
	return err
}
