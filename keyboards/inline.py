"""Инлайн-клавиатуры: меню, категории, список оборудования, календарь, выбор времени."""

from datetime import datetime, timedelta
from calendar import monthcalendar
from utils.helpers import now_msk

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import Equipment, Booking, Category


# ============== ГЛАВНОЕ МЕНЮ ==============

def get_main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Главное меню пользователя. Кнопка «Админка» показывается только администраторам."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="📝 Забронировать",
            callback_data="menu:book"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📋 Мои брони",
            callback_data="menu:my_bookings"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📦 Список оборудования",
            callback_data="menu:equipment_list"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔍 Поиск",
            callback_data="menu:search"
        )
    )

    if is_admin:
        builder.row(
            InlineKeyboardButton(
                text="⚙️ Админка",
                callback_data="admin:main"
            )
        )

    return builder.as_markup()


def get_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой «Главное меню»."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="◀️ Главное меню",
            callback_data="menu:main"
        )
    )

    return builder.as_markup()


# ============== ВЫБОР КАТЕГОРИИ ==============

def get_equip_list_categories_keyboard(categories: list[Category]) -> InlineKeyboardMarkup:
    """Клавиатура категорий для режима просмотра (не бронирования)."""
    builder = InlineKeyboardBuilder()

    for cat in categories:
        builder.row(
            InlineKeyboardButton(
                text=f"📁 {cat.name}",
                callback_data=f"equip_list:{cat.name}"
            )
        )

    builder.row(
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main")
    )

    return builder.as_markup()


def get_categories_keyboard(categories: list[str]) -> InlineKeyboardMarkup:
    """Клавиатура выбора категории оборудования при бронировании."""
    builder = InlineKeyboardBuilder()

    for category in categories:
        builder.row(
            InlineKeyboardButton(
                text=f"📁 {category}",
                callback_data=f"category:{category}"
            )
        )

    builder.row(
        InlineKeyboardButton(
            text="◀️ Главное меню",
            callback_data="menu:main"
        )
    )

    return builder.as_markup()


# ============== СПИСОК ОБОРУДОВАНИЯ С ПАГИНАЦИЕЙ ==============

ITEMS_PER_PAGE = 5


def get_equipment_keyboard(
    equipment_list: list[Equipment],
    page: int = 0,
    category: str | None = None,
    for_booking: bool = True,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    """
    Постраничный список оборудования.

    for_booking=True — клик выбирает для бронирования, False — только просмотр информации.
    """
    builder = InlineKeyboardBuilder()

    total_items = len(equipment_list)
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    if total_pages == 0:
        total_pages = 1

    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_items = equipment_list[start_idx:end_idx]

    for item in page_items:
        callback_prefix = "equip" if for_booking else "info"
        builder.row(
            InlineKeyboardButton(
                text=f"🔹 {item.name}",
                callback_data=f"{callback_prefix}:{item.id}"
            )
        )

    nav_buttons = []

    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="⏪", callback_data=f"page:{category}:0")
        )

    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️", callback_data=f"page:{category}:{page - 1}")
        )

    nav_buttons.append(
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop")
    )

    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(text="▶️", callback_data=f"page:{category}:{page + 1}")
        )

    if nav_buttons:
        builder.row(*nav_buttons)

    if back_callback:
        builder.row(
            InlineKeyboardButton(text="◀️ Назад", callback_data=back_callback)
        )
    elif category:
        builder.row(
            InlineKeyboardButton(text="◀️ К категориям", callback_data="menu:book")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main")
        )

    return builder.as_markup()


# ============== КАЛЕНДАРЬ ==============

WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
]


