
import uuid

from sqlalchemy import (
    String,
    Boolean,
    Numeric,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    symbol: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    exchange: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    asset_class: Mapped[str] = mapped_column(
        String(30),
        default="us_equity",
        nullable=False,
    )

    asset_type: Mapped[str] = mapped_column(
        String(20),
        default="stock",
        server_default="stock",
        nullable=False,
    )

    sector: Mapped[str | None] = mapped_column(
        String(60),
        nullable=True,
    )

    industry: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    market_cap: Mapped[int | None] = mapped_column(
        Numeric(24, 2),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    bars: Mapped[list["StockBar"]] = relationship(
        back_populates="stock",
        cascade="all, delete-orphan",
    )

    universe_memberships: Mapped[
        list["StockUniverseMembership"]
    ] = relationship(
        back_populates="stock",
    )

    __table_args__ = (
        CheckConstraint(
            "asset_type IN ('stock', 'etf')",
            name="ck_stock_asset_type",
        ),
        Index(
            "ix_stocks_sector_market_cap",
            "sector",
            "market_cap",
        ),
    )
