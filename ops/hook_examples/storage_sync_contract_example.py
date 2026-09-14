#!/usr/bin/env python3
"""Example storage hook contract. Replace dry-run body before production use."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("file path and destination directory required", file=sys.stderr)
        return 2
    source = Path(argv[0])
    destination = Path(argv[1])
    if not source.is_file():
        print("source file not found", file=sys.stderr)
        return 3
    destination.mkdir(parents=True, exist_ok=True)
    copied = destination / source.name
    shutil.copy2(source, copied)
    print(json.dumps({"status": "stored", "external_id": copied.name, "provider": "contract-example"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
