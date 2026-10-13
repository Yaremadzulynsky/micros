"""Setup never replaces an unexpected SDK or alters the user's Python environment."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from micros_tooling.platforms.esp8266 import bootstrap as b
from micros_tooling.storage.packages import PackageError


class BootstrapTest(unittest.TestCase):
    def test_wrong_revision_stops_before_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build/toolchains/esp8266-rtos-sdk-v3.4').mkdir(parents=True)
            with patch.object(b.shutil, 'which', return_value='/python'), patch.object(b.subprocess, 'check_output', return_value='wrong'), patch.object(b.subprocess, 'run') as run:
                with self.assertRaisesRegex(PackageError, 'pinned revision'):
                    b.setup(root)
                run.assert_not_called()

    def test_missing_python_has_actionable_error(self):
        with patch.object(b.shutil, 'which', return_value=None), patch.object(b.subprocess, 'run') as run:
            with self.assertRaisesRegex(PackageError, 'Python 3.10'):
                b.setup()
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
