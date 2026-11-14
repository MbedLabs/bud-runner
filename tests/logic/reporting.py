"""What the adapters share: the Bloom test case id of a tag and the skipped test cases of a run."""

from budtestlibrary import BudTestCase, parameterized

from bud_runner.reporting import bloom_tc_id, skipped_test_cases
from tests.parameters import Reporting as parameters


class Reporting(BudTestCase):
    """bloom_tc_id() and skipped_test_cases() on the inputs the adapters hand them."""

    @parameterized(parameters.SHORT_IDS)
    def bud_a_short_id_gets_the_test_case_type(self, written, sent):
        """A short id gets the TC type; a full or malformed id is sent as written."""
        self.assertEqual(bloom_tc_id(written), sent, f"{written!r} is sent as {sent!r}")

    @parameterized(parameters.SKIPPED_COUNTS)
    def bud_skipped_test_cases_are_counted_as_bud_counts_them(self, results, skipped):
        """A test class counts as skipped only when every one of its results is skipped."""
        self.assertEqual(
            skipped_test_cases(results), skipped, f"{len(results)} results count {skipped} skipped"
        )
