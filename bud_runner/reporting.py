"""What the framework adapters share: the Bloom test case of a tag, and the upload of a run.

``bloom_tc_id`` reads the value of a ``bloom`` tag or marker as budtestlibrary's
``BloomMetaData`` takes it, the project and the number (``PRJ-001``), and returns the
Bloom test case id (``PRJ-TC-001``). The Robot listener, the pytest plugin and the
Behave formatter collect a run in their own way and hand the upload to ``send_run``: the
results go to Bud with the station's credentials, a failed upload is spooled for the
next bud-runner invocation, the number of skipped test cases and the run's files follow,
and every problem is printed as a warning on stderr and nothing is raised.
"""

import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

BodyBuilder = Callable[[Optional[str], Optional[int]], Optional[Dict[str, Any]]]


def bloom_tc_id(value: str) -> str:
    """The Bloom test case id a ``bloom`` tag names, as ``BloomMetaData.get_full_tc_id``
    builds it: ``PRJ-001`` becomes ``PRJ-TC-001``. A value that names the type
    (``PRJ-TC-001``, in any case) or has no project part is returned as written."""
    text = str(value).strip()
    project, dash, rest = text.partition("-")
    if not dash or not project or not rest or rest.upper().startswith("TC-"):
        return text
    return f"{project}-TC-{rest}"


def skipped_test_cases(results: Iterable[Dict[str, Any]]) -> int:
    """The test cases whose results are all skipped, counted as Bud counts its run: results
    grouped by ``test_class``, a test case skipped when every result has ``metadata.skipped``."""
    cases: Dict[str, bool] = {}
    for result in results:
        skipped = bool((result.get("metadata") or {}).get("skipped"))
        name = str(result.get("test_class"))
        cases[name] = cases.get(name, True) and skipped
    return sum(1 for all_skipped in cases.values() if all_skipped)


def send_run(
    build_body: BodyBuilder,
    *,
    framework: str,
    backend: Optional[str] = None,
    test_run_id: Optional[int] = None,
    files: Iterable[Path] = (),
) -> bool:
    """Upload one collected run to Bud; True when the results reached Bud.

    ``build_body`` receives the station's runner account and the product id bud-runner
    reads from app.properties and returns the ResultsUpload body, or None when nothing
    ran. ``framework`` names the run in the messages (``Robot``, ``pytest``). False when
    nothing was sent or the results were spooled.
    """
    from bud_runner.api_client import BudAPIClient
    from bud_runner.auth import AuthManager
    from bud_runner.cli import _spool_results_payload

    auth = AuthManager(backend_url=backend)
    client = BudAPIClient(auth)
    body = build_body(auth.runner_account, auth.product_id)
    if body is None:
        print(f"[bud] The {framework} run produced no test results; nothing uploaded.", file=sys.stderr)
        return False
    try:
        response = client.upload_results_payload(body)
    except Exception as exc:
        spool = _spool_results_payload(body)
        print(f"[bud] Upload failed ({exc}); results spooled to {spool}", file=sys.stderr)
        return False
    run_id = test_run_id
    if isinstance(response, dict) and response.get("test_run_id"):
        run_id = response["test_run_id"]
    print(f"[bud] {framework} results uploaded to Bud run {run_id}", file=sys.stderr)
    skipped = skipped_test_cases(body.get("results") or [])
    if run_id and skipped:
        try:
            client.update_test_run(run_id=run_id, skipped_tests=skipped)
        except Exception as exc:
            print(f"[bud] Could not record skipped tests: {exc}", file=sys.stderr)
    if not run_id:
        return True
    for path in files:
        if not path.is_file():
            continue
        try:
            client.upload_artifact(str(path), run_id=run_id)
        except Exception as exc:
            print(f"[bud] Could not upload {path.name}: {exc}", file=sys.stderr)
    return True
