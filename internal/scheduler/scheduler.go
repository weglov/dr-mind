package scheduler

import (
	"context"
	"dr_mind/internal/repository"
	"dr_mind/pkg/telegram"
	"fmt"
	"math/rand"
	"time"

	"github.com/robfig/cron/v3"
	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

var (
	WeeklyMessages = []string{
		"Привет! 😊 Как твоё настроение сегодня? Если захочешь поговорить — я здесь.",
		"Привет! На связи Минди 🌟 Надеюсь, сегодня у тебя найдётся время на приятные мелочи!",
		"Привет! 📅 Как прошла твоя неделя? Буду рада послушать, если захочешь поделиться.",
		"Как ты там? 🌈 Если нужна поддержка или просто разговор по душам — обращайся!",
		"Надеюсь, у тебя всё хорошо ❤️ Помни, ты всегда можешь обратиться ко мне за советом или поддержкой.",
		"Это Минди 🌺 Напоминаю о важности заботы о себе: отдых и хорошие эмоции нужны каждому.",
		"Просто хочу сказать, что верю в тебя ❤️ Если захочется обсудить что-то важное — я рядом!",
		"Пусть твой день будет спокойным и светлым ☀️ Я здесь, если захочешь поговорить!",
		"Думаю о тебе и надеюсь, что твой день полон хороших моментов 😊",
	}

	StickerIDs = []string{
		"CAACAgIAAxkBAAEM1Cdnug3_A9foIEifK7S9itGrD6Mb8AACbgUAAj-VzAqGOtldiLy3NTYE",
		"CAACAgIAAxkBAAEM1C1nug48u60e7B2FIvSYqAE5zo486gACjgYAAvpRRgyWGTCDhkMr4DYE",
		"CAACAgIAAxkBAAEM1Ctnug44D5lryaN2pW27Vu87T7t4yQACCiYAAgPBeUjcZzJU8Ge0tzYE",
		"CAACAgIAAxkBAAEM1Clnug41CBV_N651cNAEixoTNaKM1wAClBgAAvdbgEjPGPx-6kVXrjYE",
		"CAACAgQAAxkBAAEM1C9nug5p5ZsrjjqdpsXnUDPb3I6arwAC2BQAAuiWMFKeUXzNBIgNGzYE",
		"CAACAgQAAxkBAAEM1DFnug56hiAAAacFk0Dg_7bEgO3ziNEAApMUAAKT-TBQTP9P0XAxl-I2BA",
		"CAACAgIAAxkBAAEM1DNnug6MjJ1irrHgAAHU4LLD9Y_n2CcAAnUaAAKQEIlKRjLKTmhNvCE2BA",
		"CAACAgQAAxkBAAEM1Ddnug6lNoe6Qz3JGfYrng9HbnxzVQACVxcAAtJZQFOXH0PCwGC1bTYE",
		"CAACAgQAAxkBAAEM1D9nug8Twpn2CAijRj6EHYPOmFCrSgACGxEAAnu7gFDZ_ClKKc1VZTYE",
	}
)

type Scheduler struct {
	cron     *cron.Cron
	repo     *repository.Repository
	tgClient *telegram.Client
}

func NewScheduler(repo *repository.Repository, tgClient *telegram.Client) *Scheduler {
	mskLocation, _ := time.LoadLocation("Europe/Moscow")
	return &Scheduler{
		cron:     cron.New(cron.WithLocation(mskLocation)),
		repo:     repo,
		tgClient: tgClient,
	}
}

func (s *Scheduler) Start() error {
	// Каждую пятницу в 20:00 MSK
	_, err := s.cron.AddFunc("0 20 * * 5", s.sendWeeklyMessages)
	if err != nil {
		return err
	}
	s.cron.Start()
	return nil
}

func (s *Scheduler) Stop() {
	s.cron.Stop()
}

func (s *Scheduler) sendWeeklyMessages() {
	ctx := context.Background()

	// Получаем всех пользователей
	userIDs, err := s.repo.GetAllUserIDs(ctx)
	if err != nil {
		fmt.Printf("Error getting user IDs: %v\n", err)
		return
	}

	// Выбираем случайное сообщение и стикер
	message := WeeklyMessages[rand.Intn(len(WeeklyMessages))]
	stickerID := StickerIDs[rand.Intn(len(StickerIDs))]

	successCount := 0
	errorCount := 0

	for _, userIDStr := range userIDs {
		userID, err := parseUserID(userIDStr)
		if err != nil {
			errorCount++
			continue
		}

		// Отправляем стикер
		sticker := tgbotapi.NewSticker(userID, tgbotapi.FileID(stickerID))
		_, err = s.tgClient.Bot.Send(sticker)
		if err != nil {
			errorCount++
			continue
		}

		time.Sleep(100 * time.Millisecond) // Задержка между отправками

		// Отправляем сообщение
		err = s.tgClient.SendMessagePlain(userID, message)
		if err != nil {
			errorCount++
			continue
		}

		// Добавляем в историю как системное сообщение (user message пустое, т.к. это сообщение от бота)
		err = s.repo.AddConversation(ctx, userIDStr, "[Weekly message]", message)
		if err != nil {
			fmt.Printf("Error saving weekly message to history: %v\n", err)
		}

		successCount++
		time.Sleep(100 * time.Millisecond) // Задержка между отправками
	}

	fmt.Printf("Weekly messages sent. Success: %d, Errors: %d\n", successCount, errorCount)
}

func parseUserID(userIDStr string) (int64, error) {
	var userID int64
	_, err := fmt.Sscanf(userIDStr, "%d", &userID)
	return userID, err
}
