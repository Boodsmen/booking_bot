"""FSM states for booking flow."""

from aiogram.fsm.state import State, StatesGroup


class BookingStates(StatesGroup):
    """States for booking creation flow."""

    choosing_category = State()
    choosing_equipment = State()
    choosing_date_start = State()
    choosing_time_start = State()
    choosing_date_end = State()
    choosing_time_end = State()
    confirming = State()


class ConfirmStartStates(StatesGroup):
    """States for booking start confirmation (photo upload)."""

    uploading_photos = State()


class CompleteBookingStates(StatesGroup):
    """States for booking completion (photo upload)."""

    uploading_photos = State()


class AddEquipmentStates(StatesGroup):
    """States for adding new equipment (admin)."""

    waiting_category = State()
    waiting_name = State()
    waiting_license_plate = State()
    waiting_photo_required = State()
    waiting_photo = State()


class AddUserStates(StatesGroup):
    """States for adding new user (admin)."""

    waiting_telegram_id = State()
    waiting_full_name = State()
    waiting_phone = State()
    waiting_admin_status = State()
    waiting_categories = State()


class MaintenanceStates(StatesGroup):
    """States for creating maintenance booking (admin)."""

    choosing_category = State()
    choosing_equipment = State()
    choosing_date_start = State()
    choosing_time_start = State()
    choosing_date_end = State()
    choosing_time_end = State()
    entering_reason = State()


class SearchStates(StatesGroup):
    """States for equipment search."""

    entering_query = State()


class ReportStates(StatesGroup):
    """States for flexible report generation."""

    choosing_filter = State()
    choosing_category = State()
    choosing_user = State()
    choosing_period = State()
    entering_start_date = State()
    entering_end_date = State()


class ImportStates(StatesGroup):
    """States for Excel import of equipment."""

    waiting_file = State()
