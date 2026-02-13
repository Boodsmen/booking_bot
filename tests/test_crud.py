"""Tests for CRUD operations with mocked session."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from database.models import Booking


@pytest.mark.asyncio
async def test_create_booking_overlap_detected(mock_session):
    """Test that overlapping booking is rejected."""
    with patch("database.crud.check_booking_overlap") as mock_overlap:
        mock_overlap.return_value = MagicMock(spec=Booking, id=99)

        from database.crud import create_booking

        now = datetime.now(timezone.utc)
        result = await create_booking(
            mock_session,
            equipment_id=1,
            user_id=123,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=3),
        )

        assert isinstance(result, str)
        assert "занят" in result


@pytest.mark.asyncio
async def test_create_booking_duration_limit(mock_session):
    """Test that booking exceeding max duration is rejected."""
    from database.crud import create_booking

    now = datetime.now(timezone.utc)
    result = await create_booking(
        mock_session,
        equipment_id=1,
        user_id=123,
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=200),  # Way over 72h limit
    )

    assert isinstance(result, str)
    assert "длительность" in result.lower() or "72" in result


@pytest.mark.asyncio
async def test_confirm_booking_status_change(mock_session):
    """Test that confirm changes pending to active."""
    booking = MagicMock(spec=Booking)
    booking.status = "pending"
    booking.start_time = datetime.now(timezone.utc)

    with patch("database.crud.get_booking_by_id", return_value=booking):
        from database.crud import confirm_booking

        result = await confirm_booking(mock_session, booking_id=1)

        assert result is not None
        assert booking.status == "active"
        assert booking.confirmed_at is not None


@pytest.mark.asyncio
async def test_confirm_booking_wrong_status(mock_session):
    """Test that confirm returns None for non-pending booking."""
    booking = MagicMock(spec=Booking)
    booking.status = "active"

    with patch("database.crud.get_booking_by_id", return_value=booking):
        from database.crud import confirm_booking

        result = await confirm_booking(mock_session, booking_id=1)
        assert result is None


@pytest.mark.asyncio
async def test_cancel_pending_booking(mock_session):
    """Test cancelling a pending booking."""
    booking = MagicMock(spec=Booking)
    booking.status = "pending"
    booking.start_time = datetime.now(timezone.utc) + timedelta(hours=1)

    with patch("database.crud.get_booking_by_id", return_value=booking):
        from database.crud import cancel_booking

        result = await cancel_booking(mock_session, booking_id=1)

        assert result is not None
        assert booking.status == "cancelled"


@pytest.mark.asyncio
async def test_expire_booking(mock_session):
    """Test expiring a pending booking."""
    booking = MagicMock(spec=Booking)
    booking.status = "pending"

    with patch("database.crud.get_booking_by_id", return_value=booking):
        from database.crud import expire_booking

        result = await expire_booking(mock_session, booking_id=1)

        assert result is not None
        assert booking.status == "expired"


@pytest.mark.asyncio
async def test_force_complete_booking(mock_session):
    """Test force-completing a booking."""
    booking = MagicMock(spec=Booking)
    booking.status = "active"
    booking.start_time = datetime.now(timezone.utc)

    with patch("database.crud.get_booking_by_id", return_value=booking):
        from database.crud import force_complete_booking

        result = await force_complete_booking(mock_session, booking_id=1)

        assert result is not None
        assert booking.status == "completed"
        assert booking.completed_at is not None


@pytest.mark.asyncio
async def test_complete_maintenance(mock_session):
    """Test completing a maintenance booking."""
    booking = MagicMock(spec=Booking)
    booking.status = "maintenance"
    booking.start_time = datetime.now(timezone.utc)

    with patch("database.crud.get_booking_by_id", return_value=booking):
        from database.crud import complete_maintenance

        result = await complete_maintenance(mock_session, booking_id=1)

        assert result is not None
        assert booking.status == "completed"


@pytest.mark.asyncio
async def test_complete_maintenance_wrong_status(mock_session):
    """Test that completing non-maintenance booking returns None."""
    booking = MagicMock(spec=Booking)
    booking.status = "active"

    with patch("database.crud.get_booking_by_id", return_value=booking):
        from database.crud import complete_maintenance

        result = await complete_maintenance(mock_session, booking_id=1)
        assert result is None


@pytest.mark.asyncio
async def test_set_confirmation_reminder_sent(mock_session):
    """Test setting confirmation_reminder_sent flag."""
    booking = MagicMock(spec=Booking)
    booking.confirmation_reminder_sent = False

    with patch("database.crud.get_booking_by_id", return_value=booking):
        from database.crud import set_confirmation_reminder_sent

        result = await set_confirmation_reminder_sent(mock_session, booking_id=1)

        assert result is not None
        assert booking.confirmation_reminder_sent is True


@pytest.mark.asyncio
async def test_set_overdue_notified(mock_session):
    """Test setting overdue_notified flag."""
    booking = MagicMock(spec=Booking)
    booking.overdue_notified = False

    with patch("database.crud.get_booking_by_id", return_value=booking):
        from database.crud import set_overdue_notified

        result = await set_overdue_notified(mock_session, booking_id=1)

        assert result is not None
        assert booking.overdue_notified is True
