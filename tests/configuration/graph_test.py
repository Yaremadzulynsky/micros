"""Offline ESP32 graph configuration persistence and rollback identity check."""

from pathlib import Path
import struct
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.platforms.esp32.device import prepare, GRAPH_BYTES
from micros_tooling.deployment.deploy import graph_digest
from micros_tooling.storage.packages import build_package, read_package

firmware, directory = map(Path, sys.argv[1:])
packages = sorted(directory.glob("*.msp"))
images, graph, plan = prepare(packages, firmware, 0)
version=struct.unpack_from("<I", graph, 4)[0]
assert len(graph)==(GRAPH_BYTES if version==3 else 1272)
assert version in (2,3)
assert struct.unpack_from("<I", graph, len(graph) - 4)[0] == zlib.crc32(graph[:-4])
if version == 3:
    gpio = plan["board_bindings"]["gpio"]
    count, recovery = struct.unpack_from("<II", graph, 1268)
    assert count == len(gpio)
    expected_recovery = next((p["line"] for p in gpio if p["name"] == plan["board_bindings"]["recovery_button"]), 0xffffffff)
    assert recovery == expected_recovery
    for index, pin in enumerate(gpio):
        actual_pin, output, name = struct.unpack_from("<II36s", graph, 1276 + index * 44)
        assert (actual_pin, output, name.rstrip(b"\0").decode()) == (pin["pin"], pin["direction"] == "output", pin["name"])
ordered = sorted(
    plan["services"], key=lambda s: (bool(s["permissions"]["publish_mask"]), s["name"])
)
for index, service in enumerate(ordered):
    # Five header words + four channel records + four service records precede configuration.
    offset = 228 + index * 260
    size = struct.unpack_from("<I", graph, offset)[0]
    payload = bytes.fromhex(service["config"])
    assert size == len(payload)
    assert graph[offset + 4 : offset + 4 + size] == payload
    assert not any(graph[offset + 4 + size : offset + 260])
with tempfile.TemporaryDirectory() as temporary:
    updated_paths = []
    for path in packages:
        package = read_package(path.read_bytes())
        if package["manifest"]["name"] == "board.colors":
            payload = bytearray.fromhex(package["manifest"]["config"])
            payload[8:12] = (3).to_bytes(4, "little")
            package["manifest"]["config"] = payload.hex()
        updated = Path(temporary) / path.name
        updated.write_bytes(
            build_package(package["manifest"], package["image"], package["schemas"])
        )
        updated_paths.append(updated)
    updated_images, updated_graph, _ = prepare(updated_paths, firmware, 0)
    assert images == updated_images
    assert graph_digest(images, graph) != graph_digest(updated_images, updated_graph)
    restored_images, restored_graph, _ = prepare(packages, firmware, 0)
    assert graph_digest(restored_images, restored_graph) == graph_digest(images, graph)
if version == 3:
    with tempfile.TemporaryDirectory() as temporary:
        remapped_paths = []
        for path in packages:
            package = read_package(path.read_bytes())
            for pin in package["manifest"]["board_bindings"]["gpio"]:
                if pin["name"] == "red_led":
                    pin["pin"] = 25
            updated = Path(temporary) / path.name
            updated.write_bytes(build_package(package["manifest"], package["image"], package["schemas"]))
            remapped_paths.append(updated)
        remapped_images, remapped_graph, remapped_plan = prepare(remapped_paths, firmware, 0)
        assert remapped_images == images
        assert graph_digest(images, graph) != graph_digest(remapped_images, remapped_graph)
        assert next(pin["pin"] for pin in remapped_plan["board_bindings"]["gpio"] if pin["name"] == "red_led") == 25
        # Combining packages from different wiring deployments is rejected.
        from micros_tooling.storage.packages import PackageError
        try:
            prepare([packages[0], *remapped_paths[1:]], firmware, 0)
        except PackageError as error:
            assert "same board wiring" in str(error)
        else:
            raise AssertionError("Mixed board bindings were admitted")
print(
    "Graph stores exact configuration bytes; configuration-only changes alter activation identity; restoring packages restores it"
)
