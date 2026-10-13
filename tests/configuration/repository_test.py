"""Saved source paths survive the layout change without rewriting private state."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.config import repository
from micros_tooling.storage.workspace import Workspace


class RepositoryTests(unittest.TestCase):
    def test_saved_profile_resolves_moved_board_without_writing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            board = root / "config/boards/test.toml"
            board.parent.mkdir(parents=True)
            board.write_text("[board]\n")
            state = root / ".micros"
            state.mkdir()
            profiles = state / "devices.json"
            original = json.dumps({"default": "test", "devices": {"test": {
                "board_source": str(root / "boards/test.toml"), "board": "board.toml",
            }}})
            profiles.write_text(original)
            with patch.object(repository, "ROOT", root):
                _, profile = Workspace(state).device()
            self.assertEqual(profile["board_source"], str(board))
            self.assertEqual(profile["board"], "board.toml")
            self.assertEqual(profiles.read_text(), original)

    def test_existing_external_relative_and_missing_targets_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "boards/test.toml"
            existing.parent.mkdir()
            existing.touch()
            with patch.object(repository, "ROOT", root):
                for value in (str(existing), str(root.parent / "boards/external.toml"),
                              "board.toml", str(root / "boards/missing.toml"), None):
                    self.assertEqual(repository.saved_source(value), value)

    def test_saved_service_sources_follow_their_owners(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for old, new in (
                ("src/services/diagnostics/channel-probe/service.toml",
                 "services/diagnostics/channel-probe/service.toml"),
                ("src/services/dht/service.toml", "examples/services/dht/service.toml"),
                ("services/button/src/service.c", "examples/services/button/src/service.c"),
                ("src/services/ir-selftest/src/service.c", "tests/fixtures/ir-selftest/src/service.c"),
            ):
                with self.subTest(old=old), patch.object(repository, "ROOT", root):
                    target = root / new
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch()
                    self.assertEqual(repository.saved_source(str(root / old)), str(target))
                    original = root / old
                    original.parent.mkdir(parents=True, exist_ok=True)
                    original.touch()
                    self.assertEqual(repository.saved_source(str(original)), str(original))


if __name__ == "__main__":
    unittest.main()
