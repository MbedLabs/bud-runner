"""
RunnerManager - Manages runner registration and status.

Handles:
- Runner registration with the backend
- Token management
- Socket communication for runner status
- Heartbeat functionality
"""

import socket
import asyncio
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
        self._socket_server: Optional[asyncio.Server] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
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
        
        # Save secret identity to machine vault
        self._auth.save_identity(
            username=username,
            token=result.get("token"),
            port=socket_port,
        )
        
        # Save public link to project app.properties
        self._auth.save_to_properties()
        
        return {
            "account": username,
            "token_saved": True,
            "vault_updated": True,
            "socket_port": socket_port,
        }

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle an incoming socket connection."""
        address = writer.get_extra_info('peername')
        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            if data:
                message = data.decode("utf-8").strip()
                logger.info(f"Received command from {address}: {message}")
                response = self._process_command(message)
                writer.write(response.encode("utf-8"))
                await writer.drain()
        except asyncio.TimeoutError:
            logger.warning(f"Connection timeout from {address}")
        except Exception as e:
            logger.error(f"Error handling connection from {address}: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

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
            self._running = False
            return "STOPPING"
        else:
            return f"UNKNOWN: {cmd}"

    async def _heartbeat_loop(self, interval: int) -> None:
        """Background heartbeat loop with automatic token rotation."""
        while self._running:
            try:
                # Use to_thread since requests is synchronous
                result = await asyncio.to_thread(self._client.heartbeat)
                
                if result.get("status") == "ok":
                    logger.debug("✓ Heartbeat sent")
                    
                    # SYSTEM ALIGNMENT: Auto-rotate token if provided
                    new_token = result.get("token")
                    if new_token:
                        logger.info("Rotating runner token automatically...")
                        self._auth.save_identity(
                            username=self._auth.runner_account,
                            token=new_token,
                            port=self._auth._socket_port
                        )
                        # Also sync to local properties
                        self._auth.save_to_properties()
                else:
                    logger.warning(f"✗ Heartbeat failed: {result.get('message')}")
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
            
            await asyncio.sleep(interval)

    async def run_daemon(self, port: int = 53035, interval: int = 60) -> None:
        """Run the daemon (socket server and heartbeat) concurrently."""
        self._running = True
        
        self._socket_server = await asyncio.start_server(
            self._handle_connection, '0.0.0.0', port
        )
        logger.info(f"Runner listening on port {port}")

        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(interval))
        logger.info(f"Heartbeat task started (interval={interval}s)")

        async with self._socket_server:
            # Run until self._running becomes False
            while self._running:
                await asyncio.sleep(1)
            
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

    def start_heartbeat(self, interval: int = 60) -> None:
        """Deprecated: Use run_daemon instead."""
        pass

    def start_listener(self, port: int = 53035) -> None:
        """Deprecated: Use run_daemon instead."""
        pass

    def stop_heartbeat(self) -> None:
        """Stop the heartbeat loop."""
        self._running = False

    def stop_listener(self) -> None:
        """Stop the socket listener."""
        self._running = False
        
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
                self._heartbeat_task is not None
                and not self._heartbeat_task.done()
            ),
        }

