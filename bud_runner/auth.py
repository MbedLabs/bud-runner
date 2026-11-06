"""
AuthManager - Unified authentication management for bud_runner.

Loads credentials from (in order of priority):
1. Function arguments (highest priority)
2. Environment variables
3. app.properties file (non-sensitive project metadata only)
4. ~/.bud/config.json runner identity vault (runner secrets only), or
   ~/.bud/locations/<name>/config.json for a runner with a location
"""

import configparser
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_selected_location: Optional[str] = None


def select_location(location: Optional[str]) -> Optional[str]:
    """Choose the location of this process's runner and return the previous choice.

    A chosen location takes precedence over the ``location`` of app.properties for every
    AuthManager and runner folder of the process; None leaves app.properties in charge.
    """
    global _selected_location
    previous, _selected_location = _selected_location, location
    return previous


def _project_properties_files() -> List[Path]:
    """The app.properties files of the working directory and its four parents, outermost first."""
    prop_files = []
    curr = Path.cwd().resolve()
    for _ in range(5):
        pf = curr / "app.properties"
        if pf.exists():
            prop_files.append(pf)
        if curr == curr.parent:
            break
        curr = curr.parent
    return list(reversed(prop_files))


def _read_properties(filepath: str) -> configparser.SectionProxy:
    """The keys and values of a .properties file."""
    with open(filepath, "r") as f:
        content = f.read()

    if "[DEFAULT]" not in content:
        content = "[DEFAULT]\n" + content

    config = configparser.ConfigParser(
        strict=False, interpolation=None, inline_comment_prefixes=None
    )
    config.read_string(content)
    return config["DEFAULT"]


def current_location() -> Optional[str]:
    """The location chosen with select_location, else the ``location`` of app.properties."""
    if _selected_location:
        return _selected_location
    location = None
    for pf in _project_properties_files():
        try:
            value = _read_properties(str(pf)).get("location")
        except Exception:
            continue
        if value:
            location = value
    return location


def state_dir(location: Optional[str], root: Optional[Path] = None) -> Path:
    """The folder holding a runner's identity, daemon, spool and cache.

    ``root`` (default ``~/.bud``) without a location, else ``root/locations/<name>``,
    where ``<name>`` is the location with every character outside ``[A-Za-z0-9._-]``
    replaced by ``-``.
    """
    base = root if root is not None else Path.home() / ".bud"
    if not location:
        return base
    return base / "locations" / location_folder_name(location)


