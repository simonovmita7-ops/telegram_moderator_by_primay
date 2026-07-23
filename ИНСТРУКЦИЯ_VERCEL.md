# 🚀 Инструкция по развертыванию Mini App и Сайта Инструкций на Vercel

Эта инструкция описывает процесс развертывания веб-интерфейсов **Group Controls Bot** (Mini App и сайта инструкций) на платформе Vercel.

---

## 📋 Проекты на Vercel

1. **Mini App (`bot/web/static`):**
   - Ссылка: `https://telegram-moderator-by-primay.vercel.app/`
   - Назначение: Интерактивная веб-панель управления ботом для администраторов.
2. **Docs Site (`docs_site`):**
   - Ссылка: `https://docs-style.vercel.app/`
   - Назначение: Публичный сайт инструкций, мини-игр и динамо-проверки статуса бота.

---

## 🛠 Подключение и Настройка

### 1. Настройка `API_BASE` в Mini App
В файле `bot/web/static/index.html` укажите адрес запущенного бэкенда бота:
```javascript
const API_BASE = "https://reapprove-roundup-coyness.ngrok-free.dev";
```

### 2. Динамический статус на Сайте Инструкций
На сайте инструкций (`docs_site/index.html`) встроен автономный JS-пингер к эндпоинту `/api/status` вашего сервера:
```javascript
const API_BASE_CANDIDATES = [
  "https://reapprove-roundup-coyness.ngrok-free.dev",
  "https://telegram-moderator-by-primay.vercel.app"
];
```
При запуске бота на ПК статус отображается как **🟢 Онлайн**, а при выключении — мгновенно переключается на **🔴 Офлайн**.

---

## 📱 Подключение Mini App в Telegram

1. Откройте Telegram и перейдите к боту **@BotFather**.
2. Введите команду `/setmenubutton` и выберите бота `@GControlsBot`.
3. Введите URL вашего Mini App на Vercel:
   `https://telegram-moderator-by-primay.vercel.app/`
4. Укажите название кнопки меню (например: `🛡️ Mini App`).
5. Теперь кнопка вызова приложения всегда доступна в чате с ботом!
