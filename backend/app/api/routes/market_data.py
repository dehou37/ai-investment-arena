from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Stock, StockBar
from app.schemas.market_data import (
    StockResponse,
    StockBarResponse,
)


router = APIRouter(
    prefix="/api",
    tags=["Market Data"],
)


@router.get("/stocks", response_model=list[StockResponse])
def get_stocks(db: Session = Depends(get_db)):
    statement = select(Stock).order_by(Stock.symbol)

    return db.scalars(statement).all()


@router.get(
    "/stocks/{symbol}/bars",
    response_model=list[StockBarResponse],
)
def get_stock_bars(
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=1000, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    symbol = symbol.upper()

    stock = db.scalar(
        select(Stock).where(Stock.symbol == symbol)
    )

    if stock is None:
        raise HTTPException(
            status_code=404,
            detail=f"Stock {symbol} was not found.",
        )

    statement = (
        select(StockBar)
        .where(StockBar.stock_id == stock.id)
        .order_by(StockBar.timestamp.desc())
    )

    if start:
        start_datetime = datetime.combine(
            start,
            time.min,
            tzinfo=timezone.utc,
        )
        statement = statement.where(
            StockBar.timestamp >= start_datetime
        )

    if end:
        # End date is inclusive.
        end_datetime = datetime.combine(
            end + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        statement = statement.where(
            StockBar.timestamp < end_datetime
        )

    if start and end and start > end:
        raise HTTPException(
            status_code=400,
            detail="Start date cannot be after end date.",
        )

    statement = statement.limit(limit)

    return db.scalars(statement).all()