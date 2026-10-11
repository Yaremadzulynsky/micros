"""Smoke-test actual terminal editing and SIGINT without contacting hardware."""
import os
from pathlib import Path
import select
import subprocess
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name=='posix','PTY smoke test requires a Unix terminal')
class TerminalTests(unittest.TestCase):
    def test_completion_interrupt_watch_and_eof(self):
        import pty
        import fcntl
        import termios
        master,slave=pty.openpty()
        code='''
import io
import signal
# CI/test launchers may ignore SIGINT. A fresh interactive terminal must not
# inherit that policy; this fixture owns its terminal and foreground session.
signal.signal(signal.SIGINT, signal.default_int_handler)
signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})
from unittest.mock import Mock
from shell_test import status
from micros_tooling.terminal.shell import Shell, line_editor
client=Mock();client.name='fixture';client.identity='0123456789ab'
client.status.return_value=status();client.inspection_supported=True
shell=Shell(client)
with line_editor(shell,None):
    shell.interact()
'''
        environment=dict(os.environ,PYTHONPATH=os.pathsep.join([str(ROOT/'src'),str(ROOT/'tests/terminal')]))
        def terminal_session():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        process=subprocess.Popen([sys.executable,'-c',code],stdin=slave,stdout=slave,stderr=slave,
                                 env=environment,preexec_fn=terminal_session,close_fds=True)
        os.close(slave)
        transcript=bytearray()
        def until(marker,timeout=5):
            deadline=time.monotonic()+timeout
            chunk=bytearray()
            while marker not in chunk:
                self.assertLess(time.monotonic(),deadline,transcript.decode(errors='replace'))
                ready,_,_=select.select([master],[],[],.1)
                if ready:
                    try:data=os.read(master,8192)
                    except OSError:data=b''
                    self.assertTrue(data,transcript.decode(errors='replace'))
                    chunk.extend(data);transcript.extend(data)
            return chunk
        try:
            until(b'fixture> ', timeout=30)
            os.write(master,b'ser\t\n')
            # Readline may redraw the prompt while completing, before executing.
            # Synchronize on the service row rather than that intermediate prompt.
            until(b'example.shell')
            os.write(master,b'watch --interval 10 services\n')
            until(b'STATE')
            os.write(master,b'\x03')
            self.assertIn(b'Interrupted',until(b'fixture> '))
            os.write(master,b'\x03')
            until(b'fixture> ')
            os.write(master,b'\x04')
            try:
                result=process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                while select.select([master],[],[],0)[0]:
                    transcript.extend(os.read(master,8192))
                self.fail('Shell did not exit after EOF: '+repr(bytes(transcript)))
            self.assertEqual(result,0,transcript.decode(errors='replace'))
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=2)
            os.close(master)


if __name__=='__main__':unittest.main()
