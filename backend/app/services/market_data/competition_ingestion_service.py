
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.competition import Competition
from app.models.stock import Stock
from app.models.stock_bar import StockBar
from app.models.stock_universe_membership import StockUniverseMembership
from app.models.stock_universe_snapshot import StockUniverseSnapshot
from app.services.market_data.alpaca import AlpacaMarketDataClient
from app.services.market_data.ingestion_service import (
    persist_alpaca_bars,
)
from app.services.trading.calendar_service import (
    get_market_session_close,
    get_market_session_open,
)
from app.core.config import settings

NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc
EXPECTED_UNIVERSE_SIZE = 30


def _normalise_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)


def _validate_bar_session(
    bars_by_symbol: dict[str, list[dict]],
    session_date: date,
) -> None:
    """Reject bars that do not belong to the requested NYSE session."""
    for symbol, bars in bars_by_symbol.items():
        for bar in bars:
            raw_timestamp = bar.get("t")

            try:
                timestamp = datetime.fromisoformat(
                    raw_timestamp.replace("Z", "+00:00")
                )
            except (AttributeError, TypeError, ValueError):
                raise ValueError(
                    f"{symbol}: invalid bar timestamp {raw_timestamp!r}."
                )

            if timestamp.tzinfo is None:
                raise ValueError(
                    f"{symbol}: bar timestamp must include a timezone."
                )

            bar_session_date = timestamp.astimezone(NEW_YORK).date()

            if bar_session_date != session_date:
                raise ValueError(
                    f"{symbol}: received a bar for "
                    f"{bar_session_date}, expected {session_date}."
                )


def _get_competition_stocks(
    db: Session,
    competition: Competition,
) -> dict[str, Stock]:
    """
    Load the exact 30 stocks assigned to this competition.

    Never resolve a newer universe snapshot dynamically.
    """
    if competition.stock_universe_snapshot_id is None:
        raise ValueError(
            "Competition has no assigned stock universe snapshot."
        )

    snapshot = db.get(
        StockUniverseSnapshot,
        competition.stock_universe_snapshot_id,
    )

    if snapshot is None or snapshot.status != "completed":
        raise ValueError(
            "Competition's assigned universe snapshot "
            "is missing or incomplete."
        )

    if snapshot.total_members != EXPECTED_UNIVERSE_SIZE:
        raise ValueError(
            f"Expected {EXPECTED_UNIVERSE_SIZE} universe members, "
            f"found {snapshot.total_members}."
        )

    rows = db.execute(
        select(StockUniverseMembership, Stock)
        .join(
            Stock,
            Stock.id == StockUniverseMembership.stock_id,
        )
        .where(
            StockUniverseMembership.snapshot_id == snapshot.id
        )
        .order_by(Stock.symbol)
    ).all()

    if len(rows) != EXPECTED_UNIVERSE_SIZE:
        raise ValueError(
            f"Expected {EXPECTED_UNIVERSE_SIZE} actual universe "
            f"memberships, found {len(rows)}."
        )

    stocks_by_symbol: dict[str, Stock] = {}

    for _, stock in rows:
        if not stock.is_active or stock.asset_type != "stock":
            raise ValueError(
                f"Universe stock {stock.symbol} is inactive "
                "or is not classified as a stock."
            )

        if stock.symbol in stocks_by_symbol:
            raise ValueError(
                f"Duplicate stock symbol in universe: {stock.symbol}."
            )

        stocks_by_symbol[stock.symbol] = stock

    benchmark = db.get(
        Stock,
        competition.benchmark_stock_id,
    )

    if benchmark is None:
        raise ValueError("Competition benchmark stock was not found.")

    if not benchmark.is_active or benchmark.asset_type != "etf":
        raise ValueError(
            "Competition benchmark must be an active ETF."
        )

    if benchmark.symbol in stocks_by_symbol:
        raise ValueError(
            "Benchmark ETF must not also appear in the stock universe."
        )

    stocks_by_symbol[benchmark.symbol] = benchmark

    return stocks_by_symbol


