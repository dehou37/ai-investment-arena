import re

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.agent_decision import AgentTradeDecision


class LLMAgentDecisionOutput(BaseModel):
    """
    LLM-facing response schema.

    Uses a string for as_of_date to keep the JSON schema
    compatible with Ollama structured outputs.
    """

    model_config = ConfigDict(extra="forbid")

    as_of_date: str = Field(
        description="Market analysis date in YYYY-MM-DD format."
    )

    summary: str = Field(
        min_length=1,
        max_length=1000,
        description="Summary of the investment strategy and market outlook.",
    )

    decisions: list[AgentTradeDecision] = Field(
        max_length=30,
        description="Trading decisions for stocks in the available universe.",
    )

    @field_validator("as_of_date")
    @classmethod
    def validate_date_format(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("as_of_date must use YYYY-MM-DD format.")

        return value

    @model_validator(mode="after")
    def validate_unique_symbols(self):
        symbols = [decision.symbol for decision in self.decisions]

        duplicates = sorted({
            symbol for symbol in symbols
            if symbols.count(symbol) > 1
        })

        if duplicates:
            raise ValueError(
                "Each stock must appear only once in the decisions. "
                f"Duplicate symbols: {', '.join(duplicates)}."
            )

        return self
