"""Вспомогательные функции: форматирование, работа со временем, фото."""

import uuid
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import TYPE_CHECKING

MSK = ZoneInfo("Europe/Moscow")
UTC = timezone.utc


def now_utc() -> datetime:
    """Текущее время в UTC (timezone-aware)."""
    return datetime.now(UTC)


def now_msk() -> datetime:
    """Текущее время в МСК без tzinfo. Для хранения/сравнения используйте now_utc()."""
    return datetime.now(MSK).replace(tzinfo=None)


def to_msk(dt: datetime) -> datetime:
    """Конвертировать aware datetime в московское время для отображения."""
    return dt.astimezone(MSK)


def parse_msk_naive(date_str: str, time_str: str) -> datetime:
    """Разобрать дату и время, введённые пользователем (МСК), и вернуть UTC-aware datetime."""
    naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    msk_aware = naive.replace(tzinfo=MSK)
    return msk_aware.astimezone(UTC)

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from database.models import Booking


async def save_photo_locally(bot, file_id: str, subdir: str) -> str:
    """
    Скачать фото из Telegram и сохранить локально.

    Возвращает путь к файлу, например: "data/photos/bookings/5/start/uuid.jpg"
    """
    photos_dir = Path("data/photos") / subdir
    photos_dir.mkdir(parents=True, exist_ok=True)

    file = await bot.get_file(file_id)
    ext = Path(file.file_path).suffix or ".jpg"
    local_path = photos_dir / f"{uuid.uuid4().hex}{ext}"
    await bot.download_file(file.file_path, destination=local_path)
    return str(local_path)


def format_datetime(dt: datetime | None, format_type: str = "user") -> str:
    """
    Форматировать datetime для отображения.

    format_type: "user" → дд.мм.гггг ЧЧ:ММ, "report" → гггг-мм-дд ЧЧ:ММ, "short" → дд.мм ЧЧ:ММ
    """
    if dt is None:
        return "-"

    if format_type == "user":
        return dt.strftime("%d.%m.%Y %H:%M")
    elif format_type == "report":
        return dt.strftime("%Y-%m-%d %H:%M")
    elif format_type == "short":
        return dt.strftime("%d.%m %H:%M")
    else:
        return dt.strftime("%d.%m.%Y %H:%M")


def format_booking_info(booking: "Booking", verbose: bool = False) -> str:
    """
    Форматировать информацию о брони для отображения пользователю.

    verbose=True — включить доп. детали (фото, временные метки, контакты).
    """
    status_map = {
        "pending": "⏳ Ожидает подтверждения",
        "active": "✅ Активна",
        "completed": "✔️ Завершена",
        "cancelled": "❌ Отменена",
        "expired": "⏰ Истекла",
        "maintenance": "🔧 Тех. обслуживание",
    }
    status_text = status_map.get(booking.status, booking.status)

    duration = booking.end_time - booking.start_time
    hours = int(duration.total_seconds() // 3600)
    minutes = int((duration.total_seconds() % 3600) // 60)
    duration_text = f"{hours}ч" if minutes == 0 else f"{hours}ч {minutes}м"

    lines = [
        f"<b>Бронь #{booking.id}</b>",
        f"Статус: {status_text}",
        f"",
        f"<b>Оборудование:</b> {booking.equipment.name}",
        f"<b>Категория:</b> {booking.equipment.category}",
        f"",
        f"<b>Начало:</b> {format_datetime(booking.start_time, 'user')}",
        f"<b>Конец:</b> {format_datetime(booking.end_time, 'user')}",
        f"<b>Длительность:</b> {duration_text}",
    ]

    if booking.is_overdue:
        overdue_mins = int((datetime.now(timezone.utc) - booking.end_time).total_seconds() // 60)
        lines.append(f"")
        lines.append(f"⚠️ <b>Просрочка:</b> {overdue_mins} минут")

    if verbose:
        lines.append(f"")
        lines.append(f"<b>Сотрудник:</b> {booking.user.full_name}")
        if booking.user.phone_number:
            lines.append(f"<b>Телефон:</b> {booking.user.phone_number}")

        lines.append(f"")
        lines.append(f"<b>Создана:</b> {format_datetime(booking.created_at, 'user')}")

        if booking.confirmed_at:
            lines.append(f"<b>Подтверждена:</b> {format_datetime(booking.confirmed_at, 'user')}")

        if booking.completed_at:
            lines.append(f"<b>Завершена:</b> {format_datetime(booking.completed_at, 'user')}")

        photo_start_count = len(booking.photos_start) if booking.photos_start else 0
        photo_end_count = len(booking.photos_end) if booking.photos_end else 0

        if photo_start_count > 0 or photo_end_count > 0:
            lines.append(f"")
            if photo_start_count > 0:
                lines.append(f"📷 Фото начала: {photo_start_count} шт.")
            if photo_end_count > 0:
                lines.append(f"📷 Фото конца: {photo_end_count} шт.")

    return "\n".join(lines)


async def get_available_time_slots(
    session: AsyncSession,
    equipment_id: int,
    target_date: date,
    slot_duration_minutes: int = 60,
    work_hours_start: int = 8,
    work_hours_end: int = 20,
) -> list[tuple[datetime, datetime]]:
    """
    Получить свободные временные слоты для оборудования на указанную дату.

    Возвращает список кортежей (start_time, end_time) доступных слотов.
    """
    from database.models import Booking

    day_start = datetime.combine(target_date, datetime.min.time()).replace(hour=work_hours_start, tzinfo=None)
    day_end = datetime.combine(target_date, datetime.min.time()).replace(hour=work_hours_end, tzinfo=None)

    query = select(Booking).where(
        and_(
            Booking.equipment_id == equipment_id,
            Booking.status.in_(["pending", "active"]),
            or_(
                # Бронь начинается в этот день
                and_(
                    Booking.start_time >= day_start,
                    Booking.start_time < day_end,
                ),
                # Бронь заканчивается в этот день
                and_(
                    Booking.end_time > day_start,
                    Booking.end_time <= day_end,
                ),
                # Бронь охватывает весь день
                and_(
                    Booking.start_time <= day_start,
                    Booking.end_time >= day_end,
                ),
            ),
        )
    ).order_by(Booking.start_time)

    result = await session.execute(query)
    bookings = result.scalars().all()

    if not bookings:
        available_slots = []
        current_time = day_start
        while current_time + timedelta(minutes=slot_duration_minutes) <= day_end:
            slot_end = current_time + timedelta(minutes=slot_duration_minutes)
            available_slots.append((current_time, slot_end))
            current_time = slot_end
        return available_slots

    available_slots = []
    current_time = day_start

    for booking in bookings:
        booking_start = max(booking.start_time, day_start)
        booking_end = min(booking.end_time, day_end)

        if current_time < booking_start:
            while current_time + timedelta(minutes=slot_duration_minutes) <= booking_start:
                slot_end = current_time + timedelta(minutes=slot_duration_minutes)
                available_slots.append((current_time, slot_end))
                current_time = slot_end

        current_time = max(current_time, booking_end)

    while current_time + timedelta(minutes=slot_duration_minutes) <= day_end:
        slot_end = current_time + timedelta(minutes=slot_duration_minutes)
        available_slots.append((current_time, slot_end))
        current_time = slot_end

    return available_slots
