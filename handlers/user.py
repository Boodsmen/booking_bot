"""User handlers: my bookings, equipment list, confirm, return, cancel."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from config import settings
from database.db import async_session_maker
from database.models import User, Booking
from database import crud
from keyboards.inline import (
    get_main_menu_keyboard,
    get_back_to_menu_keyboard,
    get_equipment_keyboard,
    get_equip_list_categories_keyboard,
    get_my_bookings_keyboard,
    get_booking_actions_keyboard,
    get_photo_upload_keyboard,
)
from utils.states import ConfirmStartStates, CompleteBookingStates, SearchStates
from utils.helpers import save_photo_locally
from utils.logger import logger


router = Router(name="user")


# ============== MY BOOKINGS ==============

@router.callback_query(F.data == "menu:my_bookings")
async def callback_my_bookings(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """
    Show user's bookings list.

    Args:
        callback: Callback query
        state: FSM context
        db_user: User from database
    """
    # Clear any previous state
    await state.clear()

    async with async_session_maker() as session:
        bookings = await crud.get_user_bookings(
            session,
            user_id=db_user.telegram_id,
            statuses=["pending", "active"],
        )

    if not bookings:
        await callback.message.edit_text(
            "📋 <b>Мои брони</b>\n\n"
            "У вас нет активных бронирований.",
            reply_markup=get_back_to_menu_keyboard()
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "📋 <b>Мои брони</b>\n\n"
        "Выберите бронь для просмотра деталей:",
        reply_markup=get_my_bookings_keyboard(bookings)
    )
    await callback.answer()


# ============== MY BOOKINGS PAGINATION ==============

@router.callback_query(F.data.startswith("mybookings_page:"))
async def callback_my_bookings_page(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """
    Handle "My Bookings" pagination.

    Args:
        callback: Callback query
        state: FSM context
        db_user: User from database
    """
    page = int(callback.data.split(":", 1)[1])

    async with async_session_maker() as session:
        bookings = await crud.get_user_bookings(
            session,
            user_id=db_user.telegram_id,
            statuses=["pending", "active"],
        )

    if not bookings:
        await callback.message.edit_text(
            "📋 <b>Мои брони</b>\n\n"
            "У вас нет активных бронирований.",
            reply_markup=get_back_to_menu_keyboard()
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "📋 <b>Мои брони</b>\n\n"
        "Выберите бронь для просмотра деталей:",
        reply_markup=get_my_bookings_keyboard(bookings, page=page)
    )
    await callback.answer()


# ============== BOOKING DETAILS ==============

@router.callback_query(F.data.startswith("mybooking:"))
async def callback_booking_details(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """
    Show booking details with action buttons.

    Args:
        callback: Callback query
        state: FSM context
        db_user: User from database
    """
    booking_id = int(callback.data.split(":", 1)[1])

    async with async_session_maker() as session:
        booking = await crud.get_booking_by_id(session, booking_id, load_relations=True)

    if not booking or booking.user_id != db_user.telegram_id:
        await callback.answer("Бронь не найдена", show_alert=True)
        return

    # Format booking info
    equipment_name = booking.equipment.name if booking.equipment else f"ID:{booking.equipment_id}"
    start_str = booking.start_time.strftime("%d.%m.%Y %H:%M")
    end_str = booking.end_time.strftime("%d.%m.%Y %H:%M")

    status_text = {
        "pending": "🕐 Ожидает подтверждения",
        "active": "✅ Активна",
        "completed": "☑️ Завершена",
        "cancelled": "❌ Отменена",
        "expired": "⏰ Истекла",
        "maintenance": "🔧 Тех. обслуживание",
    }.get(booking.status, booking.status)

    # Determine available actions
    now = datetime.now(timezone.utc)

    # Can confirm if pending and within 5 minutes of start time or past start
    can_confirm = (
        booking.status == "pending" and
        booking.start_time <= now + timedelta(minutes=5)
    )

    # Can complete if active
    can_complete = booking.status == "active"

    # Calculate duration
    duration = booking.end_time - booking.start_time
    hours = int(duration.total_seconds() // 3600)
    minutes = int((duration.total_seconds() % 3600) // 60)
    duration_str = f"{hours}ч {minutes}м" if minutes else f"{hours}ч"

    text = (
        f"📋 <b>Бронь #{booking.id}</b>\n\n"
        f"📦 Оборудование: <b>{equipment_name}</b>\n"
        f"📅 Начало: <b>{start_str}</b>\n"
        f"📅 Окончание: <b>{end_str}</b>\n"
        f"⏱ Длительность: <b>{duration_str}</b>\n"
        f"📊 Статус: {status_text}\n"
    )

    if booking.is_overdue:
        text += "\n⚠️ <b>Просрочен возврат!</b>\n"

    # Save booking_id for potential photo upload
    await state.update_data(current_booking_id=booking_id)

    await callback.message.edit_text(
        text,
        reply_markup=get_booking_actions_keyboard(booking, can_confirm, can_complete)
    )
    await callback.answer()


# ============== CONFIRM BOOKING START ==============

@router.callback_query(F.data.startswith("booking_confirm:"))
async def callback_confirm_start(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """
    Handle booking start confirmation.

    Args:
        callback: Callback query
        state: FSM context
        db_user: User from database
    """
    booking_id = int(callback.data.split(":", 1)[1])

    async with async_session_maker() as session:
        booking = await crud.get_booking_by_id(session, booking_id, load_relations=True)

    if not booking or booking.user_id != db_user.telegram_id:
        await callback.answer("Бронь не найдена", show_alert=True)
        return

    if booking.status != "pending":
        await callback.answer("Эту бронь нельзя подтвердить", show_alert=True)
        return

    # Check if photo is required
    requires_photo = booking.equipment.requires_photo if booking.equipment else False

    if requires_photo:
        # Start photo upload flow
        await state.set_state(ConfirmStartStates.uploading_photos)
        await state.update_data(
            confirm_booking_id=booking_id,
            photos=[],
        )

        await callback.message.edit_text(
            f"📸 <b>Загрузка фото</b>\n\n"
            f"Для подтверждения начала брони отправьте фото оборудования.\n"
            f"Можно отправить до 10 фото.\n\n"
            f"После загрузки нажмите «Готово».",
            reply_markup=get_photo_upload_keyboard()
        )
    else:
        # Confirm without photos
        async with async_session_maker() as session:
            result = await crud.confirm_booking(session, booking_id)

        if result:
            equipment_name = booking.equipment.name if booking.equipment else f"ID:{booking.equipment_id}"
            await callback.message.edit_text(
                f"✅ <b>Бронь подтверждена!</b>\n\n"
                f"📦 Оборудование: <b>{equipment_name}</b>\n\n"
                f"Не забудьте вернуть оборудование вовремя!",
                reply_markup=get_main_menu_keyboard()
            )
            logger.info(f"Booking #{booking_id} confirmed by user {db_user.telegram_id}")
        else:
            await callback.message.edit_text(
                "❌ Не удалось подтвердить бронь.",
                reply_markup=get_main_menu_keyboard()
            )

    await callback.answer()


# ============== COMPLETE BOOKING (RETURN) ==============

@router.callback_query(F.data.startswith("booking_complete:"))
async def callback_complete_booking(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """
    Handle equipment return.

    Args:
        callback: Callback query
        state: FSM context
        db_user: User from database
    """
    booking_id = int(callback.data.split(":", 1)[1])

    async with async_session_maker() as session:
        booking = await crud.get_booking_by_id(session, booking_id, load_relations=True)

    if not booking or booking.user_id != db_user.telegram_id:
        await callback.answer("Бронь не найдена", show_alert=True)
        return

    if booking.status != "active":
        await callback.answer("Эту бронь нельзя завершить", show_alert=True)
        return

    # Check if photo is required
    requires_photo = booking.equipment.requires_photo if booking.equipment else False

    if requires_photo:
        # Start photo upload flow
        await state.set_state(CompleteBookingStates.uploading_photos)
        await state.update_data(
            complete_booking_id=booking_id,
            photos=[],
        )

        await callback.message.edit_text(
            f"📸 <b>Загрузка фото</b>\n\n"
            f"Для завершения брони отправьте фото оборудования.\n"
            f"Можно отправить до 10 фото.\n\n"
            f"После загрузки нажмите «Готово».",
            reply_markup=get_photo_upload_keyboard()
        )
    else:
        # Complete without photos
        async with async_session_maker() as session:
            result = await crud.complete_booking(session, booking_id)

        if result:
            equipment_name = booking.equipment.name if booking.equipment else f"ID:{booking.equipment_id}"
            await callback.message.edit_text(
                f"✅ <b>Оборудование возвращено!</b>\n\n"
                f"📦 Оборудование: <b>{equipment_name}</b>\n\n"
                f"Спасибо за использование системы бронирования!",
                reply_markup=get_main_menu_keyboard()
            )
            logger.info(f"Booking #{booking_id} completed by user {db_user.telegram_id}")
        else:
            await callback.message.edit_text(
                "❌ Не удалось завершить бронь.",
                reply_markup=get_main_menu_keyboard()
            )

    await callback.answer()


# ============== CANCEL BOOKING ==============

@router.callback_query(F.data.startswith("booking_cancel:"))
async def callback_cancel_booking(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """
    Cancel user's booking.

    Args:
        callback: Callback query
        state: FSM context
        db_user: User from database
    """
    booking_id = int(callback.data.split(":", 1)[1])

    async with async_session_maker() as session:
        booking = await crud.get_booking_by_id(session, booking_id, load_relations=True)

        if not booking or booking.user_id != db_user.telegram_id:
            await callback.answer("Бронь не найдена", show_alert=True)
            return

        result = await crud.cancel_booking(session, booking_id)

    if result:
        equipment_name = booking.equipment.name if booking.equipment else f"ID:{booking.equipment_id}"
        await callback.message.edit_text(
            f"❌ <b>Бронь отменена</b>\n\n"
            f"📦 Оборудование: <b>{equipment_name}</b>\n\n"
            f"Слот освобожден для других пользователей.",
            reply_markup=get_main_menu_keyboard()
        )
        logger.info(f"Booking #{booking_id} cancelled by user {db_user.telegram_id}")
        await callback.answer()
    else:
        await callback.answer("Эту бронь нельзя отменить", show_alert=True)


# ============== PHOTO UPLOAD FOR CONFIRM START ==============

@router.message(ConfirmStartStates.uploading_photos, F.photo)
async def handle_confirm_photo(message: Message, state: FSMContext, db_user: User) -> None:
    """
    Handle photo upload for booking confirmation.

    Args:
        message: Message with photo
        state: FSM context
        db_user: User from database
    """
    data = await state.get_data()
    photos = data.get("photos", [])

    if len(photos) >= 10:
        await message.answer("Максимум 10 фото. Нажмите «Готово» для завершения.")
        return

    # Get the largest photo (best quality)
    photo = message.photo[-1]
    booking_id = data.get("confirm_booking_id", "unknown")
    local_path = await save_photo_locally(
        message.bot, photo.file_id, f"bookings/{booking_id}/start"
    )
    photos.append(local_path)

    await state.update_data(photos=photos)
    await message.answer(
        f"📸 Фото {len(photos)}/10 загружено.\n"
        f"Отправьте ещё или нажмите «Готово».",
        reply_markup=get_photo_upload_keyboard()
    )


@router.callback_query(ConfirmStartStates.uploading_photos, F.data == "photos:done")
async def callback_confirm_photos_done(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """
    Finish photo upload and confirm booking.

    Args:
        callback: Callback query
        state: FSM context
        db_user: User from database
    """
    data = await state.get_data()
    booking_id = data.get("confirm_booking_id")
    photos = data.get("photos", [])

    async with async_session_maker() as session:
        result = await crud.confirm_booking(session, booking_id, photos_start=photos)

    await state.clear()

    if result:
        await callback.message.edit_text(
            f"✅ <b>Бронь подтверждена!</b>\n\n"
            f"📸 Загружено фото: {len(photos)}\n\n"
            f"Не забудьте вернуть оборудование вовремя!",
            reply_markup=get_main_menu_keyboard()
        )
        logger.info(f"Booking #{booking_id} confirmed with {len(photos)} photos")
    else:
        await callback.message.edit_text(
            "❌ Не удалось подтвердить бронь.",
            reply_markup=get_main_menu_keyboard()
        )

    await callback.answer()


@router.callback_query(ConfirmStartStates.uploading_photos, F.data == "photos:skip")
async def callback_confirm_photos_skip(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """
    Skip photo upload and confirm booking without photos.

    Args:
        callback: Callback query
        state: FSM context
        db_user: User from database
    """
    data = await state.get_data()
    booking_id = data.get("confirm_booking_id")

    async with async_session_maker() as session:
        result = await crud.confirm_booking(session, booking_id)

    await state.clear()

    if result:
        await callback.message.edit_text(
            f"✅ <b>Бронь подтверждена!</b>\n\n"
            f"Не забудьте вернуть оборудование вовремя!",
            reply_markup=get_main_menu_keyboard()
        )
        logger.info(f"Booking #{booking_id} confirmed without photos")
    else:
        await callback.message.edit_text(
            "❌ Не удалось подтвердить бронь.",
            reply_markup=get_main_menu_keyboard()
        )

    await callback.answer()


@router.callback_query(ConfirmStartStates.uploading_photos, F.data == "photos:cancel")
async def callback_confirm_photos_cancel(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Cancel photo upload for confirmation."""
    await state.clear()
    await callback.message.edit_text(
        "❌ Подтверждение отменено.",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()


# ============== PHOTO UPLOAD FOR COMPLETE ==============

@router.message(CompleteBookingStates.uploading_photos, F.photo)
async def handle_complete_photo(message: Message, state: FSMContext, db_user: User) -> None:
    """
    Handle photo upload for booking completion.

    Args:
        message: Message with photo
        state: FSM context
        db_user: User from database
    """
    data = await state.get_data()
    photos = data.get("photos", [])

    if len(photos) >= 10:
        await message.answer("Максимум 10 фото. Нажмите «Готово» для завершения.")
        return

    photo = message.photo[-1]
    booking_id = data.get("complete_booking_id", "unknown")
    local_path = await save_photo_locally(
        message.bot, photo.file_id, f"bookings/{booking_id}/end"
    )
    photos.append(local_path)

    await state.update_data(photos=photos)
    await message.answer(
        f"📸 Фото {len(photos)}/10 загружено.\n"
        f"Отправьте ещё или нажмите «Готово».",
        reply_markup=get_photo_upload_keyboard()
    )


@router.callback_query(CompleteBookingStates.uploading_photos, F.data == "photos:done")
async def callback_complete_photos_done(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """
    Finish photo upload and complete booking.

    Args:
        callback: Callback query
        state: FSM context
        db_user: User from database
    """
    data = await state.get_data()
    booking_id = data.get("complete_booking_id")
    photos = data.get("photos", [])

    async with async_session_maker() as session:
        result = await crud.complete_booking(session, booking_id, photos_end=photos)

    await state.clear()

    if result:
        await callback.message.edit_text(
            f"✅ <b>Оборудование возвращено!</b>\n\n"
            f"📸 Загружено фото: {len(photos)}\n\n"
            f"Спасибо за использование системы бронирования!",
            reply_markup=get_main_menu_keyboard()
        )
        logger.info(f"Booking #{booking_id} completed with {len(photos)} photos")
    else:
        await callback.message.edit_text(
            "❌ Не удалось завершить бронь.",
            reply_markup=get_main_menu_keyboard()
        )

    await callback.answer()


@router.callback_query(CompleteBookingStates.uploading_photos, F.data == "photos:skip")
async def callback_complete_photos_skip(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """
    Skip photo upload and complete booking without photos.

    Args:
        callback: Callback query
        state: FSM context
        db_user: User from database
    """
    data = await state.get_data()
    booking_id = data.get("complete_booking_id")

    async with async_session_maker() as session:
        result = await crud.complete_booking(session, booking_id)

    await state.clear()

    if result:
        await callback.message.edit_text(
            f"✅ <b>Оборудование возвращено!</b>\n\n"
            f"Спасибо за использование системы бронирования!",
            reply_markup=get_main_menu_keyboard()
        )
        logger.info(f"Booking #{booking_id} completed without photos")
    else:
        await callback.message.edit_text(
            "❌ Не удалось завершить бронь.",
            reply_markup=get_main_menu_keyboard()
        )

    await callback.answer()


@router.callback_query(CompleteBookingStates.uploading_photos, F.data == "photos:cancel")
async def callback_complete_photos_cancel(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Cancel photo upload for completion."""
    await state.clear()
    await callback.message.edit_text(
        "❌ Возврат отменён.",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()


# ============== EQUIPMENT LIST ==============

@router.callback_query(F.data == "menu:equipment_list")
async def callback_equipment_list(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Show equipment categories for browsing."""
    await state.clear()

    async with async_session_maker() as session:
        categories = await crud.get_categories_for_user(
            session, db_user.telegram_id, db_user.is_admin
        )

    if not categories:
        await callback.message.edit_text(
            "📦 <b>Список оборудования</b>\n\n"
            "Нет доступного оборудования.",
            reply_markup=get_back_to_menu_keyboard()
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "📦 <b>Список оборудования</b>\n\n"
        "Выберите категорию:",
        reply_markup=get_equip_list_categories_keyboard(categories)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("equip_list:"))
async def callback_equip_list_category(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Show equipment in a category for browsing (not booking)."""
    category_name = callback.data.split(":", 1)[1]

    async with async_session_maker() as session:
        equipment_list = await crud.get_equipment_by_category(session, category_name)

    if not equipment_list:
        await callback.answer("В этой категории нет доступного оборудования", show_alert=True)
        return

    await callback.message.edit_text(
        f"📁 <b>{category_name}</b>\n\n"
        "Нажмите для просмотра информации:",
        reply_markup=get_equipment_keyboard(
            equipment_list, page=0, category=category_name,
            for_booking=False, back_callback="menu:equipment_list"
        )
    )
    await callback.answer()


# ============== EQUIPMENT INFO ==============

@router.callback_query(F.data.startswith("info:"))
async def callback_equipment_info(callback: CallbackQuery, db_user: User) -> None:
    """Show equipment information with availability and booking button."""
    equipment_id = int(callback.data.split(":", 1)[1])

    async with async_session_maker() as session:
        equipment = await crud.get_equipment_by_id(session, equipment_id)
        available_count = await crud.get_equipment_available_count(session, equipment_id) if equipment else 0

    if not equipment:
        await callback.answer("Оборудование не найдено", show_alert=True)
        return

    photo_req = "Да" if equipment.requires_photo else "Нет"
    status_text = "✅ Доступно" if equipment.is_available else "❌ Недоступно"
    license_text = f"\n🔢 Гос. номер: {equipment.license_plate}" if equipment.license_plate else ""

    text = (
        f"📦 <b>{equipment.name}</b>\n\n"
        f"📁 Категория: {equipment.category}{license_text}\n"
        f"📸 Требуется фото: {photo_req}\n"
        f"📊 Статус: {status_text}\n"
        f"📦 Доступно: {available_count} из {equipment.quantity}\n"
    )

    # Build keyboard with optional booking button
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    kb_builder = InlineKeyboardBuilder()
    if equipment.is_available and available_count > 0:
        kb_builder.row(
            InlineKeyboardButton(text="📅 Забронировать", callback_data=f"book_equip:{equipment_id}")
        )
    else:
        text += "\n❌ <b>Нет в наличии</b>\n"
    kb_builder.row(
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main")
    )
    keyboard = kb_builder.as_markup()

    # Send photo if available
    if equipment.photo and Path(equipment.photo).exists():
        from aiogram.types import FSInputFile
        photo_file = FSInputFile(equipment.photo)
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=photo_file,
            caption=text,
            reply_markup=keyboard
        )
    else:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


# ============== EQUIPMENT LIST PAGINATION ==============

@router.callback_query(F.data.startswith("page:None:"))
async def callback_equipment_list_page(callback: CallbackQuery, db_user: User) -> None:
    """Handle equipment list pagination (no category filter) — legacy fallback."""
    page = int(callback.data.split(":")[-1])

    async with async_session_maker() as session:
        user_cats = await crud.get_categories_for_user(
            session, db_user.telegram_id, db_user.is_admin
        )
        cat_ids = [c.id for c in user_cats] if user_cats else None
        equipment_list = await crud.get_all_equipment(
            session, only_available=True, category_ids=cat_ids
        )

    await callback.message.edit_text(
        "📦 <b>Список доступного оборудования</b>\n\n"
        "Нажмите для просмотра информации:",
        reply_markup=get_equipment_keyboard(equipment_list, page=page, category=None, for_booking=False)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("page:") & ~F.data.startswith("page:None:"))
async def callback_equip_list_category_page(callback: CallbackQuery, db_user: User) -> None:
    """Handle pagination within an equip_list category (info mode)."""
    parts = callback.data.split(":")
    category_name = parts[1]
    page = int(parts[2])

    async with async_session_maker() as session:
        equipment_list = await crud.get_equipment_by_category(session, category_name)

    await callback.message.edit_text(
        f"📁 <b>{category_name}</b>\n\n"
        "Нажмите для просмотра информации:",
        reply_markup=get_equipment_keyboard(
            equipment_list, page=page, category=category_name,
            for_booking=False, back_callback="menu:equipment_list"
        )
    )
    await callback.answer()


# ============== EQUIPMENT SEARCH ==============

@router.callback_query(F.data == "menu:search")
async def callback_search_start(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Start equipment search flow."""
    await state.set_state(SearchStates.entering_query)
    await callback.answer()
    await callback.message.edit_text(
        "🔍 <b>Поиск оборудования</b>\n\n"
        "Введите название или гос. номер для поиска:",
        reply_markup=get_back_to_menu_keyboard()
    )


@router.message(SearchStates.entering_query)
async def process_search_query(message: Message, state: FSMContext, db_user: User) -> None:
    """Process search query and show results."""
    query_text = message.text.strip()
    if len(query_text) < 2:
        await message.answer("❌ Введите минимум 2 символа для поиска.")
        return

    async with async_session_maker() as session:
        user_cats = await crud.get_categories_for_user(
            session, db_user.telegram_id, db_user.is_admin
        )
        cat_ids = [c.id for c in user_cats] if user_cats else None
        results = await crud.search_equipment(
            session, query_text, category_ids=cat_ids
        )

    await state.clear()

    if not results:
        await message.answer(
            f"🔍 По запросу «{query_text}» ничего не найдено.",
            reply_markup=get_main_menu_keyboard(is_admin=db_user.is_admin)
        )
        return

    await message.answer(
        f"🔍 <b>Результаты поиска</b> ({len(results)}):\n\n"
        "Нажмите для просмотра информации:",
        reply_markup=get_equipment_keyboard(results, page=0, category=None, for_booking=False)
    )
