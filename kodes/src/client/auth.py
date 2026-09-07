"""
Authentication module for Microsoft device code flow.
"""
import webbrowser
import pyautogui
import pyperclip
import time
import logging
import os
import sys
from .ui import show_code_notification

logger = logging.getLogger(__name__)


class DeviceCodeAuth:
    """
    Handles the Microsoft device authentication flow.
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
        
    def show_code_notification(self, code):
        """
        Display a notification with the device code to the user.
        
        Args:
            code: The device code to display
        """
        show_code_notification(code)
    
    def start_auth_flow(self, code):
        """
        Start the device code authentication flow (worker-thread safe).
        """
        try:
            if len(code) < 5:
                logger.warning(f"Received invalid code format: {code}")
                return False

            pyperclip.copy(code)

            self.show_code_notification(code)

            webbrowser.open(self.auth_site)
            time.sleep(1)

            result = self._auto_enter_code()
            return result

        except Exception as e:
            logger.error(f"Authentication flow error: {e}")
            return False

    def _find_template_image(self):
        """
        Locates the template image: in the source tree (src/client/../../static/img)
        AND, in frozen (PyInstaller) runs, inside the bundle / next to the exe.
        Returns: absolute path if found, None otherwise.
        """
        candidates = []
        if getattr(sys, 'frozen', False):
            bundle_dirs = [getattr(sys, '_MEIPASS', ''),
                           os.path.dirname(sys.executable)]
            for base in bundle_dirs:
                if base:
                    candidates.append(os.path.join(base, 'static', 'img', 'microsoft.png'))
                    candidates.append(os.path.join(base, 'microsoft.png'))
        candidates.append(os.path.join(self.resource_dir, "..", "..", "static", "img", "microsoft.png"))

        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return os.path.abspath(candidate)
        return None

    def _auto_enter_code(self, max_attempts=15):
        """
        Attempt to automatically enter the code into the login page.

        Args:
            max_attempts: Maximum number of attempts to locate the code field

        Returns:
            bool: True if the code was entered, False otherwise
        """
        attempts = 0
        image_path = self._find_template_image()
        if not image_path:
            logger.error("Microsoft template image not found "
                         "(static/img/microsoft.png or bundled microsoft.png)")
            return False
            
        image_path = os.path.abspath(image_path)
        logger.debug(f"Using image path: {image_path}")
        
        while attempts < max_attempts:
            try:
                search_box_location = pyautogui.locateOnScreen(image_path, confidence=0.7)
                if search_box_location is not None:
                    paste_modifier = 'command' if sys.platform == 'darwin' else 'ctrl'
                    pyautogui.hotkey(paste_modifier, 'v')
                    logger.info("Code entered automatically")
                    return True
            except Exception as e:
                logger.debug(f"Image recognition attempt {attempts+1} failed: {e}")
                
            attempts += 1
            time.sleep(0.5)
            
        logger.warning(f"Failed to auto-enter code after {max_attempts} attempts")
        return False