import json
import subprocess
import time
import os
from pathlib import Path

def main():
    cfg_path = Path('.ci/pipeline.json')
    if not cfg_path.exists():
        raise SystemExit('Missing .ci/pipeline.json')

    with cfg_path.open('r', encoding='utf-8') as f:
        cfg = json.load(f)

    outdir = Path('output')
    outdir.mkdir(exist_ok=True)

    steps_log = []
    for step in cfg.get('steps', []):
        name = step.get('name', 'unnamed')
        cmd = step.get('run')
        if not cmd:
            continue
        t0 = time.time()
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        t1 = time.time()
        steps_log.append({
            'name': name,
            'returncode': proc.returncode,
            'duration_seconds': round(t1 - t0, 3)
        })

    total_duration_seconds = round(sum(s['duration_seconds'] for s in steps_log), 3)

    tests = {'total': 0, 'passed': 0, 'failed': 0}
    test_results_path = outdir / 'test_results.json'
    if test_results_path.exists():
        try:
            with test_results_path.open('r', encoding='utf-8') as f:
                tr = json.load(f)
            for k in ['total', 'passed', 'failed']:
                if isinstance(tr.get(k), int):
                    tests[k] = tr[k]
        except Exception:
            pass

    logs = {
        'pipeline_name': cfg.get('name', ''),
        'steps': steps_log,
        'total_duration_seconds': total_duration_seconds,
        'tests': tests
    }

    with (outdir / 'ci_logs.json').open('w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2)

    with (outdir / 'ci_summary.md').open('w', encoding='utf-8') as f:
        f.write(f"Pipeline: {logs['pipeline_name']}\n")
        f.write(f"Steps: {len(steps_log)}\n")
        f.write(f"Total duration (s): {total_duration_seconds}\n")
        f.write(
            f"Tests - total: {tests['total']}, passed: {tests['passed']}, failed: {tests['failed']}\n"
        )

    print('CI simulation complete. Artifacts written to output/.')

if __name__ == '__main__':
    main()
