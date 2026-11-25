"""A local platform collection runs the workflow's stages and never passes off partial work."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import qualify_local

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / 'checkout'
    (root / '.github/workflows').mkdir(parents=True)
    (root / qualify_local.WORKFLOW).write_text(
        'cargo +1.94.0 build --release --locked --manifest-path solvers/magneto2d/Cargo.toml\n')

    executable = shutil.which('git') or 'git'

    def git(*args):
        subprocess.run([executable, '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', *args],
                       check=True, capture_output=True)

    git('init', '-q')
    git('add', '.')
    git('commit', '-q', '-m', 'candidate')
    head = subprocess.check_output([executable, '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    return root, head


def fake_stages(calls, fail_on=None):
    """Stand in for the build and benchmark_ci stages, writing what each one leaves behind."""
    def run(*args, root, env):
        args = [str(a) for a in args]
        calls.append(args)
        assert env['COILEM_BUILD_COMMIT'] and 'COILEM_MAGNETO2D_BINARY' not in env
        if 'tools.benchmark_ci' not in args:
            return
        stage, directory = args[3], Path(args[args.index('--directory') + 1])
        if stage == 'binary':
            directory.mkdir(parents=True)
            (directory / 'build-receipt.json').write_text(json.dumps(
                {'plan': {'shards': [{'id': 'suite-00'}, {'id': 'prius-00'}]}}))
        elif stage == 'shard':
            shard = args[args.index('--shard') + 1]
            if shard == fail_on:
                raise subprocess.CalledProcessError(1, args)
            assert (directory / 'build-receipt.json').is_file()
            out = directory / 'out'
            (out / 'jobs/case/native-runtime').mkdir(parents=True)
            (out / 'jobs/case/native-runtime/field.bin').write_text('raw')
            (out / 'jobs/case/result.json').write_text('{}')
            (out / 'archive.tar.gz').write_text('raw')
            (out / 'workflow-receipt.json').write_text(json.dumps({'shard': {'id': shard}}))
        else:
            assert sorted(p.name for p in (directory / 'shards').iterdir()) == ['local-prius-00', 'local-suite-00']
            (directory / 'join-receipt.json').write_text('{}')
    return run


def test_collects_every_shard_keeps_compact_output_and_joins(checkout, tmp_path):
    root, head = checkout
    calls, output = [], tmp_path / 'out'
    joined = qualify_local.collect(head, output, root=root, run=fake_stages(calls), free=lambda _: 50.0)
    assert joined == (output / 'qualification').resolve()
    assert [c[3] for c in calls if 'tools.benchmark_ci' in c] == ['binary', 'shard', 'shard', 'join']
    assert ['cargo', '+1.94.0', 'build', '--release', '--locked'] == calls[1][:5]
    shard = joined / 'shards/local-suite-00'
    assert (shard / 'jobs/case/result.json').is_file() and (shard / 'workflow-receipt.json').is_file()
    assert not (shard / 'jobs/case/native-runtime').exists() and not (shard / 'archive.tar.gz').exists()
    assert not (output / 'collect').exists()
    receipt = json.loads((joined / 'local-collection.json').read_text())
    assert receipt['candidate'] == head and receipt['collector'] == 'local' and set(receipt['shard_wall_time_s']) == {'suite-00', 'prius-00'}
    # A finished collection is returned as it is, with no further stage.
    calls.clear()
    assert qualify_local.collect(head, output, root=root, run=fake_stages(calls), free=lambda _: 50.0) == joined
    assert calls == []


def test_a_stopped_run_continues_from_the_first_unfinished_shard(checkout, tmp_path):
    root, head = checkout
    calls, output = [], tmp_path / 'out'
    with pytest.raises(subprocess.CalledProcessError):
        qualify_local.collect(head, output, root=root, run=fake_stages(calls, fail_on='prius-00'), free=lambda _: 50.0)
    assert not (output / 'qualification/join-receipt.json').exists()
    assert not (output / 'qualification/shards/local-prius-00').exists()
    calls.clear()
    qualify_local.collect(head, output, root=root, run=fake_stages(calls), free=lambda _: 50.0)
    assert [(c[3], c[5]) for c in calls if 'shard' in c] == [('shard', 'prius-00')]
    assert not any('cargo' in c for c in calls)


def test_low_disk_stops_before_a_shard_without_joining(checkout, tmp_path):
    root, head = checkout
    calls = []
    with pytest.raises(RuntimeError, match='GB free before suite-00'):
        qualify_local.collect(head, tmp_path / 'out', root=root, run=fake_stages(calls), free=lambda _: 1.0)
    assert not any('shard' in c or 'join' in c for c in calls)


def test_only_a_clean_checkout_at_the_candidate_outside_the_output_is_measured(checkout, tmp_path):
    root, head = checkout
    run = fake_stages([])
    with pytest.raises(ValueError, match='full immutable'):
        qualify_local.collect(head[:12], tmp_path / 'out', root=root, run=run)
    with pytest.raises(ValueError, match='not the candidate'):
        qualify_local.collect('0' * 40, tmp_path / 'out', root=root, run=run)
    with pytest.raises(ValueError, match='outside the checkout'):
        qualify_local.collect(head, root / 'out', root=root, run=run)
    (root / 'edited.py').write_text('x')
    with pytest.raises(ValueError, match='uncommitted'):
        qualify_local.collect(head, tmp_path / 'out', root=root, run=run)


def test_the_toolchain_is_the_one_the_workflow_builds_with():
    assert qualify_local.rust_toolchain() in (ROOT / qualify_local.WORKFLOW).read_text()
    assert qualify_local.RAW_PATTERNS == ('native-runtime', '*.tar.gz', '*.tmp', 'run.lock')
    assert "ignore_patterns('native-runtime', '*.tar.gz', '*.tmp', 'run.lock')" in (ROOT / qualify_local.WORKFLOW).read_text()
