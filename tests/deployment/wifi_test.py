"""Exercise USB provisioning UX, retry results and secret handling without hardware."""

import argparse
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from micros_tooling.communication.wifi import (
    Wifi,
    select_port,
    setup_from_terminal,
    validate_credentials,
    display_ssid,
)
from micros_tooling.storage.packages import PackageError


def status(**changes):
    return dict(
        state="connecting",
        testing=True,
        result="testing",
        reason="connection_pending",
        scan="ready",
        networks=[],
        ip="0.0.0.0",
        **changes
    )


class WifiTests(unittest.TestCase):
    def test_status_waits_for_usb_reset_reconnection(self):
        wifi = Wifi.__new__(Wifi)
        connected = {**status(), "state": "connected"}
        with patch.object(wifi, "status", side_effect=[status(), connected]), patch(
            "micros_tooling.communication.wifi.time.sleep"
        ):
            self.assertEqual(wifi.settled_status()["state"], "connected")
        with patch.object(wifi, "status", return_value=status()) as read:
            self.assertEqual(wifi.settled_status(timeout=0)["state"], "connecting")
            read.assert_called_once()

    def test_save_absent_network_and_single_fallback_commands(self):
        wifi = Wifi.__new__(Wifi)
        with patch.object(wifi, "request", return_value={}) as request:
            wifi.save(b"home", b"password")
            request.assert_called_with("WIFI ADD 686f6d65 70617373776f7264")
            wifi.save(b"phone", b"password", fallback=True)
            request.assert_called_with("WIFI FALLBACK 70686f6e65 70617373776f7264")
            wifi.forget(b"home")
            request.assert_called_with("WIFI FORGET 686f6d65")
        with patch.object(wifi, "request", return_value={"saved_networks": []}):
            self.assertEqual(wifi.saved_networks(), [])

    def test_busy_scan_retries_but_other_errors_do_not(self):
        wifi = Wifi.__new__(Wifi)
        with patch.object(wifi, "_request", side_effect=[
            {"error": "Wi-Fi operation already in progress"}, {"saved_networks": []}
        ]) as request, patch("micros_tooling.communication.wifi.time.sleep"):
            self.assertEqual(wifi.saved_networks(), [])
            self.assertEqual(request.call_count, 2)
        with patch.object(wifi, "_request", return_value={"error": "Could not save network list"}):
            with self.assertRaisesRegex(PackageError, "Could not save"):
                wifi.save(b"home", b"password")

    def test_bounds(self):
        validate_credentials(b"a" * 32, b"0" * 64)
        validate_credentials(b"test", b"")
        for ssid, password in [
            (b"", b""),
            (b"a" * 33, b""),
            (b"test", b"short"),
            (b"test", b"x" * 64),
            (b"a\0", b""),
        ]:
            with self.assertRaises(PackageError):
                validate_credentials(ssid, password)

    def test_port_ambiguity(self):
        ports = [
            argparse.Namespace(device="/dev/one", vid=0x1A86),
            argparse.Namespace(device="/dev/two", vid=0x303A),
        ]
        with patch("micros_tooling.communication.wifi.list_ports.comports", return_value=ports):
            with self.assertRaisesRegex(PackageError, "Several"):
                select_port()
            self.assertEqual(select_port("/dev/two"), "/dev/two")

    def test_success_waits_for_saved(self):
        wifi = Wifi.__new__(Wifi)
        pending = status()
        saved = {
            **pending,
            "testing": False,
            "state": "connected",
            "result": "saved",
            "ip": "192.0.2.1",
        }
        messages = []
        with patch.object(
            wifi, "request", side_effect=[pending, saved]
        ) as request, patch("micros_tooling.communication.wifi.time.sleep"):
            result = wifi.configure(b"test", b"password", messages.append)
        self.assertEqual(result["result"], "saved")
        self.assertNotIn("password", " ".join(messages))
        self.assertEqual(
            request.call_args_list[0].args[0], "WIFI SET 74657374 70617373776f7264"
        )

    def test_failure_never_reports_saved(self):
        wifi = Wifi.__new__(Wifi)
        failure = {
            **status(),
            "testing": False,
            "result": "failed_timeout",
            "reason": "authentication_failed",
        }
        with patch.object(wifi, "request", return_value=failure):
            with self.assertRaisesRegex(
                PackageError, "Previous saved settings were retained"
            ):
                wifi.configure(b"test", b"password")

    def test_cancel_restores_previous(self):
        wifi = Wifi.__new__(Wifi)
        with patch.object(
            wifi, "request", side_effect=[KeyboardInterrupt(), {}]
        ) as request:
            with self.assertRaises(KeyboardInterrupt):
                wifi.configure(b"test", b"password")
            self.assertEqual(request.call_args.args[0], "WIFI CANCEL")

    def test_password_file_preserves_spaces_and_does_not_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "password"
            path.write_bytes(b" password \n")
            args = argparse.Namespace(
                ssid="test", password_file=path, open_network=False
            )
            wifi = Wifi.__new__(Wifi)
            with patch.object(wifi, "configure", return_value={}) as configure:
                setup_from_terminal(wifi, args, lambda message: None)
                self.assertEqual(configure.call_args.args[:2], (b"test", b" password "))

    def test_no_getpass_fallback_to_echoing_stdin(self):
        args = argparse.Namespace(ssid="test", password_file=None, open_network=False)
        with patch("sys.stdin.isatty", return_value=False), patch(
            "getpass.getpass"
        ) as prompt:
            with self.assertRaisesRegex(
                PackageError, "Password entry needs a terminal"
            ):
                setup_from_terminal(None, args, lambda message: None)
            prompt.assert_not_called()

    def test_untrusted_network_names_escape_controls(self):
        self.assertNotIn("\x1b", display_ssid(b"\x1b[2J".hex()))

    def test_getpass_warning_never_falls_back_to_visible_input(self):
        import getpass

        args = argparse.Namespace(ssid="test", password_file=None, open_network=False)
        with patch("sys.stdin.isatty", return_value=True), patch(
            "getpass.getpass", side_effect=getpass.GetPassWarning()
        ):
            with self.assertRaisesRegex(PackageError, "cannot hide"):
                setup_from_terminal(None, args, lambda message: None)

    def test_cli_updates_address_only_after_saved(self):
        import contextlib
        import io
        import json
        import os
        from micros_tooling import dispatch as cli
        from micros_tooling.storage.workspace import Workspace

        for success in (True, False):
            with self.subTest(
                success=success
            ), tempfile.TemporaryDirectory() as directory:
                workspace = Workspace(directory)
                workspace.write(
                    "devices.json",
                    dict(
                        default="board",
                        devices=dict(
                            board=dict(host="192.0.2.1", mac="aa:bb:cc:dd:ee:ff")
                        ),
                    ),
                )
                password = Path(directory) / "password"
                password.write_text("password")
                initial = {**status(), "mac": "aa:bb:cc:dd:ee:ff"}
                connected = {
                    **initial,
                    "testing": False,
                    "state": "connected",
                    "result": "saved",
                    "ip": "192.0.2.2",
                    "ssid_hex": "74657374",
                }
                output = io.StringIO()
                with patch.dict(os.environ, MICROS_STATE_DIR=directory), patch.object(
                    sys,
                    "argv",
                    [
                        "micros",
                        "wifi",
                        "setup",
                        "--ssid",
                        "test",
                        "--password-file",
                        str(password),
                        "--json",
                    ],
                ), patch(
                    "micros_tooling.communication.wifi.select_port", return_value="/dev/test"
                ), patch(
                    "micros_tooling.communication.wifi.Wifi"
                ) as device, contextlib.redirect_stdout(
                    output
                ), contextlib.redirect_stderr(
                    io.StringIO()
                ):
                    device.return_value.status.return_value = initial
                    if success:
                        device.return_value.configure.return_value = connected
                        cli.main()
                        self.assertEqual(
                            json.loads(output.getvalue())["ip"], "192.0.2.2"
                        )
                    else:
                        device.return_value.configure.side_effect = PackageError(
                            "network not found"
                        )
                        with self.assertRaises(PackageError):
                            cli.main()
                    device.return_value.close.assert_called_once()
                self.assertEqual(
                    workspace.profiles()["devices"]["board"]["host"],
                    "192.0.2.2" if success else "192.0.2.1",
                )


if __name__ == "__main__":
    unittest.main()
