"""Run independent publisher and loggers; require visible loss and full cleanup."""
import subprocess
import sys
result = subprocess.run(sys.argv[1:], text=True, capture_output=True, timeout=10)
assert result.returncode == 0, result.stdout + result.stderr
assert result.stdout.count('fast logger: sample decoded') >= 15, result.stdout
assert result.stdout.count('slow logger: sample decoded') >= 5, result.stdout
assert 'slow logger: messages missed' in result.stdout, result.stdout
assert 'fast logger: messages missed' not in result.stdout, result.stdout
assert result.stdout.count(': Stopped ') == 3, result.stdout
assert 'BASELINE services=0 handles=0 channels=0 channel_bytes=0 tasks=0' in result.stdout, result.stdout
print(result.stdout, end='')
print('PASS independent protobuf publisher, fast/slow subscribers, explicit loss, and cleanup')
