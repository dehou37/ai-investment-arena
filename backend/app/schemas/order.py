
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class OrderCreate(BaseModel):
    stock_symbol: str = Field(min_length=1, max_length=20)
    side: str
    order_type: str
    quantity: int = Field(gt=0)

    limit_price: Decimal | None = Field(default=None, gt=0)

    @field_validator("stock_symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("side")
    @classmethod
    def validate_side(cls, value: str) -> str:
        value = value.lower()

        if value not in {"buy", "sell"}:
            raise ValueError("Side must be 'buy' or 'sell'.")

        return value

    @field_validator("order_type")
    @classmethod
    def validate_order_type(cls, value: str) -> str:
        value = value.lower()

        if value not in {"market", "limit"}:
            raise ValueError("Order type must be 'market' or 'limit'.")

        return value

    @field_validator("limit_price")
    @classmethod
    def validate_limit_price(cls, value, info):
        order_type = info.data.get("order_type")

        if order_type == "limit" and value is None:
            raise ValueError("Limit orders require a limit_price.")

        if order_type == "market" and value is not None:
            raise ValueError("Market orders must not include a limit_price.")

        return value


class OrderBatchCreate(BaseModel):
    orders: list[OrderCreate] = Field(
        min_length=1,
        max_length=30,
    )

    @model_validator(mode="after")
    def validate_unique_symbols(self):
        symbols = [
            order.stock_symbol
            for order in self.orders
        ]

        if len(symbols) != len(set(symbols)):
            raise ValueError(
                "A batch cannot contain multiple orders for the same stock."
            )

        return self


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    portfolio_id: UUID
    stock_id: UUID
    side: str
    order_type: str
    quantity: int
    limit_price: Decimal | None
    status: str
    submitted_at: datetime
    scheduled_execution_at: datetime | None
