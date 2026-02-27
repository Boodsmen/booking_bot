"""Задачи планировщика: напоминания, истечение броней, просрочки, автозавершение, heartbeat."""

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
    Истекает ожидающие брони, если пользователь не подтвердил начало.

    Запускается каждую минуту. Истекает pending-брони, у которых:
    start_time + confirmation_timeout_minutes < now
    """
    try:
        async with async_session_maker() as session:
            now = datetime.now(timezone.utc)
            timeout = timedelta(minutes=settings.confirmation_timeout_minutes)
            bookings = await crud.get_bookings_to_expire(session, now, timeout)

            expired_count = 0

            for booking in bookings:
                await crud.expire_booking(session, booking.id)

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
    Отправляет напоминания подтвердить начало брони.

    Запускается каждую минуту. Отправляет напоминание для pending-броней,
    у которых start_time в пределах 5 минут (прошедших или будущих).
    """
    try:
        async with async_session_maker() as session:
            now = datetime.now(timezone.utc)
            reminder_window = timedelta(minutes=5)
            bookings = await crud.get_bookings_needing_reminder(session, now, reminder_window)

            sent_count = 0

            for booking in bookings:
                time_until_start = booking.start_time - now
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
    Отправляет напоминания вернуть оборудование до окончания брони.

    Запускается каждые 5 минут. Напоминает об активных бронях,
    у которых end_time наступит в течение reminder_minutes_before (по умолчанию 15 мин).
    """
    try:
        async with async_session_maker() as session:
            now = datetime.now(timezone.utc)
            reminder_before = timedelta(minutes=settings.reminder_minutes_before)
            bookings = await crud.get_active_bookings_ending_soon(session, now, reminder_before)

            sent_count = 0

            for booking in bookings:
                time_until_end = booking.end_time - now
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
    Проверяет просроченные возвраты и уведомляет пользователей и администраторов.

    Запускается каждые 5 минут. Для активных броней с истёкшим end_time:
    - Сразу уведомляет пользователя (один раз)
    - Если просрочка > overdue_alert_minutes (по умолчанию 30 мин) — уведомляет администраторов
    """
    try:
        async with async_session_maker() as session:
            now = datetime.now(timezone.utc)
            admin_alert_threshold = timedelta(minutes=settings.overdue_alert_minutes)
            bookings = await crud.get_overdue_bookings(session, now)

            user_notified = 0
            admin_notified = 0

            for booking in bookings:

                overdue_duration = now - booking.end_time
                overdue_minutes = int(overdue_duration.total_seconds() / 60)

                # Уведомляем пользователя один раз
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

                # Если критическая просрочка и флаг ещё не выставлен — уведомляем администраторов
                if overdue_duration >= admin_alert_threshold and not booking.is_overdue:
                    await crud.set_booking_overdue(session, booking.id)

                    admins = await crud.get_all_admins(session)

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
    Автоматически завершает активные брони, у которых end_time прошёл 24+ часа назад.

    Запускается каждые 60 минут. Предотвращает зависание броней в статусе «active».
    """
    try:
        async with async_session_maker() as session:
            now = datetime.now(timezone.utc)
            threshold = timedelta(hours=24)
            bookings = await crud.get_stale_active_bookings(session, now, threshold)

            completed_count = 0

            for booking in bookings:
                await crud.force_complete_booking(session, booking.id)

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
    Записывает временную метку в файл для мониторинга работоспособности.

    Запускается каждые 30 минут. При старте бота файл проверяется
    для обнаружения простоя планировщика.
    """
    try:
        os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
        logger.debug("Scheduler heartbeat written")
    except Exception as e:
        logger.error(f"Error writing scheduler heartbeat: {e}")
