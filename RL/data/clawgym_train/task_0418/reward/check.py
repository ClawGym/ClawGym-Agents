import json
import re
import sys
from pathlib import Path
from datetime import datetime


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        text = _read_text(path)
        if not text:
            return None
        return json.loads(text)
    except Exception:
        return None


def _parse_watchlist_yaml(path: Path):
    text = _read_text(path)
    if not text:
        return None, None
    topics = []
    selectors = []
    lines = text.splitlines()
    state = None  # None, 'topics', 'selectors'
    current_selector = None
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if stripped.startswith("#") or stripped == "":
            continue
        if stripped.startswith("topics:"):
            state = "topics"
            continue
        if stripped.startswith("source_selectors:"):
            state = "selectors"
            continue
        if state == "topics":
            m = re.match(r'^\s*-\s*(?P<val>.+?)\s*$', line)
            if m:
                val = m.group("val").strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                topics.append(val)
        elif state == "selectors":
            if re.match(r'^\s*-\s+label:', line):
                label_val = line.split("label:", 1)[1].strip()
                if (label_val.startswith('"') and label_val.endswith('"')) or (label_val.startswith("'") and label_val.endswith("'")):
                    label_val = label_val[1:-1]
                current_selector = {"label": label_val, "query_modifier": None}
                selectors.append(current_selector)
            elif "query_modifier:" in line and current_selector is not None and current_selector.get("query_modifier") is None:
                qv = line.split("query_modifier:", 1)[1].strip()
                if (qv.startswith('"') and qv.endswith('"')) or (qv.startswith("'") and qv.endswith("'")):
                    qv = qv[1:-1]
                current_selector["query_modifier"] = qv
    valid_selectors = []
    for s in selectors:
        if isinstance(s, dict) and s.get("label") and s.get("query_modifier"):
            valid_selectors.append(s)
    if not topics or not valid_selectors:
        return None, None
    return topics, valid_selectors


def _flatten_values(data):
    vals = []
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                vals.append(str(k))
            except Exception:
                pass
            vals.extend(_flatten_values(v))
    elif isinstance(data, list):
        for item in data:
            vals.extend(_flatten_values(item))
    else:
        try:
            vals.append(str(data))
        except Exception:
            pass
    return vals


def _schedule_json_has_monday_0830(data) -> bool:
    if data is None:
        return False
    try:
        cron_strs = []
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str) and ("*" in v or v.strip().count(" ") >= 4):
                    cron_strs.append(v)
                if isinstance(v, (dict, list)):
                    cron_strs.extend([s for s in _flatten_values(v) if isinstance(s, str)])
        else:
            cron_strs.extend([s for s in _flatten_values(data) if isinstance(s, str)])
        for s in cron_strs:
            cron = re.sub(r"\s+", " ", s.strip())
            if re.search(r'\b30\s+0?8\s+\*\s+\*\s+1\b', cron):
                return True
    except Exception:
        pass
    vals = _flatten_values(data)
    has_monday = any(str(v).strip().lower() == "monday" for v in vals)
    has_time = any(re.fullmatch(r'0?8:30', str(v).strip()) for v in vals)
    hour_ok = False
    minute_ok = False

    def _scan(d):
        nonlocal hour_ok, minute_ok
        if isinstance(d, dict):
            for k, v in d.items():
                kl = str(k).lower()
                if kl in ("hour", "hours") and (v == 8 or str(v).strip() in ("8", "08")):
                    hour_ok = True
                if kl in ("minute", "minutes") and (v == 30 or str(v).strip() == "30"):
                    minute_ok = True
                _scan(v)
        elif isinstance(d, list):
            for it in d:
                _scan(it)
    _scan(data)
    if has_monday and (has_time or (hour_ok and minute_ok)):
        return True
    return False


def _find_latest_date_dir(data_root: Path) -> Path:
    if not data_root.exists():
        return None
    candidates = []
    for p in data_root.iterdir():
        if p.is_dir() and re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.name):
            candidates.append(p)
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x.name)[-1]


