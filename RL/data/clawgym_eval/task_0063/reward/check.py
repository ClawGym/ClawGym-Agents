import json
import csv
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional


def _safe_read_csv_dicts(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return True, rows
    except Exception:
        return False, []


def _safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def _safe_load_json(path: Path) -> Tuple[bool, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _safe_load_jsonl(path: Path) -> Tuple[bool, List[Dict[str, Any]]]:
    objs = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                objs.append(json.loads(line))
        return True, objs
    except Exception:
        return False, []


def _to_float(val: Any) -> Optional[float]:
    try:
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if s == "" or s.lower() == "none" or s.lower() == "null":
            return None
        return float(s)
    except Exception:
        return None


def _to_int(val: Any) -> Optional[int]:
    try:
        if isinstance(val, int):
            return val
        s = str(val).strip()
        if s == "" or s.lower() == "none" or s.lower() == "null":
            return None
        return int(float(s))
    except Exception:
        return None


def _compute_schema_messages(csv_path: Path, required_cols: List[str]) -> Tuple[str, str]:
    """
    Emulate input/schema_check.py stdout/stderr for given CSV and required columns.
    Returns (stdout_text, stderr_text). For OK case, stderr_text is empty.
    """
    # Default to error if file missing or malformed
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                return ("", f"ERROR: File appears empty: {csv_path}\n")
            header_set = set(headers)
            missing = [c for c in required_cols if c not in header_set]
            if missing:
                return ("", "ERROR: Missing columns: " + ", ".join(missing) + "\n")
            rows = 0
            idx_player = headers.index('player_id') if 'player_id' in header_set else None
            counts: Dict[str, int] = {}
            for row in reader:
                rows += 1
                if idx_player is not None and len(row) > idx_player:
                    pid = row[idx_player]
                    counts[pid] = counts.get(pid, 0) + 1
            dups = {k: v for k, v in counts.items() if v > 1}
            out_lines = []
            out_lines.append(f"OK: Header check passed for {csv_path}")
            out_lines.append(f"INFO: Rows={rows}, Columns={len(headers)}")
            if idx_player is None:
                out_lines.append("INFO: No player_id column present; duplicate check skipped")
            else:
                if dups:
                    parts = [f"{k} (count {v})" for k, v in sorted(dups.items())]
                    out_lines.append("WARN: Duplicate player_id values detected: " + "; ".join(parts))
                else:
                    out_lines.append("OK: No duplicate player_id values detected")
            return ("\n".join(out_lines) + "\n", "")
    except FileNotFoundError:
        return ("", f"ERROR: File not found: {csv_path}\n")
    except Exception as e:
        return ("", f"ERROR: Exception during check: {e}\n")


def _dedupe_scouts(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    best_by_id: Dict[str, Dict[str, str]] = {}
    for r in rows:
        pid = r.get("player_id", "")
        score = _to_float(r.get("scout_score"))
        prev = best_by_id.get(pid)
        if prev is None:
            best_by_id[pid] = r
        else:
            prev_score = _to_float(prev.get("scout_score"))
            if (score or -float("inf")) > (prev_score or -float("inf")):
                best_by_id[pid] = r
    return list(best_by_id.values())


def _group_by_position(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    g: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        pos = r.get("position", "")
        g.setdefault(pos, []).append(r)
    return g


def _approx_equal(a: Optional[float], b: Optional[float], tol: float = 1e-3) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "qa_schema_scout_output_present": 0.0,
        "qa_schema_perf_output_present": 0.0,
        "qa_mentions_dedup_and_ids": 0.0,
        "qa_lists_missing_retired_ids": 0.0,
        "qa_mentions_normalization_and_weights": 0.0,
        "qa_mentions_tie_breakers": 0.0,
        "shortlist_columns_and_existence": 0.0,
        "shortlist_correct_players_per_position": 0.0,
        "shortlist_values_consistency": 0.0,
        "deduplication_applied_correctly": 0.0,
        "position_summary_structure_and_positions": 0.0,
        "position_summary_aggregates_correct": 0.0,
    }

    # Load inputs
    scout_csv = workspace / "input" / "scout_reports.csv"
    perf_csv = workspace / "input" / "performance_last_season.csv"
    retired_jsonl = workspace / "input" / "retired_insights.jsonl"
    ok_scouts, scouts_rows = _safe_read_csv_dicts(scout_csv)
    ok_perf, perf_rows = _safe_read_csv_dicts(perf_csv)
    ok_retired, retired_rows = _safe_load_jsonl(retired_jsonl)

    # Compute expected schema_check outputs for QA report verification
    req_scouts = ["player_id", "name", "position", "age", "foot", "scout_score", "wage", "contract_years"]
    req_perf = ["player_id", "minutes", "goals", "assists", "xg", "xa"]
    scout_stdout, scout_stderr = _compute_schema_messages(scout_csv, req_scouts)
    perf_stdout, perf_stderr = _compute_schema_messages(perf_csv, req_perf)

    # QA report checks
    qa_path = workspace / "output" / "qa_report.md"
    ok_qa, qa_text = _safe_read_text(qa_path)

    # Check presence of exact schema outputs
    if ok_qa:
        cond1 = (scout_stdout.strip() in qa_text) and (scout_stderr.strip() in qa_text if scout_stderr.strip() else True)
        if cond1 and scout_stdout.strip() != "":
            scores["qa_schema_scout_output_present"] = 1.0
        cond2 = (perf_stdout.strip() in qa_text) and (perf_stderr.strip() in qa_text if perf_stderr.strip() else True)
        if cond2 and perf_stdout.strip() != "":
            scores["qa_schema_perf_output_present"] = 1.0

        # dedup mention and affected IDs
        qa_lower = qa_text.lower()
        if ("duplicate" in qa_lower or "deduplicat" in qa_lower) and ("p003" in qa_lower):
            scores["qa_mentions_dedup_and_ids"] = 1.0

        # missing retired_rating excluded and IDs
        if ("excluded" in qa_lower or "missing retired" in qa_lower or "missing_retired" in qa_lower) and ("p005" in qa_lower):
            scores["qa_lists_missing_retired_ids"] = 1.0

        # normalization and weights
        if ("0.65" in qa_text and "0.35" in qa_text) and (("normaliz" in qa_lower and ("/100" in qa_text or "divide by 100" in qa_lower)) and ("/10" in qa_text or "divide by 10" in qa_lower)):
            scores["qa_mentions_normalization_and_weights"] = 1.0

        # tie-breakers mention
        if ("tie" in qa_lower or "tiebreak" in qa_lower) and ("wage" in qa_lower) and ("age" in qa_lower):
            scores["qa_mentions_tie_breakers"] = 1.0

    # Build expected processed data if inputs parse OK
    expected_shortlist: List[Dict[str, Any]] = []
    expected_summary: Dict[str, Dict[str, Any]] = {}
    dedup_ids_affected: List[str] = []
    evaluated_pids_by_pos: Dict[str, List[str]] = {}
    missing_retired_by_pos: Dict[str, int] = {}

    if ok_scouts and ok_perf and ok_retired:
        # deduplicate scouts by higher scout_score
        # also collect which IDs were duplicated in raw
        counts = {}
        for r in scouts_rows:
            pid = r.get("player_id", "")
            counts[pid] = counts.get(pid, 0) + 1
        dedup_ids_affected = sorted([pid for pid, cnt in counts.items() if cnt > 1])

        dedup_scouts = _dedupe_scouts(scouts_rows)
        # Build mapping
        scouts_by_id = {r.get("player_id", ""): r for r in dedup_scouts}
        perf_by_id = {r.get("player_id", ""): r for r in perf_rows}
        retired_by_id = {r.get("player_id", ""): r for r in retired_rows}

        # Compute evaluated set and missing retired counts per position (intersection scouts+perf but absent in retired)
        positions_all = set([r.get("position", "") for r in dedup_scouts])
        # Evaluate set
        evaluated: List[Dict[str, Any]] = []
        for pid, srow in scouts_by_id.items():
            if pid not in perf_by_id:
                continue
            pos = srow.get("position", "")
            # missing retired rating count
            if pid not in retired_by_id:
                missing_retired_by_pos[pos] = missing_retired_by_pos.get(pos, 0) + 1
                continue
            # normalizations
            scout_score = _to_float(srow.get("scout_score")) or 0.0
            norm_scout = scout_score / 100.0
            retired_rating = _to_float(retired_by_id[pid].get("retired_rating")) or 0.0
            norm_retired = retired_rating / 10.0
            combined = 0.65 * norm_scout + 0.35 * norm_retired
            prow = perf_by_id[pid]
            risk_flags = retired_by_id[pid].get("risk_flags", [])
            evaluated.append({
                "player_id": pid,
                "name": srow.get("name", ""),
                "position": pos,
                "age": _to_int(srow.get("age")),
                "scout_score": scout_score,
                "retired_rating": retired_rating,
                "combined_recruitment_score": combined,
                "minutes": _to_int(prow.get("minutes")),
                "goals": _to_int(prow.get("goals")),
                "assists": _to_int(prow.get("assists")),
                "xg": _to_float(prow.get("xg")),
                "xa": _to_float(prow.get("xa")),
                "wage": _to_int(srow.get("wage")),
                "risk_flags": risk_flags if isinstance(risk_flags, list) else [],
            })
        # Build shortlist by position with tie-breakers
        by_pos = _group_by_position(evaluated)
        shortlist_expected_by_pos: Dict[str, List[Dict[str, Any]]] = {}
        for pos, items in by_pos.items():
            # tie-breakers: higher combined, then lower wage, then younger age
            items_sorted = sorted(
                items,
                key=lambda r: (
                    -(_to_float(r.get("combined_recruitment_score")) or 0.0),
                    (_to_int(r.get("wage")) if _to_int(r.get("wage")) is not None else float("inf")),
                    (_to_int(r.get("age")) if _to_int(r.get("age")) is not None else float("inf")),
                ),
            )
            shortlist_expected_by_pos[pos] = items_sorted[:2]
            evaluated_pids_by_pos[pos] = [r["player_id"] for r in items_sorted]
        # Flatten shortlist expected
        expected_shortlist = []
        for pos, lst in shortlist_expected_by_pos.items():
            for r in lst:
                # Generate risk_flags_summary string
                flags = r.get("risk_flags", [])
                if not flags:
                    rf = "None"
                else:
                    rf = ";".join(flags)
                expected_shortlist.append({
                    "player_id": r["player_id"],
                    "name": r["name"],
                    "position": r["position"],
                    "age": r["age"],
                    "scout_score": r["scout_score"],
                    "retired_rating": r["retired_rating"],
                    "combined_recruitment_score": r["combined_recruitment_score"],
                    "minutes": r["minutes"],
                    "goals": r["goals"],
                    "assists": r["assists"],
                    "xg": r["xg"],
                    "xa": r["xa"],
                    "risk_flags_summary": rf,
                })

        # Position summary expected values
        # Determine positions present from scouts (after dedup) that also appear in perf for missing counts
        # We'll include every position present in scouts (after dedup union with perf). Also ensure positions with zero evaluated (e.g., GK) included.
        pos_set = set()
        for pid, srow in scouts_by_id.items():
            if pid in perf_by_id:
                pos_set.add(srow.get("position", ""))
        # Compute per position aggregates for evaluated players
        for pos in pos_set:
            rel = [r for r in evaluated if r.get("position") == pos]
            count_eval = len(rel)
            if count_eval > 0:
                avg_comb = sum(_to_float(r["combined_recruitment_score"]) or 0.0 for r in rel) / count_eval
                avg_age = sum(_to_int(r["age"]) or 0 for r in rel) / count_eval
                total_minutes = sum(_to_int(r["minutes"]) or 0 for r in rel)
                mean_xg = sum(_to_float(r["xg"]) or 0.0 for r in rel) / count_eval
                mean_xa = sum(_to_float(r["xa"]) or 0.0 for r in rel) / count_eval
            else:
                avg_comb = None
                avg_age = None
                total_minutes = 0
                mean_xg = None
                mean_xa = None
            expected_summary[pos] = {
                "position": pos,
                "count_evaluated_players": count_eval,
                "avg_combined_score": avg_comb,
                "avg_age": avg_age,
                "total_minutes": total_minutes,
                "mean_xg": mean_xg,
                "mean_xa": mean_xa,
                "missing_retired_rating_count": missing_retired_by_pos.get(pos, 0),
            }

    # shortlist.csv checks
    shortlist_path = workspace / "output" / "shortlist.csv"
    ok_shortlist, shortlist_rows = _safe_read_csv_dicts(shortlist_path)
    required_shortlist_cols = ["player_id", "name", "position", "age", "scout_score", "retired_rating",
                               "combined_recruitment_score", "minutes", "goals", "assists", "xg", "xa", "risk_flags_summary"]
    if ok_shortlist:
        # Column order check
        try:
            with shortlist_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                headers = next(reader)
            if headers == required_shortlist_cols:
                scores["shortlist_columns_and_existence"] = 1.0
        except Exception:
            pass

    # Compare shortlist content to expected
    if ok_shortlist and expected_shortlist:
        # Build expected per position player_ids (top 2)
        expected_by_pos: Dict[str, List[str]] = {}
        for r in expected_shortlist:
            expected_by_pos.setdefault(r["position"], []).append(r["player_id"])
        # Ensure shortlist has no players with missing retired_rating (e.g., P005)
        contains_missing_retired = False
        shortlist_pids = set()
        shortlist_by_pos: Dict[str, List[Dict[str, str]]] = {}
        for r in shortlist_rows:
            pid = r.get("player_id", "")
            shortlist_pids.add(pid)
            # If retired rating missing or empty in shortlist row, flag
            rr = r.get("retired_rating", "")
            if rr is None or str(rr).strip() == "":
                contains_missing_retired = True
            shortlist_by_pos.setdefault(r.get("position", ""), []).append(r)
        if ok_retired:
            for pid in shortlist_pids:
                # If this pid not in retired jsonl, then they included a missing retired player
                found = any(obj.get("player_id") == pid for obj in retired_rows)
                if not found:
                    contains_missing_retired = True

        # Check top 2 per position correctness: the shortlist must contain only expected players for each position
        per_pos_ok = True
        for pos, exp_ids in expected_by_pos.items():
            got_ids = [r.get("player_id", "") for r in shortlist_by_pos.get(pos, [])]
            # We allow extra positions not expected only if they legitimately have evaluated players (should be subset)
            if set(got_ids) != set(exp_ids):
                per_pos_ok = False
                break
            # Also ensure not more than 2 per position
            if len(got_ids) > 2:
                per_pos_ok = False
                break
        # Also ensure no unexpected positions with evaluated players beyond expected
        unexpected_positions = [pos for pos in shortlist_by_pos.keys() if pos not in expected_by_pos]
        if unexpected_positions:
            per_pos_ok = False
        if per_pos_ok and not contains_missing_retired:
            scores["shortlist_correct_players_per_position"] = 1.0

        # Values consistency checks for each expected player
        values_ok = True
        for exp in expected_shortlist:
            # find row in shortlist
            matching = [r for r in shortlist_rows if r.get("player_id") == exp["player_id"]]
            if len(matching) != 1:
                values_ok = False
                break
            row = matching[0]
            # Check name, position, age, scout_score, retired_rating, performance stats
            if row.get("name") != exp["name"]:
                values_ok = False
                break
            if row.get("position") != exp["position"]:
                values_ok = False
                break
            if _to_int(row.get("age")) != exp["age"]:
                values_ok = False
                break
            if not _approx_equal(_to_float(row.get("scout_score")), _to_float(exp["scout_score"])):
                values_ok = False
                break
            if not _approx_equal(_to_float(row.get("retired_rating")), _to_float(exp["retired_rating"])):
                values_ok = False
                break
            if not _approx_equal(_to_float(row.get("combined_recruitment_score")), _to_float(exp["combined_recruitment_score"])):
                values_ok = False
                break
            # Performance columns
            if _to_int(row.get("minutes")) != exp["minutes"]:
                values_ok = False
                break
            if _to_int(row.get("goals")) != exp["goals"]:
                values_ok = False
                break
            if _to_int(row.get("assists")) != exp["assists"]:
                values_ok = False
                break
            if not _approx_equal(_to_float(row.get("xg")), _to_float(exp["xg"])):
                values_ok = False
                break
            if not _approx_equal(_to_float(row.get("xa")), _to_float(exp["xa"])):
                values_ok = False
                break
            # risk_flags_summary: semicolon-separated or "None" -> check set equality
            rf_cell = (row.get("risk_flags_summary") or "").strip()
            exp_cell = (exp.get("risk_flags_summary") or "").strip()
            def to_set(s: str) -> set:
                if s == "" or s.lower() == "none":
                    return set()
                return set([p.strip() for p in s.split(";") if p.strip() != ""])
            if to_set(rf_cell) != to_set(exp_cell):
                values_ok = False
                break
        if values_ok:
            scores["shortlist_values_consistency"] = 1.0

        # Deduplication applied correctly: specifically ensure P003 kept with higher scout_score (76) and appears only once overall
        dedup_ok = True
        if "P003" in [r.get("player_id") for r in scouts_rows]:
            # check shortlist row for P003 has scout_score 76
            rows_p003 = [r for r in shortlist_rows if r.get("player_id") == "P003"]
            if len(rows_p003) != 1:
                dedup_ok = False
            else:
                if _to_int(rows_p003[0].get("scout_score")) != 76:
                    dedup_ok = False
        if dedup_ok:
            scores["deduplication_applied_correctly"] = 1.0

    # position_summary.json checks
    summary_path = workspace / "output" / "position_summary.json"
    ok_summary, summary_obj = _safe_load_json(summary_path)
    # Normalize loaded structure to dict keyed by position -> dict
    def _normalize_summary(obj: Any) -> Optional[Dict[str, Dict[str, Any]]]:
        if isinstance(obj, dict):
            # If dict keyed by position with value dict, convert
            norm: Dict[str, Dict[str, Any]] = {}
            for k, v in obj.items():
                if isinstance(v, dict):
                    pos = v.get("position", k)
                    norm[pos] = v
                else:
                    return None
            return norm
        elif isinstance(obj, list):
            norm = {}
            for item in obj:
                if not isinstance(item, dict):
                    return None
                pos = item.get("position")
                if not pos:
                    return None
                norm[pos] = item
            return norm
        else:
            return None

    if ok_summary:
        norm_summary = _normalize_summary(summary_obj)
        if norm_summary is not None and expected_summary:
            # Expect all positions present in expected_summary
            expected_positions = set(expected_summary.keys())
            got_positions = set(norm_summary.keys())
            # We require at least the expected positions present
            if expected_positions.issubset(got_positions):
                scores["position_summary_structure_and_positions"] = 1.0

            # Check aggregate values
            agg_ok = True
            for pos, exp in expected_summary.items():
                got = norm_summary.get(pos, {})
                # count_evaluated_players exact
                if _to_int(got.get("count_evaluated_players")) != exp["count_evaluated_players"]:
                    agg_ok = False
                    break
                # missing_retired_rating_count exact
                if _to_int(got.get("missing_retired_rating_count")) != exp["missing_retired_rating_count"]:
                    agg_ok = False
                    break
                # total_minutes exact (sum over evaluated players)
                if _to_int(got.get("total_minutes")) != exp["total_minutes"]:
                    agg_ok = False
                    break
                # Averages with tolerance; handle 0 evaluated case flexibly (accept None or 0 or missing)
                cev = exp["count_evaluated_players"]
                if cev > 0:
                    if not _approx_equal(_to_float(got.get("avg_combined_score")), _to_float(exp["avg_combined_score"])):
                        agg_ok = False
                        break
                    if not _approx_equal(_to_float(got.get("avg_age")), _to_float(exp["avg_age"])):
                        agg_ok = False
                        break
                    if not _approx_equal(_to_float(got.get("mean_xg")), _to_float(exp["mean_xg"])):
                        agg_ok = False
                        break
                    if not _approx_equal(_to_float(got.get("mean_xa")), _to_float(exp["mean_xa"])):
                        agg_ok = False
                        break
                else:
                    # If no evaluated players, avg fields may be None, null, 0, or omitted
                    # We'll accept None/null or 0 or missing keys
                    pass
            if agg_ok:
                scores["position_summary_aggregates_correct"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()