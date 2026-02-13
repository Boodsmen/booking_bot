"""CRUD operations for database."""

from datetime import datetime, timedelta

from sqlalchemy import select, and_, or_, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database.models import User, Equipment, Booking, Category, UserCategory
from utils.cache import equipment_cache
from utils.logger import logger


# ============== USER OPERATIONS ==============

async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    telegram_id: int,
    full_name: str,
    username: str | None = None,
    phone_number: str | None = None,
    is_admin: bool = False,
) -> User:
    user = User(
        telegram_id=telegram_id,
        full_name=full_name,
        username=username,
        phone_number=phone_number,
        is_admin=is_admin,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    logger.info(f"Created user: {telegram_id} ({full_name}), admin={is_admin}")
    return user


async def get_all_admins(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User).where(User.is_admin == True)
    )
    return list(result.scalars().all())


async def get_all_users(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User).order_by(User.full_name)
    )
    return list(result.scalars().all())


async def update_user(
    session: AsyncSession,
    telegram_id: int,
    **kwargs,
) -> User | None:
    user = await get_user(session, telegram_id)
    if not user:
        return None

    for key, value in kwargs.items():
        if hasattr(user, key):
            setattr(user, key, value)

    await session.commit()
    await session.refresh(user)

    logger.info(f"Updated user {telegram_id}: {kwargs}")
    return user


# ============== CATEGORY OPERATIONS ==============

async def get_all_categories_from_db(session: AsyncSession) -> list[Category]:
    """Get all categories from categories table."""
    cache_key = "all_categories_db"
    cached = equipment_cache.get(cache_key)
    if cached is not None:
        return cached

    result = await session.execute(
        select(Category).order_by(Category.name)
    )
    categories = list(result.scalars().all())
    equipment_cache.set(cache_key, categories)
    return categories


