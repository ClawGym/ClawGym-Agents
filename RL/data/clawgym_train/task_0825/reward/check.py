import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        lines = text.splitlines()
        if not lines:
            return None
        reader = csv.DictReader(lines)
        header = reader.fieldnames or []
        rows = list(reader)
        return (header, rows)
    except Exception:
        return None


def parse_yaml_queries(path: Path) -> List[str]:
    text = read_text(path)
    if text is None:
        return []
    queries = []
    for m in re.finditer(r'^\s*query:\s*"(.*?)"\s*$', text, flags=re.MULTILINE):
        q = m.group(1).strip()
        if q:
            queries.append(q)
    return queries


def parse_iso8601(s: str) -> Optional[datetime]:
    try:
        if s.endswith("Z"):
            s_adj = s[:-1] + "+00:00"
        else:
            s_adj = s
        return datetime.fromisoformat(s_adj)
    except Exception:
        return None


def get_domain(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if not netloc and parsed.path:
            parsed = urlparse("http://" + url)
            netloc = parsed.netloc.lower()
        if "@" in netloc:
            netloc = netloc.split("@", 1)[-1]
        if ":" in netloc:
            netloc = netloc.split(":", 1)[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return None


def is_allowed_domain(domain: str) -> bool:
    allowed_substrings = ("museum", "culture", "cultura")
    domain_l = domain.lower()
    if domain_l.endswith(".edu") or domain_l.endswith(".org"):
        return True
    for sub in allowed_substrings:
        if sub in domain_l:
            return True
    return False


def extract_meeting_notes_sections(text: str) -> Dict[str, List[str]]:
    lines = text.splitlines()
    sections: Dict[str, List[str]] = {}
    current_section = None
    for line in lines:
        if re.match(r'^\s*[A-Za-z][A-Za-z\s]*:\s*$', line):
            header = line.strip().rstrip(":").strip().lower()
            current_section = header
            sections[current_section] = []
        else:
            if current_section is not None:
                sections[current_section].append(line)
    return sections


def extract_date_from_notes(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip().lower().startswith("date:"):
            m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
            if m:
                return m.group(1)
    return None


def parse_action_items_from_section(lines: List[str]) -> List[str]:
    items: List[str] = []
    for line in lines:
        l = line.strip()
        if not l:
            continue
        if l.startswith(("-", "*")) or re.match(r'^\d+\.\s+', l):
            items.append(l)
        else:
            items.append(l)
    return items


def compute_next_monday_date(from_dt: datetime) -> str:
    d = from_dt.date()
    days_ahead = (7 - d.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    target = d + timedelta(days=days_ahead)
    return target.isoformat()


def extract_errors_from_log(text: str) -> List[str]:
    errors = []
    for line in text.splitlines():
        l = line.strip()
        if re.search(r'\b(error|exception|traceback|failed)\b', l, flags=re.IGNORECASE):
            errors.append(l)
    return errors


def check_cron_entry(line: str) -> bool:
    parts = line.strip().split()
    if len(parts) < 6:
        return False
    min_s, hour_s, dom, mon, dow = parts[0], parts[1], parts[2], parts[3], parts[4]
    if min_s not in ("0", "00"):
        return False
    if hour_s not in ("9", "09"):
        return False
    dow_l = dow.lower()
    if dow_l not in ("1", "mon", "monday"):
        return False
    line_l = line.lower()
    if "scripts/run_pipeline" not in line_l:
        return False
    if "output/last_run.log" not in line_l:
        return False
    return True


def check_task_xml(path: Path) -> bool:
    text = read_text(path)
    if text is None or not text.strip():
        return False
    ok_time = False
    ok_day = False
    ok_action = False
    ok_log = False
    try:
        root = ET.fromstring(text)
        for sb in root.iter():
            tag = sb.tag.lower()
            if tag.endswith("startboundary"):
                if sb.text and ("t09:00" in sb.text.lower() or "t09:00:00" in sb.text.lower()):
                    ok_time = True
            if tag.endswith("daysofweek"):
                if sb.text and ("monday" in sb.text.lower()):
                    ok_day = True
        for a in root.iter():
            t = a.text or ""
            t_l = t.lower()
            if "scripts/run_pipeline" in t_l:
                ok_action = True
            if "output/last_run.log" in t_l:
                ok_log = True
    except Exception:
        if "StartBoundary" in text and ("T09:00" in text or "T09:00:00" in text):
            ok_time = True
        if "DaysOfWeek" in text and "Monday" in text:
            ok_day = True
        if "scripts/run_pipeline" in text:
            ok_action = True
        if "output/last_run.log" in text:
            ok_log = True
    return ok_time and ok_day and ok_action and ok_log


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "run_pipeline_script_exists": 0.0,
        "search_results_json_structure": 0.0,
        "search_results_domain_policy": 0.0,
        "search_results_min_two_sources": 0.0,
        "search_results_no_duplicate_urls": 0.0,
        "search_results_csv_match": 0.0,
        "meeting_notes_date_matches_run": 0.0,
        "meeting_notes_agenda_included": 0.0,
        "meeting_notes_background_sources_included": 0.0,
        "meeting_notes_action_items_valid": 0.0,
        "cron_entry_valid": 0.0,
        "task_xml_valid": 0.0,
        "last_run_log_present": 0.0,
        "run_summary_json_valid": 0.0,
        "run_diagnostics_consistent": 0.0,
        "readme_instructions_present": 0.0,
    }

    input_yaml = workspace / "input" / "search_queries.yaml"
    input_agenda = workspace / "input" / "agenda_topics.txt"
    input_members = workspace / "input" / "club_members.csv"

    scripts_dir = workspace / "scripts"
    run_pipeline_py = scripts_dir / "run_pipeline.py"
    run_pipeline_sh = scripts_dir / "run_pipeline.sh"
    run_pipeline_bat = scripts_dir / "run_pipeline.bat"

    output_dir = workspace / "output"
    search_json_path = output_dir / "search_results.json"
    search_csv_path = output_dir / "search_results.csv"
    notes_path = output_dir / "meeting_notes.md"
    cron_path = output_dir / "cron_entry.txt"
    task_xml_path = output_dir / "weekly_task.xml"
    log_path = output_dir / "last_run.log"
    run_summary_path = output_dir / "run_summary.json"
    diagnostics_path = output_dir / "run_diagnostics.md"
    readme_path = output_dir / "README.md"

    if run_pipeline_py.exists() or run_pipeline_sh.exists() or run_pipeline_bat.exists():
        scores["run_pipeline_script_exists"] = 1.0

    search_json = load_json_file(search_json_path)
    json_ok = False
    json_entries: List[Dict[str, Any]] = []
    if isinstance(search_json, list):
        required_fields = ["title", "url", "domain", "accessed_at", "query_used", "snippet"]
        valid = True
        urls_seen = set()
        for obj in search_json:
            if not isinstance(obj, dict):
                valid = False
                break
            for f in required_fields:
                if f not in obj:
                    valid = False
                    break
            if not valid:
                break
            url = str(obj.get("url", "")).strip()
            domain = str(obj.get("domain", "")).strip().lower()
            if not url or not domain:
                valid = False
                break
            snippet = str(obj.get("snippet", ""))
            if len(snippet) > 300:
                valid = False
                break
            accessed = str(obj.get("accessed_at", ""))
            if not parse_iso8601(accessed):
                valid = False
                break
            if url in urls_seen:
                pass
            else:
                urls_seen.add(url)
        if valid:
            json_ok = True
            json_entries = search_json

    if json_ok:
        scores["search_results_json_structure"] = 1.0

    if json_ok:
        allowed_all = True
        url_set = set()
        dup = False
        domain_match_all = True
        for obj in json_entries:
            url = str(obj.get("url", "")).strip()
            dom_field = str(obj.get("domain", "")).strip().lower()
            extracted = get_domain(url) or ""
            if extracted.startswith("www."):
                extracted = extracted[4:]
            if extracted != dom_field:
                domain_match_all = False
            if url in url_set:
                dup = True
            else:
                url_set.add(url)
            if not extracted or not is_allowed_domain(extracted):
                allowed_all = False
        if allowed_all and domain_match_all:
            scores["search_results_domain_policy"] = 1.0
        if not dup:
            scores["search_results_no_duplicate_urls"] = 1.0
        if len(url_set) >= 2:
            scores["search_results_min_two_sources"] = 1.0

    csv_parsed = load_csv_dicts(search_csv_path)
    if csv_parsed is not None and json_ok:
        header, rows = csv_parsed
        expected_header = ["title", "url", "domain", "accessed_at", "query_used", "snippet"]
        header_ok = header == expected_header
        mapping_csv = {r.get("url", "").strip(): {k: (r.get(k, "") or "").strip() for k in expected_header} for r in rows if "url" in r}
        mapping_json = {str(o["url"]).strip(): {
            "title": str(o["title"]).strip(),
            "url": str(o["url"]).strip(),
            "domain": str(o["domain"]).strip(),
            "accessed_at": str(o["accessed_at"]).strip(),
            "query_used": str(o["query_used"]).strip(),
            "snippet": str(o["snippet"]).strip(),
        } for o in json_entries}
        sets_equal = set(mapping_csv.keys()) == set(mapping_json.keys())
        fields_equal = True
        if sets_equal:
            for url in mapping_json:
                j = mapping_json[url]
                c = mapping_csv.get(url, {})
                for k in expected_header:
                    if c.get(k, "") != j.get(k, ""):
                        fields_equal = False
                        break
                if not fields_equal:
                    break
        else:
            fields_equal = False
        if header_ok and fields_equal:
            scores["search_results_csv_match"] = 1.0

    notes_text = read_text(notes_path)
    run_summary = load_json_file(run_summary_path)

    if notes_text and isinstance(run_summary, dict) and "started_at" in run_summary:
        notes_date = extract_date_from_notes(notes_text)
        started = parse_iso8601(str(run_summary.get("started_at", "")))
        if notes_date and started:
            if notes_date == started.date().isoformat():
                scores["meeting_notes_date_matches_run"] = 1.0

    agenda_text = read_text(input_agenda)
    if notes_text and agenda_text:
        all_ok = True
        for line in agenda_text.splitlines():
            t = line.strip()
            if not t:
                continue
            t_clean = t
            if t_clean.startswith("-"):
                t_clean = t_clean.lstrip("-").strip()
            if t_clean and t_clean not in notes_text:
                all_ok = False
                break
        if all_ok:
            scores["meeting_notes_agenda_included"] = 1.0

    if notes_text and json_ok and len(json_entries) >= 2:
        ok_count = 0
        for obj in json_entries[:2]:
            url = str(obj.get("url", "")).strip()
            title = str(obj.get("title", "")).strip()
            domain = str(obj.get("domain", "")).strip()
            accessed_at = str(obj.get("accessed_at", "")).strip()
            accessed_date_match = re.search(r'\d{4}-\d{2}-\d{2}', accessed_at)
            accessed_date = accessed_date_match.group(0) if accessed_date_match else accessed_at
            present = (url in notes_text) and (title in notes_text) and (domain in notes_text) and (accessed_date in notes_text)
            if present:
                ok_count += 1
        if ok_count >= 2:
            scores["meeting_notes_background_sources_included"] = 1.0

    if notes_text and run_summary and isinstance(run_summary, dict):
        sections = extract_meeting_notes_sections(notes_text)
        ai_lines = sections.get("action items", [])
        action_items = parse_action_items_from_section(ai_lines)
        members_ok = load_csv_dicts(input_members)
        started = parse_iso8601(str(run_summary.get("started_at", "")))
        next_mon = compute_next_monday_date(started) if started else None
        if members_ok and next_mon and len(action_items) >= 3:
            _, member_rows = members_ok
            member_names = [r.get("name", "").strip() for r in member_rows if r.get("name")]
            first_three_ok = True
            agenda_keywords = set()
            if agenda_text:
                for ln in agenda_text.splitlines():
                    ln_clean = re.sub(r'^[\-\*\s]+', '', ln).strip()
                    for w in re.findall(r"[A-Za-zÀ-ÿ']{4,}", ln_clean):
                        agenda_keywords.add(w.lower())
            urls = [str(o.get("url", "")).strip() for o in json_entries]
            for i in range(3):
                item = action_items[i]
                expected_owner = member_names[i % len(member_names)] if member_names else None
                has_owner = expected_owner in item if expected_owner else False
                has_planned = re.search(r'\bplanned\b', item, flags=re.IGNORECASE) is not None
                has_due = next_mon in item
                tied = False
                for u in urls:
                    if u and u in item:
                        tied = True
                        break
                if not tied:
                    low = item.lower()
                    for kw in agenda_keywords:
                        if kw in low:
                            tied = True
                            break
                if not (has_owner and has_planned and has_due and tied):
                    first_three_ok = False
                    break
            if first_three_ok:
                scores["meeting_notes_action_items_valid"] = 1.0

    cron_text = read_text(cron_path)
    if cron_text:
        line = None
        for ln in cron_text.splitlines():
            ls = ln.strip()
            if ls and not ls.startswith("#"):
                line = ls
                break
        if line and check_cron_entry(line):
            scores["cron_entry_valid"] = 1.0

    if task_xml_path.exists():
        if check_task_xml(task_xml_path):
            scores["task_xml_valid"] = 1.0

    if log_path.exists():
        try:
            size = log_path.stat().st_size
            if size > 0:
                scores["last_run_log_present"] = 1.0
        except Exception:
            pass

    run_summary_ok = False
    if isinstance(run_summary, dict):
        started = run_summary.get("started_at")
        finished = run_summary.get("finished_at")
        sources_found = run_summary.get("sources_found")
        errors = run_summary.get("errors")
        ok_fields = isinstance(started, str) and isinstance(finished, str) and isinstance(sources_found, int) and isinstance(errors, list)
        started_dt = parse_iso8601(started) if isinstance(started, str) else None
        finished_dt = parse_iso8601(finished) if isinstance(finished, str) else None
        order_ok = started_dt is not None and finished_dt is not None and started_dt <= finished_dt
        json_unique = 0
        if json_ok:
            json_unique = len({str(o.get("url", "")).strip() for o in json_entries if str(o.get("url", "")).strip()})
        sources_match = (json_unique == sources_found) if json_ok else False
        if ok_fields and order_ok and sources_match:
            run_summary_ok = True
            scores["run_summary_json_valid"] = 1.0

    diag_text = read_text(diagnostics_path)
    if diag_text is not None and isinstance(run_summary, dict) and "errors" in run_summary:
        errs = run_summary.get("errors", [])
        if isinstance(errs, list):
            if len(errs) == 0:
                if re.search(r'\bno errors\b', diag_text, flags=re.IGNORECASE):
                    scores["run_diagnostics_consistent"] = 1.0
            else:
                present_any = False
                for e in errs:
                    if isinstance(e, str) and e and e in diag_text:
                        present_any = True
                        break
                if present_any:
                    scores["run_diagnostics_consistent"] = 1.0

    readme_text = read_text(readme_path)
    if readme_text:
        has_scheduler = bool(re.search(r'\b(cron|crontab|task scheduler)\b', readme_text, flags=re.IGNORECASE))
        has_example = ("scripts/run_pipeline" in readme_text) or bool(re.search(r'python\s+scripts/run_pipeline\.py', readme_text, flags=re.IGNORECASE))
        if has_scheduler and has_example:
            scores["readme_instructions_present"] = 1.0

    if scores["search_results_domain_policy"] > 0.0 and json_ok:
        allowed_queries = set(parse_yaml_queries(input_yaml))
        if allowed_queries:
            all_queries_ok = all(str(o.get("query_used", "")).strip() in allowed_queries for o in json_entries)
        else:
            all_queries_ok = False
        if not all_queries_ok:
            scores["search_results_domain_policy"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    # Preserve insertion order as defined in the scores dict to satisfy downstream key ordering checks
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()