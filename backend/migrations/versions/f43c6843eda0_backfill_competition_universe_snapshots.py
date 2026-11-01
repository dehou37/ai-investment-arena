
"""backfill competition universe snapshots

Revision ID: f43c6843eda0
Revises: 5043dc0bc202
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f43c6843eda0"
down_revision: Union[str, Sequence[str], None] = "5043dc0bc202"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    # Identify started competitions that cannot be assigned a snapshot.
    missing_snapshots = connection.execute(
        sa.text("""
            SELECT COUNT(*)
            FROM competitions c
            WHERE c.started_at IS NOT NULL
              AND c.stock_universe_snapshot_id IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM stock_universe_snapshots s
                  WHERE s.status = 'completed'
                    AND s.as_of <= c.started_at
              )
        """)
    ).scalar_one()

    if missing_snapshots:
        raise RuntimeError(
            f"Cannot backfill competition snapshots: "
            f"{missing_snapshots} started competition(s) "
            "have no matching completed snapshot."
        )

    # Assign the latest eligible snapshot to every started
    # competition that does not already have an assignment.
    connection.execute(
        sa.text("""
            UPDATE competitions c
            SET stock_universe_snapshot_id = (
                SELECT s.id
                FROM stock_universe_snapshots s
                WHERE s.status = 'completed'
                  AND s.as_of <= c.started_at
                ORDER BY s.as_of DESC
                LIMIT 1
            )
            WHERE c.started_at IS NOT NULL
              AND c.stock_universe_snapshot_id IS NULL
        """)
    )


def downgrade() -> None:
    # Intentionally retain these historical data assignments.
    # Clearing them could remove snapshot assignments belonging
    # to competitions started after this migration.
    pass
