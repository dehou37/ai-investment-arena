from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import (
    Agent,
    AgentDailyRun,
    Competition,
    MarketSessionMonitor,
)
from app.services.llm.ollama_client import OllamaClient
from app.services.trading.decision_service import DecisionOrchestrator


COMPETITION_ID = UUID(
    "20c32a1d-9a39-4ee6-8060-74c439ba28fd"
)

AI_ANALYST_ID = UUID(
    "b47f437b-b6a0-4158-b46a-d1d11680b4ae"
)

TRADING_DATE = date(2026, 11, 2)


def main():
    client = OllamaClient()
    orchestrator = DecisionOrchestrator(
        ollama_client=client
    )

    try:
        with SessionLocal() as db:
            # Verify the competition.
            competition = db.scalar(
                select(Competition).where(
                    Competition.id == COMPETITION_ID
                )
            )

            if competition is None:
                raise RuntimeError("Competition not found.")

            if competition.status != "active":
                raise RuntimeError(
                    f"Competition is not active: {competition.status}"
                )

            # Verify the intended agent belongs to this competition.
            agent = db.scalar(
                select(Agent).where(
                    Agent.id == AI_ANALYST_ID,
                    Agent.competition_id == COMPETITION_ID,
                )
            )

            if agent is None:
                raise RuntimeError(
                    "AI Analyst does not belong to this competition."
                )

            # Verify that this session was genuinely marked missed.
            monitor = db.scalar(
                select(MarketSessionMonitor).where(
                    MarketSessionMonitor.session_date == TRADING_DATE
                )
            )

            if monitor is None or monitor.status != "missed":
                raise RuntimeError(
                    "Safety check failed: the 2 November market "
                    "session is not marked as missed."
                )

            # Lock ONLY the existing AI Analyst daily-run record.
            daily_run = db.scalar(
                select(AgentDailyRun)
                .where(
                    AgentDailyRun.competition_id == COMPETITION_ID,
                    AgentDailyRun.agent_id == AI_ANALYST_ID,
                    AgentDailyRun.trading_date == TRADING_DATE,
                )
                .with_for_update()
            )

            if daily_run is None:
                raise RuntimeError(
                    "The existing AI Analyst daily-run record "
                    "was not found."
                )

            # Strict safeguards: abort if anything has changed.
            if daily_run.status != "failed":
                raise RuntimeError(
                    f"Expected failed status, found: {daily_run.status}"
                )

            if daily_run.decision is not None:
                raise RuntimeError(
                    "A decision already exists. Refusing to overwrite it."
                )

            if daily_run.orders_created != 0:
                raise RuntimeError(
                    "The run already records orders. Refusing recovery."
                )

            print("Pre-recovery checks passed.")
            print(f"Agent: {agent.name}")
            print(f"Trading date: {TRADING_DATE}")
            print(f"Monitor status: {monitor.status}")
            print("Generating decision without submitting orders...")

            # IMPORTANT: This generates and validates a decision only.
            # It does not call generate_and_submit_agent_orders().
            decision = orchestrator.generate_agent_decision(
                db=db,
                competition_id=COMPETITION_ID,
                agent_id=AI_ANALYST_ID,
                as_of_date=TRADING_DATE,
            )

            if decision.as_of_date != TRADING_DATE:
                raise RuntimeError(
                    "Generated decision has an unexpected trading date."
                )

            symbols = [
                item.symbol for item in decision.decisions
            ]

            if len(symbols) != len(set(symbols)):
                raise RuntimeError(
                    "Generated decision contains duplicate symbols."
                )

            # Update the existing failed record only.
            daily_run.decision = decision.model_dump(mode="json")
            daily_run.orders_created = 0
            daily_run.status = "succeeded"
            daily_run.error_message = None
            daily_run.completed_at = datetime.now(timezone.utc)

            db.commit()

            print("\nRECOVERY SUCCEEDED")
            print(f"Agent: {agent.name}")
            print(f"Trading date: {TRADING_DATE}")
            print(f"Decision count: {len(decision.decisions)}")
            print(f"Orders created: {daily_run.orders_created}")
            print(f"Status: {daily_run.status}")
            print(f"Summary: {decision.summary}")

            for item in decision.decisions:
                print(
                    f"{item.symbol}: {item.action.upper()} "
                    f"quantity={item.quantity} "
                    f"confidence={item.confidence:.2f}"
                )

    except Exception:
        print("\nRECOVERY FAILED — transaction was not committed.")
        raise

    finally:
        client.close()


if __name__ == "__main__":
    main()
