
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


class Order(Base):
    __tablename__ = "orders"

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

    side: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    order_type: Mapped[str] = mapped_column(
        String(20),
        default="market",
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    limit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
    )

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    scheduled_execution_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    portfolio: Mapped["Portfolio"] = relationship(
        back_populates="orders",
    )

    stock: Mapped["Stock"] = relationship()

    executions: Mapped[list["Execution"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "side IN ('buy', 'sell')",
            name="ck_order_side",
        ),
        CheckConstraint(
            "order_type IN ('market', 'limit')",
            name="ck_order_type",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_order_quantity_positive",
        ),
        CheckConstraint(
            "status IN "
            "('pending', 'queued', 'partially_filled', "
            "'filled', 'cancelled', 'rejected')",
            name="ck_order_status",
        ),
        CheckConstraint(
            "limit_price IS NULL OR limit_price > 0",
            name="ck_order_limit_price_positive",
        ),
        CheckConstraint(
            "order_type != 'limit' OR limit_price IS NOT NULL",
            name="ck_limit_order_requires_price",
        ),
    )
