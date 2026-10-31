from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class PositionValuationResponse(BaseModel):
    stock_symbol: str
    quantity: int
    average_entry_price: Decimal
    latest_price: Decimal | None
    market_value: Decimal | None
    cost_basis: Decimal
    unrealised_pnl: Decimal | None
    price_timestamp: datetime | None


class PortfolioResponse(BaseModel):
    agent_id: UUID
    agent_name: str
    strategy_type: str
    agent_status: str

    cash_balance: Decimal
    market_value: Decimal | None
    portfolio_equity: Decimal | None
    initial_cash: Decimal

    realised_pnl: Decimal
    unrealised_pnl: Decimal | None
    total_pnl: Decimal | None
    total_return_pct: Decimal | None

    total_fees: Decimal
    total_slippage: Decimal

    valuation_complete: bool
    missing_price_symbols: list[str]
    inconsistent_positions: list[str]

    positions: list[PositionValuationResponse]


class LeaderboardEntryResponse(BaseModel):
    rank: int
    agent_id: UUID
    agent_name: str
    strategy_type: str
    agent_status: str

    cash_balance: Decimal
    market_value: Decimal | None
    portfolio_equity: Decimal | None
    initial_cash: Decimal

    realised_pnl: Decimal
    unrealised_pnl: Decimal | None
    total_pnl: Decimal | None
    total_return_pct: Decimal | None

    total_fees: Decimal
    total_slippage: Decimal

    valuation_complete: bool
    missing_price_symbols: list[str]
    inconsistent_positions: list[str]