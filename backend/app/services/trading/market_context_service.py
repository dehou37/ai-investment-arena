
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pandas_market_calendars as mcal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings

from app.models.agent import Agent
from app.models.competition import Competition
from app.models.portfolio import Portfolio
from app.models.position import Position
from app.models.stock import Stock
from app.models.stock_bar import StockBar
from app.models.stock_universe_membership import StockUniverseMembership
from app.models.stock_universe_snapshot import StockUniverseSnapshot

from math import sqrt
from statistics import stdev


HISTORY_LIMIT = 60
DAILY_TIMEFRAME = "1Day"
RAW_ADJUSTMENT = "raw"
PROVIDER = "alpaca"

MARKET_CALENDAR = "NYSE"


def _utc_day_cutoff(as_of_date: date) -> datetime:
    """Exclusive UTC cutoff after the requested market date."""
    return datetime.combine(
        as_of_date + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )


def _get_latest_expected_session_date(as_of_date: date) -> date:
    """
    Return the latest NYSE trading session on or before as_of_date.

    This handles:
    - Saturdays and Sundays
    - US market holidays
    - Special trading calendars
    - Early-close sessions

    The simulation assumes decisions are made after the relevant
    trading session has completed.
    """
    calendar = mcal.get_calendar(MARKET_CALENDAR)

    schedule = calendar.schedule(
        start_date=as_of_date - timedelta(days=14),
        end_date=as_of_date,
    )

    if schedule.empty:
        raise ValueError(
            f"No NYSE trading session found on or before {as_of_date}."
        )

    return schedule.index[-1].date()


def _decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None

    return float(value)


def _calculate_sma(
    closes: list[float],
    period: int,
) -> float | None:
    if len(closes) < period:
        return None

    values = closes[-period:]

    return sum(values) / period


def _calculate_rsi(
    closes: list[float],
    period: int = 14,
) -> float | None:
    """
    Calculate RSI using simple average gains and losses
    over the most recent period.

    This is a simple RSI implementation, not Wilder's smoothed RSI.
    """
    if len(closes) < period + 1:
        return None

    changes = [
        closes[index] - closes[index - 1]
        for index in range(len(closes) - period, len(closes))
    ]

    gains = [
        change for change in changes
        if change > 0
    ]

    losses = [
        -change for change in changes
        if change < 0
    ]

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period

    if average_loss == 0:
        if average_gain == 0:
            return 50.0

        return 100.0

    relative_strength = average_gain / average_loss

    return 100.0 - (100.0 / (1.0 + relative_strength))


def _calculate_momentum(
    closes: list[float],
    period: int = 20,
) -> float | None:
    """Calculate percentage price change over the requested period."""
    if len(closes) < period + 1:
        return None

    previous_close = closes[-(period + 1)]
    latest_close = closes[-1]

    if previous_close == 0:
        return None

    return (latest_close / previous_close) - 1.0


def _calculate_annualized_volatility(
    closes: list[float],
    period: int = 20,
) -> float | None:
    """
    Calculate annualized historical volatility from daily close returns.

    Requires period + 1 closing prices to calculate period daily returns.
    Returns None when insufficient or invalid data is available.
    """
    if len(closes) < period + 1:
        return None

    recent_closes = closes[-(period + 1):]

    if any(
        close is None or close <= 0
        for close in recent_closes
    ):
        return None

    daily_returns = [
        (recent_closes[index] / recent_closes[index - 1]) - 1
        for index in range(1, len(recent_closes))
    ]

    if len(daily_returns) < 2:
        return None

    return stdev(daily_returns) * sqrt(252)

