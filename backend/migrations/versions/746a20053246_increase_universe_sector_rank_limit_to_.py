from alembic import op


# Keep the generated revision and down_revision values here.
revision: str = '746a20053246'
down_revision: Union[str, Sequence[str], None] = 'b87f96b77d5a'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "ck_universe_sector_rank",
        "stock_universe_memberships",
        type_="check",
    )

    op.create_check_constraint(
        "ck_universe_sector_rank",
        "stock_universe_memberships",
        "sector_rank >= 1 AND sector_rank <= 30",
    )


def downgrade():
    op.drop_constraint(
        "ck_universe_sector_rank",
        "stock_universe_memberships",
        type_="check",
    )

    op.create_check_constraint(
        "ck_universe_sector_rank",
        "stock_universe_memberships",
        "sector_rank >= 1 AND sector_rank <= 10",
    )