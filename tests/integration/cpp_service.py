"""Exercise C++ object construction/destruction through independently loaded C ABI hooks."""

import subprocess
import sys

result = subprocess.run(sys.argv[1:], capture_output=True, text=True, timeout=10)
assert result.returncode == 0, result.stdout + result.stderr
assert (
    result.stdout.count("C++ service initialized through the C ABI") == 2
), result.stdout
assert result.stdout.count("C++ service stopped through the C ABI") == 2, result.stdout
print("C++ placement construction, steps, destruction and reload passed")
