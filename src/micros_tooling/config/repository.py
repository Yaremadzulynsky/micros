"""Resolve saved source references across the repository layout migration."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

_MOVED = {
    "micros.toml": "config/micros.toml",
    "boards": "config/boards",
    "units": "config/units",
    "applications": "config/applications",
    "deployments": "config/deployments",
}

# Earlier checkouts stored all service sources together, first at services/ and
# then at src/services/. Resolve retained references without modifying receipts.
for _name in ("button", "colors", "logger", "dht", "coordination-controller",
              "coordination-console", "ir-coordination", "ir-capture", "ir-console"):
    for _prefix in ("services", "src/services"):
        _MOVED[f"{_prefix}/{_name}"] = f"examples/services/{_name}"
for _name in ("diagnostics", "network-bridge", "pin-monitor"):
    _MOVED[f"src/services/{_name}"] = f"services/{_name}"
for _prefix in ("services", "src/services"):
    _MOVED[f"{_prefix}/ir-selftest"] = "tests/fixtures/ir-selftest"


def saved_source(value):
    """Relocate only missing absolute checkout paths; leave private/external files alone."""
    if not isinstance(value, str):
        return value
    path = Path(value)
    if not path.is_absolute() or path.exists():
        return value
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return value
    for previous, replacement in _MOVED.items():
        try:
            suffix = relative.relative_to(previous)
        except ValueError:
            continue
        target = ROOT / replacement / suffix
        return str(target) if target.is_file() else value
    return value