def get_calendar_keyboard(
    year: int,
    month: int,
    callback_prefix: str = "date",
    min_date: datetime | None = None,
    max_date: datetime | None = None,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    """
    Календарь для выбора даты.

    callback_prefix: префикс для коллбэков дат (date_start или date_end).
    """
    builder = InlineKeyboardBuilder()

    if min_date is None:
        min_date = now_msk()
    if max_date is None:
        max_date = now_msk() + timedelta(days=30)

    header_buttons = []

    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1

    prev_month_last = datetime(prev_year, prev_month, 28)
    if prev_month_last >= min_date:
        header_buttons.append(
            InlineKeyboardButton(text="◀️", callback_data=f"cal:{callback_prefix}:{prev_year}:{prev_month}")
        )
    else:
        header_buttons.append(InlineKeyboardButton(text=" ", callback_data="noop"))

    header_buttons.append(
        InlineKeyboardButton(text=f"{MONTHS_RU[month]} {year}", callback_data="noop")
    )

    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    next_month_first = datetime(next_year, next_month, 1)
    if next_month_first <= max_date:
        header_buttons.append(
            InlineKeyboardButton(text="▶️", callback_data=f"cal:{callback_prefix}:{next_year}:{next_month}")
        )
    else:
        header_buttons.append(InlineKeyboardButton(text=" ", callback_data="noop"))

    builder.row(*header_buttons)

    weekday_buttons = [
        InlineKeyboardButton(text=day, callback_data="noop")
        for day in WEEKDAYS_RU
    ]
    builder.row(*weekday_buttons)

    cal = monthcalendar(year, month)
    for week in cal:
        week_buttons = []
        for day in week:
            if day == 0:
                week_buttons.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                date = datetime(year, month, day)
                date_str = date.strftime("%Y-%m-%d")

                if min_date.date() <= date.date() <= max_date.date():
                    week_buttons.append(
                        InlineKeyboardButton(text=str(day), callback_data=f"{callback_prefix}:{date_str}")
                    )
                else:
                    week_buttons.append(
                        InlineKeyboardButton(text="·", callback_data="noop")
                    )
        builder.row(*week_buttons)

    nav = []
    if back_callback:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=back_callback))
    nav.append(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    builder.row(*nav)

    return builder.as_markup()


# ============== ВЫБОР ВРЕМЕНИ ==============

def get_time_keyboard(
    callback_prefix: str = "time",
    start_hour: int = 8,
    end_hour: int = 20,
    step_minutes: int = 30,
    min_time: datetime | None = None,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора времени слотами.

    min_time: если задан — скрываются прошедшие слоты (для сегодняшнего дня).
    """
    builder = InlineKeyboardBuilder()

    times = []
    current_hour = start_hour
    current_minute = 0

    while current_hour < end_hour or (current_hour == end_hour and current_minute == 0):
        time_str = f"{current_hour:02d}:{current_minute:02d}"
        if min_time is None or (current_hour, current_minute) > (min_time.hour, min_time.minute):
            times.append(time_str)

        current_minute += step_minutes
        if current_minute >= 60:
            current_minute = 0
            current_hour += 1

    # Кнопки по 4 в ряд
    row = []
    for i, time_str in enumerate(times):
        row.append(
            InlineKeyboardButton(text=time_str, callback_data=f"{callback_prefix}:{time_str}")
        )
        if len(row) == 4:
            builder.row(*row)
            row = []

    if row:
        builder.row(*row)

    if not times:
        builder.row(InlineKeyboardButton(text="⚠️ Нет доступного времени", callback_data="noop"))

    nav = []
    if back_callback:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=back_callback))
    nav.append(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    builder.row(*nav)

    return builder.as_markup()


# ============== ПОДТВЕРЖДЕНИЕ БРОНИРОВАНИЯ ==============

def get_booking_confirm_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения/отмены новой брони."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="booking:confirm"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="booking:cancel"),
    )

    return builder.as_markup()


# ============== МОИ БРОНИ ==============

def get_booking_actions_keyboard(
    booking: Booking,
    can_confirm: bool = False,
    can_complete: bool = False,
) -> InlineKeyboardMarkup:
    """Кнопки действий для конкретной брони (подтвердить, вернуть, отменить)."""
    builder = InlineKeyboardBuilder()

    if booking.status == "pending":
        if can_confirm:
            builder.row(
                InlineKeyboardButton(
                    text="✅ Подтвердить начало",
                    callback_data=f"booking_confirm:{booking.id}"
                )
            )
        builder.row(
            InlineKeyboardButton(
                text="❌ Отменить бронь",
                callback_data=f"booking_cancel:{booking.id}"
            )
        )

    elif booking.status == "active":
        if can_complete:
            builder.row(
                InlineKeyboardButton(
                    text="✅ Вернул оборудование",
                    callback_data=f"booking_complete:{booking.id}"
                )
            )
        # Отмена активной брони — только до момента начала
        now = datetime.now(booking.start_time.tzinfo)
        if booking.start_time > now:
            builder.row(
                InlineKeyboardButton(
                    text="❌ Отменить бронь",
                    callback_data=f"booking_cancel:{booking.id}"
                )
            )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:my_bookings")
    )

    return builder.as_markup()


def get_my_bookings_keyboard(bookings: list[Booking], page: int = 0) -> InlineKeyboardMarkup:
    """Постраничный список броней пользователя."""
    builder = InlineKeyboardBuilder()

    total_items = len(bookings)
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    if total_pages == 0:
        total_pages = 1

    page = max(0, min(page, total_pages - 1))

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_items = bookings[start_idx:end_idx]

    for booking in page_items:
        status_emoji = "🕐" if booking.status == "pending" else "✅"
        equipment_name = booking.equipment.name if booking.equipment else f"ID:{booking.equipment_id}"
        date_str = booking.start_time.strftime("%d.%m %H:%M")

        builder.row(
            InlineKeyboardButton(
                text=f"{status_emoji} {equipment_name} | {date_str}",
                callback_data=f"mybooking:{booking.id}"
            )
        )

    if total_pages > 1:
        nav_buttons = []

        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(text="◀️", callback_data=f"mybookings_page:{page - 1}")
            )

        nav_buttons.append(
            InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop")
        )

        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(text="▶️", callback_data=f"mybookings_page:{page + 1}")
            )

        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main")
    )

    return builder.as_markup()


# ============== ЗАГРУЗКА ФОТО ==============

def get_photo_upload_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для состояния загрузки фото (Готово / Пропустить / Отмена)."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="✅ Готово", callback_data="photos:done"),
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="photos:skip"),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="photos:cancel")
    )

    return builder.as_markup()


# ============== МЕНЮ АДМИНИСТРАТОРА ==============

def get_admin_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню администратора."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="📦 Оборудование",
            callback_data="admin:equipment_menu"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="👥 Пользователи",
            callback_data="admin:users_menu"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📋 Бронирования",
            callback_data="admin:bookings_menu"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔧 Тех. обслуживание",
            callback_data="admin:maintenance_menu"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📊 Отчеты",
            callback_data="admin:reports_menu"
        )
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main")
    )

    return builder.as_markup()


def get_admin_equipment_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню управления оборудованием."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить оборудование",
            callback_data="admin:add_equipment_info"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📋 Все оборудование",
            callback_data="admin:list_all_equipment"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔴 Снятое с оборота",
            callback_data="admin:list_disabled_equipment"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📥 Импорт из Excel",
            callback_data="admin:import_excel"
        )
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Админ меню", callback_data="admin:main")
    )

    return builder.as_markup()


def get_admin_users_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню управления пользователями."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить пользователя",
            callback_data="admin:add_user_info"
        )
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Админ меню", callback_data="admin:main")
    )

    return builder.as_markup()


def get_admin_bookings_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню управления бронированиями."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="📋 Все активные брони",
            callback_data="admin:list_active_bookings"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🕐 Ожидающие подтверждения",
            callback_data="admin:list_pending_bookings"
        )
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Админ меню", callback_data="admin:main")
    )

    return builder.as_markup()


def get_admin_maintenance_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню управления техническим обслуживанием."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="➕ Создать ТО",
            callback_data="admin:create_maintenance"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📋 Активные ТО",
            callback_data="admin:list_maintenance"
        )
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Админ меню", callback_data="admin:main")
    )

    return builder.as_markup()


def get_admin_booking_actions_keyboard(booking_id: int, status: str) -> InlineKeyboardMarkup:
    """Кнопки действий администратора над бронью."""
    builder = InlineKeyboardBuilder()

    if status in ["pending", "active"]:
        builder.row(
            InlineKeyboardButton(
                text="✅ Завершить",
                callback_data=f"admin:complete:{booking_id}"
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="❌ Отменить",
                callback_data=f"admin:cancel:{booking_id}"
            )
        )

    builder.row(
        InlineKeyboardButton(
            text="📷 Посмотреть фото",
            callback_data=f"admin:photos:{booking_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(text="◀️ К списку", callback_data="admin:bookings_menu")
    )

    return builder.as_markup()


def get_admin_reports_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню отчётов администратора."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="📊 За 7 дней",
            callback_data="admin:report:7"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📊 За 30 дней",
            callback_data="admin:report:30"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📊 За 90 дней",
            callback_data="admin:report:90"
        )
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Админ меню", callback_data="admin:main")
    )

    return builder.as_markup()


def get_back_to_booking_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    """Клавиатура «Назад к брони» после просмотра фото."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="◀️ К брони",
            callback_data=f"admin:booking:{booking_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="◀️ К списку броней",
            callback_data="admin:bookings_menu"
        )
    )

    return builder.as_markup()


