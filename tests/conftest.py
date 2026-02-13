"""Pytest fixtures for booking bot tests."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from database.models import User, Equipment, Booking


@pytest.fixture
def mock_session():
    """Create a mock async session."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


@pytest.fixture
def mock_bot():
    """Create a mock bot instance."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def sample_user():
    """Create a sample user."""
    user = MagicMock(spec=User)
    user.telegram_id = 123456789
    user.full_name = "Test User"
    user.username = "testuser"
    user.phone_number = "+7 900 000-00-00"
    user.is_admin = False
    return user


@pytest.fixture
def sample_admin():
    """Create a sample admin user."""
    user = MagicMock(spec=User)
    user.telegram_id = 987654321
    user.full_name = "Admin User"
    user.username = "adminuser"
    user.phone_number = "+7 900 111-11-11"
    user.is_admin = True
    return user


@pytest.fixture
def sample_equipment():
    """Create a sample equipment."""
    eq = MagicMock(spec=Equipment)
    eq.id = 1
    eq.name = "Toyota Camry"
    eq.category = "Автомобили"
    eq.license_plate = "А111АА97"
    eq.is_available = True
    eq.requires_photo = False
    return eq


@pytest.fixture
def now_utc():
    """Get current UTC time."""
    return datetime.now(timezone.utc)


@pytest.fixture
def sample_pending_booking(sample_user, sample_equipment, now_utc):
    """Create a sample pending booking."""
    booking = MagicMock(spec=Booking)
    booking.id = 1
    booking.equipment_id = sample_equipment.id
    booking.user_id = sample_user.telegram_id
    booking.start_time = now_utc + timedelta(hours=1)
    booking.end_time = now_utc + timedelta(hours=3)
    booking.status = "pending"
    booking.is_overdue = False
    booking.reminder_sent = False
    booking.confirmation_reminder_sent = False
    booking.overdue_notified = False
    booking.maintenance_reason = None
    booking.photos_start = None
    booking.photos_end = None
    booking.confirmed_at = None
    booking.completed_at = None
    booking.user = sample_user
    booking.equipment = sample_equipment
    return booking


@pytest.fixture
def sample_active_booking(sample_user, sample_equipment, now_utc):
    """Create a sample active booking."""
    booking = MagicMock(spec=Booking)
    booking.id = 2
    booking.equipment_id = sample_equipment.id
    booking.user_id = sample_user.telegram_id
    booking.start_time = now_utc - timedelta(hours=1)
    booking.end_time = now_utc + timedelta(hours=2)
    booking.status = "active"
    booking.is_overdue = False
    booking.reminder_sent = False
    booking.confirmation_reminder_sent = False
    booking.overdue_notified = False
    booking.maintenance_reason = None
    booking.photos_start = None
    booking.photos_end = None
    booking.confirmed_at = now_utc - timedelta(hours=1)
    booking.completed_at = None
    booking.user = sample_user
    booking.equipment = sample_equipment
    return booking


@pytest.fixture
def sample_overdue_booking(sample_user, sample_equipment, now_utc):
    """Create a sample overdue active booking."""
    booking = MagicMock(spec=Booking)
    booking.id = 3
    booking.equipment_id = sample_equipment.id
    booking.user_id = sample_user.telegram_id
    booking.start_time = now_utc - timedelta(hours=5)
    booking.end_time = now_utc - timedelta(hours=2)
    booking.status = "active"
    booking.is_overdue = False
    booking.reminder_sent = True
    booking.confirmation_reminder_sent = False
    booking.overdue_notified = False
    booking.maintenance_reason = None
    booking.photos_start = None
    booking.photos_end = None
    booking.confirmed_at = now_utc - timedelta(hours=5)
    booking.completed_at = None
    booking.user = sample_user
    booking.equipment = sample_equipment
    return booking
