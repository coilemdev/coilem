"""The persistent per-angle Gmsh mesh cache returns the mesh Gmsh would build."""

from __future__ import annotations

import gzip
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

import backend.solver as solver
from backend.mesh_evidence import build_solve_mesh_evidence
from backend.models import MotorConfig, SolveOptionsConfig
from backend.solver import _mesh_disk_cache as disk_cache

pytestmark = pytest.mark.pr

FIXTURE = Path(__file__).parent / "fixtures/spm_4p12s_simple.json"


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path / "user-data"))
    solver.clear_per_angle_gmsh_mesh_cache()
    yield
    solver.clear_per_angle_gmsh_mesh_cache()


def _config(**solve_param_changes) -> MotorConfig:
    config = MotorConfig.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    config.solve_params.mesh_density = "coarse"
    # Loaded sweep only: the no-load grid would add 80 more meshes per run.
    config.solve_options = SolveOptionsConfig(back_emf=False, thd_analysis=False, cogging_torque=False)
    for name, value in solve_param_changes.items():
        setattr(config.solve_params, name, value)
    return config


def _exact_text(value) -> str:
    """JSON text that keeps key order, int/float types and the sign of zero."""
    return json.dumps(value, separators=(",", ":"))


def _key(scope: str = "scope", angle_key: int = 0, angle: float = 0.0) -> dict:
    key = disk_cache.mesh_cache_entry_key(scope, angle_key, angle)
    assert key is not None
    return key


def _entries() -> list[Path]:
    root = disk_cache.mesh_cache_root()
    return sorted(root.glob("*.json.gz")) if root.is_dir() else []


# ── Entry key ───────────────────────────────────────────────────────────


def test_entry_key_covers_scope_angle_gmsh_producer_and_runtime(monkeypatch):
    gmsh = pytest.importorskip("gmsh")
    base = _key("scope", 7, 1.5)
    assert base["gmsh_version"] == gmsh.__version__
    assert base["producer_version"] == disk_cache.GMSH_MESH_PRODUCER_VERSION
    assert base["mesh_profile_sha256"]
    assert {"python", "platform", "machine"} <= set(base["runtime"])
    variants = [
        _key("other scope", 7, 1.5),
        _key("scope", 8, 1.5),
        _key("scope", 7, 1.25),
    ]
    for name, value in (
        ("_gmsh_version", lambda: "4.0.0"),
        ("GMSH_MESH_PRODUCER_VERSION", disk_cache.GMSH_MESH_PRODUCER_VERSION + 1),
        ("_mesh_profile_sha256", lambda: "0" * 64),
    ):
        with monkeypatch.context() as patched:
            patched.setattr(disk_cache, name, value)
            variants.append(_key("scope", 7, 1.5))
    root = disk_cache.mesh_cache_root()
    paths = {disk_cache._entry_path(root, key) for key in [base, *variants]}
    assert len(paths) == len(variants) + 1


def test_gmsh_or_producer_version_change_misses(monkeypatch):
    pytest.importorskip("gmsh")
    key = _key()
    assert disk_cache.store_mesh_cache_entry(key, {"mesh": {"nodes": [[1.0, 2.0]]}})
    for name, value in (
        ("_gmsh_version", lambda: "4.0.0"),
        ("GMSH_MESH_PRODUCER_VERSION", disk_cache.GMSH_MESH_PRODUCER_VERSION + 1),
    ):
        with monkeypatch.context() as patched:
            patched.setattr(disk_cache, name, value)
            assert disk_cache.load_mesh_cache_entry(_key()) is None
    assert disk_cache.load_mesh_cache_entry(key) == {"mesh": {"nodes": [[1.0, 2.0]]}}


def test_no_entry_key_without_gmsh(monkeypatch):
    monkeypatch.setattr(disk_cache, "_gmsh_version", lambda: None)
    assert disk_cache.mesh_cache_entry_key("scope", 0, 0.0) is None
    assert not solver._angle_mesh_cache_put("scope", {"angle_key": 0, "rotor_angle_mech_deg": 0.0}, {"a": 1})
    assert _entries() == []


