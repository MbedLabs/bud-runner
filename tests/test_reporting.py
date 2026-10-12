"""The Bloom test case id of a bloom tag, as budtestlibrary's BloomMetaData builds it."""

import pytest

from bud_runner.reporting import bloom_tc_id


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
