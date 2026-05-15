import json
import sys
import hashlib
import re
from pathlib import Path
from datetime import datetime, timedelta
import csv


def safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_read_jsonl(path: Path):
    rows = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None, False
    ok = True
    for ln in text.splitlines():
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
            rows.append(obj)
        except Exception:
            ok = False
            break
    return rows if ok else None, ok


def safe_read_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            return list(rdr)
    except Exception:
        return None


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_investment_to_int(text: str) -> int:
    if not text:
        return None
    t = text.strip().lower()
    t_clean = t.replace(",", "").replace("$", "").strip()
    m_b = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(billion|bn)\b", t_clean)
    if m_b:
        val = float(m_b.group(1)) * 1_000_000_000
        return int(round(val))
    m_m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*million\b", t_clean)
    if m_m:
        val = float(m_m.group(1)) * 1_000_000
        return int(round(val))
    digits = re.findall(r"\d+", t_clean)
    if digits:
        try:
            return int("".join(digits))
        except Exception:
            return None
    return None


def parse_percent_to_int(text: str) -> int:
    if not text:
        return None
    m = re.search(r"(\d+)\s*%", text)
    if m:
        return int(m.group(1))
    m2 = re.search(r"\b(\d+)\s*percent\b", text.lower())
    if m2:
        return int(m2.group(1))
    return None


def parse_timeline_years(text: str):
    if not text:
        return None, None
    yrs = re.findall(r"\b(20\d{2})\b", text)
    if not yrs:
        return None, None
    yrs = list(map(int, yrs))
    return (min(yrs), max(yrs))