def test_scope_key_covers_geometry_the_signature_does_not_list():
    config = _config()
    changed = config.model_copy(deep=True)
    changed.rotor.holem50_w0_mm = 1.0 if changed.rotor.holem50_w0_mm != 1.0 else 2.0
    assert solver._angle_mesh_cache_scope_key(config) != solver._angle_mesh_cache_scope_key(changed)
    # Operating-point settings stay out of the scope, so they reuse meshes.
    electrical = _config(current_amplitude_A=17.0, current_angle_deg=35.0, rated_speed_rpm=1200)
    assert solver._angle_mesh_cache_scope_key(config) == solver._angle_mesh_cache_scope_key(electrical)


# ── Round trip ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("rotor_angle_mech_deg", [0.0, 7.5, -22.5])
def test_disk_round_trip_equals_a_fresh_gmsh_build(rotor_angle_mech_deg):
    pytest.importorskip("gmsh")
    config = _config()
    first, _ = solver._GmshMeshProducer.build(config, rotor_angle_mech_deg)
    key = _key("scope", 1, rotor_angle_mech_deg)
    assert disk_cache.store_mesh_cache_entry(key, first)
    cached = disk_cache.load_mesh_cache_entry(key)
    fresh, _ = solver._GmshMeshProducer.build(config, rotor_angle_mech_deg)
    # The artifact holds no timing fields, so nothing is excluded.
    assert _exact_text(cached) == _exact_text(fresh)
    # A cache hit is re-baked for the run's operating point; at the same
    # operating point that must reproduce the fresh artifact and its evidence.
    rebaked = solver._rebake_gmsh_artifact_for_config(cached, config)
    assert _exact_text(rebaked) == _exact_text(fresh)
    assert build_solve_mesh_evidence(rebaked) == build_solve_mesh_evidence(fresh)


def test_rebaked_hit_equals_a_fresh_build_at_another_operating_point():
    pytest.importorskip("gmsh")
    built_at = _config(current_amplitude_A=10.0, current_angle_deg=0.0)
    run_at = _config(current_amplitude_A=23.0, current_angle_deg=40.0)
    key = _key("scope", 2, 15.0)
    artifact, _ = solver._GmshMeshProducer.build(built_at, 15.0)
    assert disk_cache.store_mesh_cache_entry(key, artifact)
    rebaked = solver._rebake_gmsh_artifact_for_config(disk_cache.load_mesh_cache_entry(key), run_at)
    fresh, _ = solver._GmshMeshProducer.build(run_at, 15.0)
    assert _exact_text(rebaked) == _exact_text(fresh)


# ── Corruption, eviction, atomic writes ─────────────────────────────────


@pytest.mark.parametrize(
    "damage",
    ["garbage", "truncated", "not_json", "wrong_key", "no_artifact", "directory"],
)
def test_corrupt_entry_is_a_miss_and_is_deleted(damage):
    pytest.importorskip("gmsh")
    key = _key()
    assert disk_cache.store_mesh_cache_entry(key, {"mesh": {"nodes": [[0.0, 1.0]]}})
    (path,) = _entries()
    if damage == "garbage":
        path.write_bytes(b"\x00not gzip at all")
    elif damage == "truncated":
        path.write_bytes(path.read_bytes()[:20])
    elif damage == "not_json":
        path.write_bytes(gzip.compress(b"{not json"))
    elif damage == "wrong_key":
        path.write_bytes(gzip.compress(json.dumps({"key": _key("x"), "artifact": {}}).encode()))
    elif damage == "no_artifact":
        path.write_bytes(gzip.compress(json.dumps({"key": key}).encode()))
    else:
        path.unlink()
        path.mkdir()
        (path / "inside").write_text("x")
    assert disk_cache.load_mesh_cache_entry(key) is None
    if damage != "directory":
        assert not path.exists()
    # The angle is meshed again and stored over the bad entry.
    if damage == "directory":
        (path / "inside").unlink()
        path.rmdir()
    assert disk_cache.store_mesh_cache_entry(key, {"mesh": {"nodes": [[0.0, 1.0]]}})
    assert disk_cache.load_mesh_cache_entry(key) == {"mesh": {"nodes": [[0.0, 1.0]]}}


