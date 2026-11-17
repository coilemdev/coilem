"""A sentinel collection passes the PR gate only when it reproduces the full record."""
import copy
import subprocess
from pathlib import Path

import pytest

from backend.benchmark_suite.contract import read, sha, write
from backend.benchmark_suite.physics import physics_sources
from tools import physics_impact
from tools import qualification_sentinel as sentinel
from tools.release.qualification import PRIUS_EXTRA_PHYSICS

ROOT = Path(__file__).resolve().parents[1]
MACOS, WINDOWS = 'macos-arm64', 'windows-x86_64'
CASE = 'spm_4p12s_simple_noload__tight_airgap'
TORQUE = 'native/torque_waveform/torque_Nm'


def collection(folder, platform):
    """A joined sentinel collection with the committed full record's numbers, as if measured at this tree."""
    record = read(ROOT / f'benchmarks/records/{platform}.json')
    summary = read(ROOT / record['source'] / 'benchmark_summary.json')
    rules = sentinel.definition()
    current = {name: sha(ROOT / name) for name in (*physics_sources(ROOT), *PRIUS_EXTRA_PHYSICS)}
    summary['rows'] = [row for row in summary['rows'] if row['id'] in rules['cases']]
    identity = summary['run']['identity']
    identity['source_files'].update(current)
    write(folder / 'joined-suite/report/benchmark_summary.json', summary)
    prius = read(ROOT / record['prius_report'])
    write(folder / 'sentinel-prius.json', {
        'schema': 'coilem.sentinel_prius/v1', 'source_commit': identity['commit'], 'source_dirty': False,
        'source_sha256': {**prius['source_sha256'], **current}, 'binary_sha256': identity['binary_sha256'],
        'platform': identity['platform'], 'dependencies': prius['dependencies'],
        'jobs': [job for job in prius['jobs'] if job['job'] in rules['prius_jobs']]})
    return folder


def reviewed(data, platform):
    """Record every reference-sensitive source this tree changed as owner-reviewed, so the tests hold on any branch."""
    changed = sentinel.assess(data, platform=platform)['changed_reference_sources']
    return {**data, **({'owner_reviewed_reference_sources': changed} if changed else {})}


@pytest.fixture(scope='module')
def measured(tmp_path_factory):
    folder = tmp_path_factory.mktemp('sentinel')
    return {platform: reviewed(sentinel.evidence(collection(folder / platform, platform), platform), platform)
            for platform in sentinel.PLATFORMS}


def outcome(data, platform):
    return sentinel.assess(data, platform=platform)


def test_the_sentinel_cases_cover_every_code_path_of_the_registered_suite():
    rules = sentinel.definition()
    assert sentinel.uncovered() == []
    assert len(rules['cases']) == 22 and rules['prius_jobs'] == ['loaded-torque-32', 'curve-120-16']
    for platform in sentinel.PLATFORMS:
        cases = read(ROOT / f'benchmarks/records/{platform}.json')['cases']
        assert all(cases[case]['status'] == 'PASS' for case in rules['cases'])


@pytest.mark.parametrize('dropped, lost', [
    ('ipm_vshape_8p12s_pocket_offset_contract', 'IPM v_shape 12 slots 8 poles'),
    ('spm_outer_12p9s_micro__baseline', 'outer SPM 9 slots 12 poles'),
    ('spm_8p48s_chorded_5_6', 'chorded winding'),
    ('spm_8p24s_distributed_femm_validation__cogging', 'mesh: very_fine'),
])
def test_dropping_a_case_leaves_a_named_code_path_uncovered(monkeypatch, dropped, lost):
    rules = sentinel.definition()
    rules['cases'] = [case for case in rules['cases'] if case != dropped]
    monkeypatch.setattr(sentinel, 'definition', lambda root=ROOT: rules)
    assert lost in sentinel.uncovered()
    assert any('no longer cover' in error for error in sentinel.errors())


def test_the_definition_is_bound_to_the_registered_suite(tmp_path):
    for name in (sentinel.DEFINITION, 'backend/resources.py'):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    rules = read(ROOT / sentinel.DEFINITION)
    suite = read(ROOT / rules['suite'])
    suite['cases'] = suite['cases'][:-1]
    write(tmp_path / rules['suite'], suite)
    with pytest.raises(ValueError, match='different suite'):
        sentinel.definition(tmp_path)


