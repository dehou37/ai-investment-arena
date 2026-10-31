
"""allow llm analyst strategy

Revision ID: 98c82ff349d5
Revises: e86b06b8b33d
Create Date: 2026-10-31 22:49:20.796352

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '98c82ff349d5'
down_revision: Union[str, Sequence[str], None] = 'e86b06b8b33d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        'ck_agent_strategy_type',
        'agents',
        type_='check',
    )

    op.create_check_constraint(
        'ck_agent_strategy_type',
        'agents',
        "strategy_type IN "
        "('buy_and_hold', 'momentum', 'mean_reversion', "
        "'value', 'risk_managed', 'llm_analyst')",
    )


def downgrade() -> None:
    op.drop_constraint(
        'ck_agent_strategy_type',
        'agents',
        type_='check',
    )

    op.create_check_constraint(
        'ck_agent_strategy_type',
        'agents',
        "strategy_type IN "
        "('buy_and_hold', 'momentum', 'mean_reversion', "
        "'value', 'risk_managed')",
    )