def _get_historical_bars(
    db: Session,
    stock_id: UUID,
    as_of_date: date,
) -> list[StockBar]:
    """
    Return up to 60 raw daily Alpaca bars on or before as_of_date.

    The exclusive UTC cutoff prevents future bars from entering
    the agent's market context.
    """
    cutoff = _utc_day_cutoff(as_of_date)

    statement = (
        select(StockBar)
        .where(
            StockBar.stock_id == stock_id,
            StockBar.timeframe == DAILY_TIMEFRAME,
            StockBar.adjustment == RAW_ADJUSTMENT,
            StockBar.provider == PROVIDER,
            StockBar.feed == settings.ALPACA_FEED,
            StockBar.timestamp < cutoff,
        )
        .order_by(StockBar.timestamp.desc())
        .limit(HISTORY_LIMIT)
    )

    bars = list(db.scalars(statement).all())

    bars.reverse()

    return bars


def _build_stock_context(
    stock: Stock,
    bars: list[StockBar],
    expected_session_date: date,
) -> dict[str, Any]:
    """
    Build stock context and determine whether its latest bar
    matches the latest expected completed NYSE session.
    """
    closes = [
        float(bar.close)
        for bar in bars
    ]

    latest_bar = bars[-1] if bars else None

    latest_bar_date = (
        latest_bar.timestamp.date()
        if latest_bar is not None
        else None
    )

    is_current_for_as_of_date = (
        latest_bar_date == expected_session_date
    )

    latest_price = (
        _decimal_to_float(latest_bar.close)
        if latest_bar is not None
        else None
    )

    history = [
        {
            "date": bar.timestamp.date().isoformat(),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": bar.volume,
        }
        for bar in bars
    ]

    return {
        "symbol": stock.symbol,
        "name": stock.name,
        "sector": stock.sector,
        "industry": stock.industry,
        "latest_price": latest_price,
        "latest_bar_date": (
            latest_bar_date.isoformat()
            if latest_bar_date is not None
            else None
        ),
        "expected_latest_session_date": (
            expected_session_date.isoformat()
        ),
        "data_status": (
            "current"
            if is_current_for_as_of_date
            else "stale_or_missing"
        ),
        "indicators": {
            "sma_20": _calculate_sma(closes, 20),
            "sma_50": _calculate_sma(closes, 50),
            "rsi_14": _calculate_rsi(closes, 14),
            "momentum_20d": _calculate_momentum(closes, 20),
            "volatility_20d": _calculate_annualized_volatility(closes, 20),
        },
        "history": history,
    }


def _get_universe_snapshot(
    db: Session,
    competition: Competition,
) -> StockUniverseSnapshot:
    """
    Select the latest completed universe snapshot available
    when this competition started.

    This keeps the stock universe fixed throughout the competition.
    """
    if competition.started_at is None:
        raise ValueError(
            "Competition must be started before market context "
            "can be generated."
        )

    statement = (
        select(StockUniverseSnapshot)
        .where(
            StockUniverseSnapshot.status == "completed",
            StockUniverseSnapshot.as_of <= competition.started_at,
        )
        .order_by(StockUniverseSnapshot.as_of.desc())
        .limit(1)
    )

    snapshot = db.scalars(statement).first()

    if snapshot is None:
        raise ValueError(
            "No completed stock universe snapshot was found "
            "at or before the competition start time."
        )

    return snapshot


def _get_agent_portfolio_context(
    db: Session,
    agent: Agent,
) -> dict[str, Any]:
    portfolio = db.scalars(
        select(Portfolio).where(
            Portfolio.agent_id == agent.id
        )
    ).first()

    if portfolio is None:
        raise ValueError(
            f"Agent {agent.name} does not have a portfolio."
        )

    positions = db.scalars(
        select(Position)
        .where(Position.portfolio_id == portfolio.id)
        .order_by(Position.stock_id)
    ).all()

    holdings = []

    for position in positions:
        holdings.append(
            {
                "symbol": position.stock.symbol,
                "quantity": position.quantity,
                "average_entry_price": float(
                    position.average_entry_price
                ),
            }
        )

    return {
        "portfolio_id": str(portfolio.id),
        "cash_balance": float(portfolio.cash_balance),
        "holdings": holdings,
    }


