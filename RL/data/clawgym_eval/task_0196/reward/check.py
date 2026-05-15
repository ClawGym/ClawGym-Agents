import json
import csv
import sys
import subprocess
import re
from pathlib import Path
from typing import List, Tuple, Optional, Dict


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def safe_load_json_list(path: Path) -> Optional[List]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        data = json.loads(text)
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None


def safe_load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = list(reader)
            return headers, rows
    except Exception:
        return None, None


def parse_roster(workspace: Path) -> Optional[List[str]]:
    roster_path = workspace / "input" / "roster.csv"
    headers, rows = safe_load_csv_dicts(roster_path)
    if headers is None or rows is None:
        return None
    if not all(h in headers for h in ["name", "role", "email"]):
        return None
    names = []
    for r in rows:
        n = (r.get("name") or "").strip()
        if n:
            names.append(n)
    return names


def parse_input_agenda(workspace: Path, date_str: str) -> Optional[dict]:
    agenda_path = workspace / "input" / f"agenda_{date_str}.md"
    text = safe_read_text(agenda_path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    title = None
    for ln in lines:
        if ln.strip().startswith("#"):
            title = ln.lstrip("#").strip()
            if title:
                break
    date = None
    for ln in lines:
        m = re.match(r"^\s*Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", ln)
        if m:
            date = m.group(1)
            break
    attendees = []
    for ln in lines:
        m = re.match(r"^\s*Attendees:\s*(.+)$", ln, flags=re.IGNORECASE)
        if m:
            attendees_str = m.group(1).strip()
            attendees = [a.strip() for a in attendees_str.split(",") if a.strip()]
            break
    decisions = []
    decisions_start_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^\s*Decisions\s*:\s*$", ln, flags=re.IGNORECASE) or re.match(r"^\s*Decisions\s*$", ln, flags=re.IGNORECASE):
            decisions_start_idx = i + 1
            break
    if decisions_start_idx is not None:
        for j in range(decisions_start_idx, len(lines)):
            ln = lines[j].strip()
            if not ln:
                break
            if re.match(r"^\s*\w.*:\s*$", ln) and not ln.startswith("-") and not ln.startswith("*"):
                break
            if ln.startswith("-") or ln.startswith("*") or ln.startswith("•"):
                cleaned = re.sub(r"^[\-\*\•]\s*", "", ln).strip()
                if cleaned:
                    decisions.append(cleaned)
    action_items = []
    ai_start_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^\s*Action Items\s*:\s*$", ln, flags=re.IGNORECASE) or re.match(r"^\s*Action Items\s*$", ln, flags=re.IGNORECASE):
            ai_start_idx = i + 1
            break
    if ai_start_idx is not None:
        for j in range(ai_start_idx, len(lines)):
            ln = lines[j].strip()
            if not ln:
                break
            if re.match(r"^\s*\w.*:\s*$", ln) and not ln.startswith("-") and not ln.startswith("*"):
                break
            if ln.startswith("-") or ln.startswith("*") or ln.startswith("•"):
                itm_line = re.sub(r"^[\-\*\•]\s*", "", ln).strip()
                m = re.search(r"\(([^)]*)\)\s*$", itm_line)
                if m:
                    meta = m.group(1)
                    task_text = itm_line[: m.start()].strip()
                    owner_m = re.search(r"Owner:\s*([^;]+)", meta, flags=re.IGNORECASE)
                    due_m = re.search(r"Due:\s*([^;]+)", meta, flags=re.IGNORECASE)
                    prio_m = re.search(r"Priority:\s*([^)]+)", meta, flags=re.IGNORECASE)
                    if owner_m and due_m and prio_m:
                        action_items.append({
                            "task": task_text,
                            "owner": owner_m.group(1).strip(),
                            "due_date": due_m.group(1).strip(),
                            "priority": prio_m.group(1).strip()
                        })
    return {
        "title": title,
        "date": date,
        "attendees": attendees,
        "decisions": decisions,
        "action_items": action_items
    }


def normalize_name(n: str) -> str:
    return re.sub(r"\s+", " ", n or "").strip().lower()


def extract_names_from_section(lines: List[str], header_regex: str, other_section_markers: List[str]) -> Optional[List[str]]:
    idx = None
    for i, ln in enumerate(lines):
        if re.search(header_regex, ln, flags=re.IGNORECASE):
            idx = i
            break
    if idx is None:
        return None
    m = re.search(r":\s*(.*)$", lines[idx])
    names = []
    if m:
        after = m.group(1).strip()
        if after:
            parts = [p.strip() for p in after.split(",") if p.strip()]
            names.extend(parts)
    j = idx + 1
    while j < len(lines):
        ln = lines[j].strip()
        if not ln:
            break
        if any(re.search(marker, ln, flags=re.IGNORECASE) for marker in other_section_markers):
            break
        if ln.startswith("-") or ln.startswith("*") or ln.startswith("•"):
            entry = re.sub(r"^[\-\*\•]\s*", "", ln).strip()
            if entry:
                names.append(entry)
        else:
            if re.match(r"^\s*\w[\w\s]*:\s*$", ln):
                break
            parts = [p.strip() for p in ln.split(",") if p.strip()]
            if parts:
                names.extend(parts)
        j += 1
    seen = set()
    uniq = []
    for n in names:
        key = normalize_name(n)
        if key and key not in seen:
            seen.add(key)
            uniq.append(n.strip())
    return uniq


def run_once_script(workspace: Path, timeout_sec: int = 20) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
    script_path = workspace / "scripts" / "agenda_watcher.py"
    if not script_path.exists():
        return False, None, None, None
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), "--once"],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            text=True,
        )
        return True, proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return True, None, None, "timeout"
    except Exception as e:
        return True, None, None, str(e)