def test_eviction_keeps_the_budget_and_drops_least_recently_used(monkeypatch):
    pytest.importorskip("gmsh")
    keys = [_key("scope", index, float(index)) for index in range(6)]
    for index, key in enumerate(keys):
        assert disk_cache.store_mesh_cache_entry(key, {"values": list(range(200)), "index": index})
        os.utime(disk_cache._entry_path(disk_cache.mesh_cache_root(), key), (1000.0 + index, 1000.0 + index))
    sizes = [disk_cache._entry_path(disk_cache.mesh_cache_root(), key).stat().st_size for key in keys]
    # A hit makes the oldest entry the most recently used.
    assert disk_cache.load_mesh_cache_entry(keys[0])["index"] == 0
    budget = sum(sizes[-3:])
    monkeypatch.setattr(disk_cache, "DEFAULT_MESH_CACHE_MAX_BYTES", budget)
    disk_cache.prune_mesh_cache()
    remaining = [index for index, key in enumerate(keys) if disk_cache.load_mesh_cache_entry(key) is not None]
    assert sum(path.stat().st_size for path in _entries()) <= budget
    assert remaining == [0, 4, 5]


def test_prune_removes_stale_temporary_files_only(tmp_path):
    root = disk_cache.mesh_cache_root()
    root.mkdir(parents=True)
    stale = root / ".abc.json.gz.0123.tmp"
    live = root / ".def.json.gz.4567.tmp"
    stale.write_bytes(b"partial")
    live.write_bytes(b"partial")
    os.utime(stale, (1000.0, 1000.0))
    disk_cache.prune_mesh_cache()
    assert not stale.exists()
    assert live.exists()


def test_failed_write_leaves_no_partial_file_and_keeps_the_old_entry(monkeypatch):
    pytest.importorskip("gmsh")
    key = _key()
    assert disk_cache.store_mesh_cache_entry(key, {"version": 1})

    def failing_replace(source, target):
        raise OSError("disk full")

    with monkeypatch.context() as patched:
        patched.setattr(disk_cache.os, "replace", failing_replace)
        assert not disk_cache.store_mesh_cache_entry(key, {"version": 2})
    assert sorted(path.name for path in disk_cache.mesh_cache_root().iterdir()) == [
        path.name for path in _entries()
    ]
    assert disk_cache.load_mesh_cache_entry(key) == {"version": 1}


def test_concurrent_writers_and_readers_never_see_a_partial_entry():
    pytest.importorskip("gmsh")
    key = _key()
    artifact = {"mesh": {"nodes": [[float(i), float(-i)] for i in range(5000)]}}
    errors: list[object] = []
    stop = threading.Event()

    def write() -> None:
        while not stop.is_set():
            disk_cache.store_mesh_cache_entry(key, artifact)

    def read() -> None:
        for _ in range(200):
            loaded = disk_cache.load_mesh_cache_entry(key)
            if loaded is not None and loaded != artifact:
                errors.append(loaded)

    writers = [threading.Thread(target=write) for _ in range(3)]
    readers = [threading.Thread(target=read) for _ in range(3)]
    for thread in writers + readers:
        thread.start()
    for thread in readers:
        thread.join()
    stop.set()
    for thread in writers:
        thread.join()
    assert errors == []
    assert disk_cache.load_mesh_cache_entry(key) == artifact


# ── The sweep pipeline ──────────────────────────────────────────────────


class _StopAfterMeshing(RuntimeError):
    pass


class _CountingProducer:
    source = "gmsh"
    display_name = "Gmsh"

    def __init__(self) -> None:
        self.angles: list[float] = []

    def build(self, config, rotor_angle_mech_deg):
        self.angles.append(float(rotor_angle_mech_deg))
        return solver._GmshMeshProducer.build(config, rotor_angle_mech_deg)


