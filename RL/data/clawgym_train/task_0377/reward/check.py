import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_csv_dicts(path: Path) -> Optional[List[dict]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            normalized = []
            for r in rows:
                normalized.append({(k.strip() if isinstance(k, str) else k): (v if v is not None else "") for k, v in r.items()})
            return normalized
    except Exception:
        return None


def parse_allowed_html(path: Path) -> Optional[Dict[str, List[str]]]:
    html = read_text_safe(path)
    if html is None:
        return None
    table_match = re.search(r'<table[^>]*id=["\']rules["\'][^>]*>(.*?)</table>', html, flags=re.S | re.I)
    if not table_match:
        return None
    table_html = table_match.group(1)
    rows = re.findall(r"<tr>(.*?)</tr>", table_html, flags=re.S | re.I)
    if not rows:
        return None
    mapping: Dict[str, List[str]] = {}
    for row_html in rows[1:]:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.S | re.I)
        if len(tds) != 2:
            continue
        consult_type = re.sub(r"<.*?>", "", tds[0], flags=re.S).strip()
        placeholders_csv = re.sub(r"<.*?>", "", tds[1], flags=re.S).strip()
        placeholders = [p.strip() for p in placeholders_csv.split(",") if p.strip()]
        if consult_type:
            mapping[consult_type] = placeholders
    if not mapping:
        return None
    return mapping


def extract_templates(path: Path) -> Optional[Dict[str, str]]:
    content = read_text_safe(path)
    if content is None:
        return None
    templates: Dict[str, str] = {}
    lines = content.splitlines()
    current_name = None
    buffer: List[str] = []
    tmpl_re = re.compile(r"^\s*===\s*TEMPLATE:\s*([a-zA-Z0-9_\-]+)\s*===\s*$")
    for line in lines:
        m = tmpl_re.match(line)
        if m:
            if current_name is not None:
                templates[current_name] = "\n".join(buffer).strip()
            current_name = m.group(1).strip()
            buffer = []
        else:
            if current_name is not None:
                buffer.append(line)
    if current_name is not None:
        templates[current_name] = "\n".join(buffer).strip()
    if not templates:
        return None
    return templates


def find_placeholders_in_text(text: str) -> List[str]:
    return re.findall(r"\{([a-zA-Z0-9_]+)\}", text)


def unique_sorted_semicolon(items: List[str]) -> str:
    uniq = sorted(set(items))
    return ";".join(uniq)


def format_ratio(numer: int, denom: int) -> str:
    if denom == 0:
        return "0.00"
    val = round(numer / denom + 0.0, 2)
    return f"{val:.2f}"


