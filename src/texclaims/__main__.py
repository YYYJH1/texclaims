"""Allow ``python -m texclaims`` to behave exactly like the console script."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
