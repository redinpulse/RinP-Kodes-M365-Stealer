"""
Campaign service for the Kodes server.

Campaign management: campaign CRUD, target management (including bulk
import), device-campaign linking and deployment config generation.
"""
import logging
import re
import secrets
from datetime import datetime

from ..models import Campaign, Target, DeviceInfo, Log, db
from ..utils.config import (get_server_config, save_server_config,
                            validate_domain)

logger = logging.getLogger(__name__)

_HOSTNAME_RE = re.compile(r'^[A-Za-z0-9._-]+$')

_UNKNOWN_TOKEN_WARNED = set()


class CampaignService:
    """
    Business logic for campaigns and targets.
    """


    @staticmethod
    def create_campaign(name, description=None, target_domain=None,
                        auth_site=None, post_auth_url=None):
        """
        Create a campaign. target_domain is DNS-regex validated; invalid
        values are rejected with a Turkish error message.

        Returns:
            tuple: (Campaign or None, str error message or None)
        """
        name = (name or '').strip()[:100]
        if not name:
            return None, "Campaign name cannot be empty"
        description = (description or '')[:2000]

        if target_domain:
            target_domain = validate_domain(target_domain)
            if not target_domain:
                return None, "Invalid target domain (must be in corp.com format)"

        try:
            campaign = Campaign(
                name=name,
                description=(description or '').strip() or None,
                target_domain=target_domain or None,
                auth_site=(auth_site or '').strip() or None,
                post_auth_url=(post_auth_url or '').strip() or None,
                campaign_token=secrets.token_hex(8),
            )
            db.session.add(campaign)
            db.session.add(Log(hostname='panel',
                               log_message=f"Campaign created: {name}"))
            db.session.commit()
            logger.info("Campaign created: %s (id=%s)", name, campaign.id)
            return campaign, None
        except Exception as e:
            db.session.rollback()
            logger.error("Error creating campaign: %s", e)
            return None, f"Campaign could not be created: {e}"

    @staticmethod
    def update_campaign(campaign_id, **fields):
        """
        Update editable campaign fields; domain is re-validated on change.

        Returns:
            tuple: (bool, str error or None)
        """
        campaign = Campaign.query.get(campaign_id)
        if not campaign:
            return False, "Campaign not found"

        try:
            if 'name' in fields:
                name = (fields['name'] or '').strip()
                if not name:
                    return False, "Campaign name cannot be empty"
                campaign.name = name
            if 'description' in fields:
                campaign.description = (fields['description'] or '').strip() or None
            if 'target_domain' in fields:
                domain = (fields['target_domain'] or '').strip()
                if domain:
                    domain = validate_domain(domain)
                    if not domain:
                        return False, "Invalid target domain"
                campaign.target_domain = domain or None
            if 'auth_site' in fields:
                campaign.auth_site = (fields['auth_site'] or '').strip() or None
            if 'post_auth_url' in fields:
                campaign.post_auth_url = (fields['post_auth_url'] or '').strip() or None

            db.session.add(Log(hostname='panel',
                               log_message=f"Campaign updated: {campaign.name}"))
            db.session.commit()
            return True, None
        except Exception as e:
            db.session.rollback()
            logger.error("Error updating campaign %s: %s", campaign_id, e)
            return False, f"Campaign could not be updated: {e}"

    @staticmethod
    def get_campaign(campaign_id):
        """Fetch a single campaign or None."""
        return Campaign.query.get(campaign_id)

    @staticmethod
    def list_campaigns():
        """All campaigns, newest first."""
        return Campaign.query.order_by(Campaign.created_at.desc()).all()

    @staticmethod
    def set_status(campaign_id, status):
        """
        Set campaign status; stamps launched_at / completed_at.

        Returns:
            tuple: (bool, str error or None)
        """
        campaign = Campaign.query.get(campaign_id)
        if not campaign:
            return False, "Campaign not found"
        if status not in ('draft', 'active', 'completed'):
            return False, "Invalid status"

        try:
            campaign.status = status
            if status == 'active' and not campaign.launched_at:
                campaign.launched_at = datetime.now()
            if status == 'completed':
                campaign.completed_at = datetime.now()
            db.session.add(Log(hostname='panel',
                               log_message=f"Campaign status '{status}': {campaign.name}"))
            db.session.commit()
            return True, None
        except Exception as e:
            db.session.rollback()
            logger.error("Error setting campaign status: %s", e)
            return False, f"Status could not be changed: {e}"

    @staticmethod
    def delete_campaign(campaign_id):
        """
        Delete a campaign. Linked devices are detached first (their FK is
        one-to-many from the device side, cascade does not cover them).

        Returns:
            tuple: (bool, str error or None)
        """
        campaign = Campaign.query.get(campaign_id)
        if not campaign:
            return False, "Campaign not found"

        try:
            name = campaign.name
            DeviceInfo.query.filter_by(campaign_id=campaign_id).update(
                {'campaign_id': None})
            db.session.delete(campaign)
            db.session.add(Log(hostname='panel',
                               log_message=f"Campaign deleted: {name}"))
            db.session.commit()
            return True, None
        except Exception as e:
            db.session.rollback()
            logger.error("Error deleting campaign %s: %s", campaign_id, e)
            return False, f"Campaign could not be deleted: {e}"


    @staticmethod
    def add_target(campaign_id, hostname, expected_upn=None, note=None):
        """
        Add a single target. Upserts on (campaign_id, hostname).

        Returns:
            tuple: (bool, str error or None)
        """
        hostname = (hostname or '').strip()
        if not hostname or not _HOSTNAME_RE.match(hostname):
            return False, "Invalid hostname"

        try:
            target = Target.query.filter_by(campaign_id=campaign_id,
                                            hostname=hostname).first()
            if target:
                target.expected_upn = (expected_upn or '').strip() or None
                target.note = (note or '').strip() or None
                action = "updated"
            else:
                db.session.add(Target(campaign_id=campaign_id, hostname=hostname,
                                      expected_upn=(expected_upn or '').strip() or None,
                                      note=(note or '').strip() or None))
                action = "eklendi"
            db.session.commit()
            return True, f"Target {hostname} {action}"
        except Exception as e:
            db.session.rollback()
            logger.error("Error adding target: %s", e)
            return False, f"Target could not be added: {e}"

    @staticmethod
    def import_targets(campaign_id, text):
        """
        Bulk-import targets from pasted text.

        Line format: hostname[,expected_upn[,note]] — blank lines and lines
        starting with '#' are skipped. Existing (campaign_id, hostname) rows
        are updated, not duplicated.

        Returns:
            tuple: (bool, str summary or error)
        """
        if not Campaign.query.get(campaign_id):
            return False, "Campaign not found"

        added = updated = skipped = 0
        errors = []

        try:
            for line_no, raw in enumerate((text or '').splitlines(), start=1):
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                parts = [p.strip() for p in line.replace('\t', ',').split(',')]
                hostname = parts[0] if parts else ''
                upn = parts[1] if len(parts) > 1 else ''
                note = parts[2] if len(parts) > 2 else ''

                if not hostname or not _HOSTNAME_RE.match(hostname):
                    skipped += 1
                    errors.append(f"line {line_no}: invalid hostname ({line[:40]})")
                    continue

                target = Target.query.filter_by(campaign_id=campaign_id,
                                                hostname=hostname).first()
                if target:
                    target.expected_upn = upn or target.expected_upn
                    target.note = note or target.note
                    updated += 1
                else:
                    db.session.add(Target(campaign_id=campaign_id, hostname=hostname,
                                          expected_upn=upn or None, note=note or None))
                    added += 1

            db.session.add(Log(hostname='panel',
                               log_message=(f"Target import: {added} eklendi, "
                                            f"{updated} updated, {skipped} skipped")))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("Error importing targets: %s", e)
            return False, f"Import failed: {e}"

        summary = f"Import completed: {added} added, {updated} updated, {skipped} skipped"
        if errors:
            summary += " — " + "; ".join(errors[:3])
        return True, summary

    @staticmethod
    def delete_target(campaign_id, target_id):
        """Delete one target row."""
        target = Target.query.filter_by(id=target_id,
                                        campaign_id=campaign_id).first()
        if not target:
            return False, "Target not found"
        try:
            db.session.delete(target)
            db.session.commit()
            return True, None
        except Exception as e:
            db.session.rollback()
            logger.error("Error deleting target: %s", e)
            return False, f"Target silinemedi: {e}"


    @staticmethod
    def apply_campaign_token(device, campaign_token):
        """
        Link a device to the campaign matching campaign_token (from the
        client's c= query parameter). Unknown tokens never raise — the device
        flow must not break — they are logged instead. A matching Target row
        for the hostname is bumped to 'registered'.

        Args:
            device: DeviceInfo instance (already in session)
            campaign_token: token string or None

        Returns:
            bool: True if the device was linked
        """
        if not campaign_token:
            return False

        campaign = Campaign.query.filter_by(campaign_token=campaign_token).first()
        if not campaign:
            if device.hostname not in _UNKNOWN_TOKEN_WARNED:
                _UNKNOWN_TOKEN_WARNED.add(device.hostname)
                logger.warning("Unknown campaign token: %s…",
                               campaign_token[:6])
                db.session.add(Log(hostname=device.hostname,
                                   log_message="Unknown campaign token (not linked)"))
                db.session.commit()
            return False

        if device.campaign_id != campaign.id:
            device.campaign_id = campaign.id
            db.session.add(Log(hostname=device.hostname,
                               log_message=f"Device linked to campaign: {campaign.name}"))
        else:
            return True

        target = Target.query.filter_by(campaign_id=campaign.id,
                                        hostname=device.hostname).first()
        if target and target.status == 'pending':
            target.status = 'registered'

        db.session.commit()
        return True

    @staticmethod
    def link_device(campaign_id, device_id):
        """Manually link a device from the panel."""
        device = DeviceInfo.query.get(device_id)
        campaign = Campaign.query.get(campaign_id)
        if not device or not campaign:
            return False, "Device or campaign not found"
        device.campaign_id = campaign.id
        db.session.commit()
        return True, None

    @staticmethod
    def unlink_device(device_id):
        """Detach a device from its campaign."""
        device = DeviceInfo.query.get(device_id)
        if not device:
            return False, "Device not found"
        device.campaign_id = None
        db.session.commit()
        return True, None


    @staticmethod
    def generate_client_config(campaign, base_url):
        """
        Build the per-campaign client config offered as a download from the
        panel. ngrok_token comes from the global Settings (server.json); if
        unset it stays null and the operator's own client.json value applies.

        Returns:
            dict: client configuration
        """
        server_cfg = get_server_config()
        return {
            'api_url': (base_url or 'http://localhost:9000').rstrip('/'),
            'campaign_token': campaign.campaign_token,
            'auth_site': campaign.auth_site
                         or server_cfg.get('default_auth_site'),
            'post_auth_url': campaign.post_auth_url
                             or server_cfg.get('default_post_auth_url'),
            'ngrok_token': server_cfg.get('ngrok_token'),
            'health_check_interval': 30,
        }


    @staticmethod
    def campaign_stats(campaign):
        """Per-campaign counts for the detail page."""
        return {
            'targets_total': len(campaign.targets),
            'targets_registered': sum(1 for t in campaign.targets
                                      if t.status != 'pending'),
            'devices_total': len(campaign.devices),
            'devices_online': sum(1 for d in campaign.devices if d.is_online),
            'devices_authenticated': sum(1 for d in campaign.devices
                                         if d.access_token and d.refresh_token),
        }

    @staticmethod
    def dashboard_stats():
        """Global stats for the dashboard page."""
        campaigns = Campaign.query.all()
        devices = DeviceInfo.query.all()
        return {
            'campaigns_total': len(campaigns),
            'campaigns_active': sum(1 for c in campaigns if c.status == 'active'),
            'devices_total': len(devices),
            'devices_online': sum(1 for d in devices if d.is_online),
            'devices_authenticated': sum(1 for d in devices
                                         if d.access_token and d.refresh_token),
            'targets_total': Target.query.count(),
        }


    @staticmethod
    def update_global_settings(domain, default_auth_site, default_post_auth_url,
                               ngrok_token=None):
        """
        Persist global settings to server.json (cache is reset on write).

        Returns:
            tuple: (bool, str error or None)
        """
        if domain:
            domain = validate_domain(domain)
            if not domain:
                return False, "Invalid target domain"
        from ..utils.validators import valid_ngrok_token
        if not valid_ngrok_token((ngrok_token or '').strip()):
            return False, "Invalid ngrok token format"
        ok = save_server_config({
            'domain': domain or None,
            'default_auth_site': (default_auth_site or '').strip() or None,
            'default_post_auth_url': (default_post_auth_url or '').strip() or None,
            'ngrok_token': (ngrok_token or '').strip() or None,
        })
        if not ok:
            return False, "server.json could not be written"
        db.session.add(Log(hostname='panel', log_message="Global settings updated"))
        db.session.commit()
        return True, None
