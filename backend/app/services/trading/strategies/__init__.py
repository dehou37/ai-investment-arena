
from app.services.trading.strategies.base import TradingStrategy
from app.services.trading.strategies.registry import StrategyRegistry

from app.services.trading.strategies.buy_and_hold import BuyAndHoldStrategy
from app.services.trading.strategies.momentum import MomentumStrategy
from app.services.trading.strategies.mean_reversion import MeanReversionStrategy
from app.services.trading.strategies.risk_managed import RiskManagedStrategy
from app.services.trading.strategies.llm_analyst import LLMAnalystStrategy


StrategyRegistry.register(BuyAndHoldStrategy)
StrategyRegistry.register(MomentumStrategy)
StrategyRegistry.register(MeanReversionStrategy)
StrategyRegistry.register(RiskManagedStrategy)
StrategyRegistry.register(LLMAnalystStrategy)


__all__ = [
    "TradingStrategy",
    "StrategyRegistry",
    "BuyAndHoldStrategy",
    "MomentumStrategy",
    "MeanReversionStrategy",
    "RiskManagedStrategy",
    "LLMAnalystStrategy",
]
