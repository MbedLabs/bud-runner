"""What the framework adapters share: the Bloom test case id of a tag, and the skipped test cases of
a run as Bud counts them."""

import support
from budtestlibrary import BudTestCase, parameterized

from bud_runner.reporting import bloom_tc_id, send_run, skipped_test_cases


def _result(test_class, skipped):
    """Return a result row of a class, skipped or not."""
    return {
        "test_class": test_class,
        "test_method": "check",
        "passed": not skipped,
        "duration_seconds": 0.0,
        "metadata": {"skipped": True} if skipped else {},
    }


class Reporting(BudTestCase):
    """bloom_tc_id for written ids; skipped_test_cases against the count Bud keeps for an uploaded
    run."""

    @parameterized(
        [
            ("PRJ-001", "PRJ-TC-001"),
            (" PRJ-001 ", "PRJ-TC-001"),
            ("PRJ-TC-001", "PRJ-TC-001"),
            ("prj-tc-001", "prj-tc-001"),
            ("PRJ-a_7", "PRJ-TC-a_7"),
            ("PRJ001", "PRJ001"),
            ("-001", "-001"),
            ("PRJ-", "PRJ-"),
        ]
    )
    def bud_a_short_id_gets_the_test_case_type(self, written, sent):
        """A project-number id gets the TC type; an id that names it, or has no project part, is
        kept."""
        got = bloom_tc_id(written)
        support.check(
            self,
            got,
            sent,
            f"bloom_tc_id turns the written id {written!r} into the Bloom test case id {sent!r}",
            f"bloom_tc_id turns the written id {written!r} into {got!r}, not {sent!r}",
        )

    def bud_skipped_test_cases_are_counted_as_bud_counts_them(self):
        """A test case counts as skipped when all its results are; the count of an uploaded run
        equals Bud's."""
        for label, results, expected in [
            ("no results", [], 0),
            ("class a skipped and class b ran", [_result("a", True), _result("b", False)], 1),
            (
                "class feature with one skipped and one ran result",
                [_result("feature", True), _result("feature", False)],
                0,
            ),
            (
                "class feature skipped twice and class other skipped",
                [_result("feature", True), _result("feature", True), _result("other", True)],
                2,
            ),
            ("one result without metadata", [{"test_class": "a"}], 0),
        ]:
            got = skipped_test_cases(results)
            support.check(
                self,
                got,
                expected,
                f"skipped_test_cases counts {expected} skipped test cases for {label}",
                f"skipped_test_cases counts {got} skipped test cases for {label}, not {expected}",
            )
        bud = support.Bud()
        station = bud.station("main")
        results = [
            _result("feature", True),
            _result("feature", True),
            _result("other", True),
            _result("ran", False),
            _result("mixed", True),
            _result("mixed", False),
        ]
        case = support.Case("skipped-count")
        with support.Isolated(
            case, {"BUD_RUNNER_TOKEN": station.token, "BUD_RUNNER_ACCOUNT": station.name}
        ):
            reached = send_run(
                lambda account, product: {
                    "results": results,
                    "runner_account": account,
                    "test_suite_name": "Skipped count",
                },
                framework="Demo",
                backend=bud.url,
            )
        support.need(
            self,
            reached,
            True,
            "send_run reaches Bud with the run of six results",
            "send_run does not reach Bud with the run of six results",
        )
        run = bud.runs()[0]
        support.need(
            self,
            run["name"],
            "Unknown Project - Skipped count",
            "the newest run in Bud is the one send_run sent, Unknown Project - Skipped count",
            f"the newest run in Bud is {run['name']!r}, not the one send_run sent",
        )
        counted = skipped_test_cases(results)
        support.check(
            self,
            run["skipped_tests"],
            counted,
            f"Bud counts {counted} skipped test cases on the run, as skipped_test_cases does",
            f"Bud counts {run['skipped_tests']!r} skipped test cases on the run, "
            f"skipped_test_cases {counted}",
        )
        support.check(
            self,
            run["skipped_tests"],
            2,
            "Bud counts 2 skipped test cases: feature and other are fully skipped, mixed is not",
            f"Bud counts {run['skipped_tests']!r} skipped test cases, not 2 (feature and other)",
        )
