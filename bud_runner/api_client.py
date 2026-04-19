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


def _method_result_to_row(
    test_class: str,
    method_result: Any,
    test_run_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Map a budtestlibrary TestMethodResult (or dict) → TestResultCreate row.

    The backend (app.schemas.TestResultCreate) expects the flat fields
    ``test_class``, ``test_method``, ``passed``, ``duration_seconds``,
    ``error_message``, ``traceback``, ``assertions``, ``metadata``.
    """
    if hasattr(method_result, "to_dict"):
        m = method_result.to_dict()
    elif isinstance(method_result, dict):
        m = method_result
    else:
        m = {"method_name": str(method_result), "passed": False}

    assertions = m.get("assertions")
    if assertions is not None and not isinstance(assertions, list):
        assertions = None

    row: Dict[str, Any] = {
        "test_class": test_class,
        "test_method": m.get("method_name") or m.get("test_method") or "unknown",
        "passed": bool(m.get("passed", False)),
        "duration_seconds": float(m.get("duration_seconds", 0.0) or 0.0),
        "error_message": m.get("error_message"),
        "traceback": m.get("traceback"),
        "assertions": assertions,
        "metadata": m.get("metadata"),
    }
    # TestResultCreate has test_run_id at the envelope level; include it per
    # row too so callers inspecting the payload see the association.
    if test_run_id is not None:
        row["test_run_id"] = test_run_id
    return row


def _flatten_results(
    results: List[Any],
    test_run_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Flatten TestRunResult / TestMethodResult / dict lists to TestResultCreate rows.

    Handles three shapes:
      * ``TestRunResult`` (per class, with nested ``method_results``)
      * ``TestMethodResult`` (flat, per method — needs a synthesised class name)
      * Already-flat dicts (passed through after light normalisation).
    """
    rows: List[Dict[str, Any]] = []

    for r in results:
        # 1) TestRunResult (class-level with nested method_results)
        test_class = getattr(r, "test_class", None)
        method_results = getattr(r, "method_results", None)

        if test_class is None and isinstance(r, dict):
            test_class = r.get("test_class")
            method_results = r.get("method_results")

        if test_class and method_results is not None:
            if method_results:
                for mr in method_results:
                    rows.append(_method_result_to_row(test_class, mr, test_run_id))
            else:
                # Class ran but produced no method-level results (e.g. setup
                # crash). Preserve the class-level failure signal.
                cls_err = getattr(r, "error_message", None)
                if isinstance(r, dict):
                    cls_err = cls_err or r.get("error_message")
                rows.append({
                    "test_class": test_class,
                    "test_method": "__class__",
                    "passed": bool(
                        getattr(r, "passed", None)
                        if not isinstance(r, dict)
                        else r.get("passed", False)
                    ),
                    "duration_seconds": float(
                        getattr(r, "duration_seconds", 0.0)
                        if not isinstance(r, dict)
                        else r.get("duration_seconds", 0.0) or 0.0
                    ),
                    "error_message": cls_err,
                    "traceback": None,
                    "assertions": None,
                    "metadata": None,
                    **({"test_run_id": test_run_id} if test_run_id is not None else {}),
                })
            continue

        # 2) Plain TestMethodResult (no enclosing class)
        if hasattr(r, "method_name") or (isinstance(r, dict) and "method_name" in r):
            rows.append(_method_result_to_row("UnknownTestClass", r, test_run_id))
            continue

        # 3) Already a TestResultCreate-shaped dict
        if isinstance(r, dict) and "test_method" in r and "test_class" in r:
            row = dict(r)
            if test_run_id is not None and "test_run_id" not in row:
                row["test_run_id"] = test_run_id
            rows.append(row)
            continue

        # 4) Fallback: unknown shape → still emit a placeholder row so the
        # upload does not silently drop data.
        rows.append({
            "test_class": "UnknownTestClass",
            "test_method": "unknown",
            "passed": False,
            "duration_seconds": 0.0,
            "error_message": f"Unrecognised result shape: {type(r).__name__}",
            "traceback": None,
            "assertions": None,
            "metadata": None,
            **({"test_run_id": test_run_id} if test_run_id is not None else {}),
        })

    return rows


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
        total_tests: Optional[int] = None,
        passed_tests: Optional[int] = None,
        failed_tests: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Update a test run with results or status.
        
        Args:
            run_id: Test run ID.
            status: New status (Completed, Failed, etc.).
            results: List of test results.
            total_tests: Total number of tests.
            passed_tests: Number of passed tests.
            failed_tests: Number of failed tests.
        
        Returns:
            Updated test run details.
        """
        payload = {}
        if status:
            payload["status"] = status
        if results:
            payload["results"] = results
        if total_tests is not None:
            payload["total_tests"] = total_tests
        if passed_tests is not None:
            payload["passed_tests"] = passed_tests
        if failed_tests is not None:
            payload["failed_tests"] = failed_tests
        
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

    def upload_results(
        self,
        results: List[Any],
        test_run_id: Optional[int] = None,
    ) -> bool:
        """
        Upload test results to the backend.

        Flattens nested TestRunResult → TestMethodResult structures into a flat
        list of TestResultCreate-compatible dicts expected by
        ``POST /api/results`` (see backend schemas.ResultsUpload).

        Args:
            results: List of TestRunResult / TestMethodResult / dicts. Nested
                method_results are expanded; top-level class-level failures
                are included as well so class-level errors remain visible.
            test_run_id: Optional TestRun id to associate every row with.

        Returns:
            True if upload was successful.
        """
        flat_rows = _flatten_results(results, test_run_id=test_run_id)

        response = self._session.post(
            f"{self._api_url}/results",
            json={"results": flat_rows, "test_run_id": test_run_id},
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

        The backend protects ``POST /api/runners/register`` with a shared
        secret delivered in the ``X-API-Key`` header (see backend
        ``core.deps.require_runner_api_key``). We read it from
        ``RUNNER_API_KEY`` (env var or ``app.properties``). If it's not set
        the request is still sent and will surface a clear 401 from the
        backend instead of silently doing nothing.

        Args:
            username: Runner account name.
            password: Password for registration.
            socket_port: Socket port for runner communication.

        Returns:
            Registration response with token.

        Raises:
            RuntimeError: If RUNNER_API_KEY is not configured.
            requests.HTTPError: If the backend rejects the request.
        """
        api_key = self._auth.runner_api_key
        if not api_key:
            raise RuntimeError(
                "RUNNER_API_KEY is not set. Export RUNNER_API_KEY (the shared "
                "secret from the Bud backend settings) or add runnerApiKey to "
                "app.properties before running 'bud_runner register'."
            )

        headers = {"X-API-Key": api_key}
        response = self._session.post(
            f"{self._api_url}/runners/register",
            json={
                "username": username,
                "password": password,
                "socket_port": socket_port,
            },
            headers=headers,
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
