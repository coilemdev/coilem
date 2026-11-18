"""Automatic evidence publication cannot silently widen numerical qualification."""
import copy
from pathlib import Path

import pytest

from backend.benchmark_suite.contract import read, sha, write
from backend.benchmark_suite.record import TOLERANCES, compare_case
from backend.resources import BENCHMARK_SUITE_FILE
from tools import qualification_carry as carry

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'benchmarks/candidate-qualification-20261103/windows/report/benchmark_summary.json'
# The approved v0.5.0 reports measured protocol 1.6.0; these scenarios replay that registered suite.
V050_SUITE = 'benchmarks/abcd-v1.6/benchmark_spec.json'
BENCHMARK_REFERENCE_BUNDLE_DIR = 'benchmarks/reference-baselines/protocol16-reviewed-20261103'


def test_identical_records_are_eligible_for_automatic_acceptance():
    original = read(REPORT)
    moved, rows = carry.compare_summary(original, original, original,
        {**TOLERANCES, **read(ROOT / carry.POLICY)['additional_replay_tolerances']})
    assert not moved and rows
    assert any(row['metric'] == 'lambda_d_Wb' for row in rows)


def test_matching_previous_record_cannot_accumulate_drift_from_approved_baseline():
    approved = {'mean_torque_Nm': 100.}
    previous = {'mean_torque_Nm': 100.4}
    candidate = {'mean_torque_Nm': 100.8}
    changed = carry.differences(candidate, previous, approved, TOLERANCES)
    assert len(changed) == 1 and changed[0]['baseline'] == 'approved'


@pytest.mark.parametrize('value', [float('nan'), float('inf'), None, True])
def test_nonfinite_missing_or_boolean_values_require_review(value):
    assert carry.differences({'mean_torque_Nm': value}, {'mean_torque_Nm': 1}, {'mean_torque_Nm': 1}, TOLERANCES)


def test_changed_gate_cannot_be_accepted_as_unchanged():
    original = read(REPORT)
    changed = copy.deepcopy(original)
    changed['rows'][0]['evaluation']['gates']['mean_torque'] = 'FAIL'
    with pytest.raises(ValueError, match='Changed numerical verdict or gate'):
        carry.compare_summary(changed, original, original, TOLERANCES)


def test_cogging_uses_its_own_metrics_in_records_and_comparisons():
    row = {'phase': 'E', 'status': 'PASS', 'evaluation': {'gates': {'cogging_peak_to_peak': 'PASS'}},
           'measurements': {'native': {'summary': {'cogging': {'peak_to_peak_Nm': 1., 'first_harmonic_Nm': .2}}}}}
    assert carry.observations(row) == {'cogging_peak_to_peak_Nm': 1., 'cogging_first_harmonic_Nm': .2}
    baseline = {'status': 'PASS', 'gates': row['evaluation']['gates'], 'values': carry.observations(row)}
    assert compare_case(row, baseline)['match']
    row['measurements']['native']['summary']['cogging']['peak_to_peak_Nm'] = 1.1
    assert not compare_case(row, baseline)['match']


def test_reference_reuse_preserves_registration_and_rejects_changed_geometry():
    original = read(REPORT)
    before = sha(ROOT / BENCHMARK_REFERENCE_BUNDLE_DIR / 'manifest.json')
    receipt = carry.reference_compatibility(original, original, ROOT / V050_SUITE,
                                            ROOT / BENCHMARK_REFERENCE_BUNDLE_DIR)
    assert not receipt['reference_fields_mutated']
    assert sha(ROOT / BENCHMARK_REFERENCE_BUNDLE_DIR / 'manifest.json') == before
    changed = copy.deepcopy(original)
    changed['run']['identity']['source_files']['backend/geometry_ir.py'] = 'changed'
    with pytest.raises(ValueError, match='interpretation needs review'):
        carry.reference_compatibility(changed, original, ROOT / V050_SUITE, ROOT / BENCHMARK_REFERENCE_BUNDLE_DIR)


def test_protocol_1_6_evidence_cannot_carry_into_the_newton_default_suite():
    # Protocol 1.9.0 changes 28 requests to Newton, so v0.5.6 needs fresh measurements.
    original = read(REPORT)
    with pytest.raises(ValueError, match='same registered suite'):
        carry.reference_compatibility(original, original, ROOT / BENCHMARK_SUITE_FILE,
                                      ROOT / 'benchmarks/reference-baselines/protocol110-combined-20261110')


