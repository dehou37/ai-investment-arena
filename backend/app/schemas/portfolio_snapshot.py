from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class PortfolioSnapshotResponse(BaseModel):
    id: UUID
    portfolio_id: UUID
    snapshot_date: date

    cash_balance: Decimal
    market_value: Decimal | None
    portfolio_equity: Decimal | None

    realised_pnl: Decimal
    unrealised_pnl: Decimal | None
    total_pnl: Decimal | None
    total_return_pct: Decimal | None

    total_fees: Decimal
    total_slippage: Decimal

    benchmark_close: Decimal
    valuation_complete: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SnapshotSkippedIncompleteResponse(BaseModel):
    agent_id: str
    agent_name: str
    reason: str
    missing_price_symbols: list[str] = Field(default_factory=list)
    inconsistent_positions: list[str] = Field(default_factory=list)


class SnapshotCreationResponse(BaseModel):
    competition_id: UUID
    snapshot_date: date
    created_count: int
    skipped_existing: list[str]
    skipped_incomplete: list[SnapshotSkippedIncompleteResponse]
    benchmark_symbol: str
    benchmark_close: Decimal


class AgentSnapshotHistoryResponse(BaseModel):
    competition_id: UUID
    agent_id: UUID
    agent_name: str
    strategy_type: str
    snapshots: list[PortfolioSnapshotResponse]