import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


# Constants derived from task materials
EXPECTED_QUERIES = [
    "Steve Whitmire",
    "Steve Whitmire interview",
    "Muppets puppeteer Whitmire",
    "Kermit performance Whitmire",
]
CLASSIFICATION_KEYWORDS = {
    "To contact": [
        "event",
        "appearance",
        "festival",
        "panel",
        "talk",
        "conference",
        "live",
    ],
    "To share": [
        "interview",
        "video",
        "podcast",
        "article",
        "feature",
        "profile",
        "q&a",
    ],
}
RANKING_PARAMS = {
    "per_result_limit": 20,
    "base_score_for_rank_1": 50,
    "title_keyword_bonus": 5,
    "primary_name_bonus": 3,
}


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _today_date_str() -> str:
    now = datetime.now()
    return now.strftime("%Y-%m-%d")


def _find_today_search_dir(workspace: Path, date_str: str) -> Path:
    return workspace / "out" / "search" / date_str


def _normalize_url(url: str) -> str:
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
        path = p.path or ""
        if not path:
            path = "/"
        return f"{host}{path}"
    except Exception:
        return url.strip().lower()


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _compute_score(query_term: str, engine_rank: int, title: str) -> Optional[int]:
    if engine_rank is None:
        return None
    base = RANKING_PARAMS["base_score_for_rank_1"]
    bonus_kw = RANKING_PARAMS["title_keyword_bonus"]
    primary_bonus = RANKING_PARAMS["primary_name_bonus"]
    title_lower = (title or "").lower()
    tokens = re.findall(r"[a-zA-Z0-9]+", query_term or "")
    token_set = {t.lower() for t in tokens if t}
    kw_count = 0
    for t in token_set:
        if t and t in title_lower:
            kw_count += 1
    name_bonus = primary_bonus if ("steve" in title_lower or "whitmire" in title_lower) else 0
    score = base - (engine_rank - 1) + (bonus_kw * kw_count) + name_bonus
    return score


def _classify_title(title: str) -> str:
    tl = (title or "").lower()
    for kw in CLASSIFICATION_KEYWORDS["To contact"]:
        if kw.lower() in tl:
            return "To contact"
    for kw in CLASSIFICATION_KEYWORDS["To share"]:
        if kw.lower() in tl:
            return "To share"
    return "To review"


def _parse_meeting_notes_sections(md_text: str) -> Dict[str, List[str]]:
    lines = md_text.splitlines()
    sections: Dict[str, List[str]] = {"Top Items": [], "Action Items": [], "Attendees Checklist": []}
    current = None
    for line in lines:
        stripped = line.strip()
        if stripped == "Top Items":
            current = "Top Items"
            continue
        if stripped == "Action Items":
            current = "Action Items"
            continue
        if stripped == "Attendees Checklist":
            current = "Attendees Checklist"
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _extract_notes_summary_values(md_text: str) -> Tuple[Optional[int], Optional[List[str]], Optional[int], Optional[str]]:
    m_date = re.search(r"#\s*Weekly Planning Notes\s*—\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", md_text)
    date_str = m_date.group(1) if m_date else None

    m_q = re.search(r"Queries run:\s*([0-9]+)", md_text)
    q_count = int(m_q.group(1)) if m_q else None

    m_eng = re.search(r"Search engines used:\s*(.+)", md_text)
    engines_list = None
    if m_eng:
        eng_str = m_eng.group(1).strip()
        engines_list = [e.strip() for e in eng_str.split(",") if e.strip()]

    m_res = re.search(r"Total results collected:\s*([0-9]+)", md_text)
    result_count = int(m_res.group(1)) if m_res else None

    return q_count, engines_list, result_count, date_str


def _get_latest_run_log_for_date(logs_dir: Path, date_str: str) -> Optional[Path]:
    if not logs_dir.exists():
        return None
    pattern_prefix = f"run_{date_str}_"
    candidates = [p for p in logs_dir.glob("run_*.log") if p.name.startswith(pattern_prefix)]
    if not candidates:
        return None
    return sorted(candidates)[-1]


