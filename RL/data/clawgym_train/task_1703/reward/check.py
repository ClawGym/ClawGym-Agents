import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime, date, timedelta


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_with_header(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, []
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, []


def _parse_timeline_yaml(path: Path):
    """
    Minimal deterministic parser for the provided YAML structure.
    Returns a dict with keys:
      - campaign_start (date)
      - campaign_end (date)
      - channels (list[str])
      - posting_cadence (dict[str,int])
      - preferred_days (list[str])
      - internal_approval_lead_time_days (int)
    Returns None on failure.
    """
    text = _read_text_safe(path)
    if not text:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    result = {
        "campaign_start": None,
        "campaign_end": None,
        "channels": [],
        "posting_cadence": {},
        "preferred_days": [],
        "internal_approval_lead_time_days": None,
    }
    i = 0
    n = len(lines)
    try:
        while i < n:
            line = lines[i].strip()
            if not line or line.startswith("#"):
                i += 1
                continue
            if re.match(r"^campaign_start\s*:", line):
                val = line.split(":", 1)[1].strip()
                result["campaign_start"] = datetime.strptime(val, "%Y-%m-%d").date()
            elif re.match(r"^campaign_end\s*:", line):
                val = line.split(":", 1)[1].strip()
                result["campaign_end"] = datetime.strptime(val, "%Y-%m-%d").date()
            elif re.match(r"^internal_approval_lead_time_days\s*:", line):
                val = line.split(":", 1)[1].strip()
                result["internal_approval_lead_time_days"] = int(val)
            elif re.match(r"^channels\s*:", line):
                i += 1
                while i < n and lines[i].lstrip().startswith("- "):
                    item = lines[i].strip()[2:].strip()
                    if item:
                        result["channels"].append(item)
                    i += 1
                continue
            elif re.match(r"^preferred_days\s*:", line):
                i += 1
                while i < n and lines[i].lstrip().startswith("- "):
                    item = lines[i].strip()[2:].strip()
                    if item:
                        result["preferred_days"].append(item)
                    i += 1
                continue
            elif re.match(r"^posting_cadence\s*:", line):
                i += 1
                while i < n:
                    raw = lines[i]
                    if not raw.startswith("  ") or ":" not in raw:
                        break
                    kv = raw.strip().split(":", 1)
                    key = kv[0].strip()
                    val = kv[1].strip()
                    if key and val:
                        result["posting_cadence"][key] = int(val)
                    i += 1
                continue
            i += 1
    except Exception:
        return None
    if (
        result["campaign_start"] is None
        or result["campaign_end"] is None
        or not result["channels"]
        or not result["posting_cadence"]
        or not result["preferred_days"]
        or result["internal_approval_lead_time_days"] is None
    ):
        return None
    return result


def _parse_iso_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _weekday_name_to_int(name: str):
    mapping = {
        "Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6,
        "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6,
    }
    return mapping.get(name, None)


def _normalize_names_list(s: str):
    parts = re.split(r"[;,]", s)
    clean = [p.strip() for p in parts if p.strip()]
    return clean


def _find_heading_positions(text: str):
    lines = text.splitlines()
    positions = []
    for idx, ln in enumerate(lines):
        m = re.match(r"^\s*#{1,6}\s+(.*?)\s*$", ln)
        if m:
            title = m.group(1).strip()
            positions.append((idx, title))
    return positions, lines


def _get_section_text(text: str, heading_title: str):
    positions, lines = _find_heading_positions(text)
    target_idx = None
    for idx, title in positions:
        if title.lower() == heading_title.lower():
            target_idx = idx
            break
    if target_idx is None:
        return ""
    next_idx = None
    for idx, title in positions:
        if idx > target_idx:
            next_idx = idx
            break
    start = target_idx + 1
    end = next_idx if next_idx is not None else len(lines)
    return "\n".join(lines[start:end]).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "content_calendar_exists_and_columns": 0.0,
        "content_calendar_dates_within_window": 0.0,
        "content_calendar_channels_valid": 0.0,
        "content_calendar_no_duplicate_date_channel": 0.0,
        "content_calendar_item_ids_and_categories_valid": 0.0,
        "content_calendar_category_coverage": 0.0,
        "content_calendar_approval_rules_correct": 0.0,
        "content_calendar_weekly_cadence_preferred_days": 0.0,
        "strategy_report_sections_present": 0.0,
        "strategy_report_thematic_pillars_alignment": 0.0,
        "strategy_report_posting_cadence_summary_consistent": 0.0,
        "strategy_report_first_week_snapshot_matches": 0.0,
        "strategy_report_risk_sensitivity_mentions": 0.0,
        "strategy_report_status_update_covers_approvals_next_steps": 0.0,
        "emails_presence_and_naming": 0.0,
        "emails_subject_and_greeting": 0.0,
        "emails_bulleted_first_week_matches": 0.0,
        "emails_due_date_request_present": 0.0,
    }

    # Load inputs
    brief_path = workspace / "input" / "campaign_brief.md"
    notes_path = workspace / "input" / "bilateral_notes.json"
    stakeholders_path = workspace / "input" / "stakeholders.csv"
    timeline_path = workspace / "input" / "timeline.yaml"

    brief_text = _read_text_safe(brief_path)
    notes = _load_json_safe(notes_path)
    header_stake, rows_stake = _load_csv_with_header(stakeholders_path)
    timeline = _parse_timeline_yaml(timeline_path)

    # Derived input data
    items_by_id = {}
    categories_set = set()
    sensitivity_by_id = {}
    title_by_id = {}
    cat_by_id = {}
    if notes and isinstance(notes, dict) and "items" in notes and isinstance(notes["items"], list):
        for it in notes["items"]:
            iid = it.get("id")
            cat = it.get("category")
            title = it.get("title")
            sens = it.get("sensitivity_level")
            if iid and cat:
                items_by_id[iid] = it
                categories_set.add(cat)
                sensitivity_by_id[iid] = sens
                title_by_id[iid] = title if title else ""
                cat_by_id[iid] = cat

    # Load content calendar
    cal_path = workspace / "output" / "content_calendar.csv"
    cal_header, cal_rows = _load_csv_with_header(cal_path)
    required_cols = [
        "date", "channel", "theme_category", "item_id", "post_idea_title",
        "hook", "cultural_sensitivity_notes", "approval_required_from"
    ]
    cal_valid_structure = False
    if cal_header == required_cols:
        cal_valid_structure = True
        scores["content_calendar_exists_and_columns"] = 1.0

    # Prepare timeline constraints
    campaign_start = None
    campaign_end = None
    channels = []
    posting_cadence = {}
    preferred_days = []
    preferred_day_ints = set()
    internal_approval_lead_time_days = None
    if timeline:
        campaign_start = timeline["campaign_start"]
        campaign_end = timeline["campaign_end"]
        channels = timeline["channels"]
        posting_cadence = timeline["posting_cadence"]
        preferred_days = timeline["preferred_days"]
        internal_approval_lead_time_days = timeline["internal_approval_lead_time_days"]
        for d in preferred_days:
            di = _weekday_name_to_int(d)
            if di is not None:
                preferred_day_ints.add(di)

    # Extract calendar rows into structured list
    parsed_rows = []
    date_channel_pairs = set()
    duplicates_found = False
    dates_within_window = True
    channels_valid = True
    items_valid = True
    categories_match = True
    approvals_ok = True

    # Gate conditions
    if cal_valid_structure and campaign_start and campaign_end:
        for r in cal_rows:
            if len(r) != len(required_cols):
                dates_within_window = False
                channels_valid = False
                items_valid = False
                categories_match = False
                approvals_ok = False
                continue
            d_s, ch_s, cat_s, iid_s, title_s, hook_s, sens_notes_s, appr_s = r
            d = _parse_iso_date(d_s)
            if d is None:
                dates_within_window = False
            else:
                if not (campaign_start <= d <= campaign_end):
                    dates_within_window = False
            if channels and ch_s not in channels:
                channels_valid = False
            key = (d_s, ch_s)
            if key in date_channel_pairs:
                duplicates_found = True
            else:
                date_channel_pairs.add(key)
            if not items_by_id or iid_s not in items_by_id:
                items_valid = False
            else:
                expected_cat = cat_by_id.get(iid_s)
                if expected_cat != cat_s:
                    categories_match = False
            sens_level = sensitivity_by_id.get(iid_s)
            approvers = [a.strip() for a in _normalize_names_list(appr_s)]
            approver_set = set(approvers)
            if sens_level == "high":
                if approver_set != {"Marketing Lead", "Cultural Attaché"}:
                    approvals_ok = False
            else:
                if approver_set != {"Marketing Lead"}:
                    approvals_ok = False
            parsed_rows.append({
                "date": d,
                "date_str": d_s,
                "channel": ch_s,
                "category": cat_s,
                "item_id": iid_s,
                "title": title_s,
                "hook": hook_s,
                "sens_notes": sens_notes_s,
                "approvers": approver_set,
                "sens_level": sens_level,
            })

        if dates_within_window:
            scores["content_calendar_dates_within_window"] = 1.0
        if channels_valid:
            scores["content_calendar_channels_valid"] = 1.0
        if not duplicates_found:
            scores["content_calendar_no_duplicate_date_channel"] = 1.0
        if items_valid and categories_match:
            scores["content_calendar_item_ids_and_categories_valid"] = 1.0
        if categories_set:
            covered = set()
            for pr in parsed_rows:
                covered.add(pr["category"])
            if categories_set.issubset(covered):
                scores["content_calendar_category_coverage"] = 1.0
        if approvals_ok:
            scores["content_calendar_approval_rules_correct"] = 1.0

        # Weekly cadence and preferred days check
        weekly_ok = True
        preferred_day_usage_ok = True
        if channels and posting_cadence and preferred_day_ints:
            weeks = {}
            for d in _daterange(campaign_start, campaign_end):
                week_start = d - timedelta(days=d.weekday())
                weeks.setdefault(week_start, []).append(d)

            by_channel_by_week = {}
            for pr in parsed_rows:
                if pr["date"] is None:
                    continue
                d = pr["date"]
                ws = d - timedelta(days=d.weekday())
                key = (pr["channel"], ws)
                by_channel_by_week.setdefault(key, []).append(pr)

            for ws, dates_in_week in weeks.items():
                week_dates_set = set(dates_in_week)
                available_pref_days = set([d for d in week_dates_set if d.weekday() in preferred_day_ints])
                for ch in channels:
                    cadence = posting_cadence.get(ch, 0)
                    posts = by_channel_by_week.get((ch, ws), [])
                    if len(posts) != cadence:
                        weekly_ok = False
                    posts_on_pref = [p for p in posts if p["date"] in available_pref_days]
                    needed_on_pref = min(cadence, len(available_pref_days))
                    if len(posts_on_pref) < needed_on_pref:
                        preferred_day_usage_ok = False
                    if len(available_pref_days) >= cadence:
                        if len(posts_on_pref) != len(posts):
                            preferred_day_usage_ok = False
        else:
            weekly_ok = False
            preferred_day_usage_ok = False

        if weekly_ok and preferred_day_usage_ok:
            scores["content_calendar_weekly_cadence_preferred_days"] = 1.0

    # Strategy report checks
    report_path = workspace / "output" / "strategy_report.md"
    report_text = _read_text_safe(report_path)
    if report_text:
        # Sections presence
        required_sections = [
            "Audience & Objectives",
            "Thematic Pillars",
            "Posting Cadence Summary",
            "Risk & Sensitivity",
            "First Week Content Snapshot",
            "Status Update",
        ]
        have_all_sections = True
        for sec in required_sections:
            sec_text = _get_section_text(report_text, sec)
            if not sec_text:
                have_all_sections = False
                break
        if have_all_sections:
            scores["strategy_report_sections_present"] = 1.0

        # Thematic Pillars alignment
        pillars_text = _get_section_text(report_text, "Thematic Pillars")
        pillars_ok = False
        if pillars_text and categories_set and parsed_rows:
            cats_ok = all((cat in pillars_text) for cat in categories_set)
            used_by_cat = {}
            for pr in parsed_rows:
                used_by_cat.setdefault(pr["category"], set()).add(pr["item_id"])
            items_ok = True
            for cat in categories_set:
                used_items = used_by_cat.get(cat, set())
                if not used_items:
                    items_ok = False
                    break
                found_any = False
                for iid in used_items:
                    title = title_by_id.get(iid, "")
                    if iid in pillars_text or (title and title in pillars_text):
                        found_any = True
                        break
                if not found_any:
                    items_ok = False
                    break
            pillars_ok = cats_ok and items_ok
        if pillars_ok:
            scores["strategy_report_thematic_pillars_alignment"] = 1.0

        # Posting Cadence Summary consistency
        pcs_text = _get_section_text(report_text, "Posting Cadence Summary")
        pcs_ok = False
        if pcs_text and timeline and cal_valid_structure:
            total_posts = len(parsed_rows)
            channels_present = all(ch in pcs_text for ch in channels) if channels else False
            pref_days_present = all(d in pcs_text for d in preferred_days) if preferred_days else False
            cadence_terms_present = "per week" in pcs_text.lower()
            total_present = str(total_posts) in pcs_text
            pcs_ok = channels_present and pref_days_present and cadence_terms_present and total_present
        if pcs_ok:
            scores["strategy_report_posting_cadence_summary_consistent"] = 1.0

        # First Week Content Snapshot matches
        fw_text = _get_section_text(report_text, "First Week Content Snapshot")
        fw_ok = False
        if fw_text and campaign_start and parsed_rows:
            fw_start = campaign_start
            fw_end = campaign_start + timedelta(days=6)
            fw_posts = [pr for pr in parsed_rows if pr["date"] and fw_start <= pr["date"] <= fw_end]
            lines = fw_text.splitlines()
            all_match = True
            for pr in fw_posts:
                found_line = False
                for ln in lines:
                    if pr["date_str"] in ln and pr["item_id"] in ln and pr["channel"] in ln:
                        found_line = True
                        break
                if not found_line:
                    all_match = False
                    break
            fw_ok = all_match and (len(fw_posts) > 0)
        if fw_ok:
            scores["strategy_report_first_week_snapshot_matches"] = 1.0

        # Risk & Sensitivity mentions
        rs_text = _get_section_text(report_text, "Risk & Sensitivity")
        rs_ok = False
        if rs_text and notes:
            high_ids = [iid for iid, sens in sensitivity_by_id.items() if sens == "high"]
            high_mentioned = any(iid in rs_text or (title_by_id.get(iid, "") and title_by_id[iid] in rs_text) for iid in high_ids)
            attach_mentioned = "Cultural Attaché" in rs_text
            rs_ok = high_mentioned and attach_mentioned
        if rs_ok:
            scores["strategy_report_risk_sensitivity_mentions"] = 1.0

        # Status Update covers approvals and next steps
        su_text = _get_section_text(report_text, "Status Update")
        su_ok = False
        if su_text:
            has_approval = "approval" in su_text.lower()
            has_next = "next" in su_text.lower()
            su_ok = has_approval and has_next
        if su_ok:
            scores["strategy_report_status_update_covers_approvals_next_steps"] = 1.0

    # Emails checks
    emails_dir = workspace / "output" / "emails"
    expected_emails = []
    stakeholders_ok = False
    if header_stake and rows_stake:
        try:
            idx_name = header_stake.index("name")
            idx_role = header_stake.index("role")
            idx_approval = header_stake.index("approval_required")
            stakeholders_ok = True
            for r in rows_stake:
                if len(r) < len(header_stake):
                    continue
                name = r[idx_name].strip()
                role = r[idx_role].strip()
                approval_required = r[idx_approval].strip().lower()
                if approval_required == "yes":
                    role_fname = role.replace(" ", "_")
                    name_fname = name.replace(" ", "_")
                    expected_emails.append(f"{role_fname}_{name_fname}.txt")
        except Exception:
            stakeholders_ok = False

    emails_present_ok = False
    subjects_and_greetings_ok = False
    bullets_match_ok = False
    due_date_ok = False

    if emails_dir.exists() and stakeholders_ok and campaign_start and internal_approval_lead_time_days is not None:
        actual_txt_files = sorted([p.name for p in emails_dir.glob("*.txt")])
        if sorted(expected_emails) == actual_txt_files and len(actual_txt_files) == len(expected_emails):
            emails_present_ok = True

        fw_start = campaign_start
        fw_end = campaign_start + timedelta(days=6)
        fw_posts = []
        if parsed_rows:
            fw_posts = [pr for pr in parsed_rows if pr["date"] and fw_start <= pr["date"] <= fw_end]

        due_date = (campaign_start - timedelta(days=internal_approval_lead_time_days)).strftime("%Y-%m-%d")

        subj_greet_all = True
        bullets_all = True
        due_all = True
        for fname in expected_emails:
            p = emails_dir / fname
            text = _read_text_safe(p)
            if not text:
                subj_greet_all = False
                bullets_all = False
                due_all = False
                continue
            has_subject = any(re.match(r"^\s*subject\s*:", ln, flags=re.IGNORECASE) for ln in text.splitlines())
            has_greeting = any(
                re.search(r"\b(Dear|Hi|Halo|Hai|Yth\.)\b", ln, flags=re.IGNORECASE)
                for ln in text.splitlines()
            )
            if not (has_subject and has_greeting):
                subj_greet_all = False
            bullet_lines = [ln for ln in text.splitlines() if re.match(r"^\s*[-*]\s+", ln)]
            for pr in fw_posts:
                found = False
                for ln in bullet_lines:
                    if (pr["date_str"] in ln) and (pr["item_id"] in ln) and (pr["title"] in ln) and (pr["channel"] in ln):
                        found = True
                        break
                if not found:
                    bullets_all = False
                    break
            if due_date not in text:
                due_all = False

        if subj_greet_all:
            subjects_and_greetings_ok = True
        if bullets_all and fw_posts:
            bullets_match_ok = True
        if due_all:
            due_date_ok = True

    if emails_present_ok:
        scores["emails_presence_and_naming"] = 1.0
    if subjects_and_greetings_ok:
        scores["emails_subject_and_greeting"] = 1.0
    if bullets_match_ok:
        scores["emails_bulleted_first_week_matches"] = 1.0
    if due_date_ok:
        scores["emails_due_date_request_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()