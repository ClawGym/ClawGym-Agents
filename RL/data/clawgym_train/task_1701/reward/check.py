import csv
import json
import re
import sys
import subprocess
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl_safe(path: Path) -> Optional[List[Dict[str, Any]]]:
    rows = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows
    except Exception:
        return None


def _parse_html_catalog(path: Path) -> Optional[List[Dict[str, str]]]:
    """
    Parse the single table in input HTML and return rows as list of dicts with keys:
    Title, Type, Phase, Release Date, Timeline Index, Runtime Minutes, Episodes, Avg Episode Minutes
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    # Extract tbody content
    m = re.search(r"<tbody[^>]*>(.*?)</tbody>", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    tbody = m.group(1)
    # Split rows
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.DOTALL | re.IGNORECASE)
    parsed: List[Dict[str, str]] = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
        cells = [unescape(re.sub(r"<.*?>", "", c, flags=re.DOTALL)).strip() for c in cells]
        # Expect exactly 8 columns
        if len(cells) != 8:
            return None
        parsed.append({
            "Title": cells[0],
            "Type": cells[1],
            "Phase": cells[2],
            "Release Date": cells[3],
            "Timeline Index": cells[4],
            "Runtime Minutes": cells[5],
            "Episodes": cells[6],
            "Avg Episode Minutes": cells[7],
        })
    return parsed


def _compute_expected_from_catalog(catalog_rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, int]]]:
    """
    Returns:
      - expected_timeline_rows (sorted by timeline index): dicts with timeline_index,title,type,phase,release_date,total_runtime_minutes
      - title_map: mapping title -> dict with total_runtime_minutes and other fields
      - phase_stats: mapping phase -> {titles, movies, shows, total_runtime_minutes}
    """
    timeline = []
    title_map: Dict[str, Dict[str, Any]] = {}
    phase_stats: Dict[str, Dict[str, int]] = {}
    for r in catalog_rows:
        t = r["Title"]
        typ = r["Type"]
        phase = r["Phase"]
        release = r["Release Date"]
        try:
            idx = int(r["Timeline Index"])
        except Exception:
            idx = None
        runtime_minutes = r["Runtime Minutes"].strip()
        episodes = r["Episodes"].strip()
        avg_ep = r["Avg Episode Minutes"].strip()
        if typ.lower() == "movie":
            try:
                total_runtime = int(runtime_minutes)
            except Exception:
                total_runtime = None
        else:
            try:
                total_runtime = int(episodes) * int(avg_ep)
            except Exception:
                total_runtime = None
        timeline.append({
            "timeline_index": idx,
            "title": t,
            "type": typ,
            "phase": phase,
            "release_date": release,
            "total_runtime_minutes": total_runtime,
        })
        title_map[t] = {
            "type": typ,
            "phase": phase,
            "release_date": release,
            "timeline_index": idx,
            "total_runtime_minutes": total_runtime,
        }
        if phase not in phase_stats:
            phase_stats[phase] = {"titles": 0, "movies": 0, "shows": 0, "total_runtime_minutes": 0}
        phase_stats[phase]["titles"] += 1
        if typ.lower() == "movie":
            phase_stats[phase]["movies"] += 1
        elif typ.lower() == "show":
            phase_stats[phase]["shows"] += 1
        if total_runtime is not None:
            phase_stats[phase]["total_runtime_minutes"] += total_runtime
    # sort by index ascending
    timeline_sorted = sorted(timeline, key=lambda x: (x["timeline_index"] if x["timeline_index"] is not None else 1_000_000))
    return timeline_sorted, title_map, phase_stats


def _load_csv_as_rows(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                return None
            rows = [row for row in reader]
            return fieldnames, rows
    except Exception:
        return None


def _parse_iso_datetime_with_tz(s: str) -> Optional[datetime]:
    try:
        # Python 3.11: datetime.fromisoformat supports timezone offsets
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _find_entries_in_validation_report(obj: Any) -> Optional[List[Dict[str, Any]]]:
    # Prefer obj["entries"] if present and looks like list of dicts with required keys
    required_keys = {"title", "expected_runtime_minutes", "observed_minutes", "difference_minutes", "percent_diff", "status"}
    if isinstance(obj, dict):
        if "entries" in obj and isinstance(obj["entries"], list):
            if all(isinstance(x, dict) for x in obj["entries"]):
                if all(required_keys.issubset(set(x.keys())) for x in obj["entries"]):
                    return obj["entries"]
        # Search any list value with required structure
        for v in obj.values():
            if isinstance(v, list) and all(isinstance(x, dict) for x in v):
                if all(required_keys.issubset(set(x.keys())) for x in v):
                    return v
    elif isinstance(obj, list):
        if all(isinstance(x, dict) for x in obj) and all(required_keys.issubset(set(x.keys())) for x in obj):
            return obj
    return None


def _find_summary_in_validation_report(obj: Any) -> Optional[Dict[str, Any]]:
    required_keys = {"total_titles", "ok_count", "mismatch_count", "tolerance_percent"}
    if isinstance(obj, dict):
        if "summary" in obj and isinstance(obj["summary"], dict):
            s = obj["summary"]
            if required_keys.issubset(set(s.keys())):
                return s
        # Search any dict value with required keys
        for v in obj.values():
            if isinstance(v, dict) and required_keys.issubset(set(v.keys())):
                return v
    return None


def _word_count(text: str) -> int:
    tokens = re.findall(r"\b[\w\.]+\b", text, flags=re.UNICODE)
    return len(tokens)


def _tokenize_words(text: str) -> List[str]:
    # include numbers and words, lowercase
    return [t.lower() for t in re.findall(r"\b[\w\.]+\b", text, flags=re.UNICODE)]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_exists": 0.0,
        "script_runs_success": 0.0,
        "timeline_csv_header_and_order": 0.0,
        "timeline_csv_values": 0.0,
        "phase_stats_content": 0.0,
        "validation_entries_content": 0.0,
        "validation_summary_content": 0.0,
        "note_story_order_exact_line": 0.0,
        "note_word_count_under_200": 0.0,
        "note_includes_totals_minutes_hours": 0.0,
        "note_includes_top3_titles": 0.0,
    }

    # Paths
    script_path = workspace / "scripts" / "mcu_report.py"
    input_catalog = workspace / "input" / "marvel_catalog.html"
    input_watch_log = workspace / "input" / "watch_log.jsonl"
    input_rough_note = workspace / "input" / "rough_note.txt"
    outputs_dir = workspace / "outputs"
    timeline_csv_path = outputs_dir / "mcu_timeline.csv"
    phase_stats_path = outputs_dir / "phase_stats.json"
    validation_report_path = outputs_dir / "validation_report.json"
    note_cleaned_path = outputs_dir / "note_cleaned.txt"

    # Baseline check: script exists
    if script_path.is_file():
        scores["script_exists"] = 1.0

        # Attempt to run the script
        try:
            # Use sys.executable for portability
            cmd = [
                sys.executable,
                str(script_path),
                str(input_catalog),
                str(input_watch_log),
                str(input_rough_note),
                str(outputs_dir),
            ]
            result = subprocess.run(cmd, cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            if result.returncode == 0:
                scores["script_runs_success"] = 1.0
        except Exception:
            pass

    # Load and parse input catalog for expected values
    catalog_rows = _parse_html_catalog(input_catalog)
    if catalog_rows is None:
        # Cannot compute expectations; subsequent checks will remain 0.0
        return scores

    expected_timeline, title_map, expected_phase_stats = _compute_expected_from_catalog(catalog_rows)

    # Check timeline CSV: header and order
    csv_loaded = _load_csv_as_rows(timeline_csv_path)
    if csv_loaded is not None:
        headers, rows = csv_loaded
        expected_headers = ["timeline_index", "title", "type", "phase", "release_date", "total_runtime_minutes"]
        if headers == expected_headers and len(rows) == len(expected_timeline):
            # Check sorted by timeline_index
            try:
                timeline_indices = [int(r["timeline_index"]) for r in rows]
                if timeline_indices == sorted(timeline_indices):
                    scores["timeline_csv_header_and_order"] = 1.0
            except Exception:
                pass

        # Check values equality
        ok_values = True
        if len(rows) != len(expected_timeline):
            ok_values = False
        else:
            for i, row in enumerate(rows):
                exp = expected_timeline[i]
                try:
                    # Compare title, type, release_date as exact strings
                    if row.get("title", "") != exp["title"]:
                        ok_values = False
                        break
                    if row.get("type", "") != exp["type"]:
                        ok_values = False
                        break
                    if row.get("release_date", "") != exp["release_date"]:
                        ok_values = False
                        break
                    # Compare numeric fields
                    if int(row.get("timeline_index", "-999999")) != int(exp["timeline_index"]):
                        ok_values = False
                        break
                    if int(row.get("phase", "-999999")) != int(exp["phase"]):
                        ok_values = False
                        break
                    if int(row.get("total_runtime_minutes", "-999999")) != int(exp["total_runtime_minutes"]):
                        ok_values = False
                        break
                except Exception:
                    ok_values = False
                    break
        if ok_values:
            scores["timeline_csv_values"] = 1.0

    # Check phase stats JSON content
    phase_json = _load_json_safe(phase_stats_path)
    if phase_json is not None:
        # Accept either list of objects or dict keyed by phase
        found_stats: Dict[str, Dict[str, Any]] = {}
        if isinstance(phase_json, list):
            for item in phase_json:
                if not isinstance(item, dict):
                    found_stats = {}
                    break
                if not {"phase", "titles", "movies", "shows", "total_runtime_minutes"}.issubset(item.keys()):
                    found_stats = {}
                    break
                phase_val = str(item["phase"])
                found_stats[phase_val] = {
                    "titles": item["titles"],
                    "movies": item["movies"],
                    "shows": item["shows"],
                    "total_runtime_minutes": item["total_runtime_minutes"],
                }
        elif isinstance(phase_json, dict):
            # Dict keyed by phase
            temp_stats: Dict[str, Dict[str, Any]] = {}
            valid = True
            for k, v in phase_json.items():
                if not isinstance(v, dict):
                    valid = False
                    break
                if not {"phase", "titles", "movies", "shows", "total_runtime_minutes"}.issubset(v.keys()):
                    valid = False
                    break
                phase_val = str(v["phase"])
                if str(k) != phase_val:
                    # If key doesn't match phase, still accept but use the phase in object
                    pass
                temp_stats[phase_val] = {
                    "titles": v["titles"],
                    "movies": v["movies"],
                    "shows": v["shows"],
                    "total_runtime_minutes": v["total_runtime_minutes"],
                }
            if valid:
                found_stats = temp_stats
        # Compare with expected; require exact phase set and matching counts
        try:
            exp_phases = set(expected_phase_stats.keys())
            found_phases = set(found_stats.keys())
            if found_phases == exp_phases:
                match = True
                for ph in exp_phases:
                    exp = expected_phase_stats[ph]
                    f = found_stats.get(ph, {})
                    if not (
                        int(f.get("titles", -1)) == int(exp["titles"]) and
                        int(f.get("movies", -1)) == int(exp["movies"]) and
                        int(f.get("shows", -1)) == int(exp["shows"]) and
                        int(f.get("total_runtime_minutes", -1)) == int(exp["total_runtime_minutes"])
                    ):
                        match = False
                        break
                if match:
                    scores["phase_stats_content"] = 1.0
        except Exception:
            pass

    # Check validation_report.json
    validation_json = _load_json_safe(validation_report_path)
    if validation_json is not None:
        entries = _find_entries_in_validation_report(validation_json)
        summary = _find_summary_in_validation_report(validation_json)

        # Compute expected from watch_log.jsonl and catalog
        logs = _load_jsonl_safe(input_watch_log)
        expected_entries_map: Dict[str, Dict[str, Any]] = {}
        if logs is not None:
            for rec in logs:
                title = rec.get("title")
                started_at = rec.get("started_at")
                finished_at = rec.get("finished_at")
                if title is None or started_at is None or finished_at is None:
                    expected_entries_map = {}
                    break
                dt_start = _parse_iso_datetime_with_tz(started_at)
                dt_end = _parse_iso_datetime_with_tz(finished_at)
                if dt_start is None or dt_end is None:
                    expected_entries_map = {}
                    break
                observed_minutes = int(round((dt_end - dt_start).total_seconds() / 60.0))
                expected_info = title_map.get(title)
                if expected_info is None or expected_info.get("total_runtime_minutes") is None:
                    expected_entries_map = {}
                    break
                expected_minutes = int(expected_info["total_runtime_minutes"])
                diff = observed_minutes - expected_minutes
                percent = (abs(diff) / expected_minutes * 100.0) if expected_minutes != 0 else 0.0
                status = "ok" if abs(percent) <= 5.0 else "mismatch"
                expected_entries_map[title] = {
                    "expected_runtime_minutes": expected_minutes,
                    "observed_minutes": observed_minutes,
                    "difference_minutes": diff,
                    "percent_diff": percent,
                    "status": status,
                }

        # Validate entries
        entries_ok = False
        if entries is not None and expected_entries_map:
            try:
                # Map actual entries by title
                actual_map: Dict[str, Dict[str, Any]] = {}
                for e in entries:
                    t = e.get("title")
                    if not isinstance(t, str):
                        actual_map = {}
                        break
                    actual_map[t] = e
                if set(actual_map.keys()) == set(expected_entries_map.keys()):
                    per_ok = True
                    for t, exp in expected_entries_map.items():
                        act = actual_map[t]
                        # Check expected_runtime_minutes
                        if int(act.get("expected_runtime_minutes", -9999)) != int(exp["expected_runtime_minutes"]):
                            per_ok = False
                            break
                        if int(act.get("observed_minutes", -9999)) != int(exp["observed_minutes"]):
                            per_ok = False
                            break
                        # Allow either sign for difference_minutes but magnitude must match
                        try:
                            act_diff = int(act.get("difference_minutes", -9999))
                        except Exception:
                            per_ok = False
                            break
                        if abs(act_diff) != abs(int(exp["difference_minutes"])):
                            per_ok = False
                            break
                        # percent_diff within small tolerance (0.05)
                        try:
                            act_pct = float(act.get("percent_diff"))
                        except Exception:
                            per_ok = False
                            break
                        if abs(act_pct - float(exp["percent_diff"])) > 0.05:
                            per_ok = False
                            break
                        # status strict
                        if str(act.get("status")) != str(exp["status"]):
                            per_ok = False
                            break
                    if per_ok:
                        entries_ok = True
            except Exception:
                entries_ok = False
        if entries_ok:
            scores["validation_entries_content"] = 1.0

        # Validate summary
        summary_ok = False
        if summary is not None and expected_entries_map:
            try:
                total_titles = len(expected_entries_map)
                ok_count = sum(1 for v in expected_entries_map.values() if v["status"] == "ok")
                mismatch_count = sum(1 for v in expected_entries_map.values() if v["status"] == "mismatch")
                tol = 5
                if (
                    int(summary.get("total_titles", -1)) == total_titles and
                    int(summary.get("ok_count", -1)) == ok_count and
                    int(summary.get("mismatch_count", -1)) == mismatch_count and
                    int(summary.get("tolerance_percent", -1)) == tol
                ):
                    summary_ok = True
            except Exception:
                summary_ok = False
        if summary_ok:
            scores["validation_summary_content"] = 1.0

    # Check note_cleaned.txt
    note_text = _read_text_safe(note_cleaned_path)
    if note_text is not None:
        # Story order exact line
        exact_story_line = "Captain America: The First Avenger -> Captain Marvel -> Iron Man -> The Avengers -> WandaVision -> The Falcon and the Winter Soldier"
        lines = [ln.strip() for ln in note_text.splitlines()]
        if any(ln == exact_story_line for ln in lines):
            scores["note_story_order_exact_line"] = 1.0

        # Word count under 200
        if _word_count(note_text) <= 200:
            scores["note_word_count_under_200"] = 1.0

        # Totals check: total number of titles, total runtime in minutes and hours rounded to one decimal
        total_titles_expected = len(title_map)
        total_minutes_expected = sum(int(v["total_runtime_minutes"]) for v in title_map.values())
        hours_rounded = round(total_minutes_expected / 60.0 + 1e-8, 1)
        tokens_lower = _tokenize_words(note_text)
        has_title_count = (str(total_titles_expected) in tokens_lower) or ("six" in tokens_lower)
        has_minutes = str(total_minutes_expected) in tokens_lower
        has_hours = f"{hours_rounded:.1f}".rstrip('0').rstrip('.') if '.' in f"{hours_rounded:.1f}" else f"{hours_rounded:.1f}"
        # Tokens may split decimals; also check substring presence
        has_hours_number = (f"{hours_rounded:.1f}" in note_text) or (has_hours in note_text)
        if has_title_count and has_minutes and has_hours_number:
            scores["note_includes_totals_minutes_hours"] = 1.0

        # Top 3 longest titles inclusion
        # Determine top 3 by total_runtime_minutes
        sorted_by_len = sorted(title_map.items(), key=lambda kv: int(kv[1]["total_runtime_minutes"]), reverse=True)
        top3_titles = [kv[0] for kv in sorted_by_len[:3]]
        # Require all three names to appear in the note text
        if all(t in note_text for t in top3_titles):
            scores["note_includes_top3_titles"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()