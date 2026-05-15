#!/usr/bin/env python3
import json
import sys
import os
import re
import zipfile
from datetime import datetime


def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def read_jsonl(path):
    items = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def ensure_dir(d):
    os.makedirs(d, exist_ok=True)


def validate_call_sign(cs):
    if not isinstance(cs, str):
        return False
    # Simple pattern: 3-7 uppercase letters/digits (e.g., N123AB)
    return re.fullmatch(r"[A-Z0-9]{3,7}", cs) is not None


def phrase_check(items):
    required = ["call_sign", "scenario", "pilot_says", "atc_says"]
    for i, it in enumerate(items):
        for k in required:
            v = it.get(k, "")
            if not isinstance(v, str) or len(v.strip()) == 0:
                return False, f"Record {i} missing or empty field: {k}"
        if not validate_call_sign(it.get("call_sign", "")):
            return False, f"Record {i} invalid call_sign: {it.get('call_sign')}"
    return True, "ok"


def write_report(report_dir, summary):
    ensure_dir(report_dir)
    with open(os.path.join(report_dir, "ci-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


def run(config_path):
    cfg = read_json(config_path)
    app = cfg.get("app_name", "app")
    version = cfg.get("version", "0.0.0")
    steps = cfg.get("enabled_steps", [])
    data_path = cfg.get("data_path")
    dist_dir = cfg.get("dist_dir", "dist")
    report_dir = cfg.get("report_dir", "reports")

    ensure_dir(dist_dir)
    ensure_dir(report_dir)

    summary = {
        "app_name": app,
        "version": version,
        "steps_run": [],
        "scenario_count": 0,
        "tests_passed": False,
        "phrase_check_passed": None,
        "artifact": os.path.join(dist_dir, f"{app}-{version}.zip"),
        "artifact_exists": False,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    items = read_jsonl(data_path) if data_path else []
    summary["scenario_count"] = len(items)

    # Step: test
    if "test" in steps:
        summary["steps_run"].append("test")
        summary["tests_passed"] = (
            len(items) > 0 and all(isinstance(it.get("call_sign", ""), str) and it.get("call_sign", "").strip() for it in items)
        )
        if not summary["tests_passed"]:
            write_report(report_dir, summary)
            return 1, summary

    # Step: phrase_check
    if "phrase_check" in steps:
        summary["steps_run"].append("phrase_check")
        ok, msg = phrase_check(items)
        summary["phrase_check_passed"] = ok
        summary["phrase_check_message"] = msg
        if not ok:
            write_report(report_dir, summary)
            return 1, summary

    # Step: build
    if "build" in steps:
        summary["steps_run"].append("build")
        artifact = summary["artifact"]
        with zipfile.ZipFile(artifact, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            if data_path and os.path.exists(data_path):
                z.write(data_path, arcname=os.path.basename(data_path))
            manifest = {
                "app_name": app,
                "version": version,
                "scenario_count": len(items),
                "built_at": summary["timestamp"]
            }
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
        summary["artifact_exists"] = os.path.exists(artifact)

    write_report(report_dir, summary)
    return 0, summary


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "--config":
        print("Usage: ci.py --config input/config.json", file=sys.stderr)
        sys.exit(2)
    code, summary = run(sys.argv[2])
    print(f"Steps: {','.join(summary['steps_run'])}")
    print(f"Scenarios: {summary['scenario_count']}")
    print(f"Tests passed: {summary['tests_passed']}")
    print(f"Phrase check: {summary.get('phrase_check_passed')}")
    print(f"Artifact: {summary['artifact']} (exists={summary['artifact_exists']})")
    sys.exit(code)
