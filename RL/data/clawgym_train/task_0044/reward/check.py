import json
import csv
import re
import sys
from pathlib import Path
from html.parser import HTMLParser


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        txt = _safe_read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _safe_read_csv(path: Path):
    try:
        content = _safe_read_text(path)
        if content is None:
            return None
        lines = content.splitlines()
        reader = csv.DictReader(lines)
        rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


class EventsTableParser(HTMLParser):
    def __init__(self, target_id: str):
        super().__init__()
        self.target_id = target_id
        self.in_target_table = False
        self.in_thead = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cell = ""
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "table":
            if attrs_dict.get("id") == self.target_id:
                self.in_target_table = True
        if not self.in_target_table:
            return
        if tag.lower() == "thead":
            self.in_thead = True
        if tag.lower() == "tbody":
            self.in_tbody = True
        if tag.lower() == "tr":
            self.in_tr = True
            self.current_row = []
        if tag.lower() == "td":
            self.in_td = True
            self.current_cell = ""

    def handle_endtag(self, tag):
        if not self.in_target_table:
            return
        if tag.lower() == "td":
            self.in_td = False
            self.current_row.append(self.current_cell.strip())
            self.current_cell = ""
        if tag.lower() == "tr":
            if self.in_tr and self.current_row:
                if self.in_tbody and len(self.current_row) >= 1:
                    self.rows.append(self.current_row)
            self.in_tr = False
            self.current_row = []
        if tag.lower() == "thead":
            self.in_thead = False
        if tag.lower() == "tbody":
            self.in_tbody = False
        if tag.lower() == "table":
            self.in_target_table = False

    def handle_data(self, data):
        if self.in_target_table and self.in_tr and self.in_td:
            self.current_cell += data


def _parse_events_from_html(path: Path):
    html = _safe_read_text(path)
    if html is None:
        return None
    parser = EventsTableParser("events")
    try:
        parser.feed(html)
    except Exception:
        return None
    events = []
    for row in parser.rows:
        if len(row) >= 4:
            events.append({
                "date": row[0].strip(),
                "title": row[1].strip(),
                "venue": row[2].strip(),
                "organizer": row[3].strip()
            })
    return events


def _normalize_record(rec: dict) -> dict:
    normalized = {}
    for k, v in rec.items():
        if v is None:
            normalized[k] = ""
        else:
            normalized[k] = str(v).strip()
    return normalized


def _compute_business_diff(prev_rows: list, curr_rows: list):
    prev_map = {}
    curr_map = {}
    for r in prev_rows:
        nr = _normalize_record(r)
        prev_map[nr.get("id", "")] = nr
    for r in curr_rows:
        nr = _normalize_record(r)
        curr_map[nr.get("id", "")] = nr

    prev_ids = set(prev_map.keys()) - {""}
    curr_ids = set(curr_map.keys()) - {""}

    def _id_sort_key(x: str):
        return int(x) if x.isdigit() else x

    new_ids = sorted(curr_ids - prev_ids, key=_id_sort_key)
    removed_ids = sorted(prev_ids - curr_ids, key=_id_sort_key)

    closures = []
    reopenings = []
    field_updates = []

    common_ids = prev_ids & curr_ids
    for bid in sorted(common_ids, key=_id_sort_key):
        p = prev_map[bid]
        c = curr_map[bid]
        p_status = p.get("status", "").strip().lower()
        c_status = c.get("status", "").strip().lower()
        if p_status == "open" and c_status == "temporarily_closed":
            closures.append({"id": bid, "name": c.get("name", "") or p.get("name", "")})
        elif p_status == "temporarily_closed" and c_status == "open":
            reopenings.append({"id": bid, "name": c.get("name", "") or p.get("name", "")})
        changed_fields = []
        for field in ["name", "category", "neighborhood", "street", "phone"]:
            if p.get(field, "") != c.get(field, ""):
                changed_fields.append(field)
        if changed_fields:
            field_updates.append({
                "id": bid,
                "name": c.get("name", "") or p.get("name", ""),
                "changed_fields": changed_fields
            })

    new_list = [{
        "id": bid,
        "name": curr_map[bid].get("name", ""),
        "category": curr_map[bid].get("category", ""),
        "neighborhood": curr_map[bid].get("neighborhood", "")
    } for bid in new_ids]
    removed_list = [{"id": bid, "name": prev_map[bid].get("name", "")} for bid in removed_ids]

    counts = {
        "total": len(curr_ids),
        "new": len(new_list),
        "removed": len(removed_list),
        "closures": len(closures),
        "reopenings": len(reopenings),
        "other_updates": len(field_updates)
    }

    result = {
        "counts": counts,
        "new": new_list,
        "removed": removed_list,
        "closures": closures,
        "reopenings": reopenings,
        "field_updates": field_updates
    }
    return result


