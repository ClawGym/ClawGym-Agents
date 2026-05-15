import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time

# Minimal YAML-like parser for simple key: value lines without nesting
# Avoids external dependencies.
def parse_config(path):
    cfg = {}
    with open(path, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if ':' in line:
                k, v = line.split(':', 1)
                cfg[k.strip()] = v.strip()
    # Coerce timeout if present
    if 'timeout_s' in cfg:
        try:
            cfg['timeout_s'] = int(cfg['timeout_s'])
        except Exception:
            cfg['timeout_s'] = 30
    else:
        cfg['timeout_s'] = 30
    return cfg

def parse_test_counts(output_text):
    passed = None
    failed = None
    m_p = re.search(r"PASSED:\s*(\d+)", output_text)
    m_f = re.search(r"FAILED:\s*(\d+)", output_text)
    if m_p:
        passed = int(m_p.group(1))
    if m_f:
        failed = int(m_f.group(1))
    return passed, failed

def main():
    ap = argparse.ArgumentParser(description='Local CI runner')
    ap.add_argument('--config', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    cfg = parse_config(args.config)
    cmd = cfg.get('test_command')
    if not cmd:
        print('Config missing test_command', file=sys.stderr)
        sys.exit(2)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    start = time.time()
    status = 'error'
    stdout_text = ''
    stderr_text = ''
    tests_passed = None
    tests_failed = None
    exit_code = None

    try:
        proc = subprocess.run(
            shlex.split(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=cfg.get('timeout_s', 30),
            text=True,
            check=False
        )
        stdout_text = proc.stdout or ''
        stderr_text = proc.stderr or ''
        exit_code = proc.returncode
        tests_passed, tests_failed = parse_test_counts(stdout_text)
        status = 'success' if exit_code == 0 else 'failure'
    except FileNotFoundError as e:
        stderr_text = f'FileNotFoundError: {e}'
        status = 'error'
    except subprocess.TimeoutExpired as e:
        stdout_text = e.stdout or ''
        stderr_text = (e.stderr or '') + '\nTimeoutExpired'
        status = 'failure'
    except Exception as e:
        stderr_text = f'Unhandled exception: {e}'
        status = 'error'

    duration = time.time() - start

    report = {
        'status': status,
        'command': cmd,
        'tests_passed': tests_passed,
        'tests_failed': tests_failed,
        'duration_seconds': round(duration, 6),
        'stdout': stdout_text[-4000:],
        'stderr': stderr_text[-4000:]
    }

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    # Mirror status to exit code for local use (optional)
    if status == 'success':
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()
