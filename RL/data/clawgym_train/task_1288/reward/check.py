import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_minimal_yaml(text: str) -> Optional[Dict[str, Any]]:
    data: Dict[str, Any] = {}
    in_list_key: Optional[str] = None
    for raw in text.splitlines():
        line = raw.rstrip("\n\r")
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        # List item under a previously opened list key
        if in_list_key and line.strip().startswith("- "):
            item = line.strip()[2:].strip()
            if item.startswith('"') and item.endswith('"') and len(item) >= 2:
                item = item[1:-1]
            if item.startswith("'") and item.endswith("'") and len(item) >= 2:
                item = item[1:-1]
            data[in_list_key].append(item)
            continue
        # Top-level key
        if ":" in line and not line.startswith("  ") and not line.startswith("\t"):
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            in_list_key = None
            if val == "":
                data[key] = []
                in_list_key = key
            else:
                if val.startswith("[") and val.endswith("]"):
                    inside = val[1:-1].strip()
                    if inside == "":
                        data[key] = []
                    else:
                        items = [x.strip() for x in inside.split(",")]
                        cleaned = []
                        for it in items:
                            if it.startswith('"') and it.endswith('"') and len(it) >= 2:
                                it = it[1:-1]
                            if it.startswith("'") and it.endswith("'") and len(it) >= 2:
                                it = it[1:-1]
                            cleaned.append(it)
                        data[key] = cleaned
                else:
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    data[key] = val
            continue
        # Ignore unsupported structures
    return data


