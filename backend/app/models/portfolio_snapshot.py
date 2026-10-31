import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )

    snapshot_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    cash_balance: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    market_value: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )

    portfolio_equity: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )

    realised_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    unrealised_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )

    total_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )

    total_return_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )

    total_fees: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    total_slippage: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    benchmark_close: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    valuation_complete: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    portfolio: Mapped["Portfolio"] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "snapshot_date",
            name="uq_portfolio_snapshot_date",
        ),
        CheckConstraint(
            "cash_balance >= 0",
            name="ck_snapshot_cash_nonnegative",
        ),
        CheckConstraint(
            "total_fees >= 0",
            name="ck_snapshot_fees_nonnegative",
        ),
        CheckConstraint(
            "total_slippage >= 0",
            name="ck_snapshot_slippage_nonnegative",
        ),
    )