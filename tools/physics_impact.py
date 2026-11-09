"""One PR qualification gate, including current-tree Prius evidence freshness."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path

from tools.release.qualification import PRIUS_EXTRA_PHYSICS, check

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = 'backend/benchmark_suite/physics.py'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def registry(root):
    spec = importlib.util.spec_from_file_location('_qualification_physics', root / REGISTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry_sources(root):
    return set(registry(root).physics_sources(root))


def dependency_pins(root, lock_text):
    """Pinned physics-dependency versions, by the registry at ``root``; empty for a registry without any."""
    module = registry(root)
    if lock_text is None or not getattr(module, 'PHYSICS_DEPENDENCIES', ()):
        return {}
    return module.pinned_dependencies(lock_text)


def changed_physics(root, base):
    # Evaluate each side's own registry. Removing a guarded file from the new
    # registry cannot make a real change disappear from the impact check.
    base_names = git(root, 'ls-tree', '-r', '--name-only', base).decode().splitlines()
    with tempfile.TemporaryDirectory() as temporary:
        before = Path(temporary)
        for name in [REGISTRY, *[n for n in base_names if n.startswith('solvers/magneto2d/src/') and n.endswith('.rs')]]:
            target = before / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(git(root, 'show', f'{base}:{name}'))
        guarded = registry_sources(before) | registry_sources(root) | set(PRIUS_EXTRA_PHYSICS) | {REGISTRY}
        # A Gmsh or meshio bump changes meshes without touching a guarded file.
        # Each side's pins are read by the head registry, so a bump still counts
        # in the PR that first names the dependencies.
        lock = getattr(registry(root), 'DEPENDENCY_LOCK_FILE', 'requirements.lock')
        old_lock = git(root, 'show', f'{base}:{lock}').decode() if lock in base_names else None
        new_lock = (root / lock).read_text(encoding='utf-8') if (root / lock).is_file() else None
        pins_changed = dependency_pins(root, old_lock) != dependency_pins(root, new_lock)
    changed = [lock] if pins_changed else []
    for name in sorted(guarded):
        old = git(root, 'show', f'{base}:{name}') if name in base_names else None
        new = (root / name).read_bytes() if (root / name).is_file() else None
        if old != new:
            changed.append(name)
    # Changing benchmark contracts also requires fresh, reviewed evidence.
    changes = git(root, 'diff', '--name-only', base, '--', 'benchmarks', 'backend/resources.py').decode().splitlines()
    changed.extend(name for name in changes if name == 'backend/resources.py' or name.startswith((
        'benchmarks/abcd-v', 'benchmarks/reference-baselines/')))
    return sorted(set(changed))


def measurement_key(root, ref=None):
    """Collection cache key, not a replacement for the runtime physics guard."""
    names = registry_sources(root) | set(PRIUS_EXTRA_PHYSICS) | {REGISTRY, 'requirements.lock',
        'solvers/magneto2d/Cargo.toml', '.github/workflows/release-benchmarks.yml', 'backend/resources.py',
        'tools/benchmark_prius.py', 'tools/prius_benchmark_contract.py', 'tools/report_prius_benchmark.py'}
    current = git(root, 'ls-tree', '-r', '--name-only', 'HEAD').decode().splitlines()
    names.update(n for n in current if n.startswith(('benchmarks/abcd-v1.6/', 'benchmarks/abcd-v1.9/', 'benchmarks/abcd-v1.10/',
                                                     'benchmarks/reference-baselines/',
                                                     'backend/benchmark_suite/', 'docs/benchmarks/pyleecan-prius-v1/')))
    present = set(git(root, 'ls-tree', '-r', '--name-only', ref or 'HEAD').decode().splitlines())
    values = {}
    for name in sorted(names):
        if ref:
            content = git(root, 'show', f'{ref}:{name}') if name in present else None
        else:
            content = (root / name).read_bytes() if (root / name).is_file() else None
        values[name] = hashlib.sha256(content).hexdigest() if content is not None else None
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def github(endpoint):
    return json.loads(subprocess.check_output(['gh', 'api', endpoint]))


def reusable_collection(root, key, repository, branch, current_run):
    from urllib.parse import quote

    runs = github(f'repos/{repository}/actions/workflows/ci.yml/runs?branch={quote(branch, safe="")}&event=pull_request&per_page=30')
    for run in runs['workflow_runs']:
        if str(run['id']) == str(current_run) or run.get('conclusion') in ('cancelled', 'timed_out'):
            continue
        previous = run['head_sha']
        ancestor = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', previous, 'HEAD'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ancestor.returncode or measurement_key(root, previous) != key:
            continue
        jobs = github(f'repos/{repository}/actions/runs/{run["id"]}/jobs?per_page=100')['jobs']
        measured = [j for j in jobs if j['name'].startswith('qualification-measure /')
                    or (j['name'] == 'qualification-measure' and j.get('conclusion') != 'skipped')]
        if not measured:
            continue
        artifacts = github(f'repos/{repository}/actions/runs/{run["id"]}/artifacts?per_page=100')['artifacts']
        names = {a['name'] for a in artifacts if not a.get('expired')}
        if {'benchmark-joined-windows-2022', 'benchmark-joined-macos-15'} <= names:
            return {'reuse_run_id': str(run['id']), 'collection_state': 'complete', 'measurement_candidate': previous}
        if run['status'] != 'completed' and all(j.get('conclusion') not in ('failure', 'cancelled', 'timed_out') for j in measured):
            return {'reuse_run_id': str(run['id']), 'collection_state': 'in_progress', 'measurement_candidate': previous}
    return {'reuse_run_id': '', 'collection_state': 'new', 'measurement_candidate': ''}


def assess(root, base):
    changed = changed_physics(root, base)
    errors = check(root) if changed else []
    return {'schema': 'coilem.physics_impact/v1', 'base': base,
            'head': git(root, 'rev-parse', 'HEAD').decode().strip(),
            'physics_change': bool(changed), 'changed_files': changed,
            'measurement_required': bool(changed and errors), 'errors': errors,
            'status': 'qualification evidence required' if errors else 'PASS'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--plan', action='store_true', help='Emit impact even when evidence is pending')
    args = parser.parse_args()
    result = assess(ROOT, args.base)
    result['physics_identity'] = measurement_key(ROOT) if result['physics_change'] else ''
    result.update(reuse_run_id='', collection_state='new', measurement_candidate=result['head'])
    if (args.plan and result['measurement_required'] and os.environ.get('GH_TOKEN')
            and os.environ.get('QUALIFICATION_PR_BRANCH')):
        cached = reusable_collection(ROOT, result['physics_identity'], os.environ['GITHUB_REPOSITORY'],
                                     os.environ['QUALIFICATION_PR_BRANCH'], os.environ['GITHUB_RUN_ID'])
        if cached['reuse_run_id']:
            result.update(cached)
            result['measurement_required'] = False
    print(json.dumps(result, indent=2))
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a', encoding='utf-8') as stream:
            for key in ('physics_change', 'measurement_required'):
                stream.write(f'{key}={str(result[key]).lower()}\n')
            for key in ('physics_identity', 'reuse_run_id', 'collection_state', 'measurement_candidate'):
                stream.write(f'{key}={result[key]}\n')
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(summary, 'a', encoding='utf-8') as stream:
            stream.write('### Qualification evidence\n\n' + result['status'] + '\n\n')
            stream.write('\n'.join(f'- `{name}`' for name in result['changed_files']) + '\n\n')
            stream.write('\n'.join(f'- {error}' for error in result['errors']) + '\n')
    return 0 if args.plan or not result['errors'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
