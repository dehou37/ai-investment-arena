
from datetime import date

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import (
    Agent,
    Competition,
    StockUniverseSnapshot,
)
from app.services.trading.market_context_service import (
    build_agent_market_context,
)


COMPETITION_ID = "b906cde8-9c33-41f0-aa1c-2ef571ebabde"
SNAPSHOT_ID = "d804bb9b-4810-4038-95e0-2f11a5bb21ed"

AS_OF_DATE = date(2026, 10, 31)


def main():
    with SessionLocal() as db:
        try:
            competition = db.get(Competition, COMPETITION_ID)
            snapshot = db.get(StockUniverseSnapshot, SNAPSHOT_ID)

            if competition is None:
                raise ValueError("Season 2 competition not found.")

            if snapshot is None:
                raise ValueError("Universe snapshot not found.")

            if competition.status != "pending":
                raise ValueError(
                    f"Expected pending competition, "
                    f"got {competition.status}."
                )

            # Temporarily simulate an active competition.
            # These changes are never committed.
            competition.status = "active"
            competition.started_at = snapshot.as_of

            agents = db.scalars(
                select(Agent)
                .where(Agent.competition_id == COMPETITION_ID)
                .order_by(Agent.name)
            ).all()

            if len(agents) != 5:
                raise ValueError(
                    f"Expected 5 agents, found {len(agents)}."
                )

            print(f"Competition: {competition.name}")
            print(f"Temporary as-of date: {AS_OF_DATE}")
            print(f"Agents found: {len(agents)}")
            print()

            with db.no_autoflush:

                for agent in agents:
                    print("=" * 60)
                    print(f"Testing agent: {agent.name}")
                    print(f"Strategy: {agent.strategy_type}")

                    context = build_agent_market_context(
                        db=db,
                        competition_id=COMPETITION_ID,
                        agent_id=agent.id,
                        as_of_date=AS_OF_DATE,
                    )

                    # Extract context.
                    universe_context = context["universe"]
                    stocks = universe_context["stocks"]
                    benchmark = context["benchmark"]
                    portfolio = context["portfolio"]

                    # Universe information.
                    print(
                        f"Universe snapshot: "
                        f"{universe_context['snapshot_id']}"
                    )
                    print(
                        f"Snapshot date: "
                        f"{universe_context['snapshot_as_of']}"
                    )
                    print(
                        f"Universe stocks: "
                        f"{universe_context['stock_count']}"
                    )

                    # Stock data statuses.
                    statuses = {}

                    for stock in stocks:
                        status = stock.get(
                            "data_status",
                            "unknown",
                        )

                        statuses[status] = (
                            statuses.get(status, 0) + 1
                        )

                    print(f"Stock data statuses: {statuses}")

                    # Benchmark information.
                    print(
                        f"Benchmark symbol: "
                        f"{benchmark.get('symbol')}"
                    )
                    print(
                        f"Benchmark latest price: "
                        f"{benchmark.get('latest_price')}"
                    )
                    print(
                        f"Benchmark latest bar date: "
                        f"{benchmark.get('latest_bar_date')}"
                    )
                    print(
                        f"Benchmark data status: "
                        f"{benchmark.get('data_status')}"
                    )

                    print(
                        f"Benchmark indicators: "
                        f"{benchmark.get('indicators')}"
                    )

                    # Portfolio information.
                    print(
                        f"Portfolio cash: "
                        f"{portfolio.get('cash_balance')}"
                    )
                    print(
                        f"Portfolio holdings: "
                        f"{len(portfolio.get('holdings', []))}"
                    )

                    # Assertions.
                    if len(stocks) != 30:
                        raise AssertionError(
                            f"{agent.name}: expected 30 stocks, "
                            f"received {len(stocks)}."
                        )

                    if universe_context["stock_count"] != 30:
                        raise AssertionError(
                            f"{agent.name}: expected stock_count 30, "
                            f"received "
                            f"{universe_context['stock_count']}."
                        )

                    if not benchmark:
                        raise AssertionError(
                            f"{agent.name}: benchmark context is empty."
                        )

                    if benchmark.get("symbol") != "SPY":
                        raise AssertionError(
                            f"{agent.name}: expected SPY benchmark."
                        )

                    if benchmark.get("latest_price") is None:
                        raise AssertionError(
                            f"{agent.name}: SPY price is missing."
                        )

                    if portfolio.get("cash_balance") is None:
                        raise AssertionError(
                            f"{agent.name}: portfolio cash is missing."
                        )

                    print(f"PASS: {agent.name}")
                    print()

            print("=" * 60)
            print("All five agent market-context tests passed.")

        finally:
            db.rollback()

    print("Database transaction rolled back.")
    print("Season 2 remains unchanged.")


if __name__ == "__main__":
    main()
