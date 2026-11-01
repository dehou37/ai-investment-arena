from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ExecutionActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    quantity: int
    execution_price: Decimal
    fees: Decimal
    slippage: Decimal
    executed_at: datetime


class OrderActivityResponse(BaseModel):
    id: UUID
    stock_symbol: str
    side: str
    order_type: str
    quantity: int
    limit_price: Decimal | None
    status: str
    submitted_at: datetime
    scheduled_execution_at: datetime | None
    executions: list[ExecutionActivityResponse]


class TradeActivityResponse(BaseModel):
    id: UUID
    stock_symbol: str
    side: str
    quantity: int
    execution_price: Decimal
    fees: Decimal
    slippage: Decimal
    executed_at: datetime


class DailyRunActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trading_date: date
    status: str
    decision: dict[str, Any] | None
    orders_created: int
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None