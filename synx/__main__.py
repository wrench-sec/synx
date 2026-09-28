"""Allow the CLI to be started with ``python -m synx``."""

from __future__ import annotations

import sys

from synx.cli import main

if __name__ == "__main__":
    sys.exit(main())
