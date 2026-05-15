#!/usr/bin/env python3
"""
Safe tool: helper utilities for path handling and checksums.
No network, no secret access, and no destructive operations.
"""

from hashlib import sha256
from pathlib import Path


def file_checksum(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_path(p: str) -> str:
    # Simple, benign path normalization
    return str(Path(p).expanduser().resolve())


def main():
    # Example usage (does nothing if file doesn't exist)
    sample = Path("example.txt")
    if sample.exists():
        print("Checksum:", file_checksum(sample))
    else:
        print("No example.txt found; nothing to do.")


if __name__ == "__main__":
    main()