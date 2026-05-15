import json
import csv
import sys
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_csv_dict(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames if reader.fieldnames is not None else []
            rows = [dict({k: v for k, v in row.items()}) for row in reader]
            return headers, rows
    except Exception:
        return None, None


def _compute_expected_top_athletes(data_csv: Path) -> Optional[List[Dict[str, str]]]:
    headers, rows = _safe_load_csv_dict(data_csv)
    if headers is None or rows is None:
        return None
    required_cols = ["id", "name", "city", "completed_challenges", "points", "avg_mile"]
    if any(col not in headers for col in required_cols):
        return None
    filtered = [r for r in rows if r.get("completed_challenges") == "yes"]

    def sort_key(r: Dict[str, str]):
        try:
            pts = int(r.get("points", "").strip())
        except Exception:
            pts = -10**12
        try:
            avg = float(r.get("avg_mile", "").strip())
        except Exception:
            avg = float("inf")
        name = r.get("name", "")
        # points desc, avg asc, name asc
        return (-pts, avg, name)

    sorted_rows = sorted(filtered, key=sort_key)
    top5 = sorted_rows[:5]
    out_rows: List[Dict[str, str]] = []
    for i, r in enumerate(top5, start=1):
        out_rows.append({
            "rank": str(i),
            "id": r.get("id", ""),
            "name": r.get("name", ""),
            "city": r.get("city", ""),
            "points": r.get("points", ""),
            "avg_mile": r.get("avg_mile", ""),
        })
    return out_rows


def _read_output_top_athletes(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    return _safe_load_csv_dict(path)


def _messages_split_two(text: str) -> Optional[List[str]]:
    content = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    # Ensure exactly one blank line separator and no extra blank lines
    if "\n\n\n" in content:
        return None
    parts = content.split("\n\n")
    if len(parts) != 2:
        return None
    # Ensure neither part contains additional blank-line separation
    if any("\n\n" in part for part in parts):
        return None
    return parts


def _contains_forbidden_words(text: str, words: List[str]) -> bool:
    low = text.lower()
    for w in words:
        if w.lower() in low:
            return True
    return False


def _line_matches_keywords(line: str, keywords: List[str]) -> bool:
    l = line.lower()
    return any(k.lower() in l for k in keywords)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "run_script_success": 0.0,
        "top_athletes_file_exists": 0.0,
        "top_athletes_header_correct": 0.0,
        "top_athletes_rows_count_5": 0.0,
        "top_athletes_content_correct": 0.0,
        "top_athletes_numeric_format_preserved": 0.0,
        "messages_file_exists": 0.0,
        "messages_structure_two_messages": 0.0,
        "message1_constraints": 0.0,
        "message2_constraints": 0.0,
        "fix_notes_exists": 0.0,
        "fix_notes_coverage": 0.0,
    }

    # 1) Attempt to run the processing script
    script_path = workspace / "scripts" / "process.py"
    if script_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                text=True,
            )
            if proc.returncode == 0:
                scores["run_script_success"] = 1.0
            else:
                scores["run_script_success"] = 0.0
        except Exception:
            scores["run_script_success"] = 0.0
    else:
        scores["run_script_success"] = 0.0

    # 2) Validate output/top_athletes.csv
    out_csv_path = workspace / "output" / "top_athletes.csv"
    if out_csv_path.exists():
        scores["top_athletes_file_exists"] = 1.0
        out_headers, out_rows = _read_output_top_athletes(out_csv_path)
        if out_headers is not None and out_rows is not None:
            expected_headers = ["rank", "id", "name", "city", "points", "avg_mile"]
            if out_headers == expected_headers:
                scores["top_athletes_header_correct"] = 1.0
            if len(out_rows) == 5:
                scores["top_athletes_rows_count_5"] = 1.0
            expected = _compute_expected_top_athletes(workspace / "data" / "submissions.csv")
            if expected is not None and out_headers == expected_headers:
                def _rows_to_tuples(rows: List[Dict[str, str]]) -> List[tuple]:
                    return [
                        (
                            str(r.get("rank", "")),
                            str(r.get("id", "")),
                            str(r.get("name", "")),
                            str(r.get("city", "")),
                            str(r.get("points", "")),
                            str(r.get("avg_mile", "")),
                        ) for r in rows
                    ]
                if _rows_to_tuples(out_rows) == _rows_to_tuples(expected):
                    scores["top_athletes_content_correct"] = 1.0
                    scores["top_athletes_numeric_format_preserved"] = 1.0
                else:
                    # Partial: check numeric formatting preservation per expected rows by id
                    expected_by_id = {e["id"]: e for e in expected}
                    preserved = True
                    for r in out_rows:
                        rid = r.get("id")
                        if rid in expected_by_id:
                            exp = expected_by_id[rid]
                            if str(r.get("points", "")) != str(exp.get("points", "")) or str(r.get("avg_mile", "")) != str(exp.get("avg_mile", "")):
                                preserved = False
                                break
                        else:
                            preserved = False
                            break
                    scores["top_athletes_numeric_format_preserved"] = 1.0 if preserved else 0.0
            else:
                scores["top_athletes_content_correct"] = 0.0
                scores["top_athletes_numeric_format_preserved"] = 0.0
        else:
            scores["top_athletes_header_correct"] = 0.0
            scores["top_athletes_rows_count_5"] = 0.0
            scores["top_athletes_content_correct"] = 0.0
            scores["top_athletes_numeric_format_preserved"] = 0.0
    else:
        scores["top_athletes_file_exists"] = 0.0

    # 3) Validate output/messages.md
    msg_path = workspace / "output" / "messages.md"
    if msg_path.exists():
        scores["messages_file_exists"] = 1.0
        text = _safe_read_text(msg_path)
        if text is not None:
            parts = _messages_split_two(text)
            if parts is not None and len(parts) == 2:
                scores["messages_structure_two_messages"] = 1.0
                m1, m2 = parts[0], parts[1]
                m1_ok = len(m1) <= 240
                m2_ok = len(m2) <= 240
                forbidden = ["dear", "sincerely"]
                m1_ok = m1_ok and (not _contains_forbidden_words(m1, forbidden))
                m2_ok = m2_ok and (not _contains_forbidden_words(m2, forbidden))
                # Placeholders
                m1_ok = m1_ok and ("{name}" in m1) and ("{rank}" in m1)
                # Keep original order: name before rank
                if "{name}" in m1 and "{rank}" in m1:
                    m1_ok = m1_ok and (m1.index("{name}") < m1.index("{rank}"))
                # Required phrases
                m1_ok = m1_ok and ("bold moves" in m1)
                m2_ok = m2_ok and ("{name}" in m2) and ("{rank}" not in m2)
                m2_ok = m2_ok and ("own your pace" in m2)
                scores["message1_constraints"] = 1.0 if m1_ok else 0.0
                scores["message2_constraints"] = 1.0 if m2_ok else 0.0
            else:
                scores["messages_structure_two_messages"] = 0.0
        else:
            scores["messages_structure_two_messages"] = 0.0
            scores["message1_constraints"] = 0.0
            scores["message2_constraints"] = 0.0
    else:
        scores["messages_file_exists"] = 0.0

    # 4) Validate output/fix_notes.txt
    notes_path = workspace / "output" / "fix_notes.txt"
    if notes_path.exists():
        scores["fix_notes_exists"] = 1.0
        notes_text = _safe_read_text(notes_path)
        if notes_text is not None:
            lines = [ln.strip() for ln in notes_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
            lines = [ln for ln in lines if ln != ""]
            if len(lines) >= 4:
                path_kw = ["path", "directory", "datas", "data/submissions.csv", "output/top_athletes.csv", "outputs", "output", "scripts/process.py", "file name", "filename"]
                delim_kw = ["delimiter", "comma", "semicolon", "schema", "header", "fieldnames", "columns", "avg_mile", "points", "rank", "place", "score", "avgMile"]
                filter_kw = ["filter", "completed_challenges", "completed", "yes", "true"]
                ranking_kw = ["rank", "sort", "descending", "ascending", "points", "avg_mile", "tie", "tiebreak", "tiebreaker", "name", "order"]
                has_path = any(_line_matches_keywords(ln, path_kw) for ln in lines)
                has_delim = any(_line_matches_keywords(ln, delim_kw) for ln in lines)
                has_filter = any(_line_matches_keywords(ln, filter_kw) for ln in lines)
                has_rank = any(_line_matches_keywords(ln, ranking_kw) for ln in lines)
                if has_path and has_delim and has_filter and has_rank:
                    scores["fix_notes_coverage"] = 1.0
                else:
                    scores["fix_notes_coverage"] = 0.0
            else:
                scores["fix_notes_coverage"] = 0.0
        else:
            scores["fix_notes_coverage"] = 0.0
    else:
        scores["fix_notes_exists"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()