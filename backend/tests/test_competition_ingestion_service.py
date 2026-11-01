
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.market_data import competition_ingestion_service as service


SESSION_DATE = date(2026, 10, 30)
AFTER_CLOSE = datetime(2026, 10, 30, 21, 0, tzinfo=timezone.utc)


def make_competition(status="active"):
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        started_at=datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc),
        stock_universe_snapshot_id=uuid4(),
        benchmark_stock_id=uuid4(),
    )


def make_stock(symbol, asset_type="stock"):
    return SimpleNamespace(
        id=uuid4(),
        symbol=symbol,
        is_active=True,
        asset_type=asset_type,
    )


def make_stocks():
    stocks = {
        f"STOCK{i:02d}": make_stock(f"STOCK{i:02d}")
        for i in range(30)
    }
    stocks["SPY"] = make_stock("SPY", asset_type="etf")
    return stocks


def make_bar():
    return {
        "t": "2026-10-30T04:00:00Z",
        "o": 100.0,
        "h": 105.0,
        "l": 99.0,
        "c": 103.0,
        "v": 100000,
        "n": 1000,
        "vw": 102.0,
    }


class FakeDatabase:
    def __init__(self, competition, available_stock_ids=None):
        self.competition = competition
        self.available_stock_ids = available_stock_ids or []

    def get(self, model, object_id):
        if self.competition is None:
            return None

        if object_id == self.competition.id:
            return self.competition

        return None

    def scalars(self, statement):
        return SimpleNamespace(
            all=lambda: self.available_stock_ids
        )


class FakeClient:
    def __init__(self, bars_by_symbol):
        self.bars_by_symbol = bars_by_symbol
        self.request = None

    def get_daily_bars(self, symbols, start, end):
        self.request = {
            "symbols": symbols,
            "start": start,
            "end": end,
        }
        return self.bars_by_symbol


@pytest.fixture
def setup_ingestion(monkeypatch):
    competition = make_competition()
    stocks = make_stocks()

    monkeypatch.setattr(
        service,
        "_get_competition_stocks",
        lambda db, competition: stocks,
    )

    monkeypatch.setattr(
        service,
        "persist_alpaca_bars",
        lambda **kwargs: {
            "symbols_processed": 31,
            "bars_received": sum(
                len(bars)
                for bars in kwargs["bars_by_symbol"].values()
            ),
            "bars_upserted": sum(
                len(bars)
                for bars in kwargs["bars_by_symbol"].values()
            ),
        },
    )

    db = FakeDatabase(
        competition,
        available_stock_ids=[
            stock.id for stock in stocks.values()
        ],
    )

    client = FakeClient({
        "STOCK00": [make_bar()],
    })

    return competition, stocks, db, client


def test_ingestion_requests_30_stocks_and_benchmark(setup_ingestion):
    competition, stocks, db, client = setup_ingestion

    result = service.ingest_competition_session(
        db=db,
        client=client,
        competition_id=competition.id,
        session_date=SESSION_DATE,
        now=AFTER_CLOSE,
    )

    assert result["status"] == "complete"
    assert result["symbols_requested"] == 31
    assert result["symbols_available"] == 31
    assert result["missing_symbols"] == []

    assert len(client.request["symbols"]) == 31
    assert "SPY" in client.request["symbols"]
    assert client.request["start"] == "2026-10-30"
    assert client.request["end"] == "2026-10-31"


def test_ingestion_reports_missing_symbols(setup_ingestion):
    competition, stocks, db, client = setup_ingestion

    missing_stock = stocks["STOCK29"]
    db.available_stock_ids.remove(missing_stock.id)

    result = service.ingest_competition_session(
        db=db,
        client=client,
        competition_id=competition.id,
        session_date=SESSION_DATE,
        now=AFTER_CLOSE,
    )

    assert result["status"] == "incomplete"
    assert result["symbols_available"] == 30
    assert result["missing_symbols"] == ["STOCK29"]


def test_ingestion_rejects_missing_competition():
    db = FakeDatabase(None)
    client = FakeClient({})

    with pytest.raises(ValueError, match="Competition was not found"):
        service.ingest_competition_session(
            db=db,
            client=client,
            competition_id=uuid4(),
            session_date=SESSION_DATE,
            now=AFTER_CLOSE,
        )