def _line_has_words_and_number(line: str, words: list, number: int) -> bool:
    lower = line.lower()
    if all(w in lower for w in words):
        return str(number) in line
    return False


def _text_has_label_and_number(text: str, words: list, number: int) -> bool:
    if text is None:
        return False
    for line in text.splitlines():
        if _line_has_words_and_number(line, words, number):
            return True
    return False


def _contains_id_and_name(text: str, item: dict) -> bool:
    if text is None:
        return False
    return (str(item.get("id", "")) in text) and (item.get("name", "") in text)


def _contains_all(text: str, substrings: list) -> bool:
    if text is None:
        return False
    t = text
    return all(s in t for s in substrings)


def _find_count_key(counts: dict, candidates: list):
    if not isinstance(counts, dict):
        return None
    keys = list(counts.keys())
    for cand in candidates:
        for k in keys:
            if k.lower() == cand.lower():
                return k
    for cand in candidates:
        for k in keys:
            if cand.lower() in k.lower():
                return k
    return None


def _json_get_list(obj: dict, key: str) -> list:
    val = obj.get(key)
    if isinstance(val, list):
        return val
    return []


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_file_present": 0.0,
        "script_cli_args_declared": 0.0,
        "report_exists_and_mentions_ibb": 0.0,
        "report_counts_correct": 0.0,
        "report_new_list_fields_present": 0.0,
        "report_removed_list_present": 0.0,
        "report_closures_list_present": 0.0,
        "report_reopenings_list_present": 0.0,
        "report_other_updates_fields_present": 0.0,
        "report_events_section_correct": 0.0,
        "email_subject_and_body_valid": 0.0,
        "whatsapp_message_valid": 0.0,
        "business_diff_json_valid": 0.0,
        "run_log_valid": 0.0,
    }

    # Paths
    prev_csv = workspace / "input" / "businesses_week_prev.csv"
    curr_csv = workspace / "input" / "businesses_week_curr.csv"
    events_html = workspace / "input" / "events.html"
    contacts_json = workspace / "input" / "community_contacts.json"

    report_md = workspace / "output" / "report" / "weekly_update.md"
    email_txt = workspace / "output" / "messages" / "email_draft.txt"
    whatsapp_txt = workspace / "output" / "messages" / "whatsapp_message.txt"
    diff_json = workspace / "output" / "structured" / "business_diff.json"
    run_log = workspace / "output" / "run_log.txt"

    # Script checks
    script_path = workspace / "scripts" / "generate_update.py"
    if script_path.exists():
        scores["script_file_present"] = 1.0
        code = _safe_read_text(script_path) or ""
        needed_args = ["--prev", "--curr", "--events", "--contacts", "--out-dir"]
        if all(arg in code for arg in needed_args):
            scores["script_cli_args_declared"] = 1.0

    # Load inputs
    prev_rows = _safe_read_csv(prev_csv) or []
    curr_rows = _safe_read_csv(curr_csv) or []
    events = _parse_events_from_html(events_html) or []
    contacts = _safe_load_json(contacts_json) or {}

    # Compute expected diff
    try:
        expected_diff = _compute_business_diff(prev_rows, curr_rows)
    except Exception:
        expected_diff = None

    # Report checks
    report_text = _safe_read_text(report_md)
    if report_text is not None and "Ibb" in report_text:
        scores["report_exists_and_mentions_ibb"] = 1.0

    if expected_diff is not None and report_text is not None:
        # Counts checks
        counts_ok = True
        counts = expected_diff["counts"]
        if not _text_has_label_and_number(report_text, ["total", "business"], counts["total"]):
            counts_ok = False
        if not _text_has_label_and_number(report_text, ["new"], counts["new"]):
            counts_ok = False
        if not _text_has_label_and_number(report_text, ["removed"], counts["removed"]):
            counts_ok = False
        if not (_text_has_label_and_number(report_text, ["closure"], counts["closures"])):
            counts_ok = False
        if not (_text_has_label_and_number(report_text, ["reopening"], counts["reopenings"])):
            counts_ok = False
        if not (_text_has_label_and_number(report_text, ["other", "update"], counts["other_updates"])):
            counts_ok = False
        scores["report_counts_correct"] = 1.0 if counts_ok else 0.0

        # New list items fields presence
        new_ok = True
        for item in expected_diff["new"]:
            if not _contains_id_and_name(report_text, item):
                new_ok = False
                break
            if not (_contains_all(report_text, [item.get("category", "")]) and _contains_all(report_text, [item.get("neighborhood", "")])):
                new_ok = False
                break
        scores["report_new_list_fields_present"] = 1.0 if new_ok else 0.0

        # Removed
        removed_ok = True
        for item in expected_diff["removed"]:
            if not _contains_id_and_name(report_text, item):
                removed_ok = False
                break
        scores["report_removed_list_present"] = 1.0 if removed_ok else 0.0

        # Closures
        closures_ok = True
        for item in expected_diff["closures"]:
            if not _contains_id_and_name(report_text, item):
                closures_ok = False
                break
        scores["report_closures_list_present"] = 1.0 if closures_ok else 0.0

        # Reopenings
        reopen_ok = True
        for item in expected_diff["reopenings"]:
            if not _contains_id_and_name(report_text, item):
                reopen_ok = False
                break
        scores["report_reopenings_list_present"] = 1.0 if reopen_ok else 0.0

        # Other updates fields presence
        updates_ok = True
        for item in expected_diff["field_updates"]:
            if not _contains_id_and_name(report_text, item):
                updates_ok = False
                break
            cf = item.get("changed_fields", [])
            if not cf:
                updates_ok = False
                break
            if not any(field in report_text for field in cf):
                updates_ok = False
                break
        scores["report_other_updates_fields_present"] = 1.0 if updates_ok else 0.0

        # Events section: each event date, title, venue present
        events_ok = True
        for ev in events:
            if not (_contains_all(report_text, [ev["date"], ev["title"], ev["venue"]])):
                events_ok = False
                break
        scores["report_events_section_correct"] = 1.0 if events_ok else 0.0

    # Email checks
    email_text = _safe_read_text(email_txt)
    if email_text is not None and expected_diff is not None:
        lines = email_text.splitlines()
        subject_ok = False
        body_ok = False
        if lines:
            subj = lines[0].strip()
            if subj.startswith("Subject:") and ("Ibb Weekly Update" in subj):
                subj_lower = subj.lower()
                has_new_kw = "new" in subj_lower
                has_clos_kw = "clos" in subj_lower
                has_numbers = (str(expected_diff["counts"]["new"]) in subj) and (str(expected_diff["counts"]["closures"]) in subj)
                if has_numbers and has_new_kw and has_clos_kw:
                    subject_ok = True
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        if body:
            greet_ok = bool(re.search(r"\b(hi|hello|dear)\b", body, flags=re.IGNORECASE))
            counts = expected_diff["counts"]
            new_in_body = any(_line_has_words_and_number(line, ["new"], counts["new"]) for line in body.splitlines())
            clos_in_body = any(_line_has_words_and_number(line, ["clos"], counts["closures"]) for line in body.splitlines())
            ev_matches = 0
            for ev in events:
                if (ev["title"] in body) and (ev["date"] in body):
                    ev_matches += 1
            events_listed = ev_matches >= 2
            path_ref = "output/report/weekly_update.md" in body
            body_ok = greet_ok and new_in_body and clos_in_body and events_listed and path_ref
        scores["email_subject_and_body_valid"] = 1.0 if (subject_ok and body_ok) else 0.0

    # WhatsApp checks
    whatsapp_text = _safe_read_text(whatsapp_txt)
    if whatsapp_text is not None and expected_diff is not None and contacts:
        w_ok = True
        if len(whatsapp_text) > 500:
            w_ok = False
        group_name = contacts.get("whatsapp_group", "")
        if group_name and group_name not in whatsapp_text:
            w_ok = False
        if "Ibb" not in whatsapp_text:
            w_ok = False
        counts = expected_diff["counts"]
        has_new = any(_line_has_words_and_number(line, ["new"], counts["new"]) for line in whatsapp_text.splitlines())
        has_clos = any(_line_has_words_and_number(line, ["clos"], counts["closures"]) for line in whatsapp_text.splitlines())
        if not (has_new and has_clos):
            w_ok = False
        ev_matches = 0
        for ev in events:
            if (ev["title"] in whatsapp_text) and (ev["date"] in whatsapp_text):
                ev_matches += 1
        if ev_matches < 2:
            w_ok = False
        scores["whatsapp_message_valid"] = 1.0 if w_ok else 0.0

    # business_diff.json checks
    bd = _safe_load_json(diff_json)
    if bd is not None and expected_diff is not None:
        diff_ok = True
        for k in ["counts", "new", "removed", "closures", "reopenings", "field_updates"]:
            if k not in bd:
                diff_ok = False
        counts_obj = bd.get("counts", {})
        k_total = _find_count_key(counts_obj, ["total"])
        k_new = _find_count_key(counts_obj, ["new"])
        k_removed = _find_count_key(counts_obj, ["removed"])
        k_closures = _find_count_key(counts_obj, ["closures", "closure"])
        k_reopenings = _find_count_key(counts_obj, ["reopenings", "reopening"])
        k_other = _find_count_key(counts_obj, ["other_updates", "field_updates", "other"])
        if None in [k_total, k_new, k_removed, k_closures, k_reopenings, k_other]:
            diff_ok = False
        else:
            try:
                if int(counts_obj[k_total]) != expected_diff["counts"]["total"]:
                    diff_ok = False
                if int(counts_obj[k_new]) != expected_diff["counts"]["new"]:
                    diff_ok = False
                if int(counts_obj[k_removed]) != expected_diff["counts"]["removed"]:
                    diff_ok = False
                if int(counts_obj[k_closures]) != expected_diff["counts"]["closures"]:
                    diff_ok = False
                if int(counts_obj[k_reopenings]) != expected_diff["counts"]["reopenings"]:
                    diff_ok = False
                if int(counts_obj[k_other]) != expected_diff["counts"]["other_updates"]:
                    diff_ok = False
            except Exception:
                diff_ok = False

        if len(_json_get_list(bd, "new")) != len(expected_diff["new"]):
            diff_ok = False
        if len(_json_get_list(bd, "removed")) != len(expected_diff["removed"]):
            diff_ok = False
        if len(_json_get_list(bd, "closures")) != len(expected_diff["closures"]):
            diff_ok = False
        if len(_json_get_list(bd, "reopenings")) != len(expected_diff["reopenings"]):
            diff_ok = False
        if len(_json_get_list(bd, "field_updates")) != len(expected_diff["field_updates"]):
            diff_ok = False

        def items_have_id_name(items):
            for it in items:
                if not isinstance(it, dict):
                    return False
                if "id" not in it or "name" not in it:
                    return False
            return True

        if not items_have_id_name(_json_get_list(bd, "new")):
            diff_ok = False
        if not items_have_id_name(_json_get_list(bd, "removed")):
            diff_ok = False
        if not items_have_id_name(_json_get_list(bd, "closures")):
            diff_ok = False
        if not items_have_id_name(_json_get_list(bd, "reopenings")):
            diff_ok = False

        fu = _json_get_list(bd, "field_updates")
        changed_ok = True
        id_to_fields = {}
        for it in fu:
            if not isinstance(it, dict):
                changed_ok = False
                break
            cfields = it.get("changed_fields")
            if cfields is None:
                cfields = it.get("fields_changed")
            if not isinstance(cfields, (list, tuple)):
                changed_ok = False
                break
            id_to_fields[str(it.get("id"))] = [str(x) for x in cfields]
        if changed_ok:
            for exp in expected_diff["field_updates"]:
                eid = str(exp["id"])
                exp_fields = set(exp["changed_fields"])
                got_fields = set(id_to_fields.get(eid, []))
                if not exp_fields.issubset(got_fields):
                    changed_ok = False
                    break
        if not changed_ok:
            diff_ok = False

        exp_ids_new = set([str(x["id"]) for x in expected_diff["new"]])
        got_ids_new = set([str(x.get("id")) for x in _json_get_list(bd, "new")])
        if exp_ids_new != got_ids_new:
            diff_ok = False

        exp_ids_removed = set([str(x["id"]) for x in expected_diff["removed"]])
        got_ids_removed = set([str(x.get("id")) for x in _json_get_list(bd, "removed")])
        if exp_ids_removed != got_ids_removed:
            diff_ok = False

        exp_ids_clos = set([str(x["id"]) for x in expected_diff["closures"]])
        got_ids_clos = set([str(x.get("id")) for x in _json_get_list(bd, "closures")])
        if exp_ids_clos != got_ids_clos:
            diff_ok = False

        exp_ids_reop = set([str(x["id"]) for x in expected_diff["reopenings"]])
        got_ids_reop = set([str(x.get("id")) for x in _json_get_list(bd, "reopenings")])
        if exp_ids_reop != got_ids_reop:
            diff_ok = False

        scores["business_diff_json_valid"] = 1.0 if diff_ok else 0.0

    # run_log.txt checks
    log_text = _safe_read_text(run_log)
    if log_text is not None:
        lines = log_text.splitlines()
        if lines:
            first = lines[0].strip()
            cmd_ok = False
            if first.startswith("python") and "scripts/generate_update.py" in first:
                required_arg_subs = [
                    "--prev input/businesses_week_prev.csv",
                    "--curr input/businesses_week_curr.csv",
                    "--events input/events.html",
                    "--contacts input/community_contacts.json",
                    "--out-dir output",
                ]
                if all(sub in first for sub in required_arg_subs):
                    cmd_ok = True
            rest = "\n".join(lines[1:])
            summary_ok = False
            if any(p in rest for p in [
                "output/report/weekly_update.md",
                "output/messages/email_draft.txt",
                "output/messages/whatsapp_message.txt",
                "output/structured/business_diff.json"
            ]):
                summary_ok = True
            if expected_diff is not None:
                counts = expected_diff["counts"]
                counts_present = (str(counts["new"]) in rest) and (str(counts["closures"]) in rest)
                summary_ok = summary_ok and counts_present
            scores["run_log_valid"] = 1.0 if (cmd_ok and summary_ok) else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()