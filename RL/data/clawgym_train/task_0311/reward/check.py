import json
import csv
import sys
import subprocess
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_sessions_html(path: Path) -> Optional[Dict[str, str]]:
    """
    Parse drama_sessions.html and return a dict mapping session_id -> condition
    by selecting the table that contains headers 'session_id' and 'condition'.
    """
    html = _read_text(path)
    if html is None:
        return None
    try:
        tables = re.findall(r"<table\b[^>]*>(.*?)</table>", html, flags=re.IGNORECASE | re.DOTALL)
        session_map: Dict[str, str] = {}
        found = False
        for tbl in tables:
            headers = re.findall(r"<th[^>]*>(.*?)</th>", tbl, flags=re.IGNORECASE | re.DOTALL)
            clean_headers = [re.sub(r"\s+", " ", h).strip().lower() for h in headers]
            if "session_id" in clean_headers and "condition" in clean_headers:
                found = True
                header_index = {name: idx for idx, name in enumerate(clean_headers)}
                rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, flags=re.IGNORECASE | re.DOTALL)
                # Skip the header row by ensuring we only process rows with <td> cells
                for row in rows:
                    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.IGNORECASE | re.DOTALL)
                    if not cells:
                        continue
                    cells = [re.sub(r"<[^>]*>", "", c) for c in cells]  # strip any nested tags
                    cells = [re.sub(r"\s+", " ", c).strip() for c in cells]
                    # Only process rows that match header length or more
                    if len(cells) < len(clean_headers):
                        continue
                    sid = cells[header_index["session_id"]]
                    cond = cells[header_index["condition"]]
                    if sid:
                        session_map[sid] = cond
                break
        if not found:
            return None
        return session_map
    except Exception:
        return None


def _coerce_float(value) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _coerce_int(value) -> Optional[int]:
    try:
        f = float(value)
        i = int(f)
        if abs(f - i) < 1e-9:
            return i
        return None
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return a == b or (a is not None and b is not None and abs(a - b) <= tol)


def _compute_expected(workspace: Path) -> Tuple[Optional[List[Dict[str, object]]], Optional[List[Dict[str, object]]]]:
    """
    Returns (expected_participant_deltas, expected_group_summary)
    """
    scores_path = workspace / "data" / "empathy_scores.csv"
    map_path = workspace / "data" / "participant_sessions.csv"
    html_path = workspace / "data" / "drama_sessions.html"

    scores_rows = _read_csv_rows(scores_path)
    map_rows = _read_csv_rows(map_path)
    sessions_map = _parse_sessions_html(html_path)

    if scores_rows is None or map_rows is None or sessions_map is None:
        return None, None

    # Build participant_id -> session_id mapping
    part_to_session: Dict[str, str] = {}
    for r in map_rows:
        pid = r.get("participant_id", "")
        sid = r.get("session_id", "")
        if pid and sid:
            part_to_session[pid] = sid

    deltas: List[Dict[str, object]] = []
    for r in scores_rows:
        pid = r.get("participant_id")
        pre = _coerce_float(r.get("pre_empathy"))
        post = _coerce_float(r.get("post_empathy"))
        if pid is None or pre is None or post is None:
            return None, None
        sid = part_to_session.get(pid)
        if sid is None:
            return None, None
        group = sessions_map.get(sid)
        if group is None:
            return None, None
        delta = post - pre
        deltas.append({
            "participant_id": pid,
            "session_id": sid,
            "group": group,
            "pre_empathy": pre,
            "post_empathy": post,
            "delta": delta
        })

    # Group summary
    by_group: Dict[str, Dict[str, float]] = {}
    counts: Dict[str, int] = {}
    for row in deltas:
        g = str(row["group"])
        counts[g] = counts.get(g, 0) + 1
        agg = by_group.get(g)
        if agg is None:
            agg = {"sum_pre": 0.0, "sum_post": 0.0, "sum_delta": 0.0}
            by_group[g] = agg
        agg["sum_pre"] += float(row["pre_empathy"])
        agg["sum_post"] += float(row["post_empathy"])
        agg["sum_delta"] += float(row["delta"])

    summary: List[Dict[str, object]] = []
    for g in sorted(by_group.keys()):
        n = counts[g]
        sums = by_group[g]
        mean_pre = sums["sum_pre"] / n
        mean_post = sums["sum_post"] / n
        mean_delta = sums["sum_delta"] / n
        summary.append({
            "group": g,
            "n": n,
            "mean_pre": mean_pre,
            "mean_post": mean_post,
            "mean_delta": mean_delta
        })

    return deltas, summary


