import sys
import json
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _parse_simple_yaml_jobs(path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    jobs_started = False
    jobs: Dict[str, Dict[str, Any]] = {}
    current: Dict[str, Any] = {}

    def _commit_current():
        nonlocal current
        if current:
            jid = current.get("job_id")
            if isinstance(jid, str):
                def _to_int(v):
                    try:
                        return int(str(v).strip())
                    except Exception:
                        return None

                def _to_float(v):
                    try:
                        return float(str(v).strip())
                    except Exception:
                        return None

                if "expected_duration_sec" in current:
                    current["expected_duration_sec"] = _to_int(current["expected_duration_sec"])
                if "max_retries_allowed" in current:
                    current["max_retries_allowed"] = _to_int(current["max_retries_allowed"])
                if "sla_minutes" in current:
                    current["sla_minutes"] = _to_int(current["sla_minutes"])
                if "min_success_rate" in current:
                    current["min_success_rate"] = _to_float(current["min_success_rate"])
                for k, v in list(current.items()):
                    if isinstance(v, str):
                        vv = v.strip()
                        if (vv.startswith('"') and vv.endswith('"')) or (vv.startswith("'") and vv.endswith("'")):
                            vv = vv[1:-1]
                        current[k] = vv
                jobs[jid] = current
        current = {}

    for raw in lines:
        line = raw.rstrip("\n")
        if not jobs_started:
            if line.strip() == "jobs:":
                jobs_started = True
            continue
        if line.strip().startswith("- "):
            _commit_current()
            after_dash = line.strip()[2:].strip()
            if after_dash:
                if ":" in after_dash:
                    k, v = after_dash.split(":", 1)
                    current[k.strip()] = v.strip()
            continue
        if line.strip() == "":
            continue
        if line.startswith("  "):
            stripped = line.strip()
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                current[k.strip()] = v.strip()
            continue
        else:
            break
    _commit_current()
    return jobs


def _parse_iso_date(date_time_str: str) -> Optional[str]:
    try:
        return date_time_str[:10]
    except Exception:
        return None


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _numbers_close(a: float, b: float) -> bool:
    tol = max(0.01 * abs(a), 0.1)
    return abs(a - b) <= tol


def _extract_numbers(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r"[-+]?\d+(?:\.\d+)?", text):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            pass
    return nums


def _compute_expected(workspace: Path) -> Tuple[Optional[List[Dict[str, Any]]],
                                               Optional[Dict[str, Dict[str, Any]]],
                                               Optional[Dict[str, Any]]]:
    runs_path = workspace / "input" / "runs.csv"
    cfg_path = workspace / "input" / "pipeline_config.yaml"
    runs_rows = _safe_read_csv_dicts(runs_path)
    jobs_cfg = _parse_simple_yaml_jobs(cfg_path)
    if runs_rows is None or jobs_cfg is None:
        return None, None, None

    parsed_runs: List[Dict[str, Any]] = []
    for r in runs_rows:
        try:
            run_id = r.get("run_id", "")
            job_id = r.get("job_id", "")
            run_ts = r.get("run_ts", "")
            status = r.get("status", "")
            duration = int(r.get("duration_sec", "0"))
            retries = int(r.get("retries", "0"))
            qlat = int(r.get("queued_latency_sec", "0"))
            date = _parse_iso_date(run_ts)
            if date is None:
                continue
            parsed_runs.append({
                "run_id": run_id,
                "job_id": job_id,
                "run_ts": run_ts,
                "status": status,
                "duration_sec": duration,
                "retries": retries,
                "queued_latency_sec": qlat,
                "date": date
            })
        except Exception:
            return None, None, None

    metrics_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    run_ids_by_key: Dict[Tuple[str, str], List[str]] = {}
    for r in parsed_runs:
        key = (r["date"], r["job_id"])
        m = metrics_by_key.setdefault(key, {
            "date": r["date"],
            "job_id": r["job_id"],
            "total_runs": 0,
            "success_runs": 0,
            "fail_runs": 0,
            "sum_duration": 0.0,
            "sum_queue": 0.0,
            "max_retries": 0
        })
        m["total_runs"] += 1
        if str(r["status"]).lower() == "success":
            m["success_runs"] += 1
        else:
            m["fail_runs"] += 1
        m["sum_duration"] += float(r["duration_sec"])
        m["sum_queue"] += float(r["queued_latency_sec"])
        if int(r["retries"]) > m["max_retries"]:
            m["max_retries"] = int(r["retries"])
        run_ids_by_key.setdefault(key, []).append(r["run_id"])

    for key, m in list(metrics_by_key.items()):
        total = m["total_runs"]
        m["success_rate"] = (m["success_runs"] / total) if total > 0 else 0.0
        m["avg_duration_sec"] = (m["sum_duration"] / total) if total > 0 else 0.0
        m["avg_queue_latency_sec"] = (m["sum_queue"] / total) if total > 0 else 0.0
        job_id = key[1]
        owner = None
        if jobs_cfg and job_id in jobs_cfg and "owner" in jobs_cfg[job_id]:
            owner = jobs_cfg[job_id]["owner"]
        m["owner"] = owner

    anomalies: List[Dict[str, Any]] = []
    for (date, job_id), m in metrics_by_key.items():
        if job_id not in jobs_cfg:
            continue
        cfg = jobs_cfg[job_id]
        owner = cfg.get("owner")
        min_sr = cfg.get("min_success_rate")
        if min_sr is None:
            min_sr = 0.98
        if m["success_rate"] < float(min_sr):
            anomalies.append({
                "date": date,
                "job_id": job_id,
                "owner": owner,
                "category": "success_rate",
                "observed": m["success_rate"],
                "threshold": float(min_sr),
                "sample_key": (date, job_id),
            })
        exp_dur = cfg.get("expected_duration_sec")
        if isinstance(exp_dur, int):
            dur_thresh = exp_dur * 1.25
            if m["avg_duration_sec"] > dur_thresh:
                anomalies.append({
                    "date": date,
                    "job_id": job_id,
                    "owner": owner,
                    "category": "duration",
                    "observed": m["avg_duration_sec"],
                    "threshold": dur_thresh,
                    "sample_key": (date, job_id),
                })
        max_ret = cfg.get("max_retries_allowed")
        if isinstance(max_ret, int):
            if m["max_retries"] > max_ret:
                anomalies.append({
                    "date": date,
                    "job_id": job_id,
                    "owner": owner,
                    "category": "retries",
                    "observed": m["max_retries"],
                    "threshold": max_ret,
                    "sample_key": (date, job_id),
                })

    jobs_in_runs = {jid for (_, jid) in metrics_by_key.keys()}
    cfg_jobs = set(jobs_cfg.keys())
    unknown_jobs = sorted(list(jobs_in_runs - cfg_jobs))
    unknown_jobs_entries: List[Dict[str, Any]] = []
    for uj in unknown_jobs:
        dates = sorted({date for (date, jid) in metrics_by_key.keys() if jid == uj})
        if dates:
            unknown_jobs_entries.append({"job_id": uj, "first_seen_date": dates[0]})

    configured_missing_entries: List[Dict[str, Any]] = []
    for jid in sorted(cfg_jobs - jobs_in_runs):
        owner = jobs_cfg[jid].get("owner")
        configured_missing_entries.append({"job_id": jid, "owner": owner})

    expected = {
        "metrics_by_key": metrics_by_key,
        "anomalies": anomalies,
        "unknown_jobs": unknown_jobs_entries,
        "configured_jobs_missing": configured_missing_entries,
        "run_ids_by_key": run_ids_by_key,
        "jobs_cfg": jobs_cfg,
    }
    return parsed_runs, jobs_cfg, expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "metrics_file_exists_and_parsable": 0.0,
        "metrics_row_count_and_keys_match": 0.0,
        "metrics_values_correct": 0.0,
        "anomalies_file_exists_and_parsable": 0.0,
        "anomalies_rules_covered": 0.0,
        "anomalies_sample_ids_valid": 0.0,
        "config_mismatches_exists_and_parsable": 0.0,
        "config_mismatches_content_correct": 0.0,
        "email_subject_and_recipients_present": 0.0,
        "email_references_artifacts": 0.0,
        "email_summarizes_anomalies_and_mismatches_and_length": 0.0,
    }

    runs, jobs_cfg, expected = _compute_expected(workspace)
    if runs is None or jobs_cfg is None or expected is None:
        return scores

    metrics_path = workspace / "output" / "metrics" / "daily_job_metrics.csv"
    metrics_rows = None
    if metrics_path.exists():
        metrics_rows = _safe_read_csv_dicts(metrics_path)
    if metrics_rows is not None:
        expected_columns = [
            "date",
            "job_id",
            "owner",
            "total_runs",
            "success_runs",
            "fail_runs",
            "success_rate",
            "avg_duration_sec",
            "max_retries_observed",
            "avg_queue_latency_sec",
        ]
        try:
            with metrics_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None
        if header == expected_columns:
            scores["metrics_file_exists_and_parsable"] = 1.0
        else:
            scores["metrics_file_exists_and_parsable"] = 0.0
    else:
        scores["metrics_file_exists_and_parsable"] = 0.0

    if scores["metrics_file_exists_and_parsable"] == 1.0 and metrics_rows is not None:
        keys_user = set()
        user_by_key = {}
        valid_parse = True
        for r in metrics_rows:
            try:
                date = r.get("date", "")
                job_id = r.get("job_id", "")
                key = (date, job_id)
                keys_user.add(key)
                user_by_key[key] = r
            except Exception:
                valid_parse = False
                break
        keys_expected = set(expected["metrics_by_key"].keys())
        if valid_parse and keys_user == keys_expected:
            scores["metrics_row_count_and_keys_match"] = 1.0
        else:
            scores["metrics_row_count_and_keys_match"] = 0.0

        all_ok = True
        for key, exp_m in expected["metrics_by_key"].items():
            if key not in user_by_key:
                all_ok = False
                continue
            r = user_by_key[key]
            if exp_m["owner"] is not None:
                if r.get("owner") != exp_m["owner"]:
                    all_ok = False

            def _to_int(s):
                try:
                    return int(float(str(s)))
                except Exception:
                    return None

            def _to_float(s):
                try:
                    return float(str(s))
                except Exception:
                    return None

            tr = _to_int(r.get("total_runs"))
            sr = _to_int(r.get("success_runs"))
            fr = _to_int(r.get("fail_runs"))
            sr_rate = _to_float(r.get("success_rate"))
            avg_dur = _to_float(r.get("avg_duration_sec"))
            max_ret = _to_int(r.get("max_retries_observed"))
            avg_q = _to_float(r.get("avg_queue_latency_sec"))
            if None in [tr, sr, fr, sr_rate, avg_dur, max_ret, avg_q]:
                all_ok = False
                continue
            if tr != exp_m["total_runs"]:
                all_ok = False
            if sr != exp_m["success_runs"]:
                all_ok = False
            if fr != exp_m["fail_runs"]:
                all_ok = False
            if not _float_equal(sr_rate, exp_m["success_rate"]):
                all_ok = False
            if not _float_equal(avg_dur, exp_m["avg_duration_sec"]):
                all_ok = False
            if max_ret != exp_m["max_retries"]:
                all_ok = False
            if not _float_equal(avg_q, exp_m["avg_queue_latency_sec"]):
                all_ok = False
        scores["metrics_values_correct"] = 1.0 if all_ok else 0.0

    anomalies_path = workspace / "output" / "qa" / "anomalies.json"
    anomalies_data = None
    if anomalies_path.exists():
        anomalies_data = _safe_load_json(anomalies_path)
    if isinstance(anomalies_data, list):
        scores["anomalies_file_exists_and_parsable"] = 1.0
    else:
        scores["anomalies_file_exists_and_parsable"] = 0.0

    if scores["anomalies_file_exists_and_parsable"] == 1.0:
        expected_anoms = expected["anomalies"]
        index_user: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        valid_structure = True
        for item in anomalies_data:
            try:
                date = item.get("date")
                job_id = item.get("job_id")
                rule_str = str(item.get("rule", "")).lower()
                if "success_rate" in rule_str:
                    cat = "success_rate"
                elif "duration" in rule_str:
                    cat = "duration"
                elif "retries" in rule_str:
                    cat = "retries"
                else:
                    cat = None
                if not (isinstance(date, str) and isinstance(job_id, str) and cat):
                    valid_structure = False
                    break
                index_user[(date, job_id, cat)] = item
            except Exception:
                valid_structure = False
                break
        ok_rules = True
        if not valid_structure:
            ok_rules = False
        else:
            if len(index_user) != len(expected_anoms):
                ok_rules = False
            else:
                for exp in expected_anoms:
                    key = (exp["date"], exp["job_id"], exp["category"])
                    if key not in index_user:
                        ok_rules = False
                        break
                    u = index_user[key]
                    if u.get("owner") != exp.get("owner"):
                        ok_rules = False
                        break
                    u_obs = u.get("observed")
                    u_thr = u.get("threshold")
                    try:
                        u_obs_f = float(u_obs)
                        u_thr_f = float(u_thr)
                    except Exception:
                        ok_rules = False
                        break
                    if not _numbers_close(u_obs_f, float(exp["observed"])):
                        ok_rules = False
                        break
                    if not _numbers_close(u_thr_f, float(exp["threshold"])):
                        ok_rules = False
                        break
        scores["anomalies_rules_covered"] = 1.0 if ok_rules else 0.0

        samples_ok = True
        if ok_rules:
            for exp in expected_anoms:
                key = (exp["date"], exp["job_id"], exp["category"])
                u = index_user.get(key)
                if u is None:
                    samples_ok = False
                    break
                sample_ids = u.get("sample_run_ids")
                if not isinstance(sample_ids, list) or len(sample_ids) == 0:
                    samples_ok = False
                    break
                key_runs = expected["run_ids_by_key"].get((exp["date"], exp["job_id"]), [])
                key_runs_set = set(key_runs)
                for rid in sample_ids:
                    if not isinstance(rid, str) or rid not in key_runs_set:
                        samples_ok = False
                        break
                if not samples_ok:
                    break
        else:
            samples_ok = False
        scores["anomalies_sample_ids_valid"] = 1.0 if samples_ok else 0.0

    cfg_mismatch_path = workspace / "output" / "qa" / "config_mismatches.json"
    cfg_mismatch = None
    if cfg_mismatch_path.exists():
        cfg_mismatch = _safe_load_json(cfg_mismatch_path)
    if isinstance(cfg_mismatch, dict):
        if isinstance(cfg_mismatch.get("unknown_jobs_in_runs"), list) and isinstance(cfg_mismatch.get("configured_jobs_missing_in_runs"), list):
            scores["config_mismatches_exists_and_parsable"] = 1.0
        else:
            scores["config_mismatches_exists_and_parsable"] = 0.0
    else:
        scores["config_mismatches_exists_and_parsable"] = 0.0

    if scores["config_mismatches_exists_and_parsable"] == 1.0:
        def _normalize_unknown(lst: List[Dict[str, Any]]) -> set:
            s = set()
            for e in lst:
                jid = e.get("job_id")
                fsd = e.get("first_seen_date")
                if isinstance(jid, str) and isinstance(fsd, str):
                    s.add((jid, fsd))
            return s

        def _normalize_missing(lst: List[Dict[str, Any]]) -> set:
            s = set()
            for e in lst:
                jid = e.get("job_id")
                owner = e.get("owner")
                if isinstance(jid, str) and isinstance(owner, str):
                    s.add((jid, owner))
            return s

        user_unknown = _normalize_unknown(cfg_mismatch.get("unknown_jobs_in_runs", []))
        user_missing = _normalize_missing(cfg_mismatch.get("configured_jobs_missing_in_runs", []))

        exp_unknown = _normalize_unknown(expected["unknown_jobs"])
        exp_missing = _normalize_missing(expected["configured_jobs_missing"])
        if user_unknown == exp_unknown and user_missing == exp_missing:
            scores["config_mismatches_content_correct"] = 1.0
        else:
            scores["config_mismatches_content_correct"] = 0.0

    email_path = workspace / "output" / "email" / "ops_summary_email.txt"
    email_text = None
    if email_path.exists():
        email_text = _safe_read_text(email_path)

    if isinstance(email_text, str):
        subj_phrase = "Weekly pipeline QA summary (based on input/runs.csv)"
        has_recipients = ("ops@company.example" in email_text) and ("data-eng@company.example" in email_text)
        has_subject = (subj_phrase in email_text)
        scores["email_subject_and_recipients_present"] = 1.0 if (has_recipients and has_subject) else 0.0

        has_metrics_ref = "output/metrics/daily_job_metrics.csv" in email_text
        has_anomalies_ref = "output/qa/anomalies.json" in email_text
        scores["email_references_artifacts"] = 1.0 if (has_metrics_ref and has_anomalies_ref) else 0.0

        words = email_text.split()
        within_length = len(words) <= 200

        lines = email_text.splitlines()
        bullet_lines = [ln for ln in lines if ln.strip().startswith(("-", "*", "•"))]
        expected_anoms = expected["anomalies"]
        found_all_anoms = True
        for exp in expected_anoms:
            obs = float(exp["observed"])
            thr = float(exp["threshold"])
            job_id = exp["job_id"]
            date = exp["date"]
            matched = False
            for bl in bullet_lines:
                if job_id in bl and date in bl:
                    nums = _extract_numbers(bl)
                    has_obs = any(_numbers_close(n, obs) for n in nums)
                    has_thr = any(_numbers_close(n, thr) for n in nums)
                    if has_obs and has_thr:
                        matched = True
                        break
            if not matched:
                found_all_anoms = False
                break

        mentions_unknown = any("ad_hoc_cleanup" in ln for ln in lines)
        mentions_missing = any("rebuild_features" in ln for ln in lines)

        if within_length and found_all_anoms and mentions_unknown and mentions_missing:
            scores["email_summarizes_anomalies_and_mismatches_and_length"] = 1.0
        else:
            scores["email_summarizes_anomalies_and_mismatches_and_length"] = 0.0
    else:
        scores["email_subject_and_recipients_present"] = 0.0
        scores["email_references_artifacts"] = 0.0
        scores["email_summarizes_anomalies_and_mismatches_and_length"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()