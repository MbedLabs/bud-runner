"""--verbose shows the suites' DEBUG step lifecycle, in run-tests and in a run claim-run
executes."""

import support
from budtestlibrary import BudTestCase, parameterized

DEBUG_LINE = "Entering setUp for bud_mark"


class Verbose(BudTestCase):
    """DEBUG lifecycle lines appear only with -v / --verbose."""

    def _debug_lines(self, output: str, flag: tuple, command: str) -> None:
        """Record that the suite's DEBUG setUp line is shown exactly when a verbose flag is
        given."""
        if flag:
            support.says(self, DEBUG_LINE, output, f"{command} {flag[0]}")
        else:
            support.check_not_in(
                self,
                DEBUG_LINE,
                output,
                f"{command} without -v does not show the suite's DEBUG line {DEBUG_LINE!r}",
                f"{command} without -v shows the suite's DEBUG line {DEBUG_LINE!r}",
            )

    @parameterized([(), ("-v",), ("--verbose",)])
    def bud_spawned_suite_receives_the_selected_logging_level(self, *flag):
        """run-tests --no-upload: the step's DEBUG setUp line appears only with the flag."""
        case = support.Case("verbose")
        command = "bud-runner run-tests --no-upload"
        done = case.run_tests(support.marker_suite(case), "--no-upload", *flag)
        support.exits(self, done, 0, f"{command} {' '.join(flag)}".strip())
        support.check(
            self,
            (case.cwd / "ran.marker").exists(),
            True,
            f"{command} ran the marker suite: ran.marker exists",
            f"{command} did not run the marker suite: no ran.marker",
        )
        self._debug_lines(done.out + done.err, flag, command)

    @parameterized([(), ("-v",), ("--verbose",)])
    def bud_claim_run_forwards_verbosity_to_its_execution(self, *flag):
        """claim-run of a queued run: the run's DEBUG setUp line appears only with the flag."""
        bud = support.Bud()
        station = bud.station(f"verbose{len(flag) and flag[0]}")
        case = support.Case("claim-verbose")
        test_list = support.marker_suite(case)
        seed = case.run_tests(test_list, station=station)
        support.exits(
            self, seed, 0, "a first run-tests that makes the marker test known to Bud", stop=True
        )
        bud.queue(["demo_marker.MarkerTest"], station.name)
        command = "bud-runner claim-run"
        done = case.bud_runner("claim-run", "-u", station.name, "-b", station.backend, *flag)
        support.exits(self, done, 0, f"{command} {' '.join(flag)}".strip())
        support.says(self, "✓ Claimed run", done.out, command)
        self._debug_lines(done.out + done.err, flag, command)
