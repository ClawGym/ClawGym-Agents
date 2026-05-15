#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from datetime import datetime

def main():
    config_path = os.path.join('ci', 'ci.json')
    if not os.path.exists(config_path):
        print(f"Missing config: {config_path}", file=sys.stderr)
        sys.exit(2)

    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    steps = cfg.get('steps', [])
    if not isinstance(steps, list) or not steps:
        print("No steps defined in ci/ci.json", file=sys.stderr)
        sys.exit(2)

    os.makedirs(os.path.join('out', 'logs'), exist_ok=True)
    log_path = os.path.join('out', 'logs', 'ci.log')

    def write_log(header, content):
        with open(log_path, 'a', encoding='utf-8') as lf:
            lf.write(header + "\n")
            if content:
                lf.write(content)
                if not content.endswith('\n'):
                    lf.write('\n')

    write_log(f"== CI START {datetime.utcnow().isoformat()}Z ==", "")

    for i, step in enumerate(steps, start=1):
        name = step.get('name', f'step{i}')
        cmd = step.get('run')
        if not cmd:
            print(f"Step '{name}' missing 'run' command", file=sys.stderr)
            sys.exit(2)
        write_log(f"\n== STEP {i}: {name} ==", f"COMMAND: {cmd}\nSTART: {datetime.utcnow().isoformat()}Z")
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        out = (proc.stdout or '')
        err = (proc.stderr or '')
        write_log("STDOUT:", out)
        write_log("STDERR:", err)
        write_log("END:", f"returncode={proc.returncode}\n")
        if proc.returncode != 0:
            write_log("== CI FAILED ==", f"Failed at step: {name}")
            print(f"CI failed at step '{name}'", file=sys.stderr)
            sys.exit(proc.returncode)

    write_log(f"== CI COMPLETE {datetime.utcnow().isoformat()}Z ==", "")
    print(f"CI completed. Log: {log_path}")

if __name__ == '__main__':
    main()
