"""The PR gate owns freshness; historical replay tests need no live-tree pin."""
import subprocess

import pytest

from tools import physics_impact


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL).decode().strip()


def put(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init')
    git(tmp_path, 'config', 'user.name', 'Test')
    git(tmp_path, 'config', 'user.email', 'test@example.com')
    git(tmp_path, 'config', 'core.autocrlf', 'false')
    put(tmp_path, '.gitignore', '__pycache__/\n')
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


def test_metadata_push_reuses_the_same_measurement_identity(repo):
    root, base = repo
    original = physics_impact.measurement_key(root)
    put(root, 'README.md', 'metadata only')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'metadata')
    assert physics_impact.measurement_key(root) == original == physics_impact.measurement_key(root, base)
    put(root, 'backend/field.py', 'changed physics')
    assert physics_impact.measurement_key(root) != original


@pytest.mark.parametrize('ready', [False, True])
def test_compatible_active_or_completed_ci_collection_is_reused(repo, monkeypatch, ready):
    root, base = repo
    put(root, 'README.md', 'metadata only')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'metadata')
    key = physics_impact.measurement_key(root)

    def api(endpoint):
        if '/workflows/' in endpoint:
            return {'workflow_runs': [{'id': 123, 'head_sha': base,
                                      'status': 'completed' if ready else 'in_progress',
                                      'conclusion': 'failure' if ready else None}]}
        if '/jobs?' in endpoint:
            return {'jobs': [{'name': 'qualification-measure / join (macos-15)',
                              'conclusion': 'success' if ready else None}]}
        return {'artifacts': [{'name': f'benchmark-joined-{platform}', 'expired': False}
                             for platform in ('macos-15', 'windows-2022')] if ready else []}
    monkeypatch.setattr(physics_impact, 'github', api)
    found = physics_impact.reusable_collection(root, key, 'owner/repository', 'branch', '999')
    assert found['reuse_run_id'] == '123' and found['measurement_candidate'] == base
    assert found['collection_state'] == ('complete' if ready else 'in_progress')


def test_skipped_measurement_job_cannot_mask_an_older_real_collection(repo, monkeypatch):
    root, base = repo

    def api(endpoint):
        if '/workflows/' in endpoint:
            return {'workflow_runs': [{'id': 123, 'head_sha': base, 'status': 'in_progress', 'conclusion': None}]}
        return {'jobs': [{'name': 'qualification-measure', 'conclusion': 'skipped'}]}
    monkeypatch.setattr(physics_impact, 'github', api)
    assert not physics_impact.reusable_collection(root, physics_impact.measurement_key(root), 'owner/repo', 'branch', '999')['reuse_run_id']


REGISTRY_WITH_DEPENDENCIES = (
    'PHYSICS_DEPENDENCIES = ("gmsh",)\nDEPENDENCY_LOCK_FILE = "requirements.lock"\n'
    'def physics_sources(root):\n    return ("backend/field.py",)\n'
    'def pinned_dependencies(text):\n'
    '    return {"gmsh": tuple(sorted(line.split("==")[1] for line in text.splitlines() if line.startswith("gmsh==")))}\n'
)


@pytest.fixture
def repo_with_lock(repo):
    root, _ = repo
    put(root, physics_impact.REGISTRY, REGISTRY_WITH_DEPENDENCIES)
    put(root, 'requirements.lock', 'fastapi==1.0\ngmsh==4.15.2\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'name the physics dependencies')
    return root, git(root, 'rev-parse', 'HEAD')


def test_a_mesher_version_bump_is_a_physics_change(repo_with_lock):
    root, base = repo_with_lock
    put(root, 'requirements.lock', 'fastapi==1.0\ngmsh==4.16.0\n')
    assert physics_impact.changed_physics(root, base) == ['requirements.lock']


def test_another_package_bump_is_not_a_physics_change(repo_with_lock):
    root, base = repo_with_lock
    put(root, 'requirements.lock', 'fastapi==2.0\ngmsh==4.15.2\n')
    assert physics_impact.changed_physics(root, base) == []


def test_a_bump_counts_in_the_pr_that_first_names_the_dependencies(repo):
    root, base = repo
    put(root, 'requirements.lock', 'gmsh==4.15.2\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'lock')
    base = git(root, 'rev-parse', 'HEAD')
    put(root, physics_impact.REGISTRY, REGISTRY_WITH_DEPENDENCIES)
    put(root, 'requirements.lock', 'gmsh==4.16.0\n')
    assert physics_impact.changed_physics(root, base) == ['backend/benchmark_suite/physics.py', 'requirements.lock']
