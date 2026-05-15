import json
import re
import sys
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[object]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_simple_yaml(text: str) -> Dict[str, object]:
    cfg = {}
    for line in text.splitlines():
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue
        # Remove inline comments
        if " #" in line_stripped:
            line_stripped = line_stripped.split(" #", 1)[0].strip()
        if ":" not in line_stripped:
            continue
        key, val = line_stripped.split(":", 1)
        key = key.strip()
        val = val.strip()
        # strip surrounding quotes if present
        if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
            val = val[1:-1]
        low = val.lower()
        if low == "true":
            parsed_val = True
        elif low == "false":
            parsed_val = False
        else:
            parsed_val = val
        cfg[key] = parsed_val
    return cfg


def import_event_parser(workspace: Path):
    try:
        import importlib.util
        parser_path = workspace / "src" / "event_parser.py"
        if not parser_path.exists():
            return None
        spec = importlib.util.spec_from_file_location("event_parser_mod", str(parser_path))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore
        if hasattr(mod, "parse_events"):
            return getattr(mod, "parse_events")
        return None
    except Exception:
        return None


# Fallback parsing logic mirroring src/event_parser.py to stay deterministic
EVENT_RE = re.compile(r'<div\s+class="event"\s+([^>]*)>\s*</div>')
ATTR_RE = re.compile(r'(data-(title|date|city|venue|creators))="([^"]*)"')
SLUG_CLEAN_RE = re.compile(r'[^a-z0-9\s-]')
MULTI_DASH_RE = re.compile(r'-{2,}')


def slugify(title: str) -> str:
    s = title.lower()
    s = SLUG_CLEAN_RE.sub("", s)
    s = re.sub(r"\s+", "-", s.strip())
    s = MULTI_DASH_RE.sub("-", s)
    return s


def fallback_parse_events(html_text: str) -> List[Dict]:
    from datetime import datetime
    events = []
    for m in EVENT_RE.finditer(html_text):
        attrs = dict((k, v) for (k, _, v) in ATTR_RE.findall(m.group(1)))
        title = attrs.get('data-title', '').strip()
        date_str = attrs.get('data-date', '').strip()
        city = attrs.get('data-city', '').strip()
        venue = attrs.get('data-venue', '').strip()
        creators_str = attrs.get('data-creators', '').strip()
        creators = [c.strip() for c in creators_str.split(',') if c.strip()]
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            norm_date = dt.strftime('%Y-%m-%d')
        except ValueError:
            # Invalid date format; skip
            continue
        evt = {
            'id': slugify(title),
            'title': title,
            'date': norm_date,
            'city': city,
            'venue': venue,
            'creators': creators,
        }
        events.append(evt)
    events.sort(key=lambda e: e['date'])
    return events


def compute_expected_events(workspace: Path) -> Optional[List[Dict]]:
    html_path = workspace / "input" / "events_raw.html"
    html_text = read_text_file(html_path)
    if html_text is None:
        return None
    parser = import_event_parser(workspace)
    if parser is not None:
        try:
            return parser(str(html_path))
        except Exception:
            pass
    # Fallback
    try:
        return fallback_parse_events(html_text)
    except Exception:
        return None


def parse_pytest_summary(text: str) -> Tuple[int, int, bool]:
    lines = text.splitlines()
    candidate = None
    for line in lines:
        low = line.lower()
        if ("=" in line) and ("passed" in low or "failed" in low):
            candidate = line
    if candidate is None:
        # Try alternative: search whole text for a summary-like segment
        m = re.findall(r"=+\s*([^=]*?(?:passed|failed)[^=]*?)\s*=+", text, flags=re.IGNORECASE | re.DOTALL)
        candidate = m[-1] if m else None
    passed = 0
    failed = 0
    if candidate:
        m_pass = re.search(r'(\d+)\s+passed', candidate, flags=re.IGNORECASE)
        m_fail = re.search(r'(\d+)\s+failed', candidate, flags=re.IGNORECASE)
        if m_pass:
            passed = int(m_pass.group(1))
        if m_fail:
            failed = int(m_fail.group(1))
        found = (m_pass is not None) or (m_fail is not None)
        return passed, failed, found
    return 0, 0, False


