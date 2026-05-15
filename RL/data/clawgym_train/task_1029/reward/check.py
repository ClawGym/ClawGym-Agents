import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _float_close(a: float, b: float, tol: float = 1e-6) -> bool:
    if math.isfinite(a) and math.isfinite(b):
        return abs(a - b) <= tol
    return False


def _float_close_relaxed(a: float, b: float, tol: float = 0.1) -> bool:
    return abs(a - b) <= tol


def _extract_numbers(text: str) -> List[float]:
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
    out = []
    for n in nums:
        try:
            out.append(float(n))
        except Exception:
            continue
    return out


def _to_bool_from_str(val: str) -> Optional[bool]:
    if val is None:
        return None
    v = val.strip().lower()
    if v in ("true", "t", "1"):
        return True
    if v in ("false", "f", "0"):
        return False
    return None


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    bp_path = workspace / "data" / "bp_log.csv"
    hr_path = workspace / "data" / "heart_rate.csv"
    act_path = workspace / "data" / "activities.csv"

    bp_rows = _safe_read_csv_dicts(bp_path)
    hr_rows = _safe_read_csv_dicts(hr_path)
    act_rows = _safe_read_csv_dicts(act_path)

    if bp_rows is None or hr_rows is None or act_rows is None:
        return None

    try:
        bp_map: Dict[str, Tuple[int, int]] = {}
        for r in bp_rows:
            date = r["date"].strip()
            systolic = int(r["systolic"])
            diastolic = int(r["diastolic"])
            bp_map[date] = (systolic, diastolic)

        hr_map: Dict[str, int] = {}
        for r in hr_rows:
            date = r["date"].strip()
            hr_map[date] = int(r["resting_hr"])

        gardening_minutes: Dict[str, int] = {}
        activity_dates: set = set()
        for r in act_rows:
            date = r["date"].strip()
            activity_dates.add(date)
            if r.get("activity_type", "").strip() == "Gardening":
                minutes = int(r.get("minutes", "0"))
                gardening_minutes[date] = gardening_minutes.get(date, 0) + minutes

        dates = sorted(set(bp_map.keys()) & set(hr_map.keys()) & activity_dates)

        expected_rows: List[Dict[str, Any]] = []
        for d in dates:
            s, di = bp_map[d]
            hr = hr_map[d]
            gmin = gardening_minutes.get(d, 0)
            is_g = gmin >= 30
            expected_rows.append(
                {
                    "date": d,
                    "systolic": s,
                    "diastolic": di,
                    "resting_hr": hr,
                    "gardening_minutes": gmin,
                    "is_gardening_day": is_g,
                }
            )

        g_group = [r for r in expected_rows if r["is_gardening_day"]]
        ng_group = [r for r in expected_rows if not r["is_gardening_day"]]
        counts = {"gardening": len(g_group), "non_gardening": len(ng_group)}

        def mean(vals: List[float]) -> float:
            return sum(vals) / len(vals) if vals else float("nan")

        group_means = {
            "gardening": {
                "systolic": mean([r["systolic"] for r in g_group]),
                "diastolic": mean([r["diastolic"] for r in g_group]),
                "resting_hr": mean([r["resting_hr"] for r in g_group]),
            },
            "non_gardening": {
                "systolic": mean([r["systolic"] for r in ng_group]),
                "diastolic": mean([r["diastolic"] for r in ng_group]),
                "resting_hr": mean([r["resting_hr"] for r in ng_group]),
            },
        }
        differences = {
            "systolic": group_means["gardening"]["systolic"] - group_means["non_gardening"]["systolic"],
            "diastolic": group_means["gardening"]["diastolic"] - group_means["non_gardening"]["diastolic"],
            "resting_hr": group_means["gardening"]["resting_hr"] - group_means["non_gardening"]["resting_hr"],
        }

        return {
            "dates": dates,
            "rows": expected_rows,
            "counts": counts,
            "group_means": group_means,
            "differences": differences,
        }
    except Exception:
        return None


def _parse_daily_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, Any]]]]:
    rows = _safe_read_csv_dicts(path)
    if rows is None:
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
        parsed: List[Dict[str, Any]] = []
        for r in rows:
            date = r.get("date", "").strip()
            systolic = int(r.get("systolic", ""))
            diastolic = int(r.get("diastolic", ""))
            resting_hr = int(r.get("resting_hr", ""))
            gardening_minutes = int(r.get("gardening_minutes", ""))
            is_g_str = r.get("is_gardening_day", "")
            is_g_bool = _to_bool_from_str(is_g_str)
            if is_g_bool is None:
                return None
            parsed.append(
                {
                    "date": date,
                    "systolic": systolic,
                    "diastolic": diastolic,
                    "resting_hr": resting_hr,
                    "gardening_minutes": gardening_minutes,
                    "is_gardening_day": is_g_bool,
                }
            )
        return header, parsed
    except Exception:
        return None


