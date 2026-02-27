"""Middleware авторизации по белому списку."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from config import settings
from database.db import async_session_maker
from database.crud import get_user
from utils.logger import logger


class AuthMiddleware(BaseMiddleware):
    """
    Проверяет наличие пользователя в базе данных (белый список).

    Пропускает только зарегистрированных пользователей.
    Незарегистрированным возвращает сообщение с их Telegram ID.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if not user:
            return await handler(event, data)

        telegram_id = user.id

        try:
            async with async_session_maker() as session:
                db_user = await get_user(session, telegram_id)

                if db_user:
                    # Передаём пользователя в data для хендлеров
                    data["db_user"] = db_user
                    return await handler(event, data)
                else:
                    logger.warning(f"Access denied for user {telegram_id}")

                    if isinstance(event, Message):
                        await event.answer(
                            f"🚫 Доступ запрещен.\n\n"
                            f"Ваш ID: <code>{telegram_id}</code>\n\n"
                            f"Отправьте его администратору для получения доступа.",
                            parse_mode="HTML"
                        )
                    elif isinstance(event, CallbackQuery):
                        await event.answer(
                            "Доступ запрещен. Обратитесь к администратору.",
                            show_alert=True
                        )
                    return None

        except Exception as e:
            logger.error(f"Auth middleware error: {e}")
            # При ошибке БД пропускаем начального администратора со stub-объектом
            if settings.default_admin_id and telegram_id == settings.default_admin_id:
                logger.warning(f"DB unavailable, allowing default admin {telegram_id} through")
                from database.models import User
                stub_user = User(
                    telegram_id=telegram_id,
                    full_name="Admin (DB offline)",
                    is_admin=True,
                )
                data["db_user"] = stub_user
                return await handler(event, data)
            if isinstance(event, Message):
                await event.answer(
                    "⚠️ Ошибка проверки доступа. Попробуйте позже."
                )
            return None
