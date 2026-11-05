"""The PR gate owns freshness; historical replay tests need no live-tree pin."""
import subprocess

import pytest

from tools import physics_impact


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL).decode().strip()


def put(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init')
    git(tmp_path, 'config', 'user.name', 'Test')
    git(tmp_path, 'config', 'user.email', 'test@example.com')
    put(tmp_path, physics_impact.REGISTRY, 'def physics_sources(root):\n    return ("backend/field.py",)\n')
    put(tmp_path, 'backend/field.py', 'original')
    put(tmp_path, 'README.md', 'original')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'baseline')
    return tmp_path, git(tmp_path, 'rev-parse', 'HEAD')


def test_documentation_change_needs_no_evidence(repo, monkeypatch):
    root, base = repo
    put(root, 'README.md', 'updated')
    monkeypatch.setattr(physics_impact, 'check', lambda _: pytest.fail('Nonphysics PR must not requalify'))
    assert physics_impact.assess(root, base)['status'] == 'PASS'


def test_changed_physics_fails_with_one_clear_evidence_check(repo, monkeypatch):
    root, base = repo
    put(root, 'backend/field.py', 'changed')
    monkeypatch.setattr(physics_impact, 'check', lambda _: ['Prius measured-source mismatch', 'stale Mac record'])
    result = physics_impact.assess(root, base)
    assert result['changed_files'] == ['backend/field.py']
    assert result['measurement_required'] and result['status'] == 'qualification evidence required'


def test_refreshed_matching_evidence_allows_physics_pr(repo, monkeypatch):
    root, base = repo
    put(root, 'backend/field.py', 'changed')
    monkeypatch.setattr(physics_impact, 'check', lambda _: [])
    result = physics_impact.assess(root, base)
    assert result['physics_change'] and not result['measurement_required'] and result['status'] == 'PASS'


def test_removing_a_source_from_the_new_registry_cannot_hide_its_change(repo):
    root, base = repo
    put(root, physics_impact.REGISTRY, 'def physics_sources(root):\n    return ()\n')
    put(root, 'backend/field.py', 'changed')
    assert physics_impact.changed_physics(root, base) == ['backend/benchmark_suite/physics.py', 'backend/field.py']


def test_prius_specific_sources_are_guarded(repo):
    root, base = repo
    name = next(iter(physics_impact.PRIUS_EXTRA_PHYSICS))
    put(root, name, 'changed')
    assert name in physics_impact.changed_physics(root, base)
