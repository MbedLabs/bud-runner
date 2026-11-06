"""What the adapters share: the Bloom test case id of a tag, and the skipped test cases of a run."""

import pytest

from bud_runner.reporting import bloom_tc_id, skipped_test_cases


@pytest.mark.parametrize(
    "written, sent",
    [
        ("PRJ-001", "PRJ-TC-001"),
        (" PRJ-001 ", "PRJ-TC-001"),
        ("PRJ-TC-001", "PRJ-TC-001"),
        ("prj-tc-001", "prj-tc-001"),
        ("PRJ-a_7", "PRJ-TC-a_7"),
        ("PRJ001", "PRJ001"),
        ("-001", "-001"),
        ("PRJ-", "PRJ-"),
    ],
)
def test_a_short_id_gets_the_test_case_type(written, sent):
    assert bloom_tc_id(written) == sent


def _result(test_class, skipped):
    return {"test_class": test_class, "metadata": {"skipped": True} if skipped else {}}


def test_skipped_test_cases_are_counted_as_bud_counts_them():
    assert skipped_test_cases([]) == 0
    assert skipped_test_cases([_result("a", True), _result("b", False)]) == 1
    assert skipped_test_cases([_result("feature", True), _result("feature", False)]) == 0
    assert skipped_test_cases([_result("feature", True), _result("feature", True), _result("other", True)]) == 2
    assert skipped_test_cases([{"test_class": "a"}]) == 0
