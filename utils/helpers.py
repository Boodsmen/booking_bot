"""Helper functions for formatting and utilities."""

import uuid
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import TYPE_CHECKING

MSK = ZoneInfo("Europe/Moscow")


def now_msk() -> datetime:
    """Return current datetime in Moscow timezone (naive, for display/comparison)."""
    return datetime.now(MSK).replace(tzinfo=None)

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from database.models import Booking


async def save_photo_locally(bot, file_id: str, subdir: str) -> str:
    """
    Download a Telegram photo and save it locally.

    Args:
        bot: Aiogram Bot instance
        file_id: Telegram file_id
        subdir: Subdirectory under data/photos/ (e.g. "bookings/5/start")

    Returns:
        Local path string (e.g. "data/photos/bookings/5/start/uuid.jpg")
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
    Format datetime for display.

    Args:
        dt: Datetime to format (can be None)
        format_type: "user" for user-friendly (dd.mm.yyyy HH:MM),
                    "report" for Excel reports (yyyy-mm-dd HH:MM),
                    "short" for compact (dd.mm HH:MM)

    Returns:
        Formatted string or "-" if dt is None
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
    Format booking information for display to user.

    Args:
        booking: Booking object with loaded relationships
        verbose: If True, include all details (photos, timestamps, etc.)

    Returns:
        Formatted multi-line string with booking info
    """
    # Status translations
    status_map = {
        "pending": "⏳ Ожидает подтверждения",
        "active": "✅ Активна",
        "completed": "✔️ Завершена",
        "cancelled": "❌ Отменена",
        "expired": "⏰ Истекла",
        "maintenance": "🔧 Тех. обслуживание",
    }
    status_text = status_map.get(booking.status, booking.status)

    # Calculate duration
    duration = booking.end_time - booking.start_time
    hours = int(duration.total_seconds() // 3600)
    minutes = int((duration.total_seconds() % 3600) // 60)
    duration_text = f"{hours}ч" if minutes == 0 else f"{hours}ч {minutes}м"

    # Basic info
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

    # Overdue warning
    if booking.is_overdue:
        overdue_mins = int((datetime.now(timezone.utc) - booking.end_time).total_seconds() // 60)
        lines.append(f"")
        lines.append(f"⚠️ <b>Просрочка:</b> {overdue_mins} минут")

    # Verbose mode - add extra details
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

        # Photo counts
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
    Get available time slots for equipment on a specific date.

    Args:
        session: Database session
        equipment_id: Equipment ID to check
        target_date: Date to check availability
        slot_duration_minutes: Duration of each slot in minutes (default 60)
        work_hours_start: Start of work hours (default 8:00)
        work_hours_end: End of work hours (default 20:00)

    Returns:
        List of (start_time, end_time) tuples for available slots
    """
    from database.models import Booking

    # Define day boundaries
    day_start = datetime.combine(target_date, datetime.min.time()).replace(hour=work_hours_start, tzinfo=None)
    day_end = datetime.combine(target_date, datetime.min.time()).replace(hour=work_hours_end, tzinfo=None)

    # Get all bookings for this equipment on this date
    query = select(Booking).where(
        and_(
            Booking.equipment_id == equipment_id,
            Booking.status.in_(["pending", "active"]),
            or_(
                # Booking starts on this day
                and_(
                    Booking.start_time >= day_start,
                    Booking.start_time < day_end,
                ),
                # Booking ends on this day
                and_(
                    Booking.end_time > day_start,
                    Booking.end_time <= day_end,
                ),
                # Booking spans the entire day
                and_(
                    Booking.start_time <= day_start,
                    Booking.end_time >= day_end,
                ),
            ),
        )
    ).order_by(Booking.start_time)

    result = await session.execute(query)
    bookings = result.scalars().all()

    # If no bookings, entire day is available
    if not bookings:
        available_slots = []
        current_time = day_start
        while current_time + timedelta(minutes=slot_duration_minutes) <= day_end:
            slot_end = current_time + timedelta(minutes=slot_duration_minutes)
            available_slots.append((current_time, slot_end))
            current_time = slot_end
        return available_slots

    # Find gaps between bookings
    available_slots = []
    current_time = day_start

    for booking in bookings:
        booking_start = max(booking.start_time, day_start)
        booking_end = min(booking.end_time, day_end)

        # If there's a gap before this booking
        if current_time < booking_start:
            # Split gap into slots
            while current_time + timedelta(minutes=slot_duration_minutes) <= booking_start:
                slot_end = current_time + timedelta(minutes=slot_duration_minutes)
                available_slots.append((current_time, slot_end))
                current_time = slot_end

        # Move current_time past this booking
        current_time = max(current_time, booking_end)

    # Check for gap after last booking
    while current_time + timedelta(minutes=slot_duration_minutes) <= day_end:
        slot_end = current_time + timedelta(minutes=slot_duration_minutes)
        available_slots.append((current_time, slot_end))
        current_time = slot_end

    return available_slots
