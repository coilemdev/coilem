"""Acceptance checker rejects plausible but corrupted exports without rerunning FEM."""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from backend.performance_report import ReportContext, build_idiq_table_csv, build_performance_csv
from tools.check_performance_acceptance import (
    MAP_HEADER,
    ValidationError,
    check,
    javascript_digest,
    report_data,
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/benchmarks/performance-acceptance-139-142/windows/spm-8p12s'


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


@pytest.fixture(scope='module')
def valid_evidence(tmp_path_factory):
    directory = tmp_path_factory.mktemp('acceptance-valid')
    for path in EVIDENCE.iterdir():
        if path.is_file() and path.name != 'export-check.json':
            shutil.copyfile(path, directory / path.name)
    analysis = json.loads((directory / 'analysis.json').read_text())
    data = report_data(analysis)
    winding = analysis['winding_resistance']
    context = ReportContext(design_name='Example SPM 8p/12s', map_preset='standard',
                            phase_resistance={'status': winding['status'], 'reason': winding['status_reason']})
    source = json.loads((directory / 'recheck-environment.json').read_text())['source_commit']
    previous = os.environ.get('COILEM_BUILD_COMMIT')
    os.environ['COILEM_BUILD_COMMIT'] = source
    try:
        (directory / 'performance.csv').write_bytes(build_performance_csv(data, context))
        (directory / 'idiq.csv').write_bytes(build_idiq_table_csv(data, context))
    finally:
        if previous is None:
            os.environ.pop('COILEM_BUILD_COMMIT', None)
        else:
            os.environ['COILEM_BUILD_COMMIT'] = previous
    with (directory / 'map.csv').open('w', newline='') as output:
        writer = csv.writer(output)
        writer.writerow(MAP_HEADER)
        for point in analysis['map']['points']:
            writer.writerow([point.get(field) for field in MAP_HEADER])
    write_json(directory / 'report-request.json', {
        'map': analysis['map'], 'limits': analysis['settings']['limits'], 'control': data.control,
        'phase_resistance_ohm': data.phase_resistance_ohm, 'winding_temperature_C': data.winding_temperature_C,
        'mechanical_loss_W': data.mechanical_loss_W, 'context': context.model_dump(mode='json'),
    })
    write_json(directory / 'recheck-progress.json', [])
    return directory


@pytest.fixture
def evidence(valid_evidence, tmp_path):
    shutil.copytree(valid_evidence, tmp_path, dirs_exist_ok=True)
    return tmp_path


def test_valid_evidence_and_receipt_are_repeatable_and_immutable(evidence):
    first = check(evidence)
    receipt = (evidence / 'export-check.json').read_bytes()
    assert first['passed'] and first['csv_cell_comparisons'] > 15000
    assert check(evidence) == first
    assert (evidence / 'export-check.json').read_bytes() == receipt
    (evidence / 'torque-efficiency.png').write_bytes(b'changed image')
    with pytest.raises(ValidationError, match='receipt hash/size mismatch: torque-efficiency.png'):
        check(evidence)
    assert (evidence / 'export-check.json').read_bytes() == receipt


@pytest.mark.parametrize('filename', ['performance.csv', 'map.csv', 'idiq.csv'])
@pytest.mark.parametrize('mutation', ['number', 'unit', 'missing', 'duplicate', 'nonfinite'])
def test_every_csv_rejects_corrupt_cells_and_structure(evidence, filename, mutation):
    path = evidence / filename
    rows = list(csv.reader(io.StringIO(path.read_text())))
    header_name = 'i_d_A' if filename == 'idiq.csv' else 'current_peak_A'
    header_index = 1 if filename == 'performance.csv' else next(i for i, row in enumerate(rows) if row[0] == header_name)
    if filename == 'performance.csv':
        index = next(i for i, row in enumerate(rows) if row[:2] == ['efficiency_map', 'copper_loss'])
        numeric = 3
    else:
        index = header_index + 1
        numeric = 0
    if mutation == 'number':
        rows[index][numeric] = str(float(rows[index][numeric]) + 1)
    elif mutation == 'unit':
        if filename == 'performance.csv':
            rows[index][2] = 'kW'
        else:
            rows[header_index][0] = 'i_d_mA' if filename == 'idiq.csv' else 'current_rms_A'
    elif mutation == 'missing':
        rows.pop(index)
    elif mutation == 'duplicate':
        rows.insert(index, rows[index])
    else:
        rows[index][numeric] = 'NaN'
    with path.open('w', newline='') as output:
        csv.writer(output).writerows(rows)
    with pytest.raises(ValidationError):
        check(evidence)
    assert not (evidence / 'export-check.json').exists()


@pytest.mark.parametrize(('filename', 'change', 'message'), [
    ('browser-check.json', lambda a: a.update(passed=False), 'browser check failed'),
    ('analysis.json', lambda a: a['map']['points'].pop(), '70 map points'),
    ('analysis.json', lambda a: a['map']['points'][0].update(status='failed'), 'unsuccessful'),
    ('analysis.json', lambda a: a['map']['points'].__setitem__(0, a['map']['points'][1]), 'cover the grid'),
    ('recheck.json', lambda a: a.update(grid_resolved_again=True), 'solved the grid again'),
    ('recheck.json', lambda a: a.update(returned_map_sha256='0' * 64), 'map hash mismatch'),
    ('recheck-progress.json', lambda a: a.append({'stage': 'torque_speed_map'}), 'emitted map progress'),
    ('timing.json', lambda a: a.update(request_sha256='0' * 64), 'request hash mismatch'),
    ('map-progress.json', lambda a: a.pop(), '62 ordered'),
    ('report-request.json', lambda a: a.update(phase_resistance_ohm=99), 'phase_resistance_ohm differs'),
])
def test_measurement_and_recheck_claims_are_verified(evidence, filename, change, message):
    path = evidence / filename
    value = json.loads(path.read_text())
    change(value)
    write_json(path, value)
    with pytest.raises(ValidationError, match=message):
        check(evidence)
    assert not (evidence / 'export-check.json').exists()


def test_optimized_python_cannot_bypass_checks(evidence):
    path = evidence / 'browser-check.json'
    value = json.loads(path.read_text())
    value['passed'] = False
    write_json(path, value)
    result = subprocess.run([sys.executable, '-O', '-m', 'tools.check_performance_acceptance', str(evidence)],
                            cwd=ROOT, text=True, capture_output=True)
    assert result.returncode != 0 and 'browser check failed' in result.stderr
    assert not (evidence / 'export-check.json').exists()


def test_javascript_digest_matches_original_receipts():
    timing = json.loads((EVIDENCE / 'timing.json').read_text())
    assert javascript_digest(EVIDENCE / 'request.json') == timing['request_sha256']
    recheck = json.loads((EVIDENCE / 'recheck.json').read_text())
    assert javascript_digest(EVIDENCE / 'analysis.json', 'map') == recheck['returned_map_sha256']


def test_manual_acceptance_concurrency_is_unique_for_cold_and_recheck():
    workflow = (ROOT / '.github/workflows/ci.yml').read_text()
    group = next(line for line in workflow.splitlines() if 'group: public-candidate-' in line)
    assert "inputs.performance_acceptance_only && format('-performance-{0}', github.run_id)" in group
    assert 'performance_recheck_run' not in group


def test_receipt_cannot_omit_export_hashes(evidence):
    check(evidence)
    path = evidence / 'export-check.json'
    receipt = json.loads(path.read_text())
    receipt['files'].pop('idiq.csv')
    write_json(path, receipt)
    with pytest.raises(ValidationError, match='missing required file hashes'):
        check(evidence)


@pytest.mark.parametrize('dirty', [False, True])
def test_historical_recovery_requires_the_exact_clean_export_source(tmp_path, monkeypatch, dirty):
    from tools.regenerate_performance_csvs import regenerate
    source = json.loads((EVIDENCE / 'recheck-environment.json').read_text())['source_commit']

    def git_output(command, **kwargs):
        if command[1] == 'rev-parse':
            return source if dirty else '0' * 40
        return ' M backend/performance_report.py' if dirty else ''

    monkeypatch.setattr(subprocess, 'check_output', git_output)
    output = tmp_path / 'recovered'
    with pytest.raises(ValueError, match='clean and match'):
        regenerate(tmp_path, EVIDENCE, output)
    assert not output.exists()


@pytest.mark.parametrize('mutation', ['value', 'unit', 'omission'])
def test_numeric_contract_catches_errors_even_when_the_csv_producer_agrees(evidence, monkeypatch, mutation):
    import tools.check_performance_acceptance as checker
    path = evidence / 'performance.csv'
    rows = list(csv.reader(io.StringIO(path.read_text())))
    index = next(i for i, row in enumerate(rows) if row[:2] == ['result', 'peak_torque'])
    if mutation == 'value':
        rows[index][3] = '99999'
    elif mutation == 'unit':
        rows[index][2] = 'W'
    else:
        rows.pop(index)
    output = io.StringIO(newline='')
    csv.writer(output).writerows(rows)
    content = output.getvalue().encode()
    path.write_bytes(content)
    monkeypatch.setattr(checker, 'build_performance_csv', lambda *args: content)
    with pytest.raises(ValidationError):
        check(evidence)
