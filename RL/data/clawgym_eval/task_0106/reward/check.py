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


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _find_line_starting_with(lines: List[str], prefix: str) -> Optional[str]:
    for ln in lines:
        if ln.strip().startswith(prefix):
            return ln.strip()
    return None


def _parse_agenda_md(text: str) -> Dict[str, Any]:
    # Returns parsed structure or empty structure if parsing fails
    result: Dict[str, Any] = {
        "event_title": None,
        "proposed_date": None,
        "max_minutes": None,
        "total_scheduled": None,
        "total_before": None,
        "modules": [],
        "risk_count": None,
    }
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    # Title line: "# {cfg['event_title']} - Dialogue Workshop Agenda"
    if lines:
        title_line = lines[0].strip()
        if title_line.startswith("# "):
            title = title_line[2:]
            suffix = " - Dialogue Workshop Agenda"
            if title.endswith(suffix):
                title = title[: -len(suffix)]
            result["event_title"] = title
    # Date
    date_line = _find_line_starting_with(lines, "Date:")
    if date_line:
        result["proposed_date"] = date_line.split("Date:", 1)[1].strip()
    # Max minutes
    max_line = _find_line_starting_with(lines, "Max minutes:")
    if max_line:
        mm = max_line.split("Max minutes:", 1)[1].strip()
        result["max_minutes"] = _parse_int(mm)
    # Total scheduled
    total_line = _find_line_starting_with(lines, "Total scheduled minutes:")
    if total_line:
        m = re.search(r"Total scheduled minutes:\s*(\d+)\s*\(from\s*(\d+)\s*\)", total_line)
        if m:
            result["total_scheduled"] = int(m.group(1))
            result["total_before"] = int(m.group(2))
        else:
            m2 = re.search(r"Total scheduled minutes:\s*(\d+)", total_line)
            if m2:
                result["total_scheduled"] = int(m2.group(1))
    # Modules
    modules_start = None
    for idx, ln in enumerate(lines):
        if ln.strip() == "Modules:":
            modules_start = idx + 1
            break
    modules: List[Dict[str, Any]] = []
    if modules_start is not None:
        idx = modules_start
        while idx < len(lines):
            ln = lines[idx].strip()
            if not ln:
                idx += 1
                break
            parts = [p.strip() for p in ln.split(" — ")] if " — " in ln else [p.strip() for p in ln.split(" - ")]
            if len(parts) >= 4:
                first = parts[0]
                if ". " in first:
                    title = first.split(". ", 1)[1]
                else:
                    title = first
                dur_str = parts[1]
                dm = re.search(r"(\d+)", dur_str)
                dur_val = int(dm.group(1)) if dm else None
                fac = None
                if parts[2].lower().startswith("facilitator:"):
                    fac = parts[2].split(":", 1)[1].strip()
                risk_flag = None
                for p in parts[3:]:
                    if p.lower().startswith("risk:"):
                        risk_val = p.split(":", 1)[1].strip().lower()
                        risk_flag = True if risk_val == "yes" else False if risk_val == "no" else None
                        break
                modules.append({"title": title, "duration": dur_val, "facilitator": fac, "risk_flag": risk_flag})
            idx += 1
    result["modules"] = modules
    # Risk count line
    risk_line = None
    for ln in lines[::-1]:
        if ln.strip().startswith("Risk-flagged modules:"):
            risk_line = ln.strip()
            break
    if risk_line:
        m = re.search(r"Risk-flagged modules:\s*(\d+)", risk_line)
        if m:
            result["risk_count"] = int(m.group(1))
    return result


def _scale_modules_like_script(modules: List[Dict[str, Any]], max_minutes: int) -> Tuple[List[Dict[str, Any]], int, int]:
    # Mirror scripts/build_agenda.py's scale_modules
    total_before = sum(int(m["duration"]) for m in modules)
    if total_before <= max_minutes:
        adjusted = [dict(m) for m in modules]
        return adjusted, total_before, total_before
    scale = max_minutes / float(total_before)
    adjusted: List[Dict[str, Any]] = []
    for m in modules:
        new_m = dict(m)
        new_duration = max(5, int(round(int(m["duration"]) * scale)))
        new_m["duration"] = new_duration
        adjusted.append(new_m)
    total_after = sum(m["duration"] for m in adjusted)
    adjusted.sort(key=lambda x: x["duration"], reverse=True)
    idx = 0
    while total_after > max_minutes and any(m["duration"] > 5 for m in adjusted):
        if adjusted[idx]["duration"] > 5:
            adjusted[idx]["duration"] -= 1
            total_after -= 1
        idx = (idx + 1) % len(adjusted)
    title_order = [m["title"] for m in modules]
    adjusted.sort(key=lambda m: title_order.index(m["title"]) if m["title"] in title_order else 0)
    return adjusted, total_before, total_after


