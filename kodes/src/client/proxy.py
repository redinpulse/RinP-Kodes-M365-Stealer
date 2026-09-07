"""
SOCKS5 proxy implementation for Kodes tunnel.
"""
import socket
import select
import struct
from socketserver import ThreadingMixIn, TCPServer, BaseRequestHandler
import threading
import logging

logger = logging.getLogger(__name__)


class SOCKS5Proxy(ThreadingMixIn, TCPServer):
    """
    SOCKS5 proxy server implementation with threading support.
    """
    allow_reuse_address = True


class SOCKS5Handler(BaseRequestHandler):
    """
    Handler for SOCKS5 connection requests with optional RFC 1929 authentication.
    """
    username = None
    password = None

    def _recv_exact(self, n):
        """Read exactly n bytes (handles partial reads)."""
        data = b""
        while len(data) < n:
            chunk = self.request.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed during SOCKS5 handshake")
            data += chunk
        return data

    def handle(self):
        """
        Handle a SOCKS5 client connection.
        """
        remote = None
        try:
            version, nmethods = struct.unpack("!BB", self._recv_exact(2))
            methods = self._recv_exact(nmethods)

            if self.username and self.password:
                if 0x02 not in methods:
                    self.request.sendall(b"\x05\xff")
                    return
                self.request.sendall(b"\x05\x02")

                ver, ulen = struct.unpack("!BB", self._recv_exact(2))
                uname = self._recv_exact(ulen)
                plen_byte = self._recv_exact(1)
                plen = plen_byte[0]
                passwd = self._recv_exact(plen)

                if uname == self.username and passwd == self.password:
                    self.request.sendall(b"\x01\x00")
                else:
                    self.request.sendall(b"\x01\x01")
                    logger.warning(f"SOCKS5 auth failed from {self.client_address[0]}")
                    return
            else:
                self.request.sendall(b"\x05\x00")

            version, cmd, _, address_type = struct.unpack("!BBBB", self.request.recv(4))
            
            if address_type == 1:
                address = socket.inet_ntoa(self.request.recv(4))
            elif address_type == 3:
                domain_length = self.request.recv(1)[0]
                address = self.request.recv(domain_length).decode()
            else:
                raise ValueError(f"Unsupported address type: {address_type}")
                
            port = struct.unpack('!H', self.request.recv(2))[0]
            
            logger.debug(f"Connection request to {address}:{port}")

            if cmd == 1:
                remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                remote.settimeout(10)
                remote.connect((address, port))
                bind_address = remote.getsockname()
                self.request.sendall(struct.pack("!BBBBIH", 5, 0, 0, 1, 
                                    int(bind_address[0].replace('.', '')), bind_address[1]))
            else:
                raise ValueError(f"Unsupported command: {cmd}")

            self.exchange_loop(remote)
        except Exception as e:
            logger.error(f"SOCKS5 error: {e}")
        finally:
            if remote:
                remote.close()
            self.request.close()

    def exchange_loop(self, remote):
        """
        Exchange data between client and remote server.
        
        Args:
            remote: Remote socket connection
        """
        while True:
            readable, _, _ = select.select([self.request, remote], [], [], 60)
            
            if self.request in readable:
                data = self.request.recv(4096)
                if not data:
                    break
                if remote.send(data) <= 0:
                    break
                    
            if remote in readable:
                data = remote.recv(4096)
                if not data:
                    break
                if self.request.send(data) <= 0:
                    break


def run_socks5_server(host, port, username=None, password=None):
    """
    Start a SOCKS5 proxy server on the specified host and port.

    Args:
        host: Host address to bind to
        port: Port to listen on
        username: Optional username for RFC 1929 authentication
        password: Optional password for RFC 1929 authentication

    Returns:
        SOCKS5Proxy: The running server instance
    """
    SOCKS5Handler.username = username.encode() if username else None
    SOCKS5Handler.password = password.encode() if password else None
    server = SOCKS5Proxy((host, port), SOCKS5Handler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    auth_status = " with authentication" if username and password else ""
    logger.info(f"SOCKS5 proxy server started on {host}:{port}{auth_status}")
    return server


def get_free_port():
    """
    Find an available port on the system.
    
    Returns:
        int: An available port number
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]