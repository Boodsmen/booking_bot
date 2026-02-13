"""APScheduler tasks: reminders, expiration, overdue checks, auto-complete, heartbeat."""

import os
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config import settings
from database.db import async_session_maker
from database import crud
from keyboards.inline import get_booking_actions_keyboard
from utils.logger import logger

HEARTBEAT_FILE = "logs/scheduler_heartbeat"


async def check_booking_confirmations(bot: Bot) -> None:
    """
    Check for pending bookings that need to be expired.

    Runs every 1 minute. Expires pending bookings where:
    - start_time < now - confirmation_timeout_minutes

    Args:
        bot: Bot instance for sending messages
    """
    try:
        async with async_session_maker() as session:
            # Get all pending bookings
            bookings = await crud.get_pending_bookings(session)

            now = datetime.now(timezone.utc)
            timeout = timedelta(minutes=settings.confirmation_timeout_minutes)

            expired_count = 0

            for booking in bookings:
                # Check if booking should be expired
                # Expire if start_time has passed + timeout period
                if booking.start_time + timeout < now:
                    # Expire the booking
                    await crud.expire_booking(session, booking.id)

                    # Notify user
                    try:
                        await bot.send_message(
                            chat_id=booking.user_id,
                            text=(
                                f"❌ <b>Бронь отменена</b>\n\n"
                                f"Оборудование: {booking.equipment.name}\n"
                                f"Причина: Не подтверждено начало использования в течение "
                                f"{settings.confirmation_timeout_minutes} минут после начала брони.\n\n"
                                f"Бронь автоматически отменена."
                            )
                        )
                        expired_count += 1
                        logger.info(
                            f"Expired booking {booking.id} for user {booking.user_id} "
                            f"(equipment: {booking.equipment.name})"
                        )
                    except TelegramAPIError as e:
                        logger.error(
                            f"Failed to notify user {booking.user_id} about expired booking {booking.id}: {e}"
                        )

            if expired_count > 0:
                logger.info(f"Expired {expired_count} pending booking(s)")

    except Exception as e:
        logger.error(f"Error in check_booking_confirmations: {e}", exc_info=True)


async def send_confirmation_reminders(bot: Bot) -> None:
    """
    Send reminders to confirm booking start.

    Runs every 1 minute. Sends reminder for pending bookings where:
    - start_time is within 5 minutes from now (past or future)
    - User hasn't confirmed yet

    Args:
        bot: Bot instance for sending messages
    """
    try:
        async with async_session_maker() as session:
            # Get all pending bookings
            bookings = await crud.get_pending_bookings(session)

            now = datetime.now(timezone.utc)
            reminder_window = timedelta(minutes=5)

            sent_count = 0

            for booking in bookings:
                # Skip if reminder already sent
                if booking.confirmation_reminder_sent:
                    continue

                # Check if start_time is within 5 minutes (before or after now)
                time_until_start = booking.start_time - now

                # Send reminder if start_time is within [-5min, +5min] window
                if abs(time_until_start.total_seconds()) <= reminder_window.total_seconds():
                    # Send confirmation reminder with action button
                    try:
                        keyboard = get_booking_actions_keyboard(booking)

                        if time_until_start.total_seconds() > 0:
                            time_msg = f"через {int(time_until_start.total_seconds() / 60)} мин"
                        else:
                            time_msg = "сейчас"

                        await bot.send_message(
                            chat_id=booking.user_id,
                            text=(
                                f"⏰ <b>Напоминание о брони</b>\n\n"
                                f"Оборудование: {booking.equipment.name}\n"
                                f"Время начала: {time_msg}\n\n"
                                f"Пожалуйста, подтвердите начало использования."
                            ),
                            reply_markup=keyboard
                        )
                        # Mark reminder as sent to prevent duplicates
                        await crud.set_confirmation_reminder_sent(session, booking.id)

                        sent_count += 1
                        logger.info(
                            f"Sent confirmation reminder for booking {booking.id} "
                            f"to user {booking.user_id}"
                        )
                    except TelegramAPIError as e:
                        logger.error(
                            f"Failed to send confirmation reminder to user {booking.user_id} "
                            f"for booking {booking.id}: {e}"
                        )

            if sent_count > 0:
                logger.info(f"Sent {sent_count} confirmation reminder(s)")

    except Exception as e:
        logger.error(f"Error in send_confirmation_reminders: {e}", exc_info=True)