def location_folder_name(location: str) -> str:
    """The folder name of a location: every character outside ``[A-Za-z0-9._-]`` becomes ``-``."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", location)


class IdentityVault:
    """Manages sensitive runner identities in the user's home directory."""

    def __init__(self, vault_dir: Optional[Path] = None, fallback_file: Optional[Path] = None):
        """Open the vault in ``vault_dir`` (default ``~/.bud``).

        A runner account missing from it is read from ``fallback_file`` when one is given;
        that file is only read, never written.
        """
        self.vault_dir = vault_dir if vault_dir is not None else Path.home() / ".bud"
        self.config_file = self.vault_dir / "config.json"
        self.fallback_file = fallback_file
        self._ensure_dir()

    def _ensure_dir(self):
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_file.exists():
            self.save_all({})

    def load_all(self) -> Dict[str, Any]:
        return self._read(self.config_file)

    @staticmethod
    def _read(config_file: Path) -> Dict[str, Any]:
        """The identities stored in ``config_file``; empty when it is missing or unreadable."""
        try:
            if not config_file.exists():
                return {}
            with open(config_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def save_all(self, data: Dict[str, Any]):
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(self.config_file, 0o600)

    def get_runner(self, username: str) -> Optional[Dict[str, Any]]:
        identity = self.load_all().get(username)
        if identity is None and self.fallback_file is not None:
            identity = self._read(self.fallback_file).get(username)
        return identity

    def save_runner(self, username: str, token: str, port: int, backend: str):
        data = self.load_all()
        data[username] = {
            "token": token,
            "port": port,
            "backend": backend,
        }
        self.save_all(data)

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        return self.load_all().get("_users", {}).get(username)

    def save_user(self, username: str, token: str, backend: str):
        data = self.load_all()
        users = data.setdefault("_users", {})
        users[username] = {
            "token": token,
            "backend": backend,
        }
        self.save_all(data)


class AuthManager:
    """
    Manages authentication credentials for bud_runner.
    """

    DEFAULT_BACKEND_URL = "http://localhost:8000"
    PROJECT_PROPERTY_MAPPING = {
        "budBackend": "_backend_url",
        "budRunnerAccount": "_runner_account",
        "lastUser": "_username",
        "productId": "_product_id",
        "location": "_location",
    }

    def __init__(
        self,
        username: Optional[str] = None,
        token: Optional[str] = None,
        backend_url: Optional[str] = None,
        runner_account: Optional[str] = None,
        runner_token: Optional[str] = None,
        runner_api_key: Optional[str] = None,
        properties_file: Optional[str] = None,
        bud_token: Optional[str] = None,
    ):
        self._backend_url = self.DEFAULT_BACKEND_URL
        self._token: Optional[str] = token or bud_token
        self._username: Optional[str] = None
        self._runner_account: Optional[str] = None
        self._runner_token: Optional[str] = None
        self._runner_api_key: Optional[str] = None
        self._product_id: Optional[int] = None
        self._socket_port: int = 53035
        self._location: Optional[str] = None

        self._load_project_properties(properties_file)
        if _selected_location:
            self._location = _selected_location
        self.state_dir = state_dir(self._location)
        self.vault = IdentityVault(
            self.state_dir, state_dir(None) / "config.json" if self._location else None
        )
        self._load_from_env()
        self._apply_arguments(
            username,
            token or bud_token,
            backend_url,
            runner_account,
            runner_token,
            runner_api_key,
        )
        self._load_vault_identities(backend_url)

    def _load_project_properties(self, properties_file: Optional[str]) -> None:
        """Load explicit properties or the nearest five parent property files."""
        if properties_file:
            self._load_from_properties(properties_file)
        else:
            for pf in _project_properties_files():
                self._load_from_properties(str(pf))

    def _apply_arguments(
        self, username, token, backend_url, runner_account, runner_token, runner_api_key
    ):
        """Apply explicit authentication and backend arguments after environment values."""
        if backend_url:
            self._backend_url = backend_url
        if token:
            self._token = token
        if username:
            self._username = username
            if not self._runner_account:
                self._runner_account = username
        if runner_account:
            self._runner_account = runner_account
        if runner_token:
            self._runner_token = runner_token
        if runner_api_key:
            self._runner_api_key = runner_api_key

    def _load_vault_identities(self, backend_url: Optional[str]) -> None:
        """Resolve saved runner and user identities without replacing explicit credentials."""
        self._load_vault_runner(backend_url)

        if self._username and not self._token:
            user_identity = self.vault.get_user(self._username)
            if user_identity:
                self._token = user_identity.get("token")
                if not backend_url and not os.environ.get("BUD_BACKEND_URL"):
                    self._backend_url = user_identity.get("backend", self._backend_url)

    def _load_vault_runner(self, backend_url: Optional[str]) -> None:
        """Apply the saved station identity without replacing supplied credentials."""
        if self._runner_account:
            identity = self.vault.get_runner(self._runner_account)
            if identity:
                if not self._runner_token:
                    self._runner_token = identity.get("token")
                self._socket_port = identity.get("port", self._socket_port)
                if not backend_url and not os.environ.get("BUD_BACKEND_URL"):
                    self._backend_url = identity.get("backend", self._backend_url)

    def _load_from_properties(self, filepath: str) -> None:
        """Load non-sensitive project metadata from a .properties file."""
        try:
            props = _read_properties(filepath)

            for prop_key, attr_name in self.PROJECT_PROPERTY_MAPPING.items():
                if prop_key in props and props[prop_key]:
                    val = props[prop_key]
                    if attr_name in ("_socket_port", "_product_id"):
                        try:
                            val = int(val)
                        except ValueError:
                            continue
                    setattr(self, attr_name, val)

        except Exception as e:
            logger.warning("Error loading properties: %s", e)

    def _load_from_env(self) -> None:
        """Load credentials from environment variables."""
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
    def location(self) -> Optional[str]:
        """Get the runner location."""
        return self._location

    @property
    def product_id(self) -> Optional[int]:
        """Get the associated product ID."""
        return self._product_id

    @property
    def socket_port(self) -> int:
        """Get the runner socket listener port."""
        return self._socket_port

    def save_identity(self, username: str, token: str, port: int):
        self.vault.save_runner(username, token, port, self._backend_url)
        self._runner_account = username
        self._runner_token = token
        self._socket_port = port

    def save_user_token(self, username: str, token: str) -> None:
        self.vault.save_user(username, token, self._backend_url)
        self._username = username
        self._token = token

    def save_to_properties(self, filepath: str = "app.properties") -> None:
        properties = {}
        if self._backend_url != self.DEFAULT_BACKEND_URL:
            properties["budBackend"] = self._backend_url
        if self._runner_account:
            properties["budRunnerAccount"] = self._runner_account

        if self._username:
            properties["lastUser"] = self._username
        if getattr(self, "_location", None):
            properties["location"] = self._location
        if getattr(self, "_product_id", None) is not None:
            properties["productId"] = self._product_id

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
