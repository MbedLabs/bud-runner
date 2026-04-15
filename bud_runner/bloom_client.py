"""
BloomClient - Client for Bloom ALM API integration.

Syncs test cases and campaigns to Bloom for requirement traceability.
"""

import requests
from typing import Any, Dict, List, Optional, Type
from dataclasses import dataclass, field

from bud_runner.auth import AuthManager


@dataclass
class BloomTestCaseInfo:
    """Information about a Bloom test case."""
    id: int
    tc_id: str
    title: str
    project_id: int
    description: Optional[str] = None
    status: Optional[str] = None
    steps: Optional[List[Dict[str, Any]]] = None
    campaign_id: Optional[int] = None
    url: Optional[str] = None


@dataclass
class BloomCampaignInfo:
    """Information about a Bloom test campaign."""
    id: int
    name: str
    project_id: int
    status: Optional[str] = None
    description: Optional[str] = None


class BloomClient:
    """
    Client for Bloom ALM API.

    Provides methods to sync test cases and manage campaigns.
    Supports two authentication modes:
    - Token mode: provide a pre-obtained JWT directly
    - Login mode: provide email/password to obtain a JWT
    """

    def __init__(
        self,
        bloom_url: Optional[str] = None,
        bloom_token: Optional[str] = None,
        bloom_email: Optional[str] = None,
        bloom_password: Optional[str] = None,
        auth: Optional[AuthManager] = None,
    ):
        if auth is None:
            auth = AuthManager(
                bloom_url=bloom_url,
                bloom_token=bloom_token,
                bloom_email=bloom_email,
                bloom_password=bloom_password,
            )

        self._base_url = (bloom_url or auth.bloom_url).rstrip("/")
        self._api_url = f"{self._base_url}/api"
        self._token = bloom_token or auth.bloom_token
        self._email = bloom_email or auth.bloom_email
        self._password = bloom_password or auth.bloom_password

        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"

        if self._token:
            self._session.headers["Authorization"] = f"Bearer {self._token}"
        elif self._email and self._password:
            self._login(self._email, self._password)

    def _login(self, email: str, password: str) -> None:
        """Authenticate with Bloom and store the JWT."""
        response = self._session.post(
            f"{self._api_url}/auth/login",
            json={"email": email, "password": password},
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        self._token = data["access_token"]
        self._session.headers["Authorization"] = f"Bearer {self._token}"

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def find_project(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Find a project by prefix or numeric ID.

        Args:
            identifier: Project prefix string or numeric ID.

        Returns:
            Project dict if found, None otherwise.
        """
        try:
            project_id = int(identifier)
            response = self._session.get(
                f"{self._api_url}/projects/{project_id}",
                timeout=30,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except ValueError:
            pass

        try:
            response = self._session.get(
                f"{self._api_url}/projects",
                timeout=30,
            )
            if response.status_code == 200:
                projects = response.json()
                for project in projects:
                    if project.get("prefix") == identifier:
                        return project
        except requests.exceptions.RequestException:
            pass

        return None

    def _resolve_project_id(self, identifier: str) -> int:
        """Resolve a project prefix/ID string to a numeric project ID."""
        try:
            return int(identifier)
        except ValueError:
            project = self.find_project(identifier)
            if project is None:
                raise ValueError(f"Project not found: {identifier}")
            return project["id"]

    # ------------------------------------------------------------------
    # Test Cases
    # ------------------------------------------------------------------

    def find_test_case(
        self,
        project_id: int,
        title: str,
    ) -> Optional[Dict[str, Any]]:
        """Find a test case by project and title."""
        try:
            response = self._session.get(
                f"{self._api_url}/test-cases",
                params={"project_id": project_id},
                timeout=30,
            )
            if response.status_code == 200:
                for tc in response.json():
                    if tc.get("title") == title:
                        return tc
        except requests.exceptions.RequestException:
            pass
        return None

    def create_test_case(
        self,
        project_id: int,
        title: str,
        description: str = "",
        steps: Optional[List[Dict[str, Any]]] = None,
        status: str = "Draft",
    ) -> Optional[Dict[str, Any]]:
        """Create a new test case in Bloom."""
        try:
            payload: Dict[str, Any] = {
                "project_id": project_id,
                "title": title,
                "description": description,
                "status": status,
            }
            if steps:
                payload["steps"] = steps

            response = self._session.post(
                f"{self._api_url}/test-cases",
                json=payload,
                timeout=30,
            )
            if response.status_code in (200, 201):
                return response.json()
        except requests.exceptions.RequestException:
            pass
        return None

    def update_test_case(
        self,
        test_case_id: int,
        updates: Dict[str, Any],
    ) -> bool:
        """Update an existing test case."""
        try:
            response = self._session.patch(
                f"{self._api_url}/test-cases/{test_case_id}",
                json=updates,
                timeout=30,
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    # ------------------------------------------------------------------
    # Campaigns (replaces OpenProject "Test Suite" work packages)
    # ------------------------------------------------------------------

    def find_campaign(
        self,
        project_id: int,
        name: str,
    ) -> Optional[Dict[str, Any]]:
        """Find a test campaign by project and name."""
        try:
            response = self._session.get(
                f"{self._api_url}/campaigns",
                params={"project_id": project_id},
                timeout=30,
            )
            if response.status_code == 200:
                for campaign in response.json():
                    if campaign.get("name") == name:
                        return campaign
        except requests.exceptions.RequestException:
            pass
        return None

    def create_campaign(
        self,
        project_id: int,
        name: str,
        description: str = "",
        test_case_ids: Optional[List[int]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a new test campaign."""
        try:
            payload: Dict[str, Any] = {
                "project_id": project_id,
                "name": name,
                "description": description,
                "test_case_ids": test_case_ids or [],
            }
            response = self._session.post(
                f"{self._api_url}/campaigns",
                json=payload,
                timeout=30,
            )
            if response.status_code in (200, 201):
                return response.json()
        except requests.exceptions.RequestException:
            pass
        return None

    def get_campaign_detail(self, campaign_id: int) -> Optional[Dict[str, Any]]:
        """Get full campaign details including items."""
        try:
            response = self._session.get(
                f"{self._api_url}/campaigns/{campaign_id}",
                timeout=30,
            )
            if response.status_code == 200:
                return response.json()
        except requests.exceptions.RequestException:
            pass
        return None

    def add_to_campaign(
        self,
        campaign_id: int,
        test_case_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Add a test case to a campaign."""
        try:
            response = self._session.post(
                f"{self._api_url}/campaigns/{campaign_id}/items",
                params={"test_case_id": test_case_id},
                timeout=30,
            )
            if response.status_code in (200, 201):
                return response.json()
        except requests.exceptions.RequestException:
            pass
        return None

    def update_campaign_item(
        self,
        campaign_id: int,
        item_id: int,
        status: Optional[str] = None,
        result: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> bool:
        """Update a campaign item (test execution result)."""
        try:
            payload: Dict[str, Any] = {}
            if status is not None:
                payload["status"] = status
            if result is not None:
                payload["result"] = result
            if comment is not None:
                payload["comment"] = comment

            response = self._session.patch(
                f"{self._api_url}/campaigns/{campaign_id}/items/{item_id}",
                json=payload,
                timeout=30,
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    # ------------------------------------------------------------------
    # Test Run Links (links Bud test runs to requirements)
    # ------------------------------------------------------------------

    def link_test_run(
        self,
        requirement_id: int,
        test_run_id: int,
        test_run_name: Optional[str] = None,
        teststation_url: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Link a Bud test run to a Bloom requirement."""
        try:
            payload: Dict[str, Any] = {"test_run_id": test_run_id}
            if test_run_name is not None:
                payload["test_run_name"] = test_run_name
            if teststation_url is not None:
                payload["teststation_url"] = teststation_url
            if status is not None:
                payload["status"] = status

            response = self._session.post(
                f"{self._api_url}/requirements/{requirement_id}/link-testrun",
                json=payload,
                timeout=30,
            )
            if response.status_code in (200, 201):
                return response.json()
        except requests.exceptions.RequestException:
            pass
        return None

    # ------------------------------------------------------------------
    # High-level sync (mirrors the old OpenProject sync_test_case)
    # ------------------------------------------------------------------

    def sync_test_case(
        self,
        project_identifier: str,
        campaign_name: str,
        test_class: Type,
        description: str = "",
    ) -> Optional[BloomTestCaseInfo]:
        """
        Sync a test class to Bloom as a TestCase inside a campaign.

        Args:
            project_identifier: Bloom project prefix or numeric ID.
            campaign_name: Campaign name (replaces the OpenProject "Test Suite").
            test_class: Test class to sync.
            description: Optional description.

        Returns:
            BloomTestCaseInfo for the synced test case.
        """
        project_id = self._resolve_project_id(project_identifier)

        # Find or create campaign (equivalent to old "Test Suite" WP)
        campaign = self.find_campaign(project_id, campaign_name)
        if not campaign:
            campaign = self.create_campaign(
                project_id=project_id,
                name=campaign_name,
                description=f"Test suite: {campaign_name}",
            )
        if not campaign:
            return None

        campaign_id = campaign["id"]

        # Find or create test case
        test_name = test_class.__name__
        tc = self.find_test_case(project_id, test_name)

        if not tc:
            test_methods = [
                m for m in dir(test_class)
                if m.startswith("mate_") and callable(getattr(test_class, m, None))
            ]

            full_desc = description
            if test_methods:
                full_desc += "\n\n## Test Methods\n"
                full_desc += "\n".join(f"- `{m}`" for m in test_methods)

            steps = [
                {"step": i + 1, "action": m, "expected": ""}
                for i, m in enumerate(test_methods)
            ] if test_methods else None

            tc = self.create_test_case(
                project_id=project_id,
                title=test_name,
                description=full_desc,
                steps=steps,
            )

        if not tc:
            return None

        # Add to campaign if not already present
        detail = self.get_campaign_detail(campaign_id)
        if detail:
            existing_tc_ids = {
                item["test_case_id"] for item in detail.get("items", [])
            }
            if tc["id"] not in existing_tc_ids:
                self.add_to_campaign(campaign_id, tc["id"])

        return BloomTestCaseInfo(
            id=tc["id"],
            tc_id=tc.get("tc_id", ""),
            title=tc.get("title", test_name),
            project_id=project_id,
            description=tc.get("description"),
            status=tc.get("status"),
            steps=tc.get("steps"),
            campaign_id=campaign_id,
            url=f"{self._base_url}/projects/{project_id}/test-cases/{tc['id']}",
        )

    # ------------------------------------------------------------------
    # Update test result via campaign item
    # ------------------------------------------------------------------

    def update_test_result(
        self,
        campaign_id: int,
        test_case_id: int,
        passed: bool,
        comment: str = "",
    ) -> bool:
        """
        Update a test case result within a campaign.

        Args:
            campaign_id: Campaign ID containing the test case.
            test_case_id: Test case ID to update.
            passed: Whether the test passed.
            comment: Optional comment on the result.

        Returns:
            True if successful.
        """
        detail = self.get_campaign_detail(campaign_id)
        if not detail:
            return False

        for item in detail.get("items", []):
            if item["test_case_id"] == test_case_id:
                return self.update_campaign_item(
                    campaign_id=campaign_id,
                    item_id=item["id"],
                    status="Passed" if passed else "Failed",
                    result="Pass" if passed else "Fail",
                    comment=comment,
                )

        return False
