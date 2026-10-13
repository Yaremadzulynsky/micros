#!/usr/bin/env python3
"""Generate a base's board header at CMake configuration time."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from micros_tooling.config.resources import load_board, board_header, board_partitions
from micros_tooling.storage.packages import require
from micros_tooling.storage.store import atomic_write

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--board", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--flash-size")
parser.add_argument("--partitions", type=Path)
parser.add_argument("--ota", action="store_true")
args = parser.parse_args()
board = load_board(args.board)
if args.flash_size:
    require(args.flash_size == f"{board.get('flash_mb', 8)}MB",
            "SDK flash size differs from board; configure with src/micros_tooling/platforms/esp32/build_network.py --board PATH")
if args.partitions:
    def rows(text):
        return [line.replace(" ", "") for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    require(rows(args.partitions.read_text()) == rows(board_partitions(board, ota=args.ota)),
            "Partition layout differs from board; configure with src/micros_tooling/platforms/esp32/build_network.py --board PATH")
header = board_header(board).encode()
if not args.output.exists() or args.output.read_bytes() != header:
    atomic_write(args.output, header)
