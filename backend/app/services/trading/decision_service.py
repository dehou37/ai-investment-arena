
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.schemas.agent_decision import AgentDecision
from app.services.llm.ollama_client import OllamaClient
from app.services.trading.market_context_service import (
    build_agent_market_context,
)
from app.services.trading.strategies import StrategyRegistry


class DecisionOrchestrationError(Exception):
    """Raised when an agent's trading decision cannot be generated."""


class DecisionOrchestrator:
    """
    Coordinates market context construction and strategy execution.

    This service generates decisions only.
    It does not validate trading risk or submit orders.
    """

    def __init__(self, ollama_client: OllamaClient):
        self.ollama_client = ollama_client

    def generate_agent_decision(
        self,
        db: Session,
        competition_id: UUID,
        agent_id: UUID,
        as_of_date: date,
    ) -> AgentDecision:
        """
        Build market context and generate one agent's decision.
        """

        try:
            context: dict[str, Any] = build_agent_market_context(
                db=db,
                competition_id=competition_id,
                agent_id=agent_id,
                as_of_date=as_of_date,
            )

            strategy_type = context["agent"]["strategy_type"]

            if strategy_type == "llm_analyst":
                strategy = StrategyRegistry.get(
                    strategy_type,
                    ollama_client=self.ollama_client,
                )
            else:
                strategy = StrategyRegistry.get(strategy_type)

            return strategy.generate_decision(context)

        except Exception as error:
            raise DecisionOrchestrationError(
                f"Could not generate a decision for agent "
                f"{agent_id}: {error}"
            ) from error
