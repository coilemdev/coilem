"""Apply compact measured evidence using trusted base tooling, then verify it."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from backend.benchmark_suite.contract import checked_path, read, sha, write
from tools.release.qualification import check

ROOT = Path(__file__).resolve().parents[1]


def apply(publication, root, candidate):
    if not re.fullmatch('[0-9a-f]{40}', candidate):
        raise ValueError('Need an immutable candidate SHA')
    actual = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != candidate:
        raise ValueError('PR advanced after measurement; do not overwrite it')
    # Never execute an edited candidate registry under the publisher's token.
    registry = 'backend/benchmark_suite/physics.py'
    if sha(root / registry) != sha(ROOT / registry):
        raise ValueError('Registry changes need owner review and updated trusted tooling')
    files = [p for p in publication.rglob('*') if p.is_file()]
    records = {f'benchmarks/records/{key}.json' for key in ('windows-x86_64', 'macos-arm64')}
    names = {p.relative_to(publication).as_posix() for p in files}
    if not records <= names:
        raise ValueError('Publication is missing a platform record')
    prefix = f'benchmarks/qualification-{candidate[:12]}/'
    for path in files:
        name = path.relative_to(publication).as_posix()
        if (path.is_symlink() or path.suffix not in {'.json', '.html', '.md', '.csv', '.svg'}
                or (name not in records and not name.startswith(prefix))):
            raise ValueError('Unexpected publication path')
        target = checked_path(root, name)
        if name not in records and target.exists() and sha(target) != sha(path):
            raise ValueError('Refusing to overwrite historical evidence')
    previous = {name: (root / name).read_bytes() if (root / name).is_file() else None for name in names}
    try:
        for path in files:
            target = checked_path(root, path.relative_to(publication))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        errors = check(root, candidate=candidate)
        if errors:
            raise ValueError('Publication rejected: ' + '; '.join(errors))
    except BaseException:
        for name, content in previous.items():
            target = checked_path(root, name)
            if content is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(content)
        raise
    snapshot_path = root / 'snapshot-manifest.json'
    snapshot = read(snapshot_path)
    tracked = set(subprocess.check_output(['git', '-C', str(root), 'ls-files'], text=True).splitlines()) | names
    tracked.discard('snapshot-manifest.json')
    order = [e['path'] for e in snapshot['files'] if e['path'] in tracked]
    order.extend(sorted(tracked - set(order)))
    snapshot['files'] = [{'path': name, 'bytes': (root / name).stat().st_size, 'sha256': sha(root / name)} for name in order]
    for name in sorted(records):
        old = subprocess.check_output(['git', '-C', str(root), 'show', f'HEAD:{name}'])
        snapshot['public_patches'].append({'base_commit': candidate, 'path': name,
            'source_sha256': hashlib.sha256(old).hexdigest(), 'reason': 'Publish fresh measured qualification evidence (#194).'})
    write(snapshot_path, snapshot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--candidate', required=True)
    args = parser.parse_args()
    apply(args.publication, args.root.resolve(), args.candidate)
    print(json.dumps({'status': 'PASS', 'candidate': args.candidate}))


if __name__ == '__main__':
    main()
