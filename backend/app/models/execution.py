
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    execution_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    fees: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        default=Decimal("0"),
        nullable=False,
    )

    slippage: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        default=Decimal("0"),
        nullable=False,
    )

    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    order: Mapped["Order"] = relationship(
        back_populates="executions",
    )

    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="ck_execution_quantity_positive",
        ),
        CheckConstraint(
            "execution_price > 0",
            name="ck_execution_price_positive",
        ),
        CheckConstraint(
            "fees >= 0",
            name="ck_execution_fees_nonnegative",
        ),
        CheckConstraint(
            "slippage >= 0",
            name="ck_execution_slippage_nonnegative",
        ),
        UniqueConstraint(
            "order_id",
            name="uq_execution_order_id",
        ),
    )
