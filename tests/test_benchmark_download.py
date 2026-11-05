"""Joining evidence does not need to duplicate raw runtime archives."""

import pytest

from tools.download_benchmark_shards import compact, download


def test_compact_copy_keeps_exact_measurements_and_prius_audit_inputs(tmp_path):
    source, out = tmp_path / 'source', tmp_path / 'compact'
    (source / 'retained').mkdir(parents=True)
    for name in ('request.json', 'result.json', 'native-runtime.tar.gz.json', 'retained/pose_report.json.gz'):
        (source / name).write_bytes(b'original ' + name.encode())
    (source / 'native-runtime.tar.gz').write_bytes(b'large redundant archive')
    compact(source, out)
    assert not (out / 'native-runtime.tar.gz').exists()
    for path in out.rglob('*'):
        if path.is_file():
            assert path.read_bytes() == (source / path.relative_to(out)).read_bytes()
    assert (source / 'native-runtime.tar.gz').read_bytes() == b'large redundant archive'


def test_download_rejects_unregistered_platform_or_run_without_network(tmp_path):
    with pytest.raises(ValueError):
        download('owner/repo', 'not-a-run', 'macos-15', tmp_path / 'out')
