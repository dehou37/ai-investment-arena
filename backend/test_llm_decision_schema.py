
from app.schemas.agent_decision import AgentDecision
from app.schemas.llm_decision import LLMAgentDecisionOutput


def main():
    sample_response = {
        "as_of_date": "2026-10-30",
        "summary": "NVDA demonstrates positive momentum.",
        "decisions": [
            {
                "symbol": "NVDA",
                "action": "buy",
                "quantity": 2,
                "confidence": 0.85,
                "rationale": "Positive momentum and strong technical indicators.",
            },
            {
                "symbol": "AAPL",
                "action": "hold",
                "quantity": None,
                "confidence": 0.70,
                "rationale": "No compelling trading signal.",
            },
        ],
    }

    # Validate the LLM-facing output.
    llm_output = LLMAgentDecisionOutput.model_validate(
        sample_response
    )

    # Convert into the existing application decision schema.
    agent_decision = AgentDecision.model_validate(
        llm_output.model_dump()
    )

    print("SUCCESS: LLM output schema validated.")
    print("Analysis date:", agent_decision.as_of_date)
    print("Summary:", agent_decision.summary)
    print("Number of decisions:", len(agent_decision.decisions))

    for decision in agent_decision.decisions:
        print(
            decision.symbol,
            decision.action,
            decision.quantity,
        )

    print("\nJSON Schema generated successfully:")
    print(LLMAgentDecisionOutput.model_json_schema())


if __name__ == "__main__":
    main()
