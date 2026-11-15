"""Doubles of budtestlibrary's result objects: an assertion, a step result and a test class result."""


class Assertion:
    """A double of an assertion result."""

    def __init__(self, passed: bool, message: str):
        self.passed = passed
        self.message = message

    def to_dict(self):
        """The assertion as a dict."""
        return {"passed": self.passed, "message": self.message}


class MethodResult:
    """A double of a step's result."""

    def __init__(
        self, method_name, passed, assertions, duration=0.5, err=None, tb=None, summary_message=None
    ):
        self.method_name = method_name
        self.passed = passed
        self.assertions = assertions
        self.duration_seconds = duration
        self.error_message = err
        self.traceback = tb
        self.summary_message = summary_message

    def to_dict(self):
        """The step result as a dict."""
        return {
            "method_name": self.method_name,
            "passed": self.passed,
            "assertions": [a.to_dict() for a in self.assertions],
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "traceback": self.traceback,
            "summary_message": self.summary_message,
        }


class RunResult:
    """A double of a test class's result."""

    def __init__(self, test_class, method_results, passed=None, err=None):
        self.test_class = test_class
        self.method_results = method_results
        self.passed = passed if passed is not None else all(m.passed for m in method_results)
        self.duration_seconds = sum(m.duration_seconds for m in method_results)
        self.error_message = err


class RecordingClient:
    """A double of Bud's client that records what a formatter or plugin sends."""

    def __init__(self, run_id: int, failure: Exception | None = None):
        self.calls: list = []
        self.run_id = run_id
        self.failure = failure

    def upload_results_payload(self, payload):
        """Record the results; raise the failure when one is set."""
        self.calls.append(("results", payload))
        if self.failure is not None:
            raise self.failure
        return {"test_run_id": self.run_id}

    def update_test_run(self, run_id, skipped_tests=None):
        """Record the run update."""
        self.calls.append(("update", run_id, {"skipped_tests": skipped_tests}))
