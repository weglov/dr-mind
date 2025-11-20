package repository

import (
	"time"
)

type User struct {
	UserID           string    `gorm:"primaryKey;column:user_id"`
	Name             string    `gorm:"column:name"`
	MessageCount     int       `gorm:"column:message_count"`
	CreatedAt        time.Time `gorm:"column:created_at;autoCreateTime"`
	UpdatedAt        time.Time `gorm:"column:updated_at;autoUpdateTime"`
	IsSupervisorMode bool      `gorm:"column:is_supervisor_mode;default:false"`
}

type Conversation struct {
	ID                        uint      `gorm:"primaryKey;autoIncrement"`
	UserID                    string    `gorm:"column:user_id;index"`
	MessageIndex              int       `gorm:"column:message_index"`
	EncryptedUserMessage      string    `gorm:"column:encrypted_user_message"`
	EncryptedAssistantMessage string    `gorm:"column:encrypted_assistant_message"`
	CreatedAt                 time.Time `gorm:"column:created_at;autoCreateTime"`
}

type Summary struct {
	ID                     uint      `gorm:"primaryKey;autoIncrement"`
	UserID                 string    `gorm:"column:user_id;index"`
	EncryptedSummaryText   string    `gorm:"column:encrypted_summary_text"`
	MessageCountAtSummary  int       `gorm:"column:message_count_at_summary"`
	IsCurrent              bool      `gorm:"column:is_current;default:true"`
	CreatedAt              time.Time `gorm:"column:created_at;autoCreateTime"`
	UpdatedAt              time.Time `gorm:"column:updated_at;autoUpdateTime"`
	// Non-DB field for decrypted text
	SummaryText            string    `gorm:"-"`
}

// Message struct for service layer communication (not a DB model)
type Message struct {
	User      string
	Assistant string
	Timestamp time.Time
}

