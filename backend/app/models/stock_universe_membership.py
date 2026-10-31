
import uuid
from decimal import Decimal

from sqlalchemy import (
    ForeignKey,
    Integer,
    Numeric,
    String,
    CheckConstraint,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class StockUniverseMembership(Base):
    __tablename__ = "stock_universe_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "stock_universe_snapshots.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    stock_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stocks.id", ondelete="RESTRICT"),
        nullable=False,
    )

    sector: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
    )

    industry: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    market_cap: Mapped[Decimal] = mapped_column(
        Numeric(24, 2),
        nullable=False,
    )

    sector_rank: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    snapshot: Mapped["StockUniverseSnapshot"] = relationship(
        back_populates="memberships",
    )

    stock: Mapped["Stock"] = relationship(
        back_populates="universe_memberships",
    )

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "stock_id",
            name="uq_universe_snapshot_stock",
        ),
        UniqueConstraint(
            "snapshot_id",
            "sector",
            "sector_rank",
            name="uq_universe_snapshot_sector_rank",
        ),
        CheckConstraint(
            "sector_rank >= 1 AND sector_rank <= 30",
            name="ck_universe_sector_rank",
        ),
        CheckConstraint(
            "market_cap > 0",
            name="ck_universe_market_cap_positive",
        ),
        Index(
            "ix_universe_membership_snapshot_sector",
            "snapshot_id",
            "sector",
        ),
    )
