"""
BudAPIClient - REST client for bud.embedlabs.de API.

Provides methods for:
- Creating test runs
- Uploading test results
- Managing runners
- Uploading artifacts/traces
"""

import requests
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

from bud_runner.auth import AuthManager


@dataclass
class TestRunInfo:
    """Information about a test run."""
    id: int
    name: str
    status: str
    url: str
    created_at: datetime
    test_count: int = 0
    passed_count: int = 0
    failed_count: int = 0


class BudAPIClient:
    """
    REST client for the bud.embedlabs.de API.
    
    Handles authentication and provides methods for all API endpoints.
    """

    def __init__(self, auth: AuthManager):
        """
        Initialize the API client.
        
        Args:
            auth: AuthManager instance with credentials.
        """
        self._auth = auth
        self._base_url = auth.backend_url.rstrip("/")
        self._api_url = f"{self._base_url}/api"
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"
        
        if auth.token:
            self._session.headers["Authorization"] = f"Bearer {auth.token}"

    # ==================== Test Runs ====================

    def create_test_run(
        self,
        test_case_list: str,
        test_suite_name: str,
        url_test_software: Optional[str] = None,
        ref_test_software: str = "main",
        product_composition_id: int = 1,
        status: str = "Running",
        pipeline_software_under_test: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a new test run.
        
        Args:
            test_case_list: Module path to the test case list.
            test_suite_name: Name for this test run.
            url_test_software: URL to the test software repository.
            ref_test_software: Git ref of the test software.
            product_composition_id: ID of the product composition.
            status: Initial status (Running, Pending, etc.).
            pipeline_software_under_test: Use SW version from CI pipeline.
        
        Returns:
            Dictionary with test run details including ID and URL.
        """
        payload = {
            "test_case_list": test_case_list,
            "test_suite_name": test_suite_name,
            "ref_test_software": ref_test_software,
            "product_composition_id": product_composition_id,
            "status": status,
            "pipeline_software_under_test": pipeline_software_under_test,
            "runner_account": self._auth.runner_account,
        }
        
        if url_test_software:
            payload["url_test_software"] = url_test_software
        
        response = self._session.post(
            f"{self._api_url}/test-runs",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        
        data = response.json()
        data["url"] = f"{self._base_url}/runs/{data.get('id')}"
        return data

    def get_test_run(self, run_id: int) -> Dict[str, Any]:
        """
        Get test run details by ID.
        
        Args:
            run_id: Test run ID.
        
        Returns:
            Test run details.
        """
        response = self._session.get(
            f"{self._api_url}/test-runs/{run_id}",
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def update_test_run(
        self,
        run_id: int,
        status: Optional[str] = None,
        results: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Update a test run with results or status.
        
        Args:
            run_id: Test run ID.
            status: New status (Completed, Failed, etc.).
            results: List of test results.
        
        Returns:
            Updated test run details.
        """
        payload = {}
        if status:
            payload["status"] = status
        if results:
            payload["results"] = results
        
        response = self._session.patch(
            f"{self._api_url}/test-runs/{run_id}",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def list_test_runs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        List test runs with optional filtering.
        
        Args:
            status: Filter by status.
            limit: Maximum number of results.
            offset: Offset for pagination.
        
        Returns:
            List of test run summaries.
        """
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        
        response = self._session.get(
            f"{self._api_url}/test-runs",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("runs", [])

    # ==================== Results ====================

    def upload_results(self, results: List[Any]) -> bool:
        """
        Upload test results to the backend.
        
        Args:
            results: List of test results (TestMethodResult or dicts).
        
        Returns:
            True if upload was successful.
        """
        # Convert results to dicts if needed
        result_dicts = []
        for r in results:
            if hasattr(r, "to_dict"):
                result_dicts.append(r.to_dict())
            elif isinstance(r, dict):
                result_dicts.append(r)
            else:
                result_dicts.append({"data": str(r)})
        
        response = self._session.post(
            f"{self._api_url}/results",
            json={"results": result_dicts},
            timeout=60,
        )
        return response.status_code in (200, 201)

    def upload_artifact(
        self,
        file_path: str,
        run_id: Optional[int] = None,
        test_case: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upload an artifact (trace file, log, etc.) to the backend.
        
        Args:
            file_path: Path to the file to upload.
            run_id: Optional test run ID to associate.
            test_case: Optional test case name to associate.
        
        Returns:
            Upload response with artifact ID and URL.
        """
        with open(file_path, "rb") as f:
            files = {"file": f}
            data = {}
            if run_id:
                data["run_id"] = run_id
            if test_case:
                data["test_case"] = test_case
            
            # Remove Content-Type header for multipart upload
            headers = {k: v for k, v in self._session.headers.items() if k != "Content-Type"}
            if self._auth.token:
                headers["Authorization"] = f"Bearer {self._auth.token}"
            
            response = requests.post(
                f"{self._api_url}/uploads",
                files=files,
                data=data,
                headers=headers,
                timeout=120,
            )
        
        response.raise_for_status()
        return response.json()

    # ==================== Runners ====================

    def register_runner(
        self,
        username: str,
        password: str,
        socket_port: int = 53035,
    ) -> Dict[str, Any]:
        """
        Register a new runner with the backend.
        
        Args:
            username: Runner account name.
            password: Password for registration.
            socket_port: Socket port for runner communication.
        
        Returns:
            Registration response with token.
        """
        response = self._session.post(
            f"{self._api_url}/runners/register",
            json={
                "username": username,
                "password": password,
                "socket_port": socket_port,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def get_runner_status(self) -> Dict[str, Any]:
        """
        Get current runner status.
        
        Returns:
            Runner status information.
        """
        response = self._session.get(
            f"{self._api_url}/runners/status",
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def heartbeat(self) -> bool:
        """
        Send a heartbeat to indicate runner is alive.
        
        Returns:
            True if heartbeat was acknowledged.
        """
        try:
            response = self._session.post(
                f"{self._api_url}/runners/heartbeat",
                json={"runner_account": self._auth.runner_account},
                timeout=10,
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    # ==================== Health ====================

    def health_check(self) -> bool:
        """
        Check if the backend is reachable.
        
        Returns:
            True if backend is healthy.
        """
        try:
            response = self._session.get(
                f"{self._api_url}/health",
                timeout=10,
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def get_version(self) -> str:
        """
        Get backend version.
        
        Returns:
            Version string.
        """
        response = self._session.get(
            f"{self._api_url}/version",
            timeout=10,
        )
        response.raise_for_status()
        return response.json().get("version", "unknown")
