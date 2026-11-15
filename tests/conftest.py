"""Keep each test process's default workspace out of the user's real data."""
import pytest


@pytest.fixture(autouse=True)
def isolated_user_data(monkeypatch, tmp_path):
    # tmp_path is unique per test and per xdist worker, including inherited
    # environments in spawned launcher/solver processes. Tests may override it.
    monkeypatch.setenv('COILEM_USER_DATA_ROOT', str(tmp_path / 'user-data'))
    # Python-client solves set their own cache folder for the process; this
    # resets it to "unset" (empty) for every test.
    monkeypatch.setenv('COILEM_SOLVE_CACHE_ROOT', '')
