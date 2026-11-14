"""A resumed diagnostic must not silently mix numerical identities."""
import hashlib
import json

import pytest

from tools.vshape_mesh_study import read_point


@pytest.mark.parametrize('old_identity', ['another-build', None])
def test_study_rejects_incompatible_or_legacy_cached_points(tmp_path, old_identity):
    fixture = tmp_path / 'fixture.json'
    fixture.write_text('{}')
    point = tmp_path / 'point.json'
    point.write_text(json.dumps({'identity_sha256': old_identity,
                                'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}))
    with pytest.raises(ValueError, match='fresh output directory'):
        read_point(point, {'sha256': 'current-build'}, fixture)


def test_study_rejects_a_changed_fixture_and_accepts_a_matching_point(tmp_path):
    fixture = tmp_path / 'fixture.json'
    fixture.write_text('{}')
    point = tmp_path / 'point.json'
    record = {'identity_sha256': 'same-build', 'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}
    point.write_text(json.dumps(record))
    assert read_point(point, {'sha256': 'same-build'}, fixture) == record
    fixture.write_text('{"current": 50}')
    with pytest.raises(ValueError, match='fresh output directory'):
        read_point(point, {'sha256': 'same-build'}, fixture)
