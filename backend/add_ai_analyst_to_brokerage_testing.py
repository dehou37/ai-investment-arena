from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Agent, Competition, Portfolio


COMPETITION_ID = UUID("20c32a1d-9a39-4ee6-8060-74c439ba28fd")

AGENT_NAME = "AI Analyst"


def main():
    with SessionLocal() as db:
        competition = db.scalar(
            select(Competition)
            .where(Competition.id == COMPETITION_ID)
            .with_for_update()
        )

        if competition is None:
            raise RuntimeError("Brokerage Testing competition not found.")

        if competition.status != "active":
            raise RuntimeError(
                f"Competition must be active. Current status: {competition.status}"
            )

        agent = db.scalar(
            select(Agent).where(
                Agent.competition_id == COMPETITION_ID,
                Agent.name == AGENT_NAME,
            )
        )

        if agent is None:
            agent = Agent(
                competition_id=COMPETITION_ID,
                name=AGENT_NAME,
                strategy_type="llm_analyst",
                description=(
                    "Uses a local large language model to analyse market "
                    "conditions and generate independent trading decisions."
                ),
                config={},
                status="active",
            )

            db.add(agent)
            db.flush()

            portfolio = Portfolio(
                agent_id=agent.id,
                cash_balance=competition.initial_cash,
            )

            db.add(portfolio)
            db.commit()

            print("AI Analyst created successfully.")

        else:
            portfolio = db.scalar(
                select(Portfolio).where(Portfolio.agent_id == agent.id)
            )

            if portfolio is None:
                portfolio = Portfolio(
                    agent_id=agent.id,
                    cash_balance=competition.initial_cash,
                )
                db.add(portfolio)
                db.commit()
                print("AI Analyst already existed; portfolio created.")
            else:
                print("AI Analyst and portfolio already exist.")

        print(f"Agent ID: {agent.id}")
        print(f"Strategy: {agent.strategy_type}")
        print(f"Status: {agent.status}")
        print(f"Portfolio cash: ${portfolio.cash_balance:,.2f}")


if __name__ == "__main__":
    main()