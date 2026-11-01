
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

from sqlalchemy import UUID as SQLAlchemyUUID
class Competition(Base):


    __tablename__ = "competitions"

    @property
    def benchmark_symbol(self) -> str:
        return self.benchmark_stock.symbol

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
    )

    initial_cash: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        default=Decimal("10000.00"),
        nullable=False,
    )

    duration_days: Mapped[int] = mapped_column(
        Integer,
        default=90,
        nullable=False,
    )

    benchmark_stock_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stocks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stock_universe_snapshot: Mapped["StockUniverseSnapshot | None"] = relationship()
    stock_universe_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "stock_universe_snapshots.id",
            name="fk_competitions_universe_snapshot_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    agents: Mapped[list["Agent"]] = relationship(
        back_populates="competition",
        cascade="all, delete-orphan",
    )

    benchmark_stock: Mapped["Stock"] = relationship()

    __table_args__ = (
        CheckConstraint(
            "initial_cash > 0",
            name="ck_competition_initial_cash_positive",
        ),
        CheckConstraint(
            "duration_days > 0",
            name="ck_competition_duration_positive",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'completed', 'cancelled')",
            name="ck_competition_status",
        ),
    )
