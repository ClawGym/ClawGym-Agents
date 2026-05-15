import argparse
import json
import os
import subprocess
from datetime import datetime


def ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def timestamp():
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def run_pipeline(pipeline_path, log_path):
    with open(pipeline_path, 'r', encoding='utf-8') as f:
        pipeline = json.load(f)

    env_vars = pipeline.get('env', {}) or {}

    ensure_parent_dir(log_path)
    with open(log_path, 'w', encoding='utf-8') as log:
        def write_log(line):
            log.write(f"[{timestamp()}] {line}\n")

        write_log(f"Starting pipeline: {pipeline_path}")
        if env_vars:
            write_log(f"Applying env: {env_vars}")
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in env_vars.items()})

        stages = pipeline.get('stages', [])
        for stage in stages:
            stage_name = stage.get('name', 'unnamed-stage')
            write_log(f"STAGE {stage_name}: START")
            steps = stage.get('steps', [])
            for step in steps:
                step_name = step.get('name', 'unnamed-step')
                cmd = step.get('run')
                if not cmd:
                    write_log(f"STAGE {stage_name} - STEP {step_name}: SKIPPED (no run command)")
                    continue
                write_log(f"STAGE {stage_name} - STEP {step_name}: START cmd='{cmd}'")
                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)
                write_log(f"STAGE {stage_name} - STEP {step_name}: RETURN CODE {proc.returncode}")
                if proc.stdout:
                    write_log(f"STDOUT BEGIN\n{proc.stdout.rstrip()}\nSTDOUT END")
                if proc.stderr:
                    write_log(f"STDERR BEGIN\n{proc.stderr.rstrip()}\nSTDERR END")
                if proc.returncode != 0:
                    write_log(f"STAGE {stage_name} - STEP {step_name}: FAILED, aborting pipeline")
                    write_log("Pipeline status: FAILURE")
                    return 1
            write_log(f"STAGE {stage_name}: END")
        write_log("Pipeline status: SUCCESS")
    return 0


def main():
    parser = argparse.ArgumentParser(description='Local CI pipeline simulator (offline)')
    parser.add_argument('--pipeline', required=True, help='Path to pipeline JSON (e.g., ci/pipeline.json)')
    parser.add_argument('--log', required=True, help='Path to write the CI log (e.g., output/ci.log)')
    args = parser.parse_args()

    rc = run_pipeline(args.pipeline, args.log)
    raise SystemExit(rc)


if __name__ == '__main__':
    main()
