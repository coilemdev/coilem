"""Sentinel qualification: show that a small change moved nothing, without a full collection.

A sentinel collection measures a covering subset of the registered suite and
two Prius jobs with their unchanged full-grid requests. Every waveform sample
and summary value is then compared with the full record of the same platform.
Unchanged numbers let a physics PR pass the evidence gate (tools.physics_impact).
Any difference needs the full collection, and the release gate
(tools.release.qualification) never accepts sentinel evidence.

    python -m tools.qualify_local --collection sentinel --candidate <SHA> --directory <folder>
    python -m tools.qualification_sentinel compare --macos <folder>/qualification --out <prepared>
    python -m tools.qualification_sentinel publish --publication <prepared>/publication --root <checkout>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

from backend.benchmark_suite.contract import canonical, checked_path, read, sha, write
from backend.benchmark_suite.physics import DEPENDENCY_LOCK_FILE, physics_sources, pinned_dependencies
from backend.benchmark_suite.record import TOLERANCES, gate_statuses, identity_platform_key
from backend.local_paths import contains_local_path
from tools.qualification_carry import POLICY, REFERENCE_SOURCES, differences, observations, policy_report
from tools.release.qualification import PRIUS_EXTRA_PHYSICS, _constant

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = 'benchmarks/qualification-sentinel.json'
EVIDENCE = 'benchmarks/sentinel/{platform}.json'
PLATFORMS = ('windows-x86_64', 'macos-arm64')
SCHEMA = 'coilem.qualification_sentinel/v1'
EVIDENCE_SCHEMA = 'coilem.sentinel_evidence/v1'
# Registered but solved by no suite job; the Prius jobs cover that rotor.
PLANNED_UNSUPPORTED = 'ornl_prius_2004_ipm'
# Run metadata and wall times are not measurements.
NOT_MEASURED = {'solve_metadata', 'solve_time_s', 'elapsed_s'}
PRIUS_METRICS = ('mean_torque_Nm', 'line_ab_sampled_rms_V', 'line_ab_sampled_peak_V', 'phase_neutral_fundamental_rms_V')


def definition(root=ROOT):
    data = read(root / DEFINITION)
    exact = data.get('exact') or {}
    if (data.get('schema') != SCHEMA or data.get('suite') != _constant(root / 'backend/resources.py', 'BENCHMARK_SUITE_FILE')
            or sha(root / data['suite']) != data.get('suite_sha256')
            or not data.get('cases') or len(set(data['cases'])) != len(data['cases'])
            or not data.get('prius_jobs') or len(set(data['prius_jobs'])) != len(data['prius_jobs'])
            or not all(_number(exact.get(key)) and exact[key] > 0 for key in ('relative_to_peak', 'absolute'))
            or not set(exact.get('platforms') or ()) <= set(PLATFORMS)):
        raise ValueError('Sentinel definition is invalid or names a different suite than the registered one')
    return data


def features(config, stage):
    """The code paths one registered request exercises, as comparable labels."""
    params, options, rotor, stator, winding = (
        config.get(key) or {} for key in ('solve_params', 'solve_options', 'rotor', 'stator', 'winding'))
    outer = config.get('rotor_layout') == 'outer'
    family = ('outer ' if outer else '') + ('SPM' if config.get('topology') == 'SPM' else f'IPM {rotor.get("ipm_topology")}')
    layout = f'{winding.get("type")} {winding.get("layers")}-layer'
    lane = ('six-step' if params.get('excitation_mode') else 'cogging' if options.get('cogging_torque') else 'sinusoidal sweep')
    found = {
        f'rotor: {family}', f'winding: {layout}', f'lane: {lane}', f'stage: {stage}',
        f'{family} with {layout}', f'{family} in {lane}', f'{layout} in {lane}',
        f'{family} {stator.get("slot_count")} slots {rotor.get("pole_count")} poles',
        f'sweep range: {params.get("rotor_sweep_range_deg")}', f'rotor step: {params.get("rotor_step_deg")}',
        f'current convention: {params.get("current_amplitude_convention")}',
        f'mesh: {params.get("mesh_density")}', f'magnet grade: {(config.get("materials") or {}).get("magnet_grade")}',
    }
    modifiers = {
        'no load': params.get('current_amplitude_A') == 0, 'current angle': bool(params.get('current_angle_deg')),
        'magnet temperature': params.get('magnet_temperature_C') is not None, 'tooth shoes': bool(stator.get('tooth_shoe_enabled')),
        'corner refinement': bool(params.get('corner_refinement')), 'angled magnet': bool(rotor.get('magnet_angle_deg')),
    }
    found.update(f'{family} with {name}' for name, present in modifiers.items() if present)
    if winding.get('coil_span'):
        found.add('chorded winding')
    if (winding.get('parallel_paths') or 1) > 1:
        found.add('parallel paths')
    return found


def uncovered(root=ROOT):
    """Code paths of the registered suite that no sentinel case exercises."""
    data = definition(root)
    by_case = {}
    for case in read(root / data['suite'])['cases']:
        by_case[case['id']] = set().union(*(features(read(root / job['fixture']), job['stage']) for job in case['jobs']))
    if not set(data['cases']) <= set(by_case) - {PLANNED_UNSUPPORTED}:
        raise ValueError('Sentinel names a case that the registered suite does not solve')
    wanted = set().union(*(found for case, found in by_case.items() if case != PLANNED_UNSUPPORTED))
    return sorted(wanted - set().union(*(by_case[case] for case in data['cases'])))


def shard_plan(root=ROOT, *, count=4):
    """The sentinel cases in balanced suite shards, and the sentinel Prius jobs in one."""
    from tools.benchmark_shards import plan

    data = definition(root)
    full = plan(root, count=count, suite=data['suite'], cases=data['cases'], prius=data['prius_jobs'], prius_count=1)
    body = {**{key: value for key, value in full.items() if key != 'plan_sha256'}, 'sentinel_sha256': sha(root / DEFINITION)}
    return {**body, 'plan_sha256': canonical(body)}


def gather_prius(shards, names):
    """The selected Prius jobs of complete shards, verified as the full join verifies them."""
    from backend.public_policy import parse_public_motor_config
    from tools.benchmark_prius import jobs as prius_jobs
    from tools.prius_benchmark_contract import grading_inputs, verify_completed_job, verify_registered_identity

    expected = {name: parse_public_motor_config(body).model_dump(mode='json')
                for name, body in prius_jobs(True, True) if name in names}
    first, gathered = None, {}
    for folder in shards:
        registration = read(folder / 'registration.json')
        verify_registered_identity(registration)
        grading_inputs(folder, registration)
        if not registration.get('complete') or registration['status'] != 'COMPLETE' or registration['source_dirty']:
            raise ValueError('Incomplete Prius shard')
        first = first or registration
        if any(registration[key] != first[key] for key in ('identity', 'frozen_inputs', 'source_machine_sha256', 'geometry_asset_sha256')):
            raise ValueError('Mixed Prius identities or grading inputs')
        for job in registration['jobs']:
            name = job['job']
            if name in gathered or name not in expected or job['request'] != expected[name]:
                raise ValueError('Unexpected, duplicate or modified Prius job')
            if registration['job_states'][name]['status'] != 'COMPLETE':
                raise ValueError('Incomplete Prius job state')
            verify_completed_job(folder, job, first['identity'])
            gathered[name] = job
    if set(gathered) != set(names) or set(expected) != set(names):
        raise ValueError('Incomplete sentinel Prius coverage')
    return {'schema': 'coilem.sentinel_prius/v1',
            **{key: first[key] for key in ('source_commit', 'source_dirty', 'source_sha256', 'binary_sha256', 'platform', 'dependencies')},
            'jobs': [{key: gathered[name][key] for key in ('job', 'request', 'metrics', 'torque_waveform', 'back_emf_waveform')}
                     for name in names]}


def join(suite_shards, prius_shards, directory, root=ROOT):
    """Join sentinel shards into the layout ``compare`` reads; no field solves."""
    from backend.resources import BENCHMARK_REFERENCE_BUNDLE_DIR
    from tools.join_benchmark_runs import join_suite

    data = definition(root)
    join_suite(suite_shards, suite=root / data['suite'], bundle=root / BENCHMARK_REFERENCE_BUNDLE_DIR,
               output=directory / 'joined-suite', cases=data['cases'])
    write(directory / 'sentinel-prius.json', gather_prius(prius_shards, data['prius_jobs']))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def measured(value):
    """Every measured number below ``value``: a waveform series as one list, any other value alone."""
    found = {}

    def walk(item, path):
        if isinstance(item, dict):
            for key, child in item.items():
                if key not in NOT_MEASURED:
                    walk(child, f'{path}/{key}' if path else key)
        elif isinstance(item, list):
            if item and all(_number(v) for v in item):
                found[path] = item
            else:
                for index, child in enumerate(item):
                    walk(child, f'{path}/{index}')
        elif _number(item):
            found[path] = item

    walk(value, '')
    return found


def exact_differences(candidate, baseline, limits):
    """Baseline values the candidate does not reproduce to the exact limits.

    A value only the candidate has is a new output, not a moved one; the next
    full record will carry it.
    """
    moved = []
    for name, expected in baseline.items():
        actual = candidate.get(name)
        series = isinstance(expected, list)
        if (not isinstance(actual, list) or len(actual) != len(expected) or not all(_number(v) for v in actual)) if series \
                else not _number(actual):
            moved.append({'metric': name, 'deviation': None, 'limit': None})
            continue
        peak = max(abs(v) for v in expected) if series else abs(expected)
        deviation = max(abs(a - e) for a, e in zip(actual, expected)) if series else abs(actual - expected)
        limit = max(limits['relative_to_peak'] * peak, limits['absolute'])
        if deviation > limit:
            moved.append({'metric': name, 'deviation': deviation, 'limit': limit})
    return moved


def prius_metrics(job):
    return {key: job['metrics'][key] for key in PRIUS_METRICS if job['metrics'].get(key) is not None}


def prius_measured(job):
    return measured({'metrics': prius_metrics(job), 'torque_waveform': job['torque_waveform'],
                     'back_emf_waveform': job['back_emf_waveform']})


def evidence(folder, platform, *, root=ROOT, baseline=ROOT):
    """The compact, publishable part of one platform's joined sentinel collection.

    ``root`` is the measured candidate checkout; the sentinel definition and the
    full record it will be compared with come from ``baseline``.
    """
    if not (folder / 'sentinel-prius.json').is_file() or not (folder / 'joined-suite/report/benchmark_summary.json').is_file():
        raise ValueError(f'Not a joined sentinel collection: {folder.name}')
    summary = read(folder / 'joined-suite/report/benchmark_summary.json')
    prius = read(folder / 'sentinel-prius.json')
    run, identity = summary['run'], summary['run']['identity']
    sources = identity['source_files']
    data = {
        'schema': EVIDENCE_SCHEMA, 'platform': platform, 'candidate': identity['commit'],
        'sentinel_sha256': sha(baseline / DEFINITION),
        'record': {'file': f'benchmarks/records/{platform}.json', 'sha256': sha(baseline / f'benchmarks/records/{platform}.json')},
        'run': {'status': run['status'], 'smoke': run.get('smoke'), 'reference_mode': run['reference_mode'],
                'started_at': run['started_at'], 'completed_at': run.get('completed_at'),
                'spec_sha256': run['selection']['spec_sha256'], 'bundle_sha256': run['selection']['bundle_sha256']},
        'identity': {key: identity.get(key) for key in (
            'commit', 'dirty', 'binary_sha256', 'python', 'platform', 'machine', 'dependencies', 'harness_version', 'protocol_version')},
        'physics_files': {name: sources.get(name) for name in physics_sources(root)},
        'reference_sources': {name: sources.get(name) for name in REFERENCE_SOURCES},
        'cases': {row['id']: {'phase': row['phase'], 'status': row['status'], 'gates': gate_statuses(row['evaluation']),
                              'configurations_sha256': canonical(row['configurations']),
                              'observations': observations(row), 'measured': measured(row['measurements'])}
                  for row in summary['rows']},
        'prius': {**{key: prius[key] for key in ('source_commit', 'source_dirty', 'binary_sha256', 'platform', 'dependencies')},
                  'physics_files': {name: prius['source_sha256'].get(name) for name in (*physics_sources(root), *PRIUS_EXTRA_PHYSICS)},
                  'jobs': {job['job']: {'request_sha256': canonical(job['request']), 'metrics': prius_metrics(job),
                                        'measured': prius_measured(job)} for job in prius['jobs']}},
    }
    if (folder / 'local-collection.json').is_file():
        # A collection made off the hosted runners says so in the published evidence.
        data['collection'] = read(folder / 'local-collection.json')
    elif (folder / 'join-receipt.json').is_file():
        data['collection'] = {'collector': 'workflow', 'run_urls': sorted({
            shard.get('run_url') for shard in read(folder / 'join-receipt.json')['shards'] if shard.get('run_url')})}
    if contains_local_path(json.dumps(data)):
        raise ValueError('Sentinel evidence would publish a machine-local path')
    return data


def assess(data, *, root=ROOT, baseline=ROOT, platform):
    """Compare one platform's sentinel evidence with the full record under ``baseline``.

    ``errors`` make the evidence unusable; ``moved`` lists values that differ from
    the full record; ``reference_review`` lists changed reference-sensitive sources
    or requests that the owner has not reviewed.
    """
    errors, moved, review = [], [], []
    rules = definition(baseline)
    policy = read(baseline / POLICY)
    actual = {name: sha(root / name) for name in physics_sources(root)}
    suite_sha = sha(baseline / rules['suite'])
    record_file = f'benchmarks/records/{platform}.json'
    record = read(baseline / record_file)
    full = read(checked_path(baseline, record['source'] + '/benchmark_summary.json'))
    approved = policy_report(baseline, policy['approved_reports'][platform])
    run, identity = data['run'], data['identity']
    if data.get('schema') != EVIDENCE_SCHEMA or data.get('platform') != platform or identity_platform_key(identity) != platform:
        errors.append('evidence is not a sentinel collection of this platform')
    if data.get('sentinel_sha256') != sha(baseline / DEFINITION):
        errors.append('evidence was collected for a different sentinel definition')
    if data['record'] != {'file': record_file, 'sha256': sha(baseline / record_file)}:
        errors.append('evidence was compared with a different full record')
    if (not re.fullmatch('[0-9a-f]{40}', str(data.get('candidate'))) or identity['commit'] != data['candidate']
            or identity.get('dirty') is not False or run['status'] != 'COMPLETE' or run.get('smoke')
            or run['reference_mode'] != 'FROZEN_REFERENCE'):
        errors.append('evidence must be a complete, clean, full-grid collection of one commit')
    if data['physics_files'] != actual:
        errors.append('evidence did not measure the current physics sources')
    if run['spec_sha256'] != suite_sha or record['suite_sha256'] != suite_sha or run['bundle_sha256'] != record['reference_bundle_sha256']:
        errors.append('evidence and the full record use a different suite or reference bundle')
    pins = pinned_dependencies((root / DEPENDENCY_LOCK_FILE).read_text(encoding='utf-8'))
    for name, versions in pins.items():
        if (identity.get('dependencies') or {}).get(name) not in versions:
            errors.append(f'evidence dependency is not the pinned one: {name}')
    full_run = full['run']
    if (full_run['status'] != 'COMPLETE' or full_run.get('smoke') or full_run['identity'].get('dirty') is not False
            or full_run['identity']['commit'] != record['measured_commit'] or full_run['selection']['spec_sha256'] != suite_sha):
        errors.append('the full record is not a complete measured collection of this suite')
    before = {row['id']: row for row in full['rows']}
    anchor = {row['id']: row for row in approved['rows']}
    exact = platform in rules['exact']['platforms']
    tolerances = {**TOLERANCES, **policy['additional_replay_tolerances']}
    if set(data['cases']) != set(rules['cases']):
        errors.append('evidence does not cover exactly the sentinel cases')
    for case in sorted(set(data['cases']) & set(before)):
        row, old = data['cases'][case], before[case]
        if row['status'] != 'PASS' or old['status'] != 'PASS' or row['gates'] != gate_statuses(old['evaluation']):
            moved.append({'case': case, 'metric': 'verdict or gate status', 'deviation': None, 'limit': None})
            continue
        if row['configurations_sha256'] != canonical(old['configurations']):
            review.append(f'{case}: the solved request differs from the one the full record measured')
        if exact:
            moved.extend({'case': case, **d} for d in exact_differences(row['measured'], measured(old['measurements']), rules['exact']))
        else:
            moved.extend({'case': case, 'metric': d['metric'], 'deviation': None if d['new'] is None or d['old'] is None
                          else abs(d['new'] - d['old']), 'limit': d['tolerance'], 'baseline': d['baseline']}
                         for d in differences(row['observations'], observations(old), observations(anchor[case]), tolerances))
    prius = data['prius']
    prius_actual = {**actual, **{name: sha(root / name) for name in PRIUS_EXTRA_PHYSICS}}
    if (prius['source_commit'] != data['candidate'] or prius['source_dirty'] is not False
            or prius['binary_sha256'] != identity['binary_sha256'] or prius['platform'] != identity['platform']
            or prius['physics_files'] != prius_actual or set(prius['jobs']) != set(rules['prius_jobs'])):
        errors.append('Prius sentinel jobs are incomplete or were not measured with the suite build')
    anchors = policy.get('approved_prius_reports')
    prius_anchor = policy['approved_prius'] if anchors is None else anchors[platform]
    full_prius = {job['job']: job for job in read(checked_path(baseline, record.get('prius_report', prius_anchor['file'])))['jobs']}
    approved_prius = {job['job']: job for job in policy_report(baseline, prius_anchor)['jobs']}
    prius_tolerances = {**tolerances, 'line_ab_sampled_rms_V': TOLERANCES['back_emf_fundamental_V'],
                        'phase_neutral_fundamental_rms_V': TOLERANCES['back_emf_fundamental_V'],
                        'line_ab_sampled_peak_V': TOLERANCES['back_emf_peak_V']}
    for name in sorted(set(prius['jobs']) & set(full_prius)):
        job, old = prius['jobs'][name], full_prius[name]
        if job['request_sha256'] != canonical(old['request']):
            review.append(f'Prius {name}: the solved request differs from the one the full record measured')
        if exact:
            found = exact_differences(job['measured'], prius_measured(old), rules['exact'])
        else:
            found = [{'metric': d['metric'], 'deviation': None if d['new'] is None or d['old'] is None else abs(d['new'] - d['old']),
                      'limit': d['tolerance'], 'baseline': d['baseline']}
                     for d in differences(job['metrics'], prius_metrics(old), prius_metrics(approved_prius[name]), prius_tolerances)]
        moved.extend({'case': f'Prius {name}', **d} for d in found)
    changed = {path: {'approved_sha256': approved['run']['identity']['source_files'].get(path), 'candidate_sha256': digest}
               for path, digest in data['reference_sources'].items()
               if digest != approved['run']['identity']['source_files'].get(path)}
    reviewed = data.get('owner_reviewed_reference_sources') or {}
    review.extend(f'reference-sensitive source changed: {path}' for path, entry in changed.items() if reviewed.get(path) != entry)
    return {'errors': errors, 'moved': moved, 'reference_review': review, 'changed_reference_sources': changed,
            'rule': 'exact' if exact else 'replay tolerances'}


def errors(root=ROOT):
    """Why the committed sentinel evidence does not cover this tree; empty when it does."""
    try:
        missing = uncovered(root)
        if missing:
            return ['sentinel cases no longer cover the registered suite: ' + ', '.join(missing)]
        found = []
        for platform in PLATFORMS:
            path = root / EVIDENCE.format(platform=platform)
            if not path.is_file():
                found.append(f'{platform}: no sentinel evidence')
                continue
            outcome = assess(read(path), root=root, baseline=root, platform=platform)
            found.extend(f'{platform}: {error}' for error in (*outcome['errors'], *outcome['reference_review']))
            if outcome['moved']:
                found.append(f'{platform}: {len(outcome["moved"])} sentinel values differ from the full record')
        return found
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f'sentinel evidence unavailable or invalid: {exc}']


def prepare(platforms, *, baseline=ROOT, root=ROOT, output, reference_reviewed=False):
    """Compare joined sentinel collections with the full records and stage what can be published."""
    if not platforms or not set(platforms) <= set(PLATFORMS):
        raise ValueError('Need at least one registered platform collection')
    output.mkdir(parents=True, exist_ok=False)
    staged, report = {}, {}
    for platform, folder in platforms.items():
        data = evidence(folder, platform, root=root, baseline=baseline)
        outcome = assess(data, root=root, baseline=baseline, platform=platform)
        if reference_reviewed and outcome['changed_reference_sources']:
            # Only changed source files can be accepted; a changed request has no override.
            data['owner_reviewed_reference_sources'] = outcome['changed_reference_sources']
            outcome = assess(data, root=root, baseline=baseline, platform=platform)
        staged[platform], report[platform] = data, outcome
    status = ('INVALID' if any(o['errors'] for o in report.values()) else
              'REFERENCE_REVIEW_REQUIRED' if any(o['reference_review'] for o in report.values()) else
              'MOVED' if any(o['moved'] for o in report.values()) else 'UNCHANGED')
    candidates = sorted({data['candidate'] for data in staged.values()})
    decision = {'schema': 'coilem.sentinel_decision/v1', 'status': status, 'candidates': candidates,
                'sentinel_sha256': sha(baseline / DEFINITION), 'approved_policy_sha256': sha(baseline / POLICY),
                'platforms': {platform: {**outcome, 'cases_compared': len(staged[platform]['cases']),
                                         'values_compared': sum(len(c['measured']) for c in staged[platform]['cases'].values())}
                              for platform, outcome in report.items()}}
    write(output / 'decision.json', decision)
    heading = {'UNCHANGED': 'Sentinel values unchanged', 'MOVED': 'Sentinel values moved: run the full collection',
               'REFERENCE_REVIEW_REQUIRED': 'Reference review required', 'INVALID': 'Sentinel collection cannot be used'}[status]
    lines = [f'# {heading}', '', 'Measured candidate: ' + ', '.join(f'`{c}`' for c in candidates) + '.', '']
    for platform, outcome in report.items():
        lines.append(f'## {platform} ({outcome["rule"]})')
        lines.append('')
        lines.extend(f'- {text}' for text in (*outcome['errors'], *outcome['reference_review']))
        if outcome['moved']:
            lines.extend(['| Case | Value | Deviation | Limit |', '|---|---|---:|---:|'])
            lines.extend(f'| {d["case"]} | {d["metric"]} | {d["deviation"]} | {d["limit"]} |' for d in outcome['moved'][:200])
        if not (outcome['errors'] or outcome['reference_review'] or outcome['moved']):
            lines.append(f'All {len(staged[platform]["cases"])} cases and {len(staged[platform]["prius"]["jobs"])} Prius jobs match the full record.')
        lines.append('')
    (output / 'REVIEW.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    if status == 'UNCHANGED':
        for platform, data in staged.items():
            write(output / 'publication' / EVIDENCE.format(platform=platform), data)
    return decision


def apply(publication, root):
    """Copy staged sentinel evidence into ``root``, verify it there, and index it in the snapshot manifest."""
    names = sorted(path.relative_to(publication).as_posix() for path in publication.rglob('*') if path.is_file())
    allowed = {EVIDENCE.format(platform=platform): platform for platform in PLATFORMS}
    if not names or not set(names) <= set(allowed):
        raise ValueError('Unexpected sentinel publication path')
    previous = {name: (root / name).read_bytes() if (root / name).is_file() else None for name in names}
    try:
        for name in names:
            target = checked_path(root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(publication / name, target)
            outcome = assess(read(target), root=root, baseline=root, platform=allowed[name])
            problems = [*outcome['errors'], *outcome['reference_review'], *(['values moved'] if outcome['moved'] else [])]
            if problems:
                raise ValueError('Sentinel publication rejected: ' + '; '.join(problems))
    except BaseException:
        for name, content in previous.items():
            target = checked_path(root, name)
            if content is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(content)
        raise
    snapshot_path = root / 'snapshot-manifest.json'
    snapshot = read(snapshot_path)
    git = ['git', '-C', str(root)]
    tracked = set(subprocess.check_output([*git, 'ls-files'], text=True).splitlines()) | set(names)
    tracked.discard('snapshot-manifest.json')
    order = [entry['path'] for entry in snapshot['files'] if entry['path'] in tracked]
    order.extend(sorted(tracked - set(order)))
    snapshot['files'] = [{'path': name, 'bytes': (root / name).stat().st_size, 'sha256': sha(root / name)} for name in order]
    head = subprocess.check_output([*git, 'rev-parse', 'HEAD'], text=True).strip()
    for name in names:
        if previous[name] is not None and previous[name] != (root / name).read_bytes():
            snapshot['public_patches'].append({'base_commit': head, 'path': name,
                'source_sha256': hashlib.sha256(previous[name]).hexdigest(), 'reason': 'Publish fresh sentinel qualification evidence.'})
    write(snapshot_path, snapshot)
    return names


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='Show the sentinel cases and how long the record computer took for them')
    compare = commands.add_parser('compare', help='Compare joined sentinel collections with the full records')
    compare.add_argument('--windows', type=Path)
    compare.add_argument('--macos', type=Path)
    compare.add_argument('--baseline', type=Path, default=ROOT)
    compare.add_argument('--root', type=Path, default=ROOT, help='Candidate checkout; tooling runs from the trusted base')
    compare.add_argument('--out', required=True, type=Path)
    compare.add_argument('--reference-reviewed', action='store_true',
                         help='Owner has reviewed the changed reference-sensitive source files; recorded in the evidence. '
                              'Never overrides a changed request or a moved value')
    publish = commands.add_parser('publish', help='Apply staged sentinel evidence to a checkout and verify it there')
    publish.add_argument('--publication', required=True, type=Path)
    publish.add_argument('--root', required=True, type=Path)
    check = commands.add_parser('check', help='Say whether committed sentinel evidence covers this tree')
    check.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if args.command == 'list':
        data = definition()
        for platform in PLATFORMS:
            times = read(ROOT / f'benchmarks/records/{platform}.json').get('case_runtime_s', {})
            total, full = sum(times.get(case) or 0 for case in data['cases']), sum(v or 0 for v in times.values())
            print(f'{platform}: {len(data["cases"])} of {len(times)} cases, about {total / 60:.0f} of {full / 60:.0f} min of case time')
        print('\n'.join(data['cases']))
        print('Prius jobs: ' + ', '.join(data['prius_jobs']))
        return 0
    if args.command == 'compare':
        folders = {platform: folder for platform, folder in (('windows-x86_64', args.windows), ('macos-arm64', args.macos)) if folder}
        if not folders:
            parser.error('compare needs --windows, --macos or both')
        result = prepare(folders, baseline=args.baseline, root=args.root, output=args.out, reference_reviewed=args.reference_reviewed)
        print(result['status'])
        return 0 if result['status'] == 'UNCHANGED' else 2
    if args.command == 'publish':
        print(json.dumps({'status': 'PASS', 'published': apply(args.publication, args.root.resolve())}))
        return 0
    found = errors(args.root)
    print(json.dumps({'status': 'BLOCKED' if found else 'PASS', 'errors': found}, indent=2))
    return 1 if found else 0


if __name__ == '__main__':
    raise SystemExit(main())
