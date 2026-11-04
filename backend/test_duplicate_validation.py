from app.schemas.llm_decision import LLMAgentDecisionOutput
from pydantic import ValidationError

data = {
    "as_of_date": "2026-11-02",
    "summary": "Test",
    "decisions": [
        {
            "symbol": "NVDA",
            "action": "buy",
            "quantity": 1,
            "confidence": 0.8,
            "rationale": "Test buy",
        },
        {
            "symbol": "NVDA",
            "action": "sell",
            "quantity": 1,
            "confidence": 0.8,
            "rationale": "Test sell",
        },
    ],
}

try:
    LLMAgentDecisionOutput.model_validate(data)
    print("ERROR: Duplicate was accepted")
except ValidationError as error:
    print("PASS: Duplicate correctly rejected")
    print(error)
