
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class StockUniverseSnapshot(Base):
    __tablename__ = "stock_universe_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="completed",
        nullable=False,
    )

    as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    total_members: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    memberships: Mapped[
        list["StockUniverseMembership"]
    ] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'failed')",
            name="ck_universe_snapshot_status",
        ),
        CheckConstraint(
            "total_members >= 0",
            name="ck_universe_snapshot_members_nonnegative",
        ),
    )
