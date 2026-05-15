import json
import sys
import re
import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _strip_inline_comment(line: str) -> str:
    # Remove inline comments introduced by ' #' or trailing '#' if preceded by space
    if " #" in line:
        return line.split(" #", 1)[0]
    # Also handle case where comment starts immediately after value without space (unlikely here)
    # but avoid removing hashes inside quoted strings.
    # Basic heuristic: if there's a '#' and it's after some space, trim from there.
    if "#" in line:
        idx = line.find("#")
        # If everything before '#' contains a quote that isn't closed, skip removal
        before = line[:idx]
        if before.strip():
            return before.rstrip()
    return line


def _parse_scalar(value: str) -> Any:
    v = value.strip()
    if v == "":
        return ""
    # strip quotes
    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
        v = v[1:-1]
        return v
    # list like [1, 2, 3] or ['a', 'b']
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if inner == "":
            return []
        parts = [p.strip() for p in inner.split(",")]
        out = []
        for p in parts:
            if (p.startswith("'") and p.endswith("'")) or (p.startswith('"') and p.endswith('"')):
                out.append(p[1:-1])
            else:
                # try int
                try:
                    out.append(int(p))
                except Exception:
                    out.append(p)
        return out
    # try int
    try:
        return int(v)
    except Exception:
        pass
    # otherwise return as string
    return v


def _parse_kv(text: str) -> Tuple[str, Any]:
    if ":" not in text:
        return text.strip(), None
    key, val = text.split(":", 1)
    key = key.strip()
    val = _parse_scalar(val)
    return key, val


