"""add attempt count to agent daily runs

Revision ID: a64b1e2c9f10
Revises: 9719154b7083
Create Date: 2026-11-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a64b1e2c9f10"
down_revision: Union[str, Sequence[str], None] = "9719154b7083"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_daily_runs",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_agent_daily_run_attempt_count_positive",
        "agent_daily_runs",
        "attempt_count >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_agent_daily_run_attempt_count_positive",
        "agent_daily_runs",
        type_="check",
    )
    op.drop_column("agent_daily_runs", "attempt_count")
