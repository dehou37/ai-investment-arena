from fastapi import FastAPI

app = FastAPI(
    title="AI Investment Arena",
    description="AI-powered stock investment competition",
    version="0.1.0"
)


@app.get("/")
async def root():
    return {
        "application": "AI Investment Arena",
        "status": "running",
        "version": "0.1.0"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }