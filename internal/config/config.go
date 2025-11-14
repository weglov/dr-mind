package config

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/joho/godotenv"
)

type Config struct {
	BotToken      string
	ClaudeAPIKey  string
	ClaudeModel   string
	DatabaseURL   string
	EncryptionKey string
	OpenAIAPIKey  string
}

func Load() (*Config, error) {
	// Try to load .env file from multiple possible locations
	wd, _ := os.Getwd()

	// First try current directory
	if err := godotenv.Load(); err != nil {
		// Try from project root (assuming we're in cmd/bot or similar)
		// Go up to find .env file
		currentWd := wd
		for i := 0; i < 3; i++ {
			envPath := filepath.Join(currentWd, ".env")
			if _, err := os.Stat(envPath); err == nil {
				if loadErr := godotenv.Load(envPath); loadErr == nil {
					break
				}
			}
			currentWd = filepath.Dir(currentWd)
		}
	}

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

	openAIAPIKey := os.Getenv("OPENAI_API_KEY")
	// OpenAI API key не обязателен, но нужен для транскрибации голосовых сообщений

	return &Config{
		BotToken:      botToken,
		ClaudeAPIKey:  claudeAPIKey,
		ClaudeModel:   getEnv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022"),
		DatabaseURL:   databaseURL,
		EncryptionKey: encryptionKey,
		OpenAIAPIKey:  openAIAPIKey,
	}, nil
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
