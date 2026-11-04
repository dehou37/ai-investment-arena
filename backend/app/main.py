
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes.market_data import router as market_data_router
from app.api.routes.competition import router as competitions_router
from app.api.routes.orders import router as orders_router
from app.api.routes import portfolio
from app.api.routes import snapshots

from app.services.llm.ollama_client import OllamaClient
from app.services.market_data.alpaca import AlpacaMarketDataClient
from app.services.brokerage.execution_service import execute_queued_orders

from app.services.trading.decision_service import DecisionOrchestrator
from app.services.trading.daily_trading_service import (
    DailyTradingCoordinator,
)
from app.services.trading.recovery_service import (
    DailyTradingRecoveryService,
)
from app.services.trading.autonomous_trading_service import (
    AutonomousTradingService,
)
from app.services.trading.market_session_monitor_service import (
    MarketSessionMonitorService,
)
from app.services.trading.scheduler_service import (
    DailyTradingSchedulerService,
)
from app.api.routes.activity import router as activity_router
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application resources and background trading services.
    """

    ollama_client = OllamaClient()
    alpaca_client = None

    monitor_task = None
    scheduler_task = None

    try:
        # One shared market-data client for the application lifetime.
        alpaca_client = AlpacaMarketDataClient()

        decision_orchestrator = DecisionOrchestrator(
            ollama_client=ollama_client
        )

        daily_trading_coordinator = DailyTradingCoordinator(
            decision_orchestrator=decision_orchestrator
        )

        daily_trading_recovery_service = DailyTradingRecoveryService(
            coordinator=daily_trading_coordinator,
            execute_historical_orders_fn=execute_queued_orders,
        )

        autonomous_trading_service = AutonomousTradingService(
            client=alpaca_client,
            recovery_service=daily_trading_recovery_service,
        )

        market_session_monitor_service = MarketSessionMonitorService()

        daily_trading_scheduler_service = DailyTradingSchedulerService(
            autonomous_service=autonomous_trading_service,
            interval_seconds=60,
        )

        # Expose shared services through application state.
        app.state.ollama_client = ollama_client
        app.state.alpaca_client = alpaca_client
        app.state.decision_orchestrator = decision_orchestrator
        app.state.daily_trading_coordinator = daily_trading_coordinator
        app.state.daily_trading_recovery_service = (
            daily_trading_recovery_service
        )
        app.state.autonomous_trading_service = (
            autonomous_trading_service
        )
        app.state.market_session_monitor_service = (
            market_session_monitor_service
        )
        app.state.daily_trading_scheduler_service = (
            daily_trading_scheduler_service
        )

        # Start the market-session heartbeat monitor independently.
        monitor_task = asyncio.create_task(
            market_session_monitor_service.run_forever(),
            name="market-session-monitor",
        )

        logger.info("Market session monitor background task started.")

        # Startup recovery uses the complete autonomous workflow.
        try:
            recovery_result = await asyncio.to_thread(
                daily_trading_scheduler_service.run_once
            )

            logger.info(
                "Startup autonomous trading check completed: %s",
                recovery_result,
            )

        except Exception:
            logger.exception(
                "Startup autonomous trading check encountered an error."
            )

        # Start periodic autonomous trading checks.
        scheduler_task = asyncio.create_task(
            daily_trading_scheduler_service.run_forever(),
            name="daily-trading-scheduler",
        )

        logger.info("Daily trading scheduler background task started.")

        yield

    finally:
        # Stop the daily trading scheduler.
        if scheduler_task is not None:
            scheduler_task.cancel()

            try:
                await scheduler_task
            except asyncio.CancelledError:
                logger.info(
                    "Daily trading scheduler background task stopped."
                )

        # Stop the independent market-session monitor.
        if monitor_task is not None:
            monitor_task.cancel()

            try:
                await monitor_task
            except asyncio.CancelledError:
                logger.info(
                    "Market session monitor background task stopped."
                )

        # Close shared external clients.
        if alpaca_client is not None:
            alpaca_client.close()

        ollama_client.close()


app = FastAPI(
    title="AI Investment Arena",
    description="AI-powered stock investment competition",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market_data_router)
app.include_router(competitions_router)
app.include_router(orders_router)
app.include_router(portfolio.router)
app.include_router(snapshots.router)
app.include_router(activity_router)


@app.get("/")
async def root():
    return {
        "application": "AI Investment Arena",
        "status": "running",
        "version": "0.1.0",
    }


@app.get("/health")
async def health():
    """Liveness probe: the application process is responsive."""
    return {"status": "healthy"}


@app.get("/ready")
async def readiness():
    """Readiness probe: required database access is available."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Readiness check failed.")
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "dependencies": {"database": "unavailable"},
            },
        ) from exc

    return {
        "status": "ready",
        "dependencies": {"database": "healthy"},
    }
