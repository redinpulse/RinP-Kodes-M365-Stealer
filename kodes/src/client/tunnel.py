"""
Ngrok tunnel management for Kodes proxy.
"""
import logging
from pyngrok import ngrok, conf
from .proxy import get_free_port, run_socks5_server

logger = logging.getLogger(__name__)


class TunnelManager:
    """
    Manages the creation and teardown of Ngrok tunnels.
    """
    
    def __init__(self, auth_token=None):
        """
        Initialize the tunnel manager.
        
        Args:
            auth_token: Optional Ngrok authentication token
        """
        self.server = None
        self.public_url = None
        self.local_port = None
        
        if auth_token:
            conf.get_default().auth_token = auth_token
            logger.info("Ngrok auth token configured")
    
    def start_tunnel(self):
        """
        Start the SOCKS5 proxy server and Ngrok tunnel.
        
        Returns:
            str: The public Ngrok URL for the tunnel
        """
        try:
            self.local_port = get_free_port()
            self.server = run_socks5_server('127.0.0.1', self.local_port,
                                           username='OPERATOR', password='SecureProxy123')
            
            self.public_url = ngrok.connect(self.local_port, "tcp")
            ngrok_url = str(self.public_url).split('"')[1]
            
            logger.info(f"Ngrok tunnel established: {ngrok_url}")
            return ngrok_url
            
        except Exception as e:
            logger.error(f"Failed to start tunnel: {e}")
            self.stop_tunnel()
            raise
    
    def stop_tunnel(self):
        """
        Stop the Ngrok tunnel and SOCKS5 server.
        """
        try:
            if self.public_url:
                ngrok.disconnect(self.public_url)
                self.public_url = None
                logger.info("Ngrok tunnel disconnected")
                
            if self.server:
                self.server.shutdown()
                self.server = None
                logger.info("SOCKS5 server stopped")
                
        except Exception as e:
            logger.error(f"Error stopping tunnel: {e}")
    
    def __enter__(self):
        """
        Context manager support for 'with' statement.
        """
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Ensure tunnel is stopped when exiting context.
        """
        self.stop_tunnel()