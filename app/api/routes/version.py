import os

from fastapi import APIRouter

from app.models.version import VersionResponse

router = APIRouter()


@router.get(
    "/version",
    response_model=VersionResponse,
    summary="Get application version metadata",
    description=(
        "Returns the current application version, build SHA, and deployment "
        "environment. All values are sourced from environment variables. "
        "No authentication required."
    ),
    tags=["meta"],
    responses={
        200: {
            "description": "Application version metadata",
            "content": {
                "application/json": {
                    "example": {
                        "version": "1.2.3",
                        "build_sha": "abc1234def5678",
                        "environment": "staging",
                    }
                }
            },
        }
    },
)
async def get_version() -> VersionResponse:
    """Return application version metadata from environment variables."""
    return VersionResponse(
        version=os.environ.get("APP_VERSION", "unknown"),
        build_sha=os.environ.get("BUILD_SHA", "unknown"),
        environment=os.environ.get("ENVIRONMENT", "unknown"),
    )
