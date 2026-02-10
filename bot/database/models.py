from datetime import datetime
from enum import Enum
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, Integer, Float, Date, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncAttrs

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
    fuel_since_antigel: Mapped[float] = mapped_column(Float, default=0.0)
    last_stop_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

class LogEvent(Base):
    __tablename__ = "logs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String)
    details: Mapped[str] = mapped_column(String, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Shift(Base):
    __tablename__ = "shifts"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    shift_date: Mapped[datetime] = mapped_column(Date)
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)

class ScheduleEntry(Base):
    """Manual schedule entry for power outages"""
    __tablename__ = "schedule_entries"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=False)  # Which date this applies to
    queue: Mapped[str] = mapped_column(String, default="1.1")  # 1.1, 1.2, etc.
    start_hour: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-23
    end_hour: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-23 (exclusive)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)

class WorkerShift(Base):
    __tablename__ = "worker_shifts"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[datetime] = mapped_column(Date)
    shift_number: Mapped[int] = mapped_column(Integer)  # 1 or 2
    worker1_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    worker2_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    worker3_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    start_time: Mapped[str] = mapped_column(String)  # "08:00"
    end_time: Mapped[str] = mapped_column(String)    # "20:00"
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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
    worker3_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    
    # Additional workers beyond the first 3 (stored as list of worker IDs)
    # Format: [123456789, 987654321, ...]
    additional_workers: Mapped[list] = mapped_column(JSON, nullable=True, default=list)
    
    # Completion Data
    gen_name: Mapped[str] = mapped_column(String, nullable=True)
    liters: Mapped[float] = mapped_column(Float, nullable=True)
    cans: Mapped[float] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(String, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