def parse_html_press_release(path: Path):
    html = safe_read_text(path)
    if html is None:
        return None
    m_company = re.search(r'<meta\s+name=["\']company["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    m_date = re.search(r'<meta\s+name=["\']press-date["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    company = m_company.group(1).strip() if m_company else None
    press_date = m_date.group(1).strip() if m_date else None

    rows = re.findall(r"<tr>\s*<th>([^<]+)</th>\s*<td>([^<]+)</td>\s*</tr>", html, flags=re.IGNORECASE)
    table = {th.strip().lower(): td.strip() for th, td in rows}
    project_name = table.get("project")
    investment_usd = parse_investment_to_int(table.get("investment", ""))
    claimed_emissions_reduction_percent = parse_percent_to_int(table.get("claimed emissions reduction", ""))
    region = table.get("region")
    start_year, end_year = parse_timeline_years(table.get("timeline", ""))

    data = {
        "company": company,
        "press_date": press_date,
        "project_name": project_name,
        "investment_usd": investment_usd,
        "claimed_emissions_reduction_percent": claimed_emissions_reduction_percent,
        "region": region,
        "start_year": start_year,
        "end_year": end_year,
    }
    return data


def cross_validate_with_csv(project_name: str, expected: dict, csv_rows: list):
    result = {
        "reference_match": False,
        "mismatches": []
    }
    if not csv_rows or not project_name:
        return result
    match_row = None
    for row in csv_rows:
        if (row.get("project_name") or "").strip() == project_name:
            match_row = row
            break
    if not match_row:
        return result
    mismatches = []
    if (match_row.get("company") or "").strip() != (expected.get("company") or ""):
        mismatches.append("company")
    if (match_row.get("region") or "").strip() != (expected.get("region") or ""):
        mismatches.append("region")
    try:
        csv_start = int(match_row.get("start_year"))
    except Exception:
        csv_start = None
    try:
        csv_end = int(match_row.get("end_year"))
    except Exception:
        csv_end = None
    if csv_start != expected.get("start_year"):
        mismatches.append("start_year")
    if csv_end != expected.get("end_year"):
        mismatches.append("end_year")
    result["reference_match"] = (len(mismatches) == 0)
    result["mismatches"] = mismatches
    return result


def normalize_path_str(p: str) -> str:
    return p.replace("\\", "/").rstrip("/")


def endswith_path(candidate: str, required_rel: str) -> bool:
    return normalize_path_str(candidate).endswith(normalize_path_str(required_rel))


def count_sentences(text: str) -> int:
    if not text:
        return 0
    parts = re.split(r'[.!?]+', text)
    count = sum(1 for s in parts if s.strip())
    return count


def has_investment_reference(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    if re.search(r"\$?\s*2\.4\s*(billion|bn)\b", t):
        return True
    if re.search(r"\b2\.4\s*(billion|bn)\b", t):
        return True
    if re.search(r"\b2,?400,?000,?000\b", t):
        return True
    if re.search(r"\b2400000000\b", t):
        return True
    return False


def has_percent_reference(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    if re.search(r"\b40\s*%\b", t):
        return True
    if re.search(r"\b40\s*percent\b", t):
        return True
    return False


def has_years_reference(text: str) -> bool:
    if not text:
        return False
    return ("2024" in text) or ("2028" in text)


def argument_against_gas(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    has_gas = "gas" in t
    has_transition = "transition" in t
    has_fossil_or_depend = ("fossil" in t) or ("depend" in t) or ("lock-in" in t) or ("lock in" in t) or ("lockin" in t)
    has_incompat = ("incompat" in t) or ("not compatible" in t)
    has_prolong = ("prolong" in t) or ("lock-in" in t) or ("lock in" in t)
    return has_gas and has_transition and has_fossil_or_depend and has_prolong and has_incompat


def parse_iso8601(ts: str) -> bool:
    if not isinstance(ts, str):
        return False
    s = ts
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "releases_jsonl_record_present": 0.0,
        "releases_jsonl_fields_correct": 0.0,
        "releases_jsonl_reference_validation": 0.0,
        "releases_jsonl_no_duplicates_for_sha": 0.0,
        "logs_event_for_file_present": 0.0,
        "logs_event_structure_valid": 0.0,
        "processed_state_contains_entry": 0.0,
        "processed_state_object_has_path_and_hash": 0.0,
        "policy_brief_updated_exists": 0.0,
        "policy_brief_only_placeholder_replaced": 0.0,
        "policy_brief_mentions_company_project_and_numbers": 0.0,
        "policy_brief_argument_against_gas_transition": 0.0,
        "meeting_notes_file_exists": 0.0,
        "meeting_notes_header_block_correct": 0.0,
        "meeting_notes_summary_sentences_and_facts": 0.0,
        "meeting_notes_action_items_at_least_three": 0.0,
        "meeting_notes_action_items_owners_valid": 0.0,
        "meeting_notes_action_items_due_dates_relative": 0.0,
        "meeting_notes_action_items_reference_facts": 0.0,
    }

    input_html = workspace / "input" / "incoming" / "press_release_2023-09-12_gulfenergy.html"
    projects_csv = workspace / "input" / "reference" / "projects.csv"
    policy_brief_src = workspace / "input" / "policy_brief.md"

    expected = None
    expected_sha = None

    if input_html.exists():
        try:
            expected_sha = compute_sha256(input_html)
        except Exception:
            expected_sha = None
        expected = parse_html_press_release(input_html)
    else:
        expected_sha = None
        expected = None

    cv_rows = safe_read_csv(projects_csv) if projects_csv.exists() else None
    expected_cv = {"reference_match": False, "mismatches": []}
    if expected and expected.get("project_name") and cv_rows:
        expected_cv = cross_validate_with_csv(expected["project_name"], expected, cv_rows)

    releases_path = workspace / "outputs" / "releases.jsonl"
    rel_objs, _ = safe_read_jsonl(releases_path)
    if rel_objs is not None and expected_sha:
        matching = [o for o in rel_objs if isinstance(o, dict) and o.get("sha256") == expected_sha]
        if matching:
            scores["releases_jsonl_record_present"] = 1.0
            if len(matching) == 1:
                scores["releases_jsonl_no_duplicates_for_sha"] = 1.0
            obj = matching[0]
            needed_keys = [
                "file_path",
                "sha256",
                "company",
                "press_date",
                "project_name",
                "investment_usd",
                "claimed_emissions_reduction_percent",
                "region",
                "start_year",
                "end_year",
                "reference_match",
                "mismatches",
            ]
            fields_ok = all(k in obj for k in needed_keys)
            values_ok = False
            reference_ok = False
            if expected:
                try:
                    values_ok = (
                        (obj.get("company") == expected.get("company")) and
                        (obj.get("press_date") == expected.get("press_date")) and
                        (obj.get("project_name") == expected.get("project_name")) and
                        (obj.get("investment_usd") == expected.get("investment_usd")) and
                        (obj.get("claimed_emissions_reduction_percent") == expected.get("claimed_emissions_reduction_percent")) and
                        (obj.get("region") == expected.get("region")) and
                        (obj.get("start_year") == expected.get("start_year")) and
                        (obj.get("end_year") == expected.get("end_year")) and
                        (isinstance(obj.get("file_path"), str) and endswith_path(obj.get("file_path"), "input/incoming/press_release_2023-09-12_gulfenergy.html"))
                    )
                except Exception:
                    values_ok = False
            if fields_ok and values_ok:
                scores["releases_jsonl_fields_correct"] = 1.0
            try:
                reference_ok = (obj.get("reference_match") == expected_cv.get("reference_match") and
                                isinstance(obj.get("mismatches"), list) and
                                sorted(obj.get("mismatches")) == sorted(expected_cv.get("mismatches")))
            except Exception:
                reference_ok = False
            if reference_ok:
                scores["releases_jsonl_reference_validation"] = 1.0

    events_path = workspace / "outputs" / "logs" / "events.jsonl"
    ev_objs, _ = safe_read_jsonl(events_path)
    if ev_objs is not None and expected_sha:
        ev_matches = [e for e in ev_objs if isinstance(e, dict) and e.get("sha256") == expected_sha and e.get("processed") is True]
        if ev_matches:
            scores["logs_event_for_file_present"] = 1.0
            valid_struct = False
            for e in ev_matches:
                if (isinstance(e.get("file_path"), str) and endswith_path(e.get("file_path"), "input/incoming/press_release_2023-09-12_gulfenergy.html")
                        and isinstance(e.get("sha256"), str)
                        and isinstance(e.get("processed"), bool)
                        and "timestamp" in e and parse_iso8601(e.get("timestamp"))):
                    valid_struct = True
                    break
            if valid_struct:
                scores["logs_event_structure_valid"] = 1.0

    processed_path = workspace / "outputs" / "state" / "processed.json"
    proc = safe_read_json(processed_path)
    if isinstance(proc, list) and expected_sha:
        contains = False
        has_obj_with_path_and_hash = False
        for item in proc:
            if isinstance(item, dict):
                if item.get("sha256") == expected_sha:
                    contains = True
                    if isinstance(item.get("file_path"), str) and endswith_path(item.get("file_path"), "input/incoming/press_release_2023-09-12_gulfenergy.html"):
                        has_obj_with_path_and_hash = True
            elif isinstance(item, str):
                if item == expected_sha:
                    contains = True
        if contains:
            scores["processed_state_contains_entry"] = 1.0
        if has_obj_with_path_and_hash:
            scores["processed_state_object_has_path_and_hash"] = 1.0

    updated_policy = workspace / "outputs" / "policy_brief_updated.md"
    if updated_policy.exists():
        scores["policy_brief_updated_exists"] = 1.0
        orig_text = safe_read_text(policy_brief_src)
        upd_text = safe_read_text(updated_policy)
        if orig_text is not None and upd_text is not None:
            orig_lines = orig_text.splitlines()
            upd_lines = upd_text.splitlines()
            placeholder_idx = None
            for i in range(len(orig_lines) - 1):
                if orig_lines[i].strip() == "## Latest Industry Announcements":
                    if i + 1 < len(orig_lines) and orig_lines[i + 1].strip().startswith("[TO UPDATE]"):
                        placeholder_idx = i + 1
                        break
            only_one_line_changed = False
            replaced_line = None
            if placeholder_idx is not None and len(orig_lines) == len(upd_lines):
                diffs = [j for j in range(len(orig_lines)) if (orig_lines[j] != upd_lines[j])]
                if diffs == [placeholder_idx] and upd_lines[placeholder_idx].strip() and not upd_lines[placeholder_idx].strip().startswith("[TO UPDATE]"):
                    only_one_line_changed = True
                    replaced_line = upd_lines[placeholder_idx]
            if only_one_line_changed:
                scores["policy_brief_only_placeholder_replaced"] = 1.0
                line = replaced_line
                mentions_company = expected and expected.get("company") and (expected["company"] in line)
                mentions_project = expected and expected.get("project_name") and (expected["project_name"] in line)
                facts_count = 0
                if has_investment_reference(line):
                    facts_count += 1
                if has_percent_reference(line):
                    facts_count += 1
                if has_years_reference(line):
                    facts_count += 1
                sentences_ok = 2 <= count_sentences(line) <= 4
                if mentions_company and mentions_project and facts_count >= 2 and sentences_ok:
                    scores["policy_brief_mentions_company_project_and_numbers"] = 1.0
                if argument_against_gas(line):
                    scores["policy_brief_argument_against_gas_transition"] = 1.0

    meeting_notes = workspace / "outputs" / "meeting_notes" / "press_release_2023-09-12.md"
    if meeting_notes.exists():
        scores["meeting_notes_file_exists"] = 1.0
        notes_text = safe_read_text(meeting_notes)
        if notes_text:
            lines = notes_text.splitlines()
            expected_headers = {
                "Press Release Date": expected.get("press_date") if expected else "2023-09-12",
                "Company": expected.get("company") if expected else "GulfEnergy",
                "Project": expected.get("project_name") if expected else "Bay Coast LNG Expansion",
                "Investment_USD": str(expected.get("investment_usd")) if (expected and expected.get("investment_usd") is not None) else "2400000000",
                "Claimed_Emissions_Reduction_Percent": str(expected.get("claimed_emissions_reduction_percent")) if (expected and expected.get("claimed_emissions_reduction_percent") is not None) else "40",
                "Region": expected.get("region") if expected else "Bay Coast, TX",
                "Timeline": f"{expected.get('start_year')}-{expected.get('end_year')}" if expected else "2024-2028",
            }
            header_ok = True
            for key, val in expected_headers.items():
                pattern = f"{key}: {val}"
                found = any(ln.strip() == pattern for ln in lines)
                if not found:
                    header_ok = False
                    break
            if header_ok:
                scores["meeting_notes_header_block_correct"] = 1.0

            summary_idx = None
            for i, ln in enumerate(lines):
                if ln.strip().lower().startswith("summary"):
                    summary_idx = i
                    break
            summary_text = ""
            if summary_idx is not None:
                for j in range(summary_idx + 1, len(lines)):
                    if not lines[j].strip():
                        if summary_text:
                            break
                        else:
                            continue
                    if re.match(r'^\s*#+\s*\w+', lines[j]) or lines[j].strip().lower().startswith("action items"):
                        break
                    if ":" in lines[j] and lines[j].split(":")[0] in expected_headers:
                        continue
                    if summary_text:
                        summary_text += " " + lines[j].strip()
                    else:
                        summary_text = lines[j].strip()
            if summary_text:
                s_ok = 2 <= count_sentences(summary_text) <= 4
                facts = 0
                if expected:
                    if expected.get("company") and expected["company"] in summary_text:
                        facts += 1
                    if expected.get("project_name") and expected["project_name"] in summary_text:
                        facts += 1
                if has_investment_reference(summary_text):
                    facts += 1
                if has_percent_reference(summary_text):
                    facts += 1
                if "2024" in summary_text or "2028" in summary_text:
                    facts += 1
                if s_ok and facts >= 2:
                    scores["meeting_notes_summary_sentences_and_facts"] = 1.0

            ai_idx = None
            for i, ln in enumerate(lines):
                if ln.strip().lower().startswith("action items"):
                    ai_idx = i
                    break
            items = []
            if ai_idx is not None:
                for j in range(ai_idx + 1, len(lines)):
                    ln = lines[j].strip()
                    if not ln:
                        continue
                    if re.match(r'^\s*#+\s*\w+', ln):
                        break
                    if "Owner:" in ln and "DueDate:" in ln:
                        items.append(ln)
            if len(items) >= 3:
                scores["meeting_notes_action_items_at_least_three"] = 1.0
            owners_valid = True
            due_dates_valid = True
            refs_valid = True
            allowed_owners = {"Communications", "Policy", "Research"}
            press_date_str = expected.get("press_date") if expected else "2023-09-12"
            try:
                press_dt = datetime.strptime(press_date_str, "%Y-%m-%d").date()
            except Exception:
                press_dt = None
            for ln in items:
                m_owner = re.search(r"Owner:\s*([A-Za-z ]+)", ln)
                owner_val = m_owner.group(1).strip() if m_owner else None
                if owner_val not in allowed_owners:
                    owners_valid = False
                m_due = re.search(r"DueDate:\s*(\d{4}-\d{2}-\d{2})", ln)
                due_str = m_due.group(1) if m_due else None
                if due_str and press_dt:
                    try:
                        due_dt = datetime.strptime(due_str, "%Y-%m-%d").date()
                        if not (due_dt >= press_dt and due_dt <= press_dt + timedelta(days=30)):
                            due_dates_valid = False
                    except Exception:
                        due_dates_valid = False
                else:
                    due_dates_valid = False
                ref_ok = False
                tokens = []
                if expected:
                    tokens = [
                        expected.get("company") or "",
                        expected.get("project_name") or "",
                        str(expected.get("investment_usd") or ""),
                        str(expected.get("claimed_emissions_reduction_percent") or ""),
                        expected.get("region") or "",
                        str(expected.get("start_year") or ""),
                        str(expected.get("end_year") or ""),
                    ]
                else:
                    tokens = ["GulfEnergy", "Bay Coast LNG Expansion", "2400000000", "40", "Bay Coast, TX", "2024", "2028"]
                tokens += ["40%"]
                for t in tokens:
                    if t and t in ln:
                        ref_ok = True
                        break
                if not ref_ok:
                    refs_valid = False
            if owners_valid and len(items) >= 3:
                scores["meeting_notes_action_items_owners_valid"] = 1.0
            if due_dates_valid and len(items) >= 3:
                scores["meeting_notes_action_items_due_dates_relative"] = 1.0
            if refs_valid and len(items) >= 3:
                scores["meeting_notes_action_items_reference_facts"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()