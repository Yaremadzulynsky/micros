"""Install the pinned board SDK for the terminal onboarding flow."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
SDK = ROOT / "build/toolchains/esp-idf-v5.5.2"
SDK_REVISION = "30aaf64524299d3bde422ca9a2848090d1bc5d0f"


def main():
    SDK.parent.mkdir(parents=True, exist_ok=True)
    if not SDK.exists():
        subprocess.run(["git", "clone", "--branch", "v5.5.2", "--depth", "1",
                        "--shallow-submodules", "--recursive", "https://github.com/espressif/esp-idf.git", str(SDK)], check=True)
    revision = subprocess.check_output(["git", "-C", str(SDK), "rev-parse", "HEAD"], text=True).strip()
    if revision != SDK_REVISION:
        raise ValueError("Existing ESP-IDF checkout is not the pinned revision; preserve it and select the documented SDK.")
    # IDF creates its own virtual environment and rejects being installed from
    # ours. Use the base interpreter that created the supported SDK environment.
    python = sys._base_executable
    subprocess.run([python, str(SDK / "tools/idf_tools.py"), "install", "--targets=esp32"], check=True)
    subprocess.run([python, str(SDK / "tools/idf_tools.py"), "install-python-env"], check=True)
    print("ESP32 SDK ready. Run ./micros init NAME; onboarding activates the SDK automatically.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print("micros setup: " + str(error), file=sys.stderr)
        sys.exit(1)
