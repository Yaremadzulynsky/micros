"""Live stderr progress for bounded build/USB subprocesses; stdout stays clean."""
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time
import threading
from contextlib import contextmanager

from micros_tooling.storage.packages import PackageError, require
from micros_tooling.storage.store import atomic_write


def color(text, code, stream=None):
    stream = stream or sys.stderr
    if stream.isatty() and os.environ.get('TERM') != 'dumb' and 'NO_COLOR' not in os.environ:
        return f'\033[{code}m{text}\033[0m'
    return text


def message(text):
    code = '33' if any(word in text.lower() for word in ('waiting', 'unidentified', 'unavailable', 'erase ', 'erasing')) else '36'
    print('  ' + color(text, code), file=sys.stderr, flush=True)


class Activity:
    """Animate blocking I/O without touching its timing or displaying payloads."""
    def __init__(self, label):
        self.label = label
        self.stream = sys.stderr
        self.enabled = self.stream.isatty() and os.environ.get('TERM') != 'dumb'
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.hidden = False

    def __enter__(self):
        self.started = time.monotonic()
        def animate():
            frame = 0
            while not self.stop.is_set():
                with self.lock:
                    if not self.hidden:
                        symbol = '|/-' + chr(92)
                        text = f'{symbol[frame % 4]} {self.label} · {int(time.monotonic() - self.started)}s'
                        self.stream.write('\r\033[2K  ' + color(text, '36', self.stream))
                        self.stream.flush()
                frame += 1
                self.stop.wait(.1)
        self.thread = threading.Thread(target=animate, daemon=True)
        if self.enabled:
            self.thread.start()
        return self

    @contextmanager
    def paused(self):
        with self.lock:
            self.hidden = True
            if self.enabled:
                self.stream.write('\r\033[2K')
                self.stream.flush()
        try:
            yield
        finally:
            with self.lock:
                self.hidden = False

    def __exit__(self, *exc):
        self.stop.set()
        if self.enabled:
            self.thread.join()
            self.stream.write('\r\033[2K')
            self.stream.flush()


def measurement(line):
    steps = re.search(r'\[(\d+)/(\d+)\]', line)
    if steps and int(steps[2]) > 0:
        return min(100, int(steps[1]) * 100 // int(steps[2])), f'Build steps {steps[1]}/{steps[2]}'
    percent = re.search(r'(?<![\d.])(\d{1,3})(?:\.\d+)?\s*%', line)
    if percent and int(percent[1]) <= 100:
        return int(percent[1]), 'Current step'
    return None


def run(command, log=None, timeout=120):
    labels = {'prepare': 'Building firmware', 'setup': 'Installing build tools',
              'flash': 'Writing firmware', 'erase': 'Erasing flash', 'verify-flash': 'Checking firmware'}
    label = labels.get(Path(log).stem, 'Working') if log else 'Detecting chip'
    terminal = (sys.stderr.isatty() and os.environ.get('TERM') != 'dumb'
                and threading.current_thread() is threading.main_thread())
    start = time.monotonic()
    output = bytearray()
    pending = ''
    latest = None
    updated = start
    frame = 0
    frames = "|/-\\"
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True, env=dict(os.environ, PYTHONUNBUFFERED='1'))
    completed = False
    try:
        while True:
            now = time.monotonic()
            if now - start >= timeout:
                raise PackageError(f'{label} timed out after {timeout}s.' + (f' See {log}.' if log else ''))
            if terminal:
                elapsed = int(now - start)
                if latest is not None and now - updated < 3:
                    percent, phase = latest
                    filled = percent // 5
                    visual = '[' + '#' * filled + '-' * (20 - filled) + f'] {percent:3}%'
                    detail = f' · {phase}' if phase != 'Current step' else ''
                    text = f'{label}{detail} {visual} · {elapsed}s'
                else:
                    text = f'{frames[frame % 4]} {label} · {elapsed}s'
                sys.stderr.write('\r\033[2K  ' + color(text, '36'))
                sys.stderr.flush()
                frame += 1
            ready, _, _ = select.select([process.stdout], [], [], .1)
            if ready:
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                output.extend(chunk)
                pending += chunk.decode('utf-8', errors='replace')
                lines = re.split(r'[\r\n]', pending)
                pending = lines.pop()[-8192:]
                for line in lines:
                    value = measurement(line)
                    if value is not None:
                        latest, updated = value, time.monotonic()
        process.wait(timeout=max(.1, timeout - (time.monotonic() - start)))
        completed = True
    finally:
        if not completed:
            # Stop compiler/download children as well on interruption or timeout.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        output.extend(process.stdout.read())
        process.stdout.close()
        if terminal:
            sys.stderr.write('\r\033[2K')
            sys.stderr.flush()
        if log:
            atomic_write(log, bytes(output))
    text = output.decode('utf-8', errors='replace')
    require(process.returncode == 0, 'USB/build operation failed. ' + (f'See {log}.' if log else text[-1500:]))
    return text
