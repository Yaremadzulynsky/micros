"""Install the pinned ESP8266 SDK and its isolated build dependencies."""
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys

from micros_tooling.platforms.build_esp8266 import SDK_REVISION
from micros_tooling.storage.packages import require

ROOT = Path(__file__).resolve().parents[4]


def setup(root=ROOT):
    sdk = root / 'build/toolchains/esp8266-rtos-sdk-v3.4'
    python = shutil.which('python3.10')
    require(python, 'ESP8266 setup needs Python 3.10 installed. Install Python 3.10, then rerun micros enroll.')
    require(shutil.which('cmake') and shutil.which('ninja'), 'ESP8266 setup needs cmake and ninja on PATH.')
    sdk.parent.mkdir(parents=True, exist_ok=True)
    if not sdk.exists():
        subprocess.run(['git', 'clone', '--branch', 'v3.4', '--depth', '1',
                        'https://github.com/espressif/ESP8266_RTOS_SDK.git', str(sdk)], check=True)
    revision = subprocess.check_output(['git', '-C', str(sdk), 'rev-parse', 'HEAD'], text=True).strip()
    require(revision == SDK_REVISION, 'Existing ESP8266 SDK is not the pinned revision; it has been left unchanged.')
    subprocess.run(['git', '-C', str(sdk), 'submodule', 'update', '--init', '--depth', '1'], check=True)
    # Eclipse retired the SDK's old git.eclipse.org URL; retain the pinned commit.
    subprocess.run(['git', '-C', str(sdk / 'components/coap/libcoap'), 'config',
                    'submodule.ext/tinydtls.url', 'https://github.com/eclipse/tinydtls.git'], check=True)
    subprocess.run(['git', '-C', str(sdk), 'submodule', 'update', '--init', '--recursive', '--depth', '1'], check=True)
    directory = root / 'build/esp8266'
    env_python = directory / 'python/bin/python'
    if not env_python.exists():
        subprocess.run([python, '-m', 'venv', str(env_python.parent.parent)], check=True)
    subprocess.run([str(env_python), '-m', 'pip', 'install', 'pyparsing==2.3.1', 'setuptools<81',
                    'pyserial', 'future', 'click', 'cryptography', 'pyelftools'], check=True)
    site = subprocess.check_output([str(env_python), '-c', 'import site; print(site.getsitepackages()[0])'], text=True).strip()
    # Compatibility shim belongs only to the old SDK's private environment.
    (Path(site) / 'sitecustomize.py').write_text(
        'import collections, collections.abc\n'
        'for name in ("Mapping", "MutableMapping", "Sequence", "MutableSequence", "Iterable"):\n'
        '    if not hasattr(collections, name):\n'
        '        setattr(collections, name, getattr(collections.abc, name))\n')
    tools = directory / 'tools'
    env = dict(os.environ, IDF_TOOLS_PATH=str(tools.resolve()))
    # Espressif verifies the compiler archive against its pinned tools.json hash.
    installer = [str(env_python), str(sdk / 'tools/idf_tools.py')]
    if platform.system() == 'Darwin' and platform.machine() == 'arm64':
        # The pinned SDK predates Apple Silicon. Its macOS compiler uses Rosetta.
        installer = [str(env_python), '-c',
                     'import sys, platform; platform.machine = lambda: "x86_64"; '
                     'sys.path.insert(0, sys.argv.pop(1)); import idf_tools; idf_tools.main(sys.argv[1:])',
                     str(sdk / 'tools')]
    subprocess.run([*installer, 'install', 'xtensa-lx106-elf'], env=env, check=True)
    compiler = tools / 'tools/xtensa-lx106-elf/esp-2020r3-49-gd5524c1-8.4.0/xtensa-lx106-elf'
    require((compiler / 'bin/xtensa-lx106-elf-gcc').is_file(), 'ESP8266 compiler installation is incomplete.')
    target = sdk.parent / 'xtensa-lx106-elf'
    if not target.exists():
        target.symlink_to(compiler.resolve(), target_is_directory=True)
    subprocess.run([str(target / 'bin/xtensa-lx106-elf-gcc'), '--version'], check=True)


if __name__ == '__main__':
    setup()
