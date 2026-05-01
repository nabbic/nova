from fastapi import FastAPI

from app.api.routes import version

app = FastAPI(
    title="Nova",
    description="Nova multi-tenant SaaS API",
    version="0.1.0",
)

app.include_router(version.router)
