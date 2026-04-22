"""
AuthManager - Unified authentication management for bud_runner.

Loads credentials from:
1. Function arguments (highest priority)
2. Environment variables
3. app.properties file
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any

class IdentityVault:
    """Manages secure storage of runner identities in the user's home directory."""
    
    def __init__(self, config_path: Optional[str] = None):
        if config_path:
            self.path = Path(config_path)
        else:
            self.path = Path.home() / ".bud" / "config.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with open(self.path, "w") as f:
                json.dump({}, f)

    def load_all(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def save_runner(self, username: str, token: str, port: int, backend: str):
        identities = self.load_all()
        identities[username] = {
            "token": token,
            "port": port,
            "backend": backend
        }
        with open(self.path, "w") as f:
            json.dump(identities, f, indent=2)

    def get_runner(self, username: str) -> Optional[Dict[str, Any]]:
        return self.load_all().get(username)

class AuthManager:
    """Handles loading and priority of authentication credentials."""
    
    DEFAULT_BACKEND_URL = "https://bud.embedlabs.de"

    def __init__(
        self,
        backend_url: Optional[str] = None,
        runner_account: Optional[str] = None,
        token: Optional[str] = None,
    ):
        self.vault = IdentityVault()
        
        # 1. Initialize with defaults or args
        self._backend_url = backend_url or self.DEFAULT_BACKEND_URL
        self._runner_account = runner_account
        self._token = token
        self._runner_token: Optional[str] = None
        self._socket_port: int = 53035

        # 2. Priority 2: Load from app.properties (if exists in current dir)
        self._load_from_properties()

        # 3. Priority 3: Load from Environment Variables
        self._load_from_env()

        # 4. Final step: If we have an account but no token, check the vault
        if self._runner_account and not (self._token or self._runner_token):
            identity = self.vault.get_runner(self._runner_account)
            if identity:
                self._runner_token = identity.get("token")
                self._socket_port = identity.get("port", self._socket_port)
                if not backend_url: # Only override if not explicitly provided
                    self._backend_url = identity.get("backend", self._backend_url)

    def _load_from_properties(self):
        prop_path = Path("app.properties")
        if prop_path.exists():
            properties = {}
            with open(prop_path, "r") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        properties[k.strip()] = v.strip()
            
            mapping = {
                "budBackend": "_backend_url",
                "budRunnerAccount": "_runner_account",
                "budRunnerToken": "_token",
                "runnerSocketPort": "_socket_port"
            }
            for prop_key, attr in mapping.items():
                val = properties.get(prop_key)
                if val:
                    if attr == "_socket_port":
                        setattr(self, attr, int(val))
                    else:
                        setattr(self, attr, val)

    def _load_from_env(self):
        env_mapping = {
            "BUD_BACKEND_URL": "_backend_url",
            "BUD_RUNNER_ACCOUNT": "_runner_account",
            "BUD_TOKEN": "_token",
            "BUD_RUNNER_TOKEN": "_runner_token",
            "RUNNER_SOCKET_PORT": "_socket_port"
        }
        for env_key, attr in env_mapping.items():
            val = os.getenv(env_key)
            if val:
                if attr == "_socket_port":
                    setattr(self, attr, int(val))
                else:
                    setattr(self, attr, val)

    @property
    def backend_url(self) -> str:
        return self._backend_url.rstrip("/")

    @property
    def runner_account(self) -> Optional[str]:
        return self._runner_account

    @property
    def token(self) -> Optional[str]:
        """Returns either the user token or the runner token."""
        return self._token or self._runner_token

    @property
    def socket_port(self) -> int:
        return self._socket_port

    def save_identity(self, username: str, token: str, port: int):
        self.vault.save_runner(username, token, port, self._backend_url)
        self._runner_token = token
        self._runner_account = username
        self._socket_port = port

    def is_configured(self) -> bool:
        return bool((self._token or self._runner_token) and self._backend_url)
