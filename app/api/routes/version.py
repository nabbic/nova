from fastapi import APIRouter

router = APIRouter()


@router.get("/api/version", tags=["meta"])
async def get_version() -> dict:
    return {"version": "1.0"}


@router.get("/api/version-v2", tags=["meta"])
async def get_version_v2() -> dict:
    return {"version": "2.0"}