async def get_category_by_id(session: AsyncSession, category_id: int) -> Category | None:
    result = await session.execute(
        select(Category).where(Category.id == category_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_category(session: AsyncSession, name: str) -> Category:
    """Get existing category by name or create new one."""
    result = await session.execute(
        select(Category).where(Category.name == name)
    )
    category = result.scalar_one_or_none()
    if category:
        return category

    category = Category(name=name)
    session.add(category)
    await session.commit()
    await session.refresh(category)
    equipment_cache.clear()
    logger.info(f"Created category: {category.id} - {name}")
    return category


# ============== USER CATEGORY OPERATIONS ==============

async def get_user_categories(session: AsyncSession, user_id: int) -> list[Category]:
    """Get categories assigned to a user."""
    result = await session.execute(
        select(Category)
        .join(UserCategory, UserCategory.category_id == Category.id)
        .where(UserCategory.user_id == user_id)
        .order_by(Category.name)
    )
    return list(result.scalars().all())


async def set_user_categories(session: AsyncSession, user_id: int, category_ids: list[int]) -> None:
    """Set user's accessible categories (replace all)."""
    await session.execute(
        delete(UserCategory).where(UserCategory.user_id == user_id)
    )
    for cat_id in category_ids:
        session.add(UserCategory(user_id=user_id, category_id=cat_id))
    await session.commit()
    logger.info(f"Set categories for user {user_id}: {category_ids}")


async def get_categories_for_user(session: AsyncSession, user_id: int, is_admin: bool = False) -> list[Category]:
    """Get categories accessible to a user. Admins and users with no categories get all."""
    if is_admin:
        return await get_all_categories_from_db(session)

    user_cats = await get_user_categories(session, user_id)
    if not user_cats:
        # No categories assigned -> access to all (backward compatibility)
        return await get_all_categories_from_db(session)
    return user_cats


# ============== EQUIPMENT OPERATIONS ==============

async def get_all_equipment(
    session: AsyncSession,
    only_available: bool = True,
    category_ids: list[int] | None = None,
) -> list[Equipment]:
    cache_key = f"all_equipment:{only_available}:{category_ids}"
    cached = equipment_cache.get(cache_key)
    if cached is not None:
        return cached

    query = select(Equipment).order_by(Equipment.category, Equipment.name)
    if only_available:
        query = query.where(Equipment.is_available == True)
    if category_ids is not None:
        query = query.where(Equipment.category_id.in_(category_ids))

    result = await session.execute(query)
    equipment_list = list(result.scalars().all())

    equipment_cache.set(cache_key, equipment_list)
    return equipment_list


async def get_equipment_by_id(
    session: AsyncSession,
    equipment_id: int,
) -> Equipment | None:
    result = await session.execute(
        select(Equipment).where(Equipment.id == equipment_id)
    )
    return result.scalar_one_or_none()


async def get_equipment_by_category(
    session: AsyncSession,
    category: str,
    only_available: bool = True,
) -> list[Equipment]:
    query = select(Equipment).where(Equipment.category == category).order_by(Equipment.name)
    if only_available:
        query = query.where(Equipment.is_available == True)

    result = await session.execute(query)
    return list(result.scalars().all())


async def get_equipment_by_category_id(
    session: AsyncSession,
    category_id: int,
    only_available: bool = True,
) -> list[Equipment]:
    query = select(Equipment).where(Equipment.category_id == category_id).order_by(Equipment.name)
    if only_available:
        query = query.where(Equipment.is_available == True)

    result = await session.execute(query)
    return list(result.scalars().all())


async def get_equipment_by_license_plate(
    session: AsyncSession,
    license_plate: str,
) -> Equipment | None:
    license_plate_normalized = license_plate.strip().upper()

    result = await session.execute(
        select(Equipment).where(Equipment.license_plate == license_plate_normalized)
    )
    return result.scalar_one_or_none()


async def get_all_categories(session: AsyncSession) -> list[str]:
    """Get all unique equipment categories (from categories table first, fallback to equipment.category)."""
    cache_key = "all_categories"
    cached = equipment_cache.get(cache_key)
    if cached is not None:
        return cached

    # Try from categories table first
    db_cats = await get_all_categories_from_db(session)
    if db_cats:
        categories = [c.name for c in db_cats]
        equipment_cache.set(cache_key, categories)
        return categories

    # Fallback: distinct from equipment table
    result = await session.execute(
        select(Equipment.category)
        .where(Equipment.is_available == True)
        .distinct()
        .order_by(Equipment.category)
    )
    categories = list(result.scalars().all())

    equipment_cache.set(cache_key, categories)
    return categories


async def create_equipment(
    session: AsyncSession,
    name: str,
    category: str,
    category_id: int | None = None,
    license_plate: str | None = None,
    requires_photo: bool = False,
    quantity: int = 1,
) -> Equipment:
    if license_plate:
        license_plate = license_plate.strip().upper()

    equipment = Equipment(
        name=name,
        category=category,
        category_id=category_id,
        license_plate=license_plate,
        requires_photo=requires_photo,
        quantity=max(1, quantity),
    )
    session.add(equipment)
    await session.commit()
    await session.refresh(equipment)

    equipment_cache.clear()

    logger.info(f"Created equipment: {equipment.id} - {name} ({category})")
    return equipment


async def update_equipment_availability(
    session: AsyncSession,
    equipment_id: int,
    is_available: bool,
) -> Equipment | None:
    equipment = await get_equipment_by_id(session, equipment_id)
    if not equipment:
        return None

    equipment.is_available = is_available
    await session.commit()
    await session.refresh(equipment)

    equipment_cache.clear()

    logger.info(f"Equipment {equipment_id} availability: {is_available}")
    return equipment


async def search_equipment(
    session: AsyncSession,
    query_text: str,
    category_ids: list[int] | None = None,
    only_available: bool = True,
) -> list[Equipment]:
    """Search equipment by name or license plate (ILIKE)."""
    pattern = f"%{query_text}%"
    query = select(Equipment).where(
        or_(
            Equipment.name.ilike(pattern),
            Equipment.license_plate.ilike(pattern),
        )
    ).order_by(Equipment.name)

    if only_available:
        query = query.where(Equipment.is_available == True)

    if category_ids:
        query = query.where(Equipment.category_id.in_(category_ids))

    result = await session.execute(query)
    return list(result.scalars().all())


# ============== BOOKING OPERATIONS ==============

async def get_equipment_available_count(
    session: AsyncSession,
    equipment_id: int,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> int:
    """Return number of available units for equipment at given time range."""
    equipment = await get_equipment_by_id(session, equipment_id)
    if not equipment:
        return 0

    query = select(func.count()).select_from(Booking).where(
        and_(
            Booking.equipment_id == equipment_id,
            Booking.status.in_(["pending", "active", "maintenance"]),
        )
    )

    if start_time is not None and end_time is not None:
        query = query.where(
            and_(
                Booking.start_time < end_time,
                Booking.end_time > start_time,
            )
        )

    result = await session.execute(query)
    overlapping_count = result.scalar() or 0

    return max(0, equipment.quantity - overlapping_count)


async def check_booking_overlap(
    session: AsyncSession,
    equipment_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_booking_id: int | None = None,
) -> Booking | None:
    query = (
        select(Booking)
        .where(
            and_(
                Booking.equipment_id == equipment_id,
                Booking.status.in_(["pending", "active", "maintenance"]),
                Booking.start_time < end_time,
                Booking.end_time > start_time,
            )
        )
        .with_for_update()
    )

    if exclude_booking_id:
        query = query.where(Booking.id != exclude_booking_id)

    result = await session.execute(query)
    return result.scalar_one_or_none()


async def create_booking(
    session: AsyncSession,
    equipment_id: int,
    user_id: int,
    start_time: datetime,
    end_time: datetime,
) -> Booking | str:
    duration = end_time - start_time
    max_duration = timedelta(hours=settings.max_booking_duration_hours)
    if duration > max_duration:
        return f"Максимальная длительность брони: {settings.max_booking_duration_hours} часов"

    now = datetime.now(start_time.tzinfo)
    max_future = timedelta(days=settings.max_future_booking_days)
    if start_time > now + max_future:
        return f"Нельзя бронировать более чем на {settings.max_future_booking_days} дней вперед"

    available = await get_equipment_available_count(session, equipment_id, start_time, end_time)
    if available <= 0:
        return "Этот временной слот уже занят"

    booking = Booking(
        equipment_id=equipment_id,
        user_id=user_id,
        start_time=start_time,
        end_time=end_time,
        status="pending",
    )
    session.add(booking)
    await session.commit()
    await session.refresh(booking)

    logger.info(f"Created booking: {booking.id} for user {user_id}, equipment {equipment_id}")
    return booking


async def get_booking_by_id(
    session: AsyncSession,
    booking_id: int,
    load_relations: bool = False,
) -> Booking | None:
    query = select(Booking).where(Booking.id == booking_id)

    if load_relations:
        query = query.options(
            selectinload(Booking.user),
            selectinload(Booking.equipment),
        )

    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_user_bookings(
    session: AsyncSession,
    user_id: int,
    statuses: list[str] | None = None,
    load_relations: bool = True,
) -> list[Booking]:
    if statuses is None:
        statuses = ["pending", "active"]

    query = (
        select(Booking)
        .where(
            and_(
                Booking.user_id == user_id,
                Booking.status.in_(statuses),
            )
        )
        .order_by(Booking.start_time)
    )

    if load_relations:
        query = query.options(selectinload(Booking.equipment))

    result = await session.execute(query)
    return list(result.scalars().all())


async def get_pending_bookings(session: AsyncSession) -> list[Booking]:
    result = await session.execute(
        select(Booking)
        .where(Booking.status == "pending")
        .options(
            selectinload(Booking.user),
            selectinload(Booking.equipment),
        )
        .order_by(Booking.start_time)
    )
    return list(result.scalars().all())


async def get_active_bookings(session: AsyncSession) -> list[Booking]:
    result = await session.execute(
        select(Booking)
        .where(Booking.status == "active")
        .options(
            selectinload(Booking.user),
            selectinload(Booking.equipment),
        )
        .order_by(Booking.end_time)
    )
    return list(result.scalars().all())


async def confirm_booking(
    session: AsyncSession,
    booking_id: int,
    photos_start: list[str] | None = None,
) -> Booking | None:
    booking = await get_booking_by_id(session, booking_id)
    if not booking or booking.status != "pending":
        return None

    booking.status = "active"
    booking.confirmed_at = datetime.now(booking.start_time.tzinfo)
    if photos_start:
        booking.photos_start = photos_start

    await session.commit()
    await session.refresh(booking)

    logger.info(f"Booking {booking_id} confirmed (active)")
    return booking


async def complete_booking(
    session: AsyncSession,
    booking_id: int,
    photos_end: list[str] | None = None,
) -> Booking | None:
    booking = await get_booking_by_id(session, booking_id)
    if not booking or booking.status != "active":
        return None

    booking.status = "completed"
    booking.completed_at = datetime.now(booking.start_time.tzinfo)
    if photos_end:
        booking.photos_end = photos_end

    await session.commit()
    await session.refresh(booking)

    logger.info(f"Booking {booking_id} completed")
    return booking


async def cancel_booking(
    session: AsyncSession,
    booking_id: int,
) -> Booking | None:
    booking = await get_booking_by_id(session, booking_id)
    if not booking:
        return None

    now = datetime.now(booking.start_time.tzinfo)

    if booking.status == "pending":
        booking.status = "cancelled"
        await session.commit()
        await session.refresh(booking)
        logger.info(f"Booking {booking_id} cancelled (was pending)")
        return booking

    if booking.status == "active" and booking.start_time > now:
        booking.status = "cancelled"
        await session.commit()
        await session.refresh(booking)
        logger.info(f"Booking {booking_id} cancelled (was active, not started)")
        return booking

    return None


async def expire_booking(
    session: AsyncSession,
    booking_id: int,
) -> Booking | None:
    booking = await get_booking_by_id(session, booking_id)
    if not booking or booking.status != "pending":
        return None

    booking.status = "expired"
    await session.commit()
    await session.refresh(booking)

    logger.info(f"Booking {booking_id} expired")
    return booking


async def force_complete_booking(
    session: AsyncSession,
    booking_id: int,
) -> Booking | None:
    booking = await get_booking_by_id(session, booking_id)
    if not booking:
        return None

    old_status = booking.status
    booking.status = "completed"
    booking.completed_at = datetime.now(booking.start_time.tzinfo)
    await session.commit()
    await session.refresh(booking)

    logger.info(f"Booking {booking_id} force completed by admin (was {old_status})")
    return booking


async def set_booking_overdue(
    session: AsyncSession,
    booking_id: int,
) -> Booking | None:
    booking = await get_booking_by_id(session, booking_id)
    if not booking:
        return None

    booking.is_overdue = True
    await session.commit()
    await session.refresh(booking)

    logger.info(f"Booking {booking_id} marked as overdue")
    return booking


async def set_reminder_sent(
    session: AsyncSession,
    booking_id: int,
) -> Booking | None:
    booking = await get_booking_by_id(session, booking_id)
    if not booking:
        return None

    booking.reminder_sent = True
    await session.commit()
    await session.refresh(booking)

    return booking


async def set_confirmation_reminder_sent(
    session: AsyncSession,
    booking_id: int,
) -> Booking | None:
    booking = await get_booking_by_id(session, booking_id)
    if not booking:
        return None

    booking.confirmation_reminder_sent = True
    await session.commit()
    await session.refresh(booking)

    return booking


async def set_overdue_notified(
    session: AsyncSession,
    booking_id: int,
) -> Booking | None:
    booking = await get_booking_by_id(session, booking_id)
    if not booking:
        return None

    booking.overdue_notified = True
    await session.commit()
    await session.refresh(booking)

    return booking


# ============== MAINTENANCE OPERATIONS ==============

async def create_maintenance_booking(
    session: AsyncSession,
    equipment_id: int,
    admin_id: int,
    start_time: datetime,
    end_time: datetime,
    reason: str,
) -> Booking | str:
    overlap = await check_booking_overlap(session, equipment_id, start_time, end_time)
    if overlap:
        return "Этот временной слот уже занят другой бронью"

    booking = Booking(
        equipment_id=equipment_id,
        user_id=admin_id,
        start_time=start_time,
        end_time=end_time,
        status="maintenance",
        maintenance_reason=reason,
    )
    session.add(booking)
    await session.commit()
    await session.refresh(booking)

    logger.info(f"Created maintenance booking: {booking.id} for equipment {equipment_id}, reason: {reason}")
    return booking


async def get_maintenance_bookings(
    session: AsyncSession,
    equipment_id: int | None = None,
) -> list[Booking]:
    query = (
        select(Booking)
        .where(Booking.status == "maintenance")
        .options(
            selectinload(Booking.user),
            selectinload(Booking.equipment),
        )
        .order_by(Booking.start_time)
    )

    if equipment_id is not None:
        query = query.where(Booking.equipment_id == equipment_id)

    result = await session.execute(query)
    return list(result.scalars().all())


async def complete_maintenance(
    session: AsyncSession,
    booking_id: int,
) -> Booking | None:
    booking = await get_booking_by_id(session, booking_id)
    if not booking or booking.status != "maintenance":
        return None

    booking.status = "completed"
    booking.completed_at = datetime.now(booking.start_time.tzinfo)
    await session.commit()
    await session.refresh(booking)

    logger.info(f"Maintenance booking {booking_id} completed")
    return booking
