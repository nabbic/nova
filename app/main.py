from fastapi import FastAPI

from app.api.routes.health import router as health_router

app = FastAPI(
    title="Nova API",
    description="Nova Technical Due Diligence Platform API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}


app.include_router(health_router)
