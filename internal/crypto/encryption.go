package crypto

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
)

type EncryptionService struct {
	key []byte
}

func NewEncryptionService(encryptionKey string) (*EncryptionService, error) {
	// Создаем 32-байтовый ключ из строки (SHA256)
	hash := sha256.Sum256([]byte(encryptionKey))
	return &EncryptionService{key: hash[:]}, nil
}

// Encrypt шифрует текст и возвращает base64 строку
func (e *EncryptionService) Encrypt(plaintext string) (string, error) {
	block, err := aes.NewCipher(e.key)
	if err != nil {
		return "", err
	}

	// Создаем GCM
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}

	// Создаем nonce
	nonce := make([]byte, gcm.NonceSize())
	if _, err = io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}

	// Шифруем
	ciphertext := gcm.Seal(nonce, nonce, []byte(plaintext), nil)
	return base64.StdEncoding.EncodeToString(ciphertext), nil
}

// Decrypt расшифровывает base64 строку
func (e *EncryptionService) Decrypt(encryptedText string) (string, error) {
	// Декодируем из base64
	ciphertext, err := base64.StdEncoding.DecodeString(encryptedText)
	if err != nil {
		return "", err
	}

	block, err := aes.NewCipher(e.key)
	if err != nil {
		return "", err
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}

	if len(ciphertext) < gcm.NonceSize() {
		return "", errors.New("ciphertext too short")
	}

	// Извлекаем nonce и расшифровываем
	nonce, ciphertext := ciphertext[:gcm.NonceSize()], ciphertext[gcm.NonceSize():]
	plaintext, err := gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return "", err
	}

	return string(plaintext), nil
}

// DecryptOrPlaintext пытается расшифровать строку, но если это не валидный base64,
// возвращает строку как есть (для обратной совместимости со старыми незашифрованными данными)
// Возвращает (plaintext, isPlaintext, error)
func (e *EncryptionService) DecryptOrPlaintext(encryptedText string) (string, bool, error) {
	// Если строка пустая, возвращаем как есть
	if encryptedText == "" {
		return "", true, nil
	}

	// Пытаемся декодировать из base64
	ciphertext, err := base64.StdEncoding.DecodeString(encryptedText)
	if err != nil {
		// Если это не валидный base64, это plaintext (старые незашифрованные данные)
		return encryptedText, true, nil
	}

	// Если декодирование успешно, пытаемся расшифровать
	block, err := aes.NewCipher(e.key)
	if err != nil {
		return "", false, err
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", false, err
	}

	if len(ciphertext) < gcm.NonceSize() {
		// Если ciphertext слишком короткий, возможно это не зашифрованные данные
		// Возвращаем исходную строку как plaintext
		return encryptedText, true, nil
	}

	// Извлекаем nonce и расшифровываем
	nonce, ciphertext := ciphertext[:gcm.NonceSize()], ciphertext[gcm.NonceSize():]
	plaintext, err := gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		// Если расшифровка не удалась, данные зашифрованы другим ключом
		// Возвращаем ошибку, чтобы пропустить эту запись
		return "", false, fmt.Errorf("decryption failed (possibly different key): %w", err)
	}

	return string(plaintext), false, nil
}