def extract_section_bullets(markdown: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current = None
    for line in markdown.splitlines():
        header_match = re.match(r'^\s*#{1,6}\s+(.*)\s*$', line)
        if header_match:
            current = header_match.group(1).strip()
            sections[current] = []
        else:
            bullet_match = re.match(r'^\s*[-*]\s+(.*)$', line)
            if bullet_match and current is not None:
                sections[current].append(bullet_match.group(1).strip())
    return sections


def normalize_title_for_owner(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r'owner:\s*', '', t)
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip()


def parse_todo_items(todo_text: str) -> List[Dict]:
    items = []
    for line in todo_text.splitlines():
        m = re.match(r'^\s*-\s*\[( |x|X)\]\s*(.+)$', line)
        if not m:
            continue
        checked = m.group(1).lower() == 'x'
        rest = m.group(2).strip()
        owner_match = re.search(r'\(Owner:\s*([^)]+)\)', rest)
        owner = owner_match.group(1).strip() if owner_match else ''
        # Due date pattern: 'Due: YYYY-MM-DD' may be preceded by dashes/em dashes
        due_match = re.search(r'Due:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', rest)
        due = due_match.group(1) if due_match else None
        # Title is rest with owner and due removed
        title = rest
        if owner_match:
            title = title.replace(owner_match.group(0), '').strip()
        if due_match:
            # remove a possible preceding dash/en dash/em dash and spaces
            title = re.sub(r'[\-\u2013\u2014]\s*Due:\s*[0-9]{4}-[0-9]{2}-[0-9]{2}', '', title).strip()
            title = re.sub(r'Due:\s*[0-9]{4}-[0-9]{2}-[0-9]{2}', '', title).strip()
        # Clean trailing punctuation/spaces
        title = title.strip(' —-').strip()
        items.append({
            "checked": checked,
            "owner": owner,
            "due": due,
            "title": title
        })
    return items


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_environment_production": 0.0,
        "config_deploy_true": 0.0,
        "config_version_0_4_0": 0.0,
        "tests_report_exists": 0.0,
        "tests_summary_counts_parsed": 0.0,
        "events_json_exists": 0.0,
        "events_json_schema_valid": 0.0,
        "events_json_sorted_by_date": 0.0,
        "events_json_matches_expected": 0.0,
        "release_status_has_version_and_environment": 0.0,
        "release_status_includes_event_count": 0.0,
        "release_status_tests_summary_matches": 0.0,
        "release_status_ready_for_deploy_matches": 0.0,
        "release_status_includes_changed_files": 0.0,
        "meeting_notes_has_owner_sections": 0.0,
        "meeting_notes_items_preserve_state_and_due": 0.0,
        "meeting_notes_next_sync_agenda_ok": 0.0,
    }

    # Check config.yaml updates
    cfg_path = workspace / "pipeline" / "config.yaml"
    cfg_text = read_text_file(cfg_path)
    parsed_cfg = {}
    if cfg_text is not None:
        parsed_cfg = parse_simple_yaml(cfg_text)
        env = str(parsed_cfg.get("environment", "")).strip()
        deploy_val = parsed_cfg.get("deploy", None)
        version_val = str(parsed_cfg.get("version", "")).strip()
        if env == "production":
            scores["config_environment_production"] = 1.0
        if isinstance(deploy_val, bool) and deploy_val is True:
            scores["config_deploy_true"] = 1.0
        elif isinstance(deploy_val, str) and deploy_val.lower() == "true":
            scores["config_deploy_true"] = 1.0
        # Accept version with or without quotes, but value must be 0.4.0
        if version_val == "0.4.0":
            scores["config_version_0_4_0"] = 1.0

    # Parse test report
    tests_path = workspace / "reports" / "tests.txt"
    tests_text = read_text_file(tests_path)
    passed_cnt = 0
    failed_cnt = 0
    if tests_text is not None:
        scores["tests_report_exists"] = 1.0
        passed_cnt, failed_cnt, found = parse_pytest_summary(tests_text)
        if found:
            scores["tests_summary_counts_parsed"] = 1.0

    # Compute expected events from input using parser or fallback
    expected_events = compute_expected_events(workspace)

    # Check events.json
    events_json_path = workspace / "data" / "events.json"
    events_obj = load_json_file(events_json_path)
    if events_obj is not None:
        scores["events_json_exists"] = 1.0
        # Validate schema: list of objects with exact fields
        if isinstance(events_obj, list) and all(isinstance(e, dict) for e in events_obj):
            required_fields = {"id", "title", "date", "city", "venue", "creators"}
            schema_ok = True
            for e in events_obj:
                if set(e.keys()) != required_fields:
                    schema_ok = False
                    break
                if not isinstance(e.get("creators"), list):
                    schema_ok = False
                    break
            if schema_ok:
                scores["events_json_schema_valid"] = 1.0
            # Sorted by date ascending
            try:
                dates = [e["date"] for e in events_obj]
                if dates == sorted(dates):
                    scores["events_json_sorted_by_date"] = 1.0
            except Exception:
                pass
            # Matches expected content
            if expected_events is not None:
                try:
                    def canon(lst):
                        return json.dumps(lst, sort_keys=True)
                    if canon(events_obj) == canon(expected_events):
                        scores["events_json_matches_expected"] = 1.0
                except Exception:
                    pass

    # Check release_status.md
    release_path = workspace / "reports" / "release_status.md"
    release_text = read_text_file(release_path)
    if release_text is not None and cfg_text is not None:
        # Version and environment lines present
        env = str(parsed_cfg.get("environment", "")).strip()
        ver = str(parsed_cfg.get("version", "")).strip()
        has_version_line = any(("version" in ln.lower() and ver in ln) for ln in release_text.splitlines())
        has_env_line = any(("environment" in ln.lower() and env in ln) for ln in release_text.splitlines())
        if has_version_line and has_env_line:
            scores["release_status_has_version_and_environment"] = 1.0
        # Includes event count
        events_count = len(expected_events) if expected_events is not None else None
        has_event_count = False
        if events_count is not None:
            # Look for the count number in a line referencing 'event'
            for ln in release_text.splitlines():
                if 'event' in ln.lower() and str(events_count) in ln:
                    has_event_count = True
                    break
        if has_event_count:
            scores["release_status_includes_event_count"] = 1.0
        # Tests summary "Tests: <passed> passed, <failed> failed"
        m = re.search(r'Tests:\s*(\d+)\s+passed,\s*(\d+)\s+failed', release_text, flags=re.IGNORECASE)
        if m:
            rp = int(m.group(1))
            rf = int(m.group(2))
            if rp == passed_cnt and rf == failed_cnt:
                scores["release_status_tests_summary_matches"] = 1.0
        # Ready for deploy matches deploy flag
        m2 = re.search(r'Ready\s+for\s+deploy:\s*(true|false)', release_text, flags=re.IGNORECASE)
        deploy_flag = parsed_cfg.get("deploy", None)
        deploy_bool = None
        if isinstance(deploy_flag, bool):
            deploy_bool = deploy_flag
        elif isinstance(deploy_flag, str):
            deploy_bool = deploy_flag.lower() == "true"
        if m2 and deploy_bool is not None:
            reported = m2.group(1).lower() == "true"
            if reported == deploy_bool:
                scores["release_status_ready_for_deploy_matches"] = 1.0
        # Changed files bullet list includes at minimum specified files
        bullets = [ln.strip() for ln in release_text.splitlines() if re.match(r'^\s*[-*]\s+', ln)]
        needed = {"pipeline/config.yaml", "data/events.json", "reports/tests.txt"}
        found_needed = set()
        for b in bullets:
            for need in needed:
                if need in b:
                    found_needed.add(need)
        if needed.issubset(found_needed):
            scores["release_status_includes_changed_files"] = 1.0

    # Check meeting_notes.md
    notes_path = workspace / "notes" / "meeting_notes.md"
    meeting_text = read_text_file(notes_path)
    todo_path = workspace / "docs" / "TODO.md"
    todo_text = read_text_file(todo_path)
    if meeting_text is not None and todo_text is not None:
        sections = extract_section_bullets(meeting_text)
        items = parse_todo_items(todo_text)
        owners = sorted({i["owner"] for i in items if i["owner"]})
        # Has sections per owner
        section_titles = list(sections.keys())
        owners_ok = True
        owner_to_section = {}
        for owner in owners:
            found = None
            for sec in section_titles:
                if normalize_title_for_owner(sec) == normalize_title_for_owner(owner):
                    found = sec
                    break
                # also allow title that contains the owner word as a token
                if re.search(r'\b' + re.escape(owner.lower()) + r'\b', sec.lower()):
                    found = sec
                    break
            if found is None:
                owners_ok = False
                break
            owner_to_section[owner] = found
        if owners_ok and owner_to_section:
            scores["meeting_notes_has_owner_sections"] = 1.0
        # Items preserve checkbox and due
        preserve_ok = True
        for it in items:
            owner = it["owner"]
            if not owner:
                continue
            sec = owner_to_section.get(owner)
            if not sec:
                preserve_ok = False
                break
            bullets = sections.get(sec, [])
            # find a bullet that contains the title
            matching = [b for b in bullets if it["title"] in b]
            if not matching:
                preserve_ok = False
                break
            # check checkbox state
            checkbox_ok = any(("[x]" in b.lower()) == it["checked"] and ("[ ]" in b) == (not it["checked"]) or
                              (("[x]" in b.lower()) and not ("[ ]" in b) and it["checked"]) or
                              (("[ ]" in b) and not ("[x]" in b.lower()) and not it["checked"])
                              for b in matching)
            if not checkbox_ok:
                preserve_ok = False
                break
            # check due date if present
            if it["due"]:
                due_ok = any(it["due"] in b for b in matching)
                if not due_ok:
                    preserve_ok = False
                    break
        if preserve_ok:
            scores["meeting_notes_items_preserve_state_and_due"] = 1.0
        # Next Sync Agenda section
        agenda_sec = None
        for sec in sections.keys():
            if "next sync agenda" in sec.lower():
                agenda_sec = sec
                break
        agenda_ok = False
        if agenda_sec:
            agenda_bullets = sections.get(agenda_sec, [])
            # first two items from TODO.md (file order)
            first_two = items[:2]
            if len(agenda_bullets) >= 2 and len(first_two) >= 2:
                title1 = first_two[0]["title"]
                title2 = first_two[1]["title"]
                if title1 in agenda_bullets[0] and title2 in agenda_bullets[1]:
                    agenda_ok = True
        if agenda_ok:
            scores["meeting_notes_next_sync_agenda_ok"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()