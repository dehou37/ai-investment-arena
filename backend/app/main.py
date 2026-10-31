from fastapi import FastAPI

from app.api.routes.market_data import router as market_data_router


app = FastAPI(
    title="AI Investment Arena",
    description="AI-powered stock investment competition",
    version="0.1.0",
)

app.include_router(market_data_router)


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