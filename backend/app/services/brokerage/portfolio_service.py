from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Agent,
    Competition,
    Execution,
    Order,
    Portfolio,
    Position,
    StockBar,
)
from app.core.config import settings

ZERO = Decimal("0")


def get_utc_date_cutoff(as_of_date: date | None):
    """
    Return midnight UTC on the day after as_of_date.

    This creates an exclusive upper bound for historical queries.
    """

    if as_of_date is None:
        return None

    return datetime.combine(
        as_of_date + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )


def reconstruct_portfolio_performance(
    db: Session,
    portfolio_id: UUID,
    as_of_date: date | None = None,
):
    """
    Reconstruct realised P&L and remaining cost basis from executions.

    Buy fees are added to cost basis.
    Sell fees are deducted from sale proceeds.
    Slippage is informational because it is already reflected
    in the execution price.
    """

    query = (
        select(Execution, Order.stock_id, Order.side)
        .join(Order, Execution.order_id == Order.id)
        .where(Order.portfolio_id == portfolio_id)
    )

    cutoff = get_utc_date_cutoff(as_of_date)

    if cutoff is not None:
        query = query.where(Execution.executed_at < cutoff)

    executions = db.execute(
        query.order_by(
            Execution.executed_at.asc(),
            Execution.id.asc(),
        )
    ).all()

    holdings = defaultdict(int)
    cost_basis = defaultdict(lambda: ZERO)

    realised_pnl = ZERO
    total_fees = ZERO
    total_slippage = ZERO

    for execution, stock_id, side in executions:
        quantity = execution.quantity
        price = Decimal(str(execution.execution_price))
        fees = Decimal(str(execution.fees))
        slippage = Decimal(str(execution.slippage))

        total_fees += fees
        total_slippage += slippage

        if side == "buy":
            holdings[stock_id] += quantity
            cost_basis[stock_id] += (price * quantity) + fees

        elif side == "sell":
            current_quantity = holdings[stock_id]

            if quantity > current_quantity:
                raise ValueError(
                    f"Execution history is inconsistent for stock {stock_id}: "
                    f"attempted to sell {quantity} shares but only "
                    f"{current_quantity} shares are recorded."
                )

            if current_quantity <= 0:
                raise ValueError(
                    f"Execution history has a sell without a previous buy "
                    f"for stock {stock_id}."
                )

            average_cost = cost_basis[stock_id] / current_quantity
            cost_removed = average_cost * quantity
            net_proceeds = (price * quantity) - fees

            realised_pnl += net_proceeds - cost_removed

            holdings[stock_id] -= quantity
            cost_basis[stock_id] -= cost_removed

        else:
            raise ValueError(
                f"Unsupported execution side: {side}"
            )

    return {
        "holdings": dict(holdings),
        "cost_basis": dict(cost_basis),
        "realised_pnl": realised_pnl,
        "total_fees": total_fees,
        "total_slippage": total_slippage,
    }


def get_latest_raw_close(
    db: Session,
    stock_id: UUID,
    as_of_date: date | None = None,
):
    """
    Retrieve the latest raw daily closing bar.

    When as_of_date is supplied, future bars are excluded.
    """

    query = (
        select(StockBar)
        .where(
            StockBar.stock_id == stock_id,
            StockBar.timeframe == settings.ALPACA_TIMEFRAME,
            StockBar.provider == settings.ALPACA_PROVIDER,
            StockBar.feed == settings.ALPACA_FEED,
            StockBar.adjustment == settings.ALPACA_ADJUSTMENT,
        )
    )

    cutoff = get_utc_date_cutoff(as_of_date)

    if cutoff is not None:
        query = query.where(StockBar.timestamp < cutoff)

    return db.scalar(
        query.order_by(StockBar.timestamp.desc()).limit(1)
    )


def get_raw_close_for_session(
    db: Session,
    stock_id: UUID,
    session_date: date,
):
    """
    Retrieve a raw daily closing bar for the exact requested
    trading session.

    Returns None if no bar exists for that session.
    Prefers Alpaca IEX when multiple providers/feeds exist.
    """

    session_start = datetime.combine(
        session_date,
        time.min,
        tzinfo=timezone.utc,
    )
    session_end = session_start + timedelta(days=1)

    query = (
        select(StockBar)
        .where(
            StockBar.stock_id == stock_id,
            StockBar.timeframe == settings.ALPACA_TIMEFRAME,
            StockBar.provider == settings.ALPACA_PROVIDER,
            StockBar.feed == settings.ALPACA_FEED,
            StockBar.adjustment == settings.ALPACA_ADJUSTMENT,
            StockBar.timestamp >= session_start,
            StockBar.timestamp < session_end,
        )
        .order_by(StockBar.timestamp.desc())
    )

    return db.scalar(query.limit(1))