def _rows_to_set(rows: List[Dict[str, Any]]) -> set:
    s = set()
    for r in rows:
        t = (
            r["date"],
            int(r["systolic"]),
            int(r["diastolic"]),
            int(r["resting_hr"]),
            int(r["gardening_minutes"]),
            bool(r["is_gardening_day"]),
        )
        s.add(t)
    return s


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_file_present": 0.0,
        "command_used_valid": 0.0,
        "daily_merged_present": 0.0,
        "daily_merged_columns_correct": 0.0,
        "daily_merged_rows_match": 0.0,
        "summary_json_present": 0.0,
        "summary_json_structure": 0.0,
        "summary_json_values_match": 0.0,
        "report_summary_contains_required_stats": 0.0,
        "letter_replaced_placeholder": 0.0,
        "letter_preserves_structure": 0.0,
        "letter_word_count_valid": 0.0,
        "letter_includes_stats": 0.0,
    }

    script_py = workspace / "scripts" / "analyze_gardening_health.py"
    script_sh = workspace / "scripts" / "analyze_gardening_health.sh"
    if script_py.exists() or script_sh.exists():
        scores["script_file_present"] = 1.0

    expected = _compute_expected(workspace)

    cmd_path = workspace / "output" / "command_used.txt"
    cmd_text = _safe_read_text(cmd_path)
    if cmd_text is not None:
        lines = [ln for ln in cmd_text.splitlines() if ln.strip() != ""]
        contains_script_ref = "scripts/analyze_gardening_health.py" in cmd_text or "scripts/analyze_gardening_health.sh" in cmd_text
        if len(lines) == 1 and contains_script_ref:
            scores["command_used_valid"] = 1.0

    daily_path = workspace / "output" / "daily_merged.csv"
    if daily_path.exists():
        scores["daily_merged_present"] = 1.0
        parsed = _parse_daily_csv(daily_path)
        if parsed is not None:
            header, out_rows = parsed
            expected_header = ["date", "systolic", "diastolic", "resting_hr", "gardening_minutes", "is_gardening_day"]
            if header == expected_header:
                scores["daily_merged_columns_correct"] = 1.0
            if expected is not None:
                exp_rows = expected["rows"]
                try:
                    out_set = _rows_to_set(out_rows)
                    exp_set = _rows_to_set(exp_rows)
                    if out_set == exp_set:
                        scores["daily_merged_rows_match"] = 1.0
                except Exception:
                    pass

    summary_path = workspace / "output" / "summary.json"
    summary = _safe_load_json(summary_path)
    if summary is not None and isinstance(summary, dict):
        scores["summary_json_present"] = 1.0
        structure_ok = (
            "counts" in summary
            and "group_means" in summary
            and "differences" in summary
            and isinstance(summary["counts"], dict)
            and isinstance(summary["group_means"], dict)
            and isinstance(summary["differences"], dict)
        )
        if structure_ok:
            counts = summary["counts"]
            gmeans = summary["group_means"]
            diffs = summary["differences"]
            structure_ok = (
                "gardening" in counts
                and "non_gardening" in counts
                and "gardening" in gmeans
                and "non_gardening" in gmeans
                and all(k in gmeans["gardening"] for k in ("systolic", "diastolic", "resting_hr"))
                and all(k in gmeans["non_gardening"] for k in ("systolic", "diastolic", "resting_hr"))
                and all(k in diffs for k in ("systolic", "diastolic", "resting_hr"))
            )
        if structure_ok:
            scores["summary_json_structure"] = 1.0
            if expected is not None:
                try:
                    counts = summary["counts"]
                    gmeans = summary["group_means"]
                    diffs = summary["differences"]
                    exp_counts = expected["counts"]
                    exp_gmeans = expected["group_means"]
                    exp_diffs = expected["differences"]
                    counts_match = (
                        int(counts.get("gardening", -1)) == int(exp_counts["gardening"]) and
                        int(counts.get("non_gardening", -1)) == int(exp_counts["non_gardening"])
                    )
                    gmeans_match = (
                        _float_close(float(gmeans["gardening"]["systolic"]), float(exp_gmeans["gardening"]["systolic"]))
                        and _float_close(float(gmeans["gardening"]["diastolic"]), float(exp_gmeans["gardening"]["diastolic"]))
                        and _float_close(float(gmeans["gardening"]["resting_hr"]), float(exp_gmeans["gardening"]["resting_hr"]))
                        and _float_close(float(gmeans["non_gardening"]["systolic"]), float(exp_gmeans["non_gardening"]["systolic"]))
                        and _float_close(float(gmeans["non_gardening"]["diastolic"]), float(exp_gmeans["non_gardening"]["diastolic"]))
                        and _float_close(float(gmeans["non_gardening"]["resting_hr"]), float(exp_gmeans["non_gardening"]["resting_hr"]))
                    )
                    diffs_match = (
                        _float_close(float(diffs["systolic"]), float(exp_diffs["systolic"]))
                        and _float_close(float(diffs["diastolic"]), float(exp_diffs["diastolic"]))
                        and _float_close(float(diffs["resting_hr"]), float(exp_diffs["resting_hr"]))
                    )
                    if counts_match and gmeans_match and diffs_match:
                        scores["summary_json_values_match"] = 1.0
                except Exception:
                    pass

    report_path = workspace / "reports" / "health_gardening_summary.md"
    report_text = _safe_read_text(report_path)
    if report_text is not None and expected is not None:
        has_keywords = all(k in report_text.lower() for k in ["gardening", "non-gardening", "systolic", "diastolic", "resting"])
        nums = _extract_numbers(report_text)
        counts_ok = (
            float(expected["counts"]["gardening"]) in nums and
            float(expected["counts"]["non_gardening"]) in nums
        )
        gm = expected["group_means"]
        diffs = expected["differences"]
        means_targets = [
            gm["gardening"]["systolic"], gm["gardening"]["diastolic"], gm["gardening"]["resting_hr"],
            gm["non_gardening"]["systolic"], gm["non_gardening"]["diastolic"], gm["non_gardening"]["resting_hr"],
        ]
        diffs_targets = [diffs["systolic"], diffs["diastolic"], diffs["resting_hr"]]

        def any_close(target: float, arr: List[float], tol: float = 0.1) -> bool:
            for v in arr:
                if _float_close_relaxed(v, target, tol=tol):
                    return True
            return False

        means_ok = all(any_close(t, nums) for t in means_targets)
        diffs_ok = all(any_close(t, nums) for t in diffs_targets)

        if has_keywords and counts_ok and means_ok and diffs_ok:
            scores["report_summary_contains_required_stats"] = 1.0

    draft_path = workspace / "letters" / "gp_letter_draft.md"
    review_path = workspace / "letters" / "gp_letter_for_review.md"
    draft_text = _safe_read_text(draft_path)
    review_text = _safe_read_text(review_path)
    if draft_text is not None and review_text is not None:
        if "<INSERT_ANALYSIS_SUMMARY>" not in review_text:
            scores["letter_replaced_placeholder"] = 1.0

        draft_lines = draft_text.splitlines(keepends=True)
        placeholder_idx = None
        for i, ln in enumerate(draft_lines):
            if ln.strip() == "<INSERT_ANALYSIS_SUMMARY>":
                placeholder_idx = i
                break
        if placeholder_idx is not None:
            before_text = "".join(draft_lines[:placeholder_idx])
            after_text = "".join(draft_lines[placeholder_idx + 1 :])
            prefix_ok = review_text.startswith(before_text)
            suffix_ok = review_text.endswith(after_text)
            if prefix_ok and suffix_ok:
                scores["letter_preserves_structure"] = 1.0
            if prefix_ok and suffix_ok:
                replacement_segment = review_text[len(before_text) : len(review_text) - len(after_text)]
                words = re.findall(r"\b\w+\b", replacement_segment)
                if 120 <= len(words) <= 180:
                    scores["letter_word_count_valid"] = 1.0
                if expected is not None:
                    nums = _extract_numbers(replacement_segment)
                    counts_ok = (
                        float(expected["counts"]["gardening"]) in nums and
                        float(expected["counts"]["non_gardening"]) in nums
                    )
                    gm = expected["group_means"]
                    diffs = expected["differences"]
                    means_targets = [
                        gm["gardening"]["systolic"], gm["gardening"]["diastolic"], gm["gardening"]["resting_hr"],
                        gm["non_gardening"]["systolic"], gm["non_gardening"]["diastolic"], gm["non_gardening"]["resting_hr"],
                    ]
                    diffs_targets = [diffs["systolic"], diffs["diastolic"], diffs["resting_hr"]]
                    means_ok = all(any(_float_close_relaxed(t, n) for n in nums) for t in means_targets)
                    diffs_ok = all(any(_float_close_relaxed(t, n) for n in nums) for t in diffs_targets)
                    includes_keywords = all(w in replacement_segment.lower() for w in ["systolic", "diastolic", "resting"])
                    if counts_ok and means_ok and diffs_ok and includes_keywords:
                        scores["letter_includes_stats"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()