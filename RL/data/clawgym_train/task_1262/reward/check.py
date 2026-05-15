import json
import re
import sys
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_simple_kv_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Very simple YAML key: value mapping parser for flat config files.
    Supports string values possibly quoted. Ignores comments and blank lines.
    """
    text = _read_text(path)
    if text is None:
        return None
    cfg: Dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove surrounding quotes if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        # Try to coerce ints
        if re.fullmatch(r"-?\d+", val):
            try:
                ival = int(val)
                cfg[key] = ival
                continue
            except Exception:
                pass
        # Try to coerce booleans
        lv = val.lower()
        if lv in ("true", "false"):
            cfg[key] = (lv == "true")
            continue
        cfg[key] = val
    return cfg


def _parse_resources_yaml(path: Path) -> Optional[Dict[str, Dict[str, List[str]]]]:
    """
    Parse the provided resources.yaml which has structure:
    prep:
      Topic:
        - "Item 1"
        - "Item 2"
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    data: Dict[str, Dict[str, List[str]]] = {}
    current_section: Optional[str] = None
    current_topic: Optional[str] = None
    for raw in lines:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        # Detect top-level section (no leading spaces)
        m_section = re.match(r"^(\w+):\s*$", raw)
        if m_section and not raw.startswith(" "):
            current_section = m_section.group(1)
            data.setdefault(current_section, {})
            current_topic = None
            continue
        # Detect topic under a section (2 spaces indent)
        m_topic = re.match(r"^\s{2}([^\:]+):\s*$", raw)
        if m_topic and current_section is not None:
            current_topic = m_topic.group(1).strip()
            data[current_section].setdefault(current_topic, [])
            continue
        # Detect list item (4 spaces indent, dash)
        m_item = re.match(r"^\s{4}-\s+(.*)$", raw)
        if m_item and current_section is not None and current_topic is not None:
            item = m_item.group(1).strip()
            # strip quotes
            if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                item = item[1:-1]
            data[current_section][current_topic].append(item)
            continue
    return data


