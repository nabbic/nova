from fastapi import APIRouter

from app.schemas.version import VersionResponse

router = APIRouter()


@router.get(
    "/api/version2",
    response_model=VersionResponse,
    summary="Get API version v2",
    description="Returns the current API version string. No authentication required.",
    tags=["meta"],
)
async def get_version2() -> VersionResponse:
    return VersionResponse(version="2.0.0")
