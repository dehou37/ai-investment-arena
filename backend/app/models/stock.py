
import uuid

from sqlalchemy import String, Boolean
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

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    bars: Mapped[list["StockBar"]] = relationship(
        back_populates="stock",
        cascade="all, delete-orphan",
    )
