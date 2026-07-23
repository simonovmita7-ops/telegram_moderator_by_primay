"""
ИИ-модератор: анализ сообщений через Google Gemini, Groq Cloud, SambaNova или Мульти-режим (гонка нейросетей).
Работает СТРОГО по правилам из файла правила.txt. Без встроенной чувствительности.
"""
from __future__ import annotations
import asyncio, json, logging, re
from dataclasses import dataclass
from typing import Any
import httpx
from bot.config import Settings
from bot.models import ViolationCategory

logger = logging.getLogger(__name__)
VALID_CATEGORIES = {c.value for c in ViolationCategory}
VALID_ACTIONS = {"none", "warning", "mute", "kick", "ban"}


def build_system_prompt(rules_text: str) -> str:
    return f"""Ты — эксперт-модератор Telegram-группы. Твоя единственная цель — строго и неукоснительно соблюдать ПРАВИЛА ГРУППЫ ниже.

ПРАВИЛА ГРУППЫ:
{rules_text}

КРИТИЧЕСКИЕ ИНСТРУКЦИИ ПО СОБЛЮДЕНИЮ ПРАВИЛ:
1. Правила группы имеют АБСОЛЮТНЫЙ приоритет. Оценивай каждое сообщение строго в соответствии с текстом правил выше.
2. ВАЖНО: Различай реальный грубый мат/оскорбления и безобидные шутливые или детские слова! Обычные разговорные или детские слова (например: "какашка", "блин", "дурак", "черт", "дурачок", "дура") НЕ являются тяжелым матом или опасным оскорблением. Помечай их как НЕ нарушение (violation: false, category: "none", recommended_action: "none").
3. Нарушением (violation: true) считаются ТОЛЬКО: явный нецензурный мат, прямое тяжелое оскорбление личности, жесткая ругань, а также явное нарушение конкретных запретов из ПРАВИЛ ГРУППЫ выше.
4. Если в правилах указано "Удаляй любые видео", "Запрещены картинки/ссылки/видео/кружочки/голосовые", то при наличии меток [ВИДЕО], [КРУЖОК / ВИДЕОСООБЩЕНИЕ], [ФОТО], [ГОЛОСОВОЕ СООБЩЕНИЕ] или ссылок немедленно фиксируй нарушение (violation: true, recommended_action: "warning" или "mute").
5. Если в правилах написано "Нет правил", "Не кикай, не муть", "Без предупреждений", "Разрешено всё" — то НЕ фиксируй никаких нарушений (violation: false), или если сказано не давать определённые наказания — строго выполняй волю администратора!
6. Если один пользователь отправляет несколько содержательных сообщений подряд в ходе обычного разговора, это НЕ считается спамом.
7. Если в правилах есть конкретные указания, что именно писать нарушителю (например, "Пиши что материться нельзя"), то в поле "reason" указывай именно эту понятную причину (например, "Материться нельзя!").
8. ПО УМОЛЧАНИЮ стикеры, гифки, картинки, видео, голосовые и опросы ПОЛНОСТЬЮ РАЗРЕШЕНЫ! Обычная отправка одного или нескольких стикеров — это НЕ нарушение (violation: false, category: "none"). Помечай стикеры (sticker_abuse) как нарушение ТОЛЬКО если в ПРАВИЛАХ ГРУППЫ прямым текстом написано "Запрещены стикеры", либо если идет непрерывный массовый спам стикерами (5+ штук подряд).

Категории нарушений (выбери подходящую из списка):
insult, family_insult, spam, conflict, leak, adult, violence, sticker_abuse, poll_abuse, threat, advertisement, none

Ответь ТОЛЬКО валидным JSON без markdown:
{{
  "violation": true/false,
  "category": "категория",
  "severity": 1-5,
  "reason": "краткое описание конкретного нарушенного правила на русском",
  "recommended_action": "none|warning|mute|kick|ban"
}}
severity: 1=лёгкое, 5=критическое. Нет нарушения — violation: false, category: "none", recommended_action: "none"."""


@dataclass(frozen=True, slots=True)
class AiModerationResult:
    violation: bool
    category: str
    severity: int
    reason: str
    recommended_action: str
    raw_response: dict[str, Any]