def _parse_csv_bookings(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows: List[Dict[str, Any]] = []
            for r in reader:
                try:
                    gsize = int(str(r.get("group_size", "0")).strip() or "0")
                except Exception:
                    gsize = 0
                rows.append({
                    "tour_id": (r.get("tour_id") or "").strip(),
                    "date": (r.get("date") or "").strip(),
                    "time": (r.get("time") or "").strip(),
                    "group_name": (r.get("group_name") or "").strip(),
                    "group_size": gsize,
                    "focus": (r.get("focus") or "").strip(),
                    "contact_email": (r.get("contact_email") or "").strip(),
                    "notes": (r.get("notes") or "").strip(),
                })
            return rows
    except Exception:
        return None


def _parse_exhibits_html(path: Path) -> Optional[Dict[str, List[str]]]:
    text = _read_text(path)
    if text is None:
        return None
    # Minimal extractor: <li data-topic="Topic">Text</li>
    li_re = re.compile(r'<li[^>]*data-topic="(?P<topic>[^"]+)"[^>]*>(?P<text>[^<]+)</li>')
    mapping: Dict[str, List[str]] = {}
    for m in li_re.finditer(text):
        topic = m.group("topic").strip()
        textval = m.group("text").strip()
        mapping.setdefault(topic, []).append(textval)
    return mapping


def _count_sentences(text: str) -> int:
    # Split on sentence terminators ., !, ?
    stripped = text.strip()
    if not stripped:
        return 0
    parts = re.split(r"(?<=[.!?])\s+", stripped)
    parts = [p for p in parts if p.strip()]
    return len(parts)


def _load_structured(path: Path) -> Optional[List[Dict[str, Any]]]:
    data = _read_json(path)
    if not isinstance(data, list):
        return None
    for item in data:
        if not isinstance(item, dict):
            return None
    return data


def _find_in_text(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()


def _check_watcher_pattern_strict(code: str) -> bool:
    """
    Check that watcher scans for bookings_YYYY-MM-DD.csv pattern (strict).
    Accept if code uses:
      - regex with \d{4}-\d{2}-\d{2}
      - explicit validation of filenames against that date pattern
    Reject loose glob like bookings_*.csv without validation.
    """
    # Look for regex date pattern tied to bookings_
    if re.search(r"bookings_\\d\{4\}-\\d\{2\}-\\d\{2\}\.csv", code):
        return True
    if re.search(r"bookings_\\d{4}-\\d{2}-\\d{2}\\.csv", code):
        return True
    if re.search(r"re\.compile\([^)]*bookings_.*\\d\{4\}-\\d\{2\}-\\d\{2\}\.csv", code):
        return True
    # A check that validates filename components after globbing
    if re.search(r"bookings_\{?\d{4}-\d{2}-\d{2}\}?\.csv", code):
        return True
    # If code uses glob pattern with question marks to enforce digits
    if re.search(r"glob\(\s*[\"']bookings_\?{4}-\?{2}-\?{2}\.csv[\"']\s*\)", code):
        return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_museum_and_tone_set": 0.0,
        "watcher_strict_filename_pattern": 0.0,
        "structured_output_present_and_valid": 0.0,
        "structured_highlights_correct": 0.0,
        "notifications_present": 0.0,
        "notifications_subjects_correct": 0.0,
        "notifications_bodies_content_and_length": 0.0,
        "notifications_accessibility_ack": 0.0,
        "message_limit_respected_in_notifications": 0.0,
        "meeting_notes_present": 0.0,
        "meeting_notes_tours_content": 0.0,
        "meeting_notes_action_items_scaled": 0.0,
        "processed_state_updated": 0.0,
        "processed_state_no_duplicates": 0.0,
    }

    # Load config
    cfg_path = workspace / "config" / "automation.yaml"
    cfg = _parse_simple_kv_yaml(cfg_path) if cfg_path.exists() else None

    # Check museum_name and tone are set and not TODO
    if isinstance(cfg, dict):
        museum_name = str(cfg.get("museum_name", "")).strip()
        tone = str(cfg.get("tone", "")).strip()
        if museum_name and "TODO" not in museum_name and tone and "TODO" not in tone:
            scores["config_museum_and_tone_set"] = 1.0

    # Static analysis of watcher.py for strict filename pattern
    watcher_path = workspace / "scripts" / "watcher.py"
    watcher_code = _read_text(watcher_path) if watcher_path.exists() else None
    if watcher_code:
        if _check_watcher_pattern_strict(watcher_code):
            scores["watcher_strict_filename_pattern"] = 1.0

    # Precompute expected booking data and exhibits mapping from inputs
    input_csv = workspace / "input" / "bookings_2024-11-04.csv"
    bookings: Optional[List[Dict[str, Any]]] = _parse_csv_bookings(input_csv) if input_csv.exists() else None
    exhibits_map = _parse_exhibits_html(workspace / "input" / "exhibits.html")

    # Structured output checks
    structured_path = workspace / "out" / "structured" / "bookings_2024-11-04.json"
    structured = _load_structured(structured_path) if structured_path.exists() else None
    if isinstance(structured, list) and len(structured) > 0:
        # Validate keys for all records
        required_keys = {"tour_id", "date", "time", "group_name", "group_size", "focus", "contact_email", "raw_notes", "highlights"}
        valid = True
        for rec in structured:
            if not isinstance(rec, dict) or not set(rec.keys()).issuperset(required_keys):
                valid = False
                break
            if not isinstance(rec.get("highlights"), list):
                valid = False
                break
        if valid:
            scores["structured_output_present_and_valid"] = 1.0

        # Highlights correctness: compare to exhibits_map first two entries for the focus
        if exhibits_map:
            all_ok = True
            for rec in structured:
                focus = rec.get("focus", "")
                expected_hi = exhibits_map.get(focus, [])[:2]
                if expected_hi:
                    if [str(x) for x in rec.get("highlights", [])[:2]] != expected_hi:
                        all_ok = False
                        break
            if all_ok:
                scores["structured_highlights_correct"] = 1.0

    # Notifications checks
    expected_ids = [
        ("T-1001", "2024-11-04", "10:00"),
        ("T-1002", "2024-11-04", "13:30"),
        ("T-1003", "2024-11-05", "11:00"),
    ]
    notif_root = workspace / "out" / "notifications"
    present_ok = True
    subjects_correct = True
    bodies_content_ok = True
    accessibility_ok = False
    message_limit_ok = True

    museum_name_cfg = ""
    message_max = None
    if isinstance(cfg, dict):
        museum_name_cfg = str(cfg.get("museum_name", "")).strip()
        try:
            message_max = int(cfg.get("message_max_sentences", 3))
        except Exception:
            message_max = 3

    # Build expected highlight names for per-focus
    expected_highlights = exhibits_map or {}
    # If bookings exist, build a mapping for quick lookup
    bookings_by_id: Dict[str, Dict[str, Any]] = {}
    if bookings:
        for b in bookings:
            bookings_by_id[b["tour_id"]] = b

    for tour_id, date_str, time_str in expected_ids:
        subj_path = notif_root / tour_id / "subject.txt"
        body_path = notif_root / tour_id / "body.txt"
        subj_text = _read_text(subj_path) if subj_path.exists() else None
        body_text = _read_text(body_path) if body_path.exists() else None

        if subj_text is None or body_text is None:
            present_ok = False
            continue  # can't do further checks for this id

        # Subject correctness
        if museum_name_cfg and museum_name_cfg not in subj_text:
            subjects_correct = False
        if "Tour Confirmation" not in subj_text:
            subjects_correct = False
        if (date_str not in subj_text) or (time_str not in subj_text):
            subjects_correct = False

        # Body content checks
        b = bookings_by_id.get(tour_id, None)
        if b:
            # Must include museum_name, group_name, date, time, group_size
            if museum_name_cfg and museum_name_cfg not in body_text:
                bodies_content_ok = False
            if b["group_name"] not in body_text:
                bodies_content_ok = False
            if b["date"] not in body_text or b["time"] not in body_text:
                bodies_content_ok = False
            if str(b["group_size"]) not in body_text:
                bodies_content_ok = False
            # Include at least one highlight from expected
            hl = expected_highlights.get(b["focus"], [])[:2]
            if hl:
                has_hl = any(_find_in_text(body_text, h) for h in hl)
                if not has_hl:
                    bodies_content_ok = False
            # Should not include literal "Draft msg:" prefix
            if re.search(r"\bDraft msg:\b", body_text, flags=re.IGNORECASE):
                bodies_content_ok = False
            # Sentence limit
            if message_max is not None:
                if _count_sentences(body_text) > message_max:
                    message_limit_ok = False
            # Accessibility acknowledgment for T-1002
            if tour_id == "T-1002":
                if re.search(r"accessibil", body_text, flags=re.IGNORECASE):
                    accessibility_ok = True

    if present_ok:
        scores["notifications_present"] = 1.0
    if subjects_correct and present_ok:
        scores["notifications_subjects_correct"] = 1.0
    if bodies_content_ok and present_ok:
        scores["notifications_bodies_content_and_length"] = 1.0
    if accessibility_ok and present_ok:
        scores["notifications_accessibility_ack"] = 1.0
    if message_limit_ok and present_ok:
        scores["message_limit_respected_in_notifications"] = 1.0

    # Meeting notes checks
    notes_root = workspace / "out" / "notes"
    notes_1104 = notes_root / "meeting_notes_2024-11-04.md"
    notes_1105 = notes_root / "meeting_notes_2024-11-05.md"
    n1104 = _read_text(notes_1104) if notes_1104.exists() else None
    n1105 = _read_text(notes_1105) if notes_1105.exists() else None

    if n1104 and n1105:
        # Require presence of section headers
        if ("Tours:" in n1104 and "Action Items:" in n1104) and ("Tours:" in n1105 and "Action Items:" in n1105):
            scores["meeting_notes_present"] = 1.0

    # Validate Tours section lines include info and highlights
    tours_content_ok = False
    action_items_ok = False
    if n1104 and n1105 and bookings and exhibits_map:
        def has_tour_line(note_text: str, booking: Dict[str, Any], exp_hl: List[str]) -> bool:
            pattern = re.compile(
                re.escape(booking["tour_id"]) + r".*" +
                re.escape(booking["time"]) + r".*" +
                re.escape(booking["group_name"]) + r".*" +
                r"\(" + re.escape(str(booking["group_size"])) + r"\)" + r".*" +
                re.escape(booking["focus"]),
                flags=re.DOTALL
            )
            if not pattern.search(note_text):
                return False
            if exp_hl:
                return all(_find_in_text(note_text, h) for h in exp_hl[:2])
            return True

        b1 = [b for b in bookings if b["tour_id"] == "T-1001"]
        b2 = [b for b in bookings if b["tour_id"] == "T-1002"]
        b3 = [b for b in bookings if b["tour_id"] == "T-1003"]
        cond1 = False
        cond2 = False
        cond3 = False
        if b1:
            exp_hl1 = exhibits_map.get(b1[0]["focus"], [])[:2]
            cond1 = has_tour_line(n1104, b1[0], exp_hl1)
        if b2:
            exp_hl2 = exhibits_map.get(b2[0]["focus"], [])[:2]
            cond2 = has_tour_line(n1104, b2[0], exp_hl2)
        if b3:
            exp_hl3 = exhibits_map.get(b3[0]["focus"], [])[:2]
            cond3 = has_tour_line(n1105, b3[0], exp_hl3)
        if cond1 and cond2 and cond3:
            tours_content_ok = True

        # Action items scaling
        ai1 = re.search(r"Print\s+24\s+puzzle handouts", n1104 or "", flags=re.IGNORECASE) is not None
        ai2 = re.search(r"Prepare\s+18\s+veteran-friendly seats", n1104 or "", flags=re.IGNORECASE) is not None
        home_front_presence = ("Bring ration book replicas" in (n1105 or "")) or ("Set up Victory Garden tools" in (n1105 or ""))
        if ai1 and ai2 and home_front_presence:
            action_items_ok = True

    if tours_content_ok and scores["meeting_notes_present"] == 1.0:
        scores["meeting_notes_tours_content"] = 1.0
    if action_items_ok and scores["meeting_notes_present"] == 1.0:
        scores["meeting_notes_action_items_scaled"] = 1.0

    # Processed state checks
    state_path = workspace / "state" / "processed.json"
    state = _read_json(state_path) if state_path.exists() else None
    if isinstance(state, dict) and isinstance(state.get("processed"), list):
        processed_list = state.get("processed")
        if "bookings_2024-11-04.csv" in processed_list:
            scores["processed_state_updated"] = 1.0
        if len(processed_list) == len(set(processed_list)):
            scores["processed_state_no_duplicates"] = 1.0

    return scores


def main() -> None:
    workspace_arg = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_arg)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()