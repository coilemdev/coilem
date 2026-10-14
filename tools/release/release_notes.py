"""Turn RELEASE_NOTES.md's repository-relative links into absolute links for a GitHub release page.

A release page has no repository context, so ``[text](docs/VALIDATION.md)`` would break there.
The release workflow rewrites each relative target to ``https://github.com/<repo>/blob/<tag>/<path>``
before it creates the draft, so no hand edit of the draft is needed.

    python -I tools/release/release_notes.py RELEASE_NOTES.md --repo coilemdev/coilem --ref v0.4.0
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# A Markdown inline-link target that is not already absolute (scheme or site root) or an in-page anchor.
RELATIVE_TARGET = re.compile(r"\]\((?![a-zA-Z][a-zA-Z0-9+.-]*:|/|#)([^)\s]+)\)")


def absolute_links(text: str, repo: str, ref: str) -> str:
    return RELATIVE_TARGET.sub(lambda m: f"](https://github.com/{repo}/blob/{ref}/{m.group(1).removeprefix('./')})", text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("notes", type=Path)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--ref", required=True, help="the release tag")
    args = parser.parse_args()
    sys.stdout.write(absolute_links(args.notes.read_text(encoding="utf-8"), args.repo, args.ref))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
