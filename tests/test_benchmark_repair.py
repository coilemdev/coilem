"""Recovery preserves completed measurement bytes and refuses mixed identities."""
import copy
import gzip
import hashlib

import pytest

from backend.benchmark_suite import cli
from backend.benchmark_suite import contract as native
from backend.benchmark_suite.contract import read, sha, write
from tools import prius_benchmark_contract as contract
from tools.repair_benchmark_shard import prepare_native_repair, repair_prius


@pytest.fixture
def failed_native(tmp_path):
    prior = tmp_path / 'prior'
    identity = {'commit': 'a' * 40, 'dirty': False, 'protocol_version': '1.10.0'}
    configs = {('e-case', 'native'): {'mesh_density': 'very_fine'}, ('f-case', 'native'): {'mesh_density': 'normal'}}
    jobs = []
    for (case, stage), config in configs.items():
        directory = f'jobs/{case}/{stage}'
        request, result = directory + '/request.json', directory + '/result.json'
        write(prior / request, {'config': config, 'identity': identity})
        request_sha = sha(prior / request)
        status = 'COMPLETE' if case.startswith('e-') else 'ERROR'
        write(prior / result, {'status': status, 'request_sha256': request_sha,
                               'identity_before': identity, 'identity_after': identity})
        (prior / directory / 'worker.log').write_text(status, encoding='utf-8')
        (prior / directory / 'native-runtime.tar.gz').write_bytes(b'original retained raw fields')
        jobs.append({'case_id': case, 'stage': stage, 'status': status, 'request': request, 'result': result,
                     'request_sha256': request_sha, 'result_sha256': sha(prior / result), 'exit_code': 0 if status == 'COMPLETE' else 2})
    write(prior / 'run_manifest.json', {'identity': identity, 'smoke': False,
                                       'selection': {'case_ids': ['e-case', 'f-case']}, 'jobs': jobs})
    return prior, tmp_path / 'out', configs, identity


def test_native_repair_retries_only_error_and_preserves_completed_and_failed_evidence(failed_native):
    prior, out, configs, identity = failed_native
    before = {p.relative_to(prior): sha(p) for p in prior.rglob('*') if p.is_file()}
    manifest, parent_sha = prepare_native_repair(prior, out, configs, identity, native, cli, '123')
    complete, failed = manifest['jobs']
    assert complete['status'] == 'COMPLETE' and sha(out / complete['result']) == complete['result_sha256']
    assert failed['status'] == 'READY' and not (out / failed['result']).exists() and 'result_sha256' not in failed
    assert sha(out / failed['request']) == failed['request_sha256']
    attempt = out / 'repair-receipts' / parent_sha[:12] / failed['result']
    assert sha(attempt) == sha(prior / failed['result'])
    assert not list(out.rglob('*.tar.gz'))
    assert {p.relative_to(prior): sha(p) for p in prior.rglob('*') if p.is_file()} == before


def test_native_repair_refuses_tampered_completed_result(failed_native):
    prior, out, configs, identity = failed_native
    result = prior / read(prior / 'run_manifest.json')['jobs'][0]['result']
    result.write_bytes(result.read_bytes() + b' ')
    with pytest.raises(ValueError, match='evidence changed'):
        prepare_native_repair(prior, out, configs, identity, native, cli, '123')
    assert not out.exists()


def job(root, name, identity):
    folder = root / f'jobs/{name}/attempt-1'
    request = {'case': name}
    result = {'summary': {'avg_torque_Nm': 1.}, 'torque_waveform': {'torque_Nm': [1.]},
              'back_emf_waveform': {'phase_a_V': [0.]}, 'solve_metadata': {}}
    for filename, payload in [('request.json', request), ('result.json', result), ('result-original.json', result),
                              ('environment.json', {})]:
        write(folder / filename, payload)
    raw = b'original native field'
    retained = folder / 'retained/field.json.gz'
    retained.parent.mkdir()
    with gzip.open(retained, 'wb') as stream:
        stream.write(raw)
    write(folder / 'artifact-index.json', [{'file': 'field.json', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}])
    return {'job': name, 'directory': f'jobs/{name}/attempt-1', 'request': request, 'environment': {},
            'metrics': {'mean_torque_Nm': 1.}, 'identity_before': identity, 'identity_after': identity,
            'torque_waveform': result['torque_waveform'], 'back_emf_waveform': result['back_emf_waveform'], 'solve_metadata': {},
            **{key: sha(folder / filename) for filename, key in [
                ('request.json', 'request_sha256'), ('result.json', 'result_sha256'),
                ('result-original.json', 'result_original_sha256'), ('environment.json', 'environment_sha256'),
                ('artifact-index.json', 'artifact_index_sha256')]}}


