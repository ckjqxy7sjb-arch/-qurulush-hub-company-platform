#!/usr/bin/env python3
"""Example AV scanner hook contract. Replace dry-run body before production use."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if not argv:
        print("file path required", file=sys.stderr)
        return 2
    source = Path(argv[0])
    if not source.is_file():
        print("source file not found", file=sys.stderr)
        return 3
    print(json.dumps({"status": "clean", "provider": "contract-example"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
