"""Движок и фабрика сессий базы данных."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from utils.logger import logger


# Движок с пулом соединений
engine = create_async_engine(
    settings.database_url,
    echo=False,  # True для отладки SQL запросов
    pool_size=20,
    max_overflow=10,
)

# Фабрика сессий
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Получить сессию базы данных."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Database session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Инициализировать подключение и создать таблицы."""
    try:
        from database.models import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info("Database connection established")
        logger.info("Database tables created/verified")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


async def close_db() -> None:
    """Закрыть соединения с базой данных."""
    await engine.dispose()
    logger.info("Database connections closed")
