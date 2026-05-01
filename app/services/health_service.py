"""Health check service — business logic layer."""
import os
from typing import Dict, str as StrType

_DEFAULT_VERSION: str = "1.0.0"


def get_health_response() -> Dict[str, str]:
    """Return the health check payload.

    The version is sourced from the VERSION environment variable.
    Falls back to '1.0.0' if the variable is not set.
    No database queries are performed and no local state is mutated.
    """
    version: str = os.environ.get("VERSION", _DEFAULT_VERSION)
    return {"status": "ok", "version": version}
