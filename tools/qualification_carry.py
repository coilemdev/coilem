"""Prepare measured qualification evidence; unchanged numbers use a bounded fast path.

Never edits a native run or FEMM bundle. Moved values produce a review table;
neither a changed gate nor an incompatible reference can be auto-accepted.
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
from pathlib import Path

from backend.benchmark_suite.contract import canonical, checked_path, read, sha, write
from backend.benchmark_suite.physics import physics_sources
from backend.benchmark_suite.record import TOLERANCES, build_record, gate_statuses, gated_values
from backend.benchmark_suite.references import load_bundle, load_suite, require_reviewed_bundle
from backend.resources import BENCHMARK_REFERENCE_BUNDLE_DIR, BENCHMARK_SUITE_FILE

ROOT = Path(__file__).resolve().parents[1]
POLICY = 'benchmarks/qualification-policy.json'
# Reference geometry/material/excitation and metric interpretation. Orchestration
# remains fully guarded by physics_sources(), but does not alone invalidate FEMM.
REFERENCE_SOURCES = (
    'backend/geometry.py', 'backend/geometry_drawer.py', 'backend/geometry_ir.py',
    'backend/geometry_ir_tessellation.py', 'backend/material_contract.py', 'backend/material_catalog.py',
    'backend/public_material_catalog.py', 'backend/winding_utils.py', 'backend/excitation.py',
    'backend/reference_models/prius.py', 'backend/reference_models/pyleecan_prius_2004.json',
    'backend/reference_models/pyleecan_prius_2004_config.json', 'backend/torque_metrics.py',
    'backend/back_emf_harmonics.py', 'backend/dq_flux_linkage.py', 'backend/models/config.py',
    'materials/electrical-steel/M350-50A.csv',
)


def policy_report(root, entry):
    path = checked_path(root, entry['file'])
    if sha(path) != entry['sha256']:
        raise ValueError('Owner-approved baseline changed')
    return read(path)


def reference_compatibility(summary, anchor, suite, bundle):
    spec = load_suite(suite)
    manifest, _, digest = load_bundle(bundle, spec)
    require_reviewed_bundle(bundle, manifest, spec)
    run, old = summary['run'], anchor['run']
    if run['selection']['spec_sha256'] != sha(suite) or old['selection']['spec_sha256'] != sha(suite):
        raise ValueError('Reference reuse requires the same registered suite')
    if any(r['selection']['bundle_sha256'] != digest for r in (run, old)):
        raise ValueError('Reference reuse requires the approved registered bundle')
    before = {row['id']: row for row in anchor['rows']}
    expected = {case['id'] for case in spec['cases']}
    if ({row['id'] for row in summary['rows']} != expected or set(before) != expected
            or len(summary['rows']) != len(expected) or len(anchor['rows']) != len(expected)):
        raise ValueError('Reference reuse requires exact registered coverage')
    for row in summary['rows']:
        if row['configurations'] != before[row['id']]['configurations']:
            raise ValueError(f'Reference input interpretation needs review: {row["id"]}')
    for path in REFERENCE_SOURCES:
        if run['identity']['source_files'].get(path) != old['identity']['source_files'].get(path):
            raise ValueError(f'Reference model or metric interpretation needs review: {path}')
    return {'schema': 'coilem.reference_reuse/v1', 'candidate': run['identity']['commit'],
            'suite_sha256': sha(suite), 'bundle_sha256': digest,
            'reference_commit': manifest['reference_commit'], 'reference_fields_mutated': False,
            'reference_sensitive_sources': {p: run['identity']['source_files'].get(p) for p in REFERENCE_SOURCES},
            'registered_requests_sha256': canonical({r['id']: r['configurations'] for r in summary['rows']})}


def observations(row):
    if row['status'] not in ('PASS', 'YELLOW', 'FAIL'):
        return {}
    if row['phase'] == 'E':
        # Phase E has its own metrics and never inherits A–D qualification.
        cogging = row['measurements']['native']['summary']['cogging']
        return {'cogging_peak_to_peak_Nm': cogging['peak_to_peak_Nm'],
                'cogging_first_harmonic_Nm': cogging['first_harmonic_Nm']}
    values = gated_values(row)
    if row['phase'] != 'D':
        summary = row['measurements']['native']['summary']
        dq = summary.get('dq_flux_linkage') or {}
        values.update({key: dq[key] for key in ('lambda_d_Wb', 'lambda_q_Wb', 'lambda_pm_Wb') if dq.get(key) is not None})
    return values


def differences(candidate, previous, approved, tolerances):
    changes = []
    for name in sorted(set(candidate) | set(previous) | set(approved)):
        actual = candidate.get(name)
        for label, values in (('previous', previous), ('approved', approved)):
            expected = values.get(name)
            tolerance = tolerances.get(name.rsplit('.', 1)[-1])
            valid = all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)
                        for v in (actual, expected))
            limit = max(tolerance[1], abs(expected) * tolerance[0]) if valid and tolerance else None
            if limit is None or abs(actual - expected) > limit:
                changes.append({'metric': name, 'baseline': label, 'old': expected, 'new': actual, 'tolerance': limit})
    return changes


def compare_summary(summary, previous, approved, tolerances):
    old = {r['id']: r for r in previous['rows']}
    anchor = {r['id']: r for r in approved['rows']}
    if set(old) != set(anchor) or set(old) != {r['id'] for r in summary['rows']}:
        raise ValueError('Changed case coverage needs owner review')
    table, moved = [], []
    for row in summary['rows']:
        cid = row['id']
        for basis in (old[cid], anchor[cid]):
            if row['status'] != basis['status'] or gate_statuses(row['evaluation']) != gate_statuses(basis['evaluation']):
                raise ValueError(f'Changed numerical verdict or gate: {cid}')
        values, prior, approved_values = observations(row), observations(old[cid]), observations(anchor[cid])
        moved.extend({'case': cid, **d} for d in differences(values, prior, approved_values, tolerances))
        for name, value in values.items():
            reference = row.get('reference') or {}
            reference_value = reference.get('summary', {}).get(name)
            if name.endswith('mean_torque_Nm'):
                reference_value = row['evaluation'].get('reference_average_Nm')
            if name == 'back_emf_fundamental_V':
                reference_value = reference.get('summary', {}).get('back_emf_fundamental_V')
            table.append({'case': cid, 'metric': name, 'old': prior.get(name), 'new': value,
                          'approved': approved_values.get(name), 'FEMM': reference_value, 'gate_result': row['status']})
    return moved, table


def prius_values(report):
    values = {}
    for job in report['jobs']:
        for name in ('mean_torque_Nm', 'line_ab_sampled_rms_V', 'line_ab_sampled_peak_V', 'phase_neutral_fundamental_rms_V'):
            if job['metrics'].get(name) is not None:
                values[f'{job["job"]}.{name}'] = job['metrics'][name]
    return values


def prepare(platforms, *, baseline=ROOT, output, accept_moved=False, root=ROOT):
    policy = read(baseline / POLICY)
    if set(platforms) != {'windows-x86_64', 'macos-arm64'}:
        raise ValueError('Both platform collections are required')
    output.mkdir(parents=True, exist_ok=False)
    staged, all_moved, table, candidate, reference_errors = {}, [], [], None, []
    physical = {name: sha(root / name) for name in physics_sources(root)}
    tolerances = {**TOLERANCES, **policy['additional_replay_tolerances']}
    for platform, folder in platforms.items():
        summary = read(folder / 'joined-suite/report/benchmark_summary.json')
        run = summary['run']
        candidate = candidate or run['identity']['commit']
        if not re.fullmatch('[0-9a-f]{40}', candidate):
            raise ValueError('Need an immutable candidate SHA')
        if (run['status'] != 'COMPLETE' or run.get('smoke') or run['identity'].get('dirty') is not False
                or run['reference_mode'] != 'FROZEN_REFERENCE'
                or run['identity']['commit'] != candidate
                or any(run['identity']['source_files'].get(p) != digest for p, digest in physical.items())):
            raise ValueError('Incomplete, dirty or mixed field candidates')
        from backend.benchmark_suite.record import identity_platform_key
        if identity_platform_key(run['identity']) != platform:
            raise ValueError('Platform collection was mislabeled')
        previous_record = read(baseline / f'benchmarks/records/{platform}.json')
        previous = read(checked_path(baseline, previous_record['source'] + '/benchmark_summary.json'))
        approved = policy_report(baseline, policy['approved_reports'][platform])
        try:
            receipt = reference_compatibility(summary, approved, baseline / BENCHMARK_SUITE_FILE,
                                               baseline / BENCHMARK_REFERENCE_BUNDLE_DIR)
        except ValueError as error:
            receipt = {'status': 'REFERENCE_REVIEW_REQUIRED', 'reason': str(error)}
            reference_errors.append({'platform': platform, 'reason': str(error)})
        moved, rows = compare_summary(summary, previous, approved, tolerances)
        all_moved.extend({'platform': platform, **d} for d in moved)
        table.extend({'platform': platform, **row} for row in rows)
        # Same verdicts can include deliberately experimental cases; no broader
        # feature qualification is inferred from record equality.
        for row in summary['rows']:
            if row['status'] not in ('PASS', 'UNSUPPORTED'):
                raise ValueError('The registered A–D qualification requires passing supported cases')
        prius = read(folder / 'prius-report/app-results.json')
        if (prius['field_source_commit'] != candidate or prius['field_source_dirty'] is not False
                or not prius['all_software_checks_pass'] or not all(prius['checks'].values())
                or not prius['checks'] or not prius.get('grading_provenance', {}).get('frozen_before_fields')
                or len(prius['jobs']) != 17
                or sum(len(a['field_reports']) for a in prius.get('audits', {}).values()) != 568
                or any(prius['source_sha256'].get(p) != digest for p, digest in physical.items())):
            raise ValueError('Prius candidate evidence is incomplete or stale')
        previous_prius_path = previous_record.get('prius_report', policy['approved_prius']['file'])
        previous_prius = read(checked_path(baseline, previous_prius_path))
        approved_prius = policy_report(baseline, policy['approved_prius'])
        prius_tolerances = {**tolerances, 'line_ab_sampled_rms_V': TOLERANCES['back_emf_fundamental_V'],
                            'phase_neutral_fundamental_rms_V': TOLERANCES['back_emf_fundamental_V'],
                            'line_ab_sampled_peak_V': TOLERANCES['back_emf_peak_V']}
        all_moved.extend({'platform': platform, 'case': 'Prius', **d} for d in differences(
            prius_values(prius), prius_values(previous_prius), prius_values(approved_prius), prius_tolerances))
        staged[platform] = folder, summary, receipt
    fields = ['platform', 'case', 'metric', 'old', 'new', 'approved', 'FEMM', 'gate_result']
    with (output / 'comparison.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(table)
    status = ('REFERENCE_REVIEW_REQUIRED' if reference_errors else
              'OWNER_REVIEW_REQUIRED' if all_moved and not accept_moved else 'READY')
    decision = {'schema': 'coilem.qualification_carry/v1', 'status': status, 'candidate': candidate,
                'moved_values': all_moved, 'reference_review': reference_errors,
                'accepted_moved_values': bool(all_moved and accept_moved),
                'approved_policy_sha256': sha(baseline / POLICY), 'measurements_mutated': False}
    write(output / 'decision.json', decision)
    heading = {'READY': 'Qualification evidence ready',
               'REFERENCE_REVIEW_REQUIRED': 'Reference review required',
               'OWNER_REVIEW_REQUIRED': 'Owner review required: values moved'}[status]
    lines = [f'# {heading}', '', f'Measured candidate: `{candidate}`.', '',
             '[Full old / new / approved / FEMM comparison](comparison.csv)', '']
    if reference_errors:
        lines.extend(['Reference compatibility needs owner review. Accepting moved values cannot override this check.', ''])
        lines.extend(f'- {error["platform"]}: {error["reason"]}' for error in reference_errors)
        lines.append('')
    if all_moved:
        lines.extend(['| Platform | Case | Metric | Baseline | Old | New |', '|---|---|---|---|---:|---:|'])
        lines.extend(f'| {d["platform"]} | {d["case"]} | {d["metric"]} | {d["baseline"]} | {d["old"]} | {d["new"]} |'
                     for d in all_moved)
    (output / 'REVIEW.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    if status != 'READY':
        return decision
    publication = output / 'publication'
    for platform, (folder, summary, receipt) in staged.items():
        base = f'benchmarks/qualification-{candidate[:12]}/{platform}'
        report_source = base + '/report'
        target = publication / report_source
        shutil.copytree(folder / 'joined-suite/report', target)
        prius_source = base + '/prius'
        shutil.copytree(folder / 'prius-report', publication / prius_source)
        write(publication / base / 'reference-reuse.json', receipt)
        record = build_record(summary, source=report_source, physics_files=physical)
        record.update(prius_report=prius_source + '/app-results.json',
                      carry_receipt=base + '/carry-receipt.json', reference_reuse=base + '/reference-reuse.json')
        write(publication / base / 'carry-receipt.json', decision)
        write(publication / f'benchmarks/records/{platform}.json', record)
    return decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows', required=True, type=Path)
    parser.add_argument('--macos', required=True, type=Path)
    parser.add_argument('--baseline', type=Path, default=ROOT)
    parser.add_argument('--root', type=Path, default=ROOT, help='Candidate checkout; tooling runs from the trusted base')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--accept-moved', action='store_true', help='Owner-reviewed numerical changes only; never overrides gates')
    args = parser.parse_args()
    result = prepare({'windows-x86_64': args.windows, 'macos-arm64': args.macos}, baseline=args.baseline,
                     output=args.out, accept_moved=args.accept_moved, root=args.root)
    print(result['status'])
    return 0 if result['status'] == 'READY' else 2


if __name__ == '__main__':
    raise SystemExit(main())