def ingest_competition_session(
    db: Session,
    client: AlpacaMarketDataClient,
    competition_id,
    session_date: date,
    now: datetime | None = None,
) -> dict:
    """
    Fetch and persist daily bars for one competition and NYSE session.

    Fetches the competition's 30 assigned stocks plus its benchmark.

    The caller owns the database transaction and must commit or roll
    back the session.

    Missing bars are reported as incomplete rather than treated as
    successful ingestion.
    """
    if isinstance(session_date, datetime) or not isinstance(
        session_date, date
    ):
        raise ValueError("session_date must be a datetime.date.")

    competition = db.get(Competition, competition_id)

    if competition is None:
        raise ValueError("Competition was not found.")

    if competition.status != "active":
        raise ValueError(
            "Market data can only be ingested for active competitions."
        )

    if competition.started_at is None:
        raise ValueError(
            "Active competition has no recorded start time."
        )

    market_open = get_market_session_open(session_date)
    market_close = get_market_session_close(session_date)

    if market_open is None or market_close is None:
        raise ValueError(
            f"{session_date} is not an NYSE trading session."
        )

    started_at = _normalise_utc(competition.started_at)

    if _normalise_utc(market_open) < started_at:
        raise ValueError(
            "The requested session began before the competition started."
        )

    current_time = _normalise_utc(
        now if now is not None else datetime.now(UTC)
    )

    market_close = _normalise_utc(market_close)

    if current_time < market_close:
        raise ValueError(
            "Cannot ingest a session before its market close."
        )

    stocks_by_symbol = _get_competition_stocks(
        db,
        competition,
    )

    symbols = sorted(stocks_by_symbol)

    # Alpaca's end parameter is exclusive. Request through the
    # beginning of the following calendar day.
    bars_by_symbol = client.get_daily_bars(
        symbols=symbols,
        start=session_date.isoformat(),
        end=(session_date + timedelta(days=1)).isoformat(),
    )

    if not isinstance(bars_by_symbol, dict):
        raise ValueError(
            "Alpaca returned an invalid daily bars response."
        )

    # Normalise symbol casing and reject unexpected symbols.
    normalised_bars: dict[str, list[dict]] = {}

    for returned_symbol, bars in bars_by_symbol.items():
        symbol = returned_symbol.upper()

        if symbol not in stocks_by_symbol:
            raise ValueError(
                f"Alpaca returned an unexpected symbol: {symbol}."
            )

        if symbol in normalised_bars:
            raise ValueError(
                f"Alpaca returned duplicate symbol entries: {symbol}."
            )

        if not isinstance(bars, list):
            raise ValueError(
                f"Alpaca returned an invalid bar list for {symbol}."
            )

        normalised_bars[symbol] = bars

    _validate_bar_session(
        normalised_bars,
        session_date,
    )

    persistence_result = persist_alpaca_bars(
        db=db,
        stocks_by_symbol=stocks_by_symbol,
        bars_by_symbol=normalised_bars,
    )

    # Determine availability using the database, so a previously
    # persisted bar still counts if the provider omits it on retry.
    session_start = datetime.combine(
        session_date,
        time.min,
        tzinfo=NEW_YORK,
    ).astimezone(UTC)

    session_end = datetime.combine(
        session_date + timedelta(days=1),
        time.min,
        tzinfo=NEW_YORK,
    ).astimezone(UTC)

    available_stock_ids = set(
        db.scalars(
            select(StockBar.stock_id).where(
                StockBar.stock_id.in_(
                    [stock.id for stock in stocks_by_symbol.values()]
                ),
                StockBar.timestamp >= session_start,
                StockBar.timestamp < session_end,
                StockBar.timeframe == settings.ALPACA_TIMEFRAME,
                StockBar.provider == settings.ALPACA_PROVIDER,
                StockBar.feed == settings.ALPACA_FEED,
                StockBar.adjustment == settings.ALPACA_ADJUSTMENT,
            )
        ).all()
    )

    missing_symbols = sorted(
        symbol
        for symbol, stock in stocks_by_symbol.items()
        if stock.id not in available_stock_ids
    )

    return {
        "competition_id": str(competition.id),
        "session_date": session_date.isoformat(),
        "symbols_requested": len(symbols),
        "symbols_available": len(symbols) - len(missing_symbols),
        "missing_symbols": missing_symbols,
        "status": "complete" if not missing_symbols else "incomplete",
        **persistence_result,
    }
