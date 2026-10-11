"""Exercise transaction recovery and local rollback without a connected board."""

import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from micros_tooling.deployment.deploy import (
    DeploymentError,
    deploy,
    inspect_deployment,
    graph_digest,
)
from micros_tooling.storage.packages import PackageError
from micros_tooling.storage.workspace import Workspace

OLD = "11" * 32
NEW = "22" * 32


def setUpModule():
    # Offline CLI tests must not discover the developer's configured management server.
    directory = ROOT / "build/tests"
    directory.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(dir=directory)
    unittest.addModuleCleanup(temporary.cleanup)
    environment = patch.dict(os.environ, MICROS_CLIENT_DIR=str(Path(temporary.name) / "client"))
    environment.start()
    unittest.addModuleCleanup(environment.stop)


def healthy(identity=OLD, bank=0):
    return dict(
        activation=dict(
            sequence=1,
            good=bank,
            previous=1 - bank,
            candidate=bank,
            pending=0,
            attempts=0,
            good_sha256=identity,
        ),
        services=[dict(state="Running", result=0, steps=1, callbacks=0)],
        heap=10000,
    )


class FakeRemote:
    host = "192.0.2.1"
    port = 443
    """Model externally visible side effects, including a lost response after a mutation."""

    def __init__(self, failure=None):
        self.current = healthy()
        self.failure = failure
        self.requests = []
        self.activated = False

    def status(self):
        if self.activated and self.failure == "offline":
            raise OSError("connection lost")
        return copy.deepcopy(self.current)

    def request(self, method, path, body=b""):
        self.requests.append((method, path))
        if path == "/v1/stop":
            self.current["services"] = []
            if self.failure == "stop":
                raise OSError("lost STOP response")
        elif path.startswith("/v1/image") and self.failure in (
            "upload",
            "competing",
            "interrupt",
        ):
            if self.failure == "competing":
                self.current = healthy("33" * 32, 1)
            if self.failure == "interrupt":
                raise KeyboardInterrupt()
            raise OSError("upload interrupted")
        elif path.startswith("/v1/activate?bank=1"):
            self.activated = True
            if self.failure == "reject":
                raise PackageError("rejected")
            if self.failure == "not_sent":
                raise OSError("connection failed before request")
            if self.failure == "fallback":
                self.current = healthy()
            elif self.failure in ("pending", "offline"):
                self.current["activation"]["pending"] = 1
            else:
                self.current = healthy(NEW, 1)
            if self.failure == "reply":
                raise OSError("lost successful reply")
        elif path.startswith("/v1/activate?bank=0"):
            self.current = healthy()
        return {}


def inspection(remote, unchanged=False):
    return dict(
        before=remote.status(),
        banks={
            0: dict(images={0: b"old"}, graph=b"graph", digest=OLD),
            1: dict(images={0: b"new"}, graph=b"graph", digest=NEW),
        },
        plan=dict(services=[dict(name="test")]),
        unchanged=unchanged,
        candidate=1,
    )


