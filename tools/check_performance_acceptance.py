"""Verify browser exports against saved analysis, without native solves.

Node verifies the original JSON.stringify digests. Existing receipts are
verified and never overwritten; checks remain active under python -O.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import subprocess
from pathlib import Path

from pypdf import PdfReader

from backend.drive_performance import MapModel
from backend.flux_linkage_map import map_agreement_pct
from backend.models.performance import EfficiencyMap, FluxLinkageMap, TorqueSpeedEnvelope
from backend.performance_report import PerformanceData, ReportContext, _idiq, _inductance, _mtpa, build_performance_csv
from backend.report_numbers import format_report_number

PERFORMANCE_HEADER = ['section', 'field', 'unit', 'value', 'sample_index']
MAP_HEADER = [
    'current_peak_A', 'gamma_deg', 'i_d_A', 'i_q_A', 'status', 'avg_torque_Nm', 'torque_ripple_pct',
    'lambda_d_Wb', 'lambda_q_Wb', 'iron_loss_W', 'iron_hysteresis_loss_W', 'iron_eddy_loss_W', 'nonlinear_iterations_max', 'error',
]
IDIQ_HEADER = ['i_d_A', 'i_q_A', 'current_peak_A', 'current_rms_A', 'gamma_deg', 'lambda_d_Wb', 'lambda_q_Wb', 'torque_Nm']


class ValidationError(ValueError):
    """An acceptance claim does not match its evidence."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def load(directory: Path, name: str):
    return json.loads((directory / name).read_text(encoding='utf-8'))


