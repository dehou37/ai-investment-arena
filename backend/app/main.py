from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.market_data import router as market_data_router
from app.api.routes.competition import router as competitions_router

app = FastAPI(
    title="AI Investment Arena",
    description="AI-powered stock investment competition",
    version="0.1.0",
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

