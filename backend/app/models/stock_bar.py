
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class StockBar(Base):
    __tablename__ = "stock_bars"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    stock_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"),
        nullable=False,
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    timeframe: Mapped[str] = mapped_column(
        String(20),
        default="1Day",
        nullable=False,
    )

    open: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    high: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    low: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    close: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    volume: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    trade_count: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    vwap: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )

    provider: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    feed: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    adjustment: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    stock: Mapped["Stock"] = relationship(
        back_populates="bars",
    )

    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "timeframe",
            "timestamp",
            "provider",
            "feed",
            "adjustment",
            name="uq_stock_bar_source",
        ),
        Index(
            "ix_stock_bars_stock_timestamp",
            "stock_id",
            "timestamp",
        ),
    )