def load_trigger_log(workspace: Path) -> Optional[List[dict]]:
    log_path = workspace / "out" / "trigger_log.json"
    entries = safe_load_json_list(log_path)
    if entries is None:
        return None
    valid = []
    for e in entries:
        if isinstance(e, dict):
            valid.append(e)
    return valid


def count_log_for_filename(entries: List[dict], filename: str) -> int:
    cnt = 0
    for e in entries:
        fn = e.get("filename")
        if isinstance(fn, str) and fn.endswith(filename):
            cnt += 1
    return cnt


def find_log_record(entries: List[dict], filename: str) -> Optional[dict]:
    for e in entries:
        fn = e.get("filename")
        if isinstance(fn, str) and fn.endswith(filename):
            return e
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_file_exists": 0.0,
        "supports_once_mode_execution": 0.0,
        "meeting_notes_title_and_date": 0.0,
        "meeting_notes_normalization_note": 0.0,
        "attendees_absentees_correct": 0.0,
        "decisions_copied_to_notes": 0.0,
        "notes_action_items_section_content": 0.0,
        "follow_ups_section_quality": 0.0,
        "action_items_csv_structure": 0.0,
        "action_items_csv_content": 0.0,
        "trigger_log_contains_record": 0.0,
        "idempotent_processing": 0.0,
        "supports_watch_flag": 0.0,
    }

    date_str = "2024-09-15"
    expected_agenda = parse_input_agenda(workspace, date_str)
    roster_names = parse_roster(workspace)
    expected_present = set()
    expected_absent = set()
    if expected_agenda and roster_names:
        expected_present = set(normalize_name(n) for n in expected_agenda.get("attendees", []))
        expected_absent = set(normalize_name(n) for n in roster_names) - expected_present

    script_path = workspace / "scripts" / "agenda_watcher.py"
    if script_path.exists() and script_path.is_file():
        scores["script_file_exists"] = 1.0
        text = safe_read_text(script_path) or ""
        if "--watch" in text or "add_argument('--watch'" in text or 'add_argument("-w"' in text:
            scores["supports_watch_flag"] = 1.0

    ran, rc, out, err = run_once_script(workspace)
    if ran and rc is not None and rc == 0:
        scores["supports_once_mode_execution"] = 1.0

    notes_path = workspace / "out" / f"meeting_notes_{date_str}.md"
    csv_path = workspace / "out" / f"action_items_{date_str}.csv"
    log_path = workspace / "out" / "trigger_log.json"

    notes_text = safe_read_text(notes_path)
    if notes_text is not None:
        lines = [ln.rstrip("\n") for ln in notes_text.splitlines()]
        top_lines = [ln.lower() for ln in lines[:10]]
        norm_note = any(("normaliz" in ln and "attendee" in ln) for ln in top_lines)
        if norm_note:
            scores["meeting_notes_normalization_note"] = 1.0

        title_ok = False
        date_ok = False
        if expected_agenda:
            expected_title = expected_agenda.get("title")
            for ln in lines:
                if re.match(r"^\s*Title\s*:\s*", ln, flags=re.IGNORECASE):
                    content = re.sub(r"^\s*Title\s*:\s*", "", ln, flags=re.IGNORECASE).strip()
                    if content == expected_title:
                        title_ok = True
                        break
            if not title_ok:
                for ln in lines:
                    if ln.strip().startswith("#"):
                        content = ln.lstrip("#").strip()
                        if content == expected_title:
                            title_ok = True
                            break
        for ln in lines:
            if re.match(r"^\s*Date\s*:\s*"+re.escape(date_str)+r"\s*$", ln, flags=re.IGNORECASE):
                date_ok = True
                break
        if title_ok and date_ok:
            scores["meeting_notes_title_and_date"] = 1.0

        if expected_present and expected_absent:
            attn = extract_names_from_section(lines, r"^\s*Attendees(\s*\(Present\))?", [r"^\s*Absentees", r"^\s*Decisions", r"^\s*Action Items", r"^\s*Follow", r"^\s*Title", r"^\s*Date"])
            absn = extract_names_from_section(lines, r"^\s*Absentees", [r"^\s*Attendees", r"^\s*Decisions", r"^\s*Action Items", r"^\s*Follow", r"^\s*Title", r"^\s*Date"])
            if attn is not None and absn is not None:
                attn_norm = set(normalize_name(n) for n in attn if n.strip())
                absn_norm = set(normalize_name(n) for n in absn if n.strip())
                if attn_norm == expected_present and absn_norm == expected_absent:
                    scores["attendees_absentees_correct"] = 1.0

        if expected_agenda and expected_agenda.get("decisions"):
            all_found = True
            for dec in expected_agenda["decisions"]:
                if dec not in notes_text:
                    all_found = False
                    break
            if all_found:
                scores["decisions_copied_to_notes"] = 1.0

        if expected_agenda and expected_agenda.get("action_items"):
            notes_lower = notes_text.lower()
            has_action_items_header = ("action items" in notes_lower)
            open_count = len(re.findall(r"\bopen\b", notes_lower))
            items_ok = True
            for item in expected_agenda["action_items"]:
                owner = item["owner"]
                due = item["due_date"]
                prio = item["priority"]
                found = False
                for ln in lines:
                    ln_l = ln.lower()
                    if owner.lower() in ln_l and due.lower() in ln_l and prio.lower() in ln_l:
                        found = True
                        break
                if not found:
                    items_ok = False
                    break
            if has_action_items_header and items_ok and open_count >= len(expected_agenda["action_items"]):
                scores["notes_action_items_section_content"] = 1.0

        if expected_agenda and expected_agenda.get("action_items"):
            fu_idx = None
            for i, ln in enumerate(lines):
                if re.search(r"^\s*Follow[-\s]?ups\s*:\s*$", ln, flags=re.IGNORECASE) or re.search(r"^\s*Follow[-\s]?ups\s*$", ln, flags=re.IGNORECASE):
                    fu_idx = i + 1
                    break
            if fu_idx is not None:
                bullets = []
                for j in range(fu_idx, len(lines)):
                    ln = lines[j].strip()
                    if not ln:
                        break
                    if re.match(r"^\s*\w[\w\s]*:\s*$", ln) and not ln.startswith("-") and not ln.startswith("*"):
                        break
                    if ln.startswith("-") or ln.startswith("*") or ln.startswith("•"):
                        bullets.append(re.sub(r"^[\-\*\•]\s*", "", ln).strip())
                found_all = True
                for item in expected_agenda["action_items"]:
                    owner = item["owner"].lower()
                    due = item["due_date"].lower()
                    prio = item["priority"].lower()
                    ok = False
                    for b in bullets:
                        bl = b.lower()
                        if owner in bl and due in bl and prio in bl:
                            ok = True
                            break
                    if not ok:
                        found_all = False
                        break
                if found_all and len(bullets) >= len(expected_agenda["action_items"]):
                    scores["follow_ups_section_quality"] = 1.0

    headers, rows = safe_load_csv_dicts(csv_path)
    if headers is not None and rows is not None:
        expected_headers = ["task", "owner", "due_date", "priority", "status"]
        lower_headers = [h.lower() for h in headers]
        if lower_headers == expected_headers:
            scores["action_items_csv_structure"] = 1.0
        if expected_agenda and expected_agenda.get("action_items"):
            if len(rows) == len(expected_agenda["action_items"]):
                expected_set = set()
                for item in expected_agenda["action_items"]:
                    expected_set.add((
                        (item["task"] or "").strip().lower(),
                        (item["owner"] or "").strip().lower(),
                        (item["due_date"] or "").strip().lower(),
                        (item["priority"] or "").strip().lower(),
                        "open",
                    ))
                got_set = set()
                for r in rows:
                    got_set.add((
                        (r.get("task") or "").strip().lower(),
                        (r.get("owner") or "").strip().lower(),
                        (r.get("due_date") or "").strip().lower(),
                        (r.get("priority") or "").strip().lower(),
                        (r.get("status") or "").strip().lower(),
                    ))
                if expected_set.issubset(got_set) and all((r.get("status") or "").strip().lower() == "open" for r in rows):
                    scores["action_items_csv_content"] = 1.0

    entries = load_trigger_log(workspace)
    target_filename = f"agenda_{date_str}.md"
    if entries is not None:
        cnt = count_log_for_filename(entries, target_filename)
        rec = find_log_record(entries, target_filename)
        if cnt >= 1 and rec is not None and isinstance(rec.get("timestamp"), str) and rec.get("timestamp"):
            scores["trigger_log_contains_record"] = 1.0

    if script_path.exists():
        before_entries = load_trigger_log(workspace) or []
        before_cnt = count_log_for_filename(before_entries, target_filename)
        ran2, rc2, _, err2 = run_once_script(workspace)
        after_entries = load_trigger_log(workspace) or []
        after_cnt = count_log_for_filename(after_entries, target_filename)
        if after_cnt <= max(before_cnt, 1) and after_cnt >= 1:
            scores["idempotent_processing"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()