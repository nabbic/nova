from fastapi import APIRouter

from app.schemas.version import VersionV2Response

router = APIRouter()


@router.get(
    "/version2",
    response_model=VersionV2Response,
    summary="Get API Version",
    description="Returns the current API version. No authentication required.",
    tags=["meta"],
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
async def get_version2() -> VersionV2Response:
    """Return the current API version for smoke testing and factory validation."""
    return VersionV2Response(version="2.0.0")
