"""
Configuration utilities for Kodes.
"""
import os
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    'api_url': 'http://localhost:9000',
    'ngrok_token': None,
    'log_level': 'INFO',
    'auth_site': 'https://microsoft.com/devicelogin',
    'post_auth_url': None,
    'campaign_token': None,
    'health_check_interval': 30
}


def get_config_path():
    """
    Get the path to the default configuration file.
    
    Returns:
        str: Path to the configuration file
    """
    central_config = os.path.abspath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config', 'client.json'))
    
    if os.path.exists(central_config):
        return central_config
    
    if sys.platform.startswith('win'):
        config_dir = os.path.join(os.environ.get('APPDATA', ''), 'Kodes')
    else:
        config_dir = os.path.join(os.path.expanduser('~'), '.config', 'kodes')
        
    os.makedirs(config_dir, exist_ok=True)
    
    return os.path.join(config_dir, 'config.json')


def load_config(config_path=None):
    """
    Load configuration from a JSON file.
    
    Args:
        config_path: Path to the config file, or None to use default
        
    Returns:
        dict: Configuration values
    """
    if config_path is None:
        config_path = get_config_path()
        
    config = DEFAULT_CONFIG.copy()
    
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                user_config = json.load(f)
                config.update(user_config)
                logger.info(f"Configuration loaded from {config_path}")
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        
    return config



def get_project_root():
    """
    Get the project root directory (repo root, parent of kodes/).

    Returns:
        Path: Project root path (repo root)
    """
    current_file = Path(__file__).resolve()
    config_py_dir = current_file.parent
    src_dir = config_py_dir.parent
    kodes_dir = src_dir.parent
    project_root = kodes_dir.parent
    return project_root


def get_db_path():
    """
    Get the path to the database file (configurable via KODES_DB_PATH env var).

    Returns:
        str: Absolute path to database file
    """
    env_path = os.environ.get('KODES_DB_PATH')
    if env_path:
        db_path = Path(env_path)
    else:
        project_root = get_project_root()
        db_path = project_root / 'database' / 'kodes.db'
    os.makedirs(db_path.parent, exist_ok=True)
    return str(db_path.absolute())


def get_database_uri():
    """
    Get the SQLAlchemy database URI for Kodes database.

    Returns:
        str: SQLite URI
    """
    db_path = get_db_path()
    return f'sqlite:///{db_path}'