def _list_serp_files(day_dir: Path):
    if day_dir is None or not day_dir.exists():
        return []
    return sorted([p for p in day_dir.iterdir() if p.is_file() and p.name.startswith("serp_") and p.suffix.lower() == ".html"])


def _parse_jsonl_results(results_path: Path):
    if results_path is None or not results_path.exists():
        return None, "missing"
    try:
        lines = _read_text(results_path).splitlines()
        entries = []
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            obj = json.loads(line)
            entries.append(obj)
        return entries, None
    except Exception:
        return None, "parse_error"


def _validate_results_entries(entries):
    required = ["timestamp", "source_label", "topic", "query", "search_engine", "rank", "title", "url", "snippet"]
    if entries is None:
        return False, 0, set()
    if len(entries) == 0:
        return True, 0, set()
    search_engines = set()
    groups = {}
    for e in entries:
        if not isinstance(e, dict):
            return False, len(entries), set()
        for k in required:
            if k not in e:
                return False, len(entries), set()
        if not isinstance(e["source_label"], str):
            return False, len(entries), set()
        if not isinstance(e["topic"], str):
            return False, len(entries), set()
        if not isinstance(e["query"], str):
            return False, len(entries), set()
        if not isinstance(e["search_engine"], str):
            return False, len(entries), set()
        if not (isinstance(e["rank"], int) or (isinstance(e["rank"], float) and float(e["rank"]).is_integer())):
            return False, len(entries), set()
        r = int(e["rank"])
        if r < 1 or r > 10:
            return False, len(entries), set()
        if not isinstance(e["title"], str):
            return False, len(entries), set()
        if not isinstance(e["url"], str):
            return False, len(entries), set()
        if not isinstance(e["snippet"], str):
            return False, len(entries), set()
        search_engines.add(e["search_engine"])
        key = (e["source_label"], e["topic"], e["query"])
        groups.setdefault(key, []).append(e)
    for key, grp in groups.items():
        urls = [g["url"] for g in grp]
        if len(urls) != len(set(urls)):
            return False, len(entries), search_engines
        if len(grp) > 10:
            return False, len(entries), search_engines
    return True, len(entries), search_engines


def _extract_section(lines, header):
    headers = [
        "Key Findings",
        "Action Items",
        "Diagnostics",
        "Appendix: Query Matrix",
    ]
    try:
        start_idx = None
        for i, ln in enumerate(lines):
            if ln.strip() == header:
                start_idx = i + 1
                break
        if start_idx is None:
            return []
        end_idx = len(lines)
        for j in range(start_idx, len(lines)):
            if lines[j].strip() in headers and lines[j].strip() != header:
                end_idx = j
                break
        return lines[start_idx:end_idx]
    except Exception:
        return []


