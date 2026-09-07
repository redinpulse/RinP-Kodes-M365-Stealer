"""
Authentication routes for the Kodes server.
"""
from flask import Blueprint, request, render_template, redirect, url_for, session, current_app
from functools import wraps
import logging
import time
import hmac
from ..utils.security import create_admin_token

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

_login_attempts = {}


def login_required(f):
    """
    Decorator to require authentication for routes.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'authenticated' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Admin login page.
    """
    if request.method == 'POST':
        client_ip = request.remote_addr
        now = time.time()

        if client_ip in _login_attempts:
            attempts, last_attempt = _login_attempts[client_ip]
            if now - last_attempt < 300:
                if attempts >= 5:
                    logger.warning(f"Too many failed login attempts from {client_ip}")
                    return render_template('login.html', error='Too many failed attempts. Please try again later.'), 429

        submitted_secret = request.form.get('access_token')

        app_secret_key = current_app.config['SECRET_KEY']

        if hmac.compare_digest(submitted_secret or '', app_secret_key):
            _login_attempts.pop(client_ip, None)

            session['authenticated'] = True
            session['access_token'] = create_admin_token(app_secret_key)

            logger.info("Admin login successful")
            return redirect(url_for('campaign.dashboard'))
        else:
            if client_ip not in _login_attempts:
                _login_attempts[client_ip] = (1, now)
            else:
                attempts, _ = _login_attempts[client_ip]
                _login_attempts[client_ip] = (attempts + 1, now)

            logger.warning(f"Failed login attempt from {client_ip}")

            time.sleep(0.5)

            return render_template('login.html', error='Invalid access key')

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    """
    Logout the current user by removing session data.
    """
    session.pop('authenticated', None)
    session.pop('access_token', None)
    logger.info("Admin logged out")
    return redirect(url_for('auth.login'))
