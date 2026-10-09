"""Candidate-only contracts for the history-free public boundary."""

from __future__ import annotations

import builtins
import importlib
import json
import re
import subprocess
import sys
import textwrap
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
VALID_CONFIG = json.loads(
    (REPO_ROOT / "tests" / "fixtures" / "spm_4p12s_simple.json").read_text(encoding="utf-8")
)


def test_exported_n35_contract_matches_public_catalog():
    from backend.material_catalog import MAGNET_PROPERTIES

    contract = json.loads(
        (REPO_ROOT / "solvers/magneto2d/tests/fixtures/n35_material_contract.json").read_text(encoding="utf-8")
    )
    actual = MAGNET_PROPERTIES[contract["grade"]]
    assert actual["remanence_T"] == contract["remanence_T"]
    assert actual["relative_permeability"] == contract["relative_permeability"]


def test_snapshot_has_no_inherited_commit() -> None:
    manifest = json.loads((REPO_ROOT / "snapshot-manifest.json").read_text(encoding="utf-8"))
    assert manifest["history_transferred"] is False
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"])


def test_material_api_matches_exported_native_magnet_inputs() -> None:
    from backend.public_main import app

    models = TestClient(app, base_url="http://127.0.0.1").get("/materials").json()["models"]
    rust = (REPO_ROOT / "solvers/magneto2d/src/materials.rs").read_text(encoding="utf-8")
    branches = re.findall(r'((?:"[^"]+"\s*(?:\|\s*)?)+)=>\s*\(([0-9.]+),\s*([0-9.]+)\)', rust)
    native = {grade: (float(br), float(mu)) for labels, br, mu in branches for grade in re.findall(r'"([^"]+)"', labels)}
    for grade, model in models.items():
        if model["kind"] == "permanent_magnet":
            properties = model["properties"]
            assert (properties["remanence_T"], properties["relative_permeability"]) == native[grade], grade


