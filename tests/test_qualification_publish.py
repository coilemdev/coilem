"""The publisher accepts compact evidence only, and fails without partial writes."""
import subprocess
from pathlib import Path

import pytest

from backend.benchmark_suite.contract import sha, write
from tools import qualification_publish as publisher

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def publication(tmp_path):
    root = tmp_path / 'candidate'
    root.mkdir()
    registry = 'backend/benchmark_suite/physics.py'
    target = root / registry
    target.parent.mkdir(parents=True)
    target.write_bytes((ROOT / registry).read_bytes())
    for platform in ('windows-x86_64', 'macos-arm64'):
        write(root / f'benchmarks/records/{platform}.json', {'original': True})
    write(root / 'snapshot-manifest.json', {'files': [], 'public_patches': []})
    subprocess.run(['git', 'init', str(root)], check=True, capture_output=True)
    for key, value in [('user.name', 'Test'), ('user.email', 'test@example.com')]:
        subprocess.run(['git', '-C', str(root), 'config', key, value], check=True)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-m', 'candidate'], check=True, capture_output=True)
    candidate = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    folder = tmp_path / 'publication'
    for platform in ('windows-x86_64', 'macos-arm64'):
        write(folder / f'benchmarks/records/{platform}.json', {'measured_commit': candidate})
    write(folder / f'benchmarks/qualification-{candidate[:12]}/report.json', {'measured': True})
    return root, folder, candidate


def test_rejected_evidence_restores_original_records(publication, monkeypatch):
    root, folder, candidate = publication
    before = sha(root / 'benchmarks/records/windows-x86_64.json')
    monkeypatch.setattr(publisher, 'check', lambda *args, **kwargs: ['stale Prius'])
    with pytest.raises(ValueError, match='stale Prius'):
        publisher.apply(folder, root, candidate)
    assert sha(root / 'benchmarks/records/windows-x86_64.json') == before
    assert not (root / f'benchmarks/qualification-{candidate[:12]}/report.json').exists()


def test_changed_pr_head_cannot_be_overwritten(publication):
    root, folder, _ = publication
    with pytest.raises(ValueError, match='advanced'):
        publisher.apply(folder, root, '0' * 40)


def test_publication_cannot_write_application_code_or_raw_fields(publication):
    root, folder, candidate = publication
    write(folder / 'backend/field.py', {'not': 'evidence'})
    with pytest.raises(ValueError, match='Unexpected publication path'):
        publisher.apply(folder, root, candidate)


def test_candidate_registry_is_never_executed_by_publisher(publication):
    root, folder, candidate = publication
    (root / 'backend/benchmark_suite/physics.py').write_text('raise AssertionError("must not execute")')
    with pytest.raises(ValueError, match='Registry changes need owner review'):
        publisher.apply(folder, root, candidate)