def test_combined_ag_bundle_records_each_frozen_reference_commit():
    suite = ROOT / 'benchmarks/ag-v1.12/benchmark_spec.json'
    bundle = ROOT / 'benchmarks/reference-baselines/protocol112-combined-20261117'
    report = read(ROOT / 'benchmarks/qualification-9f2ce84ef28d/windows-x86_64/report/benchmark_summary.json')
    receipt = carry.reference_compatibility(report, report, suite, bundle)
    assert receipt['reference_commits'] == report['run']['reference_commits']
    assert len(receipt['reference_commits']) > 1
    assert receipt['reference_sensitive_sources']['backend/iron_loss.py'] == (
        report['run']['identity']['source_files']['backend/iron_loss.py']
    )


@pytest.fixture
def platform_inputs(tmp_path, monkeypatch):
    # These scenarios replay the approved v0.5.0 context, independently of
    # whichever measured candidate the live platform registry now publishes.
    previous_records = {
        (ROOT / f'benchmarks/records/{key}.json').resolve():
        ROOT / f'benchmarks/records-historical/v050/{key}.json'
        for key in ('windows-x86_64', 'macos-arm64')
    }
    original_read = carry.read

    def historical_read(path):
        return original_read(previous_records.get(Path(path).resolve(), path))

    monkeypatch.setattr(carry, 'read', historical_read)
    monkeypatch.setattr(carry, 'POLICY', 'benchmarks/qualification-policy-history/protocol19-20261110.json')
    monkeypatch.setattr(carry, 'BENCHMARK_SUITE_FILE', V050_SUITE)
    monkeypatch.setattr(carry, 'BENCHMARK_REFERENCE_BUNDLE_DIR', BENCHMARK_REFERENCE_BUNDLE_DIR)
    root = tmp_path / 'candidate'
    field = root / 'backend/test_field.py'
    field.parent.mkdir(parents=True)
    field.write_text('measured test field source')
    monkeypatch.setattr(carry, 'physics_sources', lambda _: ['backend/test_field.py'])
    platforms = {}
    for key, name in [('windows-x86_64', 'windows'), ('macos-arm64', 'macos')]:
        folder = tmp_path / key
        report = read(ROOT / f'benchmarks/candidate-qualification-20261103/{name}/report/benchmark_summary.json')
        report['run']['identity']['source_files']['backend/test_field.py'] = sha(field)
        write(folder / 'joined-suite/report/benchmark_summary.json', report)
        prius = read(ROOT / 'benchmarks/candidate-qualification-20261103/prius/app-results.json')
        prius['source_sha256']['backend/test_field.py'] = sha(field)
        write(folder / 'prius-report/app-results.json', prius)
        platforms[key] = folder
    return platforms, root


def test_both_matching_platforms_prepare_new_records_without_rewriting_inputs(platform_inputs, tmp_path):
    platforms, root = platform_inputs
    hashes = {key: sha(folder / 'joined-suite/report/benchmark_summary.json') for key, folder in platforms.items()}
    result = carry.prepare(platforms, baseline=ROOT, root=root, output=tmp_path / 'output')
    assert result['status'] == 'READY'
    for key, folder in platforms.items():
        assert sha(folder / 'joined-suite/report/benchmark_summary.json') == hashes[key]
        record = read(tmp_path / f'output/publication/benchmarks/records/{key}.json')
        assert record['measured_commit'] == result['candidate'] and record['prius_report']


def test_moved_values_emit_table_and_do_not_publish(platform_inputs, tmp_path):
    platforms, root = platform_inputs
    path = platforms['windows-x86_64'] / 'joined-suite/report/benchmark_summary.json'
    changed = read(path)
    changed['rows'][0]['measurements']['native']['summary']['avg_torque_Nm'] *= 1.02
    write(path, changed)
    result = carry.prepare(platforms, baseline=ROOT, root=root, output=tmp_path / 'review')
    assert result['status'] == 'OWNER_REVIEW_REQUIRED' and result['moved_values']
    assert (tmp_path / 'review/comparison.csv').is_file() and not (tmp_path / 'review/publication').exists()