def test_the_shard_plan_holds_exactly_the_sentinel_selection():
    from tools.benchmark_shards import plan

    rules, result = sentinel.definition(), sentinel.shard_plan()
    assert result == sentinel.shard_plan() and result['sentinel_sha256'] == sha(ROOT / sentinel.DEFINITION)
    assert [s['id'] for s in result['shards']] == ['suite-00', 'suite-01', 'suite-02', 'suite-03', 'prius-00']
    assert sorted(c for s in result['shards'] if s['kind'] == 'suite' for c in s['cases']) == sorted(rules['cases'])
    assert result['shards'][-1]['cases'] == sorted(rules['prius_jobs']) and result['prius_jobs'] == ['loaded-torque-32', 'curve-120-16']
    # The full collection keeps its twelve shards and its plan.
    full = plan()
    assert len(full['shards']) == 12 and full['plan_sha256'] != result['plan_sha256'] and 'sentinel_sha256' not in full
    with pytest.raises(ValueError, match='unregistered'):
        plan(cases=['no_such_case'])


def test_a_collection_that_reproduces_the_full_record_is_unchanged_on_both_platforms(measured):
    for platform, data in measured.items():
        result = outcome(data, platform)
        assert result['errors'] == [] and result['moved'] == [] and result['reference_review'] == []
        assert result['rule'] == ('exact' if platform == MACOS else 'replay tolerances')
        assert len(data['cases']) == 22 and set(data['prius']['jobs']) == {'loaded-torque-32', 'curve-120-16'}
        # Waveform samples and summary values are compared, never wall times or run metadata.
        values = data['cases'][CASE]['measured']
        assert len(values[TORQUE]) == 48 and 'native/summary/avg_torque_Nm' in values
        assert not any('solve_time_s' in name or 'solve_metadata' in name for name in values)


def test_macos_must_reproduce_every_sample_exactly(measured):
    data = copy.deepcopy(measured[MACOS])
    series = data['cases'][CASE]['measured'][TORQUE]
    peak = max(abs(v) for v in read(ROOT / read(ROOT / 'benchmarks/records/macos-arm64.json')['source']
                                    / 'benchmark_summary.json')['rows'][0]['measurements']['native']['torque_waveform']['torque_Nm'])
    series[7] += 1e-13 * max(peak, 1.0)
    assert outcome(data, MACOS)['moved'] == []
    largest = max(range(48), key=lambda i: abs(series[i]))
    series[largest] *= 1 + 1e-6
    moved = outcome(data, MACOS)['moved']
    assert [(d['case'], d['metric']) for d in moved] == [(CASE, TORQUE)] and moved[0]['deviation'] > moved[0]['limit']
    # The same shift is far inside the replay tolerance, which is why the exact rule exists.
    assert sentinel.TOLERANCES['mean_torque_Nm'][0] > 1e-6


@pytest.mark.parametrize('damage', ['missing series', 'resized series', 'missing value', 'gate', 'verdict'])
def test_a_lost_value_or_changed_verdict_is_a_difference(measured, damage):
    data = copy.deepcopy(measured[MACOS])
    case = data['cases'][CASE]
    if damage == 'missing series':
        del case['measured'][TORQUE]
    elif damage == 'resized series':
        case['measured'][TORQUE].pop()
    elif damage == 'missing value':
        del case['measured']['native/summary/avg_torque_Nm']
    elif damage == 'gate':
        case['gates']['mean_torque'] = 'FAIL'
    else:
        case['status'] = 'YELLOW'
    assert {d['case'] for d in outcome(data, MACOS)['moved']} == {CASE}


def test_windows_uses_the_replay_tolerances_of_the_full_comparison(measured):
    data = copy.deepcopy(measured[WINDOWS])
    case = next(name for name, entry in data['cases'].items() if entry['observations'].get('mean_torque_Nm', 0) > 1)
    data['cases'][case]['observations']['mean_torque_Nm'] *= 1.001
    assert outcome(data, WINDOWS)['moved'] == []
    data['cases'][case]['observations']['mean_torque_Nm'] *= 1.01
    moved = outcome(data, WINDOWS)['moved']
    assert moved and {d['case'] for d in moved} == {case} and {d['metric'] for d in moved} == {'mean_torque_Nm'}


def test_prius_jobs_are_compared_like_the_suite(measured):
    data = copy.deepcopy(measured[MACOS])
    data['prius']['jobs']['loaded-torque-32']['measured']['metrics/mean_torque_Nm'] *= 1 + 1e-6
    assert {d['case'] for d in outcome(data, MACOS)['moved']} == {'Prius loaded-torque-32'}
    data = copy.deepcopy(measured[WINDOWS])
    data['prius']['jobs']['curve-120-16']['metrics']['mean_torque_Nm'] *= 1.02
    assert {d['case'] for d in outcome(data, WINDOWS)['moved']} == {'Prius curve-120-16'}
    data = copy.deepcopy(measured[MACOS])
    del data['prius']['jobs']['curve-120-16']
    assert any('Prius sentinel jobs' in error for error in outcome(data, MACOS)['errors'])


