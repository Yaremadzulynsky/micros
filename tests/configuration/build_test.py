"""Build twice against a real ESP32 ELF; settings changes must reuse the executable."""

from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.platforms.esp32.application import build_application
from micros_tooling.config.configuration import load_project
from micros_tooling.storage.packages import PackageError
from micros_tooling.platforms.esp32.device import prepare
from micros_tooling.deployment.deploy import graph_digest
from micros_tooling.storage.packages import read_package

PROJECT = ROOT / "tests/fixtures/configuration/micros.toml"
BOARD = PROJECT.parent / "board.toml"
firmware, output = map(Path, sys.argv[1:])
messages = []
progress = lambda phase, message: messages.append(message)
packages = build_application(PROJECT, firmware, output, progress, board=BOARD)
baseline = {p.name: read_package(p.read_bytes()) for p in packages}
images, graph, _ = prepare(packages, firmware, 0)
with tempfile.TemporaryDirectory() as temporary:
    overlay = Path(temporary) / "lab.toml"
    overlay.write_text(
        '[services.colors.config]\nbrightness = 7\ninitial_color = "blue"\n'
    )
    messages.clear()
    changed_paths = build_application(
        PROJECT, firmware, output, progress, overlay, board=BOARD
    )
    changed = {p.name: read_package(p.read_bytes()) for p in changed_paths}
    assert sum("Reusing executable" in message for message in messages) == 4, messages
    for name, package in baseline.items():
        assert package["image"] == changed[name]["image"]
    assert (
        baseline["board.colors.msp"]["sha256"] != changed["board.colors.msp"]["sha256"]
    )
    changed_images, changed_graph, _ = prepare(changed_paths, firmware, 0)
    assert graph_digest(images, graph) != graph_digest(changed_images, changed_graph)
# Deployment stack budgets change the package descriptor and cache identity.
recipe = load_project(PROJECT, board=BOARD)
colors = next(service for service in recipe["services"] if service["name"] == "board.colors")
colors["stack_bytes"] = 8192
messages.clear()
with patch("micros_tooling.platforms.esp32.application.load_project", return_value=recipe):
    resized_paths = build_application(PROJECT, firmware, output, progress, board=BOARD)
resized = {p.name: read_package(p.read_bytes()) for p in resized_paths}
assert sum("Reusing executable" in message for message in messages) == 3, messages
before = baseline["board.colors.msp"]
after = resized["board.colors.msp"]
assert after["manifest"]["memory"]["stack_bytes"] == 8192
assert after["manifest"]["memory"]["arena_bytes"] == before["manifest"]["memory"]["arena_bytes"]
assert before["image"] != after["image"]
try:
    prepare(resized_paths, firmware, 0)
except PackageError as error:
    assert "stack_bytes" in str(error), error
else:
    raise AssertionError("Four services with an 8 KiB stack must exceed the 16 KiB base budget")
# Two services can use the larger stack and carry it into the validated graph.
prepare([p for p in resized_paths if p.name in ("board.colors.msp", "board.button.msp")], firmware, 0)
# Sub-4 KiB budgets survive packaging and graph admission unchanged.
for stack_bytes in (1024, 2048):
    colors["stack_bytes"] = stack_bytes
    with patch("micros_tooling.platforms.esp32.application.load_project", return_value=recipe):
        small_paths = build_application(PROJECT, firmware, output, progress, board=BOARD)
    small = {p.name: read_package(p.read_bytes()) for p in small_paths}
    assert small["board.colors.msp"]["manifest"]["memory"]["stack_bytes"] == stack_bytes
    prepare(small_paths, firmware, 0)
# Leave the review output at the root project's values.
restored = build_application(PROJECT, firmware, output, progress, board=BOARD)
restored_images, restored_graph, _ = prepare(restored, firmware, 0)
assert graph_digest(images, graph) == graph_digest(restored_images, restored_graph)
print(
    "PASS: brightness/initial color change reuses all four executables, changes deployment identity, and restores exactly; stack budget updates descriptor/cache and enforces aggregate limit"
)