def test_changed_reference_requires_review_even_when_numbers_match_and_moves_are_accepted(platform_inputs, tmp_path):
    platforms, root = platform_inputs
    path = platforms['windows-x86_64'] / 'joined-suite/report/benchmark_summary.json'
    changed = read(path)
    changed['run']['identity']['source_files']['backend/geometry_ir.py'] = 'changed reference model'
    write(path, changed)
    output = tmp_path / 'reference-review'
    result = carry.prepare(platforms, baseline=ROOT, root=root, output=output, accept_moved=True)
    assert result['status'] == 'REFERENCE_REVIEW_REQUIRED' and not result['moved_values']
    review = (output / 'REVIEW.md').read_text()
    assert review.startswith('# Reference review required\n')
    assert 'backend/geometry_ir.py' in review and 'cannot override' in review
    assert 'values moved' not in review and not (output / 'publication').exists()


def test_missing_platform_or_mixed_candidates_cannot_publish(platform_inputs, tmp_path):
    platforms, root = platform_inputs
    with pytest.raises(ValueError, match='Both platform'):
        carry.prepare({'windows-x86_64': platforms['windows-x86_64']}, baseline=ROOT, root=root, output=tmp_path / 'missing')
    path = platforms['macos-arm64'] / 'joined-suite/report/benchmark_summary.json'
    changed = read(path)
    changed['run']['identity']['commit'] = '0' * 40
    write(path, changed)
    with pytest.raises(ValueError, match='mixed field'):
        carry.prepare(platforms, baseline=ROOT, root=root, output=tmp_path / 'mixed')


def test_publication_redacts_local_paths_and_records_a_local_collection(platform_inputs, tmp_path):
    platforms, root = platform_inputs
    folder = platforms['macos-arm64']
    path = folder / 'joined-suite/report/benchmark_summary.json'
    report = read(path)
    home = '/Users/' + 'someone/qualification/collect/suite-00/out/jobs/case/native/native-runtime/solve_cache/run'
    report['rows'][0]['measurements']['native'].setdefault('solve_metadata', {})['solve_cache_dir'] = home
    write(path, report)
    html = folder / 'joined-suite/report/coilem_benchmark_report.html'
    html.write_bytes(f'<td>{home}</td>\r\n<td>1.25</td>\r\n'.encode())
    write(folder / 'joined-suite/report/artifact_manifest.json',
          {'benchmark_summary.json': sha(path), 'coilem_benchmark_report.html': sha(html)})
    write(folder / 'local-collection.json', {'schema': 'coilem.local_collection/v1', 'collector': 'local'})
    inputs = {p: sha(p) for p in (path, html)}

    result = carry.prepare(platforms, baseline=ROOT, root=root, output=tmp_path / 'output')

    assert result['status'] == 'READY' and all(sha(p) == digest for p, digest in inputs.items())
    base = tmp_path / f'output/publication/benchmarks/qualification-{result["candidate"][:12]}'
    published = base / 'macos-arm64/report'
    assert not any(carry.contains_local_path(p.read_text(encoding='utf-8')) for p in base.rglob('*') if p.is_file())
    summary = read(published / 'benchmark_summary.json')
    assert summary['rows'][0]['measurements']['native']['solve_metadata']['solve_cache_dir'] == '<local path>'
    assert summary['rows'][0]['measurements']['native']['summary'] == report['rows'][0]['measurements']['native']['summary']
    assert (published / 'coilem_benchmark_report.html').read_bytes() == b'<td><local path></td>\r\n<td>1.25</td>\r\n'
    index = read(published / 'artifact_manifest.json')
    assert index == {name: sha(published / name) for name in index}
    projection = read(base / 'publication-projection.json')
    assert set(projection['platforms']) == {'macos-arm64'} and projection['measured_commit'] == result['candidate']
    entry = projection['platforms']['macos-arm64']
    assert entry['collection']['collector'] == 'local'
    assert {f['file'] for f in entry['files']} == {
        'report/benchmark_summary.json', 'report/coilem_benchmark_report.html', 'report/artifact_manifest.json'}
    assert all(f['original_sha256'] != f['published_sha256'] for f in entry['files'])


def test_hosted_collections_without_local_paths_publish_no_projection(platform_inputs, tmp_path):
    platforms, root = platform_inputs
    result = carry.prepare(platforms, baseline=ROOT, root=root, output=tmp_path / 'output')
    base = tmp_path / f'output/publication/benchmarks/qualification-{result["candidate"][:12]}'
    assert not (base / 'publication-projection.json').exists()


