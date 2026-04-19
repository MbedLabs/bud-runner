"""
RunnerManager - Manages runner registration and status.

Handles:
- Runner registration with bud.embedlabs.de
- Token management
- Socket communication for runner status
- Heartbeat functionality
"""

import socket
import threading
import time
import logging
from typing import Any, Dict, Optional
from pathlib import Path

from bud_runner.auth import AuthManager
from bud_runner.api_client import BudAPIClient

logger = logging.getLogger(__name__)


class RunnerManager:
    """
    Manages test runner registration and communication.
    
    Usage:
        auth = AuthManager()
        manager = RunnerManager(auth)
        manager.register("my-runner", "password")
    """

    def __init__(self, auth: AuthManager):
        """
        Initialize the runner manager.
        
        Args:
            auth: AuthManager instance for credentials.
        """
        self._auth = auth
        self._client = BudAPIClient(auth)
        self._socket_server: Optional[socket.socket] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._running = False

    def register(
        self,
        username: str,
        password: str,
        socket_port: int = 53035,
    ) -> Dict[str, Any]:
        """
        Register this machine as a test runner.
        
        Args:
            username: Runner account name.
            password: Password for registration.
            socket_port: Socket port for communication.
        
        Returns:
            Registration response with token.
        """
        # Register with backend
        result = self._client.register_runner(
            username=username,
            password=password,
            socket_port=socket_port,
        )
        
        # Save credentials to app.properties
        self._auth.save_to_properties(
            runner_token=result.get("token"),
        )
        
        # Update auth with new values
        self._auth._runner_account = username
        self._auth._runner_token = result.get("token")
        
        return {
            "account": username,
            "token_saved": True,
            "socket_port": socket_port,
        }

    def start_listener(self, port: int = 53035) -> None:
        """
        Start listening for runner commands on a socket.
        
        Args:
            port: Port to listen on.
        """
        if self._running and self._socket_server:
            return
        
        self._running = True
        self._socket_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket_server.bind(("0.0.0.0", port))
        self._socket_server.listen(5)
        
        logger.info(f"Runner listening on port {port}")
        
        while self._running:
            try:
                self._socket_server.settimeout(1.0)
                try:
                    client_socket, address = self._socket_server.accept()
                    self._handle_connection(client_socket, address)
                except (socket.timeout, OSError):
                    continue
            except Exception as e:
                if self._running:
                    logger.error(f"Socket error: {e}")
                break

    def stop_listener(self) -> None:
        """Stop the socket listener."""
        self._running = False
        if self._socket_server:
            try:
                self._socket_server.close()
            except Exception:
                pass
            self._socket_server = None
        logger.info("Socket listener stopped")

    def _handle_connection(
        self,
        client_socket: socket.socket,
        address: tuple,
    ) -> None:
        """Handle an incoming socket connection."""
        try:
            data = client_socket.recv(4096)
            if data:
                message = data.decode("utf-8").strip()
                logger.info(f"Received command from {address}: {message}")
                response = self._process_command(message)
                client_socket.sendall(response.encode("utf-8"))
        except Exception as e:
            logger.error(f"Error handling connection from {address}: {e}")
        finally:
            client_socket.close()

    def _process_command(self, command: str) -> str:
        """Process a command received via socket."""
        parts = command.split(" ", 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if cmd == "status":
            return "OK: Runner is active"
        elif cmd == "ping":
            return "PONG"
        elif cmd == "run":
            # Trigger a test run
            logger.info(f"Triggering test run: {args}")
            return f"STARTED: {args}"
        elif cmd == "stop":
            logger.info("Stop command received")
            self.stop_listener()
            return "STOPPING"
        else:
            return f"UNKNOWN: {cmd}"

    def start_heartbeat(self, interval: int = 60) -> None:
        """
        Start sending periodic heartbeats to the backend.
        
        Args:
            interval: Seconds between heartbeats.
        """
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        
        self._running = True
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(interval,),
            daemon=True,
        )
        self._heartbeat_thread.start()
        logger.info(f"Heartbeat thread started (interval={interval}s)")

    def _heartbeat_loop(self, interval: int) -> None:
        """Background heartbeat loop."""
        while self._running:
            try:
                success = self._client.heartbeat()
                if success:
                    logger.debug("✓ Heartbeat sent")
                else:
                    logger.warning("✗ Heartbeat failed")
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
            
            time.sleep(interval)

    def stop_heartbeat(self) -> None:
        """Stop the heartbeat loop."""
        self._running = False
        logger.info("Heartbeat stopped")

    def get_status(self) -> Dict[str, Any]:
        """
        Get current runner status.
        
        Returns:
            Status dictionary.
        """
        return {
            "account": self._auth.runner_account,
            "backend_url": self._auth.backend_url,
            "socket_active": self._socket_server is not None,
            "heartbeat_active": (
                self._heartbeat_thread is not None
                and self._heartbeat_thread.is_alive()
            ),
        }

