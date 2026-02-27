"""Обработчики потока бронирования: категория → оборудование → дата/время → подтверждение."""

from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from config import settings
from database.db import async_session_maker
from database.models import User, Booking
from database import crud
from keyboards.inline import (
    get_categories_keyboard,
    get_equipment_keyboard,
    get_calendar_keyboard,
    get_time_keyboard,
    get_booking_confirm_keyboard,
    get_main_menu_keyboard,
)
from utils.states import BookingStates
from utils.logger import logger
from utils.helpers import now_msk, now_utc, parse_msk_naive


router = Router(name="booking")


# ============== НАЧАЛО БРОНИРОВАНИЯ ==============

@router.callback_query(F.data == "menu:book")
async def callback_start_booking(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Начало потока бронирования — показ категорий."""
    await state.clear()

    async with async_session_maker() as session:
        categories = await crud.get_categories_for_user(
            session, db_user.telegram_id, db_user.is_admin
        )

    if not categories:
        await callback.message.edit_text(
            "😔 Нет доступного оборудования для бронирования.\n\n"
            "Обратитесь к администратору.",
            reply_markup=get_main_menu_keyboard()
        )
        await callback.answer()
        return

    await state.set_state(BookingStates.choosing_category)

    category_names = [c.name for c in categories]
    await callback.message.edit_text(
        "📁 Выберите категорию оборудования:",
        reply_markup=get_categories_keyboard(category_names)
    )
    await callback.answer()


# ============== ВЫБОР КАТЕГОРИИ ==============

@router.callback_query(BookingStates.choosing_category, F.data.startswith("category:"))
async def callback_select_category(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Выбор категории — показ списка оборудования."""
    category = callback.data.split(":", 1)[1]

    async with async_session_maker() as session:
        equipment_list = await crud.get_equipment_by_category(session, category)

    if not equipment_list:
        await callback.answer("В этой категории нет доступного оборудования", show_alert=True)
        return

    await state.update_data(category=category, equipment_list_ids=[e.id for e in equipment_list])
    await state.set_state(BookingStates.choosing_equipment)

    await callback.message.edit_text(
        f"📦 Категория: <b>{category}</b>\n\n"
        f"Выберите оборудование:",
        reply_markup=get_equipment_keyboard(equipment_list, page=0, category=category)
    )
    await callback.answer()


# ============== ПАГИНАЦИЯ ОБОРУДОВАНИЯ ==============

@router.callback_query(BookingStates.choosing_equipment, F.data.startswith("page:"))
async def callback_equipment_page(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Пагинация списка оборудования."""
    parts = callback.data.split(":")
    category = parts[1]
    page = int(parts[2])

    async with async_session_maker() as session:
        equipment_list = await crud.get_equipment_by_category(session, category)

    await callback.message.edit_text(
        f"📦 Категория: <b>{category}</b>\n\n"
        f"Выберите оборудование:",
        reply_markup=get_equipment_keyboard(equipment_list, page=page, category=category)
    )
    await callback.answer()


# ============== ВЫБОР ОБОРУДОВАНИЯ ==============

@router.callback_query(BookingStates.choosing_equipment, F.data.startswith("equip:"))
async def callback_select_equipment(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Выбор оборудования — показ календаря даты начала."""
    equipment_id = int(callback.data.split(":", 1)[1])

    async with async_session_maker() as session:
        equipment = await crud.get_equipment_by_id(session, equipment_id)

    if not equipment or not equipment.is_available:
        await callback.answer("Это оборудование недоступно", show_alert=True)
        return

    await state.update_data(
        equipment_id=equipment_id,
        equipment_name=equipment.name,
        requires_photo=equipment.requires_photo,
    )
    await state.set_state(BookingStates.choosing_date_start)

    now = now_msk()
    max_date = now + timedelta(days=settings.max_future_booking_days)

    await callback.message.edit_text(
        f"📦 Оборудование: <b>{equipment.name}</b>\n\n"
        f"📅 Выберите дату <b>начала</b> бронирования:",
        reply_markup=get_calendar_keyboard(
            year=now.year,
            month=now.month,
            callback_prefix="date_start",
            min_date=now,
            max_date=max_date,
            back_callback="booking:back_to_equipment",
        )
    )
    await callback.answer()


# ============== НАВИГАЦИЯ ПО КАЛЕНДАРЮ ==============

@router.callback_query(BookingStates.choosing_date_start, F.data.startswith("cal:date_start:"))
async def callback_calendar_start_nav(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Навигация по календарю даты начала."""
    parts = callback.data.split(":")
    year = int(parts[2])
    month = int(parts[3])

    data = await state.get_data()
    equipment_name = data.get("equipment_name", "")

    now = now_msk()
    max_date = now + timedelta(days=settings.max_future_booking_days)

    await callback.message.edit_text(
        f"📦 Оборудование: <b>{equipment_name}</b>\n\n"
        f"📅 Выберите дату <b>начала</b> бронирования:",
        reply_markup=get_calendar_keyboard(
            year=year,
            month=month,
            callback_prefix="date_start",
            min_date=now,
            max_date=max_date,
            back_callback="booking:back_to_equipment",
        )
    )
    await callback.answer()


@router.callback_query(BookingStates.choosing_date_end, F.data.startswith("cal:date_end:"))
async def callback_calendar_end_nav(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Навигация по календарю даты окончания."""
    parts = callback.data.split(":")
    year = int(parts[2])
    month = int(parts[3])

    data = await state.get_data()
    equipment_name = data.get("equipment_name", "")
    start_date = data.get("start_date", "")
    start_time = data.get("start_time", "")

    # Минимальная дата — дата начала, максимальная — начало + макс. длительность
    start_dt = datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
    max_date = start_dt + timedelta(hours=settings.max_booking_duration_hours)

    await callback.message.edit_text(
        f"📦 Оборудование: <b>{equipment_name}</b>\n"
        f"📅 Начало: <b>{start_date} {start_time}</b>\n\n"
        f"📅 Выберите дату <b>окончания</b> бронирования:",
        reply_markup=get_calendar_keyboard(
            year=year,
            month=month,
            callback_prefix="date_end",
            min_date=start_dt,
            max_date=max_date,
            back_callback="booking:back_to_time_start",
        )
    )
    await callback.answer()


# ============== ВЫБОР ДАТЫ НАЧАЛА ==============

@router.callback_query(BookingStates.choosing_date_start, F.data.startswith("date_start:"))
async def callback_select_start_date(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Выбор даты начала — показ клавиатуры времени."""
    date_str = callback.data.split(":", 1)[1]

    await state.update_data(start_date=date_str)
    await state.set_state(BookingStates.choosing_time_start)

    data = await state.get_data()
    equipment_name = data.get("equipment_name", "")

    # Отсекаем прошедшее время, если выбран сегодняшний день
    now = now_msk()
    min_time = now if date_str == now.strftime("%Y-%m-%d") else None

    await callback.message.edit_text(
        f"📦 Оборудование: <b>{equipment_name}</b>\n"
        f"📅 Дата начала: <b>{date_str}</b>\n\n"
        f"🕐 Выберите <b>время начала</b>:",
        reply_markup=get_time_keyboard(
            callback_prefix="time_start",
            min_time=min_time,
            back_callback=f"booking:back_to_date_start",
        )
    )
    await callback.answer()


# ============== ВЫБОР ВРЕМЕНИ НАЧАЛА ==============

@router.callback_query(BookingStates.choosing_time_start, F.data.startswith("time_start:"))
async def callback_select_start_time(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Выбор времени начала — показ календаря даты окончания."""
    time_str = callback.data.split(":", 1)[1]

    await state.update_data(start_time=time_str)
    await state.set_state(BookingStates.choosing_date_end)

    data = await state.get_data()
    equipment_name = data.get("equipment_name", "")
    start_date = data.get("start_date", "")

    start_dt = datetime.strptime(f"{start_date} {time_str}", "%Y-%m-%d %H:%M")
    max_date = start_dt + timedelta(hours=settings.max_booking_duration_hours)

    await callback.message.edit_text(
        f"📦 Оборудование: <b>{equipment_name}</b>\n"
        f"📅 Начало: <b>{start_date} {time_str}</b>\n\n"
        f"📅 Выберите дату <b>окончания</b> бронирования:",
        reply_markup=get_calendar_keyboard(
            year=start_dt.year,
            month=start_dt.month,
            callback_prefix="date_end",
            min_date=start_dt,
            max_date=max_date,
            back_callback="booking:back_to_time_start",
        )
    )
    await callback.answer()


# ============== ВЫБОР ДАТЫ ОКОНЧАНИЯ ==============

@router.callback_query(BookingStates.choosing_date_end, F.data.startswith("date_end:"))
async def callback_select_end_date(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Выбор даты окончания — показ клавиатуры времени."""
    date_str = callback.data.split(":", 1)[1]

    await state.update_data(end_date=date_str)
    await state.set_state(BookingStates.choosing_time_end)

    data = await state.get_data()
    equipment_name = data.get("equipment_name", "")
    start_date = data.get("start_date", "")
    start_time = data.get("start_time", "")

    await callback.message.edit_text(
        f"📦 Оборудование: <b>{equipment_name}</b>\n"
        f"📅 Начало: <b>{start_date} {start_time}</b>\n"
        f"📅 Дата окончания: <b>{date_str}</b>\n\n"
        f"🕐 Выберите <b>время окончания</b>:",
        reply_markup=get_time_keyboard(
            callback_prefix="time_end",
            back_callback="booking:back_to_date_end",
        )
    )
    await callback.answer()


# ============== ВЫБОР ВРЕМЕНИ ОКОНЧАНИЯ ==============

@router.callback_query(BookingStates.choosing_time_end, F.data.startswith("time_end:"))
async def callback_select_end_time(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Выбор времени окончания — показ сводки для подтверждения."""
    time_str = callback.data.split(":", 1)[1]

    await state.update_data(end_time=time_str)
    await state.set_state(BookingStates.confirming)

    data = await state.get_data()
    equipment_name = data.get("equipment_name", "")
    start_date = data.get("start_date", "")
    start_time = data.get("start_time", "")
    end_date = data.get("end_date", "")

    # Пользователь вводит время в МСК, конвертируем в UTC для сравнения
    start_dt = parse_msk_naive(start_date, start_time)
    end_dt = parse_msk_naive(end_date, time_str)

    # Проверяем, что время начала ещё не прошло
    if start_dt < now_utc():
        await callback.answer("Выбранное время начала уже в прошлом. Создайте новую бронь.", show_alert=True)
        await state.clear()
        await callback.message.edit_text("❌ Время бронирования истекло.", reply_markup=get_main_menu_keyboard())
        return

    if end_dt <= start_dt:
        await callback.answer("Время окончания должно быть позже начала!", show_alert=True)
        await state.set_state(BookingStates.choosing_time_end)
        return

    duration = end_dt - start_dt
    hours = int(duration.total_seconds() // 3600)
    minutes = int((duration.total_seconds() % 3600) // 60)
    duration_str = f"{hours}ч {minutes}м" if minutes else f"{hours}ч"

    await callback.message.edit_text(
        f"📋 <b>Подтверждение бронирования</b>\n\n"
        f"📦 Оборудование: <b>{equipment_name}</b>\n"
        f"📅 Начало: <b>{start_date} {start_time}</b>\n"
        f"📅 Окончание: <b>{end_date} {time_str}</b>\n"
        f"⏱ Длительность: <b>{duration_str}</b>\n\n"
        f"Подтвердить бронирование?",
        reply_markup=get_booking_confirm_keyboard()
    )
    await callback.answer()


# ============== ПОДТВЕРЖДЕНИЕ БРОНИРОВАНИЯ ==============

@router.callback_query(BookingStates.confirming, F.data == "booking:confirm")
async def callback_confirm_booking(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Подтверждение и создание брони."""
    data = await state.get_data()

    equipment_id = data.get("equipment_id")
    equipment_name = data.get("equipment_name", "")
    start_date = data.get("start_date", "")
    start_time = data.get("start_time", "")
    end_date = data.get("end_date", "")
    end_time = data.get("end_time", "")

    # Время пользователя в МСК → UTC
    start_dt = parse_msk_naive(start_date, start_time)
    end_dt = parse_msk_naive(end_date, end_time)

    # Повторная проверка: время начала не в прошлом
    now = now_utc()
    if start_dt < now:
        await callback.answer("Выбранное время уже в прошлом. Создайте новую бронь.", show_alert=True)
        await state.clear()
        await callback.message.edit_text("❌ Время бронирования истекло.", reply_markup=get_main_menu_keyboard())
        return

    async with async_session_maker() as session:
        result = await crud.create_booking(
            session=session,
            equipment_id=equipment_id,
            user_id=db_user.telegram_id,
            start_time=start_dt,
            end_time=end_dt,
        )

    await state.clear()

    if isinstance(result, str):
        await callback.message.edit_text(
            f"❌ <b>Ошибка бронирования</b>\n\n"
            f"{result}\n\n"
            f"Попробуйте выбрать другое время.",
            reply_markup=get_main_menu_keyboard()
        )
        logger.warning(f"Booking failed for user {db_user.telegram_id}: {result}")
    else:
        booking: Booking = result
        await callback.message.edit_text(
            f"✅ <b>Бронь создана!</b>\n\n"
            f"📦 Оборудование: <b>{equipment_name}</b>\n"
            f"📅 Начало: <b>{start_date} {start_time}</b>\n"
            f"📅 Окончание: <b>{end_date} {end_time}</b>\n"
            f"🔢 Номер брони: <b>#{booking.id}</b>\n\n"
            f"⚠️ Не забудьте подтвердить начало использования!\n"
            f"Бронь будет отменена, если не подтвердить в течение "
            f"{settings.confirmation_timeout_minutes} минут после времени начала.",
            reply_markup=get_main_menu_keyboard()
        )
        logger.info(f"Booking #{booking.id} created for user {db_user.telegram_id}")

    await callback.answer()


# ============== ОТМЕНА СОЗДАНИЯ БРОНИ ==============

@router.callback_query(F.data == "booking:cancel")
async def callback_cancel_booking_flow(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Отмена создания брони."""
    await state.clear()

    await callback.message.edit_text(
        f"❌ Создание брони отменено.\n\n"
        f"Выберите действие:",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()


# ============== БРОНИРОВАНИЕ СО СТРАНИЦЫ ОБОРУДОВАНИЯ ==============

@router.callback_query(F.data.startswith("book_equip:"))
async def callback_book_from_info(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Начало бронирования прямо со страницы информации об оборудовании."""
    equipment_id = int(callback.data.split(":", 1)[1])

    async with async_session_maker() as session:
        equipment = await crud.get_equipment_by_id(session, equipment_id)
        available = await crud.get_equipment_available_count(session, equipment_id)

    if not equipment or not equipment.is_available:
        await callback.answer("Это оборудование недоступно", show_alert=True)
        return

    if available <= 0:
        await callback.answer("Нет доступных единиц для бронирования", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        equipment_id=equipment_id,
        equipment_name=equipment.name,
        requires_photo=equipment.requires_photo,
    )
    await state.set_state(BookingStates.choosing_date_start)

    now = now_msk()
    max_date = now + timedelta(days=settings.max_future_booking_days)

    await callback.message.edit_text(
        f"📦 Оборудование: <b>{equipment.name}</b>\n\n"
        f"📅 Выберите дату <b>начала</b> бронирования:",
        reply_markup=get_calendar_keyboard(
            year=now.year,
            month=now.month,
            callback_prefix="date_start",
            min_date=now,
            max_date=max_date,
            back_callback="booking:back_to_equipment",
        )
    )
    await callback.answer()


# ============== НАВИГАЦИЯ НАЗАД ==============

@router.callback_query(F.data == "booking:back_to_equipment")
async def callback_back_to_equipment(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Назад к списку оборудования."""
    data = await state.get_data()
    category = data.get("category")
    if not category:
        await state.clear()
        await callback.message.edit_text("Выберите категорию:", reply_markup=get_main_menu_keyboard())
        await callback.answer()
        return
    async with async_session_maker() as session:
        equipment_list = await crud.get_equipment_by_category(session, category)
    await state.set_state(BookingStates.choosing_equipment)
    await callback.message.edit_text(
        f"📦 Категория: <b>{category}</b>\n\nВыберите оборудование:",
        reply_markup=get_equipment_keyboard(equipment_list, page=0, category=category)
    )
    await callback.answer()


@router.callback_query(F.data == "booking:back_to_date_start")
async def callback_back_to_date_start(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Назад к выбору даты начала."""
    data = await state.get_data()
    equipment_name = data.get("equipment_name", "")
    now = now_msk()
    max_date = now + timedelta(days=settings.max_future_booking_days)
    await state.set_state(BookingStates.choosing_date_start)
    await callback.message.edit_text(
        f"📦 Оборудование: <b>{equipment_name}</b>\n\n📅 Выберите дату <b>начала</b> бронирования:",
        reply_markup=get_calendar_keyboard(
            year=now.year, month=now.month, callback_prefix="date_start",
            min_date=now, max_date=max_date, back_callback="booking:back_to_equipment",
        )
    )
    await callback.answer()


@router.callback_query(F.data == "booking:back_to_time_start")
async def callback_back_to_time_start(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Назад к выбору времени начала."""
    data = await state.get_data()
    equipment_name = data.get("equipment_name", "")
    start_date = data.get("start_date", "")
    now = now_msk()
    min_time = now if start_date == now.strftime("%Y-%m-%d") else None
    await state.set_state(BookingStates.choosing_time_start)
    await callback.message.edit_text(
        f"📦 Оборудование: <b>{equipment_name}</b>\n"
        f"📅 Дата начала: <b>{start_date}</b>\n\n🕐 Выберите <b>время начала</b>:",
        reply_markup=get_time_keyboard(
            callback_prefix="time_start", min_time=min_time,
            back_callback="booking:back_to_date_start",
        )
    )
    await callback.answer()


@router.callback_query(F.data == "booking:back_to_date_end")
async def callback_back_to_date_end(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Назад к выбору даты окончания."""
    data = await state.get_data()
    equipment_name = data.get("equipment_name", "")
    start_date = data.get("start_date", "")
    start_time = data.get("start_time", "")
    start_dt = datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
    max_date = start_dt + timedelta(hours=settings.max_booking_duration_hours)
    await state.set_state(BookingStates.choosing_date_end)
    await callback.message.edit_text(
        f"📦 Оборудование: <b>{equipment_name}</b>\n"
        f"📅 Начало: <b>{start_date} {start_time}</b>\n\n📅 Выберите дату <b>окончания</b>:",
        reply_markup=get_calendar_keyboard(
            year=start_dt.year, month=start_dt.month, callback_prefix="date_end",
            min_date=start_dt, max_date=max_date, back_callback="booking:back_to_time_start",
        )
    )
    await callback.answer()


# ============== ЗАГЛУШКА NOOP ==============

@router.callback_query(F.data == "noop")
async def callback_noop(callback: CallbackQuery) -> None:
    """Обработка noop-коллбэков (заголовки календаря, счётчики страниц и т.п.)."""
    await callback.answer()
