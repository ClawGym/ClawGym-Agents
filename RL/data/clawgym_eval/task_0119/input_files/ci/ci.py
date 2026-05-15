import os
import json
import subprocess
import time

def main():
    ci_dir = os.path.dirname(__file__)
    pipeline_path = os.path.join(ci_dir, 'pipeline.json')
    with open(pipeline_path, 'r', encoding='utf-8') as f:
        pipeline = json.load(f)

    results = {
        'name': pipeline.get('name', 'local-ci'),
        'ok': True,
        'started_at': time.time(),
        'steps': []
    }

    for step in pipeline.get('steps', []):
        t0 = time.time()
        proc = subprocess.run(step['run'], shell=True, capture_output=True, text=True)
        t1 = time.time()
        step_result = {
            'name': step['name'],
            'command': step['run'],
            'returncode': proc.returncode,
            'status': 'success' if proc.returncode == 0 else 'failed',
            'started_at': t0,
            'ended_at': t1,
            'stdout': proc.stdout,
            'stderr': proc.stderr
        }
        results['steps'].append(step_result)
        if proc.returncode != 0:
            results['ok'] = False

    results['ended_at'] = time.time()

    out_path = os.path.join(ci_dir, 'latest_run.json')
    with open(out_path, 'w', encoding='utf-8') as outf:
        json.dump(results, outf, indent=2)

if __name__ == '__main__':
    main()
