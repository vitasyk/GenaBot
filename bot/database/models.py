from datetime import datetime
from enum import Enum
from sqlalchemy import BigInteger, Boolean, String, DateTime, ForeignKey, Integer, Float, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncAttrs

from bot.utils.clock import now_kyiv

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

class SessionStatus(str, Enum):
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
    # Inactive generators are hidden from start/stop/refuel menus but keep their history
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    instructions: Mapped[str] = mapped_column(String, nullable=True)  # SOS start-up text

class LogEvent(Base):
    __tablename__ = "logs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String)
    details: Mapped[str] = mapped_column(String, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=now_kyiv)

class RefuelSession(Base):
    __tablename__ = "refuel_sessions"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    start_time: Mapped[datetime] = mapped_column(DateTime) # Estimated outage start
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=True) # Actual completion time
    deadline: Mapped[datetime] = mapped_column(DateTime)  # Expected power restoration (deadline)
    status: Mapped[str] = mapped_column(String, default=SessionStatus.pending.value)
    
    # Workers on shift
    worker1_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    worker2_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    
    # Completion Data
    gen_name: Mapped[str] = mapped_column(String, nullable=True)
    liters: Mapped[float] = mapped_column(Float, nullable=True)
    cans: Mapped[float] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(String, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kyiv)
    completed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
