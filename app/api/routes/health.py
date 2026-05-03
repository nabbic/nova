from fastapi import APIRouter

from app.schemas.version import VersionV2Response

router = APIRouter()


@router.get(
    "/api/version2",
    response_model=VersionV2Response,
    summary="Get API version (v2)",
    description="Returns the current API version. Public endpoint with no authentication required. Used as a factory smoke test.",
    tags=["health"],
    responses={
        200: {
            "description": "Successful response with API version",
            "content": {
                "application/json": {
                    "example": {"version": "2.0.0"}
                }
            },
        }
    },
)
async def get_version_v2() -> VersionV2Response:
    """Return the API version for smoke testing."""
    return VersionV2Response(version="2.0.0")
