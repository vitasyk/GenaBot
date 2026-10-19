from datetime import datetime
from enum import Enum, StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    true,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bot.utils.clock import utcnow


class Base(AsyncAttrs, DeclarativeBase):
    pass

from sqlalchemy.dialects.postgresql import ENUM as pgENUM


class UserRole(str, Enum):
    admin = "admin"
    worker = "worker"
    blocked = "blocked"

class GenStatus(str, Enum):
    stopped = "stopped"
    running = "running"
    standby = "standby"

class SessionStatus(StrEnum):  # StrEnum: f"{status}" gives the value, not "SessionStatus.x"
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"
    expired = "expired"

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    sheet_name: Mapped[str] = mapped_column(String, nullable=True)
    role: Mapped[UserRole] = mapped_column(
        pgENUM(UserRole, name="userrole", create_type=False),
        default=UserRole.worker
    )

class Inventory(Base):
    __tablename__ = "inventory"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    fuel_cans: Mapped[int] = mapped_column(Integer, default=0)

class Generator(Base):
    __tablename__ = "generators"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[GenStatus] = mapped_column(
        pgENUM(GenStatus, name="genstatus", create_type=False),
        default=GenStatus.stopped
    )
    current_run_start: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    fuel_level: Mapped[float] = mapped_column(Float, default=0.0)
    tank_capacity: Mapped[float] = mapped_column(Float, default=40.0)
    consumption_rate: Mapped[float] = mapped_column(Float, default=2.0)
    total_hours_run: Mapped[float] = mapped_column(Float, default=0.0)
    last_maintenance: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    fuel_since_antigel: Mapped[float] = mapped_column(Float, default=0.0)
    last_stop_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)  # SOS start-up text (Telegram HTML)
    # SOS attachments: [{"type": "photo" | "document", "file_id": "..."}]; files live in Telegram
    instructions_media: Mapped[list | None] = mapped_column(JSON, nullable=True)

class LogEvent(Base):
    __tablename__ = "logs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String)
    details: Mapped[str] = mapped_column(String, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class ScheduleEntry(Base):
    """Manual schedule entry for power outages"""
    __tablename__ = "schedule_entries"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=False)  # Which date this applies to
    queue: Mapped[str] = mapped_column(String, default="1.1")  # 1.1, 1.2, etc.
    start_hour: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-23
    end_hour: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-23 (exclusive)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)

class RefuelSession(Base):
    __tablename__ = "refuel_sessions"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    start_time: Mapped[datetime] = mapped_column(DateTime) # Estimated outage start
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=True) # Actual completion time
    deadline: Mapped[datetime] = mapped_column(DateTime)  # Expected power restoration (deadline)
    # native_enum=False + length=None keeps the existing plain VARCHAR column: no schema change
    status: Mapped[SessionStatus] = mapped_column(
        SAEnum(SessionStatus, native_enum=False, length=None, validate_strings=True,
               values_callable=lambda e: [m.value for m in e]),
        default=SessionStatus.pending,
    )
    
    # Workers on shift
    worker1_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    worker2_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    worker3_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    
    # Additional workers beyond the first 3 (stored as list of worker IDs)
    # Format: [123456789, 987654321, ...]
    additional_workers: Mapped[list] = mapped_column(JSON, nullable=True, default=list)
    
    # Completion Data
    gen_name: Mapped[str] = mapped_column(String, nullable=True)
    liters: Mapped[float] = mapped_column(Float, nullable=True)
    cans: Mapped[float] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(String, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
