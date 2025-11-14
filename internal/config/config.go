package config

import (
	"fmt"
	"os"
)

type Config struct {
	BotToken      string
	ClaudeAPIKey  string
	ClaudeModel   string
	DatabaseURL   string
	EncryptionKey string
}

func Load() (*Config, error) {
	encryptionKey := os.Getenv("ENCRYPTION_KEY")
	if encryptionKey == "" {
		return nil, fmt.Errorf("ENCRYPTION_KEY is required")
	}

	botToken := os.Getenv("BOT_TOKEN")
	if botToken == "" {
		return nil, fmt.Errorf("BOT_TOKEN is required")
	}

	claudeAPIKey := os.Getenv("CLAUDE_API_KEY")
	if claudeAPIKey == "" {
		return nil, fmt.Errorf("CLAUDE_API_KEY is required")
	}

	databaseURL := os.Getenv("DATABASE_URL")
	if databaseURL == "" {
		return nil, fmt.Errorf("DATABASE_URL is required")
	}

	return &Config{
		BotToken:      botToken,
		ClaudeAPIKey:  claudeAPIKey,
		ClaudeModel:   getEnv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022"),
		DatabaseURL:   databaseURL,
		EncryptionKey: encryptionKey,
	}, nil
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