def test_redaction_refuses_to_change_anything_but_paths():
    assert carry._only_paths_differ({'a': ['/Users/' + 'x/y', 1.5]}, {'a': ['<local path>', 1.5]})
    assert not carry._only_paths_differ({'a': 1.5}, {'a': 1.6})
    assert not carry._only_paths_differ({'a': 'PASS'}, {'a': '<local path>'})
    assert not carry._only_paths_differ({'a': 1}, {'a': 1, 'b': 2})
    assert not carry._only_paths_differ([1, 2], [1])
    assert not carry._only_paths_differ(1, True)


def changed_reference_source(platforms):
    for folder in platforms.values():
        path = folder / 'joined-suite/report/benchmark_summary.json'
        changed = read(path)
        changed['run']['identity']['source_files']['backend/geometry_ir.py'] = 'changed reference model'
        write(path, changed)


def test_owner_reviewed_reference_sources_publish_with_the_review_on_record(platform_inputs, tmp_path):
    platforms, root = platform_inputs
    changed_reference_source(platforms)
    blocked = carry.prepare(platforms, baseline=ROOT, root=root, output=tmp_path / 'blocked')
    assert blocked['status'] == 'REFERENCE_REVIEW_REQUIRED' and not blocked['owner_reviewed_reference_sources']
    assert '--reference-reviewed' in (tmp_path / 'blocked/REVIEW.md').read_text()

    output = tmp_path / 'reviewed'
    result = carry.prepare(platforms, baseline=ROOT, root=root, output=output, reference_reviewed=True)
    assert result['status'] == 'READY' and not result['reference_review']
    assert set(result['owner_reviewed_reference_sources']) == {'windows-x86_64', 'macos-arm64'}
    base = output / f'publication/benchmarks/qualification-{result["candidate"][:12]}'
    for key in platforms:
        receipt = read(base / key / 'reference-reuse.json')['owner_reviewed_reference_sources']
        assert list(receipt) == ['backend/geometry_ir.py']
        assert receipt['backend/geometry_ir.py']['candidate_sha256'] == 'changed reference model'
        assert receipt['backend/geometry_ir.py']['approved_sha256'] != 'changed reference model'
        assert read(base / key / 'carry-receipt.json')['owner_reviewed_reference_sources'][key] == receipt
    assert 'backend/geometry_ir.py' in (output / 'REVIEW.md').read_text()


def test_unchanged_reference_sources_record_no_review_even_with_the_flag(platform_inputs, tmp_path):
    platforms, root = platform_inputs
    result = carry.prepare(platforms, baseline=ROOT, root=root, output=tmp_path / 'output', reference_reviewed=True)
    assert result['status'] == 'READY' and result['owner_reviewed_reference_sources'] == {}
    receipt = read(tmp_path / f'output/publication/benchmarks/qualification-{result["candidate"][:12]}/macos-arm64/reference-reuse.json')
    assert 'owner_reviewed_reference_sources' not in receipt


def test_a_reviewed_reference_never_overrides_a_changed_request(platform_inputs, tmp_path):
    platforms, root = platform_inputs
    path = platforms['windows-x86_64'] / 'joined-suite/report/benchmark_summary.json'
    changed = read(path)
    stage = next(iter(changed['rows'][0]['configurations']))
    changed['rows'][0]['configurations'][stage]['solve_params']['mesh_density'] = 'coarse'
    write(path, changed)
    result = carry.prepare(platforms, baseline=ROOT, root=root, output=tmp_path / 'request', reference_reviewed=True)
    assert result['status'] == 'REFERENCE_REVIEW_REQUIRED'
    assert 'input interpretation' in result['reference_review'][0]['reason']
    assert not (tmp_path / 'request/publication').exists()


def test_a_reviewed_reference_still_needs_moved_values_accepted(platform_inputs, tmp_path):
    platforms, root = platform_inputs
    changed_reference_source(platforms)
    path = platforms['windows-x86_64'] / 'joined-suite/report/benchmark_summary.json'
    changed = read(path)
    changed['rows'][0]['measurements']['native']['summary']['avg_torque_Nm'] *= 1.02
    write(path, changed)
    result = carry.prepare(platforms, baseline=ROOT, root=root, output=tmp_path / 'moved', reference_reviewed=True)
    assert result['status'] == 'OWNER_REVIEW_REQUIRED' and result['moved_values']
    assert not (tmp_path / 'moved/publication').exists()
