"""One PR qualification gate, including current-tree Prius evidence freshness."""
from __future__ import annotations

import argparse
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


def registry_sources(root):
    spec = importlib.util.spec_from_file_location('_qualification_physics', root / REGISTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.physics_sources(root))


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
    changed = []
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
    print(json.dumps(result, indent=2))
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a', encoding='utf-8') as stream:
            for key in ('physics_change', 'measurement_required'):
                stream.write(f'{key}={str(result[key]).lower()}\n')
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(summary, 'a', encoding='utf-8') as stream:
            stream.write('### Qualification evidence\n\n' + result['status'] + '\n\n')
            stream.write('\n'.join(f'- `{name}`' for name in result['changed_files']) + '\n\n')
            stream.write('\n'.join(f'- {error}' for error in result['errors']) + '\n')
    return 0 if args.plan or not result['errors'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