def test_ingestion_rejects_inactive_competition():
    competition = make_competition(status="completed")
    db = FakeDatabase(competition)
    client = FakeClient({})

    with pytest.raises(ValueError, match="only be ingested for active"):
        service.ingest_competition_session(
            db=db,
            client=client,
            competition_id=competition.id,
            session_date=SESSION_DATE,
            now=AFTER_CLOSE,
        )


def test_ingestion_rejects_non_trading_date(setup_ingestion):
    competition, _, db, client = setup_ingestion

    with pytest.raises(ValueError, match="not an NYSE trading session"):
        service.ingest_competition_session(
            db=db,
            client=client,
            competition_id=competition.id,
            session_date=date(2026, 10, 31),
            now=AFTER_CLOSE,
        )

    assert client.request is None


def test_ingestion_rejects_session_before_market_close(setup_ingestion):
    competition, _, db, client = setup_ingestion

    before_close = datetime(
        2026, 10, 30, 19, 0, tzinfo=timezone.utc
    )

    with pytest.raises(ValueError, match="before its market close"):
        service.ingest_competition_session(
            db=db,
            client=client,
            competition_id=competition.id,
            session_date=SESSION_DATE,
            now=before_close,
        )

    assert client.request is None


def test_ingestion_rejects_bar_from_wrong_session(setup_ingestion):
    competition, _, db, client = setup_ingestion

    client.bars_by_symbol = {
        "STOCK00": [{
            **make_bar(),
            "t": "2026-10-29T04:00:00Z",
        }]
    }

    with pytest.raises(ValueError, match="expected 2026-10-30"):
        service.ingest_competition_session(
            db=db,
            client=client,
            competition_id=competition.id,
            session_date=SESSION_DATE,
            now=AFTER_CLOSE,
        )


def test_ingestion_rejects_unexpected_symbol(setup_ingestion):
    competition, _, db, client = setup_ingestion

    client.bars_by_symbol = {
        "UNKNOWN": [make_bar()],
    }

    with pytest.raises(ValueError, match="unexpected symbol"):
        service.ingest_competition_session(
            db=db,
            client=client,
            competition_id=competition.id,
            session_date=SESSION_DATE,
            now=AFTER_CLOSE,
        )


def test_ingestion_rejects_invalid_session_date_type(setup_ingestion):
    competition, _, db, client = setup_ingestion

    with pytest.raises(ValueError, match="must be a datetime.date"):
        service.ingest_competition_session(
            db=db,
            client=client,
            competition_id=competition.id,
            session_date=datetime(2026, 10, 30),
            now=AFTER_CLOSE,
        )

    assert client.request is None

def test_data_status_returns_complete_when_all_31_bars_exist(
    setup_ingestion,
):
    competition, stocks, db, _ = setup_ingestion

    result = service.get_competition_session_data_status(
        db=db,
        competition_id=competition.id,
        session_date=SESSION_DATE,
    )

    assert result["status"] == "complete"
    assert result["symbols_requested"] == 31
    assert result["symbols_available"] == 31
    assert result["missing_symbols"] == []


def test_data_status_reports_missing_symbols(setup_ingestion):
    competition, stocks, db, _ = setup_ingestion

    db.available_stock_ids.remove(stocks["STOCK29"].id)
    db.available_stock_ids.remove(stocks["SPY"].id)

    result = service.get_competition_session_data_status(
        db=db,
        competition_id=competition.id,
        session_date=SESSION_DATE,
    )

    assert result["status"] == "incomplete"
    assert result["symbols_requested"] == 31
    assert result["symbols_available"] == 29
    assert result["missing_symbols"] == ["SPY", "STOCK29"]


def test_data_status_rejects_missing_competition():
    db = FakeDatabase(None)

    with pytest.raises(
        ValueError,
        match="Competition was not found",
    ):
        service.get_competition_session_data_status(
            db=db,
            competition_id=uuid4(),
            session_date=SESSION_DATE,
        )