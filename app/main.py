from fastapi import FastAPI

from app.api.routes import version

app = FastAPI(
    title="Nova API",
    version="1.0.0",
    description="Nova Technical Due Diligence Platform API",
)


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}


app.include_router(version.router, prefix="/api")
