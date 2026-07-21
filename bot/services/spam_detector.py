"""
Локальный детектор спама (без ИИ).
Дополняет ИИ-модерацию быстрой проверкой флуда.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Deque


@dataclass
class SpamCheckResult:
    """Результат проверки на спам."""

    is_spam: bool
    reason: str = ""
    spam_type: str = ""


@dataclass
class _UserMessageState:
    """Состояние сообщений пользователя в группе."""

    timestamps: Deque[datetime] = field(default_factory=lambda: deque(maxlen=50))
    texts: Deque[str] = field(default_factory=lambda: deque(maxlen=20))
    links: Deque[str] = field(default_factory=lambda: deque(maxlen=20))


class SpamDetector:
    """
    In-memory детектор спама.
    Отслеживает частоту сообщений, повторы, флуд символами/эмодзи.
    """

    def __init__(self) -> None:
        # group_id -> user_id -> state
        self._states: dict[int, dict[int, _UserMessageState]] = defaultdict(
            lambda: defaultdict(_UserMessageState)
        )
        self._processed_media_groups: Deque[str] = deque(maxlen=200)

    def _emoji_count(self, text: str) -> int:
        """Подсчёт emoji-символов в тексте."""
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"
            "\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "]+",
            flags=re.UNICODE,
        )
        return len(emoji_pattern.findall(text))

    def _extract_links(self, text: str) -> list[str]:
        return re.findall(r"https?://\S+|t\.me/\S+", text, flags=re.IGNORECASE)

    def check(
        self,
        group_id: int,
        user_id: int,
        text: str,
        message_limit: int = 15,
        window_seconds: int = 60,
        is_sticker: bool = False,
        is_gif: bool = False,
        media_group_id: str | None = None,
    ) -> SpamCheckResult:
        """
        Проверить сообщение на спам.
        """
        if media_group_id is not None:
            if media_group_id in self._processed_media_groups:
                return SpamCheckResult(is_spam=False)
            self._processed_media_groups.append(media_group_id)

        now = datetime.utcnow()
        state = self._states[group_id][user_id]
        state.timestamps.append(now)
        state.texts.append(text.strip().lower())

        limit = message_limit
        window = timedelta(seconds=window_seconds)

        # 1. Флуд по количеству сообщений
        recent = [t for t in state.timestamps if now - t <= window]
        if len(recent) >= limit:
            return SpamCheckResult(
                is_spam=True,
                reason=f"{len(recent)} сообщений за {window_seconds} сек",
                spam_type="flood",
            )

        # 2. Одинаковые сообщения подряд
        if len(state.texts) >= 3:
            last3 = list(state.texts)[-3:]
            if last3[0] == last3[1] == last3[2] and last3[0]:
                return SpamCheckResult(
                    is_spam=True,
                    reason="Три одинаковых сообщения подряд",
                    spam_type="duplicate",
                )

        # 3. Флуд символами (один символ повторяется > 50 раз)
        if text and len(set(text.strip())) <= 2 and len(text.strip()) > 50:
            return SpamCheckResult(
                is_spam=True,
                reason="Флуд повторяющимися символами",
                spam_type="char_flood",
            )

        # 4. Флуд эмодзи
        if self._emoji_count(text) > 15:
            return SpamCheckResult(
                is_spam=True,
                reason="Флуд эмодзи",
                spam_type="emoji_flood",
            )

        # 5. Флуд GIF / стикерами (считаем как сообщения — уже учтено в лимите)
        if is_gif and len(recent) >= max(3, limit // 3):
            return SpamCheckResult(
                is_spam=True,
                reason="Флуд GIF",
                spam_type="gif_flood",
            )

        if is_sticker and len(recent) >= max(5, limit // 2):
            return SpamCheckResult(
                is_spam=True,
                reason="Флуд стикерами",
                spam_type="sticker_flood",
            )

        # 6. Повторяющиеся ссылки
        links = self._extract_links(text)
        for link in links:
            state.links.append(link.lower())
        if len(state.links) >= 3:
            last_links = list(state.links)[-3:]
            if last_links[0] == last_links[1] == last_links[2]:
                return SpamCheckResult(
                    is_spam=True,
                    reason="Повторяющиеся ссылки",
                    spam_type="link_spam",
                )

        return SpamCheckResult(is_spam=False)

    def check_banned_words(
        self, text: str, banned_words: list[str], exceptions: list[str]
    ) -> SpamCheckResult:
        """Проверка на запрещённые слова из настроек группы."""
        text_lower = text.lower()
        for exc in exceptions:
            text_lower = text_lower.replace(exc.lower(), "")

        for word in banned_words:
            if word.lower() in text_lower:
                return SpamCheckResult(
                    is_spam=True,
                    reason=f"Запрещённое слово: {word}",
                    spam_type="banned_word",
                )
        return SpamCheckResult(is_spam=False)
