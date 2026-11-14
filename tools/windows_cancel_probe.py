"""Repeat real launcher interrupts, preserving watchdog traces for hangs (#234)."""
from __future__ import annotations

import argparse
import copy
import faulthandler
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import threading
import time

from tools.release.acceptance import CYLINDRICAL_HALBACH, LINEAR_HALBACH, MOTOR, SolveStream, request, sse_events


class StageStream(SolveStream):
    def __init__(self, url, body, stage):
        self.target_stage = stage
        super().__init__(url, body)

    def read(self, lines):
        for event, payload in sse_events(lines):
            fields = payload if isinstance(payload, dict) else {}
            self.last = (event, str(fields.get('stage', '')), fields.get('position'), fields.get('total'))
            position, total = fields.get('position'), fields.get('total')
            if (event == 'progress' and fields.get('stage') == self.target_stage
                    and isinstance(position, int) and isinstance(total, int) and 0 < position < total):
                self.solving.set()
            if event in ('complete', 'error'):
                self.outcome = event


def serve(folder):
    import backend.launcher as launcher
    import backend.resources as resources

    resources.ui_bundle_root = lambda: folder / 'ui'
    trace = (folder / 'traceback.txt').open('w', encoding='utf-8')
    faulthandler.enable(file=trace)

    # Arm before solving: a signal or Python watchdog thread cannot diagnose
    # a main thread blocked inside a native call that holds the GIL.
    faulthandler.dump_traceback_later(20, repeat=True, file=trace)
    return launcher.main(['--no-browser', '--port', os.environ['COILEM_PROBE_PORT']])


def attempt(folder, stage, entrypoint):
    folder.mkdir(parents=True)
    (folder / 'ui').mkdir()
    (folder / 'ui/index.html').write_text('<!doctype html><title>coilEM probe</title>')
    if entrypoint == 'console':
        from pip._vendor.distlib.scripts import ScriptMaker

        maker = ScriptMaker(None, str(folder))
        maker.executable = sys.executable
        maker.variants = {''}
        maker.make('coilem-cancel-probe = tools.windows_cancel_probe:main')
        command = [str(folder / ('coilem-cancel-probe.exe' if os.name == 'nt' else 'coilem-cancel-probe')),
                   '--serve', str(folder)]
    else:
        command = [sys.executable, '-u', '-m', 'tools.windows_cancel_probe', '--serve', str(folder)]
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    env = {**os.environ, 'COILEM_USER_DATA_ROOT': str(folder / 'data'), 'COILEM_PROBE_PORT': str(port),
           'PYTHONPATH': str(Path(__file__).resolve().parents[1]), 'PYTHONUNBUFFERED': '1'}
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', errors='replace',
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
    ready = threading.Event()
    output = []
    address = []

    def drain():
        for line in process.stdout:
            output.append(line)
            found = re.search(r'is running at (http://127\.0\.0\.1:\d+)', line)
            if found:
                address.append(found[1]); ready.set()

    reader = threading.Thread(target=drain, daemon=True); reader.start()
    result = {'stage': stage, 'entrypoint': entrypoint}
    try:
        if not ready.wait(90):
            raise RuntimeError('launcher never became ready')
        base = address[0]
        warm = copy.deepcopy(MOTOR)
        warm['solve_params'].update(solve_quality='quick', mesh_density='coarse')
        for route, body in (('/solve', warm), ('/halbach/solve', CYLINDRICAL_HALBACH),
                            ('/halbach/linear/solve', LINEAR_HALBACH)):
            status, _, _ = request('POST', base + route, body)
            if status != 200:
                raise RuntimeError(f'warm-up {route}: {status}')
        status, _, _ = request('GET', base + '/tutorials/follow-the-flux/solve?steel_return=true')
        if status != 200:
            raise RuntimeError(f'lesson warm-up: {status}')
        standard = copy.deepcopy(MOTOR)
        standard['solve_params'].update(solve_quality='standard', mesh_density='normal')
        stream = StageStream(base + '/solve/stream', standard, stage)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and not stream.solving.is_set() and not stream.ended.is_set():
            stream.solving.wait(0.05)
        if not stream.solving.is_set() or stream.ended.is_set():
            raise RuntimeError(f'target stage not reached: {stream.describe()}')
        result['progress'] = stream.last
        (folder / 'interrupt').touch()
        started = time.monotonic()
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGINT)
        try:
            result['exit'] = process.wait(timeout=35)
        except subprocess.TimeoutExpired:
            result['exit'] = None
        result['shutdown_seconds'] = round(time.monotonic() - started, 3)
        result['cancelled'] = any('SOLVER_CANCELLED' in p.read_text(encoding='utf-8')
                                  for p in (folder / 'data').rglob('manifest.json'))
        result['record_removed'] = not (folder / 'data/launcher.json').exists()
        result['pass'] = result['exit'] == 0 and result['cancelled'] and result['record_removed']
    except Exception as error:
        result.update(error=str(error), **{'pass': False})
    finally:
        if process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            else:
                process.kill()
            process.wait(timeout=10)
        reader.join(5)
        (folder / 'launcher.txt').write_text(''.join(output), encoding='utf-8')
        (folder / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--entrypoint', choices=['python', 'console'], default='console' if os.name == 'nt' else 'python')
    parser.add_argument('--attempts', type=int, default=8)
    parser.add_argument('--stage', choices=['noload_sweep', 'magneto2d_sweep'], default='noload_sweep')
    args = parser.parse_args()
    if args.serve:
        return serve(args.serve)
    if args.out is None:
        parser.error('--out is required')
    results = [attempt(args.out.resolve() / f'attempt-{i:02}', args.stage, args.entrypoint) for i in range(args.attempts)]
    return 0 if all(r['pass'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
