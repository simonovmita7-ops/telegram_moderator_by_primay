# 🛡️ Group Controls Bot (Beta 1.3)

Автономный Telegram-бот модератор групп с 100% бесплатной ИИ-модерацией (**Groq Cloud Llama-3**, **Google Gemini**), интерактивным **Mini App** веб-интерфейсом в стиле Apple Liquid Glass, автоматическими наказаниями, мини-играми и динамическим каналом статуса.

---

## ✨ Возможности

- 🤖 **100% Бесплатная ИИ-модерация:**
  - 🚀 **Groq Llama-3:** сверхбыстрые LPU-чипы (800 токенов/сек, отклик 0.1 сек).
  - 🧠 **Google Gemini:** умный и надежный нейронный движок от Google.
  - *Переключение бесплатных нейросетей прямо в Mini App для каждой группы в 1 клик!*
- 📱 **Современный Mini App (веб-панель):**
  - Дашборд статистики инцидентов, предупреждений, мутов и киков.
  - Выбор бесплатного провайдера ИИ (Groq Llama-3, Google Gemini).
  - Настройка текстовых правил и категорий ИИ-модерации.
  - Интерактивная вкладка **«Мозг» 🧠** с тумблером работы ИИ и отправкой логов ошибок автору (`@PR1MAY`).
  - Управление списком запрещённых слов и исключений.
  - Таблица лидеров участников дуэлей.
  - Быстрое добавление бота в группу через диплинк.
  - Поддержка свайпов и плавных неоновых анимаций.
- 🎮 **Мини-игры и комьюнити:**
  - Русская рулетка (`/rlt`) с выбором количества патронов.
  - Хардкор рулетка (`/HardcoreRLT`) для администраторов с автоматическим киком проигравшего.
  - Пошаговые дуэли между участниками чата (`Дуэль @user`).
  - Таблица топ-игроков дуэлей (`/top`).
- ⚡ **Мгновенный антиспам & Запрещённые слова:** реакция без задержек на запрещённые фразы и флуд.
- 📌 **Канал статуса в реальном времени:** автоматическое обновление состояния `ONLINE/OFFLINE` и версии бота в закреплённом сообщении канала.
- 🗄️ **SQLite + SQLAlchemy (Async):** надежная база данных и планировщик задач.

---

## 📁 Структура проекта

```
telegram-moderator-bot/
├── bot/
│   ├── main.py              # Точка входа и инициализация бота
│   ├── config.py            # Конфигурация из .env (Groq, Gemini, токены)
│   ├── database.py          # Асинхронное подключение SQLAlchemy
│   ├── models.py            # ORM-модели БД
│   ├── ai_moderator.py      # Модуль ИИ-анализа (Groq Llama-3 / Google Gemini)
│   ├── handlers/            # Обработчики сообщений и команд Telegram
│   │   ├── start.py         # /start, /rulesadd и приветствие
│   │   ├── moderation.py    # Фильтрация сообщений и антиспам
│   │   ├── group_panel.py   # Вызов Mini App и инлайн-панели
│   │   ├── minigames.py     # Игры (рулетка, хардкор, дуэли)
│   │   └── group_events.py  # События входа/выхода бота из групп
│   ├── keyboards/           # Инлайн и Reply клавиатуры
│   ├── services/            # Сервисы логирования, наказаний, правил и статуса
│   ├── scheduler/           # Фоновый планировщик (снятие наказаний)
│   └── web/
│       ├── server.py        # Web-сервер Mini App (aiohttp API)
│       └── static/          # WebApp статичный фронтенд (HTML, CSS, JS)
├── docs_site/               # Сайт документации и инструкций (Vercel)
├── правила.txt              # ⭐ Главный файл правил (авто-обновление)
├── schema.sql               # SQL-схема базы данных
├── .env                     # Конфигурация окружения
├── .env.example             # Пример файла .env
└── requirements.txt         # Зависимости Python
```

---

## 🚀 Требования и Установка

### Требования
- Python 3.12+
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))
- Ключи API (бесплатные):
  - Google Gemini API Key ([Google AI Studio](https://aistudio.google.com/))
  - Groq Cloud API Key ([Groq Console](https://console.groq.com/))

### Шаги установки

1. **Клонируйте репозиторий и перейдите в папку:**
   ```bash
   git clone https://github.com/your-repo/telegram-moderator-bot.git
   cd telegram-moderator-bot
   ```

2. **Создайте и активируйте виртуальное окружение:**
   ```bash
   python -m venv venv
   
   # Windows:
   venv\Scripts\activate
   
   # Linux / macOS:
   source venv/bin/activate
   ```

3. **Установите зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Настройте переменные окружения:**
   Скопируйте `.env.example` в `.env` и введите свои данные:
   ```env
   TELEGRAM_BOT_TOKEN=ВАШ_ТОКЕН_ОТ_BOTFATHER
   
   GEMINI_API_KEY=ВАШ_КЛЮЧ_GEMINI
   GEMINI_MODEL=gemini-2.5-flash

   GROQ_API_KEY=ВАШ_КЛЮЧ_GROQ
   GROQ_MODEL=llama-3.3-70b-versatile
   
   DATABASE_URL=sqlite+aiosqlite:///bot/data/moderator.db
   LOG_LEVEL=INFO
   WEBAPP_URL=https://telegram-moderator-by-primay.vercel.app/
   SUBSCRIPTION_CHANNEL=https://t.me/GroupControlsNews
   STATUS_CHANNEL_ID=@GroupControlsNews
   STATUS_MESSAGE_ID=3
   BOT_VERSION=Beta 1.3
   ```

---

## ⚙️ Запуск и Использование

### Запуск бота
```bash
python -m bot.main
```

### Настройка в Telegram
1. Добавьте бота в вашу группу и назначьте **администратором** с правами:
   - Удаление сообщений
   - Блокировка пользователей
2. Перейдите в ЛС с ботом (`@GControlsBot`) и введите `/start`.
3. Откройте **Mini App**, чтобы настроить правила модерации, списки слов и выбрать нейросеть (Groq Llama-3 / Google Gemini).

---

## 📄 Лицензия

Проект распространяется под лицензией MIT.
