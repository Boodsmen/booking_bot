"""Main bot entry point."""

import asyncio
import os
import subprocess
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database.db import init_db, close_db
from middleware.auth import AuthMiddleware
from handlers import start, booking, user, admin
from scheduler import tasks
from utils.logger import logger


# Global scheduler instance
scheduler = AsyncIOScheduler()


async def on_startup(bot: Bot) -> None:
    """Startup actions."""
    logger.info("Bot starting...")

    # Run alembic migrations before anything else
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            logger.info("Alembic migrations applied successfully")
        else:
            logger.error(f"Alembic migration failed: {result.stderr}")
    except Exception as e:
        logger.error(f"Failed to run alembic migrations: {e}")

    # Initialize database
    await init_db()

    # Create default admin if specified in config
    if settings.default_admin_id:
        from database.db import async_session_maker
        from database import crud
        async with async_session_maker() as session:
            existing_user = await crud.get_user(session, settings.default_admin_id)
            if not existing_user:
                await crud.create_user(
                    session,
                    telegram_id=settings.default_admin_id,
                    full_name="Admin",
                    is_admin=True
                )
                logger.info(f"Created default admin with ID {settings.default_admin_id}")
            else:
                # Update to admin if not already
                if not existing_user.is_admin:
                    from database.models import User
                    existing_user.is_admin = True
                    await session.commit()
                    logger.info(f"Upgraded user {settings.default_admin_id} to admin")
                else:
                    logger.info(f"Admin {settings.default_admin_id} already exists")

    # Setup scheduler tasks
    logger.info("Setting up scheduler...")

    # Task 1: Check booking confirmations (every 1 minute)
    scheduler.add_job(
        tasks.check_booking_confirmations,
        trigger='interval',
        minutes=1,
        args=[bot],
        id='check_confirmations',
        replace_existing=True
    )

    # Task 2: Send confirmation reminders (every 1 minute)
    scheduler.add_job(
        tasks.send_confirmation_reminders,
        trigger='interval',
        minutes=1,
        args=[bot],
        id='send_confirmation_reminders',
        replace_existing=True
    )

    # Task 3: Send end reminders (every 5 minutes)
    scheduler.add_job(
        tasks.send_end_reminders,
        trigger='interval',
        minutes=5,
        args=[bot],
        id='send_end_reminders',
        replace_existing=True
    )

    # Task 4: Check overdue returns (every 5 minutes)
    scheduler.add_job(
        tasks.check_overdue_returns,
        trigger='interval',
        minutes=5,
        args=[bot],
        id='check_overdue_returns',
        replace_existing=True
    )

    # Task 5: Auto-complete stuck bookings (every 60 minutes)
    scheduler.add_job(
        tasks.auto_complete_old_bookings,
        trigger='interval',
        minutes=60,
        args=[bot],
        id='auto_complete_old_bookings',
        replace_existing=True
    )

    # Task 6: Scheduler heartbeat (every 30 minutes)
    scheduler.add_job(
        tasks.scheduler_heartbeat,
        trigger='interval',
        minutes=30,
        args=[bot],
        id='scheduler_heartbeat',
        replace_existing=True
    )

    # Check heartbeat file for stale scheduler
    heartbeat_file = tasks.HEARTBEAT_FILE
    if os.path.exists(heartbeat_file):
        try:
            with open(heartbeat_file, "r") as f:
                last_beat = datetime.fromisoformat(f.read().strip())
            if datetime.now(timezone.utc) - last_beat > timedelta(minutes=60):
                logger.warning(
                    f"Scheduler was stale! Last heartbeat: {last_beat.isoformat()}. "
                    f"Possible scheduler outage detected."
                )
        except Exception as e:
            logger.error(f"Error reading heartbeat file: {e}")

    # Start scheduler
    scheduler.start()
    logger.info("Scheduler started with 6 tasks")

    # Get bot info
    bot_info = await bot.get_me()
    logger.info(f"Bot started: @{bot_info.username}")


async def on_shutdown(bot: Bot) -> None:
    """Shutdown actions."""
    logger.info("Bot shutting down...")

    # Shutdown scheduler
    scheduler.shutdown(wait=True)
    logger.info("Scheduler stopped")

    # Close database connections
    await close_db()

    logger.info("Bot stopped")


async def main() -> None:
    """Main function to run the bot."""
    # Create bot instance
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Create dispatcher
    dp = Dispatcher()

    # Register startup/shutdown handlers
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Register middlewares
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    # Register routers
    dp.include_router(start.router)
    dp.include_router(booking.router)
    dp.include_router(user.router)
    dp.include_router(admin.router)

    # Start polling
    logger.info("Starting polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
