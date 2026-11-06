"""Values the bud-runner unit suites use: inputs and Bud's answers."""


class StationNaming:
    """Values of the station_naming suite."""

    PASSWORD = "p"
    ASSIGNED = "bench-a"
    OWN_NAME = "lab-station-01"
    RENAMED = "bench-a-renamed"
    REGISTERED_TOKEN = "t"
    ASSIGNED_ANSWER = {"account": ASSIGNED, "token": REGISTERED_TOKEN}
    NAMELESS_ANSWER = {"token": REGISTERED_TOKEN}
    ONE = 1
    NONE = 0
