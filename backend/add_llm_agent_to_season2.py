
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Agent, Competition, Portfolio


SEASON_2_ID = UUID("b906cde8-9c33-41f0-aa1c-2ef571ebabde")


def add_llm_agent():
    db = SessionLocal()

    try:
        # Lock the competition row while performing this operation.
        competition = db.scalar(
            select(Competition)
            .where(Competition.id == SEASON_2_ID)
            .with_for_update()
        )

        if competition is None:
            raise ValueError("Season 2 was not found.")

        if competition.status != "pending":
            raise ValueError(
                f"Season 2 must be pending. Current status: "
                f"{competition.status}"
            )

        # Check whether AI Analyst already exists.
        existing_agent = db.scalar(
            select(Agent).where(
                Agent.competition_id == SEASON_2_ID,
                Agent.name == "AI Analyst",
            )
        )

        if existing_agent is not None:
            if existing_agent.strategy_type != "llm_analyst":
                raise ValueError(
                    "An AI Analyst agent already exists with an "
                    "unexpected strategy type."
                )

            if existing_agent.portfolio is None:
                raise ValueError(
                    "AI Analyst exists but has no portfolio. "
                    "Manual investigation is required."
                )

            print("AI Analyst already exists.")
            print(f"Agent ID: {existing_agent.id}")
            print(f"Portfolio ID: {existing_agent.portfolio.id}")
            return

        # Confirm the expected original five agents are present.
        existing_agents = db.scalars(
            select(Agent).where(
                Agent.competition_id == SEASON_2_ID
            )
        ).all()

        if len(existing_agents) != 5:
            raise ValueError(
                f"Expected 5 existing agents, found "
                f"{len(existing_agents)}. Stopping to avoid "
                "unexpected database changes."
            )

        # Create AI Analyst.
        agent = Agent(
            competition_id=competition.id,
            name="AI Analyst",
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

        # Create its virtual portfolio using competition starting capital.
        portfolio = Portfolio(
            agent_id=agent.id,
            cash_balance=competition.initial_cash,
        )

        db.add(portfolio)
        db.commit()

        print("SUCCESS: AI Analyst added to Season 2.")
        print(f"Agent ID: {agent.id}")
        print(f"Portfolio ID: {portfolio.id}")
        print(f"Starting cash: ${competition.initial_cash:,.2f}")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    add_llm_agent()