def calculate_portfolio_valuation(
    db: Session,
    portfolio: Portfolio,
    initial_cash: Decimal,
    as_of_date: date | None = None,
    exact_session_date: date | None = None,
):
    """
    Calculate portfolio valuation.

    If exact_session_date is supplied, every held stock must
    have a raw daily closing bar for that exact session.

    Otherwise, use the latest available raw closing bar on or
    before as_of_date.
    """

    performance = reconstruct_portfolio_performance(
        db,
        portfolio.id,
        as_of_date=as_of_date,
    )

    ledger_holdings = performance["holdings"]
    ledger_cost_basis = performance["cost_basis"]

    positions = db.scalars(
        select(Position)
        .options(selectinload(Position.stock))
        .where(Position.portfolio_id == portfolio.id)
        .order_by(Position.stock_id.asc())
    ).all()

    cash_balance = Decimal(str(portfolio.cash_balance))
    total_market_value = ZERO
    total_unrealised_pnl = ZERO

    position_results = []
    missing_prices = []
    inconsistent_positions = []

    position_stock_ids = set()

    for position in positions:
        stock_id = position.stock_id
        position_stock_ids.add(stock_id)

        recorded_quantity = position.quantity
        ledger_quantity = ledger_holdings.get(stock_id, 0)

        if recorded_quantity != ledger_quantity:
            inconsistent_positions.append(position.stock.symbol)

        if exact_session_date is not None:
            latest_bar = get_raw_close_for_session(
                db,
                stock_id,
                session_date=exact_session_date,
            )
        else:
            latest_bar = get_latest_raw_close(
                db,
                stock_id,
                as_of_date=as_of_date,
            )

        if latest_bar is None:
            missing_prices.append(position.stock.symbol)

            position_results.append({
                "stock_symbol": position.stock.symbol,
                "quantity": recorded_quantity,
                "average_entry_price": position.average_entry_price,
                "latest_price": None,
                "market_value": None,
                "cost_basis": ledger_cost_basis.get(stock_id, ZERO),
                "unrealised_pnl": None,
                "price_timestamp": None,
            })
            continue

        latest_price = Decimal(str(latest_bar.close))
        market_value = latest_price * recorded_quantity
        position_cost_basis = ledger_cost_basis.get(stock_id, ZERO)
        unrealised_pnl = market_value - position_cost_basis

        total_market_value += market_value
        total_unrealised_pnl += unrealised_pnl

        position_results.append({
            "stock_symbol": position.stock.symbol,
            "quantity": recorded_quantity,
            "average_entry_price": position.average_entry_price,
            "latest_price": latest_price,
            "market_value": market_value,
            "cost_basis": position_cost_basis,
            "unrealised_pnl": unrealised_pnl,
            "price_timestamp": latest_bar.timestamp,
        })

    for stock_id, quantity in ledger_holdings.items():
        if quantity > 0 and stock_id not in position_stock_ids:
            inconsistent_positions.append(str(stock_id))

    valuation_complete = (
        not missing_prices
        and not inconsistent_positions
    )

    portfolio_equity = None
    total_pnl = None
    total_return_pct = None
    unrealised_pnl = None

    if valuation_complete:
        portfolio_equity = cash_balance + total_market_value
        unrealised_pnl = total_unrealised_pnl

        total_pnl = (
            portfolio_equity - Decimal(str(initial_cash))
        )

        if initial_cash > 0:
            total_return_pct = (
                total_pnl / Decimal(str(initial_cash))
            ) * Decimal("100")

    return {
        "cash_balance": cash_balance,
        "market_value": (
            total_market_value if valuation_complete else None
        ),
        "portfolio_equity": portfolio_equity,
        "initial_cash": Decimal(str(initial_cash)),
        "realised_pnl": performance["realised_pnl"],
        "unrealised_pnl": unrealised_pnl,
        "total_pnl": total_pnl,
        "total_return_pct": total_return_pct,
        "total_fees": performance["total_fees"],
        "total_slippage": performance["total_slippage"],
        "valuation_complete": valuation_complete,
        "missing_price_symbols": missing_prices,
        "inconsistent_positions": inconsistent_positions,
        "positions": position_results,
    }


def get_agent_portfolio(
    db: Session,
    competition_id: UUID,
    agent_id: UUID,
):
    agent = db.scalar(
        select(Agent)
        .options(selectinload(Agent.portfolio))
        .where(
            Agent.id == agent_id,
            Agent.competition_id == competition_id,
        )
    )

    if agent is None or agent.portfolio is None:
        return None

    competition = db.get(Competition, competition_id)

    if competition is None:
        return None

    valuation = calculate_portfolio_valuation(
        db=db,
        portfolio=agent.portfolio,
        initial_cash=competition.initial_cash,
    )

    return {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "strategy_type": agent.strategy_type,
        "agent_status": agent.status,
        **valuation,
    }


def get_competition_leaderboard(
    db: Session,
    competition_id: UUID,
):
    competition = db.scalar(
        select(Competition)
        .options(
            selectinload(Competition.agents)
            .selectinload(Agent.portfolio),
        )
        .where(Competition.id == competition_id)
    )

    if competition is None:
        return None

    leaderboard = []

    for agent in competition.agents:
        if agent.portfolio is None:
            continue

        valuation = calculate_portfolio_valuation(
            db=db,
            portfolio=agent.portfolio,
            initial_cash=competition.initial_cash,
        )

        leaderboard.append({
            "agent_id": agent.id,
            "agent_name": agent.name,
            "strategy_type": agent.strategy_type,
            "agent_status": agent.status,
            "cash_balance": valuation["cash_balance"],
            "market_value": valuation["market_value"],
            "portfolio_equity": valuation["portfolio_equity"],
            "initial_cash": valuation["initial_cash"],
            "realised_pnl": valuation["realised_pnl"],
            "unrealised_pnl": valuation["unrealised_pnl"],
            "total_pnl": valuation["total_pnl"],
            "total_return_pct": valuation["total_return_pct"],
            "total_fees": valuation["total_fees"],
            "total_slippage": valuation["total_slippage"],
            "valuation_complete": valuation["valuation_complete"],
            "missing_price_symbols": valuation["missing_price_symbols"],
            "inconsistent_positions": valuation["inconsistent_positions"],
        })

    leaderboard.sort(
        key=lambda item: (
            item["valuation_complete"],
            item["total_return_pct"]
            if item["total_return_pct"] is not None
            else Decimal("-Infinity"),
        ),
        reverse=True,
    )

    for index, entry in enumerate(leaderboard, start=1):
        entry["rank"] = index

    return leaderboard