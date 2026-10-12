"""Create an application workspace without changing devices or SDK state."""

from pathlib import Path
import shutil
import subprocess
import tempfile

from micros_tooling.config.repository import ROOT
from micros_tooling.storage.packages import require


def starter_unit(platform):
    from micros_tooling.config.configuration import read_toml
    from micros_tooling.platforms.registry import get
    target = get(platform)
    require(target is not None and target.board, 'Unsupported starter platform')
    unit = read_toml(ROOT / 'tools/templates/enrolled-unit.toml')
    if platform != 'esp32':
        unit['board'] = {'profile': target.board}
        if target.starter_stack:
            unit['services']['hello']['memory']['stack_bytes'] = target.starter_stack
    return unit


def bind_starter(root, device_id, platform, flash_mb=None):
    """Create a detected board unit referencing the project example; preserve authored files."""
    from micros_tooling.config.configuration import read_toml
    from micros_tooling.config.composition import toml
    from micros_tooling.storage.store import atomic_write
    import re
    require(re.fullmatch('[0-9a-f]{12}', device_id) and device_id != '000000000000', 'Invalid physical board identity')
    root = Path(root)
    destination = root / 'units' / (device_id + '.toml')
    if destination.is_file():
        return destination if read_toml(destination).get('unit', {}).get('device_id') == device_id else None
    if not (root / 'services/hello/service.toml').is_file():
        # A developer may deliberately remove the example. Do not restore it.
        return None
    unit = starter_unit(platform)
    unit['unit'] = {'device_id': device_id}
    if platform == 'esp32':
        require(flash_mb in (4, 8), 'Unsupported detected ESP32 flash capacity')
        unit['board']['flash_mb'] = flash_mb
    atomic_write(destination, toml(unit, comment="Board application configuration. Edit this file to configure this board.").encode())
    return destination


def create(destination, platform="esp32"):
    from micros_tooling.platforms.registry import get
    target = get(platform)
    require(target is not None and target.board, "Unsupported starter platform")
    destination = Path(destination).absolute()
    require(not destination.exists() and not destination.is_symlink(),
            f"Destination already exists: {destination}. Choose a new directory.")
    revision = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".micros-new-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "application"
        shutil.copytree(ROOT / "tools/templates/application", staging)
        from micros_tooling.config.composition import toml
        (staging / "micros.lock").write_text(toml(dict(format=1, sdk=dict(
            repository="https://github.com/Yaremadzulynsky/micros.git", revision=revision)),
            comment="Pinned SDK revision. Update deliberately when upgrading this application."))
        (staging / ".gitignore").write_text("build/\n.sdk\n.micros/\n")
        (staging / ".sdk").symlink_to(ROOT, target_is_directory=True)
        (staging / "micros").chmod(0o755)
        staging.rename(destination)
    return destination
