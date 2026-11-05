"""Published evidence indexes cover the actual files, including edited prose."""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEXES = sorted((ROOT / 'docs/benchmarks').rglob('sha256.json'))


@pytest.mark.parametrize('index', INDEXES, ids=lambda p: str(p.relative_to(ROOT)))
def test_published_benchmark_checksums_match_every_bundle_file(index):
    checksums = json.loads(index.read_text())
    assert checksums
    assert set(checksums) == {p.name for p in index.parent.iterdir() if p.is_file() and p != index}
    for name, expected in checksums.items():
        assert Path(name).name == name
        assert hashlib.sha256((index.parent / name).read_bytes()).hexdigest() == expected, f'{index.parent.name}/{name}'


def test_preview_sampling_caveat_reproduces_from_retained_femm_values():
    path = ROOT / 'docs/benchmarks/cogging-windows-20261103/waveforms.json'
    original = path.read_bytes()
    case = next(case for case in json.loads(original)['cases'] if case['case_id'] == 'spm_4p12s_simple__tight_airgap__cogging')
    values = case['femm_baseline_torque_Nm']
    assert len(values) == 25  # 24 intervals, including the repeated endpoint
    full, preview = max(values) - min(values), max(values[::2]) - min(values[::2])
    assert full == pytest.approx(0.48077960120196483)
    assert preview == pytest.approx(0.4505944354788758)
    assert 100 * (1 - preview / full) == pytest.approx(6.278379042626836)
    assert path.read_bytes() == original
