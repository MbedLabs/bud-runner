"""
OpenProjectClient - Client for OpenProject API integration.

Syncs test cases to OpenProject Work Packages for requirement traceability.
"""

import requests
from typing import Any, Dict, List, Optional, Type
from dataclasses import dataclass, field

from bud_runner.auth import AuthManager


@dataclass
class WorkPackageInfo:
    """Information about an OpenProject Work Package."""
    id: int
    subject: str
    work_package_type: str
    project_id: str
    parent_id: Optional[int] = None
    status: Optional[str] = None
    custom_fields: Dict[str, Any] = field(default_factory=dict)
    url: Optional[str] = None


class OpenProjectClient:
    """
    Client for OpenProject API.
    
    Provides methods to sync test cases to Work Packages.
    """

    TYPE_TEST_SUITE = "Test Suite"
    TYPE_TEST_CASE = "Test Case"

    def __init__(
        self,
        pm_url: Optional[str] = None,
        pm_token: Optional[str] = None,
        auth: Optional[AuthManager] = None,
    ):
        """
        Initialize the OpenProject client.
        
        Args:
            pm_url: OpenProject URL (overrides auth manager).
            pm_token: API token (overrides auth manager).
            auth: AuthManager instance for credentials.
        """
        if auth is None:
            auth = AuthManager(pm_url=pm_url, pm_token=pm_token)
        
        self._base_url = (pm_url or auth.pm_url).rstrip("/")
        self._api_url = f"{self._base_url}/api/v3"
        self._token = pm_token or auth.pm_token
        
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"
        
        if self._token:
            self._session.headers["Authorization"] = f"Bearer {self._token}"

    def find_work_package(
        self,
        project_id: str,
        subject: str,
        wp_type: Optional[str] = None,
        parent_id: Optional[int] = None,
    ) -> Optional[WorkPackageInfo]:
        """
        Find a Work Package by subject.
        
        Args:
            project_id: Project identifier.
            subject: Work Package subject to search for.
            wp_type: Optional type filter.
            parent_id: Optional parent filter.
        
        Returns:
            WorkPackageInfo if found, None otherwise.
        """
        try:
            filters = [
                {"project": {"operator": "=", "values": [project_id]}},
                {"subject": {"operator": "=", "values": [subject]}},
            ]
            
            if wp_type:
                filters.append({"type": {"operator": "=", "values": [wp_type]}})
            if parent_id:
                filters.append({"parent": {"operator": "=", "values": [str(parent_id)]}})
            
            response = self._session.get(
                f"{self._api_url}/work_packages",
                params={"filters": str(filters)},
                timeout=30,
            )
            
            if response.status_code == 200:
                data = response.json()
                elements = data.get("_embedded", {}).get("elements", [])
                if elements:
                    return self._parse_work_package(elements[0], project_id)
            
            return None
        except requests.exceptions.RequestException:
            return None

    def create_work_package(
        self,
        project_id: str,
        subject: str,
        wp_type: str,
        description: str = "",
        parent_id: Optional[int] = None,
        custom_fields: Optional[Dict[str, Any]] = None,
    ) -> Optional[WorkPackageInfo]:
        """
        Create a new Work Package.
        
        Args:
            project_id: Project identifier.
            subject: Work Package subject/title.
            wp_type: Work Package type.
            description: Optional description.
            parent_id: Optional parent Work Package ID.
            custom_fields: Optional custom field values.
        
        Returns:
            WorkPackageInfo for the created Work Package.
        """
        try:
            payload = {
                "subject": subject,
                "_links": {
                    "type": {"href": f"/api/v3/types/{self._get_type_id(wp_type)}"},
                    "project": {"href": f"/api/v3/projects/{project_id}"},
                },
                "description": {"format": "markdown", "raw": description},
            }
            
            if parent_id:
                payload["_links"]["parent"] = {"href": f"/api/v3/work_packages/{parent_id}"}
            
            if custom_fields:
                payload.update(custom_fields)
            
            response = self._session.post(
                f"{self._api_url}/projects/{project_id}/work_packages",
                json=payload,
                timeout=30,
            )
            
            if response.status_code in (200, 201):
                return self._parse_work_package(response.json(), project_id)
            
            return None
        except requests.exceptions.RequestException:
            return None

    def update_work_package(
        self,
        work_package_id: int,
        updates: Dict[str, Any],
    ) -> bool:
        """
        Update an existing Work Package.
        
        Args:
            work_package_id: Work Package ID.
            updates: Fields to update.
        
        Returns:
            True if successful.
        """
        try:
            # Get lock version
            response = self._session.get(
                f"{self._api_url}/work_packages/{work_package_id}",
                timeout=30,
            )
            if response.status_code != 200:
                return False
            
            lock_version = response.json().get("lockVersion", 0)
            updates["lockVersion"] = lock_version
            
            response = self._session.patch(
                f"{self._api_url}/work_packages/{work_package_id}",
                json=updates,
                timeout=30,
            )
            
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def sync_test_case(
        self,
        project_id: str,
        suite_name: str,
        test_class: Type,
        description: str = "",
    ) -> Optional[WorkPackageInfo]:
        """
        Sync a test class to OpenProject as a Work Package.
        
        Args:
            project_id: OpenProject project identifier.
            suite_name: Test suite name (parent Work Package).
            test_class: Test class to sync.
            description: Optional description.
        
        Returns:
            WorkPackageInfo for the test case.
        """
        # Find or create test suite
        suite_wp = self.find_work_package(
            project_id=project_id,
            subject=suite_name,
            wp_type=self.TYPE_TEST_SUITE,
        )
        
        if not suite_wp:
            suite_wp = self.create_work_package(
                project_id=project_id,
                subject=suite_name,
                wp_type=self.TYPE_TEST_SUITE,
                description=f"Test suite: {suite_name}",
            )
        
        if not suite_wp:
            return None
        
        # Find or create test case
        test_name = test_class.__name__
        test_wp = self.find_work_package(
            project_id=project_id,
            subject=test_name,
            wp_type=self.TYPE_TEST_CASE,
            parent_id=suite_wp.id,
        )
        
        if not test_wp:
            # Extract test methods
            test_methods = [
                m for m in dir(test_class)
                if m.startswith("mate_") and callable(getattr(test_class, m, None))
            ]
            
            full_desc = description
            if test_methods:
                full_desc += "\n\n## Test Methods\n"
                full_desc += "\n".join(f"- `{m}`" for m in test_methods)
            
            test_wp = self.create_work_package(
                project_id=project_id,
                subject=test_name,
                wp_type=self.TYPE_TEST_CASE,
                description=full_desc,
                parent_id=suite_wp.id,
            )
        
        return test_wp

    def update_test_result(
        self,
        work_package_id: int,
        passed: bool,
        run_url: str,
    ) -> bool:
        """
        Update a test case with execution results.
        
        Args:
            work_package_id: Work Package ID.
            passed: Whether the test passed.
            run_url: URL to the test run.
        
        Returns:
            True if successful.
        """
        try:
            response = self._session.get(
                f"{self._api_url}/work_packages/{work_package_id}",
                timeout=30,
            )
            if response.status_code != 200:
                return False
            
            current = response.json()
            pass_count = current.get("customField4", 0) or 0
            fail_count = current.get("customField5", 0) or 0
            
            if passed:
                pass_count += 1
            else:
                fail_count += 1
            
            from datetime import datetime
            
            updates = {
                "customField1": "Pass" if passed else "Fail",
                "customField2": datetime.now().strftime("%Y-%m-%d"),
                "customField3": run_url,
                "customField4": pass_count,
                "customField5": fail_count,
            }
            
            return self.update_work_package(work_package_id, updates)
        except requests.exceptions.RequestException:
            return False

    def _get_type_id(self, type_name: str) -> str:
        """Get type ID for a type name."""
        type_mapping = {
            self.TYPE_TEST_SUITE: "1",
            self.TYPE_TEST_CASE: "2",
        }
        return type_mapping.get(type_name, "1")

    def _parse_work_package(self, wp: Dict[str, Any], project_id: str) -> WorkPackageInfo:
        """Parse API response into WorkPackageInfo."""
        return WorkPackageInfo(
            id=wp.get("id"),
            subject=wp.get("subject", ""),
            work_package_type=wp.get("_embedded", {}).get("type", {}).get("name", ""),
            project_id=project_id,
            parent_id=wp.get("_embedded", {}).get("parent", {}).get("id"),
            status=wp.get("_embedded", {}).get("status", {}).get("name"),
            url=f"{self._base_url}/work_packages/{wp.get('id')}",
        )
