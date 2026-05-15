import json
import os
import re
import sys
from datetime import datetime
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_backlog_ids_titles(path):
    ids = set()
    titles = {}
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rid = (row.get("id") or "").strip()
                title = (row.get("title") or "").strip()
                if rid:
                    ids.add(rid)
                    if title:
                        titles[rid] = title
    except Exception:
        pass
    return ids, titles

def extract_okr_keys_from_yaml(text):
    if not text:
        return set()
    keys = set()
    # Capture tokens like OBJxxx or KRxxx anywhere in the text (word boundaries)
    for m in re.finditer(r'\b(OBJ[a-zA-Z0-9_-]+|KR[a-zA-Z0-9_-]+)\b', text):
        keys.add(m.group(1))
    # Also capture top-level YAML keys that start with OBJ/KR (lines like "OBJ1:" or "KR2:")
    for line in text.splitlines():
        m = re.match(r'^\s*([A-Za-z0-9_-]+)\s*:', line)
        if m:
            k = m.group(1)
            if k.upper().startswith("OBJ") or k.upper().startswith("KR"):
                keys.add(k)
    return keys

def is_time_hhmm(s):
    if not isinstance(s, str):
        return False
    return re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', s) is not None

def hhmm_to_minutes(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)

def is_date_yyyy_mm_dd(s):
    if not isinstance(s, str):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

