import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AgentDailyRun(Base):
    __tablename__ = "agent_daily_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    competition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )

    trading_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="running",
        nullable=False,
    )

    decision: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    orders_created: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    error_message: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    competition: Mapped["Competition"] = relationship()

    agent: Mapped["Agent"] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "competition_id",
            "agent_id",
            "trading_date",
            name="uq_agent_daily_run_session",
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_agent_daily_run_status",
        ),
        CheckConstraint(
            "orders_created >= 0",
            name="ck_agent_daily_run_orders_nonnegative",
        ),
        CheckConstraint(
            "attempt_count >= 1",
            name="ck_agent_daily_run_attempt_count_positive",
        ),
    )