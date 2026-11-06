"""The name Bud reports is the name the station keeps, with Bud and the station's identity mocked."""

from unittest.mock import MagicMock

from budtestlibrary import BudTestCase

from bud_runner.runner_manager import RunnerManager
from tests.budtests.config import StationNaming as c
from tests.budtests.parameters import StationNaming as p


class StationNaming(BudTestCase):
    """RunnerManager registers and renames a station through a mocked Bud client and identity."""

    def manager(self, answer: dict):
        """A RunnerManager whose identity and Bud client are mocks; Bud answers registration with
        answer."""
        auth = MagicMock()
        auth.backend_url = c.BACKEND_URL
        auth.runner_account = c.TYPED_NAME
        auth.runner_token = c.TOKEN
        auth.socket_port = c.PORT
        manager = RunnerManager(auth)
        manager._client = MagicMock()
        manager._client.register_runner.return_value = answer
        return manager, auth

    def saved_names(self, auth) -> list:
        """The usernames the station saved its identity under, in order."""
        return [call.kwargs.get("username") for call in auth.save_identity.call_args_list]

    def bud_registration_stores_the_name_bud_assigned(self):
        """A registration Bud answers with another name returns and saves that name."""
        manager, auth = self.manager(p.ASSIGNED_ANSWER)
        result = manager.register(username=c.TYPED_NAME, password=p.PASSWORD, socket_port=c.PORT)
        self.assertEqual(result["account"], p.ASSIGNED, "the registration returns the name Bud assigned")
        self.assertEqual(self.saved_names(auth), [p.ASSIGNED], "the identity is saved once under that name")

    def bud_registration_keeps_its_own_name_when_bud_names_none(self):
        """A registration Bud answers without a name returns and saves the station's own name."""
        manager, auth = self.manager(p.NAMELESS_ANSWER)
        result = manager.register(username=p.OWN_NAME, password=p.PASSWORD, socket_port=c.PORT)
        self.assertEqual(result["account"], p.OWN_NAME, "the registration returns the station's own name")
        self.assertEqual(self.saved_names(auth), [p.OWN_NAME], "the identity is saved under its own name")

    def bud_a_heartbeat_reporting_a_new_name_rewrites_the_identity(self):
        """A heartbeat naming the station differently saves the identity once under the new name with
        the same token and port."""
        manager, auth = self.manager(p.ASSIGNED_ANSWER)
        manager._adopt_renamed_account(p.RENAMED)
        self.assertEqual(auth.save_identity.call_count, p.ONE, "the identity is saved once")
        self.assertEqual(
            auth.save_identity.call_args.kwargs,
            {"username": p.RENAMED, "token": c.TOKEN, "port": c.PORT},
            "the new name keeps the token and the port",
        )

    def bud_a_heartbeat_reporting_the_same_name_rewrites_nothing(self):
        """A heartbeat naming the station as it is named, or naming nothing, saves nothing."""
        manager, auth = self.manager(p.ASSIGNED_ANSWER)
        manager._adopt_renamed_account(c.TYPED_NAME)
        manager._adopt_renamed_account(None)
        self.assertEqual(auth.save_identity.call_count, p.NONE, "nothing is saved")
