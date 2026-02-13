"""Admin handlers with button-based interface."""

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path
from functools import wraps

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from database.db import async_session_maker
from database.models import User
from database import crud
from keyboards.inline import (
    get_admin_main_menu_keyboard,
    get_admin_equipment_menu_keyboard,
    get_admin_users_menu_keyboard,
    get_admin_bookings_menu_keyboard,
    get_admin_maintenance_menu_keyboard,
    get_admin_back_keyboard,
    get_equipment_action_keyboard,
    get_admin_booking_actions_keyboard,
    get_back_to_booking_keyboard,
    get_equipment_keyboard,
    get_calendar_keyboard,
    get_time_keyboard,
    get_db_categories_keyboard,
    get_user_category_select_keyboard,
    get_report_filter_keyboard,
    get_report_period_keyboard,
)
from utils.states import AddEquipmentStates, AddUserStates, MaintenanceStates, ReportStates, ImportStates
from keyboards.inline import get_db_categories_keyboard as get_db_cats_kb
from utils.helpers import format_booking_info, now_msk
from utils.logger import logger
from reports.generator import generate_report
from services.import_excel import parse_equipment_excel


router = Router(name="admin")


# ============== ADMIN CHECK DECORATOR ==============

def admin_only(handler):
    """Decorator to check if user is admin."""
    @wraps(handler)
    async def wrapper(event, state: FSMContext, db_user: User, **kwargs):
        if not db_user.is_admin:
            if isinstance(event, Message):
                await event.answer("⛔ У вас нет прав администратора.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ У вас нет прав администратора.", show_alert=True)
            return

        sig = inspect.signature(handler)
        handler_params = set(sig.parameters.keys())
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in handler_params}

        return await handler(event, state, db_user, **filtered_kwargs)
    return wrapper


# ============== ADMIN MAIN MENU ==============

@router.message(Command("admin"))
@admin_only
async def cmd_admin(message: Message, state: FSMContext, db_user: User) -> None:
    await state.clear()
    await message.answer(
        "⚙️ <b>Панель администратора</b>\n\nВыберите раздел:",
        reply_markup=get_admin_main_menu_keyboard()
    )


@router.callback_query(F.data == "admin:main")
@admin_only
async def callback_admin_main(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    await state.clear()
    await callback.message.edit_text(
        "⚙️ <b>Панель администратора</b>\n\nВыберите раздел:",
        reply_markup=get_admin_main_menu_keyboard()
    )
    await callback.answer()


# ============== EQUIPMENT MENU ==============

@router.callback_query(F.data == "admin:equipment_menu")
@admin_only
async def callback_equipment_menu(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    await state.clear()
    await callback.message.edit_text(
        "📦 <b>Управление оборудованием</b>\n\nВыберите действие:",
        reply_markup=get_admin_equipment_menu_keyboard()
    )
    await callback.answer()


# ============== ADD EQUIPMENT INFO ==============

@router.callback_query(F.data == "admin:add_equipment_info")
@admin_only
async def callback_add_equipment_info(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    instruction = """
📦 <b>Добавление оборудования</b>

<b>Как работает:</b>
1️⃣ Выбираете <b>категорию</b> из существующих
2️⃣ Вводите <b>название</b> оборудования
3️⃣ Указываете <b>гос. номер</b> (для автомобилей)
4️⃣ Указываете, нужны ли <b>фотографии</b> при получении/возврате

Нажмите кнопку ниже, чтобы начать добавление.
"""

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="➕ Начать добавление",
            callback_data="admin:start_add_equipment"
        )
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="admin:equipment_menu")
    )

    await callback.message.edit_text(instruction, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "admin:start_add_equipment")
