"""Known private benchmark claims that must never reappear in public files.

Release measurements stay in the private repository (docs/RELEASING.md). Whole
records are kept out by path (``tools/release/private_evidence.py``). This
module guards the other way they leaked once: a measured comparison quoted in
an otherwise public file, such as a code comment, a docstring, a README table
or a test comment. Each such claim that was removed from a public file is kept
verbatim in the private repository, and a fingerprint of it is declared here.
The public export (``tools/release/public_tree.py``), the snapshot check
(``tools/verify_snapshot.py``) and the wheel verifier
(``tools/release/verify_wheel.py``) refuse any file in which one appears.

A fingerprint never holds the claim itself, because the declared list ships
in the public source. ``disclosure_fingerprints.json`` holds, for each claim:

* ``sha256``: SHA-256 of its normalized token sequence, with a fixed prefix;
* ``tokens``: the number of tokens in it;
* ``anchor`` and ``anchor_offset``: the SHA-256 of one word token of the claim
  (its longest word, never a number) and that word's position in the claim.

Normalizing makes the match independent of layout: the text is lowercased and
split into words (``[a-z]+``) and numbers (``[0-9]+`` with decimal parts);
punctuation, Markdown, comment markers and line breaks are dropped. A file is
scanned by hashing each distinct word once, and only at a word whose hash is an
anchor are the surrounding tokens hashed and compared. Numbers are never
hashed on their own, so a number from a claim cannot be recovered by trying
every number of its form; recovering a claim needs a guess of the whole
phrase. The hashes keep the claims out of readable public files; they are not
a secret against someone who already knows or guesses the exact wording.

The plaintext list lives in the private repository
(``tests/private_records/known_disclosures.txt``), where a test checks that it
and this declared list agree and that every claim is still kept in a private
copy. To add a claim, add its wording there and regenerate the declared list:

    python -m tools.release.disclosures --write tests/private_records/known_disclosures.txt

To scan files or folders by hand:

    python -m tools.release.disclosures --check PATH [PATH ...]

Standard library only: ``tools/verify_snapshot.py`` loads this file by path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

SCHEMA = "coilem.disclosure_fingerprints/v1"
PREFIX = "coilem disclosure fingerprint v1\n"
DECLARED = Path(__file__).resolve().with_name("disclosure_fingerprints.json")
# Shorter phrases would match ordinary prose.
MIN_TOKENS = 4
_TOKEN = re.compile(r"[0-9]+(?:\.[0-9]+)*|[a-z]+")


def tokens(text: str) -> list[str]:
    """The normalized words and numbers of ``text``."""

    return _TOKEN.findall(text.lower())


def _digest(text: str) -> str:
    return hashlib.sha256((PREFIX + text).encode("utf-8")).hexdigest()


def fingerprint(phrase: str) -> dict:
    """The declared form of one claim."""

    words = tokens(phrase)
    if len(words) < MIN_TOKENS:
        raise ValueError(f"a fingerprinted claim needs at least {MIN_TOKENS} words and numbers: {phrase!r}")
    named = [(position, word) for position, word in enumerate(words) if word.isalpha()]
    if not named:
        raise ValueError(f"a fingerprinted claim needs at least one word to anchor it: {phrase!r}")
    offset, anchor = max(named, key=lambda item: (len(item[1]), -item[0]))
    return {"tokens": len(words), "anchor": _digest(anchor), "anchor_offset": offset, "sha256": _digest(" ".join(words))}


def read_phrases(path: Path) -> list[str]:
    """One claim per line; blank lines and lines starting with ``#`` are skipped."""

    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def declared_document(phrases: Iterable[str]) -> dict:
    return {
        "schema": SCHEMA,
        "about": "Fingerprints of measured benchmark claims kept in the private repository; see tools/release/disclosures.py.",
        "fingerprints": [fingerprint(phrase) for phrase in phrases],
    }


# A NamedTuple, not a dataclass: verify_snapshot.py loads this file by path, without registering a module.
class _Entry(NamedTuple):
    index: int
    length: int
    offset: int
    sha256: str


class Fingerprints:
    """A set of declared claims, and the scan that finds them in text."""

    def __init__(self, entries: Iterable[dict]):
        self._by_anchor: dict[str, list[_Entry]] = {}
        self.count = 0
        for index, entry in enumerate(entries):
            length, offset = int(entry["tokens"]), int(entry["anchor_offset"])
            if length < MIN_TOKENS or not 0 <= offset < length:
                raise ValueError(f"fingerprint {index} is malformed")
            for key in ("anchor", "sha256"):
                if not re.fullmatch(r"[0-9a-f]{64}", str(entry[key])):
                    raise ValueError(f"fingerprint {index} has no valid {key} hash")
            self._by_anchor.setdefault(entry["anchor"], []).append(_Entry(index, length, offset, entry["sha256"]))
            self.count += 1
        self._words: dict[str, tuple[_Entry, ...]] = {}

    @classmethod
    def from_phrases(cls, phrases: Iterable[str]) -> Fingerprints:
        return cls(declared_document(phrases)["fingerprints"])

    @classmethod
    def load(cls, path: Path = DECLARED) -> Fingerprints:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if document.get("schema") != SCHEMA:
            raise ValueError(f"{path} is not a {SCHEMA} document")
        return cls(document["fingerprints"])

    def _anchored(self, word: str) -> tuple[_Entry, ...]:
        found = self._words.get(word)
        if found is None:
            found = tuple(self._by_anchor.get(_digest(word), ())) if word.isalpha() else ()
            self._words[word] = found
        return found

    def find(self, text: str) -> list[int]:
        """The indices of the declared claims that appear in ``text``."""

        words = tokens(text)
        anchors = {word for word in set(words) if self._anchored(word)}
        if not anchors:
            return []
        found = set()
        for position, word in enumerate(words):
            if word not in anchors:
                continue
            for entry in self._words[word]:
                start = position - entry.offset
                if entry.index not in found and start >= 0 and start + entry.length <= len(words) \
                        and _digest(" ".join(words[start:start + entry.length])) == entry.sha256:
                    found.add(entry.index)
        return sorted(found)

    def failures(self, name: str, text: str) -> list[str]:
        return [f"known private benchmark claim (fingerprint {index}) in {name}; it is kept in the private repository"
                for index in self.find(text)]


def scan_files(root: Path, paths: Iterable[str], fingerprints: Fingerprints | None = None) -> list[str]:
    """Failures for every UTF-8 text file among ``paths`` (relative to ``root``) that holds a declared claim."""

    fingerprints = fingerprints or Fingerprints.load()
    failures = []
    for relative in sorted(paths):
        path = Path(root) / relative
        try:
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        failures.extend(fingerprints.failures(relative, text))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", type=Path, metavar="PHRASES", help="regenerate the declared list from a plaintext claim list")
    action.add_argument("--check", type=Path, nargs="+", metavar="PATH", help="scan files or folders for declared claims")
    args = parser.parse_args(argv)
    if args.write:
        document = declared_document(read_phrases(args.write))
        DECLARED.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
        print(f"{DECLARED.name}: {len(document['fingerprints'])} fingerprints")
        return 0
    fingerprints = Fingerprints.load()
    failures = []
    for target in args.check:
        if target.is_file():
            failures.extend(scan_files(Path(), [str(target)], fingerprints))
        else:
            inside = [path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()]
            failures.extend(scan_files(target, inside, fingerprints))
    for failure in failures:
        print(failure, file=sys.stderr)
    if not failures:
        print(f"no declared claim found ({fingerprints.count} fingerprints)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
