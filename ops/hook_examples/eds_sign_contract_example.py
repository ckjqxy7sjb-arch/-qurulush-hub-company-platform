#!/usr/bin/env python3
"""Example EDS hook contract. Replace dry-run body before production use."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if not argv:
        print("payload path required", file=sys.stderr)
        return 2
    payload_path = Path(argv[0])
    if not payload_path.is_file():
        print("payload file not found", file=sys.stderr)
        return 2
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if not payload.get("document_id"):
        print("document_id required", file=sys.stderr)
        return 3
    out_dir = Path(argv[1]) if len(argv) > 1 else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(payload_path, out_dir / "eds-payload.json")
    print(json.dumps({"status": "signed", "external_id": "DRY-RUN-EDS", "provider": "contract-example"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
