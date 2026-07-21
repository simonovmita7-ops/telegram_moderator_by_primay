"""
Загрузчик правил из файла правила.txt с мгновенным подхватом изменений.
При каждом обращении проверяется mtime файла — если изменился, текст перечитывается.
"""
from __future__ import annotations
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class RulesLoader:
    """Кэш правил с автоматической перезагрузкой при изменении файла."""

    def __init__(self, rules_path: Path) -> None:
        self._path = rules_path
        self._content: str = ""
        self._mtime: float = 0.0
        self._loaded_at: datetime | None = None
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            logger.warning("Файл правил не найден: %s", self._path)
            self._content = "Правила не найдены. Создайте файл правила.txt в корне проекта."
            self._mtime = 0.0
            return
        self._content = self._path.read_text(encoding="utf-8")
        self._mtime = self._path.stat().st_mtime
        self._loaded_at = datetime.utcnow()
        logger.info("Правила загружены из %s (%d символов)", self._path, len(self._content))

    def get_rules(self) -> str:
        """Получить актуальный текст правил (перечитать файл при изменении)."""
        if self._path.exists():
            current_mtime = self._path.stat().st_mtime
            if current_mtime != self._mtime:
                logger.info("Обнаружено изменение правила.txt — перезагрузка")
                self._load()
        return self._content

    @property
    def updated_at(self) -> float:
        return self._mtime

    @property
    def path(self) -> Path:
        return self._path
