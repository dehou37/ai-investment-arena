from datetime import date
from uuid import UUID
import traceback

from app.core.database import SessionLocal
from app.services.llm.ollama_client import OllamaClient
from app.services.trading.decision_service import DecisionOrchestrator

COMPETITION_ID = UUID(
    "20c32a1d-9a39-4ee6-8060-74c439ba28fd"
)

AGENTS = {
    "Contrarian": UUID(
        "b5e105f4-4264-47ab-9605-b1f54495f4fa"
    ),
    "Guardian": UUID(
        "38cad769-8e60-49f6-a497-7e58a55a01e9"
    ),
    "Momentum": UUID(
        "85997829-b07f-4dd0-9d0a-b44f21b794ca"
    ),
    "Warren": UUID(
        "794ae61e-f60b-4129-95a4-c433ce287c7b"
    ),
}

TEST_DATE = date(2026, 11, 2)

client = OllamaClient()
orchestrator = DecisionOrchestrator(ollama_client=client)

results = {}

try:
    for agent_name, agent_id in AGENTS.items():
        print("\n" + "=" * 65)
        print(f"TESTING: {agent_name}")
        print("=" * 65)

        try:
            with SessionLocal() as db:
                decision = orchestrator.generate_agent_decision(
                    db=db,
                    competition_id=COMPETITION_ID,
                    agent_id=agent_id,
                    as_of_date=TEST_DATE,
                )

            symbols = [
                item.symbol for item in decision.decisions
            ]

            if len(symbols) != len(set(symbols)):
                raise ValueError("Duplicate symbols detected.")

            print("STATUS: PASSED")
            print("Date:", decision.as_of_date)
            print("Summary:", decision.summary)
            print("Total decisions:", len(decision.decisions))

            for item in decision.decisions:
                print(
                    f"{item.symbol}: {item.action.upper()}",
                    f"Quantity={item.quantity}",
                    f"Confidence={item.confidence:.2f}",
                )

            results[agent_name] = "PASSED"

        except Exception as error:
            print("STATUS: FAILED")
            print("Error:", str(error))
            traceback.print_exc()
            results[agent_name] = "FAILED"

finally:
    client.close()

print("\n" + "=" * 65)
print("FINAL TEST SUMMARY")
print("=" * 65)

for agent_name, status in results.items():
    print(f"{agent_name}: {status}")

print(
    f"\nPassed: {sum(v == 'PASSED' for v in results.values())}"
    f"/{len(AGENTS)}"
)

print(
    f"Failed: {sum(v == 'FAILED' for v in results.values())}"
    f"/{len(AGENTS)}"
)
