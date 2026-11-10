"""Keep optional historical replay exceptions separate from product checks."""
import hashlib
import json

from tools import verify_snapshot


def test_legacy_replay_vocabulary_requires_verified_snapshot_context():
    text = "OPEN" + "EM_TEST=1; " + "Sprint" + " 27"
    path = "tools/femm_reference/_vendor/e/backend/example.py"
    assert len(verify_snapshot.text_hygiene_failures(path, text)) == 2
    assert not verify_snapshot.text_hygiene_failures(path, text, preserved_reference=True)
    assert len(verify_snapshot.text_hygiene_failures("backend/example.py", text)) == 2


def test_preserved_snapshot_still_checks_credentials_and_personal_paths():
    token = "ghp" + "_" + "a" * 30
    path = "/" + "Users" + "/example/private-file"
    failures = verify_snapshot.text_hygiene_failures("tools/femm_reference/_vendor/example.py", token + " " + path,
                                                    preserved_reference=True)
    assert any("token pattern" in failure for failure in failures)
    assert any("absolute user path" in failure for failure in failures)


def test_only_hash_verified_vendor_sources_get_replay_exceptions(tmp_path):
    package = tmp_path / "tools/femm_reference"
    source = package / "_vendor/e/backend/example.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"preserved source")
    manifest = {"files": {"_vendor/e/backend/example.py": {"sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}}
    (package / "source-manifest.json").write_text(json.dumps(manifest))
    sources, failures = verify_snapshot.preserved_reference_sources(tmp_path)
    assert sources == {"tools/femm_reference/_vendor/e/backend/example.py"}
    assert not failures
    source.write_bytes(b"changed source")
    sources, failures = verify_snapshot.preserved_reference_sources(tmp_path)
    assert not sources and len(failures) == 1
