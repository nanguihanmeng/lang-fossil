"""Modern Python 3 module: must produce zero fossils."""

from __future__ import annotations

import sys


def main() -> int:
    """Entry point."""
    print(sys.version_info)
    data = {"a": 1}
    for key, value in data.items():
        if key in data:
            print(key, value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