def test_public_main_imports_with_private_integrations_blocked(monkeypatch) -> None:
    blocked = ("backend.cloud", "backend.femm")
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith(blocked):
            raise ModuleNotFoundError(f"blocked publication import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    before = set(sys.modules)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    public_main = importlib.import_module("backend.public_main")
    imported = set(sys.modules) - before
    assert not any(name.startswith(blocked) for name in imported)
    assert public_main.app.title == "coilEM Local API"


def test_public_api_is_allowlisted_and_local(monkeypatch) -> None:
    from backend.public_main import PUBLIC_API_PATHS, app

    monkeypatch.delenv("COILEM_ENABLE_ELMER", raising=False)
    client = TestClient(app, base_url="http://127.0.0.1")
    served_paths = set(client.get("/openapi.json").json()["paths"])
    assert served_paths | {"/openapi.json"} == PUBLIC_API_PATHS
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["network_required"] is False
    assert health.json()["solver"] == "magneto2d"
    assert health.json()["capabilities"]["elmer"]["feature_enabled"] is False


def test_optional_elmer_capability_is_sanitized_and_selectable(monkeypatch) -> None:
    from backend import public_main
    from backend.elmer.capabilities import ElmerCapabilities
    from backend.public_routes import solve as solve_routes

    monkeypatch.setenv("COILEM_ENABLE_ELMER", "1")
    capability = ElmerCapabilities(
        available=True,
        qualified=True,
        solver_path="/private/runtime/bin/ElmerSolver",
        grid_path="/private/runtime/bin/ElmerGrid",
        solver_version="26.2",
        grid_version="26.2",
        platform="Darwin",
        architecture="arm64",
        solver_sha256="private-solver-hash",
        grid_sha256="private-grid-hash",
    )
    monkeypatch.setattr(public_main, "discover_elmer", lambda: capability)
    monkeypatch.setattr(solve_routes, "discover_elmer", lambda: capability)
    client = TestClient(public_main.app, base_url="http://127.0.0.1")

    health = client.get("/health").json()["capabilities"]["elmer"]
    assert health["feature_enabled"] is True
    assert health["available"] is True
    assert health["qualified"] is True
    assert health["solver_version"] == "26.2"
    assert "solver_path" not in health
    assert "solver_sha256" not in health

    validation = client.post(
        "/solve/validate",
        json={"config": VALID_CONFIG, "solver": "elmer"},
    )
    assert validation.status_code == 200
    assert validation.json()["solver_lane"]["lane"] == "elmer"


def test_public_policy_rejects_femm_and_thermal() -> None:
    from backend.public_main import app

    client = TestClient(app, base_url="http://127.0.0.1")
    femm = deepcopy(VALID_CONFIG)
    femm["solve_params"]["mesh_source"] = "femm"
    assert client.post("/solve/validate", json=femm).status_code == 400

    thermal = deepcopy(VALID_CONFIG)
    thermal["solve_params"]["magnet_temperature_C"] = 80
    before = set(sys.modules)
    response = client.post("/solve/validate", json=thermal)
    imported = set(sys.modules) - before
    assert response.status_code == 400
    assert not any(name.startswith("backend.thermal") for name in imported)

    cogging = deepcopy(VALID_CONFIG)
    cogging["solve_options"] = {"cogging_torque": True}
    response = client.post("/solve/validate", json=cogging)
    assert response.status_code == 400
    assert response.json()["detail"]["field"] == "solve_options.cogging_torque"


def test_public_policy_accepts_only_the_guided_six_step_contract() -> None:
    from backend.public_main import app

    client = TestClient(app, base_url="http://127.0.0.1")
    six_step = deepcopy(VALID_CONFIG)
    six_step["solve_params"].update(
        {
            "excitation_mode": "ideal_six_step_120",
            "current_amplitude_convention": "plateau",
            "commutation_advance_deg": 0.0,
            "phase_connection": "wye",
        }
    )
    accepted = client.post("/solve/validate", json=six_step)
    assert accepted.status_code == 200
    assert accepted.json()["solver_lane"]["lane"] == "magneto2d"

    delta = deepcopy(six_step)
    delta["solve_params"]["phase_connection"] = "delta"
    rejected = client.post("/solve/validate", json=delta)
    assert rejected.status_code == 400
    assert rejected.json()["detail"]["error_code"] == "UNSUPPORTED_LAUNCH_CONFIG"


def test_launch_solver_import_probe_blocks_private_modules() -> None:
    probe = textwrap.dedent(
        """
        import builtins
        import importlib
        blocked = ("backend.cloud", "backend.femm")
        original_import = builtins.__import__
        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith(blocked):
                raise ModuleNotFoundError(f"blocked publication import: {name}")
            return original_import(name, globals, locals, fromlist, level)
        builtins.__import__ = guarded_import
        module = importlib.import_module("backend.solver")
        assert module.Magneto2DSolver(launch_surface=True)._launch_surface is True
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_release_versions_align() -> None:
    from backend import __version__

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((REPO_ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    assert __version__ == "0.2.0"
    assert 'version = "0.2.0"' in pyproject
    assert package["version"] == "0.2.0"
    assert lock["version"] == "0.2.0"
    design_file = (REPO_ROOT / "frontend" / "src" / "public" / "designFile.ts").read_text(encoding="utf-8")
    assert "COILEM_APP_VERSION = '0.2.0'" in design_file
    magneto2d = (REPO_ROOT / "solvers" / "magneto2d" / "Cargo.toml").read_text(
        encoding="utf-8"
    )
    assert 'version = "0.3.2"' in magneto2d


def test_public_docs_match_reduced_release_contract() -> None:
    from backend.public_main import app

    paths = {
        name: REPO_ROOT / name
        for name in (
            "README.md",
            "RELEASE_NOTES.md",
            "SECURITY.md",
            "SUPPORT.md",
            "PUBLICATION_STATUS.md",
            "docs/ELMER.md",
            "docs/GETTING_STARTED.md",
            "docs/MAGNETO2D.md",
            "docs/PUBLIC_BOUNDARY.md",
            "docs/local_solve_workspace.md",
        )
    }
    assert all(path.is_file() for path in paths.values())
    documents = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}
    combined = "\n".join(documents.values())

    assert "coilEM 0.2.0" in documents["README.md"]
    assert "Magneto2D 0.3.2" in documents["README.md"]
    assert "COILEM_ENABLE_ELMER=1" in documents["docs/ELMER.md"]
    assert "hidden, and not probed" in combined
    assert "H1-H12" in documents["docs/GETTING_STARTED.md"]
    assert "H24" in documents["docs/GETTING_STARTED.md"]
    guide_text = " ".join(documents["docs/GETTING_STARTED.md"].split())
    assert "Preview does not report an under-sampled THD value" in guide_text
    assert "dedicated cogging-torque result view is not part" in documents[
        "docs/GETTING_STARTED.md"
    ]
    assert "Ideal six-step (120°)" in documents["docs/GETTING_STARTED.md"]
    assert "two conducting phases and one floating phase" in documents[
        "docs/GETTING_STARTED.md"
    ]
    assert "without PWM, switching," in documents["README.md"]
    assert "ESC dynamics or thermal behavior" in documents["README.md"]
    assert "https://github.com/coilemdev/coilem/issues" in documents["SUPPORT.md"]
    assert "https://github.com/coilemdev/coilem/security/advisories/new" in documents[
        "SECURITY.md"
    ]
    assert "appears as an enabled solver choice" not in combined
    assert "optional cogging torque" not in combined.lower()

    documented = set(
        re.findall(
            r"`(GET|POST|DELETE|PUT|PATCH) (/[^`]+)`",
            documents["docs/PUBLIC_BOUNDARY.md"],
        )
    )
    openapi = app.openapi()
    served = {
        (method.upper(), path)
        for path, operations in openapi["paths"].items()
        for method in operations
        if method.upper() in {"GET", "POST", "DELETE", "PUT", "PATCH"}
    }
    served.add(("GET", "/openapi.json"))
    assert documented == served


def test_only_rights_cleared_nonlinear_steel_curve_is_bundled() -> None:
    material_root = REPO_ROOT / "materials" / "electrical-steel"
    assert {path.name for path in material_root.glob("*.csv")} == {"M350-50A.csv"}

    curve_path = material_root / "M350-50A.csv"
    source = curve_path.read_text(encoding="utf-8")
    assert "ModelicaStandardLibrary" in source
    assert "BSD-3-Clause" in source
    assert "mu_i=1210" in source

    completed = subprocess.run(
        [sys.executable, "tools/generate_m350_50a_bh.py", "--check"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

    points = []
    for line in source.splitlines():
        if not line or line.startswith("#") or line.startswith("B_T"):
            continue
        b_t, h_a_per_m = (float(value) for value in line.split(","))
        points.append((b_t, h_a_per_m))
    assert len(points) >= 250
    assert points == sorted(points)
    assert points[-1][0] >= 2.5

    mu_0 = 4.0 * 3.141592653589793e-7
    by_b = {round(b_t, 2): (b_t, h) for b_t, h in points}
    mu_at_1_t = by_b[1.0][0] / (mu_0 * by_b[1.0][1])
    mu_at_2_2_t = by_b[2.2][0] / (mu_0 * by_b[2.2][1])
    assert mu_at_1_t > 5_000
    assert mu_at_2_2_t < 10


def test_corner_refinement_profile_is_packaged() -> None:
    profile_path = REPO_ROOT / "backend" / "mesh_profiles" / "gmsh_profiles.json"
    document = json.loads(profile_path.read_text(encoding="utf-8"))
    active_profile = document["active_experimental_profile"]
    assert active_profile == "adaptive_corner_refinement"
    assert active_profile in document["profiles"]
    assert document["profiles"][active_profile]["corner"]["sampling"] > 0


def test_internal_plans_and_stories_are_absent() -> None:
    paths = [path.relative_to(REPO_ROOT) for path in REPO_ROOT.rglob("*")]
    assert not any(
        part.lower() in {"plans", "stories"} or part.lower().startswith("sprint")
        for path in paths
        for part in path.parts
    )

    production_roots = [REPO_ROOT / "backend", REPO_ROOT / "frontend" / "src", REPO_ROOT / "solvers"]
    internal_reference = re.compile(r"(?:\bSprints?[- ]?\d+|\bstories/)", re.IGNORECASE)
    for production_root in production_roots:
        for source in production_root.rglob("*"):
            if source.suffix.lower() in {".py", ".rs", ".ts", ".tsx"}:
                assert internal_reference.search(source.read_text(encoding="utf-8")) is None, source


def test_public_core_loss_coefficients_are_absent() -> None:
    materials = (REPO_ROOT / "solvers" / "magneto2d" / "src" / "materials.rs").read_text(
        encoding="utf-8"
    )
    solve = (REPO_ROOT / "solvers" / "magneto2d" / "src" / "solve" / "mod.rs").read_text(
        encoding="utf-8"
    )
    assert "steel_loss_coefficients" not in materials
    assert "DEFAULT_STEINMETZ" not in materials
    assert "compute_stator_core_loss(" not in solve


def test_audited_dependency_notices_are_present() -> None:
    requirements = (REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")
    notices = (REPO_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for pin in [
        "charset-normalizer==3.4.9",
        "fastapi==0.139.2",
        "gmsh==4.15.2",
        "jsonschema-specifications==2025.9.1",
        "meshio==5.3.5",
        "numpy==2.4.6",
        "pillow==12.3.0",
        "rich==15.0.0",
        "uvicorn==0.51.0",
    ]:
        assert pin in requirements
    for notice in [
        "AMD, Copyright (c), 1996-2022",
        "COLAMD, Copyright 1998-2022",
        "COPYING.EIGEN.MPL2",
        "COPYING.LAPACK.BSD",
        "End of exception.",
        "Modelica Standard Library M350-50A material model",
        "Copyright (c) 1998-2025, Modelica Association and contributors",
        "Pillow's wheel is distributed under its MIT-CMU license",
        "| meshio | 5.3.5 | MIT |",
        "| rich | 15.0.0 | MIT |",
        "Elmer FEM 26.2 (optional external program)",
        "ElmerGrid, ElmerGUI, and most physical solver modules as GPL",
    ]:
        assert notice in notices


def test_custom_steel_import_survives_public_snapshot():
    from backend.magneto2d_adapter import build_magneto2d_payload
    from backend.models import MotorConfig
    from backend.public_main import app
    client = TestClient(app, base_url="http://127.0.0.1")
    csv_text = (REPO_ROOT / 'frontend/public/materials/sample-custom-steel.csv').read_text()
    response = client.post('/materials/import', json={'name': 'Independent demo', 'source': 'Synthetic test data', 'csv_text': csv_text})
    assert response.status_code == 200
    material = response.json()['material']
    config = deepcopy(VALID_CONFIG)
    config['materials'].update(stator_steel=material['id'], rotor_steel=material['id'], custom_steels={material['id']: material})
    assert client.post('/solve/validate', json={'config': config}).json()['valid']
    payload = build_magneto2d_payload(MotorConfig.model_validate(config))
    assert len(payload['materials']['custom_steels'][material['id']]['bh_curve']) == 51
    assert client.get('/materials').json()['steels'] == ['M350-50A']


@pytest.mark.parametrize("route", ["/solve", "/solve/stream"])
def test_public_workspace_limit_delete_and_retry_flow(
    monkeypatch,
    tmp_path: Path,
    route: str,
) -> None:
    from backend.public_main import app
    from backend.public_routes import solve as solve_routes
    from backend.solve_workspace import SolveWorkspace

    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    workspace = SolveWorkspace()
    stale = workspace.begin_run(
        project_name="old-incomplete-run",
        config=VALID_CONFIG,
        submitted_request={"config": VALID_CONFIG},
    )
    stale.fail(error_code="SOLVE_FAILED", message="retained diagnostic")
    (stale.partial_path / "retained-solver.log").write_bytes(b"x" * 1_000_000)
    monkeypatch.setenv("COILEM_SOLVE_WORKSPACE_MAX_BYTES", "1000000")

    class FakeResult:
        @staticmethod
        def model_dump(*, mode):
            assert mode == "json"
            return {
                "summary": {"avg_torque_Nm": 1.0},
                "torque_waveform": {
                    "electrical_angle_deg": [0.0],
                    "torque_Nm": [1.0],
                },
                "back_emf_waveform": {
                    "electrical_angle_deg": [0.0],
                    "phase_a_V": [0.0],
                    "phase_b_V": [0.0],
                    "phase_c_V": [0.0],
                },
                "solve_metadata": {"solver_name": "magneto2d-rust-0.3.2"},
            }

    monkeypatch.setattr(
        solve_routes.Magneto2DSolver,
        "solve",
        lambda self, config, on_progress=None, solve_mesh_key=None: FakeResult(),
    )
    client = TestClient(app, base_url="http://127.0.0.1")

    listed = client.get("/runs").json()
    assert listed["storage"]["accepting_new_runs"] is False
    assert listed["runs"][0]["size_bytes"] >= 1_000_000

    blocked = client.post(route, json=VALID_CONFIG)
    assert blocked.status_code == (507 if route == "/solve" else 200)
    assert '"error_code":"RUN_STORAGE_LIMIT"' in blocked.text
    assert "Open Previous runs" in blocked.text

    deleted = client.request(
        "DELETE",
        f"/runs/{listed['runs'][0]['project_slug']}/{listed['runs'][0]['run_id']}",
        json={"confirm_run_id": listed["runs"][0]["run_id"]},
    )
    assert deleted.status_code == 200
    assert deleted.json()["storage"]["accepting_new_runs"] is True

    retried = client.post(route, json=VALID_CONFIG)
    assert retried.status_code == 200
    if route == "/solve/stream":
        assert "event: complete" in retried.text
    assert '"avg_torque_Nm":1.0' in retried.text


@pytest.mark.parametrize("route", ["/solve", "/solve/stream"])
def test_public_solve_reports_workspace_limit_during_run_publication(
    monkeypatch,
    tmp_path: Path,
    route: str,
) -> None:
    from backend.public_main import app
    from backend.public_routes import solve as solve_routes

    class FakeResult:
        @staticmethod
        def model_dump(*, mode):
            assert mode == "json"
            return {
                "summary": {"avg_torque_Nm": 1.0},
                "solve_metadata": {"solver_name": "magneto2d-rust-0.3.2"},
            }

    monkeypatch.setattr(
        solve_routes.Magneto2DSolver,
        "solve",
        lambda self, config, on_progress=None, solve_mesh_key=None: FakeResult(),
    )
    monkeypatch.setenv("COILEM_USER_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("COILEM_SOLVE_WORKSPACE_MAX_BYTES", "1")

    response = TestClient(app, base_url="http://127.0.0.1").post(route, json=VALID_CONFIG)

    assert response.status_code == (507 if route == "/solve" else 200)
    assert '"error_code":"RUN_STORAGE_LIMIT"' in response.text
    assert "Open Previous runs" in response.text
    assert "event: complete" not in response.text