def safe_word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "allowed_placeholders_json_parse": 0.0,
        "allowed_placeholders_json_matches_table": 0.0,
        "messages_files_reminder_exist": 0.0,
        "messages_files_summary_exist": 0.0,
        "messages_no_curly_braces": 0.0,
        "messages_word_limit": 0.0,
        "messages_no_disallowed_values_leak": 0.0,
        "messages_include_allowed_template_values": 0.0,
        "compliance_report_parse": 0.0,
        "compliance_report_expected_rows": 0.0,
        "compliance_report_values_correct": 0.0,
    }

    html_rules_path = workspace / "input" / "policies" / "allowed_fields.html"
    appointments_csv_path = workspace / "input" / "data" / "appointments.csv"
    templates_path = workspace / "input" / "templates" / "patient_messages.txt"

    allowed_json_path = workspace / "output" / "allowed_placeholders.json"
    messages_dir = workspace / "output" / "messages"
    compliance_report_path = workspace / "output" / "compliance_report.csv"

    expected_allowed = parse_allowed_html(html_rules_path)
    appointments = read_csv_dicts(appointments_csv_path)
    templates = extract_templates(templates_path)

    allowed_json = read_json_safe(allowed_json_path)
    if isinstance(allowed_json, dict):
        scores["allowed_placeholders_json_parse"] = 1.0

    if expected_allowed is not None and isinstance(allowed_json, dict):
        exp_keys = set(expected_allowed.keys())
        got_keys = set(allowed_json.keys())
        if not exp_keys:
            scores["allowed_placeholders_json_matches_table"] = 0.0
        else:
            key_union = exp_keys.union(got_keys)
            per_key_scores = []
            for k in key_union:
                exp_set = set(expected_allowed.get(k, []))
                got_val = allowed_json.get(k, None)
                got_set = set(got_val) if isinstance(got_val, list) else set()
                per_key_scores.append(1.0 if (k in exp_keys and k in got_keys and exp_set == got_set) else 0.0)
            scores["allowed_placeholders_json_matches_table"] = sum(per_key_scores) / len(per_key_scores) if per_key_scores else 0.0

    template_placeholders: Dict[str, List[str]] = {}
    if templates is not None:
        for name, text in templates.items():
            template_placeholders[name] = find_placeholders_in_text(text)

    appointment_ids: List[str] = []
    consult_types_by_id: Dict[str, str] = {}
    if appointments:
        for row in appointments:
            aid = (row.get("appointment_id", "") or "").strip()
            ctype = (row.get("consult_type", "") or "").strip()
            if aid:
                appointment_ids.append(aid)
                consult_types_by_id[aid] = ctype

    total_expected_msgs_reminder = 0
    total_found_msgs_reminder = 0
    total_expected_msgs_summary = 0
    total_found_msgs_summary = 0

    all_message_paths: List[Tuple[str, str, Path]] = []

    if appointment_ids:
        for aid in appointment_ids:
            p_rem = messages_dir / f"{aid}_reminder.txt"
            total_expected_msgs_reminder += 1
            if p_rem.exists():
                total_found_msgs_reminder += 1
                all_message_paths.append((aid, "reminder", p_rem))
            p_sum = messages_dir / f"{aid}_summary.txt"
            total_expected_msgs_summary += 1
            if p_sum.exists():
                total_found_msgs_summary += 1
                all_message_paths.append((aid, "summary", p_sum))

    scores["messages_files_reminder_exist"] = (total_found_msgs_reminder / total_expected_msgs_reminder) if total_expected_msgs_reminder > 0 else 0.0
    scores["messages_files_summary_exist"] = (total_found_msgs_summary / total_expected_msgs_summary) if total_expected_msgs_summary > 0 else 0.0

    no_braces_pass = 0
    word_limit_pass = 0
    no_leak_pass = 0
    include_allowed_pass = 0
    total_msgs = len(all_message_paths)

    appt_by_id: Dict[str, dict] = {}
    if appointments:
        for row in appointments:
            aid = (row.get("appointment_id", "") or "").strip()
            if aid:
                appt_by_id[aid] = row

    placeholders_by_template: Dict[str, List[str]] = template_placeholders if template_placeholders else {}

    allowed_map: Dict[str, List[str]] = {}
    if isinstance(allowed_json, dict):
        for k, v in allowed_json.items():
            if isinstance(v, list):
                normalized_vals: List[str] = []
                for x in v:
                    if isinstance(x, str):
                        normalized_vals.append(x)
                    elif isinstance(x, (int, float)):
                        normalized_vals.append(str(x))
                allowed_map[str(k)] = normalized_vals

    for aid, tname, path in all_message_paths:
        content = read_text_safe(path) or ""
        if "{" not in content and "}" not in content:
            no_braces_pass += 1
        if safe_word_count(content) <= 120:
            word_limit_pass += 1

        row = appt_by_id.get(aid, {})
        consult_type = consult_types_by_id.get(aid, "")
        allowed_placeholders = set(allowed_map.get(consult_type, []))
        t_placeholders = set(placeholders_by_template.get(tname, []))

        allowed_used_in_template = t_placeholders.intersection(allowed_placeholders)
        disallowed_used_in_template = t_placeholders.difference(allowed_placeholders)

        leak_found = False
        for ph in disallowed_used_in_template:
            val = (row.get(ph, "") or "").strip()
            if val and val in content:
                leak_found = True
                break
        if not leak_found:
            no_leak_pass += 1

        include_ok = True
        for ph in allowed_used_in_template:
            val = (row.get(ph, "") or "").strip()
            if val and val not in content:
                include_ok = False
                break
        if include_ok:
            include_allowed_pass += 1

    scores["messages_no_curly_braces"] = (no_braces_pass / total_msgs) if total_msgs > 0 else 0.0
    scores["messages_word_limit"] = (word_limit_pass / total_msgs) if total_msgs > 0 else 0.0
    scores["messages_no_disallowed_values_leak"] = (no_leak_pass / total_msgs) if total_msgs > 0 else 0.0
    scores["messages_include_allowed_template_values"] = (include_allowed_pass / total_msgs) if total_msgs > 0 else 0.0

    compliance_rows = None
    try:
        if (compliance_report_path).exists():
            compliance_rows = read_csv_dicts(compliance_report_path)
    except Exception:
        compliance_rows = None

    if isinstance(compliance_rows, list) and len(compliance_rows) > 0:
        required_cols = [
            "appointment_id",
            "consult_type",
            "template_name",
            "original_used_placeholders",
            "disallowed_placeholders",
            "allowed_used_count",
            "disallowed_used_count",
            "minimum_necessary_ratio",
            "compliance_status",
        ]
        if all(all(col in r for col in required_cols) for r in compliance_rows):
            scores["compliance_report_parse"] = 1.0

    if appointments and templates and expected_allowed:
        expected_map = expected_allowed
        tnames = sorted(templates.keys())
        tmpl_ph_sets: Dict[str, set] = {name: set(find_placeholders_in_text(templates[name])) for name in tnames}

        expected_records: Dict[Tuple[str, str], dict] = {}
        for row in appointments:
            aid = (row.get("appointment_id", "") or "").strip()
            ctype = (row.get("consult_type", "") or "").strip()
            if not aid:
                continue
            for tname in tnames:
                ph_set = tmpl_ph_sets.get(tname, set())
                allowed_set = set(expected_map.get(ctype, []))
                original_used = sorted(ph_set)
                disallowed = sorted([p for p in ph_set if p not in allowed_set])
                allowed_used = sorted([p for p in ph_set if p in allowed_set])
                allowed_count = len(set(allowed_used))
                disallowed_count = len(set(disallowed))
                ratio = format_ratio(allowed_count, allowed_count + disallowed_count)
                status = "PASS" if disallowed_count == 0 else "FAIL"
                expected_records[(aid, tname)] = {
                    "appointment_id": aid,
                    "consult_type": ctype,
                    "template_name": tname,
                    "original_used_placeholders": ";".join(sorted(set(original_used))),
                    "disallowed_placeholders": ";".join(sorted(set(disallowed))),
                    "allowed_used_count": str(allowed_count),
                    "disallowed_used_count": str(disallowed_count),
                    "minimum_necessary_ratio": ratio,
                    "compliance_status": status,
                }

        if isinstance(compliance_rows, list) and compliance_rows:
            found_keys = set(( (r.get("appointment_id", "") or "").strip(), (r.get("template_name", "") or "").strip()) for r in compliance_rows)
            expected_keys = set(expected_records.keys())
            if expected_keys:
                scores["compliance_report_expected_rows"] = len(found_keys.intersection(expected_keys)) / len(expected_keys)
            else:
                scores["compliance_report_expected_rows"] = 0.0

            correct_count = 0
            total_needed = len(expected_keys)
            for key, expected_vals in expected_records.items():
                if key not in found_keys:
                    continue
                for r in compliance_rows:
                    if ((r.get("appointment_id", "") or "").strip(), (r.get("template_name", "") or "").strip()) == key:
                        ok = True
                        for col in [
                            "appointment_id",
                            "consult_type",
                            "template_name",
                            "original_used_placeholders",
                            "disallowed_placeholders",
                            "allowed_used_count",
                            "disallowed_used_count",
                            "compliance_status",
                        ]:
                            got = (r.get(col, "") or "").strip()
                            if got != expected_vals[col]:
                                ok = False
                                break
                        if ok:
                            got_ratio_str = (r.get("minimum_necessary_ratio", "") or "").strip()
                            try:
                                got_ratio_val = float(got_ratio_str)
                                exp_ratio_val = float(expected_vals["minimum_necessary_ratio"])
                                if round(got_ratio_val, 2) != round(exp_ratio_val, 2):
                                    ok = False
                                # Also require formatting to two decimals
                                if got_ratio_str != f"{round(got_ratio_val,2):.2f}":
                                    ok = False
                            except Exception:
                                ok = False
                        if ok:
                            correct_count += 1
                        break
            scores["compliance_report_values_correct"] = (correct_count / total_needed) if total_needed > 0 else 0.0
        else:
            scores["compliance_report_expected_rows"] = 0.0
            scores["compliance_report_values_correct"] = 0.0
    else:
        scores["compliance_report_expected_rows"] = 0.0
        scores["compliance_report_values_correct"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()