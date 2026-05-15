import json
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        text = safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def parse_simple_yaml_profile(text: str) -> dict:
    """
    Minimal YAML parser for the given simple structure.
    Supports:
      - top-level scalar keys (quoted or unquoted strings)
      - a simple list for states_of_interest using "- item" lines
    """
    data = {}
    lines = text.splitlines()
    i = 0
    current_key = None
    while i < len(lines):
        line = lines[i].rstrip()
        if not line or line.strip().startswith("#"):
            i += 1
            continue
        if ":" in line and not line.startswith("  -"):
            # new key
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if key == "states_of_interest":
                # Start of list
                items = []
                # If inline value exists (not expected here), ignore
                j = i + 1
                while j < len(lines):
                    nxt = lines[j].rstrip()
                    if nxt.strip().startswith("#"):
                        j += 1
                        continue
                    if nxt.startswith("  -"):
                        item = nxt[3:].strip()
                        # strip quotes if present
                        if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                            item = item[1:-1]
                        items.append(item)
                        j += 1
                    else:
                        break
                data[key] = items
                i = j
                current_key = None
                continue
            else:
                # scalar
                sval = val
                sval = sval.strip()
                if sval == "":
                    # look ahead for indented continuation (not expected)
                    sval = ""
                # strip quotes
                if (sval.startswith('"') and sval.endswith('"')) or (sval.startswith("'") and sval.endswith("'")):
                    sval = sval[1:-1]
                data[key] = sval
                current_key = key
                i += 1
                continue
        else:
            i += 1
            continue
    return data


def parse_markdown_sections(text: str) -> dict:
    """
    Parse markdown text into sections keyed by '## {heading}' titles.
    Returns dict: {heading_text: [content_lines]}
    """
    lines = text.splitlines()
    sections = {}
    current = None
    for line in lines:
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        else:
            if current is not None:
                sections[current].append(line.rstrip())
    return sections


