from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CompetitionCreate(BaseModel):
    name: str
    description: str | None = None
    duration_days: int = 90
    initial_cash: Decimal = Decimal("10000")


class PortfolioSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cash_balance: Decimal


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    strategy_type: str
    description: str | None
    status: str
    portfolio: PortfolioSummaryResponse | None = None


class CompetitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    status: str
    initial_cash: Decimal
    duration_days: int
    benchmark_symbol: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    agents: list[AgentResponse] = []