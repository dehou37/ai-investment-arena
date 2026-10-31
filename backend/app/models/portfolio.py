
import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    cash_balance: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )

    agent: Mapped["Agent"] = relationship(
        back_populates="portfolio",
    )

    positions: Mapped[list["Position"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )

    orders: Mapped[list["Order"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )
