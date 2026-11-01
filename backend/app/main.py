
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.market_data import router as market_data_router
from app.api.routes.competition import router as competitions_router
from app.api.routes.orders import router as orders_router
from app.api.routes import portfolio
from app.api.routes import snapshots

from app.services.llm.ollama_client import OllamaClient
from app.services.trading.decision_service import DecisionOrchestrator
from app.services.trading.daily_trading_service import (
    DailyTradingCoordinator,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application-wide resources.
    """

    ollama_client = OllamaClient()

    try:
        decision_orchestrator = DecisionOrchestrator(
            ollama_client=ollama_client
        )

        daily_trading_coordinator = DailyTradingCoordinator(
            decision_orchestrator=decision_orchestrator
        )

        app.state.ollama_client = ollama_client
        app.state.decision_orchestrator = decision_orchestrator
        app.state.daily_trading_coordinator = daily_trading_coordinator

        yield

    finally:
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


@app.get("/")
async def root():
    return {
        "application": "AI Investment Arena",
        "status": "running",
        "version": "0.1.0",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