def _parse_queries_json_structure(obj: Any) -> Tuple[Optional[List[str]], Optional[List[str]], Optional[Dict[str, Dict[str, int]]]]:
    if not isinstance(obj, dict):
        return None, None, None
    engines = None
    queries = None
    per_query_counts = None

    if "engines" in obj and isinstance(obj["engines"], list):
        engines = [str(x) for x in obj["engines"]]
    if "queries" in obj and isinstance(obj["queries"], list):
        queries = [str(x) for x in obj["queries"]]
    candidate_keys = ["per_query_counts", "per_query", "query_counts", "counts"]
    for key in candidate_keys:
        if key in obj and isinstance(obj[key], dict):
            d = obj[key]
            ok = True
            conv: Dict[str, Dict[str, int]] = {}
            for k, v in d.items():
                if not isinstance(v, dict):
                    ok = False
                    break
                before = v.get("before")
                after = v.get("after")
                if not isinstance(before, int) or not isinstance(after, int):
                    ok = False
                    break
                conv[str(k)] = {"before": before, "after": after}
            if ok:
                per_query_counts = conv
                break

    return queries, engines, per_query_counts


def _compute_next_monday_0900() -> str:
    now = datetime.now()
    days_ahead = (0 - now.weekday()) % 7
    next_monday = now + timedelta(days=days_ahead)
    candidate = next_monday.replace(hour=9, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=7)
    return candidate.strftime("%Y-%m-%dT%H:%M")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_exists_weekly_whitmire_digest": 0.0,
        "outputs_results_csv_today_exists_and_schema": 0.0,
        "outputs_top10_csv_today_exists_and_schema": 0.0,
        "outputs_queries_json_today_exists_and_schema": 0.0,
        "result_count_matches_json_post_dedup_sum": 0.0,
        "dedup_normalized_url_no_duplicates": 0.0,
        "scoring_formula_correct_for_results": 0.0,
        "sorting_order_correct": 0.0,
        "top10_subset_of_results_and_classification": 0.0,
        "logs_exist_and_include_engines_and_queries": 0.0,
        "meeting_notes_exists_and_placeholders_filled": 0.0,
        "meeting_notes_counts_match_json_and_results": 0.0,
        "meeting_notes_top_items_referenced": 0.0,
        "meeting_notes_action_items_assigned_by_role": 0.0,
        "meeting_notes_attendee_checklist_complete": 0.0,
        "schedule_shell_script_cron_line_valid": 0.0,
        "schedule_powershell_task_valid": 0.0,
        "next_run_txt_exists_and_has_next_monday_0900": 0.0,
    }

    date_str = _today_date_str()
    out_search_dir = _find_today_search_dir(workspace, date_str)
    results_csv = out_search_dir / "results.csv"
    top10_csv = out_search_dir / "top10.csv"
    queries_json_path = out_search_dir / "queries.json"
    notes_path = workspace / "out" / "notes" / f"meeting_notes_{date_str}.md"
    logs_dir = workspace / "out" / "logs"
    schedule_dir = workspace / "out" / "schedule"
    next_run_path = schedule_dir / "next_run.txt"
    attendees_csv_path = workspace / "input" / "attendees.csv"

    # 1. Weekly digest script existence
    if (workspace / "scripts" / "weekly_whitmire_digest.py").is_file():
        scores["script_exists_weekly_whitmire_digest"] = 1.0

    # 2. Results CSV existence and schema
    results_rows = _read_csv_dicts(results_csv) if results_csv.exists() else None
    expected_results_cols = ["query_term", "engine_name", "engine_rank", "title", "url", "score"]
    if results_rows is not None and len(results_rows) > 0:
        header_ok = True
        with results_csv.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except Exception:
                header = []
        for col in expected_results_cols:
            if col not in header:
                header_ok = False
                break
        if header_ok:
            scores["outputs_results_csv_today_exists_and_schema"] = 1.0

    # 3. Top10 CSV existence and schema
    top10_rows = _read_csv_dicts(top10_csv) if top10_csv.exists() else None
    expected_top10_cols = expected_results_cols + ["classification"]
    if top10_rows is not None and len(top10_rows) > 0:
        header_ok = True
        with top10_csv.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except Exception:
                header = []
        for col in expected_top10_cols:
            if col not in header:
                header_ok = False
                break
        if header_ok:
            scores["outputs_top10_csv_today_exists_and_schema"] = 1.0

    # 4. Queries JSON existence and schema
    queries_obj = _load_json(queries_json_path) if queries_json_path.exists() else None
    parsed_queries = None
    parsed_engines = None
    per_query_counts = None
    queries_json_schema_ok = False
    if queries_obj is not None:
        parsed_queries, parsed_engines, per_query_counts = _parse_queries_json_structure(queries_obj)
        timestamp_ok = isinstance(queries_obj.get("timestamp"), str)
        engines_ok = isinstance(parsed_engines, list) and len(parsed_engines) >= 2
        queries_ok = isinstance(parsed_queries, list) and set(parsed_queries) == set(EXPECTED_QUERIES) and len(parsed_queries) == len(EXPECTED_QUERIES)
        per_query_ok = isinstance(per_query_counts, dict) and len(per_query_counts) == len(EXPECTED_QUERIES)
        if timestamp_ok and engines_ok and queries_ok and per_query_ok:
            queries_json_schema_ok = True
            scores["outputs_queries_json_today_exists_and_schema"] = 1.0

    # 5. Result count matches JSON post-dedup sum
    if queries_json_schema_ok and results_rows is not None:
        after_sum = sum(v.get("after", 0) for v in per_query_counts.values())
        if after_sum == len(results_rows):
            scores["result_count_matches_json_post_dedup_sum"] = 1.0

    # 6. Dedup by normalized URL
    if results_rows is not None:
        norms = [_normalize_url(r.get("url", "")) for r in results_rows]
        if len(norms) == len(set(norms)):
            scores["dedup_normalized_url_no_duplicates"] = 1.0

    # 7. Scoring formula correct for results
    scoring_ok = True
    if results_rows is not None:
        for r in results_rows:
            q = r.get("query_term", "")
            title = r.get("title", "")
            erank = _safe_int(r.get("engine_rank"))
            claimed_score = _safe_int(r.get("score"))
            recomputed = _compute_score(q, erank if erank is not None else -1, title)
            if claimed_score is None or recomputed is None or claimed_score != recomputed:
                scoring_ok = False
                break
        if scoring_ok:
            scores["scoring_formula_correct_for_results"] = 1.0

    # 8. Sorting order correct (results.csv is the ranked list)
    if results_rows is not None:
        is_sorted = True
        for i in range(1, len(results_rows)):
            prev = results_rows[i - 1]
            curr = results_rows[i]
            ps = _safe_int(prev.get("score"))
            cs = _safe_int(curr.get("score"))
            per = _safe_int(prev.get("engine_rank"))
            cer = _safe_int(curr.get("engine_rank"))
            if ps is None or cs is None or per is None or cer is None:
                is_sorted = False
                break
            if cs > ps:
                is_sorted = False
                break
            if cs == ps and cer < per:
                is_sorted = False
                break
        if is_sorted and len(results_rows) >= 1:
            scores["sorting_order_correct"] = 1.0

    # 9. Top10 subset and classification
    if results_rows is not None and top10_rows is not None:
        n = min(10, len(results_rows))
        subset_ok = len(top10_rows) == n
        for i in range(min(n, len(top10_rows))):
            rr = results_rows[i]
            tr = top10_rows[i]
            for col in expected_results_cols:
                if str(rr.get(col, "")).strip() != str(tr.get(col, "")).strip():
                    subset_ok = False
                    break
            if not subset_ok:
                break
            cls = tr.get("classification", "").strip()
            recomputed_cls = _classify_title(tr.get("title", ""))
            if cls.lower() != recomputed_cls.lower():
                subset_ok = False
                break
        if subset_ok:
            scores["top10_subset_of_results_and_classification"] = 1.0

    # 10. Logs exist and include engines and queries
    logs_ok = False
    latest_log = _get_latest_run_log_for_date(logs_dir, date_str)
    if latest_log and latest_log.exists():
        content = _read_text(latest_log) or ""
        engines_in_json = parsed_engines if parsed_engines else []
        engines_present = all(e in content for e in engines_in_json) if engines_in_json else False
        queries_present = all(q in content for q in EXPECTED_QUERIES)
        logs_ok = engines_present and queries_present
    if logs_ok:
        scores["logs_exist_and_include_engines_and_queries"] = 1.0

    # Meeting notes checks
    notes_text = _read_text(notes_path) if notes_path.exists() else None
    if notes_text:
        # 11. Meeting notes placeholders filled
        if "{{" not in notes_text and "}}" not in notes_text:
            scores["meeting_notes_exists_and_placeholders_filled"] = 1.0

        # 12. Counts match json and results
        q_count, engines_list, result_count, date_in_notes = _extract_notes_summary_values(notes_text)
        counts_ok = True
        if queries_json_schema_ok:
            if q_count != len(parsed_queries or []):
                counts_ok = False
            if engines_list is None or set([e.strip() for e in engines_list]) != set(parsed_engines or []):
                counts_ok = False
        if results_rows is not None:
            if result_count != len(results_rows):
                counts_ok = False
        if date_in_notes != date_str:
            counts_ok = False
        if counts_ok:
            scores["meeting_notes_counts_match_json_and_results"] = 1.0

        sections = _parse_meeting_notes_sections(notes_text)

        # 13. Top items referenced
        top_items_ok = False
        if top10_rows is not None:
            top_lines = "\n".join(sections.get("Top Items", []))
            if top_lines:
                top_items_ok = True
                for row in top10_rows:
                    title = row.get("title", "")
                    url = row.get("url", "")
                    if title not in top_lines or url not in top_lines:
                        top_items_ok = False
                        break
        if top_items_ok:
            scores["meeting_notes_top_items_referenced"] = 1.0

        # 14. Action items assigned by role
        action_ok = False
        action_lines = sections.get("Action Items", [])
        if top10_rows is not None and action_lines:
            action_ok = True
            attendees_rows = _read_csv_dicts(attendees_csv_path) or []
            by_role: Dict[str, List[Dict[str, str]]] = {"Outreach": [], "Social": [], "Research": []}
            for r in attendees_rows:
                role = (r.get("role") or "").strip()
                if role in by_role:
                    by_role[role].append(r)
            idx_map = {"Outreach": 0, "Social": 0, "Research": 0}
            for row in top10_rows:
                title = row.get("title", "")
                classification = (row.get("classification", "")).strip().lower()
                if classification == "to contact":
                    role = "Outreach"
                    cls_label = "To contact"
                elif classification == "to share":
                    role = "Social"
                    cls_label = "To share"
                else:
                    role = "Research"
                    cls_label = "To review"
                role_list = by_role.get(role, [])
                if not role_list:
                    action_ok = False
                    break
                assignee = role_list[idx_map[role] % len(role_list)]
                idx_map[role] += 1
                expected_email = (assignee.get("email") or "").strip()
                found = False
                for line in action_lines:
                    if title in line and expected_email in line and cls_label.lower() in line.lower():
                        found = True
                        break
                if not found:
                    action_ok = False
                    break
        if action_ok:
            scores["meeting_notes_action_items_assigned_by_role"] = 1.0

        # 15. Attendee checklist complete
        attendee_check_ok = False
        attendee_lines = "\n".join(sections.get("Attendees Checklist", []))
        if attendee_lines:
            attendees_rows = _read_csv_dicts(attendees_csv_path) or []
            attendee_check_ok = True
            for r in attendees_rows:
                name = (r.get("name") or "").strip()
                if name and name not in attendee_lines:
                    attendee_check_ok = False
                    break
        if attendee_check_ok:
            scores["meeting_notes_attendee_checklist_complete"] = 1.0

    # 16. Schedule shell script cron line valid
    schedule_sh = workspace / "scripts" / "schedule_weekly.sh"
    sh_text = _read_text(schedule_sh) if schedule_sh.exists() else None
    if sh_text:
        if ("0 9 * * 1" in sh_text and "weekly_whitmire_digest.py" in sh_text and "crontab" in sh_text and "out/logs/cron.log" in sh_text):
            scores["schedule_shell_script_cron_line_valid"] = 1.0

    # 17. Schedule PowerShell task valid
    schedule_ps1 = workspace / "scripts" / "register_weekly_task.ps1"
    ps1_text = _read_text(schedule_ps1) if schedule_ps1.exists() else None
    if ps1_text:
        day_ok = ("MON" in ps1_text.upper()) or ("MONDAY" in ps1_text.upper())
        time_ok = ("09:00" in ps1_text) or ("09:00:00" in ps1_text)
        reg_ok = ("Register-ScheduledTask" in ps1_text) or ("schtasks" in ps1_text.lower())
        script_ok = "weekly_whitmire_digest.py" in ps1_text
        log_ok = "out/logs/schtask.log" in ps1_text
        if day_ok and time_ok and reg_ok and script_ok and log_ok:
            scores["schedule_powershell_task_valid"] = 1.0

    # 18. next_run.txt exists and contains next Monday at 09:00
    nr_text = _read_text(next_run_path) if next_run_path.exists() else None
    if nr_text:
        line = nr_text.strip().splitlines()[0] if nr_text.strip() else ""
        expected_timestamp = _compute_next_monday_0900()
        ts_ok = expected_timestamp in line
        cmd_ok = "weekly_whitmire_digest.py" in line
        if ts_ok and cmd_ok:
            scores["next_run_txt_exists_and_has_next_monday_0900"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()