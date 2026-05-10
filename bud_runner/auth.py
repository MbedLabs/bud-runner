"""
AuthManager - Unified authentication management for bud_runner.

Loads credentials from (in order of priority):
1. Function arguments (highest priority)
2. Environment variables
3. app.properties file
"""

import os
import configparser
from pathlib import Path
from typing import Optional, Dict, Any, List
import json

class IdentityVault:
    """Manages sensitive runner identities in the user's home directory."""
    
    def __init__(self):
        self.vault_dir = Path.home() / ".bud"
        self.config_file = self.vault_dir / "config.json"
        self._ensure_dir()

    def _ensure_dir(self):
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_file.exists():
            self.save_all({})

    def load_all(self) -> Dict[str, Any]:
        try:
            if not self.config_file.exists():
                return {}
            with open(self.config_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def save_all(self, data: Dict[str, Any]):
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(self.config_file, 0o600)

    def get_runner(self, username: str) -> Optional[Dict[str, Any]]:
        return self.load_all().get(username)

    def save_runner(self, username: str, token: str, port: int, backend: str):
        data = self.load_all()
        data[username] = {
            "token": token,
            "port": port,
            "backend": backend,
        }
        self.save_all(data)


class AuthManager:
    """
    Manages authentication credentials for bud_runner.
    """

    DEFAULT_BACKEND_URL = ""

    def __init__(
        self,
        username: Optional[str] = None,
        token: Optional[str] = None,
        backend_url: Optional[str] = None,
        runner_account: Optional[str] = None,
        runner_token: Optional[str] = None,
        runner_api_key: Optional[str] = None,
        properties_file: Optional[str] = None,
    ):
        self.vault = IdentityVault()
        self._backend_url = self.DEFAULT_BACKEND_URL
        self._token: Optional[str] = None
        self._username: Optional[str] = None
        self._runner_account: Optional[str] = None
        self._runner_token: Optional[str] = None
        self._runner_api_key: Optional[str] = None
        self._product_id: Optional[int] = None
        self._socket_port: int = 53035

        # 1. Load from properties file
        if properties_file:
            self._load_from_properties(properties_file)
        else:
            # System Alignment: Search up parent directories for properties
            prop_files = []
            curr = Path.cwd().resolve()
            for _ in range(5):
                pf = curr / "app.properties"
                if pf.exists():
                    prop_files.append(pf)
                if curr == curr.parent:
                    break
                curr = curr.parent
            
            # Load in reverse (root first) so local files override
            for pf in reversed(prop_files):
                self._load_from_properties(str(pf))

        # 2. Override with environment variables
        self._load_from_env()

        # 3. Override with constructor arguments
        if backend_url:
            self._backend_url = backend_url
        if token:
            self._token = token
        if username:
            self._username = username
        if runner_account:
            self._runner_account = runner_account
        if runner_token:
            self._runner_token = runner_token
        if runner_api_key:
            self._runner_api_key = runner_api_key

        # 4. Fetch Secret from Vault (If account is known but token is missing)
        if self._runner_account and not self._runner_token:
            identity = self.vault.get_runner(self._runner_account)
            if identity:
                self._runner_token = identity.get("token")
                self._socket_port = identity.get("port", self._socket_port)
                if not backend_url and not os.environ.get("BUD_BACKEND_URL"):
                    self._backend_url = identity.get("backend", self._backend_url)

    def _load_from_properties(self, filepath: str) -> None:
        """Load credentials from a .properties file."""
        try:
            with open(filepath, "r") as f:
                content = f.read()
            
            # configparser requires a section header
            if "[DEFAULT]" not in content:
                content = "[DEFAULT]\n" + content

            # Disable interpolation and inline comments to support complex keys
            config = configparser.ConfigParser(
                strict=False, 
                interpolation=None, 
                inline_comment_prefixes=None
            )
            config.read_string(content)
            props = config["DEFAULT"]

            mapping = {
                "budBackend": "_backend_url",
                "budToken": "_token",
                "budRunnerAccount": "_runner_account",
                "budRunnerToken": "_runner_token",
                "lastUser": "_username",
                "runnerApiKey": "_runner_api_key",
                "runnerSocketPort": "_socket_port",
                "productId": "_product_id",
            }

            for prop_key, attr_name in mapping.items():
                if prop_key in props and props[prop_key]:
                    val = props[prop_key]
                    if attr_name in ("_socket_port", "_product_id"):
                        try:
                            val = int(val)
                        except ValueError:
                            continue
                    setattr(self, attr_name, val)

        except Exception as e:
            print(f"Warning: Error loading properties: {e}")

    def _load_from_env(self) -> None:
        """Load credentials from environment variables ONLY if not already set."""
        env_mapping = {
            "BUD_BACKEND_URL": "_backend_url",
            "BUD_TOKEN": "_token",
            "BUD_USERNAME": "_username",
            "BUD_RUNNER_ACCOUNT": "_runner_account",
            "BUD_RUNNER_TOKEN": "_runner_token",
            "BUD_RUNNER_API_KEY": "_runner_api_key",
        }

        for env_key, attr_name in env_mapping.items():
            value = os.environ.get(env_key)
            if value:
                # Priority Fix: Only use ENV if the property is still missing
                if not getattr(self, attr_name):
                    setattr(self, attr_name, value)

    @property
    def backend_url(self) -> str:
        return self._backend_url

    @property
    def token(self) -> Optional[str]:
        return self._token or self._runner_token

    @property
    def username(self) -> Optional[str]:
        return self._username

    @property
    def runner_account(self) -> Optional[str]:
        return self._runner_account

    @property
    def runner_token(self) -> Optional[str]:
        return self._runner_token

    @property
    def runner_api_key(self) -> Optional[str]:
        return self._runner_api_key

    @property
    def product_id(self) -> Optional[int]:
        """Get the associated product ID."""
        return self._product_id

    def save_identity(self, username: str, token: str, port: int):
        self.vault.save_runner(username, token, port, self._backend_url)
        self._runner_account = username
        self._runner_token = token
        self._socket_port = port

    def save_to_properties(self, filepath: str = "app.properties", runner_token: Optional[str] = None) -> None:
        properties = {}
        if self._backend_url != self.DEFAULT_BACKEND_URL:
            properties["budBackend"] = self._backend_url
        if self._runner_account:
            properties["budRunnerAccount"] = self._runner_account
        
        token_to_save = runner_token or self._runner_token
        if token_to_save:
            properties["budRunnerToken"] = token_to_save
            
        if self._username:
            properties["lastUser"] = self._username
        if self._runner_api_key:
            properties["runnerApiKey"] = self._runner_api_key
        if self._socket_port:
            properties["runnerSocketPort"] = self._socket_port
        if getattr(self, "_location", None):
            properties["location"] = self._location

        with open(filepath, "w") as f:
            for key, value in properties.items():
                f.write(f"{key}={value}\n")

    def is_configured(self) -> bool:
        return bool((self._token or self._runner_token) and self._backend_url)

    def __repr__(self) -> str:
        return (
            f"AuthManager(backend={self._backend_url}, "
            f"runner={self._runner_account}, "
            f"token={'***' if self.token else 'None'})"
        )
