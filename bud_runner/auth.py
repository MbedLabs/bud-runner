"""
AuthManager - Unified authentication management for bud_runner.

Loads credentials from:
1. Function arguments (highest priority)
2. Environment variables
3. app.properties file
"""

import os
import configparser
from pathlib import Path
from typing import Optional


class AuthManager:
    """
    Manages authentication credentials for bud_runner.
    
    Credentials are loaded from (in order of priority):
    1. Constructor arguments
    2. Environment variables
    3. app.properties file
    
    Environment variables:
        BUD_BACKEND_URL - Backend URL
        BUD_TOKEN - API token (user JWT) for most API calls
        BUD_RUNNER_ACCOUNT - Runner account name
        BUD_RUNNER_TOKEN - Runner-specific token
        RUNNER_API_KEY - Shared secret required ONLY for runner registration
                          (POST /api/runners/register sends it as X-API-Key).
                          Must match the backend's RUNNER_API_KEY setting.
        BLOOM_URL - Bloom ALM URL
        BLOOM_TOKEN - Bloom ALM JWT token
        BLOOM_EMAIL - Bloom ALM login email
        BLOOM_PASSWORD - Bloom ALM login password
    """

    DEFAULT_BACKEND_URL = "https://bud.embedlabs.de/"
    DEFAULT_BLOOM_URL = "https://bloom.embedlabs.de/"

    def __init__(
        self,
        username: Optional[str] = None,
        token: Optional[str] = None,
        backend_url: Optional[str] = None,
        runner_account: Optional[str] = None,
        runner_token: Optional[str] = None,
        bloom_url: Optional[str] = None,
        bloom_token: Optional[str] = None,
        bloom_email: Optional[str] = None,
        bloom_password: Optional[str] = None,
        runner_api_key: Optional[str] = None,
        properties_file: Optional[str] = None,
    ):
        """
        Initialize authentication manager.
        
        Args:
            username: Username for authentication.
            token: API token.
            backend_url: Backend URL.
            runner_account: Runner account name.
            runner_token: Runner-specific token.
            bloom_url: Bloom ALM URL.
            bloom_token: Bloom ALM JWT token.
            bloom_email: Bloom ALM login email.
            bloom_password: Bloom ALM login password.
            properties_file: Path to app.properties file.
        """
        # Initialize with defaults
        self._backend_url = self.DEFAULT_BACKEND_URL
        self._bloom_url = self.DEFAULT_BLOOM_URL
        self._token: Optional[str] = None
        self._username: Optional[str] = None
        self._runner_account: Optional[str] = None
        self._runner_token: Optional[str] = None
        self._bloom_token: Optional[str] = None
        self._bloom_email: Optional[str] = None
        self._bloom_password: Optional[str] = None
        self._runner_api_key: Optional[str] = None

        # Load from properties file
        if properties_file:
            self._load_from_properties(properties_file)
        else:
            # Try to find app.properties
            for path in [Path("app.properties"), Path("../app.properties")]:
                if path.exists():
                    self._load_from_properties(str(path))
                    break

        # Override with environment variables
        self._load_from_env()

        # Override with constructor arguments
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
        if bloom_url:
            self._bloom_url = bloom_url
        if bloom_token:
            self._bloom_token = bloom_token
        if bloom_email:
            self._bloom_email = bloom_email
        if bloom_password:
            self._bloom_password = bloom_password
        if runner_api_key:
            self._runner_api_key = runner_api_key

    def _load_from_properties(self, filepath: str) -> None:
        """Load credentials from a .properties file."""
        try:
            with open(filepath, "r") as f:
                content = "[DEFAULT]\n" + f.read()
            
            config = configparser.ConfigParser()
            config.read_string(content)
            props = config["DEFAULT"]

            mapping = {
                "budBackend": "_backend_url",
                "budToken": "_token",
                "budRunnerAccount": "_runner_account",
                "budRunnerToken": "_runner_token",
                "bloomUrl": "_bloom_url",
                "bloomToken": "_bloom_token",
                "bloomEmail": "_bloom_email",
                "bloomPassword": "_bloom_password",
                "lastUser": "_username",
                "runnerApiKey": "_runner_api_key",
            }

            for prop_key, attr_name in mapping.items():
                if prop_key in props and props[prop_key]:
                    setattr(self, attr_name, props[prop_key])

        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Warning: Error loading properties: {e}")

    def _load_from_env(self) -> None:
        """Load credentials from environment variables."""
        env_mapping = {
            "BUD_BACKEND_URL": "_backend_url",
            "BUD_TOKEN": "_token",
            "BUD_USERNAME": "_username",
            "BUD_RUNNER_ACCOUNT": "_runner_account",
            "BUD_RUNNER_TOKEN": "_runner_token",
            "BLOOM_URL": "_bloom_url",
            "BLOOM_TOKEN": "_bloom_token",
            "BLOOM_EMAIL": "_bloom_email",
            "BLOOM_PASSWORD": "_bloom_password",
            "RUNNER_API_KEY": "_runner_api_key",
        }

        for env_key, attr_name in env_mapping.items():
            value = os.environ.get(env_key)
            if value:
                setattr(self, attr_name, value)

    @property
    def backend_url(self) -> str:
        """Get the backend URL."""
        return self._backend_url

    @property
    def token(self) -> Optional[str]:
        """Get the API token."""
        return self._token or self._runner_token

    @property
    def username(self) -> Optional[str]:
        """Get the username."""
        return self._username

    @property
    def runner_account(self) -> Optional[str]:
        """Get the runner account name."""
        return self._runner_account

    @property
    def runner_token(self) -> Optional[str]:
        """Get the runner token."""
        return self._runner_token

    @property
    def bloom_url(self) -> str:
        """Get the Bloom ALM URL."""
        return self._bloom_url

    @property
    def bloom_token(self) -> Optional[str]:
        """Get the Bloom ALM JWT token."""
        return self._bloom_token

    @property
    def bloom_email(self) -> Optional[str]:
        """Get the Bloom ALM login email."""
        return self._bloom_email

    @property
    def bloom_password(self) -> Optional[str]:
        """Get the Bloom ALM login password."""
        return self._bloom_password

    @property
    def runner_api_key(self) -> Optional[str]:
        """Get the runner-registration shared secret (X-API-Key)."""
        return self._runner_api_key

    def save_to_properties(
        self,
        filepath: str = "app.properties",
        runner_token: Optional[str] = None,
    ) -> None:
        """
        Save credentials to app.properties file.
        
        Args:
            filepath: Path to the properties file.
            runner_token: New runner token to save.
        """
        properties = {}
        
        # Load existing properties
        if Path(filepath).exists():
            try:
                with open(filepath, "r") as f:
                    content = "[DEFAULT]\n" + f.read()
                config = configparser.ConfigParser()
                config.read_string(content)
                properties = dict(config["DEFAULT"])
            except Exception:
                pass

        # Update with current values
        if self._backend_url != self.DEFAULT_BACKEND_URL:
            properties["budBackend"] = self._backend_url
        if self._runner_account:
            properties["budRunnerAccount"] = self._runner_account
        if runner_token:
            properties["budRunnerToken"] = runner_token
        elif self._runner_token:
            properties["budRunnerToken"] = self._runner_token
        if self._bloom_url != self.DEFAULT_BLOOM_URL:
            properties["bloomUrl"] = self._bloom_url
        if self._bloom_token:
            properties["bloomToken"] = self._bloom_token
        if self._bloom_email:
            properties["bloomEmail"] = self._bloom_email
        if self._username:
            properties["lastUser"] = self._username

        # Write properties file
        with open(filepath, "w") as f:
            for key, value in properties.items():
                f.write(f"{key}={value}\n")

    def is_configured(self) -> bool:
        """Check if authentication is configured."""
        return bool(self._token or self._runner_token)

    def __repr__(self) -> str:
        return (
            f"AuthManager(backend={self._backend_url}, "
            f"runner={self._runner_account}, "
            f"token={'***' if self.token else 'None'})"
        )
