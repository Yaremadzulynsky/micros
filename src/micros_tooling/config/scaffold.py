"""Create an application workspace without changing devices or SDK state."""

from pathlib import Path
import shutil
import subprocess
import tempfile

from micros_tooling.config.repository import ROOT
from micros_tooling.storage.packages import require


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
        service = staging / "services/hello"
        (service / "src").mkdir(parents=True)
        for name in ("service.toml", "src/service.c"):
            shutil.copy2(ROOT / "examples/hello-service" / name, service / name)
        from micros_tooling.config.composition import toml
        if platform != "esp32":
            from micros_tooling.config.configuration import read_toml
            unit_path = staging / "units/000000000000.toml"
            unit = read_toml(unit_path)
            unit["board"] = {"profile": target.board}
            if target.starter_stack:
                unit["services"]["hello"]["memory"]["stack_bytes"] = target.starter_stack
            unit_path.write_text(toml(unit))
        (staging / "micros.lock").write_text(toml(dict(format=1, sdk=dict(
            repository="https://github.com/Yaremadzulynsky/micros.git", revision=revision))))
        (staging / ".gitignore").write_text("build/\n.sdk\n.micros/\n")
        (staging / ".sdk").symlink_to(ROOT, target_is_directory=True)
        (staging / "micros").chmod(0o755)
        staging.rename(destination)
    return destination
