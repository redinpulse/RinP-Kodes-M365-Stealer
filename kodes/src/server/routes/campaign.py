"""
Campaign panel routes for the Kodes server.

Campaign management: campaigns, targets (including bulk import),
device-campaign linking, deployment config download, global settings and
log views. All routes follow the form-POST + flash + redirect pattern.
"""
import json
import logging

from flask import (Blueprint, Response, flash, redirect, render_template,
                   request, url_for)
from sqlalchemy import or_

from ..models import DeviceInfo, Log
from ..services.campaign import CampaignService
from ..utils.config import get_server_config
from .auth import login_required

logger = logging.getLogger(__name__)

campaign_bp = Blueprint('campaign', __name__)


def _base_url():
    """
    Server address used in deployment URLs: can be overridden with ?base=,
    defaults to the current request's host. The override is rendered back
    into panel JS contexts, so it must be a strict http(s)://host[:port]
    value — anything else is ignored.
    """
    import re as _re
    base = (request.args.get('base') or '').strip()
    if base and _re.match(r'^https?://[A-Za-z0-9.-]+(:\d{1,5})?$', base):
        return base.rstrip('/')
    return request.host_url.rstrip('/')


@campaign_bp.route('/dashboard')
@login_required
def dashboard():
    """
    Panel home: stat cards + device status + recent events.
    """
    from ..models import DeviceInfo
    stats = CampaignService.dashboard_stats()
    recent_logs = Log.query.order_by(Log.timestamp.desc()).limit(20).all()
    recent_campaigns = CampaignService.list_campaigns()[:5]
    devices = DeviceInfo.query.all()
    devices.sort(key=lambda d: (not d.is_online, not bool(d.refresh_token)))
    return render_template('dashboard.html', stats=stats,
                           recent_logs=recent_logs,
                           recent_campaigns=recent_campaigns,
                           devices=devices[:8])



@campaign_bp.route('/campaigns')
@login_required
def list_campaigns():
    """
    Campaign list.
    """
    campaigns = CampaignService.list_campaigns()
    return render_template('campaigns.html', campaigns=campaigns)


@campaign_bp.route('/campaigns/create', methods=['POST'])
@login_required
def create_campaign():
    """
    Create a new campaign.
    """
    campaign, error = CampaignService.create_campaign(
        name=request.form.get('name'),
        description=request.form.get('description'),
        target_domain=request.form.get('target_domain'),
        auth_site=request.form.get('auth_site'),
        post_auth_url=request.form.get('post_auth_url'),
    )
    if error:
        flash(error, 'error')
        return redirect(url_for('campaign.list_campaigns'))
    flash(f"Campaign created: {campaign.name}", 'success')
    return redirect(url_for('campaign.campaign_detail',
                            campaign_id=campaign.id))


@campaign_bp.route('/campaigns/<int:campaign_id>')
@login_required
def campaign_detail(campaign_id):
    """
    Campaign detail: info/target/device/deployment cards.
    """
    campaign = CampaignService.get_campaign(campaign_id)
    if not campaign:
        flash('Campaign not found', 'error')
        return redirect(url_for('campaign.list_campaigns'))

    stats = CampaignService.campaign_stats(campaign)
    linked_ids = [d.id for d in campaign.devices]
    if linked_ids:
        other_devices = DeviceInfo.query.filter(
            ~DeviceInfo.id.in_(linked_ids)).order_by(DeviceInfo.hostname).all()
    else:
        other_devices = DeviceInfo.query.order_by(DeviceInfo.hostname).all()

    return render_template('campaign_detail.html', campaign=campaign,
                           stats=stats, other_devices=other_devices,
                           base_url=_base_url(),
                           server_cfg=get_server_config())


@campaign_bp.route('/campaigns/<int:campaign_id>/update', methods=['POST'])
@login_required
def update_campaign(campaign_id):
    """
    Update campaign information.
    """
    ok, error = CampaignService.update_campaign(
        campaign_id,
        name=request.form.get('name'),
        description=request.form.get('description'),
        target_domain=request.form.get('target_domain'),
        auth_site=request.form.get('auth_site'),
        post_auth_url=request.form.get('post_auth_url'),
    )
    flash('Campaign updated' if ok else error,
          'success' if ok else 'error')
    return redirect(url_for('campaign.campaign_detail',
                            campaign_id=campaign_id))


@campaign_bp.route('/campaigns/<int:campaign_id>/launch', methods=['POST'])
@login_required
def launch_campaign(campaign_id):
    """
    Activate the campaign (stamps launched_at).
    """
    ok, error = CampaignService.set_status(campaign_id, 'active')
    flash('Campaign activated' if ok else error,
          'success' if ok else 'error')
    return redirect(url_for('campaign.campaign_detail',
                            campaign_id=campaign_id))


