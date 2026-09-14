#!/usr/bin/env python3
"""Example remote backup hook contract. Replace dry-run body before production use."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("backup path, manifest path and destination directory required", file=sys.stderr)
        return 2
    backup = Path(argv[0])
    manifest = Path(argv[1])
    destination = Path(argv[2])
    if not backup.is_file() or not manifest.is_file():
        print("backup and manifest files must exist", file=sys.stderr)
        return 3
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, destination / backup.name)
    shutil.copy2(manifest, destination / manifest.name)
    print(json.dumps({"status": "stored", "external_id": backup.name, "provider": "contract-example"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
