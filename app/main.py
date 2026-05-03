from fastapi import FastAPI

from app.api.routes.ping import router as ping_router

app = FastAPI(
    title="Nova API",
    description="Nova Technical Due Diligence Platform API",
    version="0.1.0",
)


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}


app.include_router(ping_router, prefix="/api")
