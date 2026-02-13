"""/start command handler."""

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

from database.models import User
from keyboards.inline import get_main_menu_keyboard
from utils.logger import logger


router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, db_user: User) -> None:
    """
    Handle /start command.

    Shows main menu for authorized users.
    (Unauthorized users are blocked by AuthMiddleware)

    Args:
        message: Telegram message
        db_user: User from database (injected by middleware)
    """
    logger.info(f"User {db_user.telegram_id} ({db_user.full_name}) started bot")

    await message.answer(
        f"👋 Привет, {db_user.full_name}!\n\n"
        f"Это бот для бронирования оборудования.\n"
        f"Выберите действие:",
        reply_markup=get_main_menu_keyboard(is_admin=db_user.is_admin)
    )


@router.callback_query(F.data == "menu:main")
async def callback_main_menu(callback: CallbackQuery, db_user: User) -> None:
    """
    Handle callback to return to main menu.

    Args:
        callback: Callback query
        db_user: User from database
    """
    await callback.message.edit_text(
        f"👋 Привет, {db_user.full_name}!\n\n"
        f"Это бот для бронирования оборудования.\n"
        f"Выберите действие:",
        reply_markup=get_main_menu_keyboard(is_admin=db_user.is_admin)
    )
    await callback.answer()
