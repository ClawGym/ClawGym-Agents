import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _to_int(val: Any) -> Optional[int]:
    try:
        return int(str(val).strip())
    except Exception:
        return None


def _to_float(val: Any) -> Optional[float]:
    try:
        return float(str(val).strip())
    except Exception:
        return None


def _to_bool(val: Any) -> Optional[bool]:
    s = str(val).strip().lower()
    if s in {"true", "t", "yes", "y", "1"}:
        return True
    if s in {"false", "f", "no", "n", "0"}:
        return False
    return None


def _safe_get(row: Dict[str, str], key: str) -> Optional[str]:
    return row.get(key)


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        # Fallback to equal weights if malformed
        n = len(weights)
        if n == 0:
            return weights
        return {k: 1.0 / n for k in weights}
    return {k: (v / total) for k, v in weights.items()}


def _compute_components_and_flags(candidate: Dict[str, Any], job: Dict[str, Any]) -> Tuple[Dict[str, float], List[str]]:
    flags: List[str] = []
    components: Dict[str, float] = {}

    # Commute
    j_commute = job["commute_minutes"]
    c_commute_max = candidate["max_commute_minutes"]
    if c_commute_max is None or j_commute is None:
        return {}, []  # malformed
    if j_commute > c_commute_max:
        components["commute_component"] = 0.0
        flags.append("commute_exceeds_max")
    else:
        v = max(0.0, 1.0 - (j_commute / c_commute_max) if c_commute_max > 0 else 0.0)
        components["commute_component"] = v

    # Shift
    shift_component = None
    if candidate["hard_no_nights"] is True and job["shift_pattern"] == "rotating":
        shift_component = 0.0
        flags.append("no_nights_constraint")
    else:
        pref = candidate["shift_preference"]
        jshift = job["shift_pattern"]
        if pref == "day":
            if jshift == "day":
                shift_component = 1.0
            elif jshift == "rotating":
                shift_component = 0.6
        elif pref == "rotating":
            if jshift == "rotating":
                shift_component = 1.0
            elif jshift == "day":
                shift_component = 0.8
        elif pref == "any":
            if jshift == "day":
                shift_component = 1.0
            elif jshift == "rotating":
                shift_component = 0.9
    if shift_component is None:
        return {}, []  # malformed or unexpected value
    components["shift_component"] = shift_component

    # Travel
    c_max_travel = candidate["max_travel_nights"]
    j_travel = job["travel_nights_per_month"]
    if c_max_travel is None or j_travel is None:
        return {}, []
    if c_max_travel == 0:
        if j_travel == 0:
            components["travel_component"] = 1.0
        else:
            components["travel_component"] = 0.0
            flags.append("no_travel_preference")
    else:
        components["travel_component"] = max(0.0, 1.0 - (j_travel / c_max_travel))

    # Remote
    c_min_remote = candidate["min_remote_days"]
    j_remote = job["remote_days_per_week"]
    if c_min_remote is None or j_remote is None:
        return {}, []
    if c_min_remote == 0:
        components["remote_component"] = 1.0
    else:
        components["remote_component"] = min(j_remote / c_min_remote, 1.0)

    # Training
    c_max_training = candidate["max_training_hours"]
    j_training = job["training_hours_per_week"]
    if c_max_training is None or j_training is None:
        return {}, []
    if c_max_training == 0:
        if j_training == 0:
            components["training_component"] = 1.0
        else:
            components["training_component"] = 0.0
            flags.append("training_too_high")
    else:
        components["training_component"] = max(0.0, 1.0 - (j_training / c_max_training))

    return components, flags


def _compute_score_and_decision(candidate: Dict[str, Any], job: Dict[str, Any]) -> Optional[Tuple[float, str, List[str]]]:
    components, flags = _compute_components_and_flags(candidate, job)
    if not components:
        return None
    raw_weights = {
        "commute_weight": candidate["commute_weight"],
        "shift_weight": candidate["shift_weight"],
        "travel_weight": candidate["travel_weight"],
        "remote_weight": candidate["remote_weight"],
        "training_weight": candidate["training_weight"],
    }
    if any(v is None for v in raw_weights.values()):
        return None
    norm = _normalize_weights(raw_weights)
    weighted_avg = (
        norm["commute_weight"] * components["commute_component"] +
        norm["shift_weight"] * components["shift_component"] +
        norm["travel_weight"] * components["travel_component"] +
        norm["remote_weight"] * components["remote_component"] +
        norm["training_weight"] * components["training_component"]
    )
    lifestyle_fit_score = round(weighted_avg * 100.0, 1)
    # Decision
    decision = None
    if any(f in {"no_nights_constraint", "commute_exceeds_max"} for f in flags):
        decision = "No-Go"
    else:
        if lifestyle_fit_score >= 75.0:
            decision = "Top Match"
        elif 50.0 <= lifestyle_fit_score < 75.0:
            decision = "Consider"
        else:
            decision = "No-Go"
    return lifestyle_fit_score, decision, flags


