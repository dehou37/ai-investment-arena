
from datetime import date
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class AgentTradeDecision(BaseModel):
    """
    One trading decision made by an AI agent.
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(
        min_length=1,
        max_length=10,
    )

    action: Literal["buy", "sell", "hold"]

    quantity: int | None = Field(
        default=None,
        gt=0,
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    rationale: str = Field(
        min_length=1,
        max_length=500,
    )

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_quantity(self):
        if self.action == "hold" and self.quantity is not None:
            raise ValueError(
                "Hold decisions must not specify a quantity."
            )

        if self.action in ("buy", "sell") and self.quantity is None:
            raise ValueError(
                "Buy and sell decisions require a quantity."
            )

        return self


class AgentDecision(BaseModel):
    """
    Complete set of decisions produced by one agent
    for a particular market date.
    """

    model_config = ConfigDict(extra="forbid")

    as_of_date: date

    summary: str = Field(
        min_length=1,
        max_length=1000,
    )

    decisions: list[AgentTradeDecision] = Field(
        max_length=30,
    )

    @model_validator(mode="after")
    def validate_unique_symbols(self):
        symbols = [
            decision.symbol
            for decision in self.decisions
        ]

        if len(symbols) != len(set(symbols)):
            raise ValueError(
                "An agent cannot submit multiple decisions "
                "for the same stock."
            )

        return self