def find_section(text, header, all_headers):
    # Return the content of the section named 'header' (case-insensitive),
    # delimited by the next header occurrence or end of text.
    lines = text.splitlines()
    header_indices = []
    for idx, line in enumerate(lines):
        if line.strip().lower() == header.lower():
            header_indices.append(idx)
        else:
            # also consider markdown heading with hashes
            stripped = line.strip().lstrip("#").strip()
            if stripped.lower() == header.lower():
                header_indices.append(idx)
    if not header_indices:
        return ""
    start_idx = header_indices[0] + 1
    # Find next header among all headers (case-insensitive)
    next_idx = len(lines)
    for idx in range(start_idx, len(lines)):
        candidate = lines[idx].strip().lstrip("#").strip().lower()
        if candidate in {h.lower() for h in all_headers}:
            next_idx = idx
            break
    return "\n".join(lines[start_idx:next_idx])

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Prepare checks dictionary initialized to False
    checks = {
        # weekly_plan.json existence and validity
        "json_exists": False,
        "json_valid": False,
        "json_has_required_keys": False,
        # top_priorities checks
        "top_priorities_len_3": False,
        "top_priorities_fields_valid": False,
        "top_priorities_ids_exist_in_backlog": False,
        "top_priorities_aligned_okrs_exist": False,
        # schedule checks
        "schedule_len_7": False,
        "schedule_unique_dates": False,
        "schedule_each_day_blocks_ge_2": False,
        "schedule_time_format_and_order": False,
        "schedule_no_overlaps": False,
        "schedule_blocks_have_label_or_task": False,
        # risks checks
        "risks_len_ge_3": False,
        "risks_fields_valid": False,
        # assumptions checks
        "assumptions_len_ge_2": False,
        "assumptions_non_empty": False,
        # summary.md checks
        "summary_exists": False,
        "summary_has_sections": False,
        "summary_checklist_ge_5": False,
        "summary_fallbacks_ge_2": False,
        # cross-file consistency
        "cross_titles_present_in_summary": False,
    }

    # Load reference inputs
    backlog_csv = os.path.join(input_dir, "backlog.csv")
    okr_yaml = os.path.join(input_dir, "okr.yaml")
    backlog_ids, backlog_titles = load_backlog_ids_titles(backlog_csv)
    okr_text = read_text(okr_yaml)
    okr_keys = extract_okr_keys_from_yaml(okr_text) if okr_text else set()

    # Paths to outputs
    weekly_plan_path = os.path.join(output_dir, "weekly_plan.json")
    summary_md_path = os.path.join(output_dir, "summary.md")

    weekly_plan = None
    if os.path.isfile(weekly_plan_path):
        checks["json_exists"] = True
        try:
            with open(weekly_plan_path, "r", encoding="utf-8") as f:
                weekly_plan = json.load(f)
            checks["json_valid"] = isinstance(weekly_plan, dict)
        except Exception:
            checks["json_valid"] = False

    # If JSON valid, proceed with structural checks
    if checks["json_valid"]:
        has_keys = all(k in weekly_plan for k in ["top_priorities", "schedule", "risks", "assumptions"])
        checks["json_has_required_keys"] = has_keys

        # top_priorities
        tp_ok_len = False
        tp_fields_valid = False
        tp_ids_ok = False
        tp_okrs_ok = False

        tps = weekly_plan.get("top_priorities", [])
        if isinstance(tps, list) and len(tps) == 3:
            tp_ok_len = True
            # Validate fields
            fields_valid_all = True
            ids_exist_all = True
            okrs_exist_all = True
            for item in tps:
                if not isinstance(item, dict):
                    fields_valid_all = False
                    ids_exist_all = False
                    okrs_exist_all = False
                    break
                id_val = item.get("id")
                title_val = item.get("title")
                rationale_val = item.get("rationale")
                aligned_okrs_val = item.get("aligned_okrs")

                if not (isinstance(id_val, str) and id_val.strip()):
                    fields_valid_all = False
                if not (isinstance(title_val, str) and title_val.strip()):
                    fields_valid_all = False
                if not (isinstance(rationale_val, str) and len(rationale_val.strip()) >= 30):
                    fields_valid_all = False
                if not (isinstance(aligned_okrs_val, list) and len(aligned_okrs_val) >= 1 and all(isinstance(x, str) and x.strip() for x in aligned_okrs_val)):
                    fields_valid_all = False

                # IDs exist in backlog
                if not (isinstance(id_val, str) and id_val in backlog_ids):
                    ids_exist_all = False
                # OKR keys exist
                if isinstance(aligned_okrs_val, list):
                    if not okr_keys:
                        okrs_exist_all = False
                    else:
                        for ok in aligned_okrs_val:
                            if ok not in okr_keys:
                                okrs_exist_all = False
                                break
                else:
                    okrs_exist_all = False

            tp_fields_valid = fields_valid_all
            tp_ids_ok = ids_exist_all
            tp_okrs_ok = okrs_exist_all

        checks["top_priorities_len_3"] = tp_ok_len
        checks["top_priorities_fields_valid"] = tp_fields_valid
        checks["top_priorities_ids_exist_in_backlog"] = tp_ids_ok
        checks["top_priorities_aligned_okrs_exist"] = tp_okrs_ok

        # schedule
        sched = weekly_plan.get("schedule", [])
        sched_len_ok = isinstance(sched, list) and len(sched) == 7
        checks["schedule_len_7"] = sched_len_ok

        unique_dates_ok = False
        each_day_blocks_ge_2 = False
        time_format_and_order_ok = False
        no_overlaps_ok = False
        blocks_have_label_or_task_ok = False

        if isinstance(sched, list) and len(sched) >= 1:
            dates = []
            blocks_count_ok = True
            time_fmt_order_ok_all = True
            no_overlaps_all = True
            label_or_task_all = True

            for day in sched:
                if not isinstance(day, dict):
                    time_fmt_order_ok_all = False
                    no_overlaps_all = False
                    label_or_task_all = False
                    blocks_count_ok = False
                    continue
                date_str = day.get("date")
                blocks = day.get("blocks")
                dates.append(date_str)
                if not (isinstance(blocks, list) and len(blocks) >= 2):
                    blocks_count_ok = False
                # Date validity
                if not (isinstance(date_str, str) and is_date_yyyy_mm_dd(date_str)):
                    time_fmt_order_ok_all = False  # tie to schedule validity context

                # Validate block times and order and overlaps
                prev_start = None
                prev_end = None
                for b in (blocks if isinstance(blocks, list) else []):
                    if not isinstance(b, dict):
                        time_fmt_order_ok_all = False
                        no_overlaps_all = False
                        label_or_task_all = False
                        continue
                    start = b.get("start")
                    end = b.get("end")
                    has_task_or_label = False
                    label_val = b.get("label")
                    task_id_val = b.get("task_id")
                    if (isinstance(label_val, str) and label_val.strip()) or (isinstance(task_id_val, str) and task_id_val.strip()):
                        has_task_or_label = True
                    else:
                        label_or_task_all = False

                    if not (isinstance(start, str) and isinstance(end, str) and is_time_hhmm(start) and is_time_hhmm(end)):
                        time_fmt_order_ok_all = False
                        no_overlaps_all = False
                        continue
                    start_m = hhmm_to_minutes(start)
                    end_m = hhmm_to_minutes(end)
                    if not (start_m < end_m):
                        time_fmt_order_ok_all = False
                        no_overlaps_all = False
                        continue
                    # Non-decreasing order by start time
                    if prev_start is not None and start_m < prev_start:
                        time_fmt_order_ok_all = False
                    # No overlaps (current start >= previous end)
                    if prev_end is not None and start_m < prev_end:
                        no_overlaps_all = False
                    prev_start = start_m
                    prev_end = end_m

            if sched_len_ok:
                unique_dates_ok = len(dates) == 7 and len({d for d in dates if isinstance(d, str)}) == 7 and all(is_date_yyyy_mm_dd(d) for d in dates if isinstance(d, str))

            each_day_blocks_ge_2 = blocks_count_ok
            time_format_and_order_ok = time_fmt_order_ok_all
            no_overlaps_ok = no_overlaps_all
            blocks_have_label_or_task_ok = label_or_task_all

        checks["schedule_unique_dates"] = unique_dates_ok
        checks["schedule_each_day_blocks_ge_2"] = each_day_blocks_ge_2
        checks["schedule_time_format_and_order"] = time_format_and_order_ok
        checks["schedule_no_overlaps"] = no_overlaps_ok
        checks["schedule_blocks_have_label_or_task"] = blocks_have_label_or_task_ok

        # risks
        risks = weekly_plan.get("risks", [])
        risks_len_ok = isinstance(risks, list) and len(risks) >= 3
        checks["risks_len_ge_3"] = risks_len_ok
        risks_fields_ok = False
        if isinstance(risks, list) and len(risks) >= 1:
            valid_all = True
            for r in risks:
                if not isinstance(r, dict):
                    valid_all = False
                    break
                desc = r.get("description")
                impact = r.get("impact")
                mitigation = r.get("mitigation")
                if not (isinstance(desc, str) and desc.strip()):
                    valid_all = False
                if not (isinstance(mitigation, str) and mitigation.strip()):
                    valid_all = False
                if impact not in ("low", "medium", "high"):
                    valid_all = False
            risks_fields_ok = valid_all
        checks["risks_fields_valid"] = risks_fields_ok

        # assumptions
        assumptions = weekly_plan.get("assumptions", [])
        assumptions_len_ok = isinstance(assumptions, list) and len(assumptions) >= 2
        checks["assumptions_len_ge_2"] = assumptions_len_ok
        assumptions_non_empty_ok = False
        if isinstance(assumptions, list) and len(assumptions) >= 1:
            assumptions_non_empty_ok = all(isinstance(a, str) and a.strip() for a in assumptions)
        checks["assumptions_non_empty"] = assumptions_non_empty_ok

    # summary.md checks
    summary_text = None
    if os.path.isfile(summary_md_path):
        checks["summary_exists"] = True
        summary_text = read_text(summary_md_path)

    required_headers = ["Top 3 Priorities", "Risks & Mitigations", "Assumptions", "Verification checklist", "Fallbacks"]
    if summary_text is not None:
        has_all = True
        for h in required_headers:
            if re.search(r'^\s*#*\s*' + re.escape(h) + r'\s*$', summary_text, flags=re.IGNORECASE | re.MULTILINE) is None:
                has_all = False
                break
        checks["summary_has_sections"] = has_all

        # Count checklist items within the "Verification checklist" section
        verification_section = find_section(summary_text, "Verification checklist", required_headers)
        checklist_count = 0
        for line in verification_section.splitlines():
            if re.match(r'^\s*-\s\[\s\]\s', line):
                checklist_count += 1
        checks["summary_checklist_ge_5"] = checklist_count >= 5

        # Count fallback bullet points within the "Fallbacks" section
        fallbacks_section = find_section(summary_text, "Fallbacks", required_headers)
        fallbacks_count = 0
        for line in fallbacks_section.splitlines():
            if re.match(r'^\s*-\s', line) or re.match(r'^\s*\*\s', line):
                fallbacks_count += 1
        checks["summary_fallbacks_ge_2"] = fallbacks_count >= 2

        # Cross-file consistency: titles present in summary
        titles_present = False
        if weekly_plan and isinstance(weekly_plan, dict):
            tps = weekly_plan.get("top_priorities", [])
            if isinstance(tps, list) and len(tps) == 3:
                titles = []
                for item in tps:
                    title_val = item.get("title") if isinstance(item, dict) else None
                    if isinstance(title_val, str) and title_val.strip():
                        titles.append(title_val.strip())
                if len(titles) == 3:
                    all_found = True
                    s_lower = summary_text.lower()
                    for t in titles:
                        if t.lower() not in s_lower:
                            all_found = False
                            break
                    titles_present = all_found
        checks["cross_titles_present_in_summary"] = titles_present

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or both outputs missing, reward should be 0.0
    if not os.path.isdir(output_dir):
        reward = 0.0
    else:
        if not os.path.isfile(weekly_plan_path) and not os.path.isfile(summary_md_path):
            reward = 0.0

    # Print final JSON result
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()