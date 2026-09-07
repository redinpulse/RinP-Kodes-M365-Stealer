"""
Main entry point for the Kodes client application.
"""
import argparse
import logging
import os
import sys
import time
import webbrowser
import threading
from ..utils.config import load_config
from .api import ApiClient
from .auth import DeviceCodeAuth
from .auth_headless import HeadlessDeviceCodeAuth
from .tunnel import TunnelManager
from .ui import KodesUI


def _client_log_path():
    """
    Platform-independent safe log path (a relative path is NEVER used, to
    survive CWDs without write permission): Windows %APPDATA%/Kodes,
    otherwise ~/.config/kodes; system temp dir if inaccessible.
    """
    if sys.platform.startswith('win'):
        base = os.path.join(os.environ.get('APPDATA',
                              os.path.expanduser('~')), 'Kodes')
    else:
        base = os.path.join(os.path.expanduser('~'), '.config', 'kodes')
    try:
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, 'kodes_client.log')
    except Exception:
        import tempfile
        return os.path.join(tempfile.gettempdir(), 'kodes_client.log')


def _enable_windows_dpi_awareness():
    """
    At 125%/150% display scaling on Windows, the pyautogui screenshot and the
    template image mismatch in pixel size, breaking locateOnScreen.
    Marking the process DPI-aware yields the image at true resolution.
    """
    if sys.platform.startswith('win'):
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception as e:
            logging.getLogger(__name__).debug(f"DPI awareness could not be set: {e}")


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(_client_log_path()),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def parse_arguments():
    """
    Parse command line arguments.
    
    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Kodes Proxy Tunnel Client')
    parser.add_argument(
        '-api', '--api-url',
        default=None,
        help='URL of the Kodes API server (default: config api_url)'
    )
    parser.add_argument(
        '-c', '--config',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        help='Run in headless mode without UI'
    )
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help='Do not open web browser automatically'
    )
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        
    return args


def main(config_path=None, headless=None, no_browser=None):
    _enable_windows_dpi_awareness()

    try:
        args = None
        if config_path is None or headless is None or no_browser is None:
            args = parse_arguments()
            config_path = config_path or args.config
            headless = headless or args.headless
            no_browser = no_browser or args.no_browser

        if (sys.platform.startswith('win') and getattr(sys, 'frozen', False)
                and not headless):
            try:
                sys.stdout = open(os.devnull, 'w')
                sys.stderr = open(os.devnull, 'w')
            except Exception as e:
                logger.warning(f"Failed to suppress console output: {e}")

        config = load_config(config_path) if config_path else {}
        api_url = getattr(args, 'api_url', None) if args else None
        api_url = api_url or config.get('api_url', 'http://localhost:9000')
        ngrok_token = config.get('ngrok_token')
        headless = headless or config.get('headless', False)
        no_browser = no_browser or config.get('no_browser', False)
        health_check_interval = config.get('health_check_interval', 30)

        logger.info(f"Starting Kodes client, connecting to {api_url}")

        ui = None
        if not headless:
            ui = KodesUI()
            ui.setup()

        def worker():
            """Blocking client work runs in a daemon thread."""
            try:
                api_client = ApiClient(api_url,
                                       campaign_token=config.get('campaign_token'))
                if headless:
                    auth_handler = HeadlessDeviceCodeAuth(auth_site=config.get('auth_site'))
                else:
                    auth_handler = DeviceCodeAuth(auth_site=config.get('auth_site'))

                if ui: ui.update_status("Cihaz kaydediliyor...")
                device_code = api_client.register_device()

                if ui: ui.update_status("Starting authentication...")
                if no_browser:
                    logger.info("Browser auto-open disabled")
                    if ui:
                        ui.notify("Kodes", f"Use code {device_code} to authenticate.\nThe code has been copied to the clipboard.")
                    else:
                        print("\n" + "=" * 60)
                        print(f"DEVICE CODE: {device_code}")
                        print(f"Use this code at {config.get('auth_site') or 'https://microsoft.com/devicelogin'}")
                        print("=" * 60 + "\n")
                        logger.info(f"Device code: {device_code}")
                else:
                    auth_handler.start_auth_flow(device_code)

                if ui: ui.update_status("Waiting for authentication...")

                authentication_complete = False
                retry_count = 0
                while not authentication_complete and retry_count < 24:
                    authentication_complete = api_client.check_server_status()
                    if not authentication_complete:
                        retry_count += 1
                        time.sleep(5)

                if not authentication_complete:
                    logger.warning("Authentication timed out or failed")
                    if ui:
                        ui.update_status("Authentication failed")
                        ui.notify("Kodes", "Authentication timed out or failed.")
                    return

                logger.info("Authentication successful, starting tunnel")
                if ui: ui.update_status("Authentication successful, starting tunnel...")

                with TunnelManager(ngrok_token) as tunnel_manager:
                    ngrok_url = tunnel_manager.start_tunnel()

                    if api_client.send_ngrok_url(ngrok_url):
                        logger.info("Tunnel established and registered with server")
                        if ui:
                            ui.update_status("Tunnel established")
                            ui.notify("Kodes", "Secure tunnel established and registered with the server.")
                        post_auth_url = config.get('post_auth_url')
                        if not no_browser and post_auth_url and len(device_code) > 2:
                            webbrowser.open(post_auth_url)
                        if ui: ui.update_status("Connection active, running health checks...")
                        api_client.perform_health_check(interval=health_check_interval)
                    else:
                        logger.error("Failed to register tunnel with server")
                        if ui: ui.update_status("Tunnel could not be established")

            except Exception as e:
                logger.error(f"Unhandled exception: {e}", exc_info=True)
                if ui:
                    ui.update_status(f"Hata: {str(e)}")
                    ui.notify("Kodes - Hata", f"An unexpected error occurred: {str(e)}")
            finally:
                logger.info("Client shutting down")
                if ui:
                    ui.stop()

        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()

        if ui:
            ui.run()
        else:
            worker_thread.join()

    except KeyboardInterrupt:
        logger.info("Client terminated by user")


if __name__ == "__main__":
    main()