def _load_group_summary_csv(path: Path) -> Optional[List[Dict[str, object]]]:
    rows = _read_csv_rows(path)
    if rows is None:
        return None
    normalized: List[Dict[str, object]] = []
    for r in rows:
        group = r.get("group")
        n = _coerce_int(r.get("n"))
        mean_pre = _coerce_float(r.get("mean_pre"))
        mean_post = _coerce_float(r.get("mean_post"))
        mean_delta = _coerce_float(r.get("mean_delta"))
        if group is None or n is None or mean_pre is None or mean_post is None or mean_delta is None:
            return None
        normalized.append({
            "group": group,
            "n": n,
            "mean_pre": mean_pre,
            "mean_post": mean_post,
            "mean_delta": mean_delta
        })
    return normalized


def _load_group_summary_json(path: Path) -> Optional[List[Dict[str, object]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    normalized: List[Dict[str, object]] = []
    for r in data:
        if not isinstance(r, dict):
            return None
        group = r.get("group")
        n = _coerce_int(r.get("n"))
        mean_pre = _coerce_float(r.get("mean_pre"))
        mean_post = _coerce_float(r.get("mean_post"))
        mean_delta = _coerce_float(r.get("mean_delta"))
        if group is None or n is None or mean_pre is None or mean_post is None or mean_delta is None:
            return None
        normalized.append({
            "group": group,
            "n": n,
            "mean_pre": mean_pre,
            "mean_post": mean_post,
            "mean_delta": mean_delta
        })
    return normalized


def _load_participant_deltas_csv(path: Path) -> Optional[List[Dict[str, object]]]:
    rows = _read_csv_rows(path)
    if rows is None:
        return None
    normalized: List[Dict[str, object]] = []
    for r in rows:
        pid = r.get("participant_id")
        sid = r.get("session_id")
        group = r.get("group")
        pre = _coerce_float(r.get("pre_empathy"))
        post = _coerce_float(r.get("post_empathy"))
        delta = _coerce_float(r.get("delta"))
        if pid is None or sid is None or group is None or pre is None or post is None or delta is None:
            return None
        normalized.append({
            "participant_id": pid,
            "session_id": sid,
            "group": group,
            "pre_empathy": pre,
            "post_empathy": post,
            "delta": delta
        })
    return normalized


def _check_header(path: Path, expected: List[str]) -> float:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
        if header is None:
            return 0.0
        return 1.0 if header == expected else 0.0
    except Exception:
        return 0.0


def _compare_group_summary(actual: List[Dict[str, object]], expected: List[Dict[str, object]]) -> bool:
    if actual is None or expected is None:
        return False
    actual_groups = {row["group"] for row in actual}
    expected_groups = {row["group"] for row in expected}
    if actual_groups != expected_groups:
        return False
    a_map = {row["group"]: row for row in actual}
    e_map = {row["group"]: row for row in expected}
    for g in expected_groups:
        a = a_map[g]
        e = e_map[g]
        if a["n"] != e["n"]:
            return False
        if not _approx_equal(float(a["mean_pre"]), float(e["mean_pre"])):
            return False
        if not _approx_equal(float(a["mean_post"]), float(e["mean_post"])):
            return False
        if not _approx_equal(float(a["mean_delta"]), float(e["mean_delta"])):
            return False
    return True


def _compare_participant_deltas(actual: List[Dict[str, object]], expected: List[Dict[str, object]]) -> bool:
    if actual is None or expected is None:
        return False
    if len(actual) != len(expected):
        return False
    a_map = {row["participant_id"]: row for row in actual}
    e_map = {row["participant_id"]: row for row in expected}
    if set(a_map.keys()) != set(e_map.keys()):
        return False
    for pid in e_map:
        a = a_map[pid]
        e = e_map[pid]
        if a.get("session_id") != e.get("session_id"):
            return False
        if a.get("group") != e.get("group"):
            return False
        if not _approx_equal(float(a["pre_empathy"]), float(e["pre_empathy"])):
            return False
        if not _approx_equal(float(a["post_empathy"]), float(e["post_empathy"])):
            return False
        if not _approx_equal(float(a["delta"]), float(e["delta"])):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_executes": 0.0,
        "group_summary_csv_present": 0.0,
        "group_summary_json_present": 0.0,
        "participant_deltas_csv_present": 0.0,
        "group_summary_csv_header_correct": 0.0,
        "participant_deltas_csv_header_correct": 0.0,
        "group_summary_csv_content_correct": 0.0,
        "group_summary_json_matches_csv": 0.0,
        "group_summary_json_content_correct": 0.0,
        "participant_deltas_content_correct": 0.0,
    }

    # Run the analysis script
    script_path = workspace / "scripts" / "analyze_empathy.py"
    if script_path.exists():
        try:
            res = subprocess.run([sys.executable, str(script_path)], cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            if res.returncode == 0:
                scores["script_executes"] = 1.0
            else:
                scores["script_executes"] = 0.0
        except Exception:
            scores["script_executes"] = 0.0
    else:
        scores["script_executes"] = 0.0

    out_dir = workspace / "output"
    group_csv = out_dir / "group_summary.csv"
    group_json = out_dir / "group_summary.json"
    deltas_csv = out_dir / "participant_deltas.csv"

    if group_csv.exists():
        scores["group_summary_csv_present"] = 1.0
    if group_json.exists():
        scores["group_summary_json_present"] = 1.0
    if deltas_csv.exists():
        scores["participant_deltas_csv_present"] = 1.0

    # Header checks
    expected_group_header = ["group", "n", "mean_pre", "mean_post", "mean_delta"]
    if group_csv.exists():
        scores["group_summary_csv_header_correct"] = _check_header(group_csv, expected_group_header)

    expected_deltas_header = ["participant_id", "session_id", "group", "pre_empathy", "post_empathy", "delta"]
    if deltas_csv.exists():
        scores["participant_deltas_csv_header_correct"] = _check_header(deltas_csv, expected_deltas_header)

    # Compute expected content
    expected_deltas, expected_summary = _compute_expected(workspace)

    # Content checks: group summary CSV
    actual_summary_csv = _load_group_summary_csv(group_csv) if group_csv.exists() else None
    if actual_summary_csv is not None and expected_summary is not None:
        if _compare_group_summary(actual_summary_csv, expected_summary):
            scores["group_summary_csv_content_correct"] = 1.0

    # Content checks: group summary JSON
    actual_summary_json = _load_group_summary_json(group_json) if group_json.exists() else None
    if actual_summary_json is not None and expected_summary is not None:
        if _compare_group_summary(actual_summary_json, expected_summary):
            scores["group_summary_json_content_correct"] = 1.0

    # JSON matches CSV content
    if actual_summary_json is not None and actual_summary_csv is not None:
        if _compare_group_summary(actual_summary_json, actual_summary_csv):
            scores["group_summary_json_matches_csv"] = 1.0

    # Content checks: participant deltas
    actual_deltas_csv = _load_participant_deltas_csv(deltas_csv) if deltas_csv.exists() else None
    if actual_deltas_csv is not None and expected_deltas is not None:
        if _compare_participant_deltas(actual_deltas_csv, expected_deltas):
            scores["participant_deltas_content_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()