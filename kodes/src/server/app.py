"""
Main application module for the Kodes server.
"""
import os
import logging
from flask import Flask
from .models import db
from .routes.api import api_bp
from .routes.auth import auth_bp
from .routes.campaign import campaign_bp
from .routes.web import web_bp
from .utils.security import get_or_create_secret_key
from ..utils.config import get_database_uri

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("kodes_server.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def _migrate_sqlite_columns(app):
    """
    create_all() does not add columns to existing tables — missing columns
    are added idempotently via ALTER. SQLite ALTER cannot add FK constraints;
    campaign_id stays declarative (SQLite FK enforcement is off by default;
    fresh installs get the real constraint from create_all).
    """
    from sqlalchemy import inspect, text
    with app.app_context():
        inspector = inspect(db.engine)
        if inspector.has_table('device_info'):
            cols = {c['name'] for c in inspector.get_columns('device_info')}
            if 'campaign_id' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text('ALTER TABLE device_info ADD COLUMN campaign_id INTEGER'))
                logger.info("Added campaign_id column to device_info")
            if 'service_tokens' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text('ALTER TABLE device_info ADD COLUMN service_tokens TEXT'))
                logger.info("Added service_tokens column to device_info")



def create_app(test_config=None, config_path=None):
    """
    Create and configure the Flask application.

    Args:
        test_config: Test configuration dictionary
        config_path: Path to configuration file

    Returns:
        Flask: The configured Flask application
    """
    app = Flask(__name__,
                template_folder=os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'templates')))

    app.config.from_mapping(
        SECRET_KEY=get_or_create_secret_key(),
        SQLALCHEMY_DATABASE_URI=get_database_uri(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict',
    )

    if config_path and os.path.exists(config_path):
        app.config.from_pyfile(config_path)

    if test_config:
        app.config.update(test_config)
    
    db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    
    db.init_app(app)
    with app.app_context():
        db.create_all()

    @app.route('/healthz')
    def healthz():
        return 'ok'

    @app.after_request
    def set_security_headers(resp):
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resp.headers.setdefault('X-Frame-Options', 'DENY')
        resp.headers.setdefault('Referrer-Policy', 'no-referrer')
        return resp

    try:
        _migrate_sqlite_columns(app)
    except Exception as e:
        logger.error(f"SQLite column migration failed: {e}")

    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(web_bp)
    app.register_blueprint(campaign_bp)

    return app


def run_server(host='0.0.0.0', port=9000, debug=False):
    """
    Run the Kodes server.

    Args:
        host: Host address to bind to
        port: Port to listen on
        debug: Whether to enable debug mode
    """
    app = create_app()
    access_token = app.config['SECRET_KEY']
    logger.info(f"Admin access token: {access_token}")
    print(f"\n=== KODES ADMIN ACCESS TOKEN: {access_token} ===\n", flush=True)
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    run_server(debug=True)