def file_record(path: Path) -> dict:
    content = path.read_bytes()
    return {'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}


def javascript_digest(path: Path, key: str | None = None) -> str:
    # Float serialization differs between Python and JSON.stringify. Evidence
    # is parsed as data by a fixed script; none of its content is executed.
    script = "const fs=require('node:fs'),c=require('node:crypto');let v=JSON.parse(fs.readFileSync(0,'utf8'));"
    script += "if(process.argv[1])v=v[process.argv[1]];process.stdout.write(c.createHash('sha256').update(JSON.stringify(v)).digest('hex'));"
    return subprocess.run(['node', '-e', script, key or ''], input=path.read_text(encoding='utf-8'),
                          text=True, check=True, capture_output=True).stdout


def equal(actual: str, expected, label: str, *, precision: float = 1e-10) -> None:
    if expected is None:
        require(actual == '', f'{label}: expected an empty cell')
    elif isinstance(expected, (int, float)):
        try:
            value = float(actual)
        except ValueError as exc:
            raise ValidationError(f'{label}: expected a number, got {actual!r}') from exc
        require(math.isfinite(value) and math.isfinite(expected)
                and math.isclose(value, expected, rel_tol=precision, abs_tol=precision), f'{label}: {actual} != {expected}')
    else:
        require(actual == str(expected), f'{label}: {actual!r} != {expected!r}')


def table(path: Path, header: list[str]) -> list[list[str]]:
    text = '\n'.join(line for line in path.read_text(encoding='utf-8-sig').splitlines() if not line.startswith('#'))
    rows = list(csv.reader(io.StringIO(text)))
    require(bool(rows) and rows[0] == header, f'{path.name}: incorrect header/units')
    require(all(len(row) == len(header) for row in rows[1:]), f'{path.name}: malformed row')
    return rows[1:]


def performance_rows(content: str) -> dict:
    rows = list(csv.reader(io.StringIO(content)))
    require(rows[:2] == [['report_schema', 'coilem.performance_report.v1'], PERFORMANCE_HEADER], 'performance.csv: schema/header')
    result = {}
    for row in rows[2:]:
        require(len(row) == 5, 'performance.csv: malformed row')
        section, field, unit, value, index = row
        key = section, field, index
        require(key not in result, f'performance.csv: duplicate {key}')
        result[key] = unit, value
    return result


def report_data(analysis: dict) -> PerformanceData:
    """Use saved curves/cells; interpolate only the auxiliary report tables.

    This is export transport validation, not independent physics qualification.
    No envelope, efficiency map or native solve is recomputed.
    """
    flux_map = FluxLinkageMap.model_validate(analysis['map'])
    envelope = TorqueSpeedEnvelope.model_validate(analysis['envelope'])
    efficiency = EfficiencyMap.model_validate(analysis['efficiency_map'])
    model = MapModel.from_map(flux_map)
    return PerformanceData(
        flux_map, envelope.limits, envelope.phase_resistance_ohm, envelope.winding_temperature_C,
        analysis['mechanical_loss_W'], analysis['settings']['control'], envelope, efficiency,
        [v for v in analysis['torque_agreement_pct'] if v is not None], _inductance(flux_map),
        _mtpa(model, min(envelope.limits.peak_current_A, flux_map.current_peak_A[-1])), _idiq(model),
    )


def report_context(directory: Path, analysis: dict, values: dict) -> ReportContext:
    if (directory / 'report-request.json').exists():
        request = load(directory, 'report-request.json')
        require(request['map'] == analysis['map'], 'report request: map differs from saved analysis')
        require(request['limits'] == analysis['settings']['limits'], 'report request: drive limits differ')
        envelope = analysis['envelope']
        for key, expected in {'phase_resistance_ohm': envelope['phase_resistance_ohm'],
                              'winding_temperature_C': envelope['winding_temperature_C'],
                              'mechanical_loss_W': analysis['mechanical_loss_W'],
                              'control': analysis['settings']['control']}.items():
            require(request[key] == expected, f'report request: {key} differs')
        return ReportContext.model_validate(request['context'])
    # Historical receipts bind presentation fields that predate request capture.
    require((directory / 'export-check.json').exists(), 'report-request.json required for new evidence')
    def get(section, field):
        return values[section, field, ''][1]
    winding = analysis.get('winding_resistance')
    return ReportContext(
        design_name=get('identity', 'design_name'), current_unit=get('identity', 'current_unit_shown'),
        dc_bus_source=get('input', 'dc_bus_source'), map_preset=analysis['settings']['preset'],
        phase_resistance={'status': winding['status'], 'reason': winding['status_reason']} if winding else None,
    )


def numeric_contract(data: PerformanceData, context: ReportContext) -> dict:
    """Independent field/unit mapping: a producer bug must not be its own oracle."""
    rows = {}

    def add(section, field, unit, value, index=''):
        rows[section, field, str(index)] = unit, value

    limits, flux = data.limits, data.flux_map
    for field, unit, value in (
        ('peak_current_peak', 'A', limits.peak_current_A), ('peak_current_rms', 'A', limits.peak_current_A / math.sqrt(2)),
        ('dc_bus', 'V', limits.dc_bus_V), ('modulation_index_max', '', limits.modulation_index_max),
        ('phase_voltage_limit_peak', 'V', limits.modulation_index_max * limits.dc_bus_V / 2), ('max_speed', 'rpm', limits.max_speed_rpm),
        ('phase_resistance', 'ohm', data.phase_resistance_ohm), ('winding_temperature', 'degC', data.winding_temperature_C),
        ('mechanical_loss', 'W', data.mechanical_loss_W),
    ):
        add('input', field, unit, value)
    if limits.continuous_current_A is not None:
        add('input', 'continuous_current_peak', 'A', limits.continuous_current_A)
        add('input', 'continuous_current_rms', 'A', limits.continuous_current_A / math.sqrt(2))
    for field, unit, value in (
        ('pole_pairs', '', flux.pole_pairs), ('currents', '', 7), ('current_angles', '', 10),
        ('largest_current_peak', 'A', flux.current_peak_A[-1]), ('rotor_positions_per_point', '', 24),
        ('reference_speed', 'rpm', flux.reference_speed_rpm), ('magnet_temperature', 'degC', flux.magnet_temperature_C),
    ):
        add('map', field, unit, value)
    peak = data.curve('peak')
    require(peak is not None, 'missing peak curve')
    for field, unit, value in (
        ('peak_torque', 'N m', peak.torque_Nm[0]), ('base_speed', 'rpm', peak.base_speed_rpm),
        ('peak_power', 'W', peak.peak_power_W), ('top_speed_reached', 'rpm', peak.max_speed_rpm),
        ('best_efficiency', '%', data.best_efficiency_pct),
    ):
        add('result', field, unit, value)
    if context.solved_point:
        for field, unit, value in (('speed', 'rpm', context.solved_point.speed_rpm), ('torque', 'N m', context.solved_point.torque_Nm),
                                   ('current_angle', 'deg', context.solved_point.current_angle_deg)):
            add('result', f'solved_point_{field}', unit, value)
    for curve in data.envelope.curves:
        section = f'torque_speed_{curve.limit}'
        for field, unit, value in (('base_speed', 'rpm', curve.base_speed_rpm), ('max_speed', 'rpm', curve.max_speed_rpm),
                                   ('peak_power', 'W', curve.peak_power_W)):
            add(section, field, unit, value)
        for index, speed in enumerate(curve.speed_rpm):
            d, q = curve.i_d_A[index], curve.i_q_A[index]
            current = math.hypot(d, q)
            for field, unit, value in (
                ('speed', 'rpm', speed), ('torque', 'N m', curve.torque_Nm[index]), ('power', 'W', curve.power_W[index]),
                ('i_d', 'A', d), ('i_q', 'A', q), ('current_peak', 'A', current), ('current_rms', 'A', current / math.sqrt(2)),
                ('current_angle', 'deg', math.degrees(math.atan2(-d, q)) if current > 0 else 0),
                ('phase_voltage_peak', 'V', curve.phase_voltage_peak_V[index]),
            ):
                add(section, field, unit, value, index)
    efficiency, index = data.efficiency, 0
    for r, torque in enumerate(efficiency.torque_Nm):
        for c, speed in enumerate(efficiency.speed_rpm):
            if efficiency.efficiency_pct[r][c] is None:
                continue
            for field, unit, value in (
                ('speed', 'rpm', speed), ('torque', 'N m', torque), ('efficiency', '%', efficiency.efficiency_pct[r][c]),
                ('copper_loss', 'W', efficiency.copper_loss_W[r][c]), ('iron_loss', 'W', efficiency.iron_loss_W[r][c]),
            ):
                add('efficiency_map', field, unit, value, index)
            for field, unit, array in (('current_rms', 'A', efficiency.phase_current_rms_A),
                                       ('current_angle', 'deg', efficiency.current_angle_deg)):
                if array is not None:
                    add('efficiency_map', field, unit, array[r][c], index)
            index += 1
    add('efficiency_map', 'mechanical_loss', 'W', efficiency.mechanical_loss_W)
    agreement = map_agreement_pct(flux)
    for section, entries in (('mtpa', data.mtpa), ('idiq_table', data.idiq), ('map_point', flux.points)):
        for index, entry in enumerate(entries):
            fields = [('current_peak', 'A', 'current_peak_A'), ('current_angle', 'deg', 'gamma_deg'),
                      ('i_d', 'A', 'i_d_A'), ('i_q', 'A', 'i_q_A'), ('lambda_d', 'Wb', 'lambda_d_Wb'), ('lambda_q', 'Wb', 'lambda_q_Wb')]
            fields += [('torque', 'N m', 'avg_torque_Nm' if section == 'map_point' else 'torque_Nm')]
            if section == 'map_point':
                fields += [('iron_loss', 'W', 'iron_loss_W')]
                # The saved agreement array contains only defined values in
                # PerformanceData, so preserve the full map's positions here.
                add(section, 'torque_agreement', '%', agreement[index], index)
            for field, unit, attribute in fields:
                add(section, field, unit, getattr(entry, attribute), index)
    for index, entry in enumerate(data.inductance):
        for field, unit, value in (('current_peak', 'A', entry.current_peak_A), ('L_d', 'H', entry.l_d_H), ('L_q', 'H', entry.l_q_H)):
            add('inductance', field, unit, value, index)
    return rows


def verify_measurement(directory: Path, analysis: dict) -> None:
    flux_map = analysis['map']
    require(analysis['settings']['preset'] == 'standard', 'expected Standard map')
    currents, angles = flux_map['current_peak_A'], flux_map['gamma_deg']
    require(len(currents) == len(set(currents)) == 7 and len(angles) == len(set(angles)) == 10, 'expected unique 7x10 grid')
    require(len(flux_map['points']) == 70, 'expected 70 map points')
    require({(p['current_peak_A'], p['gamma_deg']) for p in flux_map['points']}
            == {(i, a) for i in currents for a in angles}, 'map points do not cover the grid')
    require(all(p['status'] == 'ok' for p in flux_map['points']), 'map has unsuccessful points')
    require(flux_map['rotor_positions'] == 24 and flux_map['mesh_density'] == 'normal', 'expected 24 positions, normal mesh')
    require(analysis['envelope']['limits'] == analysis['settings']['limits'], 'saved envelope drive limits mismatch')
    require(analysis['envelope']['map_scope_key'] == analysis['efficiency_map']['map_scope_key'] == flux_map['scope_key'],
            'derived results map scope mismatch')
    timing, request, progress = (load(directory, name) for name in ('timing.json', 'request.json', 'map-progress.json'))
    require(timing['request_sha256'] == javascript_digest(directory / 'request.json'), 'request hash mismatch')
    require(timing['points'] == 70 and timing['distinct_solves'] == 61, 'timing point/solve count')
    require(timing['map_scope_key'] == flux_map['scope_key'], 'timing map scope mismatch')
    require(request['config']['torque_speed_analysis'] == analysis['settings'], 'request map settings mismatch')
    require([p['position'] for p in progress] == list(range(62)), 'expected 62 ordered map progress events')
    require(all(p['total'] == 61 and p['stage'] == 'torque_speed_map' for p in progress), 'map progress totals/stage')
    elapsed = [p['elapsed_s'] for p in progress]
    require(all(math.isfinite(v) for v in elapsed) and elapsed == sorted(elapsed), 'invalid map progress timing')
    equal(str(timing['map_phase_s']), elapsed[-1] - elapsed[0], 'map phase duration')
    for key, value in (('map_start_elapsed_s', elapsed[0]), ('map_end_elapsed_s', elapsed[-1]),
                       ('rotor_positions_per_point', 24), ('mesh_density', 'normal')):
        equal(str(timing[key]), value, f'timing {key}')
    environment = load(directory, 'environment.json')
    require(environment['tracked_tree_clean'] is True and environment['sample_count'] == 1
            and environment['setup_only'] is False, 'invalid cold measurement environment')
    if (directory / 'recheck.json').exists():
        recheck = load(directory, 'recheck.json')
        digest = javascript_digest(directory / 'analysis.json', 'map')
        require(recheck['measured_map_sha256'] == recheck['returned_map_sha256'] == digest, 'recheck map hash mismatch')
        require(recheck['grid_resolved_again'] is False, 'recheck solved the grid again')
        if (directory / 'recheck-progress.json').exists():
            require(load(directory, 'recheck-progress.json') == [], 'recheck emitted map progress')
        else:
            require((directory / 'export-check.json').exists(), 'recheck-progress.json required')
        env = load(directory, 'recheck-environment.json')
        require(env['source_commit'] == recheck['source_commit'] and env['sample_count'] == 0
                and env['tracked_tree_clean'] is True and env['setup_only'] is False, 'invalid recheck environment')
    require(load(directory, 'stream-errors.json') == [], 'stream reported errors')


def check(directory: Path) -> dict:
    receipt_path = directory / 'export-check.json'
    if receipt_path.exists():
        receipt = load(directory, 'export-check.json')
        require(receipt['passed'] is True and bool(receipt['files']), 'invalid existing receipt')
        required = {'analysis.json', 'browser-check.json', 'environment.json', 'request.json', 'timing.json', 'map-progress.json',
                    'stream-errors.json', 'performance.csv', 'idiq.csv', 'map.csv', 'performance.pdf'}
        require(required <= receipt['files'].keys(), 'receipt is missing required file hashes')
        for name, record in receipt['files'].items():
            require(Path(name).name == name, 'receipt contains an unsafe filename')
            require(file_record(directory / name) == record, f'receipt hash/size mismatch: {name}')
    analysis, browser = load(directory, 'analysis.json'), load(directory, 'browser-check.json')
    require(browser['passed'] is True and browser['page_errors'] == [], 'browser check failed')
    verify_measurement(directory, analysis)
    data = report_data(analysis)
    values = performance_rows((directory / 'performance.csv').read_text(encoding='utf-8-sig'))
    context = report_context(directory, analysis, values)
    expected = performance_rows(build_performance_csv(data, context).decode('utf-8'))
    # Text/notes use the report's presentation helpers; every numeric field
    # and its unit is bound independently to analysis above, not its CSV writer.
    expected.update(numeric_contract(data, context))
    environment = load(directory, 'recheck-environment.json' if (directory / 'recheck.json').exists() else 'environment.json')
    expected['identity', 'application_commit', ''] = '', environment['source_commit']
    require(values.keys() == expected.keys(), 'performance.csv: missing or unexpected samples')
    comparisons = 0
    for key, (unit, value) in expected.items():
        actual_unit, actual = values[key]
        require(actual_unit == unit, f'performance.csv {key}: incorrect unit')
        equal(actual, value, f'performance.csv {key}')
        comparisons += 1
    map_rows = table(directory / 'map.csv', MAP_HEADER)
    require(len(map_rows) == len(analysis['map']['points']), 'map.csv: incorrect point count')
    for index, (row, point) in enumerate(zip(map_rows, analysis['map']['points'])):
        for field, value in zip(MAP_HEADER, row):
            equal(value, point.get(field), f'map.csv point {index} {field}')
            comparisons += 1
    idiq_rows = table(directory / 'idiq.csv', IDIQ_HEADER)
    require(len(idiq_rows) == len(data.idiq), 'idiq.csv: incorrect grid coverage')
    for index, (row, point) in enumerate(zip(idiq_rows, data.idiq)):
        for field, value in zip(IDIQ_HEADER, row):
            expected_value = point.current_peak_A / math.sqrt(2) if field == 'current_rms_A' else getattr(point, field)
            equal(value, expected_value, f'idiq.csv point {index} {field}', precision=1e-9)  # .10g precision
            comparisons += 1
    cells = sum(v is not None for row in analysis['efficiency_map']['efficiency_pct'] for v in row)
    require(browser['efficiency_cells'] == cells, 'browser efficiency cell count')
    reader = PdfReader(directory / 'performance.pdf')
    text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    for label in ('Key results', 'Peak torque', 'Peak power', 'Best efficiency', 'Torque and power against speed', 'MTPA', 'Experimental'):
        require(label in text, f'PDF missing {label}')
    peak = data.curve('peak')
    require(peak is not None, 'missing peak curve')
    for value in (peak.torque_Nm[0], peak.peak_power_W / 1000, data.best_efficiency_pct):
        require(format_report_number(value) in text, f'PDF missing headline {value}')
    result = {
        'passed': True, 'checker_schema': 2, 'csv_cell_comparisons': comparisons, 'efficiency_cells': cells,
        'pdf_pages': len(reader.pages), 'pdf_headlines_match_analysis': True,
        'files': {path.name: file_record(path) for path in sorted(directory.iterdir()) if path.is_file() and path != receipt_path},
    }
    if not receipt_path.exists():
        with receipt_path.open('x', encoding='utf-8') as output:
            output.write(json.dumps(result, indent=2) + '\n')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', nargs='+', type=Path)
    for directory in parser.parse_args().directories:
        result = check(directory)
        print(f"{directory.name}: PASS ({result['csv_cell_comparisons']} CSV cell checks; {result['pdf_pages']} PDF pages)")


if __name__ == '__main__':
    main()
