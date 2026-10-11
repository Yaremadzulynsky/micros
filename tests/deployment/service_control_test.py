"""Individual restart uses live identity, never whole-application controls."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.deployment.service_control import restart_service
from micros_tooling.storage.packages import PackageError


def status():
    return dict(service_restart=1, service_boot="99", activation=dict(pending=0, good=0, sequence=7,
                good_sha256="a" * 64), services=[
        dict(instance="1", state="Running", result=0),
        dict(instance="2", state="Running", result=0)])


class RestartTest(unittest.TestCase):
    def remote(self):
        before = status()
        after = copy.deepcopy(before)
        after["services"][0]["instance"] = "4294967297"
        remote = Mock()
        remote.status.side_effect = [before, after]
        remote.request.return_value = dict(service_index=0, result=0)
        return remote, before, after

    def test_restart_only_selected_instance(self):
        remote, before, after = self.remote()
        self.assertEqual(restart_service(remote, 0)["status"], after)
        remote.request.assert_called_once_with("POST", "/v1/platform-command",
            f'SERVICE RESTART 0 7 {"a" * 64} 1 99'.encode())
        remote.deployment_session.assert_not_called()

    def test_reject_before_mutation(self):
        for changes, index in [(dict(service_restart=0), 0), ({}, -1), ({}, 2),
                               (dict(deployment_session="busy"), 0),
                               (dict(physical_recovery=True), 0)]:
            with self.subTest(changes=changes, index=index):
                remote, before, _ = self.remote()
                before.update(changes)
                with self.assertRaises(PackageError): restart_service(remote, index)
                remote.request.assert_not_called()
        remote, before, _ = self.remote()
        before["activation"]["pending"] = 1
        with self.assertRaises(PackageError): restart_service(remote, 0)
        remote.request.assert_not_called()

    def test_failure_and_uncertain_outcome_are_not_retried(self):
        for failure in [TimeoutError("unknown outcome"), PackageError("rejected")]:
            remote, _, _ = self.remote()
            remote.request.side_effect = failure
            with self.assertRaises(type(failure)): restart_service(remote, 0)
            self.assertEqual(remote.request.call_count, 1)

    def test_confirmation_detects_failed_start_or_changed_peer(self):
        for index, field, value in [(0, "state", "Failed"), (0, "instance", "1"),
                                    (1, "instance", "999")]:
            remote, _, after = self.remote()
            after["services"][index][field] = value
            with self.assertRaises(PackageError): restart_service(remote, 0)
            self.assertEqual(remote.request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