def get_admin_back_keyboard(back_to: str = "admin:main") -> InlineKeyboardMarkup:
    """Клавиатура «Назад» для администратора."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data=back_to)
    )

    return builder.as_markup()


def get_equipment_action_keyboard(equipment_id: int, is_available: bool) -> InlineKeyboardMarkup:
    """Клавиатура действий с оборудованием (включить / выключить из оборота)."""
    builder = InlineKeyboardBuilder()

    if is_available:
        builder.row(
            InlineKeyboardButton(
                text="🔴 Снять с оборота",
                callback_data=f"admin:disable_eq:{equipment_id}"
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="🟢 Вернуть в оборот",
                callback_data=f"admin:enable_eq:{equipment_id}"
            )
        )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="admin:equipment_menu")
    )

    return builder.as_markup()


# ============== КЛАВИАТУРЫ КАТЕГОРИЙ ==============

def get_db_categories_keyboard(
    categories: list[Category],
    callback_prefix: str = "category",
    back_callback: str = "menu:main",
) -> InlineKeyboardMarkup:
    """Клавиатура из объектов модели Category."""
    builder = InlineKeyboardBuilder()

    for cat in categories:
        builder.row(
            InlineKeyboardButton(
                text=f"📁 {cat.name}",
                callback_data=f"{callback_prefix}:{cat.id}"
            )
        )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data=back_callback)
    )

    return builder.as_markup()


def get_user_category_select_keyboard(
    categories: list[Category],
    selected_ids: list[int],
) -> InlineKeyboardMarkup:
    """Мультиселект для выбора категорий пользователя."""
    builder = InlineKeyboardBuilder()

    for cat in categories:
        check = "✅" if cat.id in selected_ids else "⬜"
        builder.row(
            InlineKeyboardButton(
                text=f"{check} {cat.name}",
                callback_data=f"user_cat_toggle:{cat.id}"
            )
        )

    builder.row(
        InlineKeyboardButton(text="💾 Сохранить", callback_data="user_cat_done"),
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="user_cat_skip"),
    )

    return builder.as_markup()


# ============== КЛАВИАТУРЫ ФИЛЬТРОВ ОТЧЁТОВ ==============

def get_report_filter_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора фильтра для отчёта."""
    builder = InlineKeyboardBuilder()

    builder.row(InlineKeyboardButton(text="📁 По категории", callback_data="report_filter:category"))
    builder.row(InlineKeyboardButton(text="👤 По сотруднику", callback_data="report_filter:user"))
    builder.row(InlineKeyboardButton(text="📅 За период", callback_data="report_filter:period"))
    builder.row(InlineKeyboardButton(text="📊 Все данные", callback_data="report_filter:all"))
    builder.row(InlineKeyboardButton(text="◀️ Админ меню", callback_data="admin:main"))

    return builder.as_markup()


def get_report_period_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора периода отчёта."""
    builder = InlineKeyboardBuilder()

    builder.row(InlineKeyboardButton(text="7 дней", callback_data="report_period:7"))
    builder.row(InlineKeyboardButton(text="30 дней", callback_data="report_period:30"))
    builder.row(InlineKeyboardButton(text="90 дней", callback_data="report_period:90"))
    builder.row(InlineKeyboardButton(text="📅 Произвольный период", callback_data="report_period:custom"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin:reports_menu"))

    return builder.as_markup()
