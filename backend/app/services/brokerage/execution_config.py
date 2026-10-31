from decimal import Decimal

# These are configurable simulation assumptions.
TRADING_FEE_RATE = Decimal("0.001")

MARKET_SLIPPAGE_RATE = Decimal("0.0005")

# Alpaca daily bars use the 1Day timeframe.
DAILY_TIMEFRAME = "1Day"

# We initially execute complete orders only.
# Partial fills can be introduced in a later iteration.