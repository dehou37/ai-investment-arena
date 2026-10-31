
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.schemas.agent_decision import AgentDecision
from app.services.llm.ollama_client import OllamaClient
from app.services.trading.market_context_service import (
    build_agent_market_context,
)
from app.services.trading.risk_service import (
    RiskValidationError,
    validate_agent_decision,
)
from app.services.trading.strategies import StrategyRegistry


class DecisionOrchestrationError(Exception):
    """Raised when agent decision orchestration fails."""


class DecisionOrchestrator:
    def __init__(self, ollama_client: OllamaClient):
        self.ollama_client = ollama_client

    def generate_agent_decision(
        self,
        db: Session,
        competition_id: UUID,
        agent_id: UUID,
        as_of_date: date,
    ) -> AgentDecision:

        try:
            # 1. Build market and portfolio context.
            context = build_agent_market_context(
                db=db,
                competition_id=competition_id,
                agent_id=agent_id,
                as_of_date=as_of_date,
            )

            # 2. Select the agent's strategy.
            strategy_type = context["agent"]["strategy_type"]

            if strategy_type == "llm_analyst":
                strategy = StrategyRegistry.get(
                    strategy_type,
                    ollama_client=self.ollama_client,
                )
            else:
                strategy = StrategyRegistry.get(strategy_type)

            # 3. Generate the proposed decision.
            decision = strategy.generate_decision(context)

            # 4. Validate the complete decision against global
            #    portfolio risk limits.
            validate_agent_decision(
                decision=decision,
                context=context,
            )

            # 5. Return only a risk-approved decision.
            return decision

        except RiskValidationError:
            # Preserve risk failures so callers can distinguish
            # rejected trades from orchestration failures.
            raise

        except Exception as error:
            raise DecisionOrchestrationError(
                f"Could not generate a decision for agent "
                f"{agent_id}: {error}"
            ) from error
