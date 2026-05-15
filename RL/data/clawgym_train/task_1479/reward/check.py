import os
import sys
import json
import csv
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def file_exists(path):
    return os.path.isfile(path)

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return json.load(f), None
    except Exception as e:
        return None, e

def count_email_entries(text):
    count = 0
    for line in text.splitlines():
        s = line.strip()
        if re.match(r'^(Email|Day)\b', s, flags=re.IGNORECASE):
            count += 1
    return count

def count_lines_starting_with(text, prefix):
    cnt = 0
    for line in text.splitlines():
        if re.match(r'^\s*' + re.escape(prefix) + r'\b', line, flags=re.IGNORECASE):
            cnt += 1
    return cnt

def calendar_header_exact(path, expected_cols):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline().rstrip("\n").rstrip("\r")
            # Normalize potential BOM
            if first_line.startswith("\ufeff"):
                first_line = first_line.lstrip("\ufeff")
            cols = [c.strip() for c in first_line.split(",")]
            return cols == expected_cols
    except Exception:
        return False

def csv_header_contains(path, required_cols):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return False
            header = [h.strip() for h in header]
            return all(col in header for col in required_cols)
    except Exception:
        return False

def csv_count_rows(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return 0
            return sum(1 for _ in reader)
    except Exception:
        return 0

def ab_csv_checks(path):
    ok_header = csv_header_contains(path, ["test_id", "variant", "subject_line", "preview_text", "char_count"])
    at_least_16 = False
    all_char_counts_valid = False
    no_banned = False

    if not ok_header:
        return ok_header, at_least_16, all_char_counts_valid, no_banned

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception:
        return ok_header, at_least_16, all_char_counts_valid, no_banned

    at_least_16 = len(rows) >= 16

    all_char_counts_valid = True
    no_banned = True
    banned_patterns = ["FREE", "Free", "Act now", "ACT NOW", "!!!"]

    for row in rows:
        # char_count check
        try:
            cc = int(str(row.get("char_count", "")).strip())
            if cc > 50:
                all_char_counts_valid = False
        except Exception:
            all_char_counts_valid = False

        subj = str(row.get("subject_line", ""))
        for pat in banned_patterns:
            if pat in subj:
                no_banned = False
                break

    return ok_header, at_least_16, all_char_counts_valid, no_banned

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks dictionary with all checks set to False
    checks = {
        # 1) plan.md checks
        "plan_exists": False,
        "plan_includes_protocols_and_metrics": False,
        "plan_mentions_b2b_days": False,
        "plan_mentions_morning": False,
        "plan_mentions_sunset": False,

        # 2) deliverability checklist checks
        "deliverability_exists": False,
        "deliverability_mentions_protocols_and_ip_warming": False,
        "deliverability_includes_starting_volume_and_20pct": False,

        # 3) segments.json checks
        "segments_exists": False,
        "segments_valid_json": False,
        "segments_has_required_keys": False,
        "segments_all_have_criteria": False,
        "segments_unengaged_mentions_open_or_click": False,
        "sunset_policy_days_at_least_90": False,

        # 4) welcome_sequence.md checks
        "welcome_exists": False,
        "welcome_email_count_5_to_7": False,
        "welcome_at_least_5_subjects": False,
        "welcome_at_least_5_previews": False,

        # 5) reengagement.md checks
        "reengagement_exists": False,
        "reengagement_at_least_3_emails": False,

        # 6) ab_testing/subject_tests.csv checks
        "ab_exists": False,
        "ab_header_contains_required_columns": False,
        "ab_at_least_16_rows": False,
        "ab_all_char_counts_valid": False,
        "ab_no_banned_patterns": False,

        # 7) schedule/send_calendar.csv
        "calendar_exists": False,
        "calendar_header_exact": False,
        "calendar_at_least_12_rows": False,

        # 8) compliance.md
        "compliance_exists": False,
        "compliance_contains_required_phrases": False,
    }

    # 1) plan.md
    plan_path = os.path.join(output_dir, "strategy", "plan.md")
    if file_exists(plan_path):
        checks["plan_exists"] = True
        plan_text = read_text(plan_path)
        plan_lc = plan_text.lower()

        req_phrases = [
            "spf", "dkim", "dmarc", "ip warming",
            "open rate >20%", "click rate >2%", "bounce rate <2%",
            "unsubscribe <0.5%", "complaints <0.1%"
        ]
        if all(p in plan_lc for p in req_phrases):
            checks["plan_includes_protocols_and_metrics"] = True

        # Mentions weekday timing suitable for B2B: at least one of Tuesday/Wednesday/Thursday
        weekdays = ["tuesday", "wednesday", "thursday"]
        if any(d in plan_lc for d in weekdays):
            checks["plan_mentions_b2b_days"] = True

        # Mentions morning or mid-morning
        if ("morning" in plan_lc) or ("mid-morning" in plan_lc) or ("mid morning" in plan_lc):
            checks["plan_mentions_morning"] = True

        # Mentions sunset policy
        if ("sunset policy" in plan_lc) or ("sunset" in plan_lc):
            checks["plan_mentions_sunset"] = True

    # 2) deliverability checklist
    deliver_path = os.path.join(output_dir, "deliverability", "dkim_spf_dmarc.txt")
    if file_exists(deliver_path):
        checks["deliverability_exists"] = True
        d_text = read_text(deliver_path)
        d_lc = d_text.lower()
        if all(k in d_lc for k in ["spf", "dkim", "dmarc", "ip warming"]):
            checks["deliverability_mentions_protocols_and_ip_warming"] = True
        # contains numeric starting volume of either "50" or "100" and includes "20%"
        has_50_or_100 = ("50" in d_text) or ("100" in d_text)
        has_20pct = "20%" in d_text
        if has_50_or_100 and has_20pct:
            checks["deliverability_includes_starting_volume_and_20pct"] = True

    # 3) segments.json
    segments_path = os.path.join(output_dir, "segments", "segments.json")
    if file_exists(segments_path):
        checks["segments_exists"] = True
        seg_json, seg_err = load_json(segments_path)
        if seg_json is not None and isinstance(seg_json, dict):
            checks["segments_valid_json"] = True
            required_keys = ["new_subscribers", "engaged_30d", "unengaged_90d", "customers", "vip", "sunset_policy"]
            if all(k in seg_json for k in required_keys):
                checks["segments_has_required_keys"] = True

                # criteria checks for each segment (excluding sunset_policy)
                segment_keys_for_criteria = ["new_subscribers", "engaged_30d", "unengaged_90d", "customers", "vip"]
                all_have_criteria = True
                for sk in segment_keys_for_criteria:
                    val = seg_json.get(sk)
                    if not isinstance(val, dict) or "criteria" not in val or not isinstance(val.get("criteria"), dict):
                        all_have_criteria = False
                        break
                if all_have_criteria:
                    checks["segments_all_have_criteria"] = True

                # unengaged_90d mentions last_open_date or last_click_date in criteria
                uneng = seg_json.get("unengaged_90d", {})
                crit = uneng.get("criteria", {}) if isinstance(uneng, dict) else {}
                crit_text = json.dumps(crit).lower() if isinstance(crit, dict) else ""
                if ("last_open_date" in crit_text) or ("last_click_date" in crit_text):
                    checks["segments_unengaged_mentions_open_or_click"] = True

                # sunset_policy days >= 90
                sp = seg_json.get("sunset_policy", {})
                days_ok = False
                if isinstance(sp, dict) and "days" in sp:
                    try:
                        days_val = sp.get("days")
                        # accept int-like or float-like strings
                        if isinstance(days_val, (int, float)):
                            days_ok = days_val >= 90
                        else:
                            days_ok = float(str(days_val)) >= 90
                    except Exception:
                        days_ok = False
                if days_ok:
                    checks["sunset_policy_days_at_least_90"] = True

    # 4) welcome_sequence.md
    welcome_path = os.path.join(output_dir, "sequences", "welcome_sequence.md")
    if file_exists(welcome_path):
        checks["welcome_exists"] = True
        w_text = read_text(welcome_path)
        entry_count = count_email_entries(w_text)
        if 5 <= entry_count <= 7:
            checks["welcome_email_count_5_to_7"] = True
        subj_count = count_lines_starting_with(w_text, "Subject")
        if subj_count >= 5:
            checks["welcome_at_least_5_subjects"] = True
        prev_count = count_lines_starting_with(w_text, "Preview")
        if prev_count >= 5:
            checks["welcome_at_least_5_previews"] = True

    # 5) reengagement.md
    reeng_path = os.path.join(output_dir, "sequences", "reengagement.md")
    if file_exists(reeng_path):
        checks["reengagement_exists"] = True
        r_text = read_text(reeng_path)
        r_count = count_email_entries(r_text)
        if r_count >= 3:
            checks["reengagement_at_least_3_emails"] = True

    # 6) ab_testing/subject_tests.csv
    ab_path = os.path.join(output_dir, "ab_testing", "subject_tests.csv")
    if file_exists(ab_path):
        checks["ab_exists"] = True
        ok_header, at_least_16, all_char_counts_valid, no_banned = ab_csv_checks(ab_path)
        if ok_header:
            checks["ab_header_contains_required_columns"] = True
        if at_least_16:
            checks["ab_at_least_16_rows"] = True
        if all_char_counts_valid:
            checks["ab_all_char_counts_valid"] = True
        if no_banned:
            checks["ab_no_banned_patterns"] = True

    # 7) schedule/send_calendar.csv
    calendar_path = os.path.join(output_dir, "schedule", "send_calendar.csv")
    if file_exists(calendar_path):
        checks["calendar_exists"] = True
        expected_header = ["date", "local_time", "segment", "campaign_name", "timezone"]
        if calendar_header_exact(calendar_path, expected_header):
            checks["calendar_header_exact"] = True
        row_count = csv_count_rows(calendar_path)
        if row_count >= 12:
            checks["calendar_at_least_12_rows"] = True

    # 8) compliance.md
    compliance_path = os.path.join(output_dir, "checklist", "compliance.md")
    if file_exists(compliance_path):
        checks["compliance_exists"] = True
        c_text = read_text(compliance_path)
        c_lc = c_text.lower()
        needed = ["physical address", "one-click unsubscribe", "can-spam", "gdpr", "opt-outs"]
        if all(term in c_lc for term in needed):
            checks["compliance_contains_required_phrases"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or empty, force reward 0.0
    if not os.path.isdir(output_dir) or not any(True for _ in os.scandir(output_dir)):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()