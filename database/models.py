"""SQLAlchemy models: User, Equipment, Booking, Category, UserCategory."""

from datetime import datetime
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Category(Base):
    """Category model - static equipment categories."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # Relationships
    equipment: Mapped[list["Equipment"]] = relationship(back_populates="category_rel")
    user_categories: Mapped[list["UserCategory"]] = relationship(back_populates="category")

    def __repr__(self) -> str:
        return f"<Category {self.id}: {self.name}>"


class UserCategory(Base):
    """User-Category M2M - controls which categories a user can access."""

    __tablename__ = "user_categories"
    __table_args__ = (
        UniqueConstraint("user_id", "category_id", name="uq_user_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"), nullable=False)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="user_categories")
    category: Mapped["Category"] = relationship(back_populates="user_categories")

    def __repr__(self) -> str:
        return f"<UserCategory user={self.user_id} cat={self.category_id}>"


class User(Base):
    """User model - employees who can book equipment."""

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    bookings: Mapped[list["Booking"]] = relationship(back_populates="user")
    user_categories: Mapped[list["UserCategory"]] = relationship(back_populates="user")

    def __repr__(self) -> str:
        return f"<User {self.telegram_id}: {self.full_name}>"


class Equipment(Base):
    """Equipment model - items available for booking."""

    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"), nullable=True)
    license_plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    photo: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_photo: Mapped[bool] = mapped_column(Boolean, default=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    bookings: Mapped[list["Booking"]] = relationship(back_populates="equipment")
    category_rel: Mapped["Category | None"] = relationship(back_populates="equipment")

    def __repr__(self) -> str:
        return f"<Equipment {self.id}: {self.name}>"


class Booking(Base):
    """Booking model - equipment reservations."""

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign keys
    equipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equipment.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False
    )

    # Time range
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Status: pending, active, completed, cancelled, expired, maintenance
    status: Mapped[str] = mapped_column(String(20), default="pending")

    # Timestamps
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Photos (stored as file paths or Telegram file_ids)
    photos_start: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True, default=list
    )
    photos_end: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True, default=list
    )

    # Flags
    is_overdue: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    overdue_notified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Maintenance
    maintenance_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="bookings")
    equipment: Mapped["Equipment"] = relationship(back_populates="bookings")

    def __repr__(self) -> str:
        return f"<Booking {self.id}: {self.status}>"
