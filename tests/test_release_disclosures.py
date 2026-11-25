"""Known private measured claims: how they are fingerprinted and found, and the snapshot check that refuses them.

The real claims are kept in the private repository; these tests use made-up ones.
"""

from __future__ import annotations

import json
import re

import pytest

from tools import verify_snapshot
from tools.release import disclosures

CLAIM = "the made-up motor's rotor loss reads 37.25% above the imaginary reference (Phase Z, 2031-01-02)"


@pytest.fixture
def known() -> disclosures.Fingerprints:
    return disclosures.Fingerprints.from_phrases([CLAIM, "| Winding mean (C) | 101.234567 | 102.345678 |"])


def test_a_claim_is_found_whatever_its_layout(known: disclosures.Fingerprints) -> None:
    rewrapped = ("x = 1\n# Before the fix THE MADE-UP motor's rotor loss\n#   reads 37.25 % above the imaginary\n"
                 "# reference (**Phase Z**, 2031-01-02).\n")
    assert known.find(rewrapped) == [0]
    table = "| Quantity | Previous | Corrected |\n| --- | ---: | ---: |\n| Winding mean (C) | 101.234567 | 102.345678 |\n"
    assert known.find(table) == [1]
    assert known.find(f"{CLAIM}\n\n{table}") == [0, 1]


def test_a_reworded_or_changed_claim_is_not_a_match(known: disclosures.Fingerprints) -> None:
    assert known.find(CLAIM.replace("37.25", "37.26")) == []
    assert known.find("The made-up motor's rotor loss reads high against the imaginary reference.") == []
    assert known.find("") == [] and known.find("12 34 56") == []


def test_a_fingerprint_needs_enough_words_and_one_word_to_anchor_it() -> None:
    with pytest.raises(ValueError, match="at least 4"):
        disclosures.fingerprint("19 PASS")
    with pytest.raises(ValueError, match="one word"):
        disclosures.fingerprint("| 35 | 28.1 | 24.2 | 1.17% |")
    entry = disclosures.fingerprint("Rotor loss 12.5% high")
    # The anchor is the longest word, never a number, so a number cannot be recovered on its own.
    assert entry["tokens"] == 4 and entry["anchor_offset"] == 0
    assert entry["anchor"] == disclosures.fingerprint("rotor alone is long")["anchor"]


def test_the_declared_list_holds_only_hashes() -> None:
    document = json.loads(disclosures.DECLARED.read_text(encoding="utf-8"))
    assert document["schema"] == disclosures.SCHEMA and document["fingerprints"]
    for entry in document["fingerprints"]:
        assert set(entry) == {"tokens", "anchor", "anchor_offset", "sha256"}
        assert re.fullmatch(r"[0-9a-f]{64}", entry["anchor"]) and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
    assert disclosures.Fingerprints.load().count == len(document["fingerprints"])
    with pytest.raises(ValueError, match="malformed"):
        disclosures.Fingerprints([{**document["fingerprints"][0], "anchor_offset": 99}])


def test_the_scan_names_each_file_and_skips_binary_files(tmp_path, known: disclosures.Fingerprints) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "notes.md").write_text(f"Status: {CLAIM}.\n", encoding="utf-8")
    (tmp_path / "clean.py").write_text("# The rotor loss reads high on coarse meshes.\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff" + CLAIM.encode())
    failures = disclosures.scan_files(tmp_path, ["docs/notes.md", "clean.py", "image.png", "missing.txt"], known)
    assert failures == ["known private benchmark claim (fingerprint 0) in docs/notes.md; it is kept in the private repository"]


def test_the_snapshot_check_refuses_a_public_file_that_quotes_a_claim(known: disclosures.Fingerprints) -> None:
    assert verify_snapshot.claim_failures("backend/solver.py", f"# {CLAIM}\n", known) == [
        "known private benchmark claim (fingerprint 0) in backend/solver.py; it is kept in the private repository"]
    # A private copy may hold it; --public-tree refuses that file by its path instead.
    assert verify_snapshot.claim_failures("benchmarks/g-v2.0/MEASURED_CLAIMS.md", CLAIM, known) == []
    assert verify_snapshot.claim_failures("tests/private_records/test_records.py", CLAIM, known) == []
    assert verify_snapshot.claim_failures("backend/solver.py", "# The rotor loss reads high.\n", known) == []
    # The declared list is the default.
    assert verify_snapshot.claim_failures("README.md", "coilEM solves motors.") == []


def test_the_command_scans_files_and_folders(tmp_path, capsys) -> None:
    (tmp_path / "a.md").write_text("Nothing measured here.\n", encoding="utf-8")
    assert disclosures.main(["--check", str(tmp_path), str(tmp_path / "a.md")]) == 0
    assert "no declared claim found" in capsys.readouterr().out
