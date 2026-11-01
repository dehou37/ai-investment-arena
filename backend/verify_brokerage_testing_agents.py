from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Agent, Competition, Portfolio, Position, Stock


COMPETITION_ID = UUID("20c32a1d-9a39-4ee6-8060-74c439ba28fd")


def main():
    with SessionLocal() as db:
        competition = db.get(Competition, COMPETITION_ID)

        if competition is None:
            raise RuntimeError("Competition not found.")

        agents = db.scalars(
            select(Agent)
            .where(Agent.competition_id == COMPETITION_ID)
            .order_by(Agent.name)
        ).all()

        print(f"\nCompetition: {competition.name}")
        print(f"Status: {competition.status}")
        print("\nAgents:")

        for agent in agents:
            portfolio = db.scalar(
                select(Portfolio).where(Portfolio.agent_id == agent.id)
            )

            cash = portfolio.cash_balance if portfolio else Decimal("0")

            print(
                f"- {agent.name} | {agent.strategy_type} | "
                f"{agent.status} | Cash: ${cash:,.2f}"
            )

        active_count = sum(1 for agent in agents if agent.status == "active")
        print(f"\nTotal agents: {len(agents)}")
        print(f"Active agents: {active_count}")

        print("\nExisting positions:")

        positions = db.execute(
            select(Agent.name, Stock.symbol, Position.quantity)
            .join(Portfolio, Portfolio.agent_id == Agent.id)
            .join(Position, Position.portfolio_id == Portfolio.id)
            .join(Stock, Stock.id == Position.stock_id)
            .where(Agent.competition_id == COMPETITION_ID)
        ).all()

        for name, symbol, quantity in positions:
            print(f"- {name}: {quantity} share(s) of {symbol}")


if __name__ == "__main__":
    from decimal import Decimal
    main()