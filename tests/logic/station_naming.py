"""The name Bud reports is the name the station keeps, with Bud and the station's identity mocked."""

from unittest.mock import MagicMock

from budtestlibrary import BudTestCase

from bud_runner.runner_manager import RunnerManager
from tests.config import StationNaming as config
from tests.parameters import StationNaming as parameters


class StationNaming(BudTestCase):
    """RunnerManager registers and renames a station through a mocked Bud client and identity."""

    def manager(self, answer: dict):
        """A RunnerManager whose identity and Bud client are mocks; Bud answers registration with
        answer."""
        auth = MagicMock()
        auth.backend_url = config.BACKEND_URL
        auth.runner_account = config.TYPED_NAME
        auth.runner_token = config.TOKEN
        auth.socket_port = config.PORT
        manager = RunnerManager(auth)
        manager._client = MagicMock()
        manager._client.register_runner.return_value = answer
        return manager, auth

    def saved_names(self, auth) -> list:
        """The usernames the station saved its identity under, in order."""
        return [call.kwargs.get("username") for call in auth.save_identity.call_args_list]

    def bud_registration_stores_the_name_bud_assigned(self):
        """A registration Bud answers with another name returns and saves that name."""
        manager, auth = self.manager(parameters.ASSIGNED_ANSWER)
        result = manager.register(
            username=config.TYPED_NAME, password=parameters.PASSWORD, socket_port=config.PORT
        )
        self.assertEqual(
            result["account"], parameters.ASSIGNED, "the registration returns the name Bud assigned"
        )
        self.assertEqual(
            self.saved_names(auth),
            [parameters.ASSIGNED],
            "the identity is saved once under that name",
        )

    def bud_registration_keeps_its_own_name_when_bud_names_none(self):
        """A registration Bud answers without a name returns and saves the station's own name."""
        manager, auth = self.manager(parameters.NAMELESS_ANSWER)
        result = manager.register(
            username=parameters.OWN_NAME, password=parameters.PASSWORD, socket_port=config.PORT
        )
        self.assertEqual(
            result["account"],
            parameters.OWN_NAME,
            "the registration returns the station's own name",
        )
        self.assertEqual(
            self.saved_names(auth),
            [parameters.OWN_NAME],
            "the identity is saved under its own name",
        )

    def bud_a_heartbeat_reporting_a_new_name_rewrites_the_identity(self):
        """A heartbeat naming the station differently saves the identity once under the new name with
        the same token and port."""
        manager, auth = self.manager(parameters.ASSIGNED_ANSWER)
        manager._adopt_renamed_account(parameters.RENAMED)
        self.assertEqual(
            auth.save_identity.call_count, parameters.ONE, "the identity is saved once"
        )
        self.assertEqual(
            auth.save_identity.call_args.kwargs,
            {"username": parameters.RENAMED, "token": config.TOKEN, "port": config.PORT},
            "the new name keeps the token and the port",
        )

    def bud_a_heartbeat_reporting_the_same_name_rewrites_nothing(self):
        """A heartbeat naming the station as it is named, or naming nothing, saves nothing."""
        manager, auth = self.manager(parameters.ASSIGNED_ANSWER)
        manager._adopt_renamed_account(config.TYPED_NAME)
        manager._adopt_renamed_account(None)
        self.assertEqual(auth.save_identity.call_count, parameters.NONE, "nothing is saved")