class TransactionTests(unittest.TestCase):
    def test_sdk_source_commands_require_project_before_device_discovery(self):
        from micros_tooling import dispatch as cli
        for command in ("config", "generate", "build", "deploy", "plan"):
            with self.subTest(command=command), \
                 patch.object(sys, "argv", ["micros", command]), \
                 patch("micros_tooling.fleet.server.discover_for_command") as discover:
                with self.assertRaisesRegex(PackageError, "require --project"):
                    cli.main()
                discover.assert_not_called()

    def test_usb_migration_ignores_old_graph_boot_rejection(self):
        from micros_tooling.platforms.esp32.device import Device
        with patch("micros_tooling.platforms.esp32.device.serial.Serial"), patch.object(Device, "command",
                side_effect=[PackageError("REJECT selected bank integrity"), []]) as command:
            device = Device("test-port")
            self.assertEqual(command.call_count, 2)
            device.close()

    def test_device_locks_allow_independent_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            with workspace.locked(device="one"):
                with workspace.locked(device="two"):
                    pass
                with self.assertRaises(ValueError):
                    with workspace.locked(device="one"):
                        pass
                with self.assertRaises(ValueError):
                    with workspace.locked():
                        pass

    def test_flash_requires_intact_prepared_binary_before_serial(self):
        from argparse import Namespace
        from micros_tooling.deployment.onboarding import onboard
        from micros_tooling.storage.packages import digest
        with tempfile.TemporaryDirectory() as directory, patch("subprocess.run") as run:
            root = Path(directory) / "onboarding/board/base"
            root.mkdir(parents=True)
            (root / "micros_runtime.elf").write_bytes(b"base")
            (root / "micros_runtime.bin").write_bytes(b"damaged")
            (root.parent / "state.json").write_text(json.dumps(dict(base_sha256=digest(b"base"),
                credentials=str(root.parent), flash_files={"micros_runtime.bin": digest(b"original")})))
            with self.assertRaisesRegex(PackageError, "artifact changed"):
                onboard(Workspace(directory), Namespace(name="board", phase="flash", credentials=None, port="unused"),
                        lambda *args: None)
            run.assert_not_called()

    def test_log_follow_retries_relay_unavailability_but_not_authentication(self):
        from micros_tooling.communication.logs import follow_logs
        from micros_tooling.communication.remote import RemoteRejected
        from unittest.mock import Mock
        for status in (409, 503, 504):
            remote = Mock()
            remote.request.side_effect = [RemoteRejected(status, b'{}'), dict(
                boot_id='boot', start=0, next=2, lost=0, end=2, data_hex='6869')]
            with patch('micros_tooling.communication.logs.time.sleep'):
                stream = follow_logs(remote, follow=True)
                self.assertEqual(next(stream)['event'], 'reconnecting')
                self.assertEqual(next(stream)['logs'], 'hi')
                stream.close()
        remote.request.side_effect = RemoteRejected(401, b'{}')
        with self.assertRaises(RemoteRejected):
            next(follow_logs(remote, follow=True))

    def test_log_cursor_preserves_identical_text_and_reports_loss(self):
        from micros_tooling.communication.logs import follow_logs
        remote = FakeRemote()
        replies = [dict(boot_id="one", start=2, next=5, lost=2, end=8, data_hex=b"hi\n".hex()),
                   dict(boot_id="one", start=5, next=8, lost=0, end=8, data_hex=b"hi\n".hex())]
        with patch.object(remote, "request", side_effect=replies):
            events = list(follow_logs(remote))
        self.assertEqual(events[0], dict(event="lost", bytes=2))
        self.assertEqual([e["logs"] for e in events if e["event"] == "logs"], ["hi\n", "hi\n"])

    def test_session_is_released_after_failure(self):
        from micros_tooling.communication.remote import Remote
        remote = object.__new__(Remote)
        remote.session_id = ""
        sent = []
        def request(method, path, body=b""):
            sent.append((method, path, remote.session_id, body))
        with patch.object(remote, "request", side_effect=request):
            with self.assertRaisesRegex(ValueError, "interrupted"):
                with remote.deployment_session(healthy()):
                    raise ValueError("interrupted")
        self.assertEqual([item[0] for item in sent], ["POST", "DELETE"])
        self.assertEqual(sent[0][2], sent[1][2])
        self.assertEqual(len(sent[0][3]), 36)
        self.assertEqual(remote.session_id, "")

    def test_config_preview_explains_unchanged_version(self):
        from micros_tooling.deployment.preview import changes
        old = dict(details={"colors": dict(version="1.0.0", settings=dict(brightness=7))})
        new = copy.deepcopy(old)
        new["details"]["colors"]["settings"]["brightness"] = 12
        self.assertEqual(changes(old, new), ["colors.brightness: 7 → 12"])

    def test_management_only_base_preparation_skips_application_compilation(self):
        from argparse import Namespace
        from micros_tooling.deployment.onboarding import onboard
        from micros_tooling.storage.workspace import Workspace
        with tempfile.TemporaryDirectory() as directory:
            workspace=Workspace(directory)
            board=Path(directory)/"board.toml"
            board.write_text('[board]\nprofile="test"\nflash_mb=4\n[board.gpio]\n')
            project=Path(directory)/"project.toml"
            project.write_text('[services]\n')
            build=Path(directory)/"onboarding/board/base"
            build.mkdir(parents=True)
            (build/"micros_runtime.elf").write_bytes(b"base")
            (build/"flash_args").write_bytes(b"flash arguments")
            (build/"flasher_args.json").write_text('{"flash_files": {}}')
            args=Namespace(name="board",phase="prepare",credentials=None,board=board,
                           project=project,rotate_identity=False,relay_credentials=None)
            sdk = Path(directory) / "sdk"
            export = sdk / "build/toolchains/esp-idf-v5.5.2/export.sh"
            export.parent.mkdir(parents=True)
            export.write_text("# Fixture for the mocked build subprocess.\n")
            with patch("micros_tooling.deployment.onboarding.ROOT", sdk), \
                 patch("micros_tooling.deployment.onboarding.provision"), \
                 patch("micros_tooling.deployment.onboarding.subprocess.run") as run, \
                 patch("micros_tooling.deployment.onboarding.build_application") as application, \
                 patch("micros_tooling.fleet.server.configured_remote", return_value=None):
                run.return_value.returncode=0
                result=onboard(workspace,args,lambda *args:None)
                self.assertEqual(result["phase"],"prepared")
                application.assert_not_called()
                run.assert_called_once()
                self.assertIn(str(export), run.call_args.args[0])

    def test_onboarding_plan_never_runs_hardware_commands(self):
        from argparse import Namespace
        from micros_tooling.deployment.onboarding import onboard
        with tempfile.TemporaryDirectory() as directory, patch("subprocess.run") as run:
            result = onboard(Workspace(directory), Namespace(name="board", phase="plan", credentials=None),
                             lambda *args: None)
            self.assertIn("prepare", result["next"])
            run.assert_not_called()

    def test_onboarding_rejects_changed_prepared_base(self):
        from argparse import Namespace
        from micros_tooling.deployment.onboarding import onboard
        with tempfile.TemporaryDirectory() as directory, patch("subprocess.run") as run:
            root = Path(directory) / "onboarding/board/base"
            root.mkdir(parents=True)
            (root / "micros_runtime.elf").write_bytes(b"changed")
            with self.assertRaisesRegex(PackageError, "Prepared base changed"):
                onboard(Workspace(directory), Namespace(name="board", phase="flash", credentials=None),
                        lambda *args: None)
            run.assert_not_called()

    def test_status_during_writer_without_local_elf(self):
        import contextlib
        import io
        from micros_tooling import dispatch as cli
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            workspace.write("devices.json", dict(default="board", devices={"board": {"host": "example"}}))
            output = io.StringIO()
            with workspace.locked(), patch.dict(os.environ, MICROS_STATE_DIR=directory), \
                    patch.object(sys, "argv", ["micros", "status", "--json"]), \
                    patch("micros_tooling.deployment.diagnostics.connect", return_value=("board", {}, FakeRemote())), \
                    contextlib.redirect_stdout(output):
                cli.main()
            self.assertEqual(json.loads(output.getvalue())["status"]["heap"], 10000)

    def test_wrong_or_unknown_base_refuses_before_prepare(self):
        from micros_tooling.deployment.identity import verify_base
        from micros_tooling.storage.packages import digest

        with tempfile.TemporaryDirectory() as directory:
            firmware = Path(directory) / "base.elf"
            firmware.write_bytes(b"base")
            remote = FakeRemote()
            with patch("micros_tooling.deployment.deploy.prepare") as prepare:
                for identity in (None, dict(base_sha256=OLD, abi_major=0,
                        abi_revision=7, graph_format=1, device_id="001122334455")):
                    remote.current["identity"] = identity
                    with self.assertRaises(PackageError):
                        inspect_deployment(remote, ["package"], firmware)
                prepare.assert_not_called()
            self.assertEqual(remote.requests, [])
            remote.current["identity"]["base_sha256"] = digest(b"base")
            verify_base(remote.current, firmware)

    def run_deploy(self, remote, unchanged=False, force=False):
        clock = iter(range(0, 1000, 10))
        return deploy(
            remote,
            [],
            None,
            prepared=inspection(remote, unchanged),
            force=force,
            clock=lambda: next(clock),
            sleep=lambda seconds: None,
        )

    def test_noop_does_not_write(self):
        remote = FakeRemote()
        self.assertTrue(self.run_deploy(remote, unchanged=True)["unchanged"])
        self.assertEqual(remote.requests, [])

    def test_force_and_success(self):
        remote = FakeRemote()
        self.assertFalse(
            self.run_deploy(remote, unchanged=True, force=True)["unchanged"]
        )
        self.assertEqual(remote.current["activation"]["good_sha256"], NEW)

    def test_lost_activation_reply_is_observed(self):
        self.assertEqual(self.run_deploy(FakeRemote("reply"))["activated_bank"], 1)

    def test_failures_restart_previous(self):
        for failure in ("stop", "upload", "interrupt", "reject", "not_sent"):
            with self.subTest(failure=failure):
                remote = FakeRemote(failure)
                with self.assertRaises(DeploymentError) as caught:
                    self.run_deploy(remote)
                self.assertEqual(caught.exception.outcome, "recovered")
                self.assertEqual(remote.current["services"][0]["state"], "Running")
                self.assertEqual(remote.current["activation"]["good_sha256"], OLD)

    def test_selective_staging_never_stops_or_recovers_live_peers(self):
        remote = FakeRemote()
        remote.current["selective_deploy"] = 1
        self.run_deploy(remote)
        self.assertNotIn(("POST", "/v1/stop"), remote.requests)
        remote = FakeRemote("upload")
        remote.current["selective_deploy"] = 1
        with self.assertRaises(DeploymentError) as caught:
            self.run_deploy(remote)
        self.assertEqual(caught.exception.outcome, "preserved")
        self.assertFalse(any("/activate" in path or path == "/v1/stop" for _, path in remote.requests))

    def test_staging_reboot_is_not_reported_as_preserved(self):
        class RebootingRemote(FakeRemote):
            def request(self, method, path, *args, **kwargs):
                if "/image" in path:
                    self.current["service_boot"] = "new-boot"
                return super().request(method, path, *args, **kwargs)
        remote = RebootingRemote("upload")
        remote.current.update(selective_deploy=1, service_boot="old-boot")
        with self.assertRaises(DeploymentError) as caught:
            self.run_deploy(remote)
        self.assertEqual(caught.exception.outcome, "unknown")

    def test_pending_or_offline_does_not_activate_again(self):
        for failure in ("pending", "offline"):
            remote = FakeRemote(failure)
            with self.assertRaises(DeploymentError) as caught:
                self.run_deploy(remote)
            self.assertEqual(caught.exception.outcome, "unknown")
            self.assertEqual(
                sum("/activate?" in path for _, path in remote.requests), 1
            )

    def test_fallback(self):
        with self.assertRaises(DeploymentError) as caught:
            self.run_deploy(FakeRemote("fallback"))
        self.assertEqual(caught.exception.outcome, "rolled_back")

    def test_competing_selection_is_never_restarted(self):
        remote = FakeRemote("competing")
        with self.assertRaises(DeploymentError):
            self.run_deploy(remote)
        self.assertFalse(any("/activate?" in path for _, path in remote.requests))

    def test_preflight_change_refuses_stop(self):
        remote = FakeRemote()
        prepared = inspection(remote)
        remote.current["activation"]["sequence"] += 1
        with self.assertRaises(PackageError):
            deploy(remote, [], None, prepared=prepared)
        self.assertEqual(remote.requests, [])

    def test_stopped_identical_application_restarts_without_upload(self):
        remote = FakeRemote()
        remote.current["services"] = []
        result = self.run_deploy(remote, unchanged=True)
        self.assertTrue(result["unchanged"])
        self.assertEqual(remote.requests, [("POST", "/v1/activate?bank=0")])

    def test_pending_preflight_refuses_mutations(self):
        remote = FakeRemote()
        remote.current["activation"]["pending"] = 1
        with patch(
            "micros_tooling.deployment.deploy.prepare", return_value=({}, bytes(232), {})
        ):
            with self.assertRaises(PackageError):
                inspect_deployment(remote, ["package"], None)
        self.assertEqual(remote.requests, [])

    def test_digest_uses_graph_order(self):
        import hashlib

        graph = bytearray(232)
        struct.pack_into("<I", graph, 12, 2)
        struct.pack_into("<I", graph, 84, 3)
        struct.pack_into("<I", graph, 120, 0)
        self.assertEqual(
            graph_digest({0: b"zero", 3: b"three"}, graph),
            hashlib.sha256(graph + b"threezero").hexdigest(),
        )


