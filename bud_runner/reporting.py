"""Upload of a test framework's run to Bud, shared by the framework adapters.

The Robot listener and the pytest plugin collect a run in their own way and hand the
upload to ``send_run``: the results go to Bud with the station's credentials, a failed
upload is spooled for the next bud-runner invocation, the skipped count and the run's
files follow, and every problem is printed as a warning on stderr and nothing is raised.
"""

import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

BodyBuilder = Callable[[Optional[str], Optional[int]], Optional[Dict[str, Any]]]


def send_run(
    build_body: BodyBuilder,
    *,
    framework: str,
    backend: Optional[str] = None,
    test_run_id: Optional[int] = None,
    skipped: int = 0,
    files: Iterable[Path] = (),
) -> None:
    """Upload one collected run to Bud.

    ``build_body`` receives the station's runner account and the product id bud-runner
    reads from app.properties and returns the ResultsUpload body, or None when nothing
    ran. ``framework`` names the run in the messages (``Robot``, ``pytest``).
    """
    from bud_runner.api_client import BudAPIClient
    from bud_runner.auth import AuthManager
    from bud_runner.cli import _spool_results_payload

    auth = AuthManager(backend_url=backend)
    client = BudAPIClient(auth)
    body = build_body(auth.runner_account, auth.product_id)
    if body is None:
        print(f"[bud] The {framework} run produced no test results; nothing uploaded.", file=sys.stderr)
        return
    try:
        response = client.upload_results_payload(body)
    except Exception as exc:
        spool = _spool_results_payload(body)
        print(f"[bud] Upload failed ({exc}); results spooled to {spool}", file=sys.stderr)
        return
    run_id = test_run_id
    if isinstance(response, dict) and response.get("test_run_id"):
        run_id = response["test_run_id"]
    print(f"[bud] {framework} results uploaded to Bud run {run_id}", file=sys.stderr)
    if run_id and skipped:
        try:
            client.update_test_run(run_id=run_id, skipped_tests=skipped)
        except Exception as exc:
            print(f"[bud] Could not record skipped tests: {exc}", file=sys.stderr)
    if not run_id:
        return
    for path in files:
        if not path.is_file():
            continue
        try:
            client.upload_artifact(str(path), run_id=run_id)
        except Exception as exc:
            print(f"[bud] Could not upload {path.name}: {exc}", file=sys.stderr)
