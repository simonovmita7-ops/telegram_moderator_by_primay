"""
Модуль базы данных: подключение, сессии.
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from bot.models import Base

db: "Database | None" = None


def get_db() -> "Database":
    if db is None:
        raise RuntimeError("База данных не инициализирована")
    return db


class Database:
    def __init__(self, settings) -> None:
        self._engine = create_async_engine(settings.database_url, echo=False)
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False)

    async def init_db(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

            def _check_migrations(sync_conn):
                from sqlalchemy import inspect, text
                inspector = inspect(sync_conn)
                if "settings" in inspector.get_table_names():
                    cols = [c["name"] for c in inspector.get_columns("settings")]
                    if "ai_provider" not in cols:
                        sync_conn.execute(text("ALTER TABLE settings ADD COLUMN ai_provider VARCHAR(32) DEFAULT 'gemini'"))
                    if "mutes_enabled" not in cols:
                        sync_conn.execute(text("ALTER TABLE settings ADD COLUMN mutes_enabled BOOLEAN DEFAULT 1"))
                    if "kicks_enabled" not in cols:
                        sync_conn.execute(text("ALTER TABLE settings ADD COLUMN kicks_enabled BOOLEAN DEFAULT 1"))
                    if "warnings_enabled" not in cols:
                        sync_conn.execute(text("ALTER TABLE settings ADD COLUMN warnings_enabled BOOLEAN DEFAULT 1"))

            await conn.run_sync(_check_migrations)

    @asynccontextmanager
    async def session(self):
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        await self._engine.dispose()