@pytest.fixture
def sweep(monkeypatch):
    """Run the per-angle sweep up to its first solve and record every mesh."""
    pytest.importorskip("gmsh")
    pool_angles: list[float] = []

    @contextmanager
    def thread_mesh_pool(workers):
        with ThreadPoolExecutor(workers) as pool:
            submit = pool.submit

            def counting_submit(fn, *args):
                pool_angles.append(float(args[1]))
                return submit(fn, *args)

            pool.submit = counting_submit
            yield pool

    def stop_at_first_solve(*args, **kwargs):
        raise _StopAfterMeshing

    monkeypatch.setattr(solver, "run_magneto2d_report", stop_at_first_solve)
    monkeypatch.setattr(solver, "gmsh_mesh_process_pool", thread_mesh_pool)
    # 0-90° elec is 0-45° mech for 4 poles: four base angles, and three angles
    # one 30° slot pitch later that are derived from them by rotation.
    monkeypatch.setattr(
        solver,
        "estimate_magneto2d_sweep_angle_grid",
        lambda config: [0.0, 15.0, 30.0, 45.0, 60.0, 75.0, 90.0],
    )

    def run(config: MotorConfig, *, pool: bool):
        monkeypatch.setattr(solver, "_gmsh_mesh_process_pool_enabled", lambda: pool)
        monkeypatch.setattr(solver.os, "cpu_count", lambda: 4)
        producer = _CountingProducer()
        pool_angles.clear()
        meshes: list[tuple[float, str, str]] = []
        original = solver.build_solve_mesh_evidence

        def recording_evidence(artifact, **kwargs):
            evidence = original(artifact, **kwargs)
            meshes.append((artifact["rotor_angle_mech_deg"], _exact_text(artifact), _exact_text(evidence)))
            return evidence

        monkeypatch.setattr(solver, "build_solve_mesh_evidence", recording_evidence)
        with pytest.raises(_StopAfterMeshing):
            solver._solve_with_per_angle_producer_meshes(config, producer, solve_cache_dir=None)
        built = sorted(producer.angles + pool_angles)
        return built, sorted(meshes)

    return run


@pytest.mark.parametrize("pool", [False, True], ids=["serial", "mesh-pool"])
def test_sweep_reuses_meshes_per_angle_and_across_restarts(sweep, pool):
    config = _config()
    cold_built, cold_meshes = sweep(config, pool=pool)
    base_angles = sorted(set(cold_built))
    assert base_angles == cold_built == [0.0, 7.5, 15.0, 22.5]
    # Slot-pitch derived angles are re-derived, not cached.
    assert len(_entries()) == len(base_angles)
    assert sorted({angle for angle, _text, _evidence in cold_meshes}) == [
        0.0, 7.5, 15.0, 22.5, 30.0, 37.5, 45.0,
    ]

    # Same backend: the in-memory layer serves every base angle.
    warm_built, warm_meshes = sweep(config, pool=pool)
    assert warm_built == []
    assert warm_meshes == cold_meshes

    # After a restart only the disk layer is left; it serves every angle.
    solver.clear_per_angle_gmsh_mesh_cache()
    restart_built, restart_meshes = sweep(config, pool=pool)
    assert restart_built == []
    assert restart_meshes == cold_meshes

    # Partial overlap: only the angles whose entries are gone are meshed.
    solver.clear_per_angle_gmsh_mesh_cache()
    scope = solver._angle_mesh_cache_scope_key(config)
    removed = base_angles[::2]
    for path in _entries():
        payload = json.loads(gzip.decompress(path.read_bytes()))
        assert payload["key"]["scope"] == scope
        if payload["key"]["rotor_angle_mech_deg"] in removed:
            path.unlink()
    partial_built, partial_meshes = sweep(config, pool=pool)
    assert partial_built == removed
    assert partial_meshes == cold_meshes
    assert len(_entries()) == len(base_angles)


def test_sweep_after_an_electrical_change_skips_gmsh_and_matches_a_cold_run(sweep):
    sweep(_config(), pool=False)
    changed = _config(current_amplitude_A=23.0, current_angle_deg=40.0)
    solver.clear_per_angle_gmsh_mesh_cache()
    warm_built, warm_meshes = sweep(changed, pool=False)
    assert warm_built == []
    disk_cache.clear_mesh_cache()
    solver.clear_per_angle_gmsh_mesh_cache()
    cold_built, cold_meshes = sweep(changed, pool=False)
    assert cold_built
    assert warm_meshes == cold_meshes


def test_sweep_after_a_tooth_shoe_change_meshes_again(sweep):
    built, _ = sweep(_config(), pool=False)
    shoe = _config()
    shoe.stator.tooth_shoe_enabled = True
    shoe.stator.tooth_shoe_overhang_mm = 1.0
    shoe = MotorConfig.model_validate(shoe.model_dump(mode="json"))
    shoe_built, _ = sweep(shoe, pool=False)
    assert shoe_built == built
    assert len(_entries()) == 2 * len(built)
