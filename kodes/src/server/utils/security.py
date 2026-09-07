"""
Security utilities for the Kodes server.
"""
import jwt
import secrets
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
import os
import logging

logger = logging.getLogger(__name__)

_ENCRYPTION_KEY = None

def get_or_create_secret_key():
    """
    Get or create a persistent secret key for session management (configurable via KODES_SECRET_KEY_PATH).

    Returns:
        str: A hexadecimal string secret key
    """
    key_file = os.environ.get('KODES_SECRET_KEY_PATH',
        os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config', 'secret.key'))
    os.makedirs(os.path.dirname(key_file), exist_ok=True)

    if os.path.exists(key_file):
        with open(key_file, 'r') as f:
            return f.read().strip()
    else:
        key = secrets.token_hex(32)
        with open(key_file, 'w') as f:
            f.write(key)
        os.chmod(key_file, 0o600)
        return key


def get_encryption_key():
    """
    Get or create the encryption key for token storage (configurable via KODES_CRYPTO_KEY_PATH).

    Returns:
        bytes: The encryption key
    """
    global _ENCRYPTION_KEY

    if _ENCRYPTION_KEY is None:
        key_file = os.environ.get('KODES_CRYPTO_KEY_PATH',
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config', 'crypto.key'))

        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                _ENCRYPTION_KEY = f.read()
        else:
            _ENCRYPTION_KEY = Fernet.generate_key()

            os.makedirs(os.path.dirname(key_file), exist_ok=True)
            with open(key_file, 'wb') as f:
                f.write(_ENCRYPTION_KEY)
            os.chmod(key_file, 0o600)

            logger.info("Generated new encryption key at %s", key_file)

    return _ENCRYPTION_KEY

def encrypt_token(token):
    """
    Encrypt a sensitive token for secure storage.
    
    Args:
        token: The token to encrypt
        
    Returns:
        str: The encrypted token
    """
    if not token:
        return None
        
    try:
        key = get_encryption_key()
        f = Fernet(key)
        return f.encrypt(token.encode()).decode()
    except Exception as e:
        logger.error(f"Error encrypting token: {e}")
        return None

def decrypt_token(encrypted_token):
    """
    Decrypt a token for use.
    
    Args:
        encrypted_token: The encrypted token
        
    Returns:
        str: The decrypted token
    """
    if not encrypted_token:
        return None
        
    try:
        key = get_encryption_key()
        f = Fernet(key)
        return f.decrypt(encrypted_token.encode()).decode()
    except Exception as e:
        logger.error(f"Error decrypting token: {e}")
        return None

def parse_jwt_token(token):
    """
    Parse a JWT token to extract its payload.
    
    Args:
        token: The JWT token
        
    Returns:
        dict: The token payload with additional processed fields
    """
    try:
        decoded_payload = jwt.decode(token, options={"verify_signature": False})
        
        processed_payload = {**decoded_payload}
        
        if 'scp' in decoded_payload:
            if isinstance(decoded_payload['scp'], str):
                processed_payload['scopes'] = decoded_payload['scp'].split()
            elif isinstance(decoded_payload['scp'], list):
                processed_payload['scopes'] = decoded_payload['scp']
            
            admin_scopes = ['Directory.ReadWrite.All', 'User.ReadWrite.All', 'Group.ReadWrite.All']
            processed_payload['has_admin_scopes'] = any(scope in processed_payload.get('scopes', []) for scope in admin_scopes)
        
        if 'roles' in decoded_payload:
            processed_payload['has_admin_role'] = any('Admin' in role for role in decoded_payload['roles'])
        
        processed_payload['token_type'] = 'Access Token'
        if decoded_payload.get('aud') == 'https://graph.microsoft.com/':
            processed_payload['token_service'] = 'Microsoft Graph'
        elif decoded_payload.get('aud') == 'https://api.spaces.skype.com/':
            processed_payload['token_service'] = 'Microsoft Teams'
        
        if 'exp' in decoded_payload:
            try:
                expiration = datetime.fromtimestamp(decoded_payload['exp'])
                processed_payload['expiration_str'] = expiration.strftime('%Y-%m-%d %H:%M:%S')
                now = datetime.now()
                processed_payload['expires_in_minutes'] = int((expiration - now).total_seconds() / 60)
                processed_payload['is_expired'] = now > expiration
            except:
                pass
                
        return processed_payload
    except Exception as e:
        logger.error(f"Error decoding JWT token: {e}")
        return {}

def create_admin_token(secret_key, expiry_hours=24):
    """
    Create an admin session token.
    
    Args:
        secret_key: The server's secret key
        expiry_hours: Token expiry in hours
        
    Returns:
        str: The signed JWT token
    """
    payload = {
        'exp': datetime.utcnow() + timedelta(hours=expiry_hours),
        'iat': datetime.utcnow(),
        'sub': 'admin'
    }
    token = jwt.encode(payload, secret_key, algorithm='HS256')
    return token