class WorkspaceTests(unittest.TestCase):
    def test_offline_hardware_id_selects_one_saved_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            profiles = dict(default=None, devices={
                "feather": {"device_id": "e89f6d30e1a8"},
                "other": {"device_id": "b0a732c8082c"}})
            workspace.write("devices.json", profiles)
            self.assertEqual(workspace.device("e89f6d30e1a8")[0], "feather")
            self.assertEqual(workspace.device("feather")[0], "feather")
            with self.assertRaisesRegex(PackageError, "No saved device"):
                workspace.device()
            with self.assertRaisesRegex(PackageError, "No saved device"):
                workspace.device("000000000000")
            profiles["devices"]["duplicate"] = profiles["devices"]["feather"]
            workspace.write("devices.json", profiles)
            with self.assertRaisesRegex(PackageError, "multiple saved devices"):
                workspace.device("e89f6d30e1a8")

    def test_confirmation_rollback_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            for identity, graph in [("a" * 64, OLD), ("b" * 64, NEW)]:
                workspace.write(
                    f"snapshots/{identity}/receipt.json",
                    dict(
                        id=identity,
                        banks={"0": graph, "1": graph},
                        services=[dict(name=identity, version="1.0.0")],
                    ),
                )
            first = workspace.observe("board", healthy())
            workspace.observe("board", healthy())
            self.assertEqual(len(workspace.history("board")), 1)
            workspace.observe("board", healthy(NEW, 1))
            self.assertEqual(
                workspace.rollback_target("board", healthy(NEW, 1))["id"], first["id"]
            )
            workspace.observe("board", healthy())
            self.assertEqual(workspace.rollback_target("board", healthy())["id"], "b" * 64)
            base = Path(directory) / "base.elf"
            base.write_bytes(b"base")
            with self.assertRaises(PackageError):
                workspace.snapshot_packages(dict(firmware_sha256="bad"), base)

    def test_unknown_and_pending_do_not_enter_history(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            workspace.observe("board", healthy())
            self.assertEqual(workspace.history("board"), [])

    def test_missing_device_friendly_cli_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/micros.py"), "status"],
                env={**os.environ, "MICROS_STATE_DIR": directory},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("device add", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


def package_fixture(payload=b"first", version="1.0.0"):
    # A valid host envelope suffices for testing local immutable storage; native
    # linkage/admission are independently exercised by package and device checks.
    from micros_tooling.storage.native_image import envelope
    from micros_tooling.storage.packages import build_package, digest

    image = envelope(1, payload)
    return build_package(
        dict(
            format=1,
            name="test.service",
            version=version,
            target=1,
            abi=dict(major=0, revision=7),
            image_sha256=digest(image),
            memory=dict(arena_bytes=0, arena_alignment=1, stack_bytes=4096),
            capabilities=dict(handles=0, timers=0, gpio=[]),
            channels=[],
            schemas={},
            persistent_data_version=0,
        ),
        image,
        {},
    )


class ReceiptAndCliTests(unittest.TestCase):
    def test_retention_preserves_current_and_release_metadata_and_resumes(self):
        from micros_tooling.storage.retention import collect

        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            firmware = Path(directory) / "base.elf"
            firmware.write_bytes(b"base")
            workspace.write("devices.json", dict(default="board", devices=dict(board={})))
            package = Path(directory) / "service.msp"
            receipts = []
            for index in range(3):
                package.write_bytes(package_fixture(str(index).encode(), f"1.0.{index}"))
                review = inspection(FakeRemote())
                for bank in review["banks"].values():
                    bank["digest"] = str(index + 1) * 64
                receipt = workspace.snapshot([package], review, firmware)
                workspace.confirm("board", receipt)
                receipts.append(receipt)
            statuses = {"board": healthy("3" * 64)}
            workspace.write("devices/board/attempts/pending.json",
                            dict(outcome="unknown", release=receipts[0]["id"]))
            protected = collect(workspace, keep=1, statuses={"board": healthy("2" * 64)})
            self.assertEqual(protected["releases"], [])
            (workspace.root / "devices/board/attempts/pending.json").unlink()
            result = collect(workspace, keep=1, statuses=statuses)
            self.assertEqual(set(result["releases"]), {item["id"] for item in receipts[:2]})
            first_package = workspace.snapshot_packages(receipts[0], firmware)[0]
            self.assertTrue(first_package.exists())
            # Fail after metadata publication, then resume without losing release metadata.
            unlink = Path.unlink
            def interrupt_first_package(path, *args, **kwargs):
                if path == first_package:
                    raise OSError("interrupted")
                return unlink(path, *args, **kwargs)
            # Receipt hashes (and directory order) change when the ABI changes.
            # Interrupt the intended package, regardless of enumeration order.
            with patch.object(Path, "unlink", autospec=True, side_effect=interrupt_first_package):
                with self.assertRaises(OSError):
                    collect(workspace, keep=1, dry_run=False, statuses=statuses)
            first_package.unlink()
            collect(workspace, keep=1, dry_run=False, statuses=statuses)
            self.assertTrue(workspace.snapshot_packages(receipts[2], firmware)[0].exists())
            retained = workspace.read(Path("snapshots") / receipts[0]["id"] / "receipt.json")
            self.assertTrue(retained["artifacts_pruned"])
            with self.assertRaisesRegex(PackageError, "pruned"):
                workspace.snapshot_packages(retained, firmware)
            self.assertEqual(retained["version_manifests"][0]["version"], "1.0.0")
            self.assertEqual(retained["packages"], receipts[0]["packages"])

    def test_damaged_history_and_receipts_do_not_block_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            workspace.write("devices/board/history.json", {"not": "history"})
            workspace.write("snapshots/broken/receipt.json", {"banks": {"0": OLD}})
            self.assertIsNone(workspace.matching(healthy(), "board"))

    def test_named_environment_validates_before_saving(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            workspace.write("devices.json", dict(default="board", devices={"board": dict(host="unused", transport="native")}))
            overlay = Path(directory) / "overlay.toml"
            command = [sys.executable, str(ROOT / "tools/micros.py"), "device", "environment", "board", "lab",
                       "--overlay", str(overlay), "--project", str(ROOT / "tests/fixtures/configuration/micros.toml"),
                       "--board", str(ROOT / "tests/fixtures/configuration/board.toml"), "--json"]
            env = dict(os.environ, MICROS_STATE_DIR=directory)
            overlay.write_text('[services.colors.config]\nbrightness = 999999\n')
            failed = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("brightness", json.loads(failed.stderr)["error"]["message"])
            self.assertNotIn("environments", workspace.profiles()["devices"]["board"])
            overlay.write_text('[services.colors.config]\nbrightness = 7\n')
            success = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual((Path(directory) / "devices/board/environments/lab.toml").read_bytes(), overlay.read_bytes())

    def test_private_backup_roundtrip_and_corruption(self):
        from micros_tooling.storage.bundles import export_state, import_state
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = Workspace(root / "source"), Workspace(root / "target")
            source.write("devices.json", dict(default=None, devices={}))
            source.write("snapshots/test/receipt.json", dict(example=True))
            export_state(source, root / "backup")
            with target.locked():
                import_state(target, root / "backup")
                import_state(target, root / "backup")  # Identical interrupted imports are resumable.
            self.assertEqual(source.profiles(), target.profiles())
            (root / "backup/devices.json").write_text("corrupted")
            with self.assertRaisesRegex(PackageError, "damaged"):
                import_state(target, root / "backup")

    def test_attempt_retains_interrupted_outcome(self):
        from micros_tooling.deployment.attempts import recorded_deploy, observe_attempt
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            remote = FakeRemote("upload")
            receipt = dict(id=NEW, banks={"0": OLD, "1": NEW})
            with self.assertRaises(DeploymentError):
                recorded_deploy(workspace, "board", receipt, remote, [], None,
                                prepared=inspection(remote))
            record = observe_attempt(workspace, "board", remote.status())
            self.assertEqual(record["outcome"], "recovered")
            self.assertEqual(record["phase"], "recover")

    def test_saved_packages_survive_rebuild_and_reject_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            package = Path(directory) / "service.msp"
            firmware = Path(directory) / "firmware.elf"
            firmware.write_bytes(b"paired base")
            original = package_fixture()
            package.write_bytes(original)
            receipt = workspace.snapshot([package], inspection(FakeRemote()), firmware)
            workspace.confirm("board", receipt)
            package.write_bytes(package_fixture(b"edited"))
            saved = workspace.snapshot_packages(receipt, firmware)[0]
            self.assertEqual(saved.read_bytes(), original)
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            changed_review = inspection(FakeRemote())
            changed_review["banks"][0]["digest"] = NEW
            changed = workspace.snapshot([package], changed_review, firmware)
            workspace.confirm("board", changed)
            self.assertEqual(receipt["services"], changed["services"])
            self.assertNotEqual(receipt["id"], changed["id"])
            self.assertNotEqual(receipt["packages"], changed["packages"])
            self.assertEqual(workspace.snapshot([package], changed_review, firmware)["id"], changed["id"])
            rollback = workspace.rollback_target("board", healthy(NEW, 1))
            self.assertEqual(rollback["id"], receipt["id"])
            self.assertEqual(workspace.snapshot_packages(rollback, firmware)[0].read_bytes(), original)
            saved.write_bytes(b"truncated")
            with self.assertRaisesRegex(PackageError, "damaged"):
                workspace.snapshot_packages(receipt, firmware)

    def test_cli_same_version_changed_content_plan_and_deploy(self):
        import contextlib
        import io
        from micros_tooling import dispatch as cli
        from micros_tooling.storage.packages import digest

        for command, dry_run, compiled, as_json, unchanged in (
            ("plan", True, False, True, False), ("plan", True, True, True, False),
            ("plan", True, False, False, False), ("deploy", True, False, True, False),
            ("deploy", False, False, True, False), ("deploy", False, True, True, False),
            ("plan", True, False, True, True), ("deploy", False, False, True, True),
        ):
            with self.subTest(
                command=command, dry_run=dry_run, compiled=compiled, as_json=as_json, unchanged=unchanged
            ), tempfile.TemporaryDirectory() as directory:
                workspace = Workspace(directory)
                firmware = Path(directory) / "devices/board/firmware.elf"
                firmware.parent.mkdir(parents=True)
                firmware.write_bytes(b"paired base")
                workspace.write(
                    "devices.json",
                    dict(
                        default="board",
                        devices=dict(
                            board=dict(
                                device_id="aabbccddeeff",
                                host="192.0.2.1",
                                transport="native",
                                firmware_sha256=digest(firmware.read_bytes()),
                            )
                        ),
                    ),
                )
                package = Path(directory) / "service.msp"
                package.write_bytes(package_fixture())
                remote = FakeRemote()
                remote.current["identity"] = dict(device_id="aabbccddeeff",
                                                  base_sha256=digest(firmware.read_bytes()),
                                                  abi_major=0, abi_revision=7, graph_format=1)
                unit = Path(directory) / "aabbccddeeff.toml"
                unit.write_text('[unit]\ndevice_id="aabbccddeeff"\n[board]\nprofile="test"\n[services]\n')
                prior = workspace.snapshot([package], inspection(remote), firmware)
                workspace.confirm("board", prior)
                if not unchanged:
                    package.write_bytes(package_fixture(b"edited at the same version"))
                prepared = inspection(remote, unchanged=unchanged)
                if not unchanged:
                    prepared["banks"][0]["digest"] = "33" * 32
                stdout = io.StringIO()
                arguments = ["micros", command]
                arguments += ["--release", str(Path(directory) / "review")] if compiled else ["--project", str(unit)]
                if as_json:
                    arguments.append("--json")
                if dry_run and command != "plan":
                    arguments.append("--dry-run")
                with patch.dict(os.environ, MICROS_STATE_DIR=directory,
                                MICROS_CLIENT_DIR=str(Path(directory) / "client")), patch.object(
                    sys, "argv", arguments
                ), patch("micros_tooling.deployment.diagnostics.Remote", return_value=remote), patch.object(
                    cli, "build_application", return_value=[package]
                ) as build, patch(
                    "micros_tooling.storage.bundles.release_packages", return_value=[package]
                ) as release, patch.object(
                    cli, "inspect_deployment", return_value=prepared
                ), contextlib.redirect_stdout(
                    stdout
                ), contextlib.redirect_stderr(
                    io.StringIO()
                ):
                    cli.main()
                self.assertEqual(build.call_count, 0 if compiled else 1)
                self.assertEqual(release.call_count, 1 if compiled else 0)
                if not as_json:
                    self.assertIn("Deployment plan: board", stdout.getvalue())
                    self.assertIn("Baseline: known", stdout.getvalue())
                    self.assertIn("all current services pause", stdout.getvalue())
                    self.assertEqual(remote.requests, [])
                    self.assertEqual([event["snapshot"] for event in workspace.history("board")], [prior["id"]])
                    continue
                result = json.loads(stdout.getvalue())
                if dry_run:
                    self.assertTrue(result["dry_run"])
                    self.assertEqual(result["deployment_plan"]["format"], 1)
                    self.assertEqual(result["deployment_plan"]["execution"]["action"], "none" if unchanged else "deploy")
                    self.assertEqual(result["deployment_plan"]["baseline"]["state"], "known")
                    self.assertEqual(result["application"]["services"], prior["services"])
                    self.assertEqual(result["application"]["id"] == prior["id"], unchanged)
                    self.assertEqual(remote.requests, [])
                    self.assertEqual([event["snapshot"] for event in workspace.history("board")], [prior["id"]])
                else:
                    self.assertEqual(result["unchanged"], unchanged)
                    if unchanged:
                        self.assertEqual(remote.requests, [])
                    else:
                        self.assertEqual(result["activated_bank"], 1)
                    self.assertEqual(len(workspace.history("board")), 1 if unchanged else 2)
                    self.assertEqual(workspace.history("board")[-1]["snapshot"], result["snapshot"])
                    self.assertEqual(workspace.snapshot_packages(prior, firmware)[0].read_bytes(), package_fixture())

    def test_invalid_status_is_protocol_error(self):
        from micros_tooling.communication.remote import Remote, decode_response

        with self.assertRaises(PackageError):
            decode_response(b"broken JSON")
        remote = Remote.__new__(Remote)
        with patch.object(remote, "request", return_value={"activation": {}}):
            with self.assertRaises(PackageError):
                remote.status()
        with patch.object(remote, "request", return_value=healthy()):
            self.assertEqual(remote.status()["activation"]["good_sha256"], OLD)


if __name__ == "__main__":
    unittest.main()