def _compute_topics_from_csv(csv_path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        import csv
        totals: Dict[str, int] = {}
        top_item: Dict[str, Dict[str, Any]] = {}
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                category = row.get("category", "").strip()
                concern = row.get("concern", "").strip()
                votes = int(row.get("votes", "0"))
                totals[category] = totals.get(category, 0) + votes
                prev = top_item.get(category)
                if prev is None or votes > prev["votes"]:
                    top_item[category] = {"concern": concern, "votes": votes}
        ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        top_categories: List[Dict[str, Any]] = []
        for cat, total in ranked:
            top_categories.append({
                "category": cat,
                "total_votes": total,
                "top_concern": top_item[cat],
            })
        return top_categories
    except Exception:
        return None


def _find_section_bounds(lines: List[str], label: str) -> Optional[Tuple[int, int]]:
    # Find a section heading for 'label' (case-insensitive) and return content bounds (start_idx, end_idx)
    label_norm = re.sub(r"\s+", " ", label.strip().lower())
    heading_indices: List[int] = []
    for i, ln in enumerate(lines):
        text = ln.strip()
        low = text.lower()
        is_heading = False
        if low == label_norm or low == f"{label_norm}:":
            is_heading = True
        elif low.startswith("#") and label_norm in low:
            is_heading = True
        elif low.startswith(label_norm) and (low == label_norm or low.startswith(label_norm + ":")):
            is_heading = True
        if is_heading:
            heading_indices.append(i)
    if not heading_indices:
        return None
    start_heading = heading_indices[0]
    required_labels = [
        "Overview",
        "Agenda summary",
        "Time cap confirmation",
        "Top community concerns",
        "Action items",
        "Risk and mitigation",
    ]
    end_idx = len(lines)
    for i in range(start_heading + 1, len(lines)):
        low = lines[i].strip().lower()
        for lbl in required_labels:
            ln = lbl.lower()
            if (low == ln or low == f"{ln}:"
                or (low.startswith("#") and ln in low)
                or (low.startswith(ln) and (low == ln or low.startswith(ln + ":")))):
                end_idx = i
                return (start_heading + 1, end_idx)
    return (start_heading + 1, end_idx)


def _parse_meeting_notes_sections(text: str) -> Dict[str, str]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    sections = {
        "overview": "",
        "agenda summary": "",
        "time cap confirmation": "",
        "top community concerns": "",
        "action items": "",
        "risk and mitigation": "",
    }
    for label in list(sections.keys()):
        bounds = _find_section_bounds(lines, label)
        if bounds is not None:
            start, end = bounds
            sections[label] = "\n".join(lines[start:end]).strip()
        else:
            sections[label] = ""
    return sections


def _extract_action_items_by_team(section_text: str, teams: List[str]) -> Dict[str, List[Tuple[str, Optional[str]]]]:
    items_by_team: Dict[str, List[Tuple[str, Optional[str]]]] = {t: [] for t in teams}
    lines = [ln for ln in section_text.splitlines()]
    team_positions: Dict[str, int] = {}
    for i, ln in enumerate(lines):
        for team in teams:
            if team.lower() in ln.strip().lower():
                if team not in team_positions:
                    team_positions[team] = i
    if team_positions:
        sorted_positions = sorted([(pos, team) for team, pos in team_positions.items()])
        for idx, (pos, team) in enumerate(sorted_positions):
            start = pos + 1
            end = len(lines)
            if idx + 1 < len(sorted_positions):
                end = sorted_positions[idx + 1][0]
            for ln in lines[start:end]:
                stripped = ln.strip()
                if not stripped:
                    continue
                if re.match(r"^(\*|-|\d+\.)\s+", stripped):
                    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", stripped)
                    items_by_team[team].append((stripped, date_match.group(1) if date_match else None))
    else:
        for team in teams:
            for ln in lines:
                if team.lower() in ln.lower():
                    stripped = ln.strip()
                    if stripped:
                        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", stripped)
                        items_by_team[team].append((stripped, date_match.group(1) if date_match else None))
    return items_by_team


def _parse_date(date_str: str) -> Optional[Tuple[int, int, int]]:
    try:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", date_str)
        if not m:
            return None
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        return None


def _date_leq(a: str, b: str) -> bool:
    da = _parse_date(a)
    db = _parse_date(b)
    if not da or not db:
        return False
    return da <= db


def grade(transcript: list, workspace_path: str) -> dict:
    ws = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_max_minutes_set": 0.0,
        "outputs_exist": 0.0,
        "agenda_total_minutes_valid": 0.0,
        "agenda_matches_scaled_config": 0.0,
        "topics_json_correct": 0.0,
        "meeting_notes_sections_present": 0.0,
        "overview_content_correct": 0.0,
        "agenda_summary_consistent": 0.0,
        "time_cap_confirmation_correct": 0.0,
        "top_concerns_in_notes_correct": 0.0,
        "action_items_per_team": 0.0,
        "action_items_reference_top_concern_per_team": 0.0,
        "risk_mitigation_per_risky_module": 0.0,
    }

    # Paths
    config_path = ws / "config" / "workshop_config.json"
    concerns_csv = ws / "data" / "concerns.csv"
    agenda_path = ws / "output" / "agenda.md"
    topics_path = ws / "output" / "topics.json"
    notes_path = ws / "output" / "meeting_notes.md"

    # Load config
    cfg = _load_json(config_path)
    if cfg and isinstance(cfg, dict) and "max_minutes" in cfg:
        try:
            if int(cfg.get("max_minutes")) == 120:
                scores["config_max_minutes_set"] = 1.0
        except Exception:
            pass

    # Check outputs existence
    if agenda_path.exists() and topics_path.exists():
        scores["outputs_exist"] = 1.0

    # Parse agenda.md
    agenda_text = _read_text(agenda_path) if agenda_path.exists() else None
    agenda_parsed = _parse_agenda_md(agenda_text) if agenda_text else None
    if agenda_parsed and agenda_parsed.get("total_scheduled") is not None:
        total_after = agenda_parsed["total_scheduled"]
        if total_after <= 120:
            scores["agenda_total_minutes_valid"] = 1.0

    # Compare agenda content to scaled config
    if cfg and agenda_parsed and cfg.get("modules") and agenda_parsed.get("modules"):
        try:
            max_minutes = int(cfg.get("max_minutes"))
            modules_cfg = cfg.get("modules")
            if isinstance(modules_cfg, list) and all(isinstance(m, dict) for m in modules_cfg):
                adjusted, total_before, total_after = _scale_modules_like_script(modules_cfg, max_minutes)
                totals_match = (
                    agenda_parsed.get("total_scheduled") == total_after and
                    agenda_parsed.get("total_before") == total_before and
                    agenda_parsed.get("max_minutes") == max_minutes
                )
                modules_match = True
                if len(agenda_parsed["modules"]) != len(adjusted):
                    modules_match = False
                else:
                    for am, em in zip(agenda_parsed["modules"], adjusted):
                        if (am.get("title") != em.get("title") or
                            am.get("duration") != em.get("duration") or
                            (am.get("facilitator") or "") != (em.get("facilitator") or "")):
                            modules_match = False
                            break
                if totals_match and modules_match:
                    scores["agenda_matches_scaled_config"] = 1.0
        except Exception:
            pass

    # Validate topics.json correctness against concerns.csv
    topics_data = _load_json(topics_path) if topics_path.exists() else None
    expected_topics = _compute_topics_from_csv(concerns_csv) if concerns_csv.exists() else None
    if topics_data and expected_topics is not None:
        got_top = topics_data.get("top_categories")
        if isinstance(got_top, list) and len(got_top) == len(expected_topics):
            match = True
            for a, b in zip(got_top, expected_topics):
                if not (a.get("category") == b.get("category") and
                        a.get("total_votes") == b.get("total_votes") and
                        isinstance(a.get("top_concern"), dict) and
                        a["top_concern"].get("concern") == b["top_concern"].get("concern") and
                        a["top_concern"].get("votes") == b["top_concern"].get("votes")):
                    match = False
                    break
            if match:
                scores["topics_json_correct"] = 1.0

    # Meeting notes checks
    notes_text = _read_text(notes_path) if notes_path and notes_path.exists() else None
    sections = _parse_meeting_notes_sections(notes_text) if notes_text else None
    if sections:
        required = ["overview", "agenda summary", "time cap confirmation", "top community concerns", "action items", "risk and mitigation"]
        if all(sections.get(k, "") != "" for k in required):
            scores["meeting_notes_sections_present"] = 1.0

        # Overview contains event title and proposed date from config
        if cfg:
            ev = str(cfg.get("event_title", "") or "")
            pd = str(cfg.get("proposed_date", "") or "")
            overview_ok = (ev != "" and pd != "" and ev in sections.get("overview", "") and pd in sections.get("overview", ""))
            if overview_ok:
                scores["overview_content_correct"] = 1.0

        # Agenda summary consistent with agenda.md
        if agenda_parsed and agenda_parsed.get("modules"):
            agsum = sections.get("agenda summary", "")
            agsum_lines = agsum.splitlines()
            all_modules_present = True
            for m in agenda_parsed["modules"]:
                title = m.get("title") or ""
                fac = m.get("facilitator") or ""
                dur = m.get("duration")
                found = False
                for ln in agsum_lines:
                    if title in ln and fac in ln and (str(dur) in ln):
                        found = True
                        break
                if not found:
                    all_modules_present = False
                    break
            if all_modules_present:
                scores["agenda_summary_consistent"] = 1.0

        # Time cap confirmation
        if agenda_parsed:
            tcc = sections.get("time cap confirmation", "")
            exact_num = str(agenda_parsed.get("total_scheduled"))
            has_number = exact_num in tcc
            conf_ok = any(pat in tcc for pat in ["<= 120", "<=120", "≤ 120", "120 or less", "at or under 120"])
            if has_number and conf_ok and agenda_parsed.get("total_scheduled", 9999) <= 120:
                scores["time_cap_confirmation_correct"] = 1.0

        # Top community concerns
        if topics_data and isinstance(topics_data.get("top_categories"), list):
            tcc_section = sections.get("top community concerns", "")
            tcc_ok = True
            for obj in topics_data["top_categories"]:
                cat = obj.get("category", "")
                concern = (obj.get("top_concern") or {}).get("concern", "")
                if not (cat and concern and (cat in tcc_section) and (concern in tcc_section)):
                    tcc_ok = False
                    break
            if tcc_ok and len(topics_data["top_categories"]) == 3:
                scores["top_concerns_in_notes_correct"] = 1.0

        # Action items
        if cfg:
            teams = cfg.get("teams") or []
            if isinstance(teams, list) and teams:
                act_section = sections.get("action items", "")
                items_by_team = _extract_action_items_by_team(act_section, teams)
                pd = str(cfg.get("proposed_date", ""))
                per_team_ok = True
                ref_ok = True
                top_cats = []
                if topics_data and isinstance(topics_data.get("top_categories"), list):
                    top_cats = [obj.get("category", "") for obj in topics_data["top_categories"] if obj.get("category")]
                for team in teams:
                    items = items_by_team.get(team, [])
                    valid_items = []
                    for txt, due in items:
                        if due and _date_leq(due, pd):
                            valid_items.append((txt, due))
                    if len(valid_items) < 2:
                        per_team_ok = False
                    if top_cats:
                        if not any(any(cat in txt for cat in top_cats) for (txt, _due) in (valid_items if valid_items else items)):
                            ref_ok = False
                if per_team_ok:
                    scores["action_items_per_team"] = 1.0
                if ref_ok and top_cats:
                    scores["action_items_reference_top_concern_per_team"] = 1.0

        # Risk and mitigation
        if agenda_parsed and agenda_parsed.get("modules"):
            risky_titles = [m.get("title") for m in agenda_parsed["modules"] if m.get("risk_flag") is True]
            rm_section = sections.get("risk and mitigation", "")
            rm_lines = rm_section.splitlines()
            mitigation_keywords = ["mitigation", "mitigate", "contingency", "backup", "plan", "safety", "de-escalation", "support", "monitor", "training", "brief", "prepare", "assign", "extra"]
            all_risks_addressed = True
            for title in risky_titles:
                found = False
                for idx, ln in enumerate(rm_lines):
                    if title and title in ln:
                        window = "\n".join(rm_lines[idx: min(len(rm_lines), idx + 3)])
                        if any(kw.lower() in window.lower() for kw in mitigation_keywords):
                            found = True
                            break
                if not found:
                    all_risks_addressed = False
                    break
            if risky_titles and all_risks_addressed:
                scores["risk_mitigation_per_risky_module"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()