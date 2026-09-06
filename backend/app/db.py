from __future__ import annotations

import os
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql+asyncpg://tidebic:tidebic@localhost:5432/tidebic")


engine: AsyncEngine = create_async_engine(_database_url(), pool_pre_ping=True)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session

