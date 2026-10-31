
import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )

    stock_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stocks.id", ondelete="RESTRICT"),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    average_entry_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    portfolio: Mapped["Portfolio"] = relationship(
        back_populates="positions",
    )

    stock: Mapped["Stock"] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "stock_id",
            name="uq_position_portfolio_stock",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_position_quantity_positive",
        ),
        CheckConstraint(
            "average_entry_price > 0",
            name="ck_position_average_price_positive",
        ),
    )
