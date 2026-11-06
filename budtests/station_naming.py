"""The name Bud gives a station is the name the station uses: at registration and after a rename in
Bud."""

import time

import support
from budtestlibrary import BudTestCase


class StationNaming(BudTestCase):
    """register against keys with and without a station name; the daemon adopting a rename made in
    Bud."""

    def setUpClass(self):
        self.bud = support.Bud()

    def bud_registration_stores_the_name_bud_assigned(self):
        """A key minted with a station name: register -u <another name> is registered and saved
        under Bud's name."""
        name = self.bud.free_station_name()
        key = self.bud.mint_key(name)
        case = support.Case("named-key")
        support.pace_registration()
        command = f"bud-runner register -u typed-on-the-bench with a key reserving {name}"
        done = case.bud_runner(
            "register",
            "-u",
            "typed-on-the-bench",
            "-p",
            "station-password-1",
            "-b",
            self.bud.url,
            "--api-key",
            key,
            "--no-start",
        )
        support.exits(self, done, 0, command)
        support.says(self, f"✓ Registered as {name}.", done.out, command)
        saved = sorted(case.vault())
        support.check(
            self,
            saved,
            [name],
            f"the identity vault holds only {name}, the name Bud assigned",
            f"the identity vault holds {saved}, not only {name}",
        )

    def bud_registration_keeps_its_own_name_when_bud_names_none(self):
        """A key without a station name: the station is registered and saved under the name
        typed."""
        name = self.bud.free_station_name()
        key = self.bud.mint_key()
        case = support.Case("unnamed-key")
        support.pace_registration()
        command = f"bud-runner register -u {name} with a key that reserves no name"
        done = case.bud_runner(
            "register",
            "-u",
            name,
            "-p",
            "station-password-1",
            "-b",
            self.bud.url,
            "--api-key",
            key,
            "--no-start",
        )
        support.exits(self, done, 0, command)
        saved = sorted(case.vault())
        support.check(
            self,
            saved,
            [name],
            f"the identity vault holds only {name}, the name typed",
            f"the identity vault holds {saved}, not only {name}",
        )
        listed = [s["account"] for s in self.bud.stations()]
        support.check_in(
            self,
            name,
            listed,
            f"Bud lists the station under the typed name {name}",
            f"Bud does not list {name}; it lists {listed}",
        )

    def bud_a_heartbeat_reporting_a_new_name_rewrites_the_identity(self):
        """The daemon runs, the station is renamed in Bud, and after a heartbeat the vault holds the
        new name with the same token."""
        station = self.bud.station("renamed")
        case = support.Case("rename")
        case.give_station(station)
        running = case.start(
            support.PYTHON,
            "-m",
            "bud_runner",
            "daemon",
            "-u",
            station.name,
            "--interval",
            "2",
            "--port",
            support.closed_port(),
        )
        try:
            support.wait_for(
                lambda: any(
                    s["account"] == station.name and s["is_online"] for s in self.bud.stations()
                ),
                timeout=30,
            )
            new_name = self.bud.free_station_name()
            answer = self.bud.request(
                "PATCH", f"/runners/{station.name}", json={"account": new_name}
            )
            support.need(
                self,
                answer.status_code,
                200,
                f"Bud renames station {station.name} to {new_name}",
                f"Bud answers {answer.status_code} to renaming {station.name}: {answer.text[:300]}",
            )
            support.wait_for(lambda: new_name in case.vault(), timeout=30)
        finally:
            running.stop()
        saved = sorted(case.vault())
        support.check_in(
            self,
            new_name,
            saved,
            f"after a heartbeat the identity vault holds the new name {new_name}",
            f"30 s after the rename the identity vault holds {saved}, without {new_name}",
        )
        support.check(
            self,
            case.vault().get(new_name, {}).get("token") == station.token,
            True,
            f"{new_name} keeps the station's token in the vault",
            f"{new_name} does not carry the station's token in the vault",
        )
        support.says(
            self,
            f"Renamed in Bud: {station.name} is now {new_name}",
            running.out,
            "the daemon log",
        )

    def bud_a_heartbeat_reporting_the_same_name_rewrites_nothing(self):
        """Two heartbeats without a rename leave the vault file unchanged."""
        station = self.bud.station("steady")
        case = support.Case("steady")
        case.give_station(station)
        vault = case.home / ".bud" / "config.json"
        before = vault.read_bytes()
        running = case.start(
            support.PYTHON,
            "-m",
            "bud_runner",
            "daemon",
            "-u",
            station.name,
            "--interval",
            "2",
            "--port",
            support.closed_port(),
        )
        try:
            support.wait_for(
                lambda: any(
                    s["account"] == station.name and s["is_online"] for s in self.bud.stations()
                ),
                timeout=30,
            )
            time.sleep(5)
        finally:
            running.stop()
        support.check(
            self,
            vault.read_bytes() == before,
            True,
            "heartbeats that report the same name leave the identity vault byte for byte unchanged",
            "heartbeats that report the same name rewrote the identity vault",
        )
