import json
import socket
import qbittorrentapi
from urllib.parse import urlparse
from typing import Callable, Optional
from qbittorrentapi.exceptions import APIConnectionError

class QBittorrentClient:
    def __init__(self, log_callback: Optional[Callable[[str], None]] = print, auto_connect: bool = False):
        """
        :param log_callback: Function to log messages
        :param auto_connect: If True, attempt to connect immediately
        """
        self._client: Optional[qbittorrentapi.Client] = None
        self.log_callback = log_callback

        if auto_connect:
            self.connect(silent=True)

    def connect(self, silent: bool = False) -> Optional[qbittorrentapi.Client]:
        """Connect to qBittorrent, return client object"""
        if self._client:
            if not silent:
                self.log_callback("ℹ️ Already connected to qBittorrent!")
            return self._client

        try:
            with open("login_files/qbittorrent_credentials.json", "r") as file:
                qt_data = json.load(file)
        except Exception as e:
            self.log_callback(f"❌ Failed to load credentials: {e}")
            return None

        # --- PRE-FLIGHT CHECK (Fixes the 30s hang) ---
        if not self._is_port_open(qt_data['host']):
            self.log_callback("❌ qBittorrent is not running (Port is closed).")
            return None

        try:
            # Basic client initialization (No more 'Unexpected Argument' errors)
            client = qbittorrentapi.Client(
                host=qt_data['host'],
                username=qt_data['username'],
                password=qt_data['password'],
            )

            # Attempt login with a simple timeout
            client.auth_log_in(requests_params={'timeout': 2})

            self._client = client
            if not silent:
                self.log_callback("✅ Connected to qBittorrent!")
            return self._client

        # 1. Catch if the username/password is wrong
        except qbittorrentapi.LoginFailed as e:
            self.log_callback(f"❌ qBittorrent Login failed: {e}")
            return None

        # 2. Catch if qBittorrent is closed/port is wrong
        except APIConnectionError:
            self.log_callback("❌ Could not connect: qBittorrent is not running or WebUI is disabled.")
            return None

        # 3. Catch-all for any other unexpected issues (SSL, etc)
        except Exception as e:
            self.log_callback(f"❌ An unexpected error occurred: {e}")
            return None

    def _is_port_open(self, url: str) -> bool:
        """Checks if the qBittorrent port is actually listening."""
        try:
            parsed = urlparse(url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 8080

            # Try to connect to the socket very briefly
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def disconnect(self):
        """Disconnect from qBittorrent"""
        if self._client:
            self._client = None
            self.log_callback("🔌 Disconnected from qBittorrent.")
        else:
            self.log_callback("ℹ️ No qBittorrent connection to disconnect.")

    @property
    def is_connected(self) -> bool:
        return self._client is not None