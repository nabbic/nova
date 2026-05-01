import os
import logging
from flask import Flask
from app.api.routes.health import health_bp

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Application factory."""
    app = Flask(__name__)

    # Register blueprints
    app.register_blueprint(health_bp)

    logger.info('Nova application started')
    return app


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8080'))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    application = create_app()
    application.run(host='0.0.0.0', port=port, debug=debug)
