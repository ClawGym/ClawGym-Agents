import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Any]:
    try:
        text = read_text_safe(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def parse_jsonl_safe(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        items: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def parse_simple_yaml_schedule(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal parser for the provided simple YAML format with three top-level keys.
    Expects lines like:
      iterations: 5
      interval_seconds: 1
      command_template: "python input/sim_job.py --run-id {i}"
    """
    text = read_text_safe(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comments not inside quotes (best-effort)
        # For simplicity here, we will not attempt to preserve quoted '#'
        if "#" in line:
            hash_index = line.find("#")
            line = line[:hash_index].rstrip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove surrounding quotes if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        # Cast known fields
        if key == "iterations":
            try:
                data[key] = int(val)
            except Exception:
                return None
        elif key == "interval_seconds":
            try:
                if "." in val:
                    data[key] = float(val)
                else:
                    data[key] = int(val)
            except Exception:
                return None
        elif key == "command_template":
            data[key] = val
        else:
            # Ignore unknown keys
            data[key] = val
    # Ensure required keys exist
    for req in ("iterations", "interval_seconds", "command_template"):
        if req not in data:
            return None
    return data


def slugify_error_type(s: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    return slug


def normalize_domain(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return None


def floats_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def compute_expected_success(run_id: int) -> bool:
    return (run_id % 2) == 1


def compute_expected_metrics(run_id: int) -> Tuple[float, float]:
    # Matches input/sim_job.py
    acc = round(0.72 + (run_id % 7) * 0.02, 3)
    loss = round(1.0 / (run_id % 4 + 1), 3)
    return acc, loss


def compute_expected_error_type(run_id: int) -> str:
    err_case = run_id % 3
    if err_case == 0:
        return "ZeroDivisionError"
    elif err_case == 1:
        return "KeyError"
    else:
        return "ValueError"


def safe_get_number(d: Dict[str, Any], key: str) -> Optional[float]:
    val = d.get(key, None)
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(val)  # attempt coercion from string
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "runner_script_exists": 0.0,
        "run_events_jsonl_present_and_valid": 0.0,
        "run_events_run_ids_and_statuses_correct": 0.0,
        "run_events_metrics_correct_on_success": 0.0,
        "run_events_error_types_correct": 0.0,
        "summary_json_present_and_valid": 0.0,
        "summary_totals_consistent_with_logs": 0.0,
        "summary_duration_stats_consistent": 0.0,
        "summary_success_metrics_means_correct": 0.0,
        "error_lookups_present_and_valid": 0.0,
    }

    # Check script existence
    runner_path = workspace / "scripts" / "scheduled_runner.py"
    if runner_path.is_file():
        scores["runner_script_exists"] = 1.0

    # Parse schedule.yaml for expected iterations
    schedule_path = workspace / "input" / "schedule.yaml"
    schedule = parse_simple_yaml_schedule(schedule_path) if schedule_path.exists() else None
    expected_iterations: Optional[int] = None
    if schedule and isinstance(schedule.get("iterations"), int):
        expected_iterations = schedule["iterations"]

    # Load run events jsonl
    events_path = workspace / "out" / "logs" / "run_events.jsonl"
    events = parse_jsonl_safe(events_path) if events_path.exists() else None
    if events is None:
        # leave related scores as 0.0
        return scores if (workspace_path and False) else scores  # no-op return
    else:
        # Validate structure of each event
        valid_events = True
        for e in events:
            # Required fields per spec
            required_keys = ["run_id", "start_ts", "end_ts", "duration_ms", "exit_code", "status", "parsed_metrics", "error_type", "stderr_tail"]
            if not all(k in e for k in required_keys):
                valid_events = False
                break
            # Types and basic constraints
            if not isinstance(e["run_id"], int):
                valid_events = False
                break
            if safe_get_number(e, "start_ts") is None or safe_get_number(e, "end_ts") is None or safe_get_number(e, "duration_ms") is None:
                valid_events = False
                break
            if not isinstance(e.get("exit_code"), int):
                valid_events = False
                break
            if e.get("status") not in ("ok", "error"):
                valid_events = False
                break
            if "stderr_tail" not in e or not isinstance(e.get("stderr_tail", ""), (str, type(None))):
                valid_events = False
                break
            # parsed_metrics can be None or dict
            pm = e.get("parsed_metrics")
            if pm is not None and not isinstance(pm, dict):
                valid_events = False
                break
            # error_type can be None or str
            et = e.get("error_type")
            if et is not None and not isinstance(et, str):
                valid_events = False
                break
            # time constraints
            st = safe_get_number(e, "start_ts")
            en = safe_get_number(e, "end_ts")
            dur = safe_get_number(e, "duration_ms")
            if st is None or en is None or dur is None:
                valid_events = False
                break
            if en < st or dur < 0:
                valid_events = False
                break
        if valid_events:
            scores["run_events_jsonl_present_and_valid"] = 1.0

    # Run IDs and statuses correctness
    run_ids_ok = False
    statuses_ok = True
    if expected_iterations is not None:
        expected_set = set(range(1, expected_iterations + 1))
        got_set = set(e["run_id"] for e in events)
        if got_set == expected_set and len(events) == expected_iterations:
            run_ids_ok = True
        else:
            run_ids_ok = False
    else:
        run_ids_ok = False

    for e in events:
        exit_code = e.get("exit_code")
        status = e.get("status")
        if (exit_code == 0 and status != "ok") or (exit_code != 0 and status != "error"):
            statuses_ok = False
            break

    if run_ids_ok and statuses_ok:
        # Also check that success/failure matches sim_job behavior if schedule known
        if expected_iterations is not None:
            behavior_ok = True
            for e in events:
                rid = e["run_id"]
                expected_success = compute_expected_success(rid)
                if expected_success and not (e["status"] == "ok" and e["exit_code"] == 0):
                    behavior_ok = False
                    break
                if (not expected_success) and not (e["status"] == "error" and e["exit_code"] != 0):
                    behavior_ok = False
                    break
            if behavior_ok:
                scores["run_events_run_ids_and_statuses_correct"] = 1.0
        else:
            # Without schedule, we cannot assert mapping to sim_job
            scores["run_events_run_ids_and_statuses_correct"] = 0.0

    # Metrics correctness on success
    metrics_ok = True
    if expected_iterations is not None:
        for e in events:
            rid = e["run_id"]
            if compute_expected_success(rid):
                pm = e.get("parsed_metrics")
                if not isinstance(pm, dict):
                    metrics_ok = False
                    break
                acc = pm.get("accuracy")
                loss = pm.get("loss")
                try:
                    acc_val = float(acc)
                    loss_val = float(loss)
                except Exception:
                    metrics_ok = False
                    break
                exp_acc, exp_loss = compute_expected_metrics(rid)
                if not (floats_equal(acc_val, exp_acc) and floats_equal(loss_val, exp_loss)):
                    metrics_ok = False
                    break
        if metrics_ok:
            scores["run_events_metrics_correct_on_success"] = 1.0

    # Error types correctness
    error_types_ok = True
    if expected_iterations is not None:
        for e in events:
            rid = e["run_id"]
            if not compute_expected_success(rid):
                exp_err = compute_expected_error_type(rid)
                et = e.get("error_type")
                # Must match expected error type
                if et != exp_err:
                    error_types_ok = False
                    break
                # stderr_tail should be non-empty for failures
                stderr_tail = e.get("stderr_tail")
                if not isinstance(stderr_tail, str) or stderr_tail.strip() == "":
                    error_types_ok = False
                    break
            else:
                # For successes, error_type should be None or empty string
                et = e.get("error_type")
                if et not in (None, ""):
                    error_types_ok = False
                    break
        if error_types_ok:
            scores["run_events_error_types_correct"] = 1.0

    # Summary JSON
    summary_path = workspace / "out" / "reports" / "summary.json"
    summary = load_json_safe(summary_path) if summary_path.exists() else None
    if isinstance(summary, dict):
        fields_ok = True
        # Required top-level fields
        req_top = ["total_runs", "success_count", "failure_count", "success_rate", "duration_ms", "metrics_on_success", "failures_by_error_type"]
        if not all(k in summary for k in req_top):
            fields_ok = False
        # Types and constraints
        if not isinstance(summary.get("total_runs"), int):
            fields_ok = False
        if not isinstance(summary.get("success_count"), int):
            fields_ok = False
        if not isinstance(summary.get("failure_count"), int):
            fields_ok = False
        sr = summary.get("success_rate")
        if not isinstance(sr, (int, float)) or not (0.0 <= float(sr) <= 1.0):
            fields_ok = False
        dur = summary.get("duration_ms")
        if not isinstance(dur, dict) or not all(k in dur for k in ("min", "max", "mean")):
            fields_ok = False
        else:
            if not all(isinstance(dur.get(k), (int, float)) for k in ("min", "max", "mean")):
                fields_ok = False
        mos = summary.get("metrics_on_success")
        if not isinstance(mos, dict) or not all(k in mos for k in ("accuracy_mean", "loss_mean")):
            fields_ok = False
        else:
            if not all(isinstance(mos.get(k), (int, float)) for k in ("accuracy_mean", "loss_mean")):
                fields_ok = False
        fbet = summary.get("failures_by_error_type")
        if not isinstance(fbet, dict):
            fields_ok = False
        if fields_ok:
            # Basic count consistency
            total_runs = summary["total_runs"]
            sc = summary["success_count"]
            fc = summary["failure_count"]
            try:
                sr_val = float(summary["success_rate"])
            except Exception:
                fields_ok = False
            else:
                if total_runs != sc + fc:
                    fields_ok = False
                else:
                    if total_runs > 0:
                        if not floats_equal(sr_val, sc / total_runs):
                            fields_ok = False
            if fields_ok:
                scores["summary_json_present_and_valid"] = 1.0

    # Summary totals consistent with logs
    if isinstance(summary, dict):
        try:
            total_runs_s = int(summary.get("total_runs"))
            success_count_s = int(summary.get("success_count"))
            failure_count_s = int(summary.get("failure_count"))
            # From logs
            total_runs_l = len(events)
            success_count_l = sum(1 for e in events if e.get("status") == "ok")
            failure_count_l = sum(1 for e in events if e.get("status") == "error")
            fbet_s = summary.get("failures_by_error_type", {})
            # Build from logs
            fbet_l: Dict[str, int] = {}
            for e in events:
                if e.get("status") == "error":
                    et = e.get("error_type")
                    if isinstance(et, str):
                        fbet_l[et] = fbet_l.get(et, 0) + 1
            totals_ok = (total_runs_s == total_runs_l and success_count_s == success_count_l and failure_count_s == failure_count_l)
            fbet_ok = True
            # Compare failure mapping exactly
            if isinstance(fbet_s, dict):
                # Remove entries with zero
                fbet_s_nonzero = {k: int(v) for k, v in fbet_s.items() if isinstance(v, int) and v != 0}
                fbet_ok = fbet_s_nonzero == fbet_l
            else:
                fbet_ok = False
            if totals_ok and fbet_ok:
                scores["summary_totals_consistent_with_logs"] = 1.0
        except Exception:
            pass

    # Summary duration stats consistent with logs
    if isinstance(summary, dict) and len(events) > 0:
        try:
            durs = [float(e.get("duration_ms")) for e in events if isinstance(e.get("duration_ms"), (int, float)) or isinstance(e.get("duration_ms"), str)]
            durs = [float(x) for x in durs]
            min_l = min(durs)
            max_l = max(durs)
            mean_l = sum(durs) / len(durs)
            dur_s = summary.get("duration_ms", {})
            if isinstance(dur_s, dict):
                min_s = float(dur_s.get("min"))
                max_s = float(dur_s.get("max"))
                mean_s = float(dur_s.get("mean"))
                if floats_equal(min_l, min_s) and floats_equal(max_l, max_s) and floats_equal(mean_l, mean_s):
                    scores["summary_duration_stats_consistent"] = 1.0
        except Exception:
            pass

    # Summary success metrics means correct
    if isinstance(summary, dict):
        try:
            mos = summary.get("metrics_on_success", {})
            if isinstance(mos, dict):
                acc_mean_s = float(mos.get("accuracy_mean"))
                loss_mean_s = float(mos.get("loss_mean"))
                # Derive from logs only on successes
                accs: List[float] = []
                losses: List[float] = []
                for e in events:
                    if e.get("status") == "ok":
                        pm = e.get("parsed_metrics")
                        if isinstance(pm, dict) and ("accuracy" in pm and "loss" in pm):
                            accs.append(float(pm["accuracy"]))
                            losses.append(float(pm["loss"]))
                if len(accs) > 0 and len(losses) > 0:
                    acc_mean_l = sum(accs) / len(accs)
                    loss_mean_l = sum(losses) / len(losses)
                    if floats_equal(acc_mean_l, acc_mean_s) and floats_equal(loss_mean_l, loss_mean_s):
                        scores["summary_success_metrics_means_correct"] = 1.0
        except Exception:
            pass

    # Error lookups presence and validity
    error_types: List[str] = []
    for e in events:
        if e.get("status") == "error":
            et = e.get("error_type")
            if isinstance(et, str):
                error_types.append(et)
    distinct_error_types = sorted(set(error_types))
    all_lookups_ok = True
    for et in distinct_error_types:
        slug = slugify_error_type(et)
        lookup_path = workspace / "out" / "error_lookups" / f"{slug}.json"
        lookup = load_json_safe(lookup_path) if lookup_path.exists() else None
        if not isinstance(lookup, dict):
            all_lookups_ok = False
            break
        # Required fields: timestamp, query, engine_name, results (list up to 5), domain_counts (mapping)
        if "timestamp" not in lookup or "query" not in lookup or "engine_name" not in lookup or "results" not in lookup or "domain_counts" not in lookup:
            all_lookups_ok = False
            break
        if not isinstance(lookup.get("query"), str) or lookup.get("query").strip() == "":
            all_lookups_ok = False
            break
        if not isinstance(lookup.get("engine_name"), str) or lookup.get("engine_name").strip() == "":
            all_lookups_ok = False
            break
        results = lookup.get("results")
        if not isinstance(results, list):
            all_lookups_ok = False
            break
        if len(results) > 5:
            all_lookups_ok = False
            break
        for r in results:
            if not isinstance(r, dict) or "title" not in r or "url" not in r:
                all_lookups_ok = False
                break
            if not isinstance(r.get("title"), str) or not isinstance(r.get("url"), str):
                all_lookups_ok = False
                break
        if not all_lookups_ok:
            break
        # Domain counts correctness
        domains_from_results: Dict[str, int] = {}
        for r in results:
            dom = normalize_domain(r.get("url", ""))
            if dom is None or dom == "":
                continue
            domains_from_results[dom] = domains_from_results.get(dom, 0) + 1
        provided_dc = lookup.get("domain_counts")
        if not isinstance(provided_dc, dict):
            all_lookups_ok = False
            break
        # Normalize provided domain keys
        provided_dc_norm: Dict[str, int] = {}
        try:
            for k, v in provided_dc.items():
                if not isinstance(v, int):
                    all_lookups_ok = False
                    break
                domk = k.lower()
                if domk.startswith("www."):
                    domk = domk[4:]
                provided_dc_norm[domk] = provided_dc_norm.get(domk, 0) + v
            if not all_lookups_ok:
                break
        except Exception:
            all_lookups_ok = False
            break
        # Compare computed counts: Only require that provided counts match counts derived from results
        if provided_dc_norm != domains_from_results:
            all_lookups_ok = False
            break
        # Validate query format: must contain 'Python' and error type
        q = lookup.get("query", "")
        if not isinstance(q, str):
            all_lookups_ok = False
            break
        if "python" not in q.lower():
            all_lookups_ok = False
            break
        if et.lower() not in q.lower():
            all_lookups_ok = False
            break
        # If KeyError, expect 'missing' token present
        if et == "KeyError":
            if "missing" not in q.lower():
                all_lookups_ok = False
                break
        # If ValueError, expect some informative token from the message
        if et == "ValueError":
            informative_tokens = ["invalid", "shape", "batch", "input"]
            if not any(tok in q.lower() for tok in informative_tokens):
                all_lookups_ok = False
                break

    if distinct_error_types and all_lookups_ok:
        scores["error_lookups_present_and_valid"] = 1.0
    elif not distinct_error_types:
        # If no errors occurred (unexpected for provided sim_job and schedule), do not penalize lookup presence check
        # but according to provided inputs there should be errors; keep as 0.0 if missing
        pass

    return scores


def main() -> None:
    workspace_arg = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace_arg = sys.argv[1]
    result = grade([], workspace_arg)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()