def build_agent_market_context(
    db: Session,
    competition_id: UUID,
    agent_id: UUID,
    as_of_date: date,
) -> dict[str, Any]:
    """
    Build the market and portfolio context for one agent.

    All historical market data is restricted to as_of_date or earlier.

    The competition's stock universe is fixed using the latest
    completed snapshot available at competition start.

    Market-data freshness is evaluated against the latest expected
    NYSE trading session, not simply against as_of_date.
    """
    competition = db.get(Competition, competition_id)

    if competition is None:
        raise ValueError("Competition not found.")

    if competition.status != "active":
        raise ValueError(
            "Market context can only be generated for active competitions."
        )

    agent = db.get(Agent, agent_id)

    if agent is None or agent.competition_id != competition.id:
        raise ValueError(
            "Agent was not found in this competition."
        )

    if agent.status != "active":
        raise ValueError("Agent is not active.")

    if competition.started_at is None:
        raise ValueError("Competition has no start timestamp.")

    if as_of_date < competition.started_at.date():
        raise ValueError(
            "Decision date cannot be earlier than the competition start date."
        )

    # Determine the latest expected completed NYSE session.
    expected_session_date = _get_latest_expected_session_date(
        as_of_date
    )

    snapshot = _get_universe_snapshot(db, competition)

    memberships = db.scalars(
        select(StockUniverseMembership)
        .where(
            StockUniverseMembership.snapshot_id == snapshot.id
        )
        .order_by(StockUniverseMembership.sector_rank)
    ).all()

    if not memberships:
        raise ValueError(
            "The selected stock universe snapshot has no members."
        )

    stocks: list[Stock] = []

    for membership in memberships:
        stock = membership.stock

        if stock.is_active and stock.asset_type == "stock":
            stocks.append(stock)

    if not stocks:
        raise ValueError(
            "The selected universe contains no active stocks."
        )

    market_data = []

    for stock in stocks:
        bars = _get_historical_bars(
            db=db,
            stock_id=stock.id,
            as_of_date=as_of_date,
        )

        market_data.append(
            _build_stock_context(
                stock=stock,
                bars=bars,
                expected_session_date=expected_session_date,
            )
        )

    benchmark_stock = competition.benchmark_stock

    benchmark_bars = _get_historical_bars(
        db=db,
        stock_id=benchmark_stock.id,
        as_of_date=as_of_date,
    )

    if not benchmark_bars:
        raise ValueError(
            f"No historical benchmark data found for "
            f"{benchmark_stock.symbol} on or before {as_of_date}."
        )

    benchmark = _build_stock_context(
        stock=benchmark_stock,
        bars=benchmark_bars,
        expected_session_date=expected_session_date,
    )

    portfolio_context = _get_agent_portfolio_context(
        db=db,
        agent=agent,
    )

    return {
        "competition": {
            "id": str(competition.id),
            "name": competition.name,
            "initial_cash": float(competition.initial_cash),
            "duration_days": competition.duration_days,
            "benchmark_symbol": benchmark_stock.symbol,
        },
        "agent": {
            "id": str(agent.id),
            "name": agent.name,
            "strategy_type": agent.strategy_type,
            "description": agent.description,
            "config": agent.config or {},
        },
        "as_of_date": as_of_date.isoformat(),
        "expected_latest_session_date": (
            expected_session_date.isoformat()
        ),
        "universe": {
            "snapshot_id": str(snapshot.id),
            "snapshot_as_of": snapshot.as_of.isoformat(),
            "stock_count": len(market_data),
            "stocks": market_data,
        },
        "benchmark": benchmark,
        "portfolio": portfolio_context,
        "trading_constraints": {
            "long_only": True,
            "whole_shares_only": True,
            "fractional_shares_allowed": False,
            "margin_allowed": False,
            "short_selling_allowed": False,
        },
    }
