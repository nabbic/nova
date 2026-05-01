"""Health check route handler."""
import logging

from flask import Blueprint, Response, jsonify

from app.services.health_service import get_health_response

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__, url_prefix="/api")


@health_bp.route("/health", methods=["GET"])
def health_check() -> Response:
    """Public health check endpoint. No authentication required."""
    logger.info("Health check requested")
    payload = get_health_response()
    return jsonify(payload), 200
