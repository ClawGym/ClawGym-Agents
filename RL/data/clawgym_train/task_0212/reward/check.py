import json
import csv
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        items: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def _safe_load_lineup_csv(path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    try:
        res: Dict[str, Dict[str, str]] = {}
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = (row.get("show_id") or "").strip()
                if not sid:
                    continue
                res[sid] = {
                    "title": (row.get("title") or "").strip(),
                    "editor_email": (row.get("editor_email") or "").strip(),
                }
        return res
    except Exception:
        return None


def _build_expected_digest(transcripts: List[Dict[str, Any]], lineup: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for seg in transcripts:
        d = seg.get("date")
        if not d:
            continue
        by_date.setdefault(d, []).append(seg)

    digest_daily: List[Dict[str, Any]] = []
    for date in sorted(by_date.keys()):
        segs = by_date[date]
        shows_map: Dict[str, List[Dict[str, Any]]] = {}
        for s in segs:
            sid = s.get("show_id")
            if not sid:
                continue
            shows_map.setdefault(sid, []).append(s)

        shows_list = []
        for show_id in sorted(shows_map.keys()):
            s_list = shows_map[show_id]
            total_segments = len(s_list)
            total_duration = 0
            for s in s_list:
                try:
                    total_duration += int(s.get("duration_sec", 0))
                except Exception:
                    total_duration += 0

            hl: List[str] = []
            for s in s_list:
                highlights = s.get("highlights") or []
                if isinstance(highlights, list):
                    for h in highlights:
                        if isinstance(h, str) and h not in hl:
                            hl.append(h)
                            if len(hl) >= 3:
                                break
                if len(hl) >= 3:
                    break

            meta = lineup.get(show_id, {"title": show_id, "editor_email": ""})
            shows_list.append({
                "show_id": show_id,
                "title": meta.get("title", show_id),
                "total_segments": total_segments,
                "total_duration_sec": total_duration,
                "top_highlights": hl
            })
        digest_daily.append({"date": date, "shows": shows_list})

    return {"daily": digest_daily}


def _validate_digest_structure(d: Any) -> bool:
    if not isinstance(d, dict):
        return False
    daily = d.get("daily")
    if not isinstance(daily, list):
        return False
    for day in daily:
        if not isinstance(day, dict):
            return False
        date = day.get("date")
        shows = day.get("shows")
        if not isinstance(date, str):
            return False
        if not isinstance(shows, list):
            return False
        for show in shows:
            if not isinstance(show, dict):
                return False
            if not isinstance(show.get("show_id"), str):
                return False
            if not isinstance(show.get("title"), str):
                return False
            ts = show.get("total_segments")
            td = show.get("total_duration_sec")
            if not isinstance(ts, int) or isinstance(ts, bool):
                return False
            if not isinstance(td, int) or isinstance(td, bool):
                return False
            th = show.get("top_highlights")
            if not isinstance(th, list):
                return False
            if len(th) > 3:
                return False
            seen = set()
            for h in th:
                if not isinstance(h, str):
                    return False
                if h in seen:
                    return False
                seen.add(h)
    return True


def _digests_equal_strict(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return a == b


def _check_code_jsonl_handling(script_text: Optional[str]) -> bool:
    if not script_text:
        return False
    text = script_text
    lowered = text.lower()
    idx = lowered.find("def load_transcripts")
    segment = text
    if idx != -1:
        rest = text[idx:]
        next_def = rest.find("\ndef ")
        if next_def != -1:
            segment = rest[:next_def]
        else:
            segment = rest

    seg_lower = segment.lower()
    if "json.load(" in seg_lower:
        return False
    has_jsonloads = "json.loads(" in seg_lower
    has_line_iter = "for line in" in seg_lower or ".readlines()" in seg_lower or ".splitlines()" in seg_lower
    has_open = "open(" in seg_lower and ("'r'" in seg_lower or '"r"' in seg_lower)
    return has_open and (has_jsonloads or has_line_iter)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summarize_jsonl_logic_present": 0.0,
        "digest_file_exists_and_parseable": 0.0,
        "digest_structure_valid": 0.0,
        "digest_matches_expected": 0.0,
        "status_report_exists": 0.0,
        "status_contains_root_cause_and_fix": 0.0,
        "status_contains_before_after_verification": 0.0,
        "email_exists": 0.0,
        "email_addresses_editor_and_opening": 0.0,
        "email_includes_breakdown_per_date_show": 0.0,
        "email_has_next_steps": 0.0,
    }

    # Paths
    summarize_py = workspace / "scripts" / "summarize.py"
    transcripts_path = workspace / "input" / "transcripts.jsonl"
    lineup_path = workspace / "input" / "lineup.csv"
    digest_path = workspace / "output" / "daily_digest.json"
    status_path = workspace / "reports" / "status_summary.md"
    email_path = workspace / "drafts" / "email_bugfix_update.txt"

    # Check summarize.py for jsonl handling logic
    if summarize_py.exists() and summarize_py.is_file():
        script_text = _safe_read_text(summarize_py)
        if _check_code_jsonl_handling(script_text):
            scores["summarize_jsonl_logic_present"] = 1.0

    # Load inputs to compute expected digest
    transcripts = None
    lineup = None
    if transcripts_path.exists() and lineup_path.exists():
        transcripts = _safe_load_jsonl(transcripts_path)
        lineup = _safe_load_lineup_csv(lineup_path)

    expected_digest: Optional[Dict[str, Any]] = None
    if transcripts is not None and lineup is not None:
        expected_digest = _build_expected_digest(transcripts, lineup)

    # Load produced digest
    actual_digest = None
    if digest_path.exists() and digest_path.is_file():
        actual = _safe_load_json(digest_path)
        if actual is not None:
            scores["digest_file_exists_and_parseable"] = 1.0
            if _validate_digest_structure(actual):
                scores["digest_structure_valid"] = 1.0
            actual_digest = actual

    # Compare expected vs actual
    if expected_digest is not None and actual_digest is not None:
        if _digests_equal_strict(expected_digest, actual_digest):
            scores["digest_matches_expected"] = 1.0

    # Status report checks
    if status_path.exists() and status_path.is_file():
        scores["status_report_exists"] = 1.0
        status_text_raw = _safe_read_text(status_path) or ""
        status_text = status_text_raw.lower()
        mentions_file = "scripts/summarize.py" in status_text
        mentions_jsonl = any(tok in status_text for tok in ["jsonl", "json lines", "newline-delimited", "line-delimited", "ndjson"])
        mentions_parser_issue = ("json.load" in status_text) or (("json" in status_text) and ("array" in status_text))
        mentions_fix = any(tok in status_text for tok in ["fix", "fixed", "update", "updated", "change", "changed", "patch", "patched"])
        if mentions_file and mentions_jsonl and mentions_parser_issue and mentions_fix:
            scores["status_contains_root_cause_and_fix"] = 1.0

        # before/after verification: pre-fix and post-fix numbers
        pref = (("zero" in status_text and "transcript" in status_text) or ("empty" in status_text and "daily" in status_text))
        post_ok = False
        if expected_digest is not None:
            lines = [ln.lower() for ln in (status_text_raw.splitlines())]
            all_dates_present = True
            per_show_ok = True
            for day in expected_digest.get("daily", []):
                date = day.get("date", "")
                if date and (date.lower() not in status_text):
                    if date not in status_text_raw:
                        all_dates_present = False
                for show in day.get("shows", []):
                    show_id = show.get("show_id", "")
                    title = show.get("title", "")
                    ts = show.get("total_segments", None)
                    td = show.get("total_duration_sec", None)
                    if ts is None or td is None:
                        per_show_ok = False
                        continue
                    found_line = False
                    for ln in lines:
                        if show_id.lower() in ln or title.lower() in ln:
                            if str(ts) in ln and str(td) in ln:
                                found_line = True
                                break
                    if not found_line:
                        per_show_ok = False
                        break
                if not per_show_ok:
                    break
            post_ok = all_dates_present and per_show_ok
        if pref and post_ok:
            scores["status_contains_before_after_verification"] = 1.0

    # Email checks
    if email_path.exists() and email_path.is_file():
        scores["email_exists"] = 1.0
        email_text_raw = _safe_read_text(email_path) or ""
        email_text = email_text_raw.lower()

        to_ok = "managing_editor@example.org" in email_text
        fixed_ok = "fixed" in email_text and "daily digest" in email_text and ("regener" in email_text)
        if to_ok and fixed_ok:
            scores["email_addresses_editor_and_opening"] = 1.0

        breakdown_ok = False
        if expected_digest is not None:
            bullet_lines = []
            for ln in email_text_raw.splitlines():
                stripped = ln.lstrip()
                if stripped.startswith(("- ", "* ", "• ")):
                    bullet_lines.append(ln)
            all_ok = True
            for day in expected_digest.get("daily", []):
                for show in day.get("shows", []):
                    show_id = show.get("show_id", "")
                    title = show.get("title", "")
                    ts = show.get("total_segments", 0)
                    td = show.get("total_duration_sec", 0)
                    first_hl = ""
                    th = show.get("top_highlights") or []
                    if isinstance(th, list) and th:
                        first_hl = th[0]
                    found = False
                    for bl in bullet_lines:
                        bl_low = bl.lower()
                        if (show_id.lower() in bl_low) or (title.lower() in bl_low):
                            if str(ts) in bl and str(td) in bl:
                                if first_hl == "" or (first_hl in bl):
                                    found = True
                                    break
                    if not found:
                        all_ok = False
                        break
                if not all_ok:
                    break
            breakdown_ok = all_ok
        if breakdown_ok:
            scores["email_includes_breakdown_per_date_show"] = 1.0

        if ("next steps" in email_text) or ("next step" in email_text):
            scores["email_has_next_steps"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()