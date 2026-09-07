"""
Device management service for the Kodes server.
"""
import logging
from datetime import datetime
from ..models import DeviceInfo, Log, db

logger = logging.getLogger(__name__)


class DeviceService:
    """
    Service for device-related operations.
    """
    
    @staticmethod
    def register_device(hostname, ngrok_url=None):
        """
        Register a new device in the system.
        
        Args:
            hostname: Device hostname
            ngrok_url: Optional ngrok tunnel URL
            
        Returns:
            DeviceInfo: The created device record
        """
        try:
            existing_device = DeviceInfo.query.filter_by(hostname=hostname).first()
            if existing_device:
                logger.warning(f"Device {hostname} already registered")
                return existing_device
            
            new_device = DeviceInfo(
                hostname=hostname,
                device_code='',
                ngrok_url=ngrok_url,
                last_seen=datetime.now()
            )
            db.session.add(new_device)
            
            log_message = f"{hostname} registered"
            if ngrok_url:
                log_message += f" with ngrok URL: {ngrok_url}"
                
            log_entry = Log(hostname=hostname, log_message=log_message)
            db.session.add(log_entry)
            
            db.session.commit()
            logger.info(f"Device {hostname} registered successfully")
            
            return new_device
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error registering device {hostname}: {e}")
            raise
    
    @staticmethod
    def update_device(hostname, **kwargs):
        """
        Update an existing device record.
        
        Args:
            hostname: Device hostname
            **kwargs: Fields to update
            
        Returns:
            DeviceInfo: The updated device record, or None if not found
        """
        try:
            device = DeviceInfo.query.filter_by(hostname=hostname).first()
            if not device:
                logger.warning(f"Device {hostname} not found for update")
                return None
            
            for key, value in kwargs.items():
                if hasattr(device, key):
                    setattr(device, key, value)
            
            device.last_seen = datetime.now()
            
            log_message = f"{hostname} updated"
            log_entry = Log(hostname=hostname, log_message=log_message)
            db.session.add(log_entry)
            
            db.session.commit()
            logger.info(f"Device {hostname} updated successfully")
            
            return device
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating device {hostname}: {e}")
            raise
    
    @staticmethod
    def get_device(hostname):
        """
        Get a device by hostname.
        
        Args:
            hostname: Device hostname
            
        Returns:
            DeviceInfo: The device record, or None if not found
        """
        return DeviceInfo.query.filter_by(hostname=hostname).first()