def _build_user_prompt(message_text, context_messages, violation_history,
                       banned_words, exception_words, is_poll=False,
                       poll_question="", poll_options=None):
    context_block = "\n".join(f"- {m}" for m in context_messages[-20:]) or "(нет)"
    history_block = "\n".join(f"- {h}" for h in violation_history[-10:]) or "(нет)"
    poll_block = ""
    if is_poll:
        opts = ", ".join(poll_options or [])
        poll_block = f"\n\nЭто ОПРОС.\nВопрос: {poll_question}\nВарианты: {opts}"
    banned_block = ", ".join(banned_words) if banned_words else "(нет)"
    exc_block = ", ".join(exception_words) if exception_words else "(нет)"
    return f"""Дополнительные запрещённые слова (реагировать немедленно): {banned_block}
Слова-исключения (НЕ реагировать): {exc_block}

Последние сообщения (контекст):
{context_block}

История нарушений пользователя:
{history_block}
{poll_block}

Анализируемое сообщение:
{message_text}
"""


def _parse_ai_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {"violation": False, "category": "none", "severity": 0, "reason": "ИИ вернул пустой ответ", "recommended_action": "none"}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    
    # 1. Прямой парсинг
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Поиск вырезанного JSON блока {...} через regex
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # 3. Восстановление обломанного JSON при MAX_TOKENS
    start = text.find('{')
    if start != -1:
        truncated = text[start:]
        if truncated.count('"') % 2 != 0:
            truncated += '"'
        if not truncated.endswith('}'):
            truncated += '}'
        try:
            return json.loads(truncated)
        except json.JSONDecodeError:
            pass

    return {"violation": False, "category": "none", "severity": 0, "reason": f"Не удалось разобрать JSON ответа ИИ: {text[:100]}", "recommended_action": "none"}


def _normalize_result(data: dict[str, Any]) -> AiModerationResult:
    violation = bool(data.get("violation", False))
    category = str(data.get("category", "none"))
    if category not in VALID_CATEGORIES:
        category = "none"; violation = False
    severity = max(0, min(5, int(data.get("severity", 0))))
    reason = str(data.get("reason", ""))
    action = str(data.get("recommended_action", "none"))
    if action not in VALID_ACTIONS:
        action = "none"
    return AiModerationResult(violation=violation, category=category,
                              severity=severity, reason=reason,
                              recommended_action=action, raw_response=data)


