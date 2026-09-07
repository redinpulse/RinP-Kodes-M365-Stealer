"""
Headless authentication module for Microsoft device code flow.
"""
import webbrowser
import time
import logging
import os

logger = logging.getLogger(__name__)


class HeadlessDeviceCodeAuth:
    """
    Handles the Microsoft device authentication flow without GUI dependencies.
    """
    
    def __init__(self, resource_dir=None, auth_site=None):
        """
        Initialize the authentication handler.

        Args:
            resource_dir: Path to the directory containing resources like images
            auth_site: Device login URL (from client config, overrides default)
        """
        self.resource_dir = resource_dir or os.path.dirname(os.path.abspath(__file__))
        self.auth_site = auth_site or "https://microsoft.com/devicelogin"
    
    def start_auth_flow(self, code):
        """
        Start the device code authentication flow.
        
        Args:
            code: The device code to use
            
        Returns:
            bool: True if the flow was started successfully, False otherwise
        """
        try:
            if len(code) < 5:
                logger.warning(f"Received invalid code format: {code}")
                return False
                
            print("\n" + "=" * 60)
            print(f"DEVICE CODE: {code}")
            print(f"Use this code at {self.auth_site}")
            print("=" * 60 + "\n")

            logger.info(f"Device code: {code}")

            try:
                if not webbrowser.open(self.auth_site):
                    logger.warning("Could not open browser automatically")
                    print(f"Please open {self.auth_site} in your browser")
                else:
                    logger.info("Browser opened to device login page")
            except Exception as e:
                logger.error(f"Error opening browser: {e}")
                print(f"Please open {self.auth_site} in your browser")
            
            logger.info("Waiting for user to complete authentication")
            return True
            
        except Exception as e:
            logger.error(f"Authentication flow error: {e}")
            return False