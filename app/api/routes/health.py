import os
import logging
from flask import Blueprint, jsonify, Response

logger = logging.getLogger(__name__)

health_bp = Blueprint('health', __name__)

FALLBACK_VERSION = '1.0.0'


def _get_version() -> str:
    """Return the application version from environment or fallback."""
    return os.environ.get('APP_VERSION', FALLBACK_VERSION)


@health_bp.route('/api/health', methods=['GET'])
def health_check() -> Response:
    """Public health check endpoint.

    Returns HTTP 200 with a static JSON body indicating service health.
    No authentication is required. Explicitly registered without auth middleware.
    Does not expose internal state, environment variables, or tenant data.
    """
    logger.info('Health check requested')
    payload = {
        'status': 'ok',
        'version': _get_version(),
    }
    return jsonify(payload), 200
