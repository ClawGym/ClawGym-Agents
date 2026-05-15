import json
import csv
import sys
import re
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urlparse


def _safe_read_text(path: Path) -> tuple[str, str]:
    try:
        return path.read_text(encoding="utf-8"), ""
    except Exception as e:
        return "", str(e)


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), ""
    except Exception as e:
        return None, str(e)


def _safe_parse_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [dict(row) for row in reader]
            return headers, rows, ""
    except Exception as e:
        return [], [], str(e)


def _is_iso_date_yyyy_mm_dd(s: str) -> bool:
    try:
        datetime.strptime(s.strip(), "%Y-%m-%d")
        return True
    except Exception:
        return False


def _is_iso8601_timestamp(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    if not re.match(r"^\d{4}-\d{2}-\d{2}T", s):
        return False
    try:
        ts = s.replace("Z", "+00:00")
        datetime.fromisoformat(ts)
        return True
    except Exception:
        return False


def _domain_from_url(u: str) -> str:
    try:
        p = urlparse(u.strip())
        return p.netloc.lower()
    except Exception:
        return ""


def _is_url(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    return s.startswith("http://") or s.startswith("https://")


def _paragraphs(text: str) -> list[str]:
    paras = []
    current = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                paras.append("\n".join(current).strip())
                current = []
        else:
            current.append(line.rstrip())
    if current:
        paras.append("\n".join(current).strip())
    return paras


def _word_count(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)


def _get_expected_destinations(input_data: dict) -> list[dict]:
    dests = input_data.get("destinations", []) if isinstance(input_data, dict) else []
    results = []
    for d in dests:
        city = d.get("city")
        state = d.get("state")
        dates = d.get("dates", [])
        focus = d.get("focus", [])
        if isinstance(city, str) and isinstance(state, str):
            results.append({
                "city": city,
                "state": state,
                "dates": dates if isinstance(dates, list) else [],
                "focus": focus if isinstance(focus, list) else [],
            })
    return results


def _csv_row_lookup(rows: list[dict], city: str, state: str) -> dict | None:
    for r in rows:
        if (r.get("destination_city", "") == city) and (r.get("destination_state", "") == state):
            return r
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "tourism_contacts_has_required_columns": 0.0,
        "tourism_contacts_row_count_matches": 0.0,
        "tourism_contacts_fields_valid": 0.0,
        "tourism_contacts_officialness_heuristic": 0.0,
        "search_log_schema_valid": 0.0,
        "search_log_coverage_per_destination": 0.0,
        "template_has_required_placeholders": 0.0,
        "template_paragraph_and_length_valid": 0.0,
        "template_requests_guidelines_and_call": 0.0,
        "template_mentions_deliverables": 0.0,
        "email_preview_exists_and_name": 0.0,
        "email_preview_values_filled_and_matched": 0.0,
        "email_preview_no_placeholders_remaining": 0.0,
        "meeting_notes_title_and_participants": 0.0,
        "meeting_notes_discussion_and_decisions_references": 0.0,
        "meeting_notes_action_items_due_dates": 0.0,
    }

    # Load input JSON
    input_path = workspace / "input" / "roadtrip_plan.json"
    input_data, input_err = _safe_load_json(input_path)
    if not isinstance(input_data, dict):
        return scores

    trip_title = input_data.get("trip_title", "")
    sponsor = input_data.get("sponsor", {})
    key_message = sponsor.get("key_message", "")
    deliverables = sponsor.get("deliverables", []) if isinstance(sponsor.get("deliverables", []), list) else []
    collaborators = input_data.get("collaborators", []) if isinstance(input_data.get("collaborators", []), list) else []
    owners = {"Me"} | {c.get("name", "") for c in collaborators if isinstance(c, dict) and isinstance(c.get("name", ""), str)}
    owners = {o for o in owners if o}
    window = input_data.get("window", {})
    window_end = window.get("end_date", "")
    expected_dests = _get_expected_destinations(input_data)

    # 1) CSV: outputs/research/tourism_contacts.csv
    csv_path = workspace / "outputs" / "research" / "tourism_contacts.csv"
    csv_headers, csv_rows, csv_err = _safe_parse_csv_dicts(csv_path)
    required_columns = [
        "destination_city",
        "destination_state",
        "official_org_name",
        "official_site_url",
        "media_or_press_page_url",
        "contact_email_or_form",
        "press_kit_or_assets_url",
        "content_guidelines_summary",
        "query_used",
        "date_accessed",
    ]
    if csv_headers:
        has_all = all(col in csv_headers for col in required_columns)
        scores["tourism_contacts_has_required_columns"] = 1.0 if has_all else 0.0

    # Row count and mapping to destinations
    if csv_rows and expected_dests:
        expected_set = {(d["city"], d["state"]) for d in expected_dests}
        seen = [(r.get("destination_city", ""), r.get("destination_state", "")) for r in csv_rows]
        seen_set = set(seen)
        correct_count = (len(csv_rows) == len(expected_dests)) and (seen_set == expected_set)
        no_dupes = len(seen) == len(seen_set)
        scores["tourism_contacts_row_count_matches"] = 1.0 if (correct_count and no_dupes) else 0.0

    # Fields validity
    fields_valid = True
    if csv_rows:
        for r in csv_rows:
            if not isinstance(r.get("query_used", ""), str) or not r.get("query_used", "").strip():
                fields_valid = False
                break
            if not _is_iso_date_yyyy_mm_dd(r.get("date_accessed", "")):
                fields_valid = False
                break
            cgs = r.get("content_guidelines_summary", "")
            if not isinstance(cgs, str) or len(cgs) > 300:
                fields_valid = False
                break
            for url_field in ("official_site_url", "media_or_press_page_url", "press_kit_or_assets_url"):
                val = r.get(url_field, "")
                if not isinstance(val, str):
                    fields_valid = False
                    break
                v = val.strip()
                if v != "N/A" and not _is_url(v):
                    fields_valid = False
                    break
            if not fields_valid:
                break
            cef = r.get("contact_email_or_form", "")
            if not isinstance(cef, str) or not cef.strip():
                fields_valid = False
                break
            if cef.strip() != "N/A":
                if ("@" not in cef) and (not _is_url(cef)):
                    fields_valid = False
                    break
    if csv_rows:
        scores["tourism_contacts_fields_valid"] = 1.0 if fields_valid else 0.0

    # Officialness heuristic
    if csv_rows:
        count = 0
        ok = 0
        for r in csv_rows:
            count += 1
            urls = []
            for k in ("official_site_url", "media_or_press_page_url"):
                v = r.get(k, "")
                if isinstance(v, str) and v.strip() != "N/A":
                    urls.append(v.strip())
            if not urls:
                continue
            row_ok = False
            for u in urls:
                dom = _domain_from_url(u)
                if dom.endswith(".gov") or dom.endswith(".us"):
                    row_ok = True
                    break
                if any(token in dom for token in ["visit", "tourism", "travel"]):
                    row_ok = True
                    break
            if row_ok:
                ok += 1
        scores["tourism_contacts_officialness_heuristic"] = (ok / count) if count > 0 else 0.0

    # 2) search_log.jsonl
    log_path = workspace / "outputs" / "research" / "search_log.jsonl"
    log_text, log_err = _safe_read_text(log_path)
    log_entries = []
    if log_text:
        for i, line in enumerate(log_text.splitlines()):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                log_entries.append(obj)
            except Exception:
                log_entries.append({"__invalid__": True})

    schema_valid = True
    if log_entries:
        for obj in log_entries:
            if obj.get("__invalid__"):
                schema_valid = False
                break
            if not isinstance(obj.get("destination_city"), str) or not isinstance(obj.get("destination_state"), str):
                schema_valid = False
                break
            if not isinstance(obj.get("queries"), list) or not obj.get("queries"):
                schema_valid = False
                break
            if not all(isinstance(q, str) and q.strip() for q in obj.get("queries", [])):
                schema_valid = False
                break
            if not isinstance(obj.get("chosen_result_title"), str):
                schema_valid = False
                break
            if not isinstance(obj.get("chosen_result_url"), str) or not obj.get("chosen_result_url").strip():
                schema_valid = False
                break
            rationale = obj.get("rationale")
            if not isinstance(rationale, str) or len(rationale) > 200:
                schema_valid = False
                break
            if not _is_iso8601_timestamp(obj.get("timestamp", "")):
                schema_valid = False
                break
    if log_entries:
        scores["search_log_schema_valid"] = 1.0 if schema_valid else 0.0

    # Coverage per destination
    if expected_dests:
        coverage = 0
        for d in expected_dests:
            c = d["city"]
            s = d["state"]
            found = False
            for obj in log_entries:
                if isinstance(obj, dict) and (obj.get("destination_city") == c) and (obj.get("destination_state") == s):
                    found = True
                    break
            if found:
                coverage += 1
        scores["search_log_coverage_per_destination"] = coverage / len(expected_dests) if expected_dests else 0.0

    # 3) Email template
    tmpl_path = workspace / "outputs" / "communications" / "outreach_email_template.txt"
    tmpl_text, tmpl_err = _safe_read_text(tmpl_path)
    placeholders = {"[[TRIP_TITLE]]", "[[DESTINATION]]", "[[DATES]]", "[[ORG_NAME]]", "[[MEDIA_PAGE_URL]]", "[[PRESS_KIT_URL]]", "[[KEY_MESSAGE]]"}
    if tmpl_text:
        has_placeholders = all(p in tmpl_text for p in placeholders)
        scores["template_has_required_placeholders"] = 1.0 if has_placeholders else 0.0
        paras = _paragraphs(tmpl_text)
        wc = _word_count(tmpl_text)
        if 3 <= len(paras) <= 5 and wc <= 220:
            scores["template_paragraph_and_length_valid"] = 1.0
        else:
            scores["template_paragraph_and_length_valid"] = 0.0
        content_lower = tmpl_text.lower()
        asks_guidelines = ("guideline" in content_lower) or ("permit" in content_lower) or ("media" in content_lower and "contact" in content_lower)
        asks_call = "call" in content_lower
        scores["template_requests_guidelines_and_call"] = 1.0 if (asks_guidelines and asks_call) else 0.0
        scores["template_mentions_deliverables"] = 1.0 if "deliverables" in content_lower else 0.0

    # 4) Email preview for first destination
    if expected_dests:
        first = expected_dests[0]
        city0 = first["city"]
        state0 = first["state"]
        preview_name = f"outreach_email_preview_{city0}_{state0}.txt"
        preview_path = workspace / "outputs" / "communications" / preview_name
        if preview_path.exists():
            scores["email_preview_exists_and_name"] = 1.0
        preview_text, prev_err = _safe_read_text(preview_path)
        if preview_text:
            scores["email_preview_no_placeholders_remaining"] = 1.0 if not re.search(r"\[\[.+?\]\]", preview_text) else 0.0

            include_ok = True
            if trip_title and (trip_title not in preview_text):
                include_ok = False
            if city0 not in preview_text or state0 not in preview_text:
                include_ok = False
            dts = first.get("dates", [])
            if isinstance(dts, list) and len(dts) >= 2:
                if dts[0] not in preview_text or dts[-1] not in preview_text:
                    include_ok = False
            if isinstance(key_message, str) and key_message and (key_message not in preview_text):
                include_ok = include_ok and True
            else:
                include_ok = False

            row = _csv_row_lookup(csv_rows, city0, state0) if csv_rows else None
            mapping_ok = True
            if row is None:
                mapping_ok = False
            else:
                map_fields = {
                    "ORG_NAME": "official_org_name",
                    "MEDIA_PAGE_URL": "media_or_press_page_url",
                    "PRESS_KIT_URL": "press_kit_or_assets_url",
                }
                for placeholder, csv_field in map_fields.items():
                    val = row.get(csv_field, "")
                    if not isinstance(val, str):
                        mapping_ok = False
                        break
                    if val.strip() == "" or val.strip() == "N/A":
                        pattern_note = f"[Missing: {placeholder}]"
                        if "TBD" not in preview_text or pattern_note not in preview_text:
                            mapping_ok = False
                            break
                    else:
                        if val not in preview_text:
                            mapping_ok = False
                            break

            scores["email_preview_values_filled_and_matched"] = 1.0 if (include_ok and mapping_ok) else 0.0

    # 5) Planning call notes
    notes_path = workspace / "outputs" / "meetings" / "planning_call_notes.md"
    notes_text, notes_err = _safe_read_text(notes_path)
    if notes_text:
        lines = [ln for ln in notes_text.splitlines() if ln.strip()]
        title_ok = False
        if lines:
            first_line = lines[0]
            date_match = re.search(r"\d{4}-\d{2}-\d{2}", first_line)
            if trip_title in first_line and date_match:
                title_ok = True

        participants_ok = True
        if "Me" not in notes_text:
            participants_ok = False
        for c in collaborators:
            nm = c.get("name", "")
            if nm and nm not in notes_text:
                participants_ok = False
                break

        scores["meeting_notes_title_and_participants"] = 1.0 if (title_ok and participants_ok) else 0.0

        refs_ok = all([
            "outputs/research/tourism_contacts.csv" in notes_text,
            "outputs/research/search_log.jsonl" in notes_text,
            "outputs/communications/outreach_email_template.txt" in notes_text,
        ])

        drone_ok = ("drone" in notes_text.lower() and ("restriction" in notes_text.lower() or "regulation" in notes_text.lower()))
        decisions_ok = "Decisions" in notes_text or "decisions" in notes_text

        discussion_ok = True
        if csv_rows and expected_dests:
            for d in expected_dests:
                city = d["city"]
                focus_list = d["focus"]
                has_focus = any(f in notes_text for f in focus_list if isinstance(f, str))
                row = _csv_row_lookup(csv_rows, d["city"], d["state"])
                org_ok = True
                if row:
                    org_name = row.get("official_org_name", "")
                    if isinstance(org_name, str) and org_name.strip() and org_name not in notes_text:
                        org_ok = False
                else:
                    org_ok = False
                city_ok = city in notes_text
                if not (has_focus and org_ok and city_ok):
                    discussion_ok = False
                    break
        else:
            discussion_ok = False

        ddref_ok = all([refs_ok, drone_ok, decisions_ok, discussion_ok])
        scores["meeting_notes_discussion_and_decisions_references"] = 1.0 if ddref_ok else 0.0

        action_lines = [ln for ln in notes_text.splitlines() if "Due" in ln]
        task_count = 0
        due_dates_ok = True
        owner_ok_all = True
        end_ok = _is_iso_date_yyyy_mm_dd(window_end)
        end_dt = datetime.strptime(window_end, "%Y-%m-%d").date() if end_ok else None
        for ln in action_lines:
            m = re.search(r"Due\s+(\d{4}-\d{2}-\d{2})", ln)
            owner_match = re.match(r"^\s*-?\s*([^:]+):", ln)
            if m and owner_match:
                due_str = m.group(1)
                owner = owner_match.group(1).strip()
                if owner not in owners:
                    owner_ok_all = False
                if _is_iso_date_yyyy_mm_dd(due_str) and end_dt is not None:
                    ddt = datetime.strptime(due_str, "%Y-%m-%d").date()
                    if ddt > end_dt:
                        due_dates_ok = False
                task_count += 1
        if task_count >= 5 and due_dates_ok and owner_ok_all:
            scores["meeting_notes_action_items_due_dates"] = 1.0
        else:
            if task_count > 0:
                scores["meeting_notes_action_items_due_dates"] = min(task_count / 5.0, 1.0) if (due_dates_ok and owner_ok_all) else 0.0
            else:
                scores["meeting_notes_action_items_due_dates"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()