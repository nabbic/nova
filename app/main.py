from fastapi import FastAPI

from app.api.routes import version

app = FastAPI(title="Nova API", version="2.0")

app.include_router(version.router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}