def _load_simple_reminders_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Very simple YAML parser tailored to the expected structure:
    window:
      start: 'YYYY-MM-DD'
      end: 'YYYY-MM-DD'
    channels:
      - name: Email
        days_before: [14, 7, 1]
        template: 'path'
      - name: SMS
        days_before: [1]
        template: 'path'
    """
    txt = _read_text(path)
    if txt is None:
        return None
    lines = [ln.rstrip("\n\r") for ln in txt.splitlines()]
    # remove full-line comments and trim inline comments
    processed = []
    for ln in lines:
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        no_comment = _strip_inline_comment(ln)
        if no_comment.strip() == "":
            continue
        processed.append(no_comment.rstrip())

    cfg: Dict[str, Any] = {}
    i = 0
    n = len(processed)
    while i < n:
        line = processed[i]
        if not line.strip():
            i += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent != 0:
            # Unexpected indentation at top-level; skip
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _ = _parse_kv(line)
        if key == "window":
            # Expect nested keys start and end
            i += 1
            win: Dict[str, Any] = {}
            while i < n:
                sub = processed[i]
                sub_indent = len(sub) - len(sub.lstrip(" "))
                if sub_indent <= indent:
                    break
                skey, sval = _parse_kv(sub.strip())
                if skey:
                    win[skey] = sval
                i += 1
            cfg["window"] = win
            continue
        elif key == "channels":
            # Parse list of maps
            i += 1
            channels: List[Dict[str, Any]] = []
            current: Optional[Dict[str, Any]] = None
            while i < n:
                sub = processed[i]
                sub_indent = len(sub) - len(sub.lstrip(" "))
                if sub_indent <= indent:
                    break
                sub_stripped = sub.strip()
                if sub_stripped.startswith("- "):
                    # start new item
                    if current is not None:
                        channels.append(current)
                    current = {}
                    rest = sub_stripped[2:].strip()
                    if rest:
                        k, v = _parse_kv(rest)
                        if k:
                            current[k] = v
                    i += 1
                    # consume following key/values with greater indent
                    while i < n:
                        sub2 = processed[i]
                        sub2_indent = len(sub2) - len(sub2.lstrip(" "))
                        if sub2_indent <= sub_indent:
                            break
                        k2, v2 = _parse_kv(sub2.strip())
                        if k2:
                            current[k2] = v2
                        i += 1
                    continue
                else:
                    i += 1
            # append last current if exists
            if current is not None:
                channels.append(current)
            cfg["channels"] = channels
            continue
        else:
            # Generic top-level scalar
            _, val = _parse_kv(line)
            cfg[key] = val
            i += 1
            continue
    return cfg


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            rows = []
            for r in rdr:
                # Normalize None to empty strings
                rows.append({k: (v if v is not None else "") for k, v in r.items()})
            return rows
    except Exception:
        return None


def _safe_read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.reader(f)
            header = next(rdr, None)
            if header is None:
                return []
            return header
    except Exception:
        return None


def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        return None


def _compute_expected_schedule(cfg: Dict[str, Any], events_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, str]]]:
    try:
        w = cfg.get("window") or {}
        ws = _parse_iso_date(str(w.get("start", "")).strip())
        we = _parse_iso_date(str(w.get("end", "")).strip())
        if ws is None or we is None:
            return None
        channels = cfg.get("channels")
        if not isinstance(channels, list):
            return None
        ch_list = []
        for ch in channels:
            if not isinstance(ch, dict):
                return None
            name = ch.get("name")
            template = ch.get("template")
            offsets = ch.get("days_before")
            if name is None or template is None:
                return None
            if offsets is None or not isinstance(offsets, list):
                return None
            int_offsets: List[int] = []
            for o in offsets:
                try:
                    int_offsets.append(int(o))
                except Exception:
                    return None
            ch_list.append({"name": str(name), "template": str(template), "days_before": int_offsets})
        expected: List[Dict[str, str]] = []
        for ev in events_rows:
            status = (ev.get("status") or "").strip().lower()
            if status != "planned":
                continue
            ev_dt = _parse_iso_date(ev.get("event_date", ""))
            if ev_dt is None:
                continue
            if not (ws <= ev_dt <= we):
                continue
            for ch in ch_list:
                for d in ch["days_before"]:
                    send_dt = ev_dt - timedelta(days=int(d))
                    expected.append({
                        "event_name": (ev.get("event_name") or "").strip(),
                        "event_date": ev_dt.isoformat(),
                        "channel": ch["name"],
                        "send_date": send_dt.isoformat(),
                        "template_path": ch["template"],
                    })
        return expected
    except Exception:
        return None


def _rows_canonical(rows: List[Dict[str, str]], keys: List[str]) -> List[Tuple]:
    canon = []
    for r in rows:
        tup = tuple((r.get(k, "") or "").strip() for k in keys)
        canon.append(tup)
    return canon


def _extract_meeting_info(raw_md_path: Path) -> Tuple[List[str], List[Dict[str, str]], List[str]]:
    """
    Returns (decisions, actions, attendees_names)
    actions: list of dicts with owner, task, due_date
    """
    txt = _read_text(raw_md_path) or ""
    lines = txt.splitlines()
    decisions: List[str] = []
    actions: List[Dict[str, str]] = []
    attendees: List[str] = []

    # Attendees line
    for ln in lines:
        if ln.strip().lower().startswith("attendees:"):
            content = ln.split(":", 1)[1].strip()
            parts = [p.strip() for p in content.split(",") if p.strip()]
            names = []
            for p in parts:
                if " (" in p:
                    names.append(p.split(" (", 1)[0].strip())
                else:
                    names.append(p.strip())
            attendees = names
            break

    # Decisions and Actions
    dec_re = re.compile(r"\[DECISION\]\s*(.+)")
    act_re = re.compile(r"\[ACTION\s+owner:([^\s\]]+)\s+due:([0-9]{4}-[0-9]{2}-[0-9]{2})\]\s*(.+)")
    for ln in lines:
        m = dec_re.search(ln)
        if m:
            decisions.append(m.group(1).strip())
        m2 = act_re.search(ln)
        if m2:
            owner = m2.group(1).strip()
            due = m2.group(2).strip()
            task = m2.group(3).strip()
            actions.append({"owner": owner, "task": task, "due_date": due, "status": "open"})
    return decisions, actions, attendees


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "yaml_updated_days_before_keys": 0.0,
        "scheduled_reminders_file_exists_and_schema": 0.0,
        "scheduled_reminders_content_correct": 0.0,
        "scheduled_reminders_sorted": 0.0,
        "minutes_file_has_sections": 0.0,
        "minutes_decisions_extracted": 0.0,
        "minutes_action_items_listed": 0.0,
        "action_items_csv_schema": 0.0,
        "action_items_csv_content": 0.0,
        "template_updated_file_exists": 0.0,
        "template_sponsor_blurb_inserted": 0.0,
        "template_supply_list_bullets": 0.0,
        "template_base_content_preserved": 0.0,
    }

    # Part 1: Reminder scheduler
    cfg_path = workspace / "config" / "reminders.yaml"
    cfg = _load_simple_reminders_yaml(cfg_path) if cfg_path.exists() else None

    # yaml_updated_days_before_keys
    yaml_ok = False
    if cfg is not None and isinstance(cfg.get("channels"), list):
        chs = cfg.get("channels") or []
        all_have_days_before = True
        for ch in chs:
            if not isinstance(ch, dict):
                all_have_days_before = False
                break
            offsets = ch.get("days_before")
            if offsets is None or not isinstance(offsets, list):
                all_have_days_before = False
                break
            # check all ints/coerceable
            try:
                _ = [int(o) for o in offsets]
            except Exception:
                all_have_days_before = False
                break
        if all_have_days_before:
            yaml_ok = True
    scores["yaml_updated_days_before_keys"] = 1.0 if yaml_ok else 0.0

    scheduled_path = workspace / "out" / "scheduled_reminders.csv"
    header = _safe_read_csv_header(scheduled_path) if scheduled_path.exists() else None
    expected_header = ["event_name", "event_date", "channel", "send_date", "template_path"]
    if header is not None and header == expected_header:
        scores["scheduled_reminders_file_exists_and_schema"] = 1.0
    else:
        scores["scheduled_reminders_file_exists_and_schema"] = 0.0

    # scheduled_reminders_content_correct
    actual_rows = _safe_read_csv_dicts(scheduled_path) if scheduled_path.exists() else None
    if actual_rows is not None and header == expected_header and cfg is not None and yaml_ok:
        events_rows = _safe_read_csv_dicts(workspace / "input" / "events.csv") or []
        expected_rows = _compute_expected_schedule(cfg, events_rows)
        if expected_rows is not None:
            # compare as sets of tuples over expected_header keys
            act_set = set(_rows_canonical(actual_rows, expected_header))
            exp_set = set(_rows_canonical(expected_rows, expected_header))
            if act_set == exp_set:
                scores["scheduled_reminders_content_correct"] = 1.0
            else:
                scores["scheduled_reminders_content_correct"] = 0.0
        else:
            scores["scheduled_reminders_content_correct"] = 0.0
    else:
        scores["scheduled_reminders_content_correct"] = 0.0

    # scheduled_reminders_sorted
    if actual_rows is not None and header == expected_header:
        # Check sorted by (send_date, channel, event_name)
        def key_fn(r: Dict[str, str]) -> Tuple[str, str, str]:
            return ((r.get("send_date") or "").strip(),
                    (r.get("channel") or "").strip(),
                    (r.get("event_name") or "").strip())
        sorted_rows = sorted(actual_rows, key=key_fn)
        if [key_fn(r) for r in actual_rows] == [key_fn(r) for r in sorted_rows]:
            scores["scheduled_reminders_sorted"] = 1.0
        else:
            scores["scheduled_reminders_sorted"] = 0.0
    else:
        scores["scheduled_reminders_sorted"] = 0.0

    # Part 2: Meeting minutes and action items
    raw_meeting_path = workspace / "input" / "meeting_2026-04-13_raw.md"
    decisions_expected: List[str] = []
    actions_expected: List[Dict[str, str]] = []
    attendees_expected: List[str] = []
    if raw_meeting_path.exists():
        decisions_expected, actions_expected, attendees_expected = _extract_meeting_info(raw_meeting_path)

    minutes_path = workspace / "out" / "meeting_minutes_2026-04-13.md"
    minutes_text = _read_text(minutes_path) if minutes_path.exists() else None

    # minutes_file_has_sections
    if minutes_text is not None:
        lines = minutes_text.splitlines()
        def has_heading(title: str) -> bool:
            pat = re.compile(r"^\s*#{1,6}\s*"+re.escape(title)+r"\s*$")
            return any(pat.match(ln) for ln in lines)
        if has_heading("Attendees") and has_heading("Decisions") and has_heading("Action Items"):
            scores["minutes_file_has_sections"] = 1.0
        else:
            scores["minutes_file_has_sections"] = 0.0
    else:
        scores["minutes_file_has_sections"] = 0.0

    # minutes_decisions_extracted
    if minutes_text is not None and decisions_expected:
        all_present = all(d in minutes_text for d in decisions_expected)
        scores["minutes_decisions_extracted"] = 1.0 if all_present else 0.0
    else:
        scores["minutes_decisions_extracted"] = 0.0

    # minutes_action_items_listed
    if minutes_text is not None and actions_expected:
        all_tasks_present = all((ai["task"] in minutes_text) for ai in actions_expected)
        scores["minutes_action_items_listed"] = 1.0 if all_tasks_present else 0.0
    else:
        scores["minutes_action_items_listed"] = 0.0

    # action_items_csv_schema and content
    ai_csv_path = workspace / "out" / "action_items_2026-04-13.csv"
    ai_header = _safe_read_csv_header(ai_csv_path) if ai_csv_path.exists() else None
    ai_expected_header = ["owner", "task", "due_date", "status"]
    if ai_header is not None and ai_header == ai_expected_header:
        scores["action_items_csv_schema"] = 1.0
    else:
        scores["action_items_csv_schema"] = 0.0

    ai_rows = _safe_read_csv_dicts(ai_csv_path) if ai_csv_path.exists() else None
    if ai_rows is not None and ai_header == ai_expected_header and actions_expected:
        # Compare content: exactly the set of expected actions with status "open"
        expected_ai = [{"owner": a["owner"], "task": a["task"], "due_date": a["due_date"], "status": "open"} for a in actions_expected]
        act_set = set(_rows_canonical(ai_rows, ai_expected_header))
        exp_set = set(_rows_canonical(expected_ai, ai_expected_header))
        if act_set == exp_set and len(ai_rows) == len(expected_ai):
            scores["action_items_csv_content"] = 1.0
        else:
            scores["action_items_csv_content"] = 0.0
    else:
        scores["action_items_csv_content"] = 0.0

    # Part 3: Updated email template
    updated_tpl_path = workspace / "out" / "templates" / "reminder_email_template_updated.md"
    if updated_tpl_path.exists():
        scores["template_updated_file_exists"] = 1.0
    else:
        scores["template_updated_file_exists"] = 0.0

    updated_tpl_text = _read_text(updated_tpl_path) if updated_tpl_path.exists() else None
    # sponsor blurb inserted and placeholder removed
    sponsor_blurb_path = workspace / "input" / "sponsor_blurb.md"
    sponsor_blurb_text = _read_text(sponsor_blurb_path) or ""
    sponsor_blurb_text_stripped = sponsor_blurb_text.strip()
    if updated_tpl_text is not None and sponsor_blurb_text_stripped:
        blurb_present = sponsor_blurb_text_stripped in updated_tpl_text
        placeholder_absent = "<!-- SPONSOR_BLURB -->" not in updated_tpl_text
        if blurb_present and placeholder_absent:
            scores["template_sponsor_blurb_inserted"] = 1.0
        else:
            scores["template_sponsor_blurb_inserted"] = 0.0
    else:
        scores["template_sponsor_blurb_inserted"] = 0.0

    # supply list bullets
    inv_path = workspace / "input" / "materials_inventory.csv"
    include_rows = []
    inv_rows = _safe_read_csv_dicts(inv_path) or []
    for r in inv_rows:
        event = (r.get("event") or "").strip()
        include = (r.get("include_in_email") or "").strip().lower()
        if event == "Charity Blanket Drive" and include == "yes":
            item = (r.get("item") or "").strip()
            qty = (r.get("quantity") or "").strip()
            unit = (r.get("unit") or "").strip()
            bullet = f"- {item} — {qty} {unit}"
            include_rows.append(bullet)
    excluded_bullet = "- Tapestry needles — 10 packs"
    if updated_tpl_text is not None and include_rows:
        all_included_present = all(b in updated_tpl_text for b in include_rows)
        excluded_absent = excluded_bullet not in updated_tpl_text
        placeholder_absent = "<!-- SUPPLY_LIST: EVENT=Charity Blanket Drive -->" not in updated_tpl_text
        if all_included_present and excluded_absent and placeholder_absent:
            scores["template_supply_list_bullets"] = 1.0
        else:
            scores["template_supply_list_bullets"] = 0.0
    else:
        scores["template_supply_list_bullets"] = 0.0

    # base content preserved
    base_ok = False
    if updated_tpl_text is not None:
        checks = [
            "# Event Reminder: {{event_name}}",
            "Hi everyone,",
            "## Supplies",
            "Thanks and happy knitting!",
            "— Purl & Loop Yarn Shop",
            "{{event_date}}",
            "{{location}}",
        ]
        base_ok = all(ch in updated_tpl_text for ch in checks)
    scores["template_base_content_preserved"] = 1.0 if base_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()