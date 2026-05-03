from pydantic import BaseModel, Field


class VersionResponse(BaseModel):
    """Application version metadata response schema."""

    version: str = Field(
        description=(
            "Application version string, sourced from APP_VERSION env var. "
            "Defaults to 'unknown' if not set."
        ),
    )
    build_sha: str = Field(
        description=(
            "Git commit SHA of the current build, sourced from BUILD_SHA env var. "
            "Defaults to 'unknown' if not set."
        ),
    )
    environment: str = Field(
        description=(
            "Deployment environment name, sourced from ENVIRONMENT env var. "
            "Defaults to 'unknown' if not set."
        ),
    )
