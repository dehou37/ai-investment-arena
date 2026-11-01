
"""add stock universe snapshot to competitions

Revision ID: 5043dc0bc202
Revises: 91219f6d067f
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5043dc0bc202"
down_revision: Union[str, Sequence[str], None] = "91219f6d067f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FK_NAME = "fk_competitions_universe_snapshot_id"


def upgrade() -> None:
    op.add_column(
        "competitions",
        sa.Column(
            "stock_universe_snapshot_id",
            sa.Uuid(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        FK_NAME,
        "competitions",
        "stock_universe_snapshots",
        ["stock_universe_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        FK_NAME,
        "competitions",
        type_="foreignkey",
    )

    op.drop_column(
        "competitions",
        "stock_universe_snapshot_id",
    )
