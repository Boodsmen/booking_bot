"""Tests for scheduler tasks with mocked DB and bot."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_confirmation_reminder_not_sent_twice(mock_bot, sample_pending_booking, now_utc):
    """Test that confirmation reminder is not sent if already sent."""
    # Mark as already sent
    sample_pending_booking.confirmation_reminder_sent = True
    sample_pending_booking.start_time = now_utc  # Within window

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("scheduler.tasks.async_session_maker", return_value=mock_session), \
         patch("scheduler.tasks.crud.get_pending_bookings", return_value=[sample_pending_booking]):

        from scheduler.tasks import send_confirmation_reminders
        await send_confirmation_reminders(mock_bot)

    # Bot should NOT have been called
    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_confirmation_reminder_sent_once(mock_bot, sample_pending_booking, now_utc):
    """Test that confirmation reminder is sent when not yet sent and within window."""
    sample_pending_booking.confirmation_reminder_sent = False
    sample_pending_booking.start_time = now_utc  # Exactly now (within ±5min window)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("scheduler.tasks.async_session_maker", return_value=mock_session), \
         patch("scheduler.tasks.crud.get_pending_bookings", return_value=[sample_pending_booking]), \
         patch("scheduler.tasks.crud.set_confirmation_reminder_sent", return_value=sample_pending_booking):

        from scheduler.tasks import send_confirmation_reminders
        await send_confirmation_reminders(mock_bot)

    mock_bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_overdue_notification_not_sent_twice(mock_bot, sample_overdue_booking, now_utc):
    """Test that overdue user notification is not sent if already notified."""
    sample_overdue_booking.overdue_notified = True

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("scheduler.tasks.async_session_maker", return_value=mock_session), \
         patch("scheduler.tasks.crud.get_active_bookings", return_value=[sample_overdue_booking]):

        from scheduler.tasks import check_overdue_returns
        await check_overdue_returns(mock_bot)

    # User notification should NOT have been sent (already notified)
    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_overdue_notification_sent_once(mock_bot, sample_overdue_booking, now_utc):
    """Test that overdue user notification is sent when not yet notified."""
    sample_overdue_booking.overdue_notified = False
    sample_overdue_booking.is_overdue = False

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("scheduler.tasks.async_session_maker", return_value=mock_session), \
         patch("scheduler.tasks.crud.get_active_bookings", return_value=[sample_overdue_booking]), \
         patch("scheduler.tasks.crud.set_overdue_notified", return_value=sample_overdue_booking), \
         patch("scheduler.tasks.crud.set_booking_overdue", return_value=sample_overdue_booking), \
         patch("scheduler.tasks.crud.get_all_admins", return_value=[]):

        from scheduler.tasks import check_overdue_returns
        await check_overdue_returns(mock_bot)

    # User notification should have been sent exactly once
    assert mock_bot.send_message.call_count == 1


@pytest.mark.asyncio
async def test_auto_complete_old_bookings(mock_bot, sample_active_booking, now_utc):
    """Test that bookings older than 24h are auto-completed."""
    # Make booking 25 hours past end
    sample_active_booking.end_time = now_utc - timedelta(hours=25)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("scheduler.tasks.async_session_maker", return_value=mock_session), \
         patch("scheduler.tasks.crud.get_active_bookings", return_value=[sample_active_booking]), \
         patch("scheduler.tasks.crud.force_complete_booking", return_value=sample_active_booking):

        from scheduler.tasks import auto_complete_old_bookings
        await auto_complete_old_bookings(mock_bot)

    # User should be notified
    mock_bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_auto_complete_skips_recent_bookings(mock_bot, sample_active_booking, now_utc):
    """Test that bookings not yet 24h past end are NOT auto-completed."""
    # End time only 2 hours ago (< 24h threshold)
    sample_active_booking.end_time = now_utc - timedelta(hours=2)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("scheduler.tasks.async_session_maker", return_value=mock_session), \
         patch("scheduler.tasks.crud.get_active_bookings", return_value=[sample_active_booking]):

        from scheduler.tasks import auto_complete_old_bookings
        await auto_complete_old_bookings(mock_bot)

    # Nothing should have been sent
    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_booking_expiration(mock_bot, sample_pending_booking, now_utc):
    """Test that pending bookings past timeout are expired."""
    # Set start_time far in the past to trigger expiration
    sample_pending_booking.start_time = now_utc - timedelta(hours=1)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("scheduler.tasks.async_session_maker", return_value=mock_session), \
         patch("scheduler.tasks.crud.get_pending_bookings", return_value=[sample_pending_booking]), \
         patch("scheduler.tasks.crud.expire_booking", return_value=sample_pending_booking):

        from scheduler.tasks import check_booking_confirmations
        await check_booking_confirmations(mock_bot)

    # User should be notified about expiration
    mock_bot.send_message.assert_called_once()
