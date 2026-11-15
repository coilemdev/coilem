"""``python -m coilem``: the same as the ``coilem`` command."""

import sys

from backend.launcher import main

if __name__ == "__main__":
    sys.exit(main())