def _count_errors_warnings_in_log(log_text: str):
    if not log_text:
        return 0, 0, []
    errors = 0
    warnings = 0
    error_examples = []
    for line in log_text.splitlines():
        l = line.strip()
        if re.search(r'\b(ERROR|Exception|Traceback)\b', l):
            errors += 1
            if len(error_examples) < 2:
                error_examples.append(l)
        if re.search(r'\b(WARN|WARNING)\b', l):
            warnings += 1
    return errors, warnings, error_examples


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "schedule_json_monday_0830": 0.0,
        "scheduler_script_reads_config": 0.0,
        "dry_run_script_present": 0.0,
        "dry_run_logs_present": 0.0,
        "timestamped_run_log_present": 0.0,
        "data_serp_files_for_all_queries": 0.0,
        "results_jsonl_structure_and_limits": 0.0,
        "meeting_notes_filled": 0.0,
        "notes_queries_match_expected": 0.0,
        "notes_serp_files_match_count": 0.0,
        "notes_results_count_match": 0.0,
        "notes_error_warning_counts_match": 0.0,
        "notes_run_log_path_valid": 0.0,
        "notes_search_engine_matches_results": 0.0,
        "appendix_topics_listed": 0.0,
        "appendix_source_selectors_listed": 0.0,
        "key_findings_aggregated": 0.0,
        "action_items_cover_sources": 0.0,
    }

    watchlist_path = workspace / "input" / "watchlist.yaml"
    topics, selectors = _parse_watchlist_yaml(watchlist_path)
    expected_queries = 0
    selector_labels = []
    query_modifiers = []
    if topics is not None and selectors is not None:
        expected_queries = len(topics) * len(selectors)
        selector_labels = [s["label"] for s in selectors]
        query_modifiers = [s["query_modifier"] for s in selectors]

    schedule_path = workspace / "config" / "schedule.json"
    schedule_data = _load_json(schedule_path)
    if schedule_data is not None and _schedule_json_has_monday_0830(schedule_data):
        scores["schedule_json_monday_0830"] = 1.0

    scheduler_py = workspace / "scripts" / "scheduler.py"
    scheduler_text = _read_text(scheduler_py)
    if scheduler_text:
        # Ensure it references the config path or file name
        if "schedule.json" in scheduler_text or "config/schedule.json" in scheduler_text:
            scores["scheduler_script_reads_config"] = 1.0

    run_once_py = workspace / "scripts" / "run_once.py"
    run_once_sh = workspace / "scripts" / "run_once.sh"
    if run_once_py.exists() or run_once_sh.exists():
        scores["dry_run_script_present"] = 1.0

    logs_dir = workspace / "logs"
    dry_run_log = logs_dir / "dry_run.log"
    dry_run_text = _read_text(dry_run_log)
    if dry_run_text:
        scores["dry_run_logs_present"] = 1.0

    run_logs = []
    if logs_dir.exists():
        for p in logs_dir.iterdir():
            if p.is_file() and re.fullmatch(r'\d{8}_\d{6}_run\.log', p.name):
                run_logs.append(p)
    run_logs_sorted = sorted(run_logs, key=lambda x: x.name)
    if run_logs_sorted:
        if _read_text(run_logs_sorted[-1]):
            scores["timestamped_run_log_present"] = 1.0

    data_root = workspace / "data"
    day_dir = _find_latest_date_dir(data_root)
    serp_files = _list_serp_files(day_dir) if day_dir else []
    if expected_queries > 0 and day_dir is not None and len(serp_files) >= expected_queries:
        scores["data_serp_files_for_all_queries"] = 1.0

    results_path = day_dir / "results.jsonl" if day_dir is not None else None
    entries, parse_err = _parse_jsonl_results(results_path) if results_path else (None, "missing")
    entries_valid, n_entries, search_engines = _validate_results_entries(entries)
    if entries_valid and results_path and results_path.exists():
        scores["results_jsonl_structure_and_limits"] = 1.0

    notes_path = workspace / "meeting_notes" / "weekly_brief.md"
    notes_text = _read_text(notes_path)
    if notes_text and ("{{" not in notes_text and "}}" not in notes_text):
        scores["meeting_notes_filled"] = 1.0

    notes_lines = notes_text.splitlines() if notes_text else []
    diagnostics = _extract_section(notes_lines, "Diagnostics")

    def _extract_int_after(prefix, lines):
        for ln in lines:
            m = re.match(r'^\s*-\s*' + re.escape(prefix) + r'\s*:\s*(\d+)\s*$', ln)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
        return None

    n_queries_notes = _extract_int_after("Queries attempted", diagnostics)
    n_serps_notes = _extract_int_after("SERP files saved", diagnostics)
    n_results_notes = _extract_int_after("Result entries written", diagnostics)

    n_errors_notes = None
    n_warnings_notes = None
    for ln in diagnostics:
        m = re.match(r'^\s*-\s*Errors\s*:\s*(\d+)\s*\|\s*Warnings\s*:\s*(\d+)\s*$', ln)
        if m:
            n_errors_notes = int(m.group(1))
            n_warnings_notes = int(m.group(2))
            break

    search_engine_notes = None
    for ln in diagnostics:
        m = re.match(r'^\s*-\s*Search engine used\s*:\s*(.+?)\s*$', ln)
        if m:
            search_engine_notes = m.group(1).strip()
            break

    run_log_path_notes = None
    for ln in diagnostics:
        m = re.match(r'^\s*-\s*Primary run log\s*:\s*(.+?)\s*$', ln)
        if m:
            run_log_path_notes = m.group(1).strip()
            break

    if expected_queries and n_queries_notes is not None and n_queries_notes == expected_queries:
        scores["notes_queries_match_expected"] = 1.0
    if day_dir and n_serps_notes is not None and n_serps_notes == len(serp_files):
        scores["notes_serp_files_match_count"] = 1.0
    if n_results_notes is not None and n_results_notes == n_entries:
        scores["notes_results_count_match"] = 1.0

    n_errors_actual, n_warnings_actual, _examples = _count_errors_warnings_in_log(dry_run_text)
    if n_errors_notes is not None and n_warnings_notes is not None:
        if n_errors_notes == n_errors_actual and n_warnings_notes == n_warnings_actual:
            scores["notes_error_warning_counts_match"] = 1.0

    if run_log_path_notes:
        run_log_candidate = workspace / run_log_path_notes
        if run_log_candidate.exists() and re.fullmatch(r'\d{8}_\d{6}_run\.log', Path(run_log_path_notes).name):
            scores["notes_run_log_path_valid"] = 1.0

    if search_engine_notes:
        if n_entries > 0:
            if len(search_engines) == 1 and search_engine_notes.strip().lower() == list(search_engines)[0].strip().lower():
                scores["notes_search_engine_matches_results"] = 1.0

    appendix = _extract_section(notes_lines, "Appendix: Query Matrix")
    appendix_text = "\n".join(appendix).lower()
    if notes_text:
        if topics:
            if all(t.lower() in appendix_text for t in topics):
                scores["appendix_topics_listed"] = 1.0
        if query_modifiers:
            if all(qm.lower() in appendix_text for qm in query_modifiers):
                scores["appendix_source_selectors_listed"] = 1.0

    # Key Findings: only consider if meeting notes exist
    if notes_text:
        key_findings = _extract_section(notes_lines, "Key Findings")
        finding_lines = []
        for ln in key_findings:
            m = re.match(r'^\s*-\s+\[Source:\s*.+?\]\s+.+?\s+—\s+https?://\S+\s*$', ln)
            if m:
                finding_lines.append(ln)
        if n_entries > 0:
            if 1 <= len(finding_lines) <= 5:
                scores["key_findings_aggregated"] = 1.0
        else:
            # If no results, having zero findings in notes is acceptable but only if notes exist
            if len(finding_lines) == 0:
                scores["key_findings_aggregated"] = 1.0

    # Action Items coverage: only consider if meeting notes exist
    if notes_text:
        action_items = _extract_section(notes_lines, "Action Items")
        action_map = {}
        for ln in action_items:
            m = re.match(r'^\s*-\s*(.+?)\s*:\s*(.+)$', ln)
            if m:
                label = m.group(1).strip()
                action_map.setdefault(label, []).append(m.group(2).strip())
        sources_with_results = set()
        if entries:
            for e in entries:
                if isinstance(e, dict) and "source_label" in e:
                    sources_with_results.add(e["source_label"])
        coverage_ok = True
        if selectors:
            all_labels = [s["label"] for s in selectors]
            for label in all_labels:
                lines_for_label = action_map.get(label, [])
                if label in sources_with_results:
                    if not lines_for_label:
                        coverage_ok = False
                        break
                    if all("No new items this cycle" in l for l in lines_for_label):
                        coverage_ok = False
                        break
                else:
                    if not lines_for_label or not any("No new items this cycle" in l for l in lines_for_label):
                        coverage_ok = False
                        break
        else:
            # If we cannot parse selectors, and notes exist with some action lines, give credit
            if not action_map:
                coverage_ok = False
        if coverage_ok and action_map:
            scores["action_items_cover_sources"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()