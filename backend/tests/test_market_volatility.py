
from math import sqrt
from statistics import stdev

from app.services.trading.market_context_service import (
    _calculate_annualized_volatility,
)


def test_volatility_returns_none_with_insufficient_history():
    closes = [100.0] * 20

    result = _calculate_annualized_volatility(closes, 20)

    assert result is None


def test_volatility_calculates_annualized_standard_deviation():
    closes = [
        100.0,
        101.0,
        100.0,
        102.0,
        101.0,
        103.0,
        102.0,
        104.0,
        103.0,
        105.0,
        104.0,
        106.0,
        105.0,
        107.0,
        106.0,
        108.0,
        107.0,
        109.0,
        108.0,
        110.0,
        109.0,
    ]

    daily_returns = [
        closes[index] / closes[index - 1] - 1
        for index in range(1, len(closes))
    ]

    expected = stdev(daily_returns) * sqrt(252)

    result = _calculate_annualized_volatility(closes, 20)

    assert result == expected


def test_volatility_returns_none_for_nonpositive_closes():
    closes = [100.0] * 21
    closes[-1] = 0.0

    result = _calculate_annualized_volatility(closes, 20)

    assert result is None