class AiModerator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=settings.ai_request_timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def analyze(self, message_text, context_messages, violation_history,
                       rules_text="", banned_words=None, exception_words=None,
                       is_poll=False, poll_question="", poll_options=None,
                       provider="gemini"):
        system_prompt = build_system_prompt(rules_text if rules_text else
            "Запрещены: оскорбления, спам, угрозы, реклама, насилие, порнография.")
        user_prompt = _build_user_prompt(
            message_text, context_messages, violation_history,
            banned_words or [], exception_words or [],
            is_poll, poll_question, poll_options)
        try:
            p = (provider or "gemini").lower()
            if p == "multi":
                raw_text = await self._call_multi_race(user_prompt, system_prompt)
            elif p == "groq":
                try:
                    raw_text = await self._call_groq(user_prompt, system_prompt)
                except Exception as exc:
                    logger.warning("[AI] Groq недоступен, фоллбек на резервные ИИ: %s", exc)
                    raw_text = await self._call_any_fallback(user_prompt, system_prompt)
            elif p == "sambanova":
                try:
                    raw_text = await self._call_sambanova(user_prompt, system_prompt)
                except Exception as exc:
                    logger.warning("[AI] SambaNova недоступен, фоллбек на резервные ИИ: %s", exc)
                    raw_text = await self._call_any_fallback(user_prompt, system_prompt)
            else:
                try:
                    raw_text = await self._call_gemini(user_prompt, system_prompt)
                except Exception as exc:
                    logger.warning("[AI] Gemini недоступен, фоллбек на резервные ИИ: %s", exc)
                    raw_text = await self._call_any_fallback(user_prompt, system_prompt)

            data = _parse_ai_json(raw_text)
            return _normalize_result(data)
        except Exception as exc:
            logger.warning("[AI] Предупреждение / ошибка: %s", exc)
            return AiModerationResult(violation=False, category="none", severity=0,
                reason=f"Ошибка ИИ ({provider}): {exc}", recommended_action="none", raw_response={"error": str(exc)})

    async def _call_any_fallback(self, user_prompt, system_prompt):
        """Резервный перебор основных провайдеров, а при их сбое — вызов экстренного SambaNova."""
        for provider_func, name in [
            (self._call_groq, "Groq"),
            (self._call_gemini, "Gemini")
        ]:
            try:
                return await provider_func(user_prompt, system_prompt)
            except Exception as exc:
                logger.warning("[AI Fallback] %s недоступен: %s", name, exc)

        # Если основные провайдеры упали — задействуем экстренный SambaNova
        if getattr(self._settings, "sambanova_api_key", None):
            try:
                logger.info("[AI Emergency] Основные ИИ недоступны, подключаем экстренный резерв SambaNova...")
                return await self._call_sambanova(user_prompt, system_prompt)
            except Exception as exc:
                logger.warning("[AI Emergency] SambaNova недоступен: %s", exc)

        raise ValueError("Все ИИ провайдеры (включая экстренный резерв) недоступны")

    async def _call_multi_race(self, user_prompt, system_prompt):
        """Параллельный запуск основных провайдеров (Gemini, Groq) — возвращает первый успешный ответ."""
        tasks = []
        if getattr(self._settings, "groq_api_key", None):
            tasks.append(asyncio.create_task(self._call_groq(user_prompt, system_prompt)))
        if getattr(self._settings, "gemini_api_key", None):
            tasks.append(asyncio.create_task(self._call_gemini(user_prompt, system_prompt)))

        if not tasks:
            raise ValueError("Нет настроенных основных ключей ИИ для мульти-режима")

        pending = tasks
        last_error = None
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for completed_task in done:
                try:
                    result = completed_task.result()
                    for t in pending:
                        t.cancel()
                    return result
                except (asyncio.CancelledError, GeneratorExit):
                    pass
                except Exception as exc:
                    last_error = exc
                    logger.warning("[AI Multi-Race] Ошибка провайдера: %s", exc)

        raise last_error or ValueError("Все ИИ провайдеры вернули ошибку в мульти-режиме")

    async def _call_gemini(self, user_prompt, system_prompt):
        api_key = getattr(self._settings, "gemini_api_key", None)
        if not api_key: raise ValueError("GEMINI_API_KEY не задан")
        model = getattr(self._settings, "gemini_model", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        delay = 3.0
        for attempt in range(1, 4):
            r = await self._client.post(url, params={"key": api_key},
                headers={"Content-Type": "application/json"},
                json={"system_instruction": {"parts": [{"text": system_prompt}]},
                      "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                      "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json", "maxOutputTokens": 1000}})
            if r.status_code == 429 and attempt < 3:
                await asyncio.sleep(delay); delay *= 2; continue
            r.raise_for_status()
            res_json = r.json()
            candidates = res_json.get("candidates", [])
            if not candidates:
                raise ValueError(f"Gemini API вернул пустой список кандидатов: {res_json}")
            candidate = candidates[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            if not parts:
                finish_reason = candidate.get("finishReason", "UNKNOWN")
                raise ValueError(f"Контент Gemini заблокирован или пуст (код завершения: {finish_reason})")
            return parts[0].get("text", "")

    async def _call_groq(self, user_prompt, system_prompt):
        api_key = getattr(self._settings, "groq_api_key", None)
        if not api_key: raise ValueError("GROQ_API_KEY не задан")
        model = getattr(self._settings, "groq_model", "llama-3.3-70b-versatile")
        delay = 2.0
        for attempt in range(1, 4):
            r = await self._client.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model,
                      "messages": [{"role": "system", "content": system_prompt},
                                   {"role": "user", "content": user_prompt}],
                      "temperature": 0.1, "response_format": {"type": "json_object"}})
            if r.status_code == 429 and attempt < 3:
                await asyncio.sleep(delay); delay *= 2; continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    async def _call_sambanova(self, user_prompt, system_prompt):
        api_key = getattr(self._settings, "sambanova_api_key", None)
        if not api_key: raise ValueError("SAMBANOVA_API_KEY не задан")
        model = getattr(self._settings, "sambanova_model", "Meta-Llama-3.3-70B-Instruct")
        delay = 2.0
        for attempt in range(1, 4):
            r = await self._client.post("https://api.sambanova.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model,
                      "messages": [{"role": "system", "content": system_prompt},
                                   {"role": "user", "content": user_prompt}],
                      "temperature": 0.1, "response_format": {"type": "json_object"}})
            if r.status_code == 429 and attempt < 3:
                await asyncio.sleep(delay); delay *= 2; continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