@pytest.mark.parametrize('change, message', [
    (lambda d: d['physics_files'].update({'backend/geometry.py': '0' * 64}), 'current physics sources'),
    (lambda d: d['prius']['physics_files'].update({'backend/geometry.py': '0' * 64}), 'Prius sentinel jobs'),
    (lambda d: d['identity'].update(dirty=True), 'complete, clean, full-grid'),
    (lambda d: d['run'].update(smoke=True), 'complete, clean, full-grid'),
    (lambda d: d['run'].update(reference_mode='NATIVE_ONLY'), 'complete, clean, full-grid'),
    (lambda d: d.update(sentinel_sha256='0' * 64), 'different sentinel definition'),
    (lambda d: d['record'].update(sha256='0' * 64), 'different full record'),
    (lambda d: d['run'].update(spec_sha256='0' * 64), 'different suite or reference bundle'),
    (lambda d: d['identity']['dependencies'].update(gmsh='0.0.0'), 'pinned'),
    (lambda d: d['cases'].pop(CASE), 'exactly the sentinel cases'),
    (lambda d: d['identity'].update(platform='Windows-2022Server-10.0.20348-SP0', machine='AMD64'), 'this platform'),
])
def test_evidence_of_another_tree_definition_or_record_cannot_be_used(measured, change, message):
    data = copy.deepcopy(measured[MACOS])
    change(data)
    assert any(message in error for error in outcome(data, MACOS)['errors'])


def test_changed_reference_sources_and_requests_need_owner_review(measured):
    data = copy.deepcopy(measured[MACOS])
    data['reference_sources']['backend/geometry.py'] = '1' * 64
    result = outcome(data, MACOS)
    assert 'reference-sensitive source changed: backend/geometry.py' in result['reference_review']
    data.setdefault('owner_reviewed_reference_sources', {})['backend/geometry.py'] = result['changed_reference_sources']['backend/geometry.py']
    assert outcome(data, MACOS)['reference_review'] == []
    # A review of one hash does not cover a later change of the same file.
    data['reference_sources']['backend/geometry.py'] = '2' * 64
    assert outcome(data, MACOS)['reference_review']
    # A changed request has no override.
    data = copy.deepcopy(measured[MACOS])
    data['cases'][CASE]['configurations_sha256'] = '0' * 64
    data['prius']['jobs']['curve-120-16']['request_sha256'] = '0' * 64
    review = outcome(data, MACOS)['reference_review']
    assert any(CASE in text for text in review) and any('Prius curve-120-16' in text for text in review)


def test_compare_stages_evidence_only_when_nothing_moved(tmp_path):
    folders = {platform: collection(tmp_path / 'joined' / platform, platform) for platform in sentinel.PLATFORMS}
    decision = sentinel.prepare(folders, output=tmp_path / 'ready', reference_reviewed=True)
    assert decision['status'] == 'UNCHANGED'
    staged = sorted(p.relative_to(tmp_path / 'ready/publication').as_posix()
                    for p in (tmp_path / 'ready/publication').rglob('*') if p.is_file())
    assert staged == ['benchmarks/sentinel/macos-arm64.json', 'benchmarks/sentinel/windows-x86_64.json']
    assert 'match the full record' in (tmp_path / 'ready/REVIEW.md').read_text(encoding='utf-8')
    # One platform can be compared alone; the gate still needs both.
    assert sentinel.prepare({MACOS: folders[MACOS]}, output=tmp_path / 'one', reference_reviewed=True)['status'] == 'UNCHANGED'
    summary_path = folders[MACOS] / 'joined-suite/report/benchmark_summary.json'
    summary = read(summary_path)
    summary['rows'][0]['measurements']['native']['torque_waveform']['torque_Nm'][0] += 1e-3
    write(summary_path, summary)
    decision = sentinel.prepare(folders, output=tmp_path / 'moved', reference_reviewed=True)
    assert decision['status'] == 'MOVED' and not (tmp_path / 'moved/publication').exists()
    assert 'run the full collection' in (tmp_path / 'moved/REVIEW.md').read_text(encoding='utf-8')
    with pytest.raises(ValueError, match='registered platform'):
        sentinel.prepare({}, output=tmp_path / 'none')
    # A full collection has no sentinel Prius file; it goes through tools.qualification_carry.
    (folders[WINDOWS] / 'sentinel-prius.json').unlink()
    with pytest.raises(ValueError, match='Not a joined sentinel collection'):
        sentinel.prepare({WINDOWS: folders[WINDOWS]}, output=tmp_path / 'full')


def test_evidence_never_publishes_a_local_path(tmp_path):
    folder = collection(tmp_path / 'joined', MACOS)
    # Built here so that this file itself holds no home-folder path.
    write(folder / 'local-collection.json', {'collector': 'local', 'note': '/'.join(('', 'Users', 'someone', 'coilem-qualification'))})
    with pytest.raises(ValueError, match='machine-local path'):
        sentinel.evidence(folder, MACOS)


