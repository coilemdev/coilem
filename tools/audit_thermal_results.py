"""Recompute thermal-only evidence from frozen native maps and saved point sources.

No EM solves, mutation of old records, or calibration fitting is performed.
Physical measurements do not exist in the pending bench registration.
"""
import argparse
import hashlib
import json
from pathlib import Path

from backend.benchmark_suite.temperature_metrics import TemperatureReference, check_temperature_interpolation, thermal_processing_identity
from backend.benchmark_suite.thermal_analytical import run_suite
from backend.loss_breakdown import operating_point_losses
from backend.models import DriveLimits, IronLoss, MotorConfig
from backend.models.thermal import ThermalInputs
from backend.resources import data_file
from backend.temperature_maps import TemperatureMapBracket
from backend.thermal_network import thermal_estimate
from backend.winding_resistance import winding_resistance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records-root', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Evidence already exists; choose a new output path')
    spec = json.loads(data_file('benchmarks/thermal-v0.6/map-interpolation-gates.json').read_text())
    native = []
    for case in spec['cases']:
        path = data_file(f"benchmarks/thermal-v0.6/{case['id']}-native.json")
        raw = path.read_bytes()
        old = json.loads(raw)
        bracket = TemperatureMapBracket.model_validate(old['bracket'])
        refs = [TemperatureReference.model_validate(r) for r in old['references']]
        new = check_temperature_interpolation(bracket, refs,
            limits=DriveLimits(dc_bus_V=case['dc_bus_V'], max_speed_rpm=case['max_speed_rpm'], peak_current_A=case['peak_current_A']),
            phase_resistance_ohm=winding_resistance(bracket.design).phase_resistance_ohm,
            thermal_inputs=ThermalInputs.model_validate(spec['thermal_inputs']),
            required_temperatures_C=tuple(spec['intermediate_C']), required_off_grid=tuple(map(tuple,spec['off_grid'])))
        native.append(dict(case_id=case['id'], source_bundle_sha256=hashlib.sha256(raw).hexdigest(),
            source_scope_keys=[bracket.low.scope_key,bracket.high.scope_key], previous_status=old['acceptance']['status'],
            acceptance=new.model_dump(mode='json')))
    points = []
    for path in sorted(args.records_root.glob('*.json')) if args.records_root else []:
        raw = path.read_bytes()
        old = json.loads(raw)
        if old.get('kind') != 'point':
            continue
        config = MotorConfig.model_validate(old['config'])
        settings = ThermalInputs.model_validate(old['inputs'])
        summary = old['source']['summary']
        iron = IronLoss.model_validate(summary['iron_loss'])
        winding, losses = operating_point_losses(config, summary['avg_torque_Nm'], iron)
        new = thermal_estimate(config, settings, winding, losses, iron, with_copper_feedback=True)
        points.append(dict(record_id=old['id'], source_sha256=hashlib.sha256(raw).hexdigest(),
            config_sha256=hashlib.sha256(json.dumps(old['config'],sort_keys=True).encode()).hexdigest(),
            inputs=old['inputs'], previous_nodes=old['result']['nodes'], result=new.model_dump(mode='json')))
    result = dict(kind='thermal_path_recomputation', output_status='experimental',
        output_status_reason='Reprocessed numerical evidence under assumed cooling; no physical motor qualification.',
        thermal_processing_sha256=thermal_processing_identity(),
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        native=native, points=points, original_analytical_suite=run_suite(),
        calibration=dict(status='NOT_COMPARED', reason='No registered motor or physical bench measurements; no calibration refit. '
            'Existing point inputs retained for comparison.'),
        note='Native EM observations reused unchanged; propagated-temperature comparisons use fixed supplied copper heat as registered, '
            'not rating feedback.')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(native=[(n['case_id'],n['acceptance']['status']) for n in native],points=len(points),
        analytical=result['original_analytical_suite']['status'])))
    return int(any(n['acceptance']['status']=='FAIL' for n in native) or result['original_analytical_suite']['status']=='FAIL')


if __name__ == '__main__':
    raise SystemExit(main())
