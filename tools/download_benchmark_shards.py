"""Download shards sequentially, keeping bulky raw archives out of the join.

Old workflow artifacts may contain both raw archives and compact evidence.
Stage one at a time, retain the immutable requests/results and Prius audit
inputs, then remove only this local download's redundant archive copies.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def link_or_copy(source, target):
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)
    return target


def compact(source, target):
    shutil.copytree(source, target, copy_function=link_or_copy,
                    ignore=shutil.ignore_patterns('native-runtime', '*.tar.gz', '*.tmp', 'run.lock'))


def download(repository, run_id, runner, output):
    if not str(run_id).isdigit() or runner not in ('windows-2022', 'macos-15', 'ubuntu-24.04'):
        raise ValueError('Need a numeric run ID and registered platform')
    prefix = f'benchmark-shard-{runner}-'
    response = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100']))
    artifacts = [a for a in response['artifacts'] if a['name'].startswith(prefix) and not a['expired']]
    if len(artifacts) != 12 or len({a['name'] for a in artifacts}) != 12:
        raise ValueError('Need all twelve platform shards; collection may still be running')
    output.mkdir(parents=True, exist_ok=False)
    receipts = []
    for artifact in sorted(artifacts, key=lambda a: a['name']):
        with tempfile.TemporaryDirectory(prefix='coilem-shard-', dir=output.parent) as temporary:
            source = Path(temporary)
            subprocess.run(['gh', 'run', 'download', str(run_id), '--repo', repository,
                            '--name', artifact['name'], '--dir', str(source)], check=True)
            compact(source, output / artifact['name'])
        receipts.append({k: artifact.get(k) for k in ('id', 'name', 'digest', 'size_in_bytes')})
        print('Verified download selection:', artifact['name'], flush=True)
    (output.parent / 'download-receipt.json').write_text(json.dumps({
        'source_repository': repository, 'source_run_id': str(run_id), 'artifacts': receipts,
        'measurement_files_mutated': False, 'raw_archives_retained_in_source_run': True,
    }, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--runner', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY'))
    args = parser.parse_args()
    if not args.repo:
        parser.error('--repo is required outside Actions')
    download(args.repo, args.run_id, args.runner, args.out)


if __name__ == '__main__':
    main()
