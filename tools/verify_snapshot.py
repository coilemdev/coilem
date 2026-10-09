"""Verify publication contents; numerical and maintainer signoff are separate."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub fine-grained token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "service API key": re.compile(r"\b(?:sk-proj-|sk_live_|AIza)[A-Za-z0-9_-]{24,}\b"),
}
PERSONAL_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@(?:gmail|hotmail|outlook|yahoo|protonmail|icloud)\.com\b", re.IGNORECASE)
ABSOLUTE_USER_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+\\", re.IGNORECASE),
    re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/", re.IGNORECASE),
)
FORBIDDEN_PARTS = {
    "cloud",
    "femm_solver",
    "migrations",
    "alembic",
    "infra",
    "reports",
    "admin",
    "billing",
    "telemetry",
    "plans",
    "stories",
}
FORBIDDEN_SUFFIXES = {".ans", ".fem", ".log", ".pem", ".key"}
ALLOWED_DATA_FILES = {
    "materials/electrical-steel/M350-50A.csv",
    "frontend/public/materials/sample-custom-steel.csv",
}
# Single-digit sector/surface symbols (S1-S9) are engineering data. Story IDs
# have multiple digits or a task suffix; explicit sprint/path references also fail.
INTERNAL_PLANNING_REFERENCE = re.compile(
    r"(?:(?-i:(?<![A-Za-z0-9/+])(?:S\d{2,3}(?:-[A-Za-z0-9]+)*|S\d-(?!S\d\b)[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*|DW-\d+)\b(?![+/]))"
    r"|prior\s+internal\s+development|\bSprints?[- ]?\d+|\bstories/|(?:^[\"'`\s(]*|[\"'`\s(])qa/[A-Za-z0-9_./-]+)",
    re.IGNORECASE,
)
FORBIDDEN_RUST_RUNTIME_MARKERS = {
    "MeshSource::Femm",
    '"femm_import"',
    "pub debug: Option<DebugConfig>",
    "struct DebugConfig",
}
ALLOWED_BINARY_SIGNATURES = {
    "docs/images/coilem-landing-page.png": b"\x89PNG\r\n\x1a\n",
    "docs/images/magneto2d-follow-flux-fields.png": b"\x89PNG\r\n\x1a\n",
    "docs/images/magneto2d-p1-element.png": b"\x89PNG\r\n\x1a\n",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def text_hygiene_failures(relative: str, text: str) -> list[str]:
    """Return locations/categories only: never print a detected credential."""
    failures = [f"{label} pattern: {relative}" for label, pattern in SECRET_PATTERNS.items() if pattern.search(text)]
    if any(pattern.search(text) for pattern in ABSOLUTE_USER_PATH_PATTERNS):
        failures.append(f"absolute user path: {relative}")
    if re.search(r"OPEN(?:_?EM)_", text):
        failures.append(f"legacy environment prefix: {relative}")
    if INTERNAL_PLANNING_REFERENCE.search(text):
        failures.append(f"internal planning reference: {relative}")
    # Legal attribution must survive cleanup; this exception is deliberately
    # limited to the two reviewed licensing documents.
    if relative not in {"LICENSE", "THIRD_PARTY_NOTICES.md"} and PERSONAL_EMAIL.search(text):
        failures.append(f"personal contact address: {relative}")
    return failures


def png_hygiene_failures(relative: str, path: Path) -> list[str]:
    from PIL import Image

    try:
        with Image.open(path) as picture:
            metadata = dict(picture.info)
            picture.verify()
    except Exception:
        return [f"invalid publication PNG: {relative}"]
    failures = []
    for key, value in metadata.items():
        if key.lower() not in {"software", "dpi", "gamma", "srgb", "chromaticity", "transparency", "aspect"}:
            failures.append(f"unreviewed image identity metadata: {relative}")
        if isinstance(value, (str, bytes)):
            decoded = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
            failures.extend(text_hygiene_failures(relative, decoded))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publication", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "snapshot-manifest.json").read_text(encoding="utf-8"))

    expected = {entry["path"]: entry for entry in manifest["files"]}
    actual = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
        and ".git" not in path.relative_to(root).parts
        and not any(
            (
                part
                in {
                    "node_modules",
                    "target",
                    "dist-public-boundary",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    ".venv",
                    "test-results",
                    "playwright-report",
                }
                or part.startswith(".venv-")
            )
            for part in path.relative_to(root).parts
        )
        and not any(part.endswith(".egg-info") for part in path.relative_to(root).parts)
        and path.name != "snapshot-manifest.json"
    }
    failures = []
    if set(actual) != set(expected):
        failures.append(f"manifest mismatch: missing={sorted(set(expected) - set(actual))}, unexpected={sorted(set(actual) - set(expected))}")
    for relative, entry in expected.items():
        path = actual.get(relative)
        if path is not None and sha256(path) != entry["sha256"]:
            failures.append(f"hash mismatch: {relative}")

    for relative, path in actual.items():
        parts = {part.lower() for part in Path(relative).parts}
        forbidden = sorted(parts & FORBIDDEN_PARTS)
        if forbidden:
            failures.append(f"forbidden path component {forbidden}: {relative}")
        if any(part.startswith("sprint") for part in parts):
            failures.append(f"forbidden sprint path: {relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            failures.append(f"forbidden file type: {relative}")
        if path.suffix.lower() == ".csv" and relative not in ALLOWED_DATA_FILES:
            failures.append(f"unreviewed material or fixture CSV: {relative}")
        allowed_signature = ALLOWED_BINARY_SIGNATURES.get(relative)
        if allowed_signature is not None:
            if not path.read_bytes().startswith(allowed_signature):
                failures.append(f"invalid allowlisted binary signature: {relative}")
            failures.extend(png_hygiene_failures(relative, path))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"unexpected binary file: {relative}")
            continue
        failures.extend(text_hygiene_failures(relative, text))
        if relative.startswith("backend/") and path.suffix == ".py":
            try:
                tree = ast.parse(text, filename=relative)
            except SyntaxError as exc:
                failures.append(f"Python syntax error in {relative}: {exc}")
            else:
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        if node.module.startswith(("backend.femm", "backend.cloud")):
                            failures.append(f"private backend import in {relative}: {node.module}")
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith(("backend.femm", "backend.cloud")):
                                failures.append(
                                    f"private backend import in {relative}: {alias.name}"
                                )
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if "femm" in node.name.lower():
                            failures.append(
                                f"private compatibility definition in {relative}: {node.name}"
                            )
                    elif isinstance(node, ast.Attribute) and node.attr == "debug":
                        failures.append(f"private debug model access in {relative}:{node.lineno}")
        if relative.startswith("solvers/magneto2d/src/") and path.suffix == ".rs":
            for marker in FORBIDDEN_RUST_RUNTIME_MARKERS:
                if marker in text:
                    failures.append(f"private Rust runtime marker {marker!r}: {relative}")

    for excluded in [
        "backend/cloud",
        "backend/femm_solver",
        "backend/models/diagnostics.py",
        "frontend/src/App.tsx",
        "frontend/src/main.tsx",
    ]:
        if (root / excluded).exists():
            failures.append(f"excluded path exists: {excluded}")

    cargo = (root / "solvers" / "magneto2d" / "Cargo.toml").read_text(encoding="utf-8")
    direct = {match.group(1) for match in re.finditer(r"^(serde|serde_json|rayon|faer)\s*=", cargo, re.MULTILINE)}
    if direct != {"serde", "serde_json", "rayon", "faer"}:
        failures.append(f"unexpected Rust direct dependency set: {sorted(direct)}")
    package = json.loads((root / "frontend" / "package.json").read_text(encoding="utf-8"))
    expected_frontend_runtime = {
        "react": "18.3.1",
        "react-dom": "18.3.1",
        "three": "0.183.2",
    }
    if package.get("dependencies") != expected_frontend_runtime:
        failures.append(f"unexpected frontend runtime dependencies: {package.get('dependencies')}")
    expected_frontend_dev = {
        "@playwright/test": "1.60.0",
        "@types/react": "18.3.28",
        "@types/react-dom": "18.3.7",
        "@types/three": "0.183.1",
        "@vitejs/plugin-react": "4.7.0",
        "typescript": "5.6.3",
        "vite": "6.4.3",
    }
    if package.get("devDependencies") != expected_frontend_dev:
        failures.append(f"unexpected frontend development dependencies: {package.get('devDependencies')}")
    requirements = (root / "requirements.lock").read_text(encoding="utf-8")
    required_runtime_pins = {
        "fastapi==0.139.2",
        "gmsh==4.15.2",
        "charset-normalizer==3.4.9",
        "jsonschema-specifications==2025.9.1",
        "markdown-it-py==4.2.0",
        "mdurl==0.1.2",
        "meshio==5.3.5",
        "numpy==2.4.6",
        "pillow==12.3.0",
        "pydantic==2.13.4",
        "pygments==2.20.0",
        "rich==15.0.0",
        "uvicorn==0.51.0",
    }
    missing_pins = sorted(pin for pin in required_runtime_pins if pin not in requirements)
    if missing_pins:
        failures.append(f"Python runtime lock is missing audited pins: {missing_pins}")
    notices = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    required_notices = {
        "AMD, Copyright (c), 1996-2022",
        "COLAMD, Copyright 1998-2022",
        "COPYING.EIGEN.MPL2",
        "COPYING.LAPACK.BSD",
        "End of exception.",
        "Gmsh 4.15.2",
        "| meshio | 5.3.5 | MIT |",
        "| rich | 15.0.0 | MIT |",
        "Elmer FEM 26.2 (optional external program)",
        "ElmerSolver main library",
        "ElmerGrid, ElmerGUI, and most physical solver modules as GPL",
        "React 18.3.1",
        "three.js carries this notice:",
        "Copyright © 2010-2026 three.js authors",
        "Copyright (c) Facebook, Inc. and its affiliates.",
        "Copyright (c) 2015 Andres Suarez",
        "Copyright (c) 2014-2018 Simon Lydell",
        "Modelica Standard Library M350-50A material model",
        "Pillow's wheel is distributed under its MIT-CMU license",
        "Copyright (c) 1998-2025, Modelica Association and contributors",
    }
    missing_notices = sorted(term for term in required_notices if term not in notices)
    if missing_notices:
        failures.append(f"third-party notices are incomplete: {missing_notices}")

    if failures:
        print("TECHNICAL SNAPSHOT GATE FAILED", file=sys.stderr)
        print("\n".join(f"- {failure}" for failure in failures), file=sys.stderr)
        return 1
    print(f"technical snapshot gate passed ({len(actual)} manifest files)")

    if args.publication:
        blockers = []
        license_path = root / "LICENSE"
        if not license_path.is_file():
            blockers.append("root LICENSE is missing")
        else:
            license_text = license_path.read_text(encoding="utf-8")
            if "GNU AFFERO GENERAL PUBLIC LICENSE" not in license_text or "Version 3" not in license_text:
                blockers.append("root LICENSE is not the approved GNU AGPL version 3 text")
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        if not re.search(r'^license\s*=\s*"AGPL-3\.0-or-later"$', pyproject, re.MULTILINE):
            blockers.append("Python metadata is not AGPL-3.0-or-later")
        if not re.search(r'^license\s*=\s*"AGPL-3\.0-or-later"$', cargo, re.MULTILINE):
            blockers.append("Magneto2D metadata is not AGPL-3.0-or-later")
        frontend_package = json.loads((root / "frontend" / "package.json").read_text(encoding="utf-8"))
        if frontend_package.get("license") != "AGPL-3.0-or-later":
            blockers.append("frontend metadata is not AGPL-3.0-or-later")
        if not (root / "TRADEMARKS.md").is_file():
            blockers.append("separate coilEM trademark reservation is missing")
        readme = (root / "README.md").read_text(encoding="utf-8")
        readme_screenshot = "docs/images/coilem-landing-page.png"
        if readme_screenshot not in readme or not (root / readme_screenshot).is_file():
            blockers.append("README landing-page screenshot is missing")
        if not (root / "requirements.lock").is_file() or not (root / "THIRD_PARTY_NOTICES.md").is_file():
            blockers.append("audited dependency lock or third-party notices are not present")
        material_source = (root / "solvers" / "magneto2d" / "src" / "materials.rs").read_text(encoding="utf-8")
        solve_source = (root / "solvers" / "magneto2d" / "src" / "solve" / "mod.rs").read_text(encoding="utf-8")
        if not (root / "MATERIALS.md").is_file():
            blockers.append("material assumptions and sources are not documented")
        material_files = {
            path.relative_to(root).as_posix()
            for path in (root / "materials").rglob("*")
            if path.is_file()
        }
        if material_files != {path for path in ALLOWED_DATA_FILES if path.startswith("materials/")}:
            blockers.append(f"unexpected public material data set: {sorted(material_files)}")
        if any(term in material_source for term in ["DEFAULT_STEINMETZ_KH", "steel_loss_coefficients"]):
            blockers.append("unsourced grade-specific core-loss coefficients remain")
        if "compute_stator_core_loss(" in solve_source:
            blockers.append("public solve still computes grade-specific core loss")
        shared_solver_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                root / "backend" / "solver" / "__init__.py",
                root / "backend" / "solver" / "_helpers.py",
            ]
        )
        if re.search(r"(?:from|import)\s+backend\.femm", shared_solver_source):
            blockers.append("shared solver source still contains lazy private FEMM compatibility imports")
        public_frontend_files = {
            "index.html",
            "main.tsx",
            "App.tsx",
            "PublicLanding.tsx",
            "api.ts",
            "styles.css",
        }
        public_frontend = root / "frontend" / "src" / "public"
        missing_frontend = sorted(
            name for name in public_frontend_files if not (public_frontend / name).is_file()
        )
        if missing_frontend:
            blockers.append(f"composed visual public frontend is incomplete: {missing_frontend}")
        landing_assets = {
            "Landing3DPreview.tsx",
            "hero_field_8p12s.compact.json",
            "hero_mesh_8p12s.compact.json",
            "hero_motor_8p12s_200mm.json",
            "hero_report_8p12s.compact.json",
        }
        landing_root = root / "frontend" / "src" / "components" / "landing-3d"
        missing_landing_assets = sorted(
            name for name in landing_assets if not (landing_root / name).is_file()
        )
        if missing_landing_assets:
            blockers.append(f"coilEM landing visualization is incomplete: {missing_landing_assets}")
        if blockers:
            print("PUBLICATION GATE BLOCKED", file=sys.stderr)
            print("\n".join(f"- {blocker}" for blocker in blockers), file=sys.stderr)
            return 2
        print("publication content gate passed; numerical, browser and maintainer signoff remain separate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
