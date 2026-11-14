"""Conservative PR job selection. Unknown paths and missing history run everything.

Qualification deliberately has its own, independent physics/evidence gate.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ('runtime', 'frontend', 'browser', 'native', 'audit')
PR_MATRIX = [
    {'os': 'ubuntu-24.04', 'python': '3.11'},
    {'os': 'windows-latest', 'python': '3.11'},
]
FULL_MATRIX = [*PR_MATRIX, {'os': 'macos-latest', 'python': '3.11'}, {'os': 'ubuntu-24.04', 'python': '3.15'}]
COMPATIBILITY_FILES = {'pyproject.toml', 'setup.py', 'requirements.lock', 'MANIFEST.in', 'tools/release/policy.py'}
DOC_FILES = {'LICENSE', 'CITATION.cff', '.gitattributes', '.gitignore', 'snapshot-manifest.json'}


def select(paths: list[str] | None, *, full: bool = False) -> dict:
    selected = set(CHECKS) if full or paths is None else set()
    for path in paths or []:
        if path.startswith('frontend/'):
            selected.update(('frontend', 'browser'))
        elif path.startswith('solvers/'):
            selected.update(('runtime', 'browser', 'native', 'audit'))
        elif path.startswith(('backend/', 'tests/', 'tools/')):
            selected.update(('runtime', 'browser'))
        elif path in {'pyproject.toml', 'setup.py', 'requirements.lock', 'MANIFEST.in'} or path.startswith('.github/'):
            selected.update(CHECKS)
        elif path in DOC_FILES or path.endswith('.md'):
            # Publication and qualification still check these independently.
            continue
        else:
            selected.update(CHECKS)
    compatibility = any(path in COMPATIBILITY_FILES or path.startswith('.github/') for path in paths or [])
    matrix = FULL_MATRIX if full or compatibility else PR_MATRIX
    return {**{name: name in selected for name in CHECKS}, 'runtime_matrix': {'include': matrix}}


def changed_paths(root: Path, base: str, head: str, *, pull_request: bool) -> list[str] | None:
    # Event SHAs only; a deleted branch, first push or incomplete history is full coverage.
    if not all(re.fullmatch(r'[0-9a-f]{40,64}', sha) and set(sha) != {'0'} for sha in (base, head)):
        return None
    try:
        diff = subprocess.check_output(
            ['git', 'diff', '--name-only', '--no-renames', '-z', f'{base}{"..." if pull_request else ".."}{head}'],
            cwd=root, stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return None
    return [os.fsdecode(name) for name in diff.split(b'\0') if name]


def plan(event_name: str, event: dict, ref: str, sha: str, root: Path = ROOT) -> dict:
    full = event_name in {'schedule', 'workflow_dispatch'} or ref.startswith('refs/heads/release/')
    pr = event_name == 'pull_request'
    if pr:
        base = event.get('pull_request', {}).get('base', {}).get('sha', '')
        head = event.get('pull_request', {}).get('head', {}).get('sha', '')
    else:
        base, head = event.get('before', ''), sha
    paths = None if full else changed_paths(root, base, head, pull_request=pr)
    return select(paths, full=full)


def main() -> None:
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    result = plan(os.environ['GITHUB_EVENT_NAME'], event, os.environ['GITHUB_REF'], os.environ['GITHUB_SHA'])
    values = {key: json.dumps(value, separators=(',', ':')) for key, value in result.items()}
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
        output.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