@admin_only
async def callback_start_add_equipment(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Start equipment adding - select category from DB."""
    async with async_session_maker() as session:
        categories = await crud.get_all_categories_from_db(session)

    if not categories:
        await callback.answer("Нет категорий в БД. Сначала импортируйте оборудование.", show_alert=True)
        return

    await state.set_state(AddEquipmentStates.waiting_category)

    await callback.message.edit_text(
        "📦 <b>Добавление оборудования</b>\n\n"
        "Шаг 1 из 4: Выберите категорию:",
        reply_markup=get_db_categories_keyboard(
            categories, callback_prefix="admin_cat", back_callback="admin:equipment_menu"
        )
    )
    await callback.answer()


# ============== LIST ALL EQUIPMENT ==============

@router.callback_query(F.data == "admin:list_all_equipment")
@admin_only
async def callback_list_all_equipment(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Show category buttons to browse equipment."""
    async with async_session_maker() as session:
        categories = await crud.get_all_categories_from_db(session)

    if not categories:
        await callback.message.edit_text(
            "📦 <b>Список оборудования</b>\n\n❌ Оборудование не добавлено.",
            reply_markup=get_admin_back_keyboard("admin:equipment_menu")
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "📦 <b>Все оборудование</b>\n\nВыберите категорию:",
        reply_markup=get_db_cats_kb(categories, callback_prefix="admin_equip_cat", back_callback="admin:equipment_menu")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_equip_cat:"))
@admin_only
async def callback_admin_equip_by_category(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Show paginated equipment list for a category."""
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    category_id = int(callback.data.split(":")[1])
    page = 0
    # Support page in callback: admin_equip_cat:ID:PAGE
    parts = callback.data.split(":")
    if len(parts) == 3:
        page = int(parts[2])

    async with async_session_maker() as session:
        category = await crud.get_category_by_id(session, category_id)
        all_eq = await crud.get_all_equipment(session, only_available=False)

    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    items = [eq for eq in all_eq if eq.category_id == category_id]

    ITEMS_PER_PAGE = 10
    total = len(items)
    total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    page_items = items[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]

    lines = [f"📦 <b>{category.name}</b> ({total} шт.)\n"]
    lines.append("🟢 В обороте | 🔴 Снято | 📷 Фото\n")
    for eq in page_items:
        status = "🟢" if eq.is_available else "🔴"
        photo_mark = " 📷" if eq.requires_photo else ""
        plate = f" [{eq.license_plate}]" if eq.license_plate else ""
        qty = f" ×{eq.quantity}" if eq.quantity > 1 else ""
        lines.append(f"{status} {eq.name}{plate}{photo_mark}{qty}")

    builder = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"admin_equip_cat:{category_id}:{page-1}"))
    if total_pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"admin_equip_cat:{category_id}:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="◀️ К категориям", callback_data="admin:list_all_equipment"))
    builder.row(InlineKeyboardButton(text="◀️ Управление", callback_data="admin:equipment_menu"))

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await callback.answer()


# ============== LIST DISABLED EQUIPMENT ==============

@router.callback_query(F.data == "admin:list_disabled_equipment")
@admin_only
async def callback_list_disabled_equipment(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    async with async_session_maker() as session:
        all_equipment = await crud.get_all_equipment(session, only_available=False)

    disabled = [eq for eq in all_equipment if not eq.is_available]

    if not disabled:
        await callback.message.edit_text(
            "🔴 <b>Снятое с оборота оборудование</b>\n\n✅ Все оборудование активно!",
            reply_markup=get_admin_back_keyboard("admin:equipment_menu")
        )
        await callback.answer()
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()

    lines = ["🔴 <b>Снятое с оборота оборудование</b>\n"]
    lines.append("Нажмите на кнопку, чтобы вернуть в оборот:\n")

    for eq in disabled:
        photo_mark = " 📷" if eq.requires_photo else ""
        lines.append(f"• ID:{eq.id} - {eq.name} ({eq.category}){photo_mark}")

        builder.row(
            InlineKeyboardButton(
                text=f"🟢 Вернуть: {eq.name}",
                callback_data=f"admin:enable_eq:{eq.id}"
            )
        )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="admin:equipment_menu")
    )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=builder.as_markup()
    )
    await callback.answer()


# ============== MANAGE EQUIPMENT INFO ==============

@router.callback_query(F.data == "admin:manage_equipment_info")
@admin_only
async def callback_manage_equipment_info(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    instruction = """
🔧 <b>Управление оборудованием</b>

<b>Что это делает:</b>
Позволяет временно снять оборудование с оборота или вернуть его обратно.

<b>Когда использовать:</b>
• 🔴 <b>Снять с оборота</b> — ремонт, недоступно, передано, списано
• 🟢 <b>Вернуть в оборот</b> — ремонт завершён, снова доступно

<b>Как это работает:</b>
1️⃣ Перейдите в «📋 Все оборудование» — найдите нужный ID
2️⃣ Перейдите в «🔴 Снятое с оборота» — нажмите кнопку «Вернуть»
3️⃣ Или используйте кнопки ниже для управления по ID

<b>💡 Совет:</b>
Для ТО (тех. обслуживания) используйте раздел «🔧 Тех. обслуживание» — он блокирует конкретный период.
"""

    await callback.message.edit_text(
        instruction,
        reply_markup=get_admin_back_keyboard("admin:equipment_menu")
    )
    await callback.answer()


# ============== ENABLE/DISABLE EQUIPMENT ==============

@router.callback_query(F.data.startswith("admin:enable_eq:"))
@admin_only
async def callback_enable_equipment(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    equipment_id = int(callback.data.split(":")[2])

    async with async_session_maker() as session:
        equipment = await crud.get_equipment_by_id(session, equipment_id)
        if not equipment:
            await callback.answer("❌ Оборудование не найдено", show_alert=True)
            return
        await crud.update_equipment_availability(session, equipment_id, True)

    logger.info(f"Admin {db_user.telegram_id} enabled equipment {equipment_id}")
    await callback.answer(f"✅ {equipment.name} возвращено в оборот!", show_alert=True)
    await callback_list_disabled_equipment(callback, state, db_user)


@router.callback_query(F.data.startswith("admin:disable_eq:"))
@admin_only
async def callback_disable_equipment(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    equipment_id = int(callback.data.split(":")[2])

    async with async_session_maker() as session:
        equipment = await crud.get_equipment_by_id(session, equipment_id)
        if not equipment:
            await callback.answer("❌ Оборудование не найдено", show_alert=True)
            return
        await crud.update_equipment_availability(session, equipment_id, False)

    logger.info(f"Admin {db_user.telegram_id} disabled equipment {equipment_id}")
    await callback.answer(f"🔴 {equipment.name} снято с оборота!", show_alert=True)
    await callback_equipment_menu(callback, state, db_user)


# ============== ADD EQUIPMENT FLOW ==============

@router.callback_query(F.data.startswith("admin_cat:"), AddEquipmentStates.waiting_category)
@admin_only
async def process_category_button(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Process category selection from DB categories."""
    category_id = int(callback.data.split(":", 1)[1])

    async with async_session_maker() as session:
        category = await crud.get_category_by_id(session, category_id)

    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    await state.update_data(equipment_category=category.name, equipment_category_id=category.id)
    await state.set_state(AddEquipmentStates.waiting_name)

    await callback.message.edit_text(
        f"✅ Категория: <b>{category.name}</b>\n\n"
        f"Шаг 2 из 4: Введите название оборудования\n\n"
        f"Например: Toyota Camry, Ноутбук Dell XPS 15, Видеокамера Sony",
        reply_markup=get_admin_back_keyboard("admin:equipment_menu")
    )
    await callback.answer()


@router.message(AddEquipmentStates.waiting_name)
@admin_only
async def process_equipment_name(message: Message, state: FSMContext, db_user: User) -> None:
    name = message.text.strip()

    if len(name) < 3:
        await message.answer("❌ Название слишком короткое. Минимум 3 символа.\n\nПопробуйте еще раз:")
        return

    await state.update_data(equipment_name=name)
    await state.set_state(AddEquipmentStates.waiting_license_plate)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⏭️ Пропустить", callback_data="license:skip"))
    builder.row(InlineKeyboardButton(text="◀️ Отмена", callback_data="admin:equipment_menu"))

    data = await state.get_data()
    await message.answer(
        f"✅ Категория: <b>{data['equipment_category']}</b>\n"
        f"✅ Название: <b>{name}</b>\n\n"
        f"Шаг 3 из 4: Введите гос. номер (для автомобилей)\n\n"
        f"Или нажмите «Пропустить».",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "license:skip", AddEquipmentStates.waiting_license_plate)
@admin_only
async def process_license_skip(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    await state.update_data(equipment_license_plate=None)
    await state.set_state(AddEquipmentStates.waiting_photo_required)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да", callback_data="photo_req:yes"),
        InlineKeyboardButton(text="❌ Нет", callback_data="photo_req:no"),
    )

    data = await state.get_data()
    await callback.message.edit_text(
        f"✅ Категория: <b>{data['equipment_category']}</b>\n"
        f"✅ Название: <b>{data['equipment_name']}</b>\n"
        f"✅ Гос. номер: <i>не указан</i>\n\n"
        f"Шаг 4 из 4: Требуются ли фотографии при получении/возврате?",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.message(AddEquipmentStates.waiting_license_plate)
@admin_only
async def process_license_plate(message: Message, state: FSMContext, db_user: User) -> None:
    license_plate = message.text.strip().upper()

    if len(license_plate) < 4:
        await message.answer("❌ Номер слишком короткий. Минимум 4 символа.\n\nПопробуйте или нажмите «Пропустить»:")
        return

    async with async_session_maker() as session:
        existing = await crud.get_equipment_by_license_plate(session, license_plate)
        if existing:
            await message.answer(
                f"❌ Оборудование с номером <b>{license_plate}</b> уже существует!\n"
                f"Существующее: {existing.name} (ID: {existing.id})\n\n"
                f"Введите другой номер или нажмите «Пропустить»:"
            )
            return

    await state.update_data(equipment_license_plate=license_plate)
    await state.set_state(AddEquipmentStates.waiting_photo_required)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да", callback_data="photo_req:yes"),
        InlineKeyboardButton(text="❌ Нет", callback_data="photo_req:no"),
    )

    data = await state.get_data()
    await message.answer(
        f"✅ Категория: <b>{data['equipment_category']}</b>\n"
        f"✅ Название: <b>{data['equipment_name']}</b>\n"
        f"✅ Гос. номер: <b>{license_plate}</b>\n\n"
        f"Шаг 4 из 4: Требуются ли фотографии при получении/возврате?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("photo_req:"), AddEquipmentStates.waiting_photo_required)
@admin_only
async def process_photo_required(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    requires_photo = callback.data.split(":")[1] == "yes"
    await state.update_data(equipment_requires_photo=requires_photo)
    await state.set_state(AddEquipmentStates.waiting_photo)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⏭ Пропустить", callback_data="equip_photo:skip"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:equipment_menu"))

    await callback.message.edit_text(
        "📸 <b>Фото оборудования</b>\n\n"
        "Отправьте фото оборудования или нажмите «Пропустить».",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


async def _finish_add_equipment(event, state: FSMContext, db_user: User, photo_path: str | None = None):
    """Finalize equipment creation."""
    data = await state.get_data()

    async with async_session_maker() as session:
        equipment = await crud.create_equipment(
            session,
            name=data["equipment_name"],
            category=data["equipment_category"],
            category_id=data.get("equipment_category_id"),
            license_plate=data.get("equipment_license_plate"),
            requires_photo=data.get("equipment_requires_photo", False),
        )
        if photo_path:
            equipment.photo = photo_path
            await session.commit()

    await state.clear()

    logger.info(
        f"Admin {db_user.telegram_id} added equipment: "
        f"{equipment.name} (ID:{equipment.id}, category:{equipment.category})"
    )

    photo_text = "Да ✅" if equipment.requires_photo else "Нет ❌"
    license_text = f"<b>{equipment.license_plate}</b>" if equipment.license_plate else "<i>не указан</i>"
    photo_status = "✅ Загружено" if photo_path else "<i>нет</i>"

    text = (
        f"✅ <b>Оборудование добавлено!</b>\n\n"
        f"<b>Название:</b> {equipment.name}\n"
        f"<b>Категория:</b> {equipment.category}\n"
        f"<b>Гос. номер:</b> {license_text}\n"
        f"<b>Требуются фото:</b> {photo_text}\n"
        f"<b>Фото:</b> {photo_status}\n"
        f"<b>ID:</b> {equipment.id}"
    )

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=get_admin_back_keyboard("admin:equipment_menu"))
        await event.answer("✅ Добавлено!", show_alert=True)
    else:
        await event.answer(text, reply_markup=get_admin_back_keyboard("admin:equipment_menu"))


@router.callback_query(F.data == "equip_photo:skip", AddEquipmentStates.waiting_photo)
@admin_only
async def process_equipment_photo_skip(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    await _finish_add_equipment(callback, state, db_user)


@router.message(AddEquipmentStates.waiting_photo, F.photo)
@admin_only
async def process_equipment_photo(message: Message, state: FSMContext, db_user: User) -> None:
    """Save equipment photo locally."""
    photo = message.photo[-1]  # Best quality
    photos_dir = Path("data/photos/equipment")
    photos_dir.mkdir(parents=True, exist_ok=True)

    file = await message.bot.get_file(photo.file_id)
    ext = Path(file.file_path).suffix or ".jpg"
    local_name = f"{photo.file_unique_id}{ext}"
    local_path = photos_dir / local_name

    await message.bot.download_file(file.file_path, destination=local_path)

    await _finish_add_equipment(message, state, db_user, photo_path=str(local_path))


@router.message(AddEquipmentStates.waiting_photo)
@admin_only
async def process_equipment_photo_invalid(message: Message, state: FSMContext, db_user: User) -> None:
    await message.answer("❌ Отправьте фото или нажмите «Пропустить».")


# ============== USERS MENU ==============

@router.callback_query(F.data == "admin:users_menu")
@admin_only
async def callback_users_menu(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    await state.clear()
    await callback.message.edit_text(
        "👥 <b>Управление пользователями</b>\n\nВыберите действие:",
        reply_markup=get_admin_users_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin:add_user_info")
@admin_only
async def callback_add_user_info(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    instruction = """
👥 <b>Добавление пользователя</b>

<b>Как работает:</b>
1️⃣ Сотрудник запускает бота командой /start
2️⃣ Бот показывает его <b>Telegram ID</b>
3️⃣ Вы добавляете его через эту форму

<b>Что нужно ввести:</b>
• <b>Telegram ID</b> — цифровой идентификатор
• <b>ФИО</b> — полное имя
• <b>Телефон</b> — для экстренной связи (можно пропустить)
• <b>Права</b> — обычный или администратор
• <b>Категории</b> — к каким категориям оборудования будет доступ

Нажмите кнопку ниже, чтобы начать добавление.
"""

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Начать добавление", callback_data="admin:start_add_user"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:users_menu"))

    await callback.message.edit_text(instruction, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "admin:start_add_user")
@admin_only
async def callback_start_add_user(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    await state.set_state(AddUserStates.waiting_telegram_id)

    await callback.message.edit_text(
        "👥 <b>Добавление пользователя</b>\n\n"
        "Шаг 1 из 5: Введите Telegram ID пользователя\n\n"
        "Пользователь может узнать свой ID, запустив бота командой /start",
        reply_markup=get_admin_back_keyboard("admin:users_menu")
    )
    await callback.answer()


@router.message(AddUserStates.waiting_telegram_id)
@admin_only
async def process_user_telegram_id(message: Message, state: FSMContext, db_user: User) -> None:
    try:
        telegram_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Telegram ID должен быть числом.\n\nПопробуйте еще раз:")
        return

    async with async_session_maker() as session:
        existing_user = await crud.get_user(session, telegram_id)

    if existing_user:
        await message.answer(
            f"❌ Пользователь с ID {telegram_id} уже существует!\n\n"
            f"<b>ФИО:</b> {existing_user.full_name}\n"
            f"<b>Админ:</b> {'Да' if existing_user.is_admin else 'Нет'}\n\n"
            "Попробуйте другой ID:",
            reply_markup=get_admin_back_keyboard("admin:users_menu")
        )
        return

    await state.update_data(user_telegram_id=telegram_id)
    await state.set_state(AddUserStates.waiting_full_name)

    await message.answer(
        f"✅ Telegram ID: <code>{telegram_id}</code>\n\n"
        f"Шаг 2 из 5: Введите ФИО пользователя",
        reply_markup=get_admin_back_keyboard("admin:users_menu")
    )


@router.message(AddUserStates.waiting_full_name)
@admin_only
async def process_user_full_name(message: Message, state: FSMContext, db_user: User) -> None:
    full_name = message.text.strip()

    if len(full_name) < 3:
        await message.answer("❌ ФИО слишком короткое. Минимум 3 символа.\n\nПопробуйте еще раз:")
        return

    await state.update_data(user_full_name=full_name)
    await state.set_state(AddUserStates.waiting_phone)

    data = await state.get_data()

    await message.answer(
        f"✅ Telegram ID: <code>{data['user_telegram_id']}</code>\n"
        f"✅ ФИО: <b>{full_name}</b>\n\n"
        f"Шаг 3 из 5: Введите номер телефона\n\n"
        f"Отправьте <code>-</code> чтобы пропустить",
        reply_markup=get_admin_back_keyboard("admin:users_menu")
    )


@router.message(AddUserStates.waiting_phone)
@admin_only
async def process_user_phone(message: Message, state: FSMContext, db_user: User) -> None:
    phone = message.text.strip()
    if phone == "-":
        phone = None

    await state.update_data(user_phone=phone)
    await state.set_state(AddUserStates.waiting_admin_status)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👤 Обычный", callback_data="user_admin:no"),
        InlineKeyboardButton(text="⚙️ Админ", callback_data="user_admin:yes"),
    )

    data = await state.get_data()
    phone_text = phone if phone else "не указан"

    await message.answer(
        f"✅ Telegram ID: <code>{data['user_telegram_id']}</code>\n"
        f"✅ ФИО: <b>{data['user_full_name']}</b>\n"
        f"✅ Телефон: <code>{phone_text}</code>\n\n"
        f"Шаг 4 из 5: Выберите права доступа:",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("user_admin:"), AddUserStates.waiting_admin_status)
@admin_only
async def process_user_admin_status(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Process admin status, then ask for category access."""
    is_admin = callback.data.split(":")[1] == "yes"
    await state.update_data(user_is_admin=is_admin)

    # If admin, skip category selection (admins have access to all)
    if is_admin:
        await _create_user_and_finish(callback, state, db_user, selected_category_ids=[])
        return

    # Show category selection for regular users
    async with async_session_maker() as session:
        categories = await crud.get_all_categories_from_db(session)

    if not categories:
        # No categories in DB, just create user
        await _create_user_and_finish(callback, state, db_user, selected_category_ids=[])
        return

    await state.update_data(selected_category_ids=[])
    await state.set_state(AddUserStates.waiting_categories)

    await callback.message.edit_text(
        "Шаг 5 из 5: Выберите доступные категории оборудования\n\n"
        "Нажмите на категорию, чтобы выбрать/убрать.\n"
        "«Пропустить» = доступ ко всем категориям.",
        reply_markup=get_user_category_select_keyboard(categories, [])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("user_cat_toggle:"), AddUserStates.waiting_categories)
@admin_only
async def process_user_cat_toggle(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Toggle category selection."""
    cat_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = data.get("selected_category_ids", [])

    if cat_id in selected:
        selected.remove(cat_id)
    else:
        selected.append(cat_id)

    await state.update_data(selected_category_ids=selected)

    async with async_session_maker() as session:
        categories = await crud.get_all_categories_from_db(session)

    await callback.message.edit_text(
        "Шаг 5 из 5: Выберите доступные категории оборудования\n\n"
        "Нажмите на категорию, чтобы выбрать/убрать.\n"
        "«Пропустить» = доступ ко всем категориям.",
        reply_markup=get_user_category_select_keyboard(categories, selected)
    )
    await callback.answer()


@router.callback_query(F.data == "user_cat_done", AddUserStates.waiting_categories)
@admin_only
async def process_user_cat_done(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Save selected categories and create user."""
    data = await state.get_data()
    selected = data.get("selected_category_ids", [])
    await _create_user_and_finish(callback, state, db_user, selected_category_ids=selected)


@router.callback_query(F.data == "user_cat_skip", AddUserStates.waiting_categories)
@admin_only
async def process_user_cat_skip(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Skip category selection = access to all."""
    await _create_user_and_finish(callback, state, db_user, selected_category_ids=[])


async def _create_user_and_finish(
    callback: CallbackQuery,
    state: FSMContext,
    db_user: User,
    selected_category_ids: list[int],
) -> None:
    """Helper: create user and show result."""
    data = await state.get_data()
    is_admin = data.get("user_is_admin", False)

    async with async_session_maker() as session:
        new_user = await crud.create_user(
            session,
            telegram_id=data["user_telegram_id"],
            full_name=data["user_full_name"],
            phone_number=data.get("user_phone"),
            is_admin=is_admin
        )

        if selected_category_ids:
            await crud.set_user_categories(session, new_user.telegram_id, selected_category_ids)

    await state.clear()

    logger.info(
        f"Admin {db_user.telegram_id} added user: "
        f"{new_user.full_name} (ID:{new_user.telegram_id}, admin:{is_admin}, "
        f"categories:{selected_category_ids})"
    )

    phone_text = new_user.phone_number if new_user.phone_number else "не указан"
    admin_text = "Администратор ⚙️" if is_admin else "Обычный пользователь 👤"
    cat_text = f"{len(selected_category_ids)} шт." if selected_category_ids else "Все"

    await callback.message.edit_text(
        f"✅ <b>Пользователь добавлен!</b>\n\n"
        f"<b>Telegram ID:</b> <code>{new_user.telegram_id}</code>\n"
        f"<b>ФИО:</b> {new_user.full_name}\n"
        f"<b>Телефон:</b> <code>{phone_text}</code>\n"
        f"<b>Права:</b> {admin_text}\n"
        f"<b>Категории:</b> {cat_text}",
        reply_markup=get_admin_back_keyboard("admin:users_menu")
    )
    await callback.answer("✅ Добавлен!", show_alert=True)


# ============== BOOKINGS MENU ==============

@router.callback_query(F.data == "admin:bookings_menu")
@admin_only
async def callback_bookings_menu(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    await state.clear()
    await callback.message.edit_text(
        "📋 <b>Управление бронированиями</b>\n\nВыберите действие:",
        reply_markup=get_admin_bookings_menu_keyboard()
    )
    await callback.answer()


# ============== LIST ACTIVE BOOKINGS ==============

@router.callback_query(F.data == "admin:list_active_bookings")
@admin_only
async def callback_list_active_bookings(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    async with async_session_maker() as session:
        bookings = await crud.get_active_bookings(session)

    if not bookings:
        await callback.message.edit_text(
            "📋 <b>Активные брони</b>\n\n✅ Нет активных броней.",
            reply_markup=get_admin_back_keyboard("admin:bookings_menu")
        )
        await callback.answer()
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    lines = ["📋 <b>Активные брони</b>\n", f"Всего: {len(bookings)}\n"]

    now = datetime.now(timezone.utc)
    for booking in bookings:
        user_name = booking.user.full_name if booking.user else f"ID:{booking.user_id}"
        equipment_name = booking.equipment.name if booking.equipment else f"ID:{booking.equipment_id}"
        start_str = booking.start_time.strftime("%d.%m %H:%M")
        end_str = booking.end_time.strftime("%d.%m %H:%M")
        overdue_mark = " ⚠️" if booking.end_time < now else ""

        lines.append(f"\n<b>Бронь #{booking.id}</b>{overdue_mark}")
        lines.append(f"👤 {user_name}")
        lines.append(f"📦 {equipment_name}")
        lines.append(f"🕐 {start_str} - {end_str}")

        builder.row(InlineKeyboardButton(
            text=f"#{booking.id} - {equipment_name[:20]}",
            callback_data=f"admin:booking:{booking.id}"
        ))

    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:bookings_menu"))

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await callback.answer()


# ============== LIST PENDING BOOKINGS ==============

@router.callback_query(F.data == "admin:list_pending_bookings")
@admin_only
async def callback_list_pending_bookings(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    async with async_session_maker() as session:
        bookings = await crud.get_pending_bookings(session)

    if not bookings:
        await callback.message.edit_text(
            "🕐 <b>Ожидающие подтверждения</b>\n\n✅ Нет ожидающих броней.",
            reply_markup=get_admin_back_keyboard("admin:bookings_menu")
        )
        await callback.answer()
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    lines = ["🕐 <b>Ожидающие подтверждения</b>\n", f"Всего: {len(bookings)}\n"]

    for booking in bookings:
        user_name = booking.user.full_name if booking.user else f"ID:{booking.user_id}"
        equipment_name = booking.equipment.name if booking.equipment else f"ID:{booking.equipment_id}"
        start_str = booking.start_time.strftime("%d.%m %H:%M")

        lines.append(f"\n<b>Бронь #{booking.id}</b>")
        lines.append(f"👤 {user_name}")
        lines.append(f"📦 {equipment_name}")
        lines.append(f"🕐 Начало: {start_str}")

        builder.row(InlineKeyboardButton(
            text=f"#{booking.id} - {equipment_name[:20]}",
            callback_data=f"admin:booking:{booking.id}"
        ))

    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:bookings_menu"))

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await callback.answer()


# ============== BOOKING DETAILS ==============

@router.callback_query(F.data.startswith("admin:booking:"))
@admin_only
async def callback_booking_details(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    booking_id = int(callback.data.split(":")[2])

    async with async_session_maker() as session:
        booking = await crud.get_booking_by_id(session, booking_id, load_relations=True)

    if not booking:
        await callback.answer("❌ Бронь не найдена", show_alert=True)
        return

    message = format_booking_info(booking, verbose=True)

    await callback.message.edit_text(
        message,
        reply_markup=get_admin_booking_actions_keyboard(booking_id, booking.status)
    )
    await callback.answer()


# ============== COMPLETE BOOKING ==============

@router.callback_query(F.data.startswith("admin:complete:"))
@admin_only
async def callback_complete_booking(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    booking_id = int(callback.data.split(":")[2])

    async with async_session_maker() as session:
        booking = await crud.get_booking_by_id(session, booking_id, load_relations=True)
        if not booking:
            await callback.answer("❌ Бронь не найдена", show_alert=True)
            return
        if booking.status not in ["pending", "active"]:
            await callback.answer(f"❌ Нельзя завершить бронь со статусом '{booking.status}'", show_alert=True)
            return
        await crud.force_complete_booking(session, booking_id)

    logger.warning(
        f"Admin {db_user.telegram_id} force-completed booking {booking_id} "
        f"(user: {booking.user.full_name}, equipment: {booking.equipment.name})"
    )

    await callback.answer("✅ Бронь завершена!", show_alert=True)
    await callback_list_active_bookings(callback, state, db_user)


# ============== CANCEL BOOKING ==============

@router.callback_query(F.data.startswith("admin:cancel:"))
@admin_only
async def callback_cancel_booking(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    booking_id = int(callback.data.split(":")[2])

    async with async_session_maker() as session:
        booking = await crud.get_booking_by_id(session, booking_id, load_relations=True)
        if not booking:
            await callback.answer("❌ Бронь не найдена", show_alert=True)
            return
        if booking.status not in ["pending", "active"]:
            await callback.answer(f"❌ Нельзя отменить бронь со статусом '{booking.status}'", show_alert=True)
            return
        result = await crud.cancel_booking(session, booking_id)

    if result:
        logger.info(f"Admin {db_user.telegram_id} cancelled booking {booking_id}")
        await callback.answer("✅ Бронь отменена!", show_alert=True)
        await callback_list_active_bookings(callback, state, db_user)
    else:
        await callback.answer("❌ Не удалось отменить. Используйте «Завершить» для активных броней.", show_alert=True)


# ============== GET BOOKING PHOTOS ==============

@router.callback_query(F.data.startswith("admin:photos:"))
@admin_only
async def callback_get_booking_photos(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    booking_id = int(callback.data.split(":")[2])

    async with async_session_maker() as session:
        booking = await crud.get_booking_by_id(session, booking_id, load_relations=True)
        if not booking:
            await callback.answer("❌ Бронь не найдена", show_alert=True)
            return

    await callback.answer()

    await callback.message.answer(
        f"📷 <b>Фотографии брони #{booking_id}</b>\n\n"
        f"<b>Сотрудник:</b> {booking.user.full_name}\n"
        f"<b>Оборудование:</b> {booking.equipment.name}\n"
        f"<b>Статус:</b> {booking.status}"
    )

    from aiogram.types import InputMediaPhoto
    import os

    # Send start photos
    if booking.photos_start:
        await callback.message.answer(f"📸 <b>Фото начала ({len(booking.photos_start)} шт.):</b>")
        media_group = []
        for photo_ref in booking.photos_start:
            if photo_ref.startswith("/"):
                # Local file path
                if os.path.exists(photo_ref):
                    media_group.append(InputMediaPhoto(media=FSInputFile(photo_ref)))
            else:
                # Telegram file_id
                media_group.append(InputMediaPhoto(media=photo_ref))

        if media_group:
            try:
                await asyncio.wait_for(
                    callback.message.answer_media_group(media_group),
                    timeout=30
                )
            except Exception as e:
                logger.error(f"Failed to send photos_start: {e}")
                await callback.message.answer("❌ Не удалось загрузить фото начала")
    else:
        await callback.message.answer("📸 Фото начала: <i>нет</i>")

    # Send end photos
    if booking.photos_end:
        await callback.message.answer(f"📸 <b>Фото конца ({len(booking.photos_end)} шт.):</b>")
        media_group = []
        for photo_ref in booking.photos_end:
            if photo_ref.startswith("/"):
                if os.path.exists(photo_ref):
                    media_group.append(InputMediaPhoto(media=FSInputFile(photo_ref)))
            else:
                media_group.append(InputMediaPhoto(media=photo_ref))

        if media_group:
            try:
                await asyncio.wait_for(
                    callback.message.answer_media_group(media_group),
                    timeout=30
                )
            except Exception as e:
                logger.error(f"Failed to send photos_end: {e}")
                await callback.message.answer("❌ Не удалось загрузить фото конца")
    else:
        await callback.message.answer("📸 Фото конца: <i>нет</i>")

    await callback.message.answer(
        "Выберите действие:",
        reply_markup=get_back_to_booking_keyboard(booking_id)
    )


# ============== MAINTENANCE MENU ==============

@router.callback_query(F.data == "admin:maintenance_menu")
@admin_only
async def callback_maintenance_menu(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    await state.clear()
    await callback.message.edit_text(
        "🔧 <b>Тех. обслуживание</b>\n\nВыберите действие:",
        reply_markup=get_admin_maintenance_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin:create_maintenance")
@admin_only
async def callback_create_maintenance(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    async with async_session_maker() as session:
        categories = await crud.get_all_categories_from_db(session)

    if not categories:
        await callback.answer("Нет категорий в БД", show_alert=True)
        return

    await state.set_state(MaintenanceStates.choosing_category)

    await callback.message.edit_text(
        "🔧 <b>Создание ТО</b>\n\nШаг 1: Выберите категорию:",
        reply_markup=get_db_categories_keyboard(
            categories, callback_prefix="maint_cat", back_callback="admin:maintenance_menu"
        )
    )
    await callback.answer()


@router.callback_query(MaintenanceStates.choosing_category, F.data.startswith("maint_cat:"))
@admin_only
async def callback_maintenance_select_category(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    category_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        category = await crud.get_category_by_id(session, category_id)
        all_eq = await crud.get_all_equipment(session, only_available=True)

    equipment_list = [eq for eq in all_eq if eq.category_id == category_id]

    if not equipment_list:
        await callback.answer("В этой категории нет доступного оборудования", show_alert=True)
        return

    await state.update_data(maint_category_id=category_id, maint_category_name=category.name if category else "")
    await state.set_state(MaintenanceStates.choosing_equipment)

    await callback.message.edit_text(
        f"🔧 <b>Создание ТО</b>\n\n"
        f"📁 Категория: <b>{category.name if category else ''}</b>\n\n"
        f"Шаг 2: Выберите оборудование:",
        reply_markup=get_equipment_keyboard(equipment_list, page=0, category=None, for_booking=True)
    )
    await callback.answer()


@router.callback_query(MaintenanceStates.choosing_equipment, F.data.startswith("equip:"))
@admin_only
async def callback_maintenance_select_equipment(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    equipment_id = int(callback.data.split(":", 1)[1])

    async with async_session_maker() as session:
        equipment = await crud.get_equipment_by_id(session, equipment_id)

    if not equipment:
        await callback.answer("Оборудование не найдено", show_alert=True)
        return

    await state.update_data(equipment_id=equipment_id, equipment_name=equipment.name)
    await state.set_state(MaintenanceStates.choosing_date_start)

    now = now_msk()
    max_date = now + timedelta(days=90)

    await callback.message.edit_text(
        f"🔧 <b>Создание ТО</b>\n\n"
        f"📦 Оборудование: <b>{equipment.name}</b>\n\n"
        f"Шаг 3: Выберите дату <b>начала</b> ТО:",
        reply_markup=get_calendar_keyboard(year=now.year, month=now.month, callback_prefix="date_start", min_date=now, max_date=max_date, back_callback="admin:create_maintenance")
    )
    await callback.answer()


@router.callback_query(MaintenanceStates.choosing_equipment, F.data.startswith("page:"))
@admin_only
async def callback_maintenance_equipment_page(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    parts = callback.data.split(":")
    page = int(parts[-1])

    data = await state.get_data()
    category_id = data.get("maint_category_id")
    category_name = data.get("maint_category_name", "")

    async with async_session_maker() as session:
        all_eq = await crud.get_all_equipment(session, only_available=True)

    equipment_list = [eq for eq in all_eq if eq.category_id == category_id] if category_id else all_eq

    await callback.message.edit_text(
        f"🔧 <b>Создание ТО</b>\n\n"
        f"📁 Категория: <b>{category_name}</b>\n\nШаг 2: Выберите оборудование:",
        reply_markup=get_equipment_keyboard(equipment_list, page=page, category=None, for_booking=True)
    )
    await callback.answer()


@router.callback_query(MaintenanceStates.choosing_date_start, F.data.startswith("date_start:"))
@admin_only
async def callback_maintenance_select_start_date(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    date_str = callback.data.split(":", 1)[1]
    await state.update_data(start_date=date_str)
    await state.set_state(MaintenanceStates.choosing_time_start)

    data = await state.get_data()
    await callback.message.edit_text(
        f"🔧 <b>Создание ТО</b>\n\n"
        f"📦 Оборудование: <b>{data['equipment_name']}</b>\n"
        f"📅 Дата начала: <b>{date_str}</b>\n\n"
        f"Шаг 3: Выберите <b>время начала</b>:",
        reply_markup=get_time_keyboard(callback_prefix="time_start", back_callback="maint:back_date_start")
    )
    await callback.answer()


@router.callback_query(MaintenanceStates.choosing_date_start, F.data.startswith("cal:date_start:"))
@admin_only
async def callback_maintenance_cal_start_nav(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    parts = callback.data.split(":")
    year = int(parts[2])
    month = int(parts[3])

    data = await state.get_data()
    now = now_msk()
    max_date = now + timedelta(days=90)

    await callback.message.edit_text(
        f"🔧 <b>Создание ТО</b>\n\n"
        f"📦 Оборудование: <b>{data['equipment_name']}</b>\n\n"
        f"Шаг 2: Выберите дату <b>начала</b> ТО:",
        reply_markup=get_calendar_keyboard(year=year, month=month, callback_prefix="date_start", min_date=now, max_date=max_date, back_callback="admin:create_maintenance")
    )
    await callback.answer()


@router.callback_query(MaintenanceStates.choosing_time_start, F.data.startswith("time_start:"))
@admin_only
async def callback_maintenance_select_start_time(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    time_str = callback.data.split(":", 1)[1]
    await state.update_data(start_time=time_str)
    await state.set_state(MaintenanceStates.choosing_date_end)

    data = await state.get_data()
    start_dt = datetime.strptime(f"{data['start_date']} {time_str}", "%Y-%m-%d %H:%M")
    max_date = start_dt + timedelta(days=90)

    await callback.message.edit_text(
        f"🔧 <b>Создание ТО</b>\n\n"
        f"📦 Оборудование: <b>{data['equipment_name']}</b>\n"
        f"📅 Начало: <b>{data['start_date']} {time_str}</b>\n\n"
        f"Шаг 4: Выберите дату <b>окончания</b> ТО:",
        reply_markup=get_calendar_keyboard(year=start_dt.year, month=start_dt.month, callback_prefix="date_end", min_date=start_dt, max_date=max_date, back_callback="maint:back_time_start")
    )
    await callback.answer()


@router.callback_query(MaintenanceStates.choosing_date_end, F.data.startswith("cal:date_end:"))
@admin_only
async def callback_maintenance_cal_end_nav(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    parts = callback.data.split(":")
    year = int(parts[2])
    month = int(parts[3])

    data = await state.get_data()
    start_dt = datetime.strptime(f"{data['start_date']} {data['start_time']}", "%Y-%m-%d %H:%M")
    max_date = start_dt + timedelta(days=90)

    await callback.message.edit_text(
        f"🔧 <b>Создание ТО</b>\n\n"
        f"📦 Оборудование: <b>{data['equipment_name']}</b>\n"
        f"📅 Начало: <b>{data['start_date']} {data['start_time']}</b>\n\n"
        f"Шаг 4: Выберите дату <b>окончания</b> ТО:",
        reply_markup=get_calendar_keyboard(year=year, month=month, callback_prefix="date_end", min_date=start_dt, max_date=max_date, back_callback="maint:back_time_start")
    )
    await callback.answer()


@router.callback_query(MaintenanceStates.choosing_date_end, F.data.startswith("date_end:"))
@admin_only
async def callback_maintenance_select_end_date(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    date_str = callback.data.split(":", 1)[1]
    await state.update_data(end_date=date_str)
    await state.set_state(MaintenanceStates.choosing_time_end)

    data = await state.get_data()
    await callback.message.edit_text(
        f"🔧 <b>Создание ТО</b>\n\n"
        f"📦 Оборудование: <b>{data['equipment_name']}</b>\n"
        f"📅 Начало: <b>{data['start_date']} {data['start_time']}</b>\n"
        f"📅 Дата окончания: <b>{date_str}</b>\n\n"
        f"Шаг 5: Выберите <b>время окончания</b>:",
        reply_markup=get_time_keyboard(callback_prefix="time_end", back_callback="maint:back_date_end")
    )
    await callback.answer()


@router.callback_query(MaintenanceStates.choosing_time_end, F.data.startswith("time_end:"))
@admin_only
async def callback_maintenance_select_end_time(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    time_str = callback.data.split(":", 1)[1]
    await state.update_data(end_time=time_str)

    data = await state.get_data()
    start_dt = datetime.strptime(f"{data['start_date']} {data['start_time']}", "%Y-%m-%d %H:%M")
    end_dt = datetime.strptime(f"{data['end_date']} {time_str}", "%Y-%m-%d %H:%M")

    if end_dt <= start_dt:
        await callback.answer("Время окончания должно быть позже начала!", show_alert=True)
        return

    await state.set_state(MaintenanceStates.entering_reason)

    await callback.message.edit_text(
        f"🔧 <b>Создание ТО</b>\n\n"
        f"📦 Оборудование: <b>{data['equipment_name']}</b>\n"
        f"📅 Начало: <b>{data['start_date']} {data['start_time']}</b>\n"
        f"📅 Окончание: <b>{data['end_date']} {time_str}</b>\n\n"
        f"Шаг 6: Введите <b>причину</b> ТО:",
        reply_markup=get_admin_back_keyboard("admin:maintenance_menu")
    )
    await callback.answer()


@router.callback_query(F.data == "maint:back_date_start")
@admin_only
async def callback_maint_back_to_date_start(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Go back to start date selection in maintenance flow."""
    data = await state.get_data()
    now = now_msk()
    max_date = now + timedelta(days=90)
    await state.set_state(MaintenanceStates.choosing_date_start)
    await callback.message.edit_text(
        f"🔧 <b>Создание ТО</b>\n\n"
        f"📦 Оборудование: <b>{data.get('equipment_name', '')}</b>\n\n"
        f"Шаг 3: Выберите дату <b>начала</b> ТО:",
        reply_markup=get_calendar_keyboard(year=now.year, month=now.month, callback_prefix="date_start",
                                           min_date=now, max_date=max_date, back_callback="admin:create_maintenance")
    )
    await callback.answer()


@router.callback_query(F.data == "maint:back_time_start")
@admin_only
async def callback_maint_back_to_time_start(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Go back to start time selection in maintenance flow."""
    data = await state.get_data()
    start_date = data.get("start_date", "")
    now = now_msk()
    min_time = now if start_date == now.strftime("%Y-%m-%d") else None
    await state.set_state(MaintenanceStates.choosing_time_start)
    await callback.message.edit_text(
        f"🔧 <b>Создание ТО</b>\n\n"
        f"📦 Оборудование: <b>{data.get('equipment_name', '')}</b>\n"
        f"📅 Дата начала: <b>{start_date}</b>\n\n"
        f"Шаг 3: Выберите <b>время начала</b>:",
        reply_markup=get_time_keyboard(callback_prefix="time_start", min_time=min_time, back_callback="maint:back_date_start")
    )
    await callback.answer()


@router.callback_query(F.data == "maint:back_date_end")
@admin_only
async def callback_maint_back_to_date_end(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Go back to end date selection in maintenance flow."""
    data = await state.get_data()
    start_dt = datetime.strptime(f"{data['start_date']} {data['start_time']}", "%Y-%m-%d %H:%M")
    max_date = start_dt + timedelta(days=90)
    await state.set_state(MaintenanceStates.choosing_date_end)
    await callback.message.edit_text(
        f"🔧 <b>Создание ТО</b>\n\n"
        f"📦 Оборудование: <b>{data.get('equipment_name', '')}</b>\n"
        f"📅 Начало: <b>{data['start_date']} {data['start_time']}</b>\n\n"
        f"Шаг 4: Выберите дату <b>окончания</b> ТО:",
        reply_markup=get_calendar_keyboard(year=start_dt.year, month=start_dt.month, callback_prefix="date_end",
                                           min_date=start_dt, max_date=max_date, back_callback="maint:back_time_start")
    )
    await callback.answer()


@router.message(MaintenanceStates.entering_reason)
@admin_only
async def process_maintenance_reason(message: Message, state: FSMContext, db_user: User) -> None:
    reason = message.text.strip()

    if len(reason) < 3:
        await message.answer("❌ Причина слишком короткая. Минимум 3 символа.")
        return

    data = await state.get_data()
    start_dt = datetime.strptime(f"{data['start_date']} {data['start_time']}", "%Y-%m-%d %H:%M")
    end_dt = datetime.strptime(f"{data['end_date']} {data['end_time']}", "%Y-%m-%d %H:%M")

    async with async_session_maker() as session:
        result = await crud.create_maintenance_booking(
            session=session,
            equipment_id=data["equipment_id"],
            admin_id=db_user.telegram_id,
            start_time=start_dt,
            end_time=end_dt,
            reason=reason,
        )

    await state.clear()

    if isinstance(result, str):
        await message.answer(
            f"❌ <b>Ошибка создания ТО</b>\n\n{result}",
            reply_markup=get_admin_back_keyboard("admin:maintenance_menu")
        )
    else:
        logger.info(f"Admin {db_user.telegram_id} created maintenance booking {result.id}")
        await message.answer(
            f"✅ <b>ТО создано!</b>\n\n"
            f"📦 Оборудование: <b>{data['equipment_name']}</b>\n"
            f"📅 Начало: <b>{data['start_date']} {data['start_time']}</b>\n"
            f"📅 Окончание: <b>{data['end_date']} {data['end_time']}</b>\n"
            f"📝 Причина: {reason}\n"
            f"🔢 ID: #{result.id}",
            reply_markup=get_admin_back_keyboard("admin:maintenance_menu")
        )


@router.callback_query(F.data == "admin:list_maintenance")
@admin_only
async def callback_list_maintenance(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    async with async_session_maker() as session:
        maintenance_list = await crud.get_maintenance_bookings(session)

    if not maintenance_list:
        await callback.message.edit_text(
            "🔧 <b>Активные ТО</b>\n\n✅ Нет активных ТО.",
            reply_markup=get_admin_back_keyboard("admin:maintenance_menu")
        )
        await callback.answer()
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    lines = ["🔧 <b>Активные ТО</b>\n", f"Всего: {len(maintenance_list)}\n"]

    for m in maintenance_list:
        equipment_name = m.equipment.name if m.equipment else f"ID:{m.equipment_id}"
        start_str = m.start_time.strftime("%d.%m %H:%M")
        end_str = m.end_time.strftime("%d.%m %H:%M")
        reason = m.maintenance_reason or "не указана"

        lines.append(f"\n<b>ТО #{m.id}</b>")
        lines.append(f"📦 {equipment_name}")
        lines.append(f"🕐 {start_str} - {end_str}")
        lines.append(f"📝 {reason}")

        builder.row(InlineKeyboardButton(
            text=f"✅ Завершить ТО #{m.id}",
            callback_data=f"admin:complete_maintenance:{m.id}"
        ))

    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:maintenance_menu"))

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("admin:complete_maintenance:"))
@admin_only
async def callback_complete_maintenance(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    booking_id = int(callback.data.split(":")[2])

    async with async_session_maker() as session:
        result = await crud.complete_maintenance(session, booking_id)

    if result:
        logger.info(f"Admin {db_user.telegram_id} completed maintenance booking {booking_id}")
        await callback.answer("✅ ТО завершено!", show_alert=True)
    else:
        await callback.answer("❌ ТО не найдено или уже завершено", show_alert=True)

    await callback_list_maintenance(callback, state, db_user)


# ============== REPORTS MENU ==============

@router.callback_query(F.data == "admin:reports_menu")
@admin_only
async def callback_reports_menu(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    await state.clear()

    await callback.message.edit_text(
        "📊 <b>Отчеты</b>\n\n"
        "Выберите тип фильтрации для отчета:",
        reply_markup=get_report_filter_keyboard()
    )
    await callback.answer()


# --- Report filter: by category ---
@router.callback_query(F.data == "report_filter:category")
@admin_only
async def callback_report_filter_category(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    async with async_session_maker() as session:
        categories = await crud.get_all_categories_from_db(session)

    if not categories:
        await callback.answer("Нет категорий в БД", show_alert=True)
        return

    await state.set_state(ReportStates.choosing_category)

    await callback.message.edit_text(
        "📊 <b>Отчет по категории</b>\n\nВыберите категорию:",
        reply_markup=get_db_categories_keyboard(categories, callback_prefix="rpt_cat", back_callback="admin:reports_menu")
    )
    await callback.answer()


@router.callback_query(ReportStates.choosing_category, F.data.startswith("rpt_cat:"))
@admin_only
async def callback_report_select_category(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    category_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        category = await crud.get_category_by_id(session, category_id)

    await state.update_data(report_category_id=category_id, report_category_name=category.name if category else "")
    await state.set_state(ReportStates.choosing_period)

    await callback.message.edit_text(
        f"📊 <b>Отчет по категории: {category.name if category else ''}</b>\n\nВыберите период:",
        reply_markup=get_report_period_keyboard()
    )
    await callback.answer()


# --- Report filter: by user ---
@router.callback_query(F.data == "report_filter:user")
@admin_only
async def callback_report_filter_user(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    async with async_session_maker() as session:
        users = await crud.get_all_users(session)

    if not users:
        await callback.answer("Нет пользователей", show_alert=True)
        return

    await state.set_state(ReportStates.choosing_user)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    for u in users[:20]:
        builder.row(InlineKeyboardButton(
            text=f"👤 {u.full_name}",
            callback_data=f"rpt_user:{u.telegram_id}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:reports_menu"))

    await callback.message.edit_text(
        "📊 <b>Отчет по сотруднику</b>\n\nВыберите сотрудника:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(ReportStates.choosing_user, F.data.startswith("rpt_user:"))
@admin_only
async def callback_report_select_user(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    user_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        target_user = await crud.get_user(session, user_id)

    await state.update_data(
        report_user_id=user_id,
        report_user_name=target_user.full_name if target_user else str(user_id)
    )
    await state.set_state(ReportStates.choosing_period)

    await callback.message.edit_text(
        f"📊 <b>Отчет по сотруднику: {target_user.full_name if target_user else user_id}</b>\n\nВыберите период:",
        reply_markup=get_report_period_keyboard()
    )
    await callback.answer()


# --- Report filter: period only ---
@router.callback_query(F.data == "report_filter:period")
@admin_only
async def callback_report_filter_period(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    await state.set_state(ReportStates.choosing_period)

    await callback.message.edit_text(
        "📊 <b>Отчет за период</b>\n\nВыберите период:",
        reply_markup=get_report_period_keyboard()
    )
    await callback.answer()


# --- Report filter: all ---
@router.callback_query(F.data == "report_filter:all")
@admin_only
async def callback_report_filter_all(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    await state.set_state(ReportStates.choosing_period)

    await callback.message.edit_text(
        "📊 <b>Полный отчет</b>\n\nВыберите период:",
        reply_markup=get_report_period_keyboard()
    )
    await callback.answer()


# --- Report period selection ---
@router.callback_query(ReportStates.choosing_period, F.data.startswith("report_period:"))
@admin_only
async def callback_report_period(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    period = callback.data.split(":")[1]

    if period == "custom":
        await state.set_state(ReportStates.entering_start_date)
        await callback.message.edit_text(
            "📅 Введите дату <b>начала</b> периода\n\n"
            "Формат: ДД.ММ.ГГГГ (например: 01.01.2026)",
            reply_markup=get_admin_back_keyboard("admin:reports_menu")
        )
        await callback.answer()
        return

    days = int(period)
    data = await state.get_data()
    await state.clear()

    await callback.answer()
    await callback.message.edit_text("⏳ Генерирую отчет...")

    try:
        async with async_session_maker() as session:
            report_path = await generate_report(
                session, days,
                category_id=data.get("report_category_id"),
                user_id=data.get("report_user_id"),
                bot=callback.message.bot,
            )

        if not report_path:
            await callback.message.edit_text(
                "❌ Нет данных для отчета.",
                reply_markup=get_admin_back_keyboard("admin:reports_menu")
            )
            return

        file = FSInputFile(report_path)

        # Build caption
        filter_parts = []
        if data.get("report_category_name"):
            filter_parts.append(f"Категория: {data['report_category_name']}")
        if data.get("report_user_name"):
            filter_parts.append(f"Сотрудник: {data['report_user_name']}")
        filter_text = ", ".join(filter_parts) if filter_parts else "Без фильтров"

        await callback.message.answer_document(
            file,
            caption=f"📊 <b>Отчет за {days} дней</b>\n{filter_text}"
        )

        Path(report_path).unlink(missing_ok=True)
        logger.info(f"Admin {db_user.telegram_id} generated report: {days} days, filters: {filter_text}")

        await callback.message.edit_text(
            "✅ Отчет сгенерирован и отправлен!",
            reply_markup=get_admin_back_keyboard("admin:reports_menu")
        )

    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка: {e}",
            reply_markup=get_admin_back_keyboard("admin:reports_menu")
        )


@router.message(ReportStates.entering_start_date)
@admin_only
async def process_report_start_date(message: Message, state: FSMContext, db_user: User) -> None:
    try:
        start_date = datetime.strptime(message.text.strip(), "%d.%m.%Y")
    except ValueError:
        await message.answer("❌ Неверный формат. Используйте ДД.ММ.ГГГГ\n\nНапример: 01.01.2026")
        return

    await state.update_data(report_start_date=start_date.strftime("%Y-%m-%d"))
    await state.set_state(ReportStates.entering_end_date)

    await message.answer(
        f"✅ Начало периода: <b>{message.text.strip()}</b>\n\n"
        f"📅 Введите дату <b>окончания</b> периода\n\n"
        f"Формат: ДД.ММ.ГГГГ",
        reply_markup=get_admin_back_keyboard("admin:reports_menu")
    )


@router.message(ReportStates.entering_end_date)
@admin_only
async def process_report_end_date(message: Message, state: FSMContext, db_user: User) -> None:
    try:
        end_date = datetime.strptime(message.text.strip(), "%d.%m.%Y")
    except ValueError:
        await message.answer("❌ Неверный формат. Используйте ДД.ММ.ГГГГ")
        return

    data = await state.get_data()
    start_date = datetime.strptime(data["report_start_date"], "%Y-%m-%d")

    if end_date <= start_date:
        await message.answer("❌ Дата окончания должна быть позже даты начала.")
        return

    await state.clear()

    await message.answer("⏳ Генерирую отчет...")

    try:
        async with async_session_maker() as session:
            report_path = await generate_report(
                session, days=None,
                category_id=data.get("report_category_id"),
                user_id=data.get("report_user_id"),
                start_date=start_date,
                end_date=end_date,
                bot=message.bot,
            )

        if not report_path:
            await message.answer(
                "❌ Нет данных для отчета.",
                reply_markup=get_admin_back_keyboard("admin:reports_menu")
            )
            return

        file = FSInputFile(report_path)
        await message.answer_document(
            file,
            caption=f"📊 <b>Отчет {start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')}</b>"
        )
        Path(report_path).unlink(missing_ok=True)
        logger.info(f"Admin {db_user.telegram_id} generated custom period report")

        await message.answer(
            "✅ Отчет сгенерирован!",
            reply_markup=get_admin_back_keyboard("admin:reports_menu")
        )

    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        await message.answer(
            f"❌ Ошибка: {e}",
            reply_markup=get_admin_back_keyboard("admin:reports_menu")
        )


# Legacy report buttons (redirect to new flow)
@router.callback_query(F.data.startswith("admin:report:"))
@admin_only
async def callback_generate_report_legacy(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Legacy report button handler - generate report directly."""
    days = int(callback.data.split(":")[2])

    await callback.answer()
    await callback.message.edit_text(f"⏳ Генерирую отчет за {days} дней...")

    try:
        async with async_session_maker() as session:
            report_path = await generate_report(session, days, bot=callback.message.bot)

        if not report_path:
            await callback.message.edit_text(
                "❌ Нет данных для отчета.",
                reply_markup=get_admin_back_keyboard("admin:reports_menu")
            )
            return

        file = FSInputFile(report_path)
        await callback.message.answer_document(
            file,
            caption=f"📊 <b>Отчет за {days} дней</b>"
        )
        Path(report_path).unlink(missing_ok=True)
        logger.info(f"Admin {db_user.telegram_id} generated report for {days} days")

        await callback.message.edit_text(
            "✅ Отчет сгенерирован!",
            reply_markup=get_admin_back_keyboard("admin:reports_menu")
        )

    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка: {e}",
            reply_markup=get_admin_back_keyboard("admin:reports_menu")
        )


# ============== EXCEL IMPORT ==============

@router.callback_query(F.data == "admin:import_excel")
@admin_only
async def callback_import_excel(callback: CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Start Excel import flow."""
    await state.set_state(ImportStates.waiting_file)
    await callback.answer()
    await callback.message.edit_text(
        "📥 <b>Импорт оборудования из Excel</b>\n\n"
        "Отправьте Excel-файл (.xlsx) со следующими столбцами:\n\n"
        "• <b>Название</b> — название оборудования (обязательно)\n"
        "• <b>Категория</b> — категория оборудования (обязательно)\n"
        "• <b>Гос номер</b> — гос. номер (необязательно)\n"
        "• <b>Фото</b> — требуется ли фото: да/нет (необязательно)\n\n"
        "💡 Первая строка — заголовки столбцов.",
        reply_markup=get_admin_back_keyboard("admin:equipment_menu")
    )


@router.message(ImportStates.waiting_file, F.document)
@admin_only
async def process_import_file(message: Message, state: FSMContext, db_user: User) -> None:
    """Process uploaded Excel file."""
    doc = message.document

    if not doc.file_name or not doc.file_name.endswith((".xlsx", ".xls")):
        await message.answer(
            "❌ Нужен файл формата .xlsx\n\nОтправьте Excel-файл или нажмите «Назад».",
            reply_markup=get_admin_back_keyboard("admin:equipment_menu")
        )
        return

    await message.answer("⏳ Обрабатываю файл...")

    # Download file
    tmp_dir = Path("tmp")
    tmp_dir.mkdir(exist_ok=True)
    file_path = tmp_dir / doc.file_name

    try:
        file = await message.bot.get_file(doc.file_id)
        await message.bot.download_file(file.file_path, destination=file_path)

        # Parse
        items, errors = parse_equipment_excel(file_path)

        if not items and errors:
            await message.answer(
                "❌ <b>Ошибки при импорте:</b>\n\n" + "\n".join(errors),
                reply_markup=get_admin_back_keyboard("admin:equipment_menu")
            )
            await state.clear()
            return

        # Import into DB
        created = 0
        skipped = 0
        async with async_session_maker() as session:
            for item in items:
                try:
                    cat = await crud.get_or_create_category(session, item["category"])
                    await crud.create_equipment(
                        session,
                        name=item["name"],
                        category=item["category"],
                        category_id=cat.id,
                        license_plate=item.get("license_plate"),
                        requires_photo=item.get("requires_photo", False),
                    )
                    created += 1
                except Exception as e:
                    errors.append(f"{item['name']}: {e}")
                    skipped += 1

        # Build result message
        result_lines = [
            f"✅ <b>Импорт завершён</b>\n",
            f"📦 Добавлено: <b>{created}</b>",
            f"⏭ Пропущено: <b>{skipped}</b>",
        ]
        if errors:
            result_lines.append(f"\n⚠️ <b>Замечания:</b>")
            for err in errors[:20]:
                result_lines.append(f"• {err}")
            if len(errors) > 20:
                result_lines.append(f"... и ещё {len(errors) - 20}")

        await message.answer(
            "\n".join(result_lines),
            reply_markup=get_admin_back_keyboard("admin:equipment_menu")
        )

        logger.info(f"Admin {db_user.telegram_id} imported {created} equipment items from Excel")

    except Exception as e:
        logger.error(f"Excel import error: {e}", exc_info=True)
        await message.answer(
            f"❌ Ошибка импорта: {e}",
            reply_markup=get_admin_back_keyboard("admin:equipment_menu")
        )
    finally:
        file_path.unlink(missing_ok=True)
        await state.clear()


@router.message(ImportStates.waiting_file)
@admin_only
async def process_import_not_file(message: Message, state: FSMContext, db_user: User) -> None:
    """Handle non-file messages during import."""
    await message.answer(
        "❌ Отправьте Excel-файл (.xlsx).\n\n"
        "Если хотите отменить — нажмите «Назад».",
        reply_markup=get_admin_back_keyboard("admin:equipment_menu")
    )
