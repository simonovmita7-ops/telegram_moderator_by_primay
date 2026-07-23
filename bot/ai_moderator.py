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
    return f"""Ты — строгий модератор Telegram-группы. Ты анализируешь сообщения ИСКЛЮЧИТЕЛЬНО по правилам группы ниже.

ПРАВИЛА ГРУППЫ:
{rules_text}

ВАЖНО:
- Действуй ТОЛЬКО по этим правилам. Никакой самодеятельности.
- Нарушает правило => violation: true. Не нарушает => violation: false.
- Анализируй буквально и точно.
- ВАЖНО: Если один пользователь отправляет несколько (даже 5+) сообщений подряд, но они несут смысл и являются частью нормального разговора (не бессмысленный флуд/набор символов/реклама), то это НЕ считается спамом. Будь лоялен, не квалифицируй содержательные сообщения как спам.

Категории нарушений (строго одна из):
insult, family_insult, spam, conflict, leak, adult, violence, sticker_abuse, poll_abuse, threat, advertisement, none

Ответь ТОЛЬКО валидным JSON без markdown:
{{
  "violation": true/false,
  "category": "категория",
  "severity": 1-5,
  "reason": "описание нарушения конкретного правила на русском",
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
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass
        raise


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
        """Резервный перебор всех настроенных провайдеров."""
        for provider_func, name in [
            (self._call_groq, "Groq"),
            (self._call_sambanova, "SambaNova"),
            (self._call_gemini, "Gemini")
        ]:
            try:
                return await provider_func(user_prompt, system_prompt)
            except Exception as exc:
                logger.warning("[AI Fallback] %s недоступен: %s", name, exc)
        raise ValueError("Все ИИ провайдеры недоступны")

    async def _call_multi_race(self, user_prompt, system_prompt):
        """Параллельный запуск всех настроенных провайдеров — возвращает первый успешный ответ."""
        tasks = []
        if getattr(self._settings, "groq_api_key", None):
            tasks.append(asyncio.create_task(self._call_groq(user_prompt, system_prompt)))
        if getattr(self._settings, "sambanova_api_key", None):
            tasks.append(asyncio.create_task(self._call_sambanova(user_prompt, system_prompt)))
        if getattr(self._settings, "gemini_api_key", None):
            tasks.append(asyncio.create_task(self._call_gemini(user_prompt, system_prompt)))

        if not tasks:
            raise ValueError("Нет настроенных ключей ИИ для мульти-режима")

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
                      "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json", "maxOutputTokens": 300}})
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
        r = await self._client.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model,
                  "messages": [{"role": "system", "content": system_prompt},
                               {"role": "user", "content": user_prompt}],
                  "temperature": 0.1, "response_format": {"type": "json_object"}})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    async def _call_sambanova(self, user_prompt, system_prompt):
        api_key = getattr(self._settings, "sambanova_api_key", None)
        if not api_key: raise ValueError("SAMBANOVA_API_KEY не задан")
        model = getattr(self._settings, "sambanova_model", "Meta-Llama-3.1-405B-Instruct")
        r = await self._client.post("https://api.sambanova.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model,
                  "messages": [{"role": "system", "content": system_prompt},
                               {"role": "user", "content": user_prompt}],
                  "temperature": 0.1, "response_format": {"type": "json_object"}})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