def _parse_front_matter_and_body(text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    lines = text.splitlines()
    if not lines:
        return None, None
    if lines[0].strip() != "---":
        return None, None
    fm_lines: List[str] = []
    idx = 1
    while idx < len(lines) and lines[idx].strip() != "---":
        fm_lines.append(lines[idx])
        idx += 1
    if idx >= len(lines) or lines[idx].strip() != "---":
        return None, None
    body_lines = lines[idx + 1 :]
    fm_text = "\n".join(fm_lines)
    body_text = "\n".join(body_lines)
    fm = _parse_minimal_yaml(fm_text) or {}
    return fm, body_text


def _extract_headings(body: str) -> List[Tuple[str, int]]:
    headings: List[Tuple[str, int]] = []
    lines = body.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if m:
            headings.append((m.group(1).strip(), i))
    return headings


def _extract_section(body: str, heading_title: str) -> Optional[str]:
    lines = body.splitlines()
    start_idx: Optional[int] = None
    for i, line in enumerate(lines):
        m = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if m and m.group(1).strip() == heading_title:
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if re.match(r"^\s{0,3}#{1,6}\s+.+$", lines[j]):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def _parse_list_items(section_text: Optional[str]) -> List[str]:
    if not section_text:
        return []
    lines = section_text.splitlines()
    items: List[str] = []
    current: List[str] = []
    for line in lines:
        if re.match(r"^\s*[-\*]\s+", line):
            if current:
                items.append("\n".join(current).strip())
                current = []
            current.append(line.strip()[2:].strip())
        else:
            if current:
                current.append(line.rstrip())
    if current:
        items.append("\n".join(current).strip())
    return [i for i in items if i.strip()]


def _compute_absolute_url(cfg: Dict[str, Any], date_iso: str, slug: str) -> Optional[str]:
    try:
        base = (cfg.get("url") or "").rstrip("/")
        pattern = (cfg.get("permalink") or "").strip()
        if not base or not pattern:
            return None
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", date_iso)
        if not m:
            return None
        year, month, day = m.group(1), m.group(2), m.group(3)
        if not pattern.startswith("/"):
            pattern = "/" + pattern
        path = pattern
        path = path.replace(":year", year).replace(":month", month).replace(":day", day).replace(":title", slug)
        while "//" in path:
            path = path.replace("//", "/")
        return base + path
    except Exception:
        return None


def _parse_notes(text: str) -> Dict[str, Any]:
    notes: Dict[str, Any] = {
        "meeting_date_iso": None,
        "decisions": [],
        "actions": [],
        "deferred": [],
        "next_meeting": None,
    }
    m_date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if m_date:
        notes["meeting_date_iso"] = m_date.group(1)
    for line in text.splitlines():
        if line.strip().startswith("DECISION:"):
            val = line.split("DECISION:", 1)[1].strip()
            if not val.endswith("."):
                val = val + "."
            notes["decisions"].append(val)
        if line.strip().startswith("DEFERRED:"):
            val = line.split("DEFERRED:", 1)[1].strip()
            if not val.endswith("."):
                val = val + "."
            notes["deferred"].append(val)
    action_re = re.compile(
        r"^ACTION:\s*Owner:\s*(?P<owner>[^—\-]+?)\s*[—\-]\s*(?P<desc>.*?)(?:\s+by\s+(?P<due>[^.]+))?\.",
        re.UNICODE,
    )
    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("ACTION:"):
            m = action_re.match(line_stripped)
            if m:
                owner = m.group("owner").strip()
                desc = (m.group("desc") or "").strip()
                due = (m.group("due") or "").strip()
                notes["actions"].append({"owner": owner, "due": due, "desc": desc, "raw": line_stripped})
            else:
                owner = ""
                due = ""
                mo = re.search(r"Owner:\s*([^—\-]+)", line_stripped)
                if mo:
                    owner = mo.group(1).strip()
                md = re.search(r"\bby\s+([^\.]+)", line_stripped)
                if md:
                    due = md.group(1).strip()
                notes["actions"].append({"owner": owner, "due": due, "desc": "", "raw": line_stripped})
    nm_line = None
    for line in text.splitlines():
        if line.strip().lower().startswith("next meeting:"):
            nm_line = line.strip()
            break
    notes["next_meeting"] = nm_line
    return notes


EXPECTED_ORIGINAL_NOTES = """# Homeschool Co-op Planning Meeting — 2024-09-14

Date: Saturday, Sept 14, 2024, 9:30–11:15 AM
Location: Community Center, Room B
Attendees: Maya (Coordinator), Leo (Dad), Priya (Mom), Sam (Science Lead), Nina (Art)

Agenda:
1. Fall session schedule
2. Volunteers & roles
3. Budget & supplies
4. Field trip ideas

Discussion highlights:
- Families prefer 2-hour blocks in the morning.
- Science and art will alternate rooms; younger kids stay near art.

DECISION: Fall co-op will run for 8 Saturdays, Oct 12–Nov 30, 9:30–11:30 AM.
DECISION: Supplies budget cap set to $150 total; recommend $20 per-family materials fee.

ACTION: Owner: Maya — Draft the class schedule and share a Google Doc by Sep 21, 2024.
ACTION: Owner: Leo — Send volunteer preference form to parents by Sep 18, 2024.
ACTION: Owner: Priya — Price bulk art supplies (paint, brushes, paper) and email options by Sep 25, 2024.

DEFERRED: Choose spring field trip destination; revisit on Oct 26 meeting.

Next meeting: Saturday, Sep 28, 2024 at 9:00 AM (same location).
"""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "post_file_exists": 0.0,
        "post_front_matter_fields": 0.0,
        "post_title_and_date_correct": 0.0,
        "post_categories_valid": 0.0,
        "post_tags_valid": 0.0,
        "post_sections_order": 0.0,
        "post_decisions_included": 0.0,
        "post_action_items_included": 0.0,
        "post_deferred_included": 0.0,
        "post_next_meeting_present": 0.0,
        "email_file_exists_and_subject": 0.0,
        "email_action_items_match": 0.0,
        "email_full_recap_link": 0.0,
        "notes_publishing_appended": 0.0,
        "notes_original_preserved": 0.0,
    }

    # Paths
    config_path = workspace / "site" / "_config.yml"
    notes_path = workspace / "content" / "drafts" / "co-op-planning-notes.md"
    post_path = workspace / "output" / "posts" / "2024-09-14-co-op-planning-meeting.md"
    email_path = workspace / "output" / "email" / "co-op-parents-2024-09-14.txt"

    # Read and parse config
    cfg_text = _read_text(config_path) or ""
    cfg = _parse_minimal_yaml(cfg_text) if cfg_text else None
    allowed_categories: List[str] = []
    allowed_tags: List[str] = []
    if cfg:
        allowed_categories = cfg.get("allowed_categories") or []
        allowed_tags = cfg.get("allowed_tags") or []

    # Read notes
    notes_text = _read_text(notes_path) or ""
    if notes_text:
        notes = _parse_notes(notes_text)
    else:
        notes = {"decisions": [], "actions": [], "deferred": [], "meeting_date_iso": None, "next_meeting": None}

    meeting_date = notes.get("meeting_date_iso") or "2024-09-14"
    absolute_url = _compute_absolute_url(cfg if cfg else {}, meeting_date, "co-op-planning-meeting") if cfg else None

    # Post checks
    post_text = _read_text(post_path)
    if post_text is not None:
        scores["post_file_exists"] = 1.0
        fm, body = _parse_front_matter_and_body(post_text)
        if fm is not None and body is not None:
            has_all_fields = all(k in fm for k in ["title", "date", "categories", "tags"]) and isinstance(fm.get("categories"), list) and isinstance(fm.get("tags"), list)
            if has_all_fields:
                scores["post_front_matter_fields"] = 1.0
            expected_title = "Co-op Planning Meeting (Sept 14, 2024)"
            title_ok = str(fm.get("title", "")).strip() == expected_title
            date_ok = str(fm.get("date", "")).strip() == "2024-09-14"
            if title_ok and date_ok:
                scores["post_title_and_date_correct"] = 1.0
            cats = fm.get("categories") if isinstance(fm.get("categories"), list) else []
            if cats == ["co-op"] and ("co-op" in allowed_categories if allowed_categories else False):
                scores["post_categories_valid"] = 1.0
            tags = fm.get("tags") if isinstance(fm.get("tags"), list) else []
            if isinstance(tags, list) and len(tags) >= 2 and allowed_tags and all(t in allowed_tags for t in tags):
                scores["post_tags_valid"] = 1.0
            # Sections order check
            expected_headings = ["Overview", "Decisions", "Action Items", "Deferred Items", "Next Meeting"]
            headings = _extract_headings(body)
            if headings:
                # Map each expected heading to its first line index in body
                line_indices: List[int] = []
                ok = True
                for eh in expected_headings:
                    idxs = [li for (ht, li) in headings if ht == eh]
                    if not idxs:
                        ok = False
                        break
                    line_indices.append(idxs[0])
                if ok:
                    # strictly increasing order
                    if all(line_indices[i] < line_indices[i + 1] for i in range(len(line_indices) - 1)):
                        scores["post_sections_order"] = 1.0
            # Decisions included
            decisions_section = _extract_section(body, "Decisions")
            decisions_ok = False
            if decisions_section is not None:
                all_present = True
                for d in notes.get("decisions", []):
                    if not d or d not in decisions_section:
                        all_present = False
                        break
                if all_present and notes.get("decisions"):
                    decisions_ok = True
            scores["post_decisions_included"] = 1.0 if decisions_ok else 0.0
            # Deferred included
            deferred_section = _extract_section(body, "Deferred Items")
            deferred_ok = False
            if deferred_section is not None:
                all_present = True
                for d in notes.get("deferred", []):
                    if not d or d not in deferred_section:
                        all_present = False
                        break
                if all_present and notes.get("deferred"):
                    deferred_ok = True
            scores["post_deferred_included"] = 1.0 if deferred_ok else 0.0
            # Action items included
            action_section = _extract_section(body, "Action Items")
            action_ok = False
            if action_section is not None:
                items = _parse_list_items(action_section)
                expected_actions = notes.get("actions", [])
                if len(items) == len(expected_actions) and len(items) > 0:
                    matched = []
                    for act in expected_actions:
                        owner = (act.get("owner") or "").strip()
                        due = (act.get("due") or "").strip()
                        found = False
                        for it in items:
                            if ("Owner" in it and "Due" in it and (owner in it) and (due in it)):
                                found = True
                                break
                        matched.append(found)
                    if all(matched):
                        action_ok = True
            scores["post_action_items_included"] = 1.0 if action_ok else 0.0
            # Next Meeting
            next_section = _extract_section(body, "Next Meeting")
            next_ok = False
            if next_section is not None:
                if ("Sep 28, 2024" in next_section) and ("9:00 AM" in next_section):
                    next_ok = True
            scores["post_next_meeting_present"] = 1.0 if next_ok else 0.0

    # Email checks
    email_text = _read_text(email_path)
    if email_text is not None:
        lines = [ln.rstrip("\r") for ln in email_text.splitlines()]
        if lines:
            expected_subject = "Subject: Recap: Co-op Planning Meeting (Sept 14, 2024)"
            if lines[0].strip() == expected_subject:
                scores["email_file_exists_and_subject"] = 1.0
        bullet_lines = [ln for ln in lines if re.match(r"^\s*-\s+", ln)]
        full_recap_ok = False
        if bullet_lines and absolute_url:
            last_bullet = bullet_lines[-1].strip()
            if last_bullet == f"- Full recap: {absolute_url}":
                full_recap_ok = True
        scores["email_full_recap_link"] = 1.0 if full_recap_ok else 0.0
        expected_actions = notes.get("actions", [])
        action_bullets = bullet_lines[:-1] if bullet_lines else []
        action_match_ok = False
        if expected_actions and (len(action_bullets) == len(expected_actions)):
            per_item_ok = True
            for act in expected_actions:
                owner = (act.get("owner") or "").strip()
                due = (act.get("due") or "").strip()
                found = False
                for b in action_bullets:
                    btxt = b.strip()
                    if ("Owner" in btxt and "Due" in btxt and (owner in btxt) and (due in btxt)):
                        found = True
                        break
                if not found:
                    per_item_ok = False
                    break
            if per_item_ok:
                action_match_ok = True
        scores["email_action_items_match"] = 1.0 if action_match_ok else 0.0

    # Notes publishing section and preservation
    notes_publishing_ok = False
    notes_original_preserved_ok = False
    if notes_text:
        # Trim trailing empty lines
        lines = [ln.rstrip("\r") for ln in notes_text.splitlines()]
        while lines and not lines[-1].strip():
            lines.pop()
        if len(lines) >= 2 and absolute_url:
            last_line = lines[-1].strip()
            second_last = lines[-2].strip()
            is_heading = bool(re.match(r"^\s*#{1,6}\s*Publishing\s*$", second_last)) or (second_last == "Publishing")
            if is_heading and last_line == f"Cleaned summary posted: {absolute_url}":
                notes_publishing_ok = True
                # Only credit preservation if publishing section exists
                expected_prefix = EXPECTED_ORIGINAL_NOTES
                if notes_text.startswith(expected_prefix) or notes_text.startswith(expected_prefix + "\n"):
                    notes_original_preserved_ok = True
    scores["notes_publishing_appended"] = 1.0 if notes_publishing_ok else 0.0
    scores["notes_original_preserved"] = 1.0 if notes_publishing_ok and notes_original_preserved_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()