async def send_end_reminders(bot: Bot) -> None:
    """
    Send reminders to return equipment before booking ends.

    Runs every 5 minutes. Sends reminder for active bookings where:
    - end_time is within reminder_minutes_before (default 15 min)
    - reminder_sent flag is False

    Args:
        bot: Bot instance for sending messages
    """
    try:
        async with async_session_maker() as session:
            # Get all active bookings
            bookings = await crud.get_active_bookings(session)

            now = datetime.now(timezone.utc)
            reminder_before = timedelta(minutes=settings.reminder_minutes_before)

            sent_count = 0

            for booking in bookings:
                # Skip if reminder already sent
                if booking.reminder_sent:
                    continue

                # Check if end_time is approaching
                time_until_end = booking.end_time - now

                # Send reminder if end_time is within reminder window
                if timedelta(0) < time_until_end <= reminder_before:
                    try:
                        minutes_left = int(time_until_end.total_seconds() / 60)

                        await bot.send_message(
                            chat_id=booking.user_id,
                            text=(
                                f"⏰ <b>Напоминание о возврате</b>\n\n"
                                f"Оборудование: {booking.equipment.name}\n"
                                f"Осталось времени: {minutes_left} мин\n\n"
                                f"Пожалуйста, верните оборудование вовремя."
                            )
                        )

                        # Mark reminder as sent
                        await crud.set_reminder_sent(session, booking.id)

                        sent_count += 1
                        logger.info(
                            f"Sent end reminder for booking {booking.id} "
                            f"to user {booking.user_id} ({minutes_left} min left)"
                        )
                    except TelegramAPIError as e:
                        logger.error(
                            f"Failed to send end reminder to user {booking.user_id} "
                            f"for booking {booking.id}: {e}"
                        )

            if sent_count > 0:
                logger.info(f"Sent {sent_count} end reminder(s)")

    except Exception as e:
        logger.error(f"Error in send_end_reminders: {e}", exc_info=True)