def extract_percent_from_text(text: str):
    """
    Extract first percentage number from text like '8%'.
    Returns float or None.
    """
    m = re.search(r'(\d+(?:\.\d+)?)\s*%', text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def expected_state_doc_filename(state: str) -> str:
    return f"{state}_compliance.md"


def compute_expected_from_doc(doc_path: Path) -> dict:
    text = safe_read_text(doc_path)
    if text is None:
        return None
    sections = parse_markdown_sections(text)
    expected = {}
    # FIRB
    firb_lines = sections.get("FIRB Approval", [])
    firb_text = " ".join([l.strip() for l in firb_lines if l.strip()])
    firb_required = None
    if firb_text:
        if "required" in firb_text.lower():
            firb_required = True
        elif "not required" in firb_text.lower():
            firb_required = False
    expected["firb_required"] = firb_required
    # Foreign Buyer Surcharges (Rates)
    fbs_lines = sections.get("Foreign Buyer Surcharges (Rates)", [])
    fbs_text = " ".join([l.strip() for l in fbs_lines if l.strip()])
    stamp_rate = extract_percent_from_text(fbs_text) if fbs_text else None
    expected["stamp_duty_surcharge_rate"] = stamp_rate
    # Land Tax Surcharge (Rates)
    lts_lines = sections.get("Land Tax Surcharge (Rates)", [])
    lts_text = " ".join([l.strip() for l in lts_lines if l.strip()])
    land_rate = extract_percent_from_text(lts_text) if lts_text else None
    expected["land_tax_surcharge_rate"] = land_rate
    # Prohibited Property Types
    ppt_lines = sections.get("Prohibited Property Types", [])
    ppt = []
    for l in ppt_lines:
        s = l.strip()
        if s.startswith("- "):
            ppt.append(s[2:].strip())
    expected["prohibited_property_types"] = ppt if ppt else None
    # Penalties
    pen_lines = sections.get("Penalties for Non-Compliance", [])
    pen_texts = []
    for l in pen_lines:
        s = l.strip()
        if s.startswith("- "):
            s = s[2:].strip()
        if s:
            pen_texts.append(s)
    penalties_summary = " ".join(pen_texts).strip() if pen_texts else None
    expected["penalties_summary"] = penalties_summary
    # Required citation sections for grading
    expected["required_sections"] = [
        "FIRB Approval",
        "Foreign Buyer Surcharges (Rates)",
        "Land Tax Surcharge (Rates)",
        "Prohibited Property Types",
        "Penalties for Non-Compliance",
    ]
    return expected


def find_section_range(lines, heading_name: str):
    """
    Find section boundaries for a given heading name appearing as:
      - exact line 'Heading Name:' (case-sensitive)
      - or markdown '#/## Heading Name' (any number of #)
    Returns (start_idx, end_idx) of content lines after the heading line and before next heading, or (None, None) if not found.
    """
    # Identify heading lines
    indices = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("#"):
            # markdown heading
            title = stripped.lstrip("#").strip()
            if title == heading_name or title == f"{heading_name}:":
                indices.append(idx)
        else:
            # plain with colon
            if stripped == f"{heading_name}:" or stripped == heading_name:
                indices.append(idx)
    if not indices:
        return (None, None)
    start_idx = indices[0] + 1
    # Find end_idx
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        s = lines[j].strip()
        if not s:
            # allow blank lines inside section
            pass
        if s.startswith("#"):
            end_idx = j
            break
        if s.endswith(":") and not s.startswith("- "):
            # treat another plain-colon heading as next section
            end_idx = j
            break
    return (start_idx, end_idx)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_states_of_interest_updated": 0.0,
        "config_investor_residency_updated": 0.0,
        "compliance_json_exists": 0.0,
        "compliance_json_states_match_config": 0.0,
        "compliance_json_values_nsw": 0.0,
        "compliance_json_citations_nsw": 0.0,
        "compliance_json_values_vic": 0.0,
        "compliance_json_citations_vic": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_title_correct": 0.0,
        "meeting_profile_summary_uses_config": 0.0,
        "meeting_key_requirements_by_state": 0.0,
        "meeting_open_questions_includes_date_conditions": 0.0,
        "meeting_action_items_requirements": 0.0,
        "no_qld_in_outputs": 0.0,
    }

    # Load and parse config
    config_path = workspace / "config" / "investor_profile.yaml"
    config_text = safe_read_text(config_path)
    profile = {}
    if config_text is not None:
        profile = parse_simple_yaml_profile(config_text)
    states_of_interest = profile.get("states_of_interest")
    investor_residency = profile.get("investor_residency")
    entity_type = profile.get("entity_type")
    property_type = profile.get("property_type")
    target_contract_date = profile.get("target_contract_date")
    meeting_date_str = profile.get("meeting_date")

    # Check config states updated
    if isinstance(states_of_interest, list) and states_of_interest == ["NSW", "VIC"]:
        scores["config_states_of_interest_updated"] = 1.0
    else:
        scores["config_states_of_interest_updated"] = 0.0

    # Check config residency updated
    if isinstance(investor_residency, str) and investor_residency == "non-resident":
        scores["config_investor_residency_updated"] = 1.0
    else:
        scores["config_investor_residency_updated"] = 0.0

    # Expected values from docs for NSW and VIC
    expected_by_state = {}
    for st in ["NSW", "VIC"]:
        doc_file = workspace / "docs" / expected_state_doc_filename(st)
        expected_by_state[st] = compute_expected_from_doc(doc_file)

    # Load output compliance checklist
    checklist_path = workspace / "output" / "compliance_checklist.json"
    checklist = safe_load_json(checklist_path)
    if isinstance(checklist, list):
        scores["compliance_json_exists"] = 1.0
    else:
        scores["compliance_json_exists"] = 0.0

    # Validate compliance JSON state coverage and values
    json_states_ok = False
    values_ok = {"NSW": False, "VIC": False}
    citations_ok = {"NSW": False, "VIC": False}
    no_qld_in_json = True

    if isinstance(checklist, list) and isinstance(states_of_interest, list):
        # Extract states from JSON
        json_states = []
        objs_by_state = {}
        for obj in checklist:
            if isinstance(obj, dict) and "state" in obj:
                st = obj.get("state")
                if isinstance(st, str):
                    json_states.append(st)
                    objs_by_state[st] = obj
        # Ensure only and all configured states appear
        json_state_set = set(json_states)
        config_state_set = set(states_of_interest) if isinstance(states_of_interest, list) else set()
        if json_state_set == config_state_set and json_state_set == {"NSW", "VIC"}:
            json_states_ok = True

        # No QLD content check in JSON text
        json_text = safe_read_text(checklist_path) or ""
        if "QLD" in json_text:
            no_qld_in_json = False

        # Validate for each state
        for st in ["NSW", "VIC"]:
            obj = objs_by_state.get(st)
            exp = expected_by_state.get(st)
            if not obj or not isinstance(obj, dict) or not exp:
                continue
            try:
                firb_required = obj.get("firb_required", None)
                prohibited = obj.get("prohibited_property_types", None)
                stamp = obj.get("stamp_duty_surcharge_rate", None)
                land = obj.get("land_tax_surcharge_rate", None)
                penalties = obj.get("penalties_summary", None)
                citations = obj.get("citations", None)

                # Types and values
                firb_ok = isinstance(firb_required, bool) and firb_required is True and exp.get("firb_required") is True
                prohibited_ok = isinstance(prohibited, list) and exp.get("prohibited_property_types") == prohibited
                # Accept int/float equality
                def num_equal(a, b):
                    try:
                        if a is None or b is None:
                            return False
                        return float(a) == float(b)
                    except Exception:
                        return False

                stamp_ok = num_equal(stamp, exp.get("stamp_duty_surcharge_rate"))
                land_ok = num_equal(land, exp.get("land_tax_surcharge_rate"))
                penalties_ok = isinstance(penalties, str) and penalties.strip() == (exp.get("penalties_summary") or "").strip()

                if firb_ok and prohibited_ok and stamp_ok and land_ok and penalties_ok:
                    values_ok[st] = True

                # Citations check
                c_ok = False
                if isinstance(citations, list):
                    # Each citation must have file and section
                    all_format_ok = True
                    for c in citations:
                        if not isinstance(c, dict) or "file" not in c or "section" not in c:
                            all_format_ok = False
                            break
                        if not isinstance(c.get("file"), str) or not isinstance(c.get("section"), str):
                            all_format_ok = False
                            break
                    if all_format_ok:
                        # Coverage of required sections
                        sections_in_json = {(c["file"], c["section"]) for c in citations if isinstance(c, dict)}
                        required_sections = exp.get("required_sections", [])
                        required = {(expected_state_doc_filename(st), sec) for sec in required_sections}
                        # Ensure all required are present
                        if required.issubset(sections_in_json):
                            c_ok = True
                citations_ok[st] = c_ok

            except Exception:
                pass

    scores["compliance_json_states_match_config"] = 1.0 if json_states_ok else 0.0
    scores["compliance_json_values_nsw"] = 1.0 if values_ok["NSW"] else 0.0
    scores["compliance_json_citations_nsw"] = 1.0 if citations_ok["NSW"] else 0.0
    scores["compliance_json_values_vic"] = 1.0 if values_ok["VIC"] else 0.0
    scores["compliance_json_citations_vic"] = 1.0 if citations_ok["VIC"] else 0.0

    # Meeting notes checks
    notes_path = workspace / "output" / "meeting_notes.md"
    notes_text = safe_read_text(notes_path)
    if notes_text is not None:
        scores["meeting_notes_exists"] = 1.0
    else:
        scores["meeting_notes_exists"] = 0.0

    if notes_text is not None:
        lines = notes_text.splitlines()
        # Title check
        title_line = ""
        if lines:
            title_line = lines[0].strip()
        expected_title = "Compliance Review: NSW & VIC (Non-Resident Buyer)"
        scores["meeting_title_correct"] = 1.0 if title_line == expected_title else 0.0

        # Profile Summary check: contains values from config
        ps_start, ps_end = find_section_range(lines, "Profile Summary")
        profile_ok = False
        if ps_start is not None and ps_end is not None:
            ps_text = "\n".join(lines[ps_start:ps_end])
            conds = []
            # All the required values must be present in the section
            # Use safe fallbacks to prevent crashes
            conds.append(isinstance(investor_residency, str) and investor_residency in ps_text)
            conds.append(isinstance(entity_type, str) and entity_type in ps_text)
            conds.append(isinstance(property_type, str) and property_type in ps_text)
            conds.append(isinstance(target_contract_date, str) and target_contract_date in ps_text)
            # states_of_interest: ensure both states mentioned
            soi_ok = False
            if isinstance(states_of_interest, list):
                soi_ok = all(isinstance(s, str) and s in ps_text for s in states_of_interest)
            conds.append(soi_ok)
            profile_ok = all(conds)
        scores["meeting_profile_summary_uses_config"] = 1.0 if profile_ok else 0.0

        # Key Compliance Requirements by State: ensure summaries per state
        kcrs_start, kcrs_end = find_section_range(lines, "Key Compliance Requirements by State")
        kcrs_ok = False
        if kcrs_start is not None and kcrs_end is not None:
            kcrs_text = "\n".join(lines[kcrs_start:kcrs_end])
            # NSW checks
            nsw_ok = ("NSW" in kcrs_text and
                      ("FIRB" in kcrs_text or "FIRB approval" in kcrs_text) and
                      ("8%" in kcrs_text) and
                      ("2%" in kcrs_text) and
                      ("Established" in kcrs_text))
            # VIC checks
            vic_ok = ("VIC" in kcrs_text and
                      ("FIRB" in kcrs_text or "FIRB approval" in kcrs_text) and
                      ("8%" in kcrs_text) and
                      ("4%" in kcrs_text) and
                      ("Established" in kcrs_text))
            kcrs_ok = nsw_ok and vic_ok
        scores["meeting_key_requirements_by_state"] = 1.0 if kcrs_ok else 0.0

        # Open Questions: date-based conditions
        oq_start, oq_end = find_section_range(lines, "Open Questions")
        oq_ok = False
        if oq_start is not None and oq_end is not None:
            oq_lines = [l.strip() for l in lines[oq_start:oq_end] if l.strip()]
            # Must have at least two question-like items
            question_like = [l for l in oq_lines if l.endswith("?")]
            has_two = len(question_like) >= 2
            text_all = " ".join(oq_lines).lower()
            # NSW: look for contract date applicability or specific date
            nsw_cond = ("nsw" in text_all and ("contract" in text_all or "rate" in text_all or "confirm" in text_all)) or ("2024-06-30" in text_all)
            # VIC: concessions/contract date change
            vic_cond = ("vic" in text_all and ("contract" in text_all or "concession" in text_all or "rate" in text_all or "confirm" in text_all)) or ("2024-07-01" in text_all)
            oq_ok = has_two and nsw_cond and vic_cond
        scores["meeting_open_questions_includes_date_conditions"] = 1.0 if oq_ok else 0.0

        # Action Items: at least 4, split between Me and Conveyancer, due date = meeting_date - 2 days
        ai_start, ai_end = find_section_range(lines, "Action Items")
        ai_ok = False
        if ai_start is not None and ai_end is not None:
            ai_lines = [l.strip() for l in lines[ai_start:ai_end] if l.strip()]
            # Compute due date
            due_date_str = None
            try:
                if isinstance(meeting_date_str, str):
                    md = datetime.strptime(meeting_date_str, "%Y-%m-%d").date()
                    due_date = md - timedelta(days=2)
                    due_date_str = due_date.isoformat()
            except Exception:
                due_date_str = None
            # Count items - lines starting with '-' or '*' or containing 'Due:' or due date
            items = [l for l in ai_lines if l.startswith("- ") or l.startswith("* ") or (due_date_str and due_date_str in l)]
            enough_items = len(items) >= 4
            # Presence of due date in each item is strict; we'll require due date string appears at least 4 times
            due_dates_count = 0
            if due_date_str:
                due_dates_count = sum(1 for l in ai_lines if due_date_str in l)
            due_dates_ok = due_date_str is not None and due_dates_count >= 4
            # Split between Me and Conveyancer
            has_me = any(("Me" in l) or ("Investor" in l) for l in ai_lines)
            has_conveyancer = any(("Conveyancer" in l) for l in ai_lines)
            ai_ok = enough_items and due_dates_ok and has_me and has_conveyancer
        scores["meeting_action_items_requirements"] = 1.0 if ai_ok else 0.0

    # No QLD in outputs (both files)
    no_qld = True
    # From compliance JSON text was already checked; also meeting notes
    if notes_text is not None and "QLD" in notes_text:
        no_qld = False
    if scores["compliance_json_exists"] == 0.0:
        # If JSON missing, we can't confirm; consider as fail for this check
        no_qld = False
    else:
        # If JSON exists, we used json_text earlier
        if not no_qld_in_json:
            no_qld = False
    scores["no_qld_in_outputs"] = 1.0 if no_qld else 0.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()