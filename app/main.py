from fastapi import FastAPI

from app.api.routes import version

app = FastAPI(
    title="Nova API",
    description="Nova Technical Due Diligence Platform API",
    version="2.0.0",
)


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}


app.include_router(version.router, prefix="/api")
