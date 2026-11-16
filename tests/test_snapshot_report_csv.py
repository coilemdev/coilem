"""Published report tables stay allowed after the platform records move on; nothing else does."""
import hashlib
import json

from tools.verify_snapshot import indexed_report_csvs


def report(root, folder, *, index=True, name='benchmark_results.csv', listed=None):
    path = root / 'benchmarks' / folder / 'macos-arm64/report' / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b'case,status\r\na,PASS\r\n')
    if index:
        digest = listed or hashlib.sha256(path.read_bytes()).hexdigest()
        (path.parent / 'artifact_manifest.json').write_text(json.dumps({name: digest}))
    return path.relative_to(root).as_posix()


def test_only_an_indexed_table_at_the_fixed_report_path_is_report_data(tmp_path):
    good = report(tmp_path, 'qualification-0123456789ab')
    report(tmp_path, 'qualification-0123456789ac', index=False)
    report(tmp_path, 'qualification-0123456789ad', listed='0' * 64)
    report(tmp_path, 'qualification-policy-history')
    report(tmp_path, 'qualification-0123456789ae', name='material.csv')
    report(tmp_path, 'other-0123456789ab')
    assert indexed_report_csvs(tmp_path) == {good}
