from decimal import Decimal
from sqlalchemy import text

from app.core.database import engine


COMPETITION_ID = "20c32a1d-9a39-4ee6-8060-74c439ba28fd"
STARTING_CASH = Decimal("10000.00")


def main():
    with engine.begin() as conn:
        # Find Warren in the Brokerage Testing competition.
        agent_id = conn.execute(
            text("""
                SELECT id
                FROM agents
                WHERE competition_id = :competition_id
                  AND name = 'Warren'
            """),
            {"competition_id": COMPETITION_ID},
        ).scalar_one_or_none()

        if agent_id is None:
            raise RuntimeError("Warren was not found.")

        # Find Warren's portfolio.
        portfolio_id = conn.execute(
            text("""
                SELECT id
                FROM portfolios
                WHERE agent_id = :agent_id
            """),
            {"agent_id": agent_id},
        ).scalar_one_or_none()

        if portfolio_id is None:
            raise RuntimeError("Warren's portfolio was not found.")

        # Delete executions belonging to Warren's orders.
        executions_deleted = conn.execute(
            text("""
                DELETE FROM executions
                WHERE order_id IN (
                    SELECT id
                    FROM orders
                    WHERE portfolio_id = :portfolio_id
                )
            """),
            {"portfolio_id": portfolio_id},
        ).rowcount

        # Delete Warren's orders and positions.
        orders_deleted = conn.execute(
            text("""
                DELETE FROM orders
                WHERE portfolio_id = :portfolio_id
            """),
            {"portfolio_id": portfolio_id},
        ).rowcount

        positions_deleted = conn.execute(
            text("""
                DELETE FROM positions
                WHERE portfolio_id = :portfolio_id
            """),
            {"portfolio_id": portfolio_id},
        ).rowcount

        # Delete Warren's historical portfolio snapshots.
        snapshots_deleted = conn.execute(
            text("""
                DELETE FROM portfolio_snapshots
                WHERE portfolio_id = :portfolio_id
            """),
            {"portfolio_id": portfolio_id},
        ).rowcount

        # Delete Warren's historical daily-run records.
        daily_runs_deleted = conn.execute(
            text("""
                DELETE FROM agent_daily_runs
                WHERE agent_id = :agent_id
            """),
            {"agent_id": agent_id},
        ).rowcount

        # Restore the original starting cash.
        conn.execute(
            text("""
                UPDATE portfolios
                SET cash_balance = :starting_cash
                WHERE id = :portfolio_id
            """),
            {
                "starting_cash": STARTING_CASH,
                "portfolio_id": portfolio_id,
            },
        )

        # Verify Warren remains active.
        verification = conn.execute(
            text("""
                SELECT
                    a.name,
                    a.strategy_type,
                    a.status,
                    p.cash_balance
                FROM agents a
                JOIN portfolios p ON p.agent_id = a.id
                WHERE a.id = :agent_id
            """),
            {"agent_id": agent_id},
        ).mappings().one()

        if verification["status"] != "active":
            raise RuntimeError("Warren is unexpectedly not active.")

        if Decimal(verification["cash_balance"]) != STARTING_CASH:
            raise RuntimeError("Warren's cash balance was not reset correctly.")

    print("Warren's portfolio was successfully reset.")
    print(f"Agent: {verification['name']}")
    print(f"Strategy: {verification['strategy_type']}")
    print(f"Status: {verification['status']}")
    print(f"Cash: ${verification['cash_balance']:,.2f}")
    print(f"Executions deleted: {executions_deleted}")
    print(f"Orders deleted: {orders_deleted}")
    print(f"Positions deleted: {positions_deleted}")
    print(f"Snapshots deleted: {snapshots_deleted}")
    print(f"Daily runs deleted: {daily_runs_deleted}")


if __name__ == "__main__":
    main()