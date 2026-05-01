"""Application entry point."""
import logging
import sys

from flask import Flask

from app.api.routes.health import health_bp


def create_app() -> Flask:
    """Create and configure the Flask application."""
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    app = Flask(__name__)

    app.register_blueprint(health_bp)

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="0.0.0.0", port=8080)
