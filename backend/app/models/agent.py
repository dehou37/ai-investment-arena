
import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    competition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    strategy_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        nullable=False,
    )

    competition: Mapped["Competition"] = relationship(
        back_populates="agents",
    )

    portfolio: Mapped["Portfolio"] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "competition_id",
            "name",
            name="uq_agent_competition_name",
        ),
        CheckConstraint(
            "strategy_type IN "
            "('buy_and_hold', 'momentum', 'mean_reversion', "
            "'value', 'risk_managed')",
            name="ck_agent_strategy_type",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'disqualified')",
            name="ck_agent_status",
        ),
    )
