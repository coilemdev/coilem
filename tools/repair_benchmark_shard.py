"""Repair a failed shard using its exact measured candidate and original binary.

This is orchestration only. Completed requests/results remain byte-identical;
new fields run through the frozen candidate's own public collection tools.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8', newline='\n')
    temporary.replace(path)


def copy_job(source, target, *, omit_runtime=False):
    def link_or_copy(src, dst):
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
        return dst
    shutil.copytree(source, target, copy_function=link_or_copy,
                    ignore=shutil.ignore_patterns('native-runtime', '*.tar.gz', '*.tmp', 'run.lock') if omit_runtime else None)


def prepare_native_repair(prior, output, configs, identity, native, cli, source_run, execution_overrides=None):
    """Stage a resume copy, retaining verified successes and archiving failed attempts."""
    path = prior / 'run_manifest.json'
    parent_sha = digest(path)
    manifest = read(path)
    pairs = [(job['case_id'], job['stage']) for job in manifest['jobs']]
    if (manifest['identity'] != identity or manifest['smoke']
            or set(pairs) != set(configs) or len(pairs) != len(configs)
            or set(manifest['selection']['case_ids']) != {case for case, _ in configs}):
        raise ValueError('Native repair does not match the frozen candidate and shard selection')
    reused = []
    for job, key in zip(manifest['jobs'], pairs, strict=True):
        request_path = native.checked_path(prior, job['request'])
        request = read(request_path)
        if (digest(request_path) != job['request_sha256'] or request['identity'] != identity
                or request['config'] != configs[key]):
            raise ValueError('Native repair request changed')
        result_path = native.checked_path(prior, job['result'])
        if job['status'] == 'COMPLETE' or result_path.is_file():
            data = cli.verify_artifact(prior, job, identity)
            if job['status'] == 'COMPLETE':
                if data['status'] != 'COMPLETE' or job.get('exit_code') != 0:
                    raise ValueError('Cannot reuse incomplete native fields')
                reused.append({'case_id': key[0], 'stage': key[1], 'result_sha256': job['result_sha256']})
    copy_job(prior, output, omit_runtime=True)
    retried = []
    for job in manifest['jobs']:
        if job['status'] != 'ERROR':
            continue
        result_path = native.checked_path(output, job['result'])
        failed = output / 'repair-receipts' / parent_sha[:12] / result_path.parent.relative_to(output)
        failed.mkdir(parents=True)
        write(failed / 'job.json', job)
        for name in (result_path.name, 'worker.log', 'native-runtime.tar.gz.json'):
            artifact = result_path.parent / name
            if artifact.is_file():
                artifact.replace(failed / name)
        retried.append({'case_id': job['case_id'], 'stage': job['stage']})
        for key in ('result_sha256', 'error', 'exit_code', 'pid', 'started_at', 'completed_at'):
            job.pop(key, None)
        job['status'] = 'READY'
    write(output / 'run_manifest.json', manifest)
    write(output / 'repair-receipt.json', {'parent_manifest_sha256': parent_sha,
        'source_run_id': source_run, 'requests_mutated': False,
        'reused_complete_jobs': reused, 'retried_failed_jobs': retried,
        'execution_overrides': execution_overrides or {},
        'original_raw_fields_retained_in_source_run': True})
    return manifest, parent_sha


def repair_prius(prior, output, selected, registry, expected, contract, collect):
    parent = read(prior / 'registration.json')
    parent_sha = digest(prior / 'registration.json')
    contract.verify_registered_identity(parent)
    contract.verify_identity(expected, parent['identity'])
    contract.grading_inputs(prior, parent)
    jobs = parent['selection']['jobs']
    if (len(jobs) != len(selected) or {j['job'] for j in jobs} != set(selected)
            or any(j['request'] != registry[j['job']] for j in jobs)):
        raise ValueError('Repair selection differs from the frozen registered requests')
    completed = {j['job']: j for j in parent['jobs']}
    if len(completed) != len(parent['jobs']) or not set(completed) <= set(selected):
        raise ValueError('Invalid completed-job selection')
    for name, job in completed.items():
        if parent['job_states'][name]['status'] != 'COMPLETE' or job['request'] != registry[name]:
            raise ValueError('Completed job is inconsistent with its registered request')
        contract.verify_completed_job(prior, job, expected)
    output.mkdir(parents=True, exist_ok=False)
    merged = copy.deepcopy(parent)
    merged.update(jobs=[], job_states={}, status='RUNNING', complete=False)
    for entry in parent['frozen_inputs'].values():
        target = output / entry['file']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prior / entry['file'], target)
    proof = {'schema': 'coilem.collection_repair/v1', 'parent_registration_sha256': parent_sha,
             'reused_jobs': sorted(completed), 'new_case_registration_sha256': {}, 'requests_mutated': False}
    merged['repair'] = proof
    finishes = []
    # Keep verified completed work durable before attempting any missing case.
    for name in selected:
        if name not in completed:
            continue
        job, state = completed[name], parent['job_states'][name]
        copy_job(prior / job['directory'], output / job['directory'])
        merged['jobs'].append(job)
        merged['job_states'][name] = state
        finishes.extend(a['finished_utc'] for a in state['attempts'] if a['status'] == 'COMPLETE')
        print(f'Verified completed {name}; retaining original measurement', flush=True)
    write(output / 'registration.json', merged)
    try:
        for name in selected:
            if name in completed:
                continue
            case = output / 'repair-attempts' / name
            print(f'Collecting missing {name} with the frozen candidate', flush=True)
            collect(name, case)
            registration = read(case / 'registration.json')
            contract.verify_registered_identity(registration)
            contract.verify_identity(expected, registration['identity'])
            contract.grading_inputs(case, registration)
            if (not registration.get('complete') or registration['status'] != 'COMPLETE'
                    or registration['frozen_inputs'] != parent['frozen_inputs'] or len(registration['jobs']) != 1):
                raise ValueError('Repaired case is incomplete or changed its grading inputs')
            job = registration['jobs'][0]
            if job['job'] != name or job['request'] != registry[name]:
                raise ValueError('Repaired case changed its registered request')
            contract.verify_completed_job(case, job, expected)
            state, source = registration['job_states'][name], case
            proof['new_case_registration_sha256'][name] = digest(case / 'registration.json')
            finishes.append(registration['finished_utc'])
            write(output / 'repair-receipts' / f'{name}.json', registration)
            copy_job(source / job['directory'], output / job['directory'])
            merged['jobs'].append(job)
            merged['job_states'][name] = state
            write(output / 'registration.json', merged)
            # The verified job files and exact case registration are retained above.
            shutil.rmtree(source)
        merged.update(status='COMPLETE', complete=True, finished_utc=max(finishes))
        write(output / 'registration.json', merged)
    except BaseException:
        merged.update(status='FAILED', complete=False)
        write(output / 'registration.json', merged)
        raise
    if digest(prior / 'registration.json') != parent_sha:
        raise ValueError('Original registration changed during repair')
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--shard', required=True)
    args = parser.parse_args()
    root, directory = args.candidate_root.resolve(), args.directory.resolve()
    sys.path.insert(0, str(root))
    from backend.benchmark_suite import contract as native
    from tools import benchmark_prius as runner
    from tools import prius_benchmark_contract as prius
    from tools.benchmark_shards import plan

    if native.ROOT.resolve() != root:
        raise ValueError('Collector backend is outside the frozen candidate')
    receipt = read(directory / 'build-receipt.json')
    binary = root / 'solvers/magneto2d/target/release' / ('magneto2d.exe' if os.name == 'nt' else 'magneto2d')
    if (native.identity(binary) != receipt['identity'] or plan(root) != receipt['plan']):
        raise ValueError('Repair must use the exact original candidate, binary and collection environment')
    shard = next(s for s in receipt['plan']['shards'] if s['id'] == args.shard)
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)

    def run(*options):
        subprocess.run([sys.executable, '-m', *map(str, options)], cwd=root, env=env, check=True)

    prior, output = directory / 'prior', directory / 'out'
    if shard['kind'] == 'prius':
        registry = {name: runner.parse_public_motor_config(body).model_dump(mode='json')
                    for name, body in runner.jobs(True, True)}
        repair_prius(prior, output, shard['cases'], registry, runner.current_identity(), prius,
                     lambda name, path: run('tools.benchmark_prius', '--out', path,
                                             '--curve', '--refinement', '--only', name))
    else:
        from backend.benchmark_suite import cli
        from backend.benchmark_suite.references import load_suite

        spec = load_suite(root / receipt['plan']['suite'])
        selected = [case for case in spec['cases'] if case['id'] in shard['cases']]
        configs, _, _ = cli.inputs(spec, selected)
        # Use bounded execution on a repaired Windows worker. These controls
        # change scheduling only; registered mesh and solver inputs stay exact.
        overrides = {'COILEM_MAGNETO2D_GMSH_PRODUCER_WORKERS': '2', 'COILEM_MAGNETO2D_GMSH_SOLVE_WORKERS': '2',
                     'COILEM_MAGNETO2D_FIELD_PREVIEW_WORKERS': '1'} if os.name == 'nt' else {}
        env.update(overrides)
        manifest, parent_sha = prepare_native_repair(prior, output, configs, receipt['identity'], native, cli,
                                                     os.environ.get('SOURCE_RUN'), overrides)
        phases = sorted({case['phase'] for case in selected})
        options = ['tools.run_benchmarks', '--resume', '--suite', receipt['plan']['suite'],
                   '--phases', *phases, '--out-dir', output, '--archive-runtime']
        if manifest['reference_mode'] == 'NATIVE_ONLY':
            options.append('--no-reference')
        for name in shard['cases']:
            options.extend(['--case', name])
        run(*options)
        if digest(prior / 'run_manifest.json') != parent_sha:
            raise ValueError('Original native run manifest changed during repair')
    write(output / 'workflow-receipt.json', {'candidate': receipt['identity']['commit'],
        'plan_sha256': receipt['plan']['plan_sha256'], 'shard': shard,
        'run_url': os.environ.get('COILEM_WORKFLOW_RUN_URL'), 'binary_sha256': digest(binary),
        'repair_tool_sha256': digest(Path(__file__)), 'source_candidate_relabelled': False,
        'source_run_id': os.environ.get('SOURCE_RUN')})


if __name__ == '__main__':
    main()
