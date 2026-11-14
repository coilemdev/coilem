"""Job selection must skip only proven unrelated jobs, including after renames."""
import json
import subprocess

import pytest

from tools import ci_plan


@pytest.mark.parametrize('paths,expected', [
    (['frontend/src/public/App.tsx'], {'frontend', 'browser'}),
    (['frontend/package-lock.json'], {'frontend', 'browser'}),
    (['backend/public_policy.py'], {'runtime', 'browser'}),
    (['tests/test_python_client.py'], {'runtime', 'browser'}),
    (['tools/physics_impact.py'], {'runtime', 'browser'}),
    (['solvers/magneto2d/src/main.rs'], {'runtime', 'browser', 'native', 'audit'}),
    (['pyproject.toml'], set(ci_plan.CHECKS)),
    (['requirements.lock'], set(ci_plan.CHECKS)),
    (['.github/workflows/ci.yml'], set(ci_plan.CHECKS)),
    (['README.md', 'docs/RELEASE_0_5_8.md', 'snapshot-manifest.json'], set()),
    (['benchmarks/af-v1.10/contract.json'], set(ci_plan.CHECKS)),
    (['docs/benchmarks/reference.py'], set(ci_plan.CHECKS)),
    (['new-code-directory/a.py'], set(ci_plan.CHECKS)),
    ([], set()),
    (None, set(ci_plan.CHECKS)),
    (['frontend/a.tsx', 'backend/b.py'], {'frontend', 'runtime', 'browser'}),
])
def test_path_selection(paths, expected):
    result = ci_plan.select(paths)
    assert {name for name in ci_plan.CHECKS if result[name]} == expected


@pytest.mark.parametrize('event,ref', [
    ('schedule', 'refs/heads/main'),
    ('push', 'refs/heads/release/v0.5.8'),
    ('workflow_dispatch', 'refs/heads/codex/ci'),
])
def test_release_nightly_and_manual_run_all_platforms(event, ref):
    result = ci_plan.plan(event, {}, ref, '0' * 40)
    assert all(result[name] for name in ci_plan.CHECKS)
    assert result['runtime_matrix']['include'] == ci_plan.FULL_MATRIX


@pytest.mark.parametrize('path', [
    'pyproject.toml', 'setup.py', 'requirements.lock', 'MANIFEST.in',
    'tools/release/policy.py', '.github/workflows/ci.yml',
])
def test_compatibility_changes_expand_pr_runtime_coverage(path):
    result = ci_plan.select([path])
    assert result['runtime']
    assert result['runtime_matrix']['include'] == [
        {'os': 'ubuntu-24.04', 'python': '3.11'},
        {'os': 'windows-latest', 'python': '3.11'},
        {'os': 'macos-latest', 'python': '3.11'},
        {'os': 'ubuntu-24.04', 'python': '3.15'},
    ]


def test_routine_pr_uses_two_environments():
    assert ci_plan.select(['backend/public_policy.py'])['runtime_matrix']['include'] == [
        {'os': 'ubuntu-24.04', 'python': '3.11'},
        {'os': 'windows-latest', 'python': '3.11'},
    ]


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root).decode().strip()


def test_diff_uses_pr_head_and_merge_base_and_keeps_both_sides_of_rename(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.email', 'ci-test@example.invalid')
    git(tmp_path, 'config', 'user.name', 'CI plan test')
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'frontend').mkdir()
    original = tmp_path / 'backend/original.py'
    original.write_text('original\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'base')
    base = git(tmp_path, 'rev-parse', 'HEAD')
    git(tmp_path, 'checkout', '-qb', 'feature')
    original.rename(tmp_path / 'frontend/moved.ts')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'move')
    head = git(tmp_path, 'rev-parse', 'HEAD')
    git(tmp_path, 'checkout', '-q', base)
    (tmp_path / 'requirements.lock').write_text('base advanced\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'base advanced')
    advanced_base = git(tmp_path, 'rev-parse', 'HEAD')
    paths = ci_plan.changed_paths(tmp_path, advanced_base, head, pull_request=True)
    assert set(paths) == {'backend/original.py', 'frontend/moved.ts'}
    result = ci_plan.plan('pull_request', {'pull_request': {'base': {'sha': advanced_base}, 'head': {'sha': head}}},
                          'refs/pull/1/merge', advanced_base, tmp_path)
    assert result['runtime'] and result['frontend'] and not result['native']
    assert 'requirements.lock' in ci_plan.changed_paths(tmp_path, advanced_base, head, pull_request=False)


@pytest.mark.parametrize('base,head', [('0' * 40, 'f' * 40), ('a' * 40, 'b' * 40), ('--bad', 'HEAD')])
def test_missing_or_invalid_history_defaults_to_all_jobs(tmp_path, base, head):
    assert ci_plan.changed_paths(tmp_path, base, head, pull_request=True) is None


def test_main_writes_boolean_and_matrix_outputs(monkeypatch, tmp_path, capsys):
    event_path = tmp_path / 'event.json'
    output = tmp_path / 'outputs'
    event_path.write_text('{}')
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(event_path))
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'workflow_dispatch')
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    ci_plan.main()
    values = dict(line.split('=', 1) for line in output.read_text().splitlines())
    assert values['runtime'] == 'true'
    assert json.loads(values['runtime_matrix'])['include'] == ci_plan.FULL_MATRIX
    assert json.loads(capsys.readouterr().out)['runtime'] is True