def test_the_gate_needs_valid_evidence_of_both_platforms(measured, tmp_path, monkeypatch):
    monkeypatch.setattr(sentinel, 'EVIDENCE', str(tmp_path / '{platform}.json'))
    assert sentinel.errors() == ['windows-x86_64: no sentinel evidence', 'macos-arm64: no sentinel evidence']
    write(tmp_path / 'macos-arm64.json', measured[MACOS])
    assert sentinel.errors() == ['windows-x86_64: no sentinel evidence']
    write(tmp_path / 'windows-x86_64.json', measured[WINDOWS])
    assert sentinel.errors() == []
    moved = copy.deepcopy(measured[MACOS])
    moved['cases'][CASE]['measured'][TORQUE][0] += 1.0
    write(tmp_path / 'macos-arm64.json', moved)
    assert sentinel.errors() == ['macos-arm64: 1 sentinel values differ from the full record']
    (tmp_path / 'macos-arm64.json').write_text('{}', encoding='utf-8')
    assert sentinel.errors()[0].startswith('sentinel evidence unavailable or invalid')


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], stderr=subprocess.DEVNULL).decode().strip()

    git('init')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.com')
    git('config', 'core.autocrlf', 'false')
    for name, text in ((physics_impact.REGISTRY, 'def physics_sources(root):\n    return ("backend/field.py",)\n'),
                       ('backend/field.py', 'original'), ('snapshot-manifest.json', '{"files": [], "public_patches": []}\n')):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding='utf-8', newline='\n')
    git('add', '.')
    git('commit', '-m', 'baseline')
    return tmp_path, git('rev-parse', 'HEAD')


def test_a_physics_pr_passes_the_gate_on_sentinel_evidence_but_not_without_it(repo, monkeypatch):
    root, base = repo
    (root / 'backend/field.py').write_text('changed', encoding='utf-8')
    monkeypatch.setattr(physics_impact, 'check', lambda _: ['stale record'])
    monkeypatch.setattr(physics_impact, 'sentinel_errors', lambda _: [])
    result = physics_impact.assess(root, base)
    assert result['status'] == 'PASS' and result['evidence_basis'] == 'sentinel' and not result['measurement_required']
    monkeypatch.setattr(physics_impact, 'sentinel_errors', lambda _: ['macos-arm64: no sentinel evidence'])
    result = physics_impact.assess(root, base)
    assert result['status'] == 'qualification evidence required' and result['measurement_required']
    assert result['errors'] == ['stale record'] and result['sentinel_errors'] == ['macos-arm64: no sentinel evidence']
    # A full collection is named as such, and an unchanged tree needs neither.
    monkeypatch.setattr(physics_impact, 'check', lambda _: [])
    assert physics_impact.assess(root, base)['evidence_basis'] == 'full collection'
    (root / 'backend/field.py').write_text('original', encoding='utf-8')
    assert physics_impact.assess(root, base)['evidence_basis'] == ''


def test_the_release_gate_never_reads_sentinel_evidence():
    source = (ROOT / 'tools/release/qualification.py').read_text(encoding='utf-8')
    assert 'sentinel' not in source


def test_publish_verifies_in_place_indexes_the_snapshot_and_rolls_back_a_rejection(repo, measured, monkeypatch):
    root, _ = repo
    publication = root.parent / 'publication'
    write(publication / 'benchmarks/sentinel/macos-arm64.json', measured[MACOS])
    clean = {'errors': [], 'moved': [], 'reference_review': []}
    monkeypatch.setattr(sentinel, 'assess', lambda data, **_: clean)
    assert sentinel.apply(publication, root) == ['benchmarks/sentinel/macos-arm64.json']
    target = root / 'benchmarks/sentinel/macos-arm64.json'
    listed = {entry['path']: entry for entry in read(root / 'snapshot-manifest.json')['files']}
    assert listed['benchmarks/sentinel/macos-arm64.json']['sha256'] == sha(target)
    assert 'snapshot-manifest.json' not in listed and 'backend/field.py' in listed
    before = target.read_bytes()
    write(publication / 'benchmarks/sentinel/macos-arm64.json', {**measured[MACOS], 'candidate': '0' * 40})
    monkeypatch.setattr(sentinel, 'assess', lambda data, **_: {**clean, 'moved': [{'case': CASE}]})
    with pytest.raises(ValueError, match='rejected: values moved'):
        sentinel.apply(publication, root)
    assert target.read_bytes() == before
    write(publication / 'benchmarks/records/macos-arm64.json', {})
    with pytest.raises(ValueError, match='Unexpected sentinel publication path'):
        sentinel.apply(publication, root)
