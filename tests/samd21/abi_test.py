#!/usr/bin/env python3
"""Verify the actual ARM compiler's ABI and reject incompatible ARM profiles."""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler-dir", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "check.o"
        common = ["-mthumb", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "src/sdk/abi/include"), "-c", "-o", str(output)]
        for source, compiler, standard in [
            ("tests/samd21/target_check.c", "gcc", "c17"),
            ("tools/checks/abi_compile.c", "gcc", "c17"),
            ("tools/checks/abi_compile.cpp", "g++", "c++17"),
        ]:
            subprocess.run([str(args.compiler_dir / ("arm-none-eabi-" + compiler)),
                            "-mcpu=cortex-m0plus", "-std=" + standard, *common, str(ROOT / source)], check=True)
        for flags in [("-mcpu=cortex-m3",), ("-mcpu=cortex-m0plus", "-mbig-endian")]:
            result = subprocess.run([str(args.compiler_dir / "arm-none-eabi-gcc"),
                                     *flags, "-std=c17", *common, str(ROOT / "tests/samd21/target_check.c")],
                                    capture_output=True, text=True)
            assert result.returncode != 0 and "Unsupported micros native target" in result.stderr, result.stderr
    print("PASS: ARM C/C++ ABI layouts; incompatible architecture and endianness rejected")


if __name__ == "__main__":
    main()
