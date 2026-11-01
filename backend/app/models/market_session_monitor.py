
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MarketSessionMonitor(Base):
    __tablename__ = "market_session_monitors"

    __table_args__ = (
        CheckConstraint(
            "status IN ('monitoring', 'completed', 'missed')",
            name="ck_market_session_monitor_status",
        ),
    )

    id: Mapped[uuid4] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    session_date: Mapped[datetime.date] = mapped_column(
        Date,
        unique=True,
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="monitoring",
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    missed_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