def registration(root, names, completed, identity):
    frozen = {}
    for key, source in contract.GRADING_INPUTS.items():
        name = f'frozen-inputs/{key}.json'
        write(root / name, {})
        frozen[key] = {'source': source, 'file': name, 'sha256': sha(root / name)}
    data = {'schema': contract.SCHEMA, 'identity': identity, 'source_commit': identity['commit'], 'source_dirty': False,
            'source_sha256': identity['source_files'], 'binary_sha256': identity['binary_sha256'],
            'platform': identity['platform'], 'python': identity['python'], 'dependencies': identity['dependencies'],
            'frozen_inputs': frozen, 'selection': {'jobs': [{'job': n, 'request': {'case': n}} for n in names]},
            'jobs': [job(root, n, identity) for n in completed],
            'job_states': {n: {'status': 'COMPLETE', 'attempts': [{'status': 'COMPLETE', 'finished_utc': '2026-11-04T00:00:00Z'}]}
                           for n in completed}, 'complete': len(names) == len(completed),
            'status': 'COMPLETE' if len(names) == len(completed) else 'FAILED', 'finished_utc': '2026-11-04T00:00:00Z'}
    write(root / 'registration.json', data)
    return data


@pytest.fixture
def recovery(tmp_path):
    identity = {'commit': 'a'*40, 'dirty': False, 'source_files': {}, 'collector_source_sha256': {},
                'binary_sha256': 'b'*64, 'platform': 'test', 'python': 'test', 'dependencies': {}}
    prior, output = tmp_path / 'prior', tmp_path / 'repaired'
    registration(prior, ['a', 'b'], ['a'], identity)
    calls = []

    def collect(name, path):
        calls.append(name)
        registration(path, [name], [name], identity)
    return prior, output, identity, collect, calls


def test_repair_collects_only_missing_cases_and_keeps_original_bytes(recovery):
    prior, output, identity, collect, calls = recovery
    before = {str(p.relative_to(prior)): sha(p) for p in prior.rglob('*') if p.is_file()}
    result = repair_prius(prior, output, ['a', 'b'], {'a': {'case': 'a'}, 'b': {'case': 'b'}}, identity, contract, collect)
    assert calls == ['b'] and result['complete'] and result['repair']['reused_jobs'] == ['a']
    assert before == {str(p.relative_to(prior)): sha(p) for p in prior.rglob('*') if p.is_file()}
    for entry in result['jobs']:
        contract.verify_completed_job(output, entry, identity)


def test_changed_completed_result_is_rejected_before_collecting_fields(recovery):
    prior, output, identity, collect, calls = recovery
    write(prior / 'jobs/a/attempt-1/result.json', {'tampered': True})
    with pytest.raises(ValueError, match='artifact changed'):
        repair_prius(prior, output, ['a', 'b'], {'a': {'case': 'a'}, 'b': {'case': 'b'}}, identity, contract, collect)
    assert not calls and not output.exists()


def test_repaired_case_cannot_change_candidate_identity(recovery):
    prior, output, identity, _, calls = recovery

    def collect(name, path):
        calls.append(name)
        changed = copy.deepcopy(identity)
        changed['binary_sha256'] = 'c'*64
        registration(path, [name], [name], changed)
    with pytest.raises(ValueError, match='identity changed'):
        repair_prius(prior, output, ['a', 'b'], {'a': {'case': 'a'}, 'b': {'case': 'b'}}, identity, contract, collect)
    assert read(output / 'registration.json')['status'] == 'FAILED'
    assert [j['job'] for j in read(output / 'registration.json')['jobs']] == ['a']
    assert (output / 'jobs/a/attempt-1/result.json').exists()
    assert (output / 'repair-attempts/b/registration.json').exists()