async def check_overdue_returns(bot: Bot) -> None:
    """
    Check for overdue equipment returns and notify users/admins.

    Runs every 5 minutes. For active bookings where end_time has passed:
    - Sends immediate notification to user
    - If overdue > overdue_alert_minutes (default 30 min), notify admins
    - Sets is_overdue flag

    Args:
        bot: Bot instance for sending messages
    """
    try:
        async with async_session_maker() as session:
            # Get all active bookings
            bookings = await crud.get_active_bookings(session)

            now = datetime.now(timezone.utc)
            admin_alert_threshold = timedelta(minutes=settings.overdue_alert_minutes)

            user_notified = 0
            admin_notified = 0

            for booking in bookings:
                # Check if booking is overdue
                if booking.end_time >= now:
                    continue  # Not overdue yet

                overdue_duration = now - booking.end_time
                overdue_minutes = int(overdue_duration.total_seconds() / 60)

                # Notify user about overdue (only once)
                if not booking.overdue_notified:
                    try:
                        keyboard = get_booking_actions_keyboard(booking)

                        await bot.send_message(
                            chat_id=booking.user_id,
                            text=(
                                f"⚠️ <b>Просрочен возврат оборудования!</b>\n\n"
                                f"Оборудование: {booking.equipment.name}\n"
                                f"Просрочено: {overdue_minutes} мин\n\n"
                                f"Пожалуйста, верните оборудование как можно скорее."
                            ),
                            reply_markup=keyboard
                        )

                        # Mark as notified to prevent duplicates
                        await crud.set_overdue_notified(session, booking.id)

                        user_notified += 1
                        logger.info(
                            f"Notified user {booking.user_id} about overdue booking {booking.id} "
                            f"({overdue_minutes} min overdue)"
                        )
                    except TelegramAPIError as e:
                        logger.error(
                            f"Failed to notify user {booking.user_id} about overdue booking {booking.id}: {e}"
                        )

                # If seriously overdue and not already flagged, notify admins
                if overdue_duration >= admin_alert_threshold and not booking.is_overdue:
                    # Mark as overdue
                    await crud.set_booking_overdue(session, booking.id)

                    # Get all admins
                    admins = await crud.get_all_admins(session)

                    # Notify each admin
                    for admin in admins:
                        try:
                            await bot.send_message(
                                chat_id=admin.telegram_id,
                                text=(
                                    f"🚨 <b>КРИТИЧЕСКАЯ ПРОСРОЧКА</b>\n\n"
                                    f"Сотрудник: {booking.user.full_name} (@{booking.user.username or 'без username'})\n"
                                    f"Телефон: {booking.user.phone_number or 'не указан'}\n"
                                    f"Оборудование: {booking.equipment.name}\n"
                                    f"Просрочено: {overdue_minutes} мин\n\n"
                                    f"Требуется вмешательство администратора."
                                )
                            )
                            admin_notified += 1
                        except TelegramAPIError as e:
                            logger.error(
                                f"Failed to notify admin {admin.telegram_id} about overdue booking {booking.id}: {e}"
                            )

                    logger.warning(
                        f"CRITICAL OVERDUE: Booking {booking.id} by user {booking.user_id} "
                        f"({booking.equipment.name}) is {overdue_minutes} min overdue. "
                        f"Notified {admin_notified} admin(s)."
                    )

            if user_notified > 0 or admin_notified > 0:
                logger.info(
                    f"Overdue checks: notified {user_notified} user(s), "
                    f"{admin_notified} admin(s)"
                )

    except Exception as e:
        logger.error(f"Error in check_overdue_returns: {e}", exc_info=True)


async def auto_complete_old_bookings(bot: Bot) -> None:
    """
    Auto-complete active bookings that exceeded end_time by 24+ hours.

    Runs every 60 minutes. Prevents stuck "active" bookings from lingering forever.

    Args:
        bot: Bot instance for sending messages
    """
    try:
        async with async_session_maker() as session:
            bookings = await crud.get_active_bookings(session)

            now = datetime.now(timezone.utc)
            threshold = timedelta(hours=24)

            completed_count = 0

            for booking in bookings:
                if now - booking.end_time >= threshold:
                    await crud.force_complete_booking(session, booking.id)

                    # Notify user
                    try:
                        await bot.send_message(
                            chat_id=booking.user_id,
                            text=(
                                f"ℹ️ <b>Бронь автоматически завершена</b>\n\n"
                                f"Оборудование: {booking.equipment.name}\n"
                                f"Причина: Прошло более 24 часов после окончания брони.\n\n"
                                f"Если оборудование не возвращено, обратитесь к администратору."
                            )
                        )
                    except TelegramAPIError as e:
                        logger.error(
                            f"Failed to notify user {booking.user_id} about auto-completed booking {booking.id}: {e}"
                        )

                    completed_count += 1
                    logger.info(
                        f"Auto-completed booking {booking.id} for user {booking.user_id} "
                        f"(equipment: {booking.equipment.name})"
                    )

            if completed_count > 0:
                logger.info(f"Auto-completed {completed_count} old booking(s)")

    except Exception as e:
        logger.error(f"Error in auto_complete_old_bookings: {e}", exc_info=True)


async def scheduler_heartbeat(bot: Bot) -> None:
    """
    Write heartbeat timestamp to file for health monitoring.

    Runs every 30 minutes. On bot startup, the heartbeat file is checked
    to detect if the scheduler was down.

    Args:
        bot: Bot instance (unused, required by scheduler interface)
    """
    try:
        os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
        logger.debug("Scheduler heartbeat written")
    except Exception as e:
        logger.error(f"Error writing scheduler heartbeat: {e}")