def _load_candidates(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    path = workspace / "input" / "candidate_preferences.csv"
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    candidates: List[Dict[str, Any]] = []
    for r in rows:
        try:
            c = {
                "candidate_id": r.get("candidate_id"),
                "candidate_name": r.get("candidate_name"),
                "max_commute_minutes": _to_int(r.get("max_commute_minutes")),
                "commute_weight": _to_float(r.get("commute_weight")),
                "shift_preference": (r.get("shift_preference") or "").strip().lower(),
                "hard_no_nights": _to_bool(r.get("hard_no_nights")),
                "shift_weight": _to_float(r.get("shift_weight")),
                "max_travel_nights": _to_int(r.get("max_travel_nights")),
                "travel_weight": _to_float(r.get("travel_weight")),
                "min_remote_days": _to_int(r.get("min_remote_days")),
                "remote_weight": _to_float(r.get("remote_weight")),
                "max_training_hours": _to_int(r.get("max_training_hours")),
                "training_weight": _to_float(r.get("training_weight")),
                "notes": r.get("notes"),
            }
        except Exception:
            return None
        candidates.append(c)
    return candidates


def _load_jobs(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    path = workspace / "input" / "job_options.csv"
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    jobs: List[Dict[str, Any]] = []
    for r in rows:
        try:
            j = {
                "job_id": r.get("job_id"),
                "role": r.get("role"),
                "location": r.get("location"),
                "commute_minutes": _to_int(r.get("commute_minutes")),
                "shift_pattern": (r.get("shift_pattern") or "").strip().lower(),
                "travel_nights_per_month": _to_int(r.get("travel_nights_per_month")),
                "remote_days_per_week": _to_int(r.get("remote_days_per_week")),
                "training_hours_per_week": _to_int(r.get("training_hours_per_week")),
                "notes": r.get("notes"),
            }
        except Exception:
            return None
        jobs.append(j)
    return jobs


def _read_recommendations(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    path = workspace / "outputs" / "recommendations.csv"
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, None
            f.seek(0)
            dr = csv.DictReader(f)
            rows = [dict(row) for row in dr]
            return rows, header
    except Exception:
        return None, None


def _parse_flags_cell(cell: str) -> List[str]:
    if cell is None:
        return []
    s = str(cell).strip()
    if not s:
        return []
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p]


def _safe_float_from_recs(row: Dict[str, str], key: str) -> Optional[float]:
    try:
        return float(row.get(key))
    except Exception:
        return None


def _find_section(text: str, keyword: str) -> Optional[str]:
    lines = text.splitlines()
    indices = []
    for i, line in enumerate(lines):
        if line.strip().startswith("#") and keyword.lower() in line.lower():
            indices.append(i)
    if not indices:
        return None
    # Take first occurrence; section ends before next heading
    start = indices[0]
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].strip().startswith("#"):
            end = j
            break
    section_text = "\n".join(lines[start:end])
    return section_text


def _count_bullets_in_section(section_text: str) -> int:
    return sum(1 for line in section_text.splitlines() if line.strip().startswith(("-", "*")))


def _top_jobs_for_candidate(recs: List[Dict[str, str]], candidate_id: str) -> List[Tuple[str, float, str, List[str]]]:
    # returns list of (job_id, score, decision, flags)
    items: List[Tuple[str, float, str, List[str]]] = []
    for row in recs:
        if row.get("candidate_id") == candidate_id:
            score = _safe_float_from_recs(row, "lifestyle_fit_score")
            decision = (row.get("decision") or "").strip()
            job_id = row.get("job_id")
            flags = _parse_flags_cell(row.get("flags"))
            if score is not None and job_id:
                items.append((job_id, score, decision, flags))
    items.sort(key=lambda x: (-x[1], x[0]))
    return items


def _find_normalized_weights_map(obj: Any, candidate_ids: List[str]) -> Optional[Dict[str, Dict[str, float]]]:
    # recursively search for a dict mapping candidate_id -> dict with expected weight keys
    expected_keys = {"commute_weight", "shift_weight", "travel_weight", "remote_weight", "training_weight"}
    def is_target(d: Dict[Any, Any]) -> bool:
        # keys must include all candidate_ids
        try:
            keys = set(d.keys())
            if not all(cid in keys for cid in candidate_ids):
                return False
            for cid in candidate_ids:
                v = d.get(cid)
                if not isinstance(v, dict):
                    return False
                if set(v.keys()) != expected_keys:
                    return False
                # ensure numeric
                for wv in v.values():
                    float(wv)  # may raise
            return True
        except Exception:
            return False

    if isinstance(obj, dict):
        if is_target(obj):
            return obj  # type: ignore
        for v in obj.values():
            found = _find_normalized_weights_map(v, candidate_ids)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for it in obj:
            found = _find_normalized_weights_map(it, candidate_ids)
            if found is not None:
                return found
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "compute_script_present": 0.0,
        "validate_script_present": 0.0,
        "recommendations_file_present": 0.0,
        "recommendations_columns_correct": 0.0,
        "recommendations_row_count_complete": 0.0,
        "recommendations_scores_correct": 0.0,
        "recommendations_decisions_correct": 0.0,
        "recommendations_flags_correct": 0.0,
        "recommendations_identity_consistent": 0.0,
        "validation_report_present": 0.0,
        "validation_report_pass_all": 0.0,
        "validation_pairs_logic_pass": 0.0,
        "run_info_present": 0.0,
        "run_info_pair_count_correct": 0.0,
        "run_info_normalized_weights_correct": 0.0,
        "summary_report_present": 0.0,
        "summary_exec_summary_bullets_2_to_4": 0.0,
        "summary_per_candidate_top2_covered": 0.0,
        "summary_method_section_complete": 0.0,
        "meeting_notes_present": 0.0,
        "meeting_agenda_present": 0.0,
        "meeting_per_candidate_three_actions_with_top_job": 0.0,
    }

    # Presence of scripts
    compute_script = workspace / "scripts" / "compute_lifestyle_fit.py"
    validate_script = workspace / "scripts" / "validate_scoring.py"
    if compute_script.is_file() and compute_script.stat().st_size > 0:
        scores["compute_script_present"] = 1.0
    if validate_script.is_file() and validate_script.stat().st_size > 0:
        scores["validate_script_present"] = 1.0

    # Load inputs
    candidates = _load_candidates(workspace)
    jobs = _load_jobs(workspace)

    # Recommendations CSV presence and structure
    recs_rows, recs_header = _read_recommendations(workspace)
    if recs_rows is not None and recs_header is not None and len(recs_rows) > 0:
        scores["recommendations_file_present"] = 1.0

        expected_cols = ["candidate_id", "candidate_name", "job_id", "role", "lifestyle_fit_score", "decision", "flags"]
        if recs_header == expected_cols:
            scores["recommendations_columns_correct"] = 1.0

        # Row count complete
        if candidates is not None and jobs is not None:
            expected_count = len(candidates) * len(jobs)
            if len(recs_rows) == expected_count:
                scores["recommendations_row_count_complete"] = 1.0

        # Build lookup for inputs
        cand_by_id: Dict[str, Dict[str, Any]] = {}
        job_by_id: Dict[str, Dict[str, Any]] = {}
        if candidates:
            cand_by_id = {c["candidate_id"]: c for c in candidates if c.get("candidate_id")}
        if jobs:
            job_by_id = {j["job_id"]: j for j in jobs if j.get("job_id")}

        # Verify identity consistency: candidate_name and role match inputs
        identity_ok = True
        for row in recs_rows:
            cid = row.get("candidate_id")
            jid = row.get("job_id")
            if cid in cand_by_id:
                rec_name = (row.get("candidate_name") or "").strip()
                src_name = (cand_by_id[cid].get("candidate_name") or "").strip()
                if rec_name != src_name:
                    identity_ok = False
                    break
            else:
                identity_ok = False
                break
            if jid in job_by_id:
                rec_role = (row.get("role") or "").strip()
                src_role = (job_by_id[jid].get("role") or "").strip()
                if rec_role != src_role:
                    identity_ok = False
                    break
            else:
                identity_ok = False
                break
        if identity_ok and candidates is not None and jobs is not None:
            scores["recommendations_identity_consistent"] = 1.0

        # Verify scores, decisions, flags
        scores_ok = True
        decisions_ok = True
        flags_ok = True
        for row in recs_rows:
            cid = row.get("candidate_id")
            jid = row.get("job_id")
            if not cid or not jid:
                scores_ok = False
                decisions_ok = False
                flags_ok = False
                break
            if cid not in cand_by_id or jid not in job_by_id:
                scores_ok = False
                decisions_ok = False
                flags_ok = False
                break
            computed = _compute_score_and_decision(cand_by_id[cid], job_by_id[jid])
            if computed is None:
                scores_ok = False
                decisions_ok = False
                flags_ok = False
                break
            comp_score, comp_decision, comp_flags = computed
            rec_score = _safe_float_from_recs(row, "lifestyle_fit_score")
            if rec_score is None or abs(rec_score - comp_score) > 1e-9:
                scores_ok = False
            rec_decision = (row.get("decision") or "").strip()
            if rec_decision != comp_decision:
                decisions_ok = False
            rec_flags = set(_parse_flags_cell(row.get("flags")))
            if set(comp_flags) != rec_flags:
                flags_ok = False
        if scores_ok:
            scores["recommendations_scores_correct"] = 1.0
        if decisions_ok:
            scores["recommendations_decisions_correct"] = 1.0
        if flags_ok:
            scores["recommendations_flags_correct"] = 1.0
    else:
        # If recommendations missing or empty, dependent checks remain 0
        pass

    # Validation report presence and content
    validation_report_path = workspace / "outputs" / "validation_report.txt"
    report_text = _read_text(validation_report_path)
    if report_text is not None and report_text.strip():
        scores["validation_report_present"] = 1.0

    # Validation cases logic pass and report PASS lines
    validation_cases = _load_json(workspace / "input" / "validation_cases.json")
    if validation_cases and isinstance(validation_cases, dict):
        pairs = validation_cases.get("pairs", [])
        # Check logic pass from recommendations
        logic_ok = True
        report_ok = True
        if recs_rows:
            # build score lookup
            score_by = {}
            for row in recs_rows:
                cid = row.get("candidate_id")
                jid = row.get("job_id")
                s = _safe_float_from_recs(row, "lifestyle_fit_score")
                if cid and jid and s is not None:
                    score_by[(cid, jid)] = s
            for case in pairs:
                cid = case.get("candidate_id")
                better = case.get("better")
                worse = case.get("worse")
                if cid is None or better is None or worse is None:
                    logic_ok = False
                    break
                sb = score_by.get((cid, better))
                sw = score_by.get((cid, worse))
                if sb is None or sw is None or not (sb > sw):
                    logic_ok = False
                    break
        else:
            logic_ok = False

        if report_text:
            lines = [ln.strip() for ln in report_text.splitlines() if ln.strip()]
            for case in pairs:
                cid = case.get("candidate_id")
                better = case.get("better")
                worse = case.get("worse")
                if cid is None or better is None or worse is None:
                    report_ok = False
                    break
                found_line = False
                for ln in lines:
                    if cid in ln and better in ln and worse in ln and ("PASS" in ln or "pass" in ln.lower()):
                        found_line = True
                        break
                if not found_line:
                    report_ok = False
                    break
        else:
            report_ok = False

        if logic_ok:
            scores["validation_pairs_logic_pass"] = 1.0
        if report_ok:
            scores["validation_report_pass_all"] = 1.0

    # Run info checks
    run_info_path = workspace / "outputs" / "run_info.json"
    run_info = _load_json(run_info_path)
    if run_info is not None:
        scores["run_info_present"] = 1.0
        # Pair count check
        rec_count = len(recs_rows) if recs_rows else None
        pair_count_ok = False
        if isinstance(run_info, dict) and rec_count is not None:
            for key in ["pair_count", "pairs_scored", "num_pairs", "recommendation_count", "count"]:
                if key in run_info and isinstance(run_info[key], (int, float)) and int(run_info[key]) == rec_count:
                    pair_count_ok = True
                    break
        if pair_count_ok:
            scores["run_info_pair_count_correct"] = 1.0

        # Normalized weights correctness
        if candidates is not None and isinstance(run_info, (dict, list)):
            candidate_ids = [c["candidate_id"] for c in candidates if c.get("candidate_id")]
            found_map = _find_normalized_weights_map(run_info, candidate_ids)
            if found_map is not None:
                # Compute expected normalized weights
                ok = True
                for c in candidates:
                    cid = c["candidate_id"]
                    raw = {
                        "commute_weight": c["commute_weight"],
                        "shift_weight": c["shift_weight"],
                        "travel_weight": c["travel_weight"],
                        "remote_weight": c["remote_weight"],
                        "training_weight": c["training_weight"],
                    }
                    if any(v is None for v in raw.values()):
                        ok = False
                        break
                    expected = _normalize_weights(raw)
                    got = found_map.get(cid, {})
                    # compare within small tolerance
                    for k, ev in expected.items():
                        gv = got.get(k)
                        try:
                            gvf = float(gv)
                        except Exception:
                            ok = False
                            break
                        if abs(gvf - ev) > 1e-6:
                            ok = False
                            break
                    if not ok:
                        break
                if ok:
                    scores["run_info_normalized_weights_correct"] = 1.0

    # Summary report checks
    summary_path = workspace / "reports" / "lifestyle_fit_summary.md"
    summary_text = _read_text(summary_path)
    if summary_text is not None and summary_text.strip():
        scores["summary_report_present"] = 1.0
        # Executive Summary bullets 2-4
        exec_sec = _find_section(summary_text, "Executive Summary")
        if exec_sec:
            bullets = _count_bullets_in_section(exec_sec)
            if 2 <= bullets <= 4:
                scores["summary_exec_summary_bullets_2_to_4"] = 1.0

        # Per-candidate top2 covered
        per_candidate_ok = True
        method_ok = False
        if recs_rows:
            for cid in ["C01", "C02", "C03"]:
                sec = _find_section(summary_text, cid)
                if not sec:
                    per_candidate_ok = False
                    break
                # determine top 2
                top = _top_jobs_for_candidate(recs_rows, cid)[:2]
                if len(top) < 2:
                    per_candidate_ok = False
                    break
                components_keywords = {"commute", "shift", "travel", "remote", "training"}
                # For each top job, check job id, score, decision present in a line
                for job_id, sc, dec, flags in top:
                    # find a line that mentions job_id, score, decision
                    sc_str = f"{sc:.1f}"
                    line_found = False
                    for ln in sec.splitlines():
                        if (job_id in ln) and (sc_str in ln) and (dec in ln):
                            line_found = True
                            break
                    if not line_found:
                        per_candidate_ok = False
                        break
                    # Check at least two components mentioned in section
                # at least two component keywords anywhere in section
                comp_mentions = sum(1 for kw in components_keywords if kw in sec.lower())
                if comp_mentions < 2:
                    per_candidate_ok = False
                    break
                # If flags present for either of top jobs, ensure a flag string appears
                flag_strings = {"commute_exceeds_max", "no_nights_constraint", "no_travel_preference", "training_too_high"}
                any_flags = set()
                for _, _, _, fl in top:
                    any_flags.update(fl)
                if any_flags:
                    if not any(fs in sec for fs in flag_strings):
                        per_candidate_ok = False
                        break
            if per_candidate_ok:
                scores["summary_per_candidate_top2_covered"] = 1.0

        # Method section must mention components, normalized, and validation pass/fail
        method_sec = _find_section(summary_text, "Method")
        if method_sec:
            lower = method_sec.lower()
            if all(k in lower for k in ["commute", "shift", "travel", "remote", "training"]) and ("normaliz" in lower):
                # Validation mention
                if "validation" in lower and ("pass" in lower or "fail" in lower or "failed" in lower):
                    method_ok = True
        if method_ok:
            scores["summary_method_section_complete"] = 1.0

    # Meeting notes checks
    meeting_path = workspace / "meetings" / "next_steps.md"
    meeting_text = _read_text(meeting_path)
    if meeting_text is not None and meeting_text.strip():
        scores["meeting_notes_present"] = 1.0
        # Agenda presence
        if "agenda" in meeting_text.lower():
            scores["meeting_agenda_present"] = 1.0
        # Per candidate three actions referencing top job id
        if recs_rows:
            ok_all = True
            for cid in ["C01", "C02", "C03"]:
                top = _top_jobs_for_candidate(recs_rows, cid)[:1]
                if not top:
                    ok_all = False
                    break
                top_job = top[0][0]
                # Count bullet lines mentioning top_job
                count = 0
                for ln in meeting_text.splitlines():
                    if ln.strip().startswith(("-", "*")) and (top_job in ln):
                        count += 1
                if count < 3:
                    ok_all = False
                    break
            if ok_all:
                scores["meeting_per_candidate_three_actions_with_top_job"] = 1.0

    return scores


def main() -> None:
        workspace = "."
        if len(sys.argv) >= 2 and sys.argv[1].strip():
            workspace = sys.argv[1]
        result = grade([], workspace)
        print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()