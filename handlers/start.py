"""Обработчик команды /start."""

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

from database.models import User
from keyboards.inline import get_main_menu_keyboard
from utils.logger import logger


router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, db_user: User) -> None:
    """Обработка /start. Неавторизованные пользователи блокируются в AuthMiddleware."""
    logger.info(f"User {db_user.telegram_id} ({db_user.full_name}) started bot")

    await message.answer(
        f"👋 Привет, {db_user.full_name}!\n\n"
        f"Это бот для бронирования оборудования.\n"
        f"Выберите действие:",
        reply_markup=get_main_menu_keyboard(is_admin=db_user.is_admin)
    )


@router.callback_query(F.data == "menu:main")
async def callback_main_menu(callback: CallbackQuery, db_user: User) -> None:
    """Возврат в главное меню."""
    await callback.message.edit_text(
        f"👋 Привет, {db_user.full_name}!\n\n"
        f"Это бот для бронирования оборудования.\n"
        f"Выберите действие:",
        reply_markup=get_main_menu_keyboard(is_admin=db_user.is_admin)
    )
    await callback.answer()
