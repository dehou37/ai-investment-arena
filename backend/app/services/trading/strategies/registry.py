
from app.services.trading.strategies.base import TradingStrategy


class StrategyRegistry:
    """
    Central registry for available trading strategies.

    Strategy implementations are registered by their strategy_type.
    """

    _strategies: dict[str, type[TradingStrategy]] = {}

    @classmethod
    def register(
        cls,
        strategy_class: type[TradingStrategy],
    ) -> None:
        """Register a trading strategy implementation."""

        if not issubclass(strategy_class, TradingStrategy):
            raise TypeError(
                "Registered strategies must inherit from TradingStrategy."
            )

        strategy_type = getattr(
            strategy_class,
            "strategy_type",
            None,
        )

        if not isinstance(strategy_type, str) or not strategy_type.strip():
            raise ValueError(
                "Strategy must define a non-empty strategy_type."
            )

        if strategy_type in cls._strategies:
            raise ValueError(
                f"Strategy '{strategy_type}' is already registered."
            )

        cls._strategies[strategy_type] = strategy_class

    @classmethod
    def get(
        cls,
        strategy_type: str,
    ) -> TradingStrategy:
        """Retrieve an instance of a registered strategy."""

        strategy_class = cls._strategies.get(strategy_type)

        if strategy_class is None:
            available = ", ".join(cls.supported_strategies())

            raise ValueError(
                f"Unknown strategy type: '{strategy_type}'. "
                f"Available strategies: {available or 'none'}."
            )

        return strategy_class()

    @classmethod
    def supported_strategies(cls) -> tuple[str, ...]:
        """Return all registered strategy types."""

        return tuple(sorted(cls._strategies.keys()))
