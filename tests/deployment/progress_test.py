import io
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from micros_tooling.terminal import progress as p
from micros_tooling.storage.packages import PackageError


class Terminal(io.StringIO):
    def isatty(self):
        return True


class ProgressTest(unittest.TestCase):
    def test_activity_animates_pauses_and_cleans_up_on_error(self):
        stream = Terminal()
        with patch.object(p.sys, 'stderr', stream), patch.dict(os.environ, {'TERM':'xterm'}):
            with self.assertRaisesRegex(ValueError, 'stop'):
                with p.Activity('Waiting for Wi-Fi') as activity:
                    time.sleep(.15)
                    with activity.paused():
                        snapshot = stream.getvalue()
                        time.sleep(.15)
                        self.assertEqual(stream.getvalue(), snapshot)
                    raise ValueError('stop')
        self.assertIn('Waiting for Wi-Fi', stream.getvalue())
        self.assertFalse(activity.thread.is_alive())
        self.assertTrue(stream.getvalue().endswith('\r\033[2K'))

    def test_measurements(self):
        self.assertEqual(p.measurement('[12/40] Compiling'), (30, 'Build steps 12/40'))
        self.assertEqual(p.measurement('Writing at 0x10000... (50 %)'), (50, 'Current step'))
        self.assertIsNone(p.measurement('Connecting...'))

    def test_color_opt_out(self):
        with patch.dict(os.environ, {'TERM':'xterm', 'NO_COLOR':''}):
            self.assertEqual(p.color('test', '36', Terminal()), 'test')
        self.assertEqual(p.color('test', '36', io.StringIO()), 'test')

    def test_live_progress_and_complete_log(self):
        stream = Terminal()
        with tempfile.TemporaryDirectory() as directory, patch.object(p.sys, 'stderr', stream), patch.dict(os.environ, {'TERM':'xterm'}):
            log = Path(directory) / 'prepare.log'
            output = p.run([sys.executable, '-u', '-c', 'import time; print("[1/2] Building"); time.sleep(.25); print("[2/2] Done")'], log)
            self.assertEqual(log.read_text(), output)
        self.assertIn('50%', stream.getvalue())
        self.assertIn('Building firmware', stream.getvalue())
        self.assertTrue(stream.getvalue().endswith('\r\033[2K'))

    def test_redirected_output_is_quiet(self):
        stream = io.StringIO()
        with patch.object(p.sys, 'stderr', stream):
            self.assertEqual(p.run([sys.executable, '-c', 'print("done")']), 'done\n')
        self.assertEqual(stream.getvalue(), '')

    def test_timeout_saves_partial_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'prepare.log'
            with self.assertRaisesRegex(PackageError, 'timed out'):
                p.run([sys.executable, '-u', '-c', 'import time; print("started"); time.sleep(10)'], log, timeout=.3)
            self.assertIn('started', log.read_text())

    def test_failure_keeps_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'prepare.log'
            with self.assertRaisesRegex(PackageError, 'failed'):
                p.run([sys.executable, '-c', 'print("failed step"); raise SystemExit(1)'], log)
            self.assertIn('failed step', log.read_text())


if __name__ == '__main__':
    unittest.main()
