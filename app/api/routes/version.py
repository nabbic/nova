from fastapi import APIRouter

from app.schemas.version import VersionResponse

router = APIRouter()


@router.get(
    "/version2",
    response_model=VersionResponse,
    summary="Get API Version",
    description="Returns the current API version. No authentication required.",
    tags=["Meta"],
    responses={
        200: {
            "description": "Successful response with API version",
            "content": {"application/json": {"example": {"version": "2.0.0"}}},
        }
    },
)
async def get_version() -> VersionResponse:
    """Return the current API version."""
    return VersionResponse(version="2.0.0")
