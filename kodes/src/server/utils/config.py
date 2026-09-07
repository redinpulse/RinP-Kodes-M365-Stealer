"""
Server configuration utilities for Kodes.

Loads server.json so operator-controlled values (target tenant domain, etc.)
stay in configuration instead of hardcoded in source.
"""
import json
import logging
import os
import re
import threading

logger = logging.getLogger(__name__)

_SERVER_CONFIG = None
_CONFIG_LOCK = threading.Lock()

_DOMAIN_RE = re.compile(
    r'^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
    r'(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$'
)

DEFAULT_SERVER_CONFIG = {
    'domain': None,
    'default_auth_site': 'https://microsoft.com/devicelogin',
    'default_post_auth_url': None,
    'ngrok_token': None,
}


def get_server_config():
    """
    Load server.json (path overridable via KODES_SERVER_CONFIG), cached.

    Returns:
        dict: Merged server configuration
    """
    global _SERVER_CONFIG
    with _CONFIG_LOCK:
        if _SERVER_CONFIG is not None:
            return _SERVER_CONFIG

        config = DEFAULT_SERVER_CONFIG.copy()
        config_path = os.environ.get(
            'KODES_SERVER_CONFIG',
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))), 'config', 'server.json'))

        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config.update(json.load(f))
                logger.info("Server configuration loaded from %s", config_path)
            else:
                logger.warning("Server configuration not found at %s", config_path)
        except Exception as e:
            logger.error("Error loading server configuration from %s: %s",
                         config_path, e)

        _SERVER_CONFIG = config
        return _SERVER_CONFIG


def validate_domain(domain):
    """
    Validate a tenant domain against the DNS-name regex.

    Returns:
        str or None: Normalized domain, or None if invalid/empty
    """
    if not domain or not isinstance(domain, str):
        return None
    domain = domain.strip()
    return domain if _DOMAIN_RE.match(domain) else None


def reset_server_config_cache():
    """
    Reset the cached server configuration so the next read reloads server.json.
    Must be called after writing the file (Settings page), otherwise edits
    appear to do nothing.
    """
    global _SERVER_CONFIG
    with _CONFIG_LOCK:
        _SERVER_CONFIG = None


def save_server_config(updates):
    """
    Read-modify-write server.json, then reset the loader cache.

    Args:
        updates: dict of config keys to set (only known keys are honoured)

    Returns:
        bool: True on success
    """
    import json

    config_path = os.environ.get(
        'KODES_SERVER_CONFIG',
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(__file__)))), 'config', 'server.json'))

    config = dict(get_server_config())
    config.update({k: v for k, v in updates.items() if k in DEFAULT_SERVER_CONFIG})

    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)
            f.write('\n')
        reset_server_config_cache()
        logger.info("Server configuration saved to %s", config_path)
        return True
    except Exception as e:
        logger.error("Error saving server configuration to %s: %s", config_path, e)
        return False


def get_target_domain():
    """
    Return the configured target tenant domain, or None if missing/invalid.

    Returns:
        str or None: Validated domain like "example.com"
    """
    domain = get_server_config().get('domain')
    validated = validate_domain(domain)
    if not validated:
        logger.error('Target domain not configured or invalid — set "domain" in server.json')
        return None
    return validated


def get_target_domain_for(hostname, db_session=None):
    """
    Campaign-aware domain resolution: the device's campaign target_domain wins,
    otherwise falls back to the global server.json domain. Both values pass
    the DNS regex — a hand-edited DB row must never reach a PowerShell command.

    Args:
        hostname: Device hostname to resolve the campaign for
        db_session: Optional explicit session (required from background
                    threads that run without app context)

    Returns:
        str or None: Validated domain
    """
    try:
        from .. import models
        session = db_session
        if session is None:
            from ..models import db
            session = db.session
        device = session.query(models.DeviceInfo).filter_by(hostname=hostname).first()
        if device and device.campaign and device.campaign.target_domain:
            domain = validate_domain(device.campaign.target_domain)
            if domain:
                return domain
    except Exception as e:
        logger.warning("Campaign domain lookup failed for %s: %s", hostname, e)
    return get_target_domain()
