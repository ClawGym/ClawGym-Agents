import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        rows: List[Dict[str, str]] = []
        reader = csv.DictReader(text.splitlines())
        expected_headers = {"suite", "test_id", "script", "expected_status"}
        if set(reader.fieldnames or []) != expected_headers:
            return None
        for row in reader:
            if not all(k in row for k in expected_headers):
                return None
            rows.append({
                "suite": row["suite"],
                "test_id": row["test_id"],
                "script": row["script"],
                "expected_status": row["expected_status"],
            })
        return rows
    except Exception:
        return None


def _run_test_script(workspace: Path, script_rel_path: str, timeout_sec: int = 10) -> Tuple[str, str, Optional[float], Optional[Dict[str, Any]]]:
    script_path = workspace / script_rel_path
    if not script_path.exists():
        return ("error", f"script not found: {script_rel_path}", None, None)
    try:
        completed = subprocess.run(
            [sys.executable, script_rel_path],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return ("error", f"timeout executing {script_rel_path}", None, None)
    except Exception as e:
        return ("error", f"exec failed: {e.__class__.__name__}", None, None)

    stdout = completed.stdout.strip()
    if completed.returncode != 0:
        try:
            raw = json.loads(stdout)
        except Exception:
            stderr_note = (completed.stderr or "").strip()
            short_err = stderr_note.splitlines()[0] if stderr_note else "non-zero exit"
            return ("error", short_err, None, None)
        status = str(raw.get("status", "error"))
        message = str(raw.get("message", ""))
        duration = raw.get("duration_ms", None)
        try:
            duration_ms = float(duration) if duration is not None else None
        except Exception:
            duration_ms = None
        return (status, message, duration_ms, raw)

    try:
        raw = json.loads(stdout)
    except Exception:
        short = stdout[:80] if stdout else "no stdout / non-JSON"
        return ("error", f"non-JSON stdout: {short}", None, None)

    status = str(raw.get("status", "error"))
    message = str(raw.get("message", ""))
    duration = raw.get("duration_ms", None)
    try:
        duration_ms = float(duration) if duration is not None else None
    except Exception:
        duration_ms = None
    return (status, message, duration_ms, raw)


def _compute_change(baseline_status: Optional[str], current_status: str) -> str:
    def is_pass(s: Optional[str]) -> bool:
        return s == "pass"

    def is_fail_like(s: Optional[str]) -> bool:
        return s in {"fail", "error"}

    if baseline_status is None:
        return "no_change"
    if is_pass(baseline_status) and is_fail_like(current_status):
        return "regression"
    if is_fail_like(baseline_status) and is_pass(current_status):
        return "fix"
    return "no_change"


def _parse_summary_numbers(summary_text: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    total = None
    passed = None
    failed = None
    lines = summary_text.splitlines()
    for line in lines:
        lower = line.lower()
        if "total" in lower:
            m = re.search(r"total[^0-9]*(\d+)", lower)
            if m:
                try:
                    total = int(m.group(1))
                except Exception:
                    pass
        if "pass" in lower:
            m = re.search(r"pass\w*[^0-9]*(\d+)", lower)
            if m:
                try:
                    passed = int(m.group(1))
                except Exception:
                    pass
        if "fail" in lower:
            m = re.search(r"fail\w*[^0-9]*(\d+)", lower)
            if m:
                try:
                    failed = int(m.group(1))
                except Exception:
                    pass
    return total, passed, failed


def _extract_bullet_lines(summary_text: str) -> List[str]:
    bullets: List[str] = []
    for line in summary_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullets.append(stripped)
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "run_results_present": 0.0,
        "run_results_cover_all_tests": 0.0,
        "run_results_schema_valid": 0.0,
        "run_results_content_correct": 0.0,
        "summary_present": 0.0,
        "summary_overview_matches": 0.0,
        "summary_expected_vs_actual_lists_mismatches": 0.0,
        "summary_changes_vs_baseline_lists": 0.0,
        "summary_reproduction_commands_listed": 0.0,
    }

    # Load manifest and baseline (as internal references, not scored directly)
    manifest_path = workspace / "input" / "community_test_manifest.csv"
    manifest_rows = _safe_load_csv(manifest_path)
    manifest_ok = manifest_rows is not None

    baseline_path = workspace / "input" / "baseline_results.json"
    baseline_data = _safe_load_json(baseline_path)
    baseline_map: Dict[str, Optional[str]] = {}
    if isinstance(baseline_data, list):
        for item in baseline_data:
            if isinstance(item, dict) and isinstance(item.get("test_id"), str):
                status = item.get("status")
                if isinstance(status, str):
                    baseline_map[item["test_id"]] = status

    # Recompute truth by executing scripts per manifest
    recomputed: Dict[str, Dict[str, Any]] = {}
    if manifest_ok:
        for row in manifest_rows:
            test_id = row["test_id"]
            suite = row["suite"]
            script = row["script"]
            expected_status = row["expected_status"]
            status, message, duration_ms, _ = _run_test_script(workspace, script)
            actual_status = status if status in {"pass", "fail"} else "error"
            baseline_status = baseline_map.get(test_id, None)
            matches_expected = (expected_status == actual_status)
            change = _compute_change(baseline_status, actual_status)
            recomputed[test_id] = {
                "suite": suite,
                "test_id": test_id,
                "script": script,
                "actual_status": actual_status,
                "expected_status": expected_status,
                "matches_expected": matches_expected,
                "baseline_status": baseline_status if baseline_status is not None else None,
                "change": change,
                "message": message if isinstance(message, str) else "",
                "duration_ms": duration_ms,
            }

    # Validate out/run_results.json
    out_run_results_path = workspace / "out" / "run_results.json"
    run_results_raw = _safe_load_json(out_run_results_path)
    if run_results_raw is not None:
        scores["run_results_present"] = 1.0

    coverage_ok = False
    schema_ok = False
    content_ok = False

    expected_test_ids = set([r["test_id"] for r in manifest_rows]) if manifest_ok else set()

    if isinstance(run_results_raw, list) and all(isinstance(x, dict) for x in run_results_raw):
        seen_ids = set()
        rr_map: Dict[str, Dict[str, Any]] = {}
        for item in run_results_raw:
            tid = item.get("test_id")
            if isinstance(tid, str):
                rr_map[tid] = item
                seen_ids.add(tid)
        if manifest_ok and len(run_results_raw) == len(expected_test_ids) and seen_ids == expected_test_ids:
            coverage_ok = True

        required_fields = {
            "suite": str,
            "test_id": str,
            "script": str,
            "actual_status": str,
            "expected_status": str,
            "matches_expected": bool,
            "change": str,
            "message": str,
        }
        allowed_changes = {"regression", "fix", "no_change"}
        allowed_statuses = {"pass", "fail", "error"}
        schema_all_good = True
        for tid in expected_test_ids:
            item = rr_map.get(tid)
            if item is None:
                schema_all_good = False
                break
            for k, t in required_fields.items():
                if k not in item:
                    schema_all_good = False
                    break
                if k == "matches_expected":
                    if not isinstance(item[k], bool):
                        schema_all_good = False
                        break
                else:
                    if not isinstance(item[k], t):
                        schema_all_good = False
                        break
            if not schema_all_good:
                break
            if item.get("actual_status") not in allowed_statuses:
                schema_all_good = False
                break
            if "baseline_status" not in item:
                schema_all_good = False
                break
            if item["baseline_status"] is not None and not isinstance(item["baseline_status"], str):
                schema_all_good = False
                break
            if item.get("change") not in allowed_changes:
                schema_all_good = False
                break
            if "duration_ms" not in item:
                schema_all_good = False
                break
            if not isinstance(item["duration_ms"], (int, float)):
                schema_all_good = False
                break
        schema_ok = schema_all_good

        if manifest_ok:
            content_good = True
            for tid, truth in recomputed.items():
                item = rr_map.get(tid)
                if item is None:
                    content_good = False
                    break
                if item.get("suite") != truth["suite"]:
                    content_good = False
                    break
                if item.get("script") != truth["script"]:
                    content_good = False
                    break
                if item.get("expected_status") != truth["expected_status"]:
                    content_good = False
                    break
                if item.get("actual_status") != truth["actual_status"]:
                    content_good = False
                    break
                if item.get("baseline_status", None) != truth["baseline_status"]:
                    content_good = False
                    break
                if item.get("matches_expected") is not truth["matches_expected"]:
                    content_good = False
                    break
                if item.get("change") != truth["change"]:
                    content_good = False
                    break
                if item.get("message") != truth["message"]:
                    content_good = False
                    break
                try:
                    if float(item.get("duration_ms")) != float(truth["duration_ms"]):
                        content_good = False
                        break
                except Exception:
                    content_good = False
                    break
            content_ok = content_good

    scores["run_results_cover_all_tests"] = 1.0 if coverage_ok else 0.0
    scores["run_results_schema_valid"] = 1.0 if schema_ok else 0.0
    scores["run_results_content_correct"] = 1.0 if content_ok else 0.0

    # Validate out/summary.md
    summary_path = workspace / "out" / "summary.md"
    summary_text = _safe_read_text(summary_path)
    if summary_text is not None:
        scores["summary_present"] = 1.0

        total_num, passed_num, failed_num = _parse_summary_numbers(summary_text)
        if manifest_ok:
            total_truth = len(manifest_rows)
            passed_truth = sum(1 for v in recomputed.values() if v["actual_status"] == "pass")
            failed_truth = total_truth - passed_truth
            overview_ok = (total_num == total_truth and passed_num == passed_truth and failed_num == failed_truth)
        else:
            overview_ok = False
        scores["summary_overview_matches"] = 1.0 if overview_ok else 0.0

        mismatches = [tid for tid, v in recomputed.items() if not v["matches_expected"]] if manifest_ok else []
        eva_ok = True
        for tid in mismatches:
            v = recomputed[tid]
            found = False
            for line in summary_text.splitlines():
                if (tid in line) and (v["expected_status"] in line) and (v["actual_status"] in line):
                    found = True
                    break
            if not found:
                eva_ok = False
                break
        scores["summary_expected_vs_actual_lists_mismatches"] = 1.0 if eva_ok else 0.0

        bullets = _extract_bullet_lines(summary_text)
        changes_ok = True
        if manifest_ok:
            regressions = [tid for tid, v in recomputed.items()
                           if v["baseline_status"] == "pass" and v["actual_status"] in {"fail", "error"}]
            fixes = [tid for tid, v in recomputed.items()
                     if v["baseline_status"] == "fail" and v["actual_status"] == "pass"]
            for tid in regressions:
                if not any(tid in b for b in bullets):
                    changes_ok = False
                    break
            if changes_ok:
                for tid in fixes:
                    if not any(tid in b for b in bullets):
                        changes_ok = False
                        break
        else:
            changes_ok = False
        scores["summary_changes_vs_baseline_lists"] = 1.0 if changes_ok else 0.0

        repro_ok = True
        if manifest_ok:
            for row in manifest_rows:
                script = row["script"]
                pattern = re.compile(rf"\bpython(?:\d+(?:\.\d+)*)?\s+{re.escape(script)}\b")
                if not any(pattern.search(line) for line in summary_text.splitlines()):
                    repro_ok = False
                    break
        else:
            repro_ok = False
        scores["summary_reproduction_commands_listed"] = 1.0 if repro_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()