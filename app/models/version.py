from pydantic import BaseModel, Field


class VersionResponse(BaseModel):
    """Application version metadata response schema."""

    version: str = Field(
        description=(
            "Application version string, sourced from APP_VERSION env var. "
            "Defaults to 'unknown' if not set."
        ),
        example="1.2.3",
    )
    build_sha: str = Field(
        description=(
            "Git commit SHA of the current build, sourced from BUILD_SHA env var. "
            "Defaults to 'unknown' if not set."
        ),
        example="abc1234def5678",
    )
    environment: str = Field(
        description=(
            "Deployment environment name, sourced from ENVIRONMENT env var. "
            "Defaults to 'unknown' if not set."
        ),
        example="staging",
    )
