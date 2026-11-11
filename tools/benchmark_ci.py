"""Small entry points for the build / shard / join qualification workflow."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from backend.benchmark_suite import COMMAND_PHASES
from backend.benchmark_suite.contract import identity, read, sha, write
from backend.resources import BENCHMARK_REFERENCE_BUNDLE_DIR
from tools.benchmark_shards import plan
from tools.join_benchmark_runs import join_prius, join_suite

ROOT = Path(__file__).resolve().parents[1]


def binary_path():
    return ROOT / 'solvers/magneto2d/target/release' / ('magneto2d.exe' if os.name == 'nt' else 'magneto2d')


def run(*args):
    subprocess.run([sys.executable, '-m', *map(str, args)], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['plan', 'binary', 'shard', 'join'])
    parser.add_argument('--runner', default='both')
    parser.add_argument('--shard')
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--collection', default='registered', choices=['registered', 'protocol16-native-only'])
    args = parser.parse_args()
    if requested := os.environ.get('COILEM_BUILD_COMMIT'):
        actual = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
        if not re.fullmatch('[0-9a-f]{40}', requested) or requested != actual:
            raise ValueError('candidate must be the exact full immutable checkout SHA')
    spec = plan()
    directory = args.directory.resolve()
    if args.stage == 'plan':
        runners = ['windows-2022', 'macos-15'] if args.runner == 'both' else [args.runner]
        matrix = {'include': [{**shard, 'runner': runner} for runner in runners for shard in spec['shards']]}
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            stream.write('matrix=' + json.dumps(matrix) + '\n')
            stream.write('platforms=' + json.dumps(runners) + '\n')
        write(directory / 'plan.json', spec)
    elif args.stage == 'binary':
        write(directory / 'build-receipt.json', {'identity': identity(binary_path()), 'plan': spec})
        shutil.copyfile(binary_path(), directory / binary_path().name)
    elif args.stage == 'shard':
        receipt = read(directory / 'build-receipt.json')
        if identity(binary_path()) != receipt['identity'] or spec != receipt['plan']:
            raise ValueError('Build artifact does not match candidate, environment, binary or shard plan')
        shard = next(s for s in spec['shards'] if s['id'] == args.shard)
        output = directory / 'out'
        if shard['kind'] == 'suite':
            options = ['tools.run_benchmarks', '--suite', spec['suite'], '--phases', *COMMAND_PHASES,
                       '--out-dir', output, '--archive-runtime']
            if args.collection == 'protocol16-native-only':
                options.append('--no-reference')
            for case in shard['cases']:
                options.extend(['--case', case])
            run(*options)
        else:
            options = ['tools.benchmark_prius', '--out', output, '--curve', '--refinement']
            for job in shard['cases']:
                options.extend(['--job', job])
            run(*options)
        write(output / 'workflow-receipt.json', {'candidate': receipt['identity']['commit'],
              'plan_sha256': spec['plan_sha256'], 'shard': shard,
              'run_url': os.environ.get('COILEM_WORKFLOW_RUN_URL'), 'binary_sha256': sha(binary_path())})
    else:
        folders = sorted((directory / 'shards').iterdir())
        selected = {}
        for folder in folders:
            receipt = read(folder / 'workflow-receipt.json')
            shard = receipt['shard']
            if shard not in spec['shards'] or shard['id'] in selected or receipt['plan_sha256'] != spec['plan_sha256']:
                raise ValueError('Duplicate or unregistered workflow shard')
            selected[shard['id']] = folder
        if set(selected) != {s['id'] for s in spec['shards']}:
            raise ValueError('Missing workflow shard')
        suite_shards = [selected[s['id']] for s in spec['shards'] if s['kind'] == 'suite']
        prius_shards = [selected[s['id']] for s in spec['shards'] if s['kind'] == 'prius']
        join_suite(suite_shards, suite=ROOT / spec['suite'], bundle=ROOT / BENCHMARK_REFERENCE_BUNDLE_DIR,
                   output=directory / 'joined-suite')
        join_prius(prius_shards, directory / 'joined-prius')
        run('tools.report_prius_benchmark', directory / 'joined-prius', '--out', directory / 'prius-report')
        shutil.copyfile(ROOT / 'snapshot-manifest.json', directory / 'prius-report/source-snapshot.json')
        write(directory / 'join-receipt.json', {'schema': 'coilem.qualification_ci_join/v1',
              'plan': spec, 'shards': [read(f / 'workflow-receipt.json') for f in folders]})


if __name__ == '__main__':
    main()