@campaign_bp.route('/campaigns/<int:campaign_id>/complete', methods=['POST'])
@login_required
def complete_campaign(campaign_id):
    """
    Mark the campaign completed (stamps completed_at).
    """
    ok, error = CampaignService.set_status(campaign_id, 'completed')
    flash('Campaign marked as completed' if ok else error,
          'success' if ok else 'error')
    return redirect(url_for('campaign.campaign_detail',
                            campaign_id=campaign_id))


@campaign_bp.route('/campaigns/<int:campaign_id>/delete', methods=['POST'])
@login_required
def delete_campaign(campaign_id):
    """
    Delete the campaign (linked devices are unlinked first).
    """
    ok, error = CampaignService.delete_campaign(campaign_id)
    flash('Campaign deleted' if ok else error,
          'success' if ok else 'error')
    return redirect(url_for('campaign.list_campaigns'))



@campaign_bp.route('/campaigns/<int:campaign_id>/targets/add', methods=['POST'])
@login_required
def add_target(campaign_id):
    """
    Add a single target (updates if the hostname exists).
    """
    ok, message = CampaignService.add_target(
        campaign_id,
        hostname=request.form.get('hostname'),
        expected_upn=request.form.get('expected_upn'),
        note=request.form.get('note'),
    )
    flash(message if message else ('Target added' if ok else 'Target could not be added'),
          'success' if ok else 'error')
    return redirect(url_for('campaign.campaign_detail',
                            campaign_id=campaign_id))


@campaign_bp.route('/campaigns/<int:campaign_id>/targets/import', methods=['POST'])
@login_required
def import_targets(campaign_id):
    """
    Bulk target import: hostname[,upn[,note]] per line.
    """
    ok, summary = CampaignService.import_targets(
        campaign_id, request.form.get('targets_text'))
    flash(summary, 'success' if ok else 'error')
    return redirect(url_for('campaign.campaign_detail',
                            campaign_id=campaign_id))


@campaign_bp.route('/campaigns/<int:campaign_id>/targets/<int:target_id>/delete',
                   methods=['POST'])
@login_required
def delete_target(campaign_id, target_id):
    """
    Delete a target record.
    """
    ok, error = CampaignService.delete_target(campaign_id, target_id)
    flash('Target deleted' if ok else error,
          'success' if ok else 'error')
    return redirect(url_for('campaign.campaign_detail',
                            campaign_id=campaign_id))



@campaign_bp.route('/campaigns/<int:campaign_id>/devices/link', methods=['POST'])
@login_required
def link_device(campaign_id):
    """
    Link a device to a campaign manually from the panel.
    """
    ok, error = CampaignService.link_device(
        campaign_id, request.form.get('device_id', type=int))
    flash('Device linked' if ok else error,
          'success' if ok else 'error')
    return redirect(url_for('campaign.campaign_detail',
                            campaign_id=campaign_id))


@campaign_bp.route('/campaigns/<int:campaign_id>/devices/unlink', methods=['POST'])
@login_required
def unlink_device(campaign_id):
    """
    Unlink a device from its campaign.
    """
    ok, error = CampaignService.unlink_device(
        request.form.get('device_id', type=int))
    flash('Device unlinked' if ok else error,
          'success' if ok else 'error')
    return redirect(url_for('campaign.campaign_detail',
                            campaign_id=campaign_id))



@campaign_bp.route('/campaigns/<int:campaign_id>/client-config')
@login_required
def client_config(campaign_id):
    """
    Download the campaign-specific client.json (attachment). ngrok_token is
    deliberately EXCLUDED — the per-target secret stays in the operator's config.
    """
    campaign = CampaignService.get_campaign(campaign_id)
    if not campaign:
        flash('Campaign not found', 'error')
        return redirect(url_for('campaign.list_campaigns'))

    payload = CampaignService.generate_client_config(campaign, _base_url())
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype='application/json',
        headers={'Content-Disposition':
                 f'attachment;filename=client_config_{campaign.id}.json'}
    )



@campaign_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """
    server.json management: global target domain + campaign defaults.
    The config cache is reset after saving (inside save_server_config).
    """
    if request.method == 'POST':
        ok, error = CampaignService.update_global_settings(
            domain=request.form.get('domain'),
            default_auth_site=request.form.get('default_auth_site'),
            default_post_auth_url=request.form.get('default_post_auth_url'),
            ngrok_token=request.form.get('ngrok_token'),
        )
        flash('Settings saved' if ok else error,
              'success' if ok else 'error')
        return redirect(url_for('campaign.settings'))
    return render_template('settings.html', config=get_server_config())



@campaign_bp.route('/logs')
@login_required
def logs():
    """
    Log table: paginated (50/page) + ?q= filter (hostname or message).
    """
    page = request.args.get('page', 1, type=int)
    q = (request.args.get('q') or '').strip()

    query = Log.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Log.hostname.like(like),
                                 Log.log_message.like(like)))

    pagination = query.order_by(Log.timestamp.desc()).paginate(
        page=page, per_page=50, error_out=False)
    return render_template('logs.html', logs=pagination.items,
                           pagination=pagination, q=q)
