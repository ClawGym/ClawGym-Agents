import json
import os
import sys
import csv
from datetime import datetime, timedelta, date

def get_workspace_root():
    if len(sys.argv) > 1 and sys.argv[1]:
        return sys.argv[1]
    return "/root/.openclaw/workspace"

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def normalize_header(header):
    return header.strip().lower()

def read_csv_dicts(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return []
        keys = [normalize_header(h) for h in header]
        for parts in reader:
            # Pad or trim to header length
            if len(parts) < len(keys):
                parts = parts + [""] * (len(keys) - len(parts))
            elif len(parts) > len(keys):
                parts = parts[:len(keys)]
            row = {}
            for i, key in enumerate(keys):
                row[key] = parts[i].strip()
            rows.append(row)
    return rows

def parse_number(val):
    if val is None:
        return 0.0
    s = str(val).strip()
    if s == "":
        return 0.0
    # Remove common currency and thousands markers
    # Keep minus sign and dot
    cleaned = []
    for ch in s:
        if ch.isdigit() or ch in ['.', '-', '+', 'e', 'E']:
            cleaned.append(ch)
        elif ch in [',', '$', '€', '£']:
            continue
        else:
            # skip other symbols/spaces
            continue
    cleaned_s = "".join(cleaned)
    if cleaned_s in ("", "-", "+"):
        return 0.0
    try:
        return float(cleaned_s)
    except ValueError:
        # Fallback: try to remove non-numeric except dot and minus
        try:
            return float("".join([c for c in s if (c.isdigit() or c in ".-")]))
        except Exception:
            return 0.0

def parse_date_yyyy_mm_dd(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d").date()
        return dt
    except ValueError:
        return None

def get_anchor_date(cfg):
    # Prefer 'anchor_date', then 'anchorDate', then 'today', then 'date'
    for key in ["anchor_date", "anchorDate", "today", "date"]:
        if key in cfg:
            d = parse_date_yyyy_mm_dd(str(cfg[key]))
            if d:
                return d
    return None

def build_expected(workspace_root):
    input_dir = os.path.join(workspace_root, "input")
    contacts_path = os.path.join(input_dir, "contacts.csv")
    deals_path = os.path.join(input_dir, "deals.csv")
    config_path = os.path.join(input_dir, "config.json")

    contacts = read_csv_dicts(contacts_path)
    deals = read_csv_dicts(deals_path)
    config = read_json(config_path)

    # Contacts mapping by email (lowercased)
    email_to_name = {}
    for c in contacts:
        email = (c.get("email") or "").strip().lower()
        name = (c.get("name") or "").strip()
        if email and email not in email_to_name:
            email_to_name[email] = name

    # Pipeline stages
    stages = ["prospect", "qualified", "proposal", "negotiation", "closed-won", "closed-lost"]
    stage_counts = {s: 0 for s in stages}
    stage_totals = {s: 0.0 for s in stages}

    # Build tags per deal and followups
    expected_tags_rows = []  # list of (title, normalized_tags)
    followup_lines = []  # list of tuples (due_date, line_str)

    anchor = get_anchor_date(config)
    # window inclusive [anchor, anchor+7]
    if anchor:
        end_date = anchor + timedelta(days=7)
    else:
        end_date = None

    open_stages = set(["prospect", "qualified", "proposal", "negotiation"])

    for d in deals:
        title = (d.get("title") or "").strip()
        stage = (d.get("stage") or "").strip().lower()
        value = parse_number(d.get("value"))

        if stage in stage_counts:
            stage_counts[stage] += 1
            stage_totals[stage] += value

        # tags normalization
        tags_field = d.get("tags") or ""
        parts = [p.strip().lower() for p in tags_field.split(";")] if tags_field != "" else []
        parts = [p for p in parts if p != ""]
        # de-dup and sort
        unique_sorted = sorted(set(parts))
        tags_norm = ";".join(unique_sorted)
        expected_tags_rows.append((title, tags_norm))

        # followups within next 7d for open stages
        if stage in open_stages and anchor is not None:
            due_str = d.get("followup_due") or ""
            due = parse_date_yyyy_mm_dd(due_str)
            if due is not None and anchor <= due <= end_date:
                contact_email = (d.get("contact_email") or "").strip().lower()
                contact_name = email_to_name.get(contact_email)
                if not contact_name or contact_name.strip() == "":
                    # Fallback to email if no match
                    contact_name = d.get("contact_email") or ""
                note = d.get("followup_note") or ""
                line = f"{due.strftime('%Y-%m-%d')} | {title} | {contact_name} | {note}"
                followup_lines.append((due, line))

    # Prepare expected pipeline report
    stages_obj = {s: {"count": stage_counts[s], "total_value": float(stage_totals[s])} for s in stages}
    grand_total_count = sum(stage_counts.values())
    grand_total_value = float(sum(stage_totals.values()))
    expected_pipeline = {
        "stages": stages_obj,
        "grand_total_count": grand_total_count,
        "grand_total_value": grand_total_value
    }

    # Sort expected followups by due date ascending
    followup_lines_sorted = sorted(followup_lines, key=lambda x: (x[0].toordinal(),))
    expected_followups_lines = [line for _, line in followup_lines_sorted]
    expected_followups_header1 = f"Follow-ups due in next 7 days (anchor: {anchor.strftime('%Y-%m-%d') if anchor else ''})"
    expected_followups_header2 = "due_date | deal_title | contact_name | note"

    # Prepare expected tags csv rows sorted by title ascending
    expected_tags_rows_sorted = sorted(expected_tags_rows, key=lambda x: (x[0] or "").lower())

    expected = {
        "pipeline": expected_pipeline,
        "followups": {
            "header1": expected_followups_header1,
            "header2": expected_followups_header2,
            "lines": expected_followups_lines
        },
        "tags": expected_tags_rows_sorted
    }
    return expected

def float_eq(a, b, tol=1e-6):
    return abs(float(a) - float(b)) <= tol

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir not used for scoring, but path kept for completeness
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "pipeline_file_exists": False,
        "pipeline_structure_ok": False,
        "pipeline_counts_values_ok": False,
        "pipeline_grand_totals_ok": False,
        "followups_file_exists": False,
        "followups_header_ok": False,
        "followups_lines_match_set": False,
        "followups_sorted": False,
        "tags_file_exists": False,
        "tags_header_ok": False,
        "tags_rows_ok": False
    }

    # Default reward is 0.0 (no-op baseline)
    try:
        expected = build_expected(workspace_root)
    except Exception:
        # If inputs are unreadable, we cannot compute expectations; keep reward 0
        expected = None

    # 1) pipeline_report.json
    pipeline_path = os.path.join(output_dir, "pipeline_report.json")
    if os.path.isfile(pipeline_path):
        checks["pipeline_file_exists"] = True
        try:
            with open(pipeline_path, "r", encoding="utf-8") as f:
                pipeline_out = json.load(f)
            # Structure: stages (exact six), counts numeric, total_value numeric, grand totals
            stages_required = ["prospect", "qualified", "proposal", "negotiation", "closed-won", "closed-lost"]
            structure_ok = isinstance(pipeline_out, dict) and "stages" in pipeline_out and isinstance(pipeline_out["stages"], dict)
            if structure_ok:
                out_stages_keys = sorted(list(pipeline_out["stages"].keys()))
                structure_ok = (out_stages_keys == sorted(stages_required))
            if structure_ok:
                # validate numeric types and presence
                for s in stages_required:
                    v = pipeline_out["stages"].get(s, {})
                    if not isinstance(v, dict):
                        structure_ok = False
                        break
                    if "count" not in v or "total_value" not in v:
                        structure_ok = False
                        break
                    # ensure numbers
                    if not isinstance(v["count"], (int, float)) or not isinstance(v["total_value"], (int, float)):
                        structure_ok = False
                        break
                if "grand_total_count" not in pipeline_out or "grand_total_value" not in pipeline_out:
                    structure_ok = False
                else:
                    if not isinstance(pipeline_out["grand_total_count"], (int, float)) or not isinstance(pipeline_out["grand_total_value"], (int, float)):
                        structure_ok = False
            checks["pipeline_structure_ok"] = bool(structure_ok)
            if expected and structure_ok:
                # compare per-stage counts and totals
                per_ok = True
                for s in stages_required:
                    exp_c = expected["pipeline"]["stages"][s]["count"]
                    exp_v = expected["pipeline"]["stages"][s]["total_value"]
                    got_c = pipeline_out["stages"][s]["count"]
                    got_v = pipeline_out["stages"][s]["total_value"]
                    if not (int(got_c) == int(exp_c) and float_eq(got_v, exp_v)):
                        per_ok = False
                        break
                checks["pipeline_counts_values_ok"] = per_ok
                # compare grand totals equal to sums across stages and equal to expected
                gt_ok = False
                if per_ok:
                    # compute sums from out
                    sum_c = sum(int(pipeline_out["stages"][s]["count"]) for s in stages_required)
                    sum_v = sum(float(pipeline_out["stages"][s]["total_value"]) for s in stages_required)
                    gt_ok = (int(pipeline_out["grand_total_count"]) == int(sum_c)) and float_eq(pipeline_out["grand_total_value"], sum_v) \
                            and (int(pipeline_out["grand_total_count"]) == int(expected["pipeline"]["grand_total_count"])) \
                            and float_eq(pipeline_out["grand_total_value"], expected["pipeline"]["grand_total_value"])
                checks["pipeline_grand_totals_ok"] = gt_ok
        except Exception:
            # leave checks as is
            pass

    # 2) followups_due_7d.md
    followups_path = os.path.join(output_dir, "followups_due_7d.md")
    if os.path.isfile(followups_path):
        checks["followups_file_exists"] = True
        try:
            with open(followups_path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n").strip() for ln in f.readlines()]
            # Need at least 2 lines (header + columns header)
            header_ok = False
            if expected:
                header1 = expected["followups"]["header1"]
                header2 = expected["followups"]["header2"]
                if len(lines) >= 2 and lines[0] == header1 and lines[1] == header2:
                    header_ok = True
            checks["followups_header_ok"] = header_ok
            if expected and header_ok:
                body_lines = lines[2:] if len(lines) > 2 else []
                # Compare set equality with expected lines
                exp_set = set(expected["followups"]["lines"])
                out_set = set([ln for ln in body_lines if ln != ""])
                checks["followups_lines_match_set"] = (exp_set == out_set)
                # Check sorted by due date ascending
                def extract_date(ln):
                    # Expected format: YYYY-MM-DD | Deal Title | Contact Name | Note
                    # Take first 10 chars
                    if len(ln) >= 10:
                        dstr = ln[:10]
                        try:
                            return datetime.strptime(dstr, "%Y-%m-%d").date()
                        except Exception:
                            return date.min
                    return date.min
                sorted_ok = True
                prev = None
                for ln in body_lines:
                    d = extract_date(ln)
                    if prev is not None and d < prev:
                        sorted_ok = False
                        break
                    prev = d
                checks["followups_sorted"] = sorted_ok
        except Exception:
            pass

    # 3) deal_tags.csv
    tags_path = os.path.join(output_dir, "deal_tags.csv")
    if os.path.isfile(tags_path):
        checks["tags_file_exists"] = True
        try:
            with open(tags_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            header_ok = False
            if rows:
                hdr = [h.strip() for h in rows[0]]
                header_ok = (len(hdr) >= 2 and hdr[0] == "title" and hdr[1] == "tags")
            checks["tags_header_ok"] = header_ok
            if header_ok and expected:
                out_map = {}
                for r in rows[1:]:
                    if not r:
                        continue
                    title = (r[0] if len(r) > 0 else "").strip()
                    tags_val = (r[1] if len(r) > 1 else "").strip()
                    out_map[title] = tags_val
                exp_pairs = expected["tags"]
                # Verify titles set matches exactly and tags match
                titles_ok = set(out_map.keys()) == set([t for (t, _) in exp_pairs])
                tags_ok = titles_ok and all(out_map.get(t, None) == tg for (t, tg) in exp_pairs)
                checks["tags_rows_ok"] = bool(tags_ok)
        except Exception:
            pass

    # Aggregate reward
    pipeline_pass = checks["pipeline_file_exists"] and checks["pipeline_structure_ok"] and checks["pipeline_counts_values_ok"] and checks["pipeline_grand_totals_ok"]
    followups_pass = checks["followups_file_exists"] and checks["followups_header_ok"] and checks["followups_lines_match_set"] and checks["followups_sorted"]
    tags_pass = checks["tags_file_exists"] and checks["tags_header_ok"] and checks["tags_rows_ok"]

    total_pass = sum([1 if pipeline_pass else 0, 1 if followups_pass else 0, 1 if tags_pass else 0])
    reward = total_pass / 3.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()