import json
import os
import re
import sys

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def is_nonempty_string(value):
    return isinstance(value, str) and value.strip() != ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Presence checks for required artifacts
        "has_sequence_plan": False,
        "schedule_exists": False,
        "metrics_exists": False,
        "copy_dir_exists_and_files": False,

        # sequence_plan.json structure/content checks
        "sequence_plan_json_valid": False,
        "sequence_top_level_fields": False,
        "emails_count_is_7": False,
        "email_numbers_correct": False,
        "subjects_length_valid_all": False,
        "email1_send_immediate": False,
        "email7_cta_has_demo_or_book": False,
        "has_case_study_email": False,
        "cta_links_valid": False,
        "body_structure_valid": False,
        "trigger_mentions_report": False,

        # copy files checks
        "copy_files_named_correctly": False,
        "copy_files_sections_present": False,
        "copy_subjects_previews_match": False,

        # schedule.tsv checks
        "schedule_header_valid": False,
        "schedule_rows_count_7": False,
        "schedule_numbers_correct": False,
        "schedule_offsets_valid": False,
        "schedule_subjects_match": False,

        # metrics_plan.json checks
        "metrics_json_valid": False,
        "metrics_overall_kpis_present": False,
        "metrics_per_email_valid": False,
    }

    # Paths
    seq_path = os.path.join(output_dir, "sequence_plan.json")
    schedule_path = os.path.join(output_dir, "schedule.tsv")
    metrics_path = os.path.join(output_dir, "metrics_plan.json")
    copy_dir = os.path.join(output_dir, "copy")

    # Presence checks
    if os.path.isfile(seq_path):
        checks["has_sequence_plan"] = True
    if os.path.isfile(schedule_path):
        checks["schedule_exists"] = True
    if os.path.isfile(metrics_path):
        checks["metrics_exists"] = True
    if os.path.isdir(copy_dir):
        # must contain at least one md per E1_..E7_
        try:
            files = os.listdir(copy_dir)
            have_all = True
            for i in range(1, 8):
                prefix = f"E{i}_"
                if not any(name.startswith(prefix) and name.endswith(".md") for name in files):
                    have_all = False
                    break
            checks["copy_dir_exists_and_files"] = have_all
        except Exception:
            checks["copy_dir_exists_and_files"] = False

    # Initialize containers for cross-file validations
    subjects_by_num = {}
    previews_by_num = {}
    send_by_num = {}
    cta_text_by_num = {}
    cta_link_by_num = {}
    body_by_num = {}

    # Validate sequence_plan.json
    if checks["has_sequence_plan"]:
        seq_json, err = read_json_file(seq_path)
        if seq_json is not None and err is None:
            checks["sequence_plan_json_valid"] = True
            # Top-level fields
            required_top = ["sequence_name", "trigger", "goal", "length", "timing", "exit_conditions", "emails"]
            top_ok = True
            for k in required_top:
                if k not in seq_json:
                    top_ok = False
                    break
            # Types
            if top_ok:
                if not is_nonempty_string(seq_json.get("sequence_name", "")):
                    top_ok = False
                if not is_nonempty_string(seq_json.get("trigger", "")):
                    top_ok = False
                if not is_nonempty_string(seq_json.get("goal", "")):
                    top_ok = False
                if not isinstance(seq_json.get("length", None), (int, float)):
                    top_ok = False
                timing_val = seq_json.get("timing", None)
                if not (isinstance(timing_val, str) or isinstance(timing_val, dict)):
                    top_ok = False
                exit_val = seq_json.get("exit_conditions", None)
                if not (isinstance(exit_val, str) or isinstance(exit_val, list)):
                    top_ok = False
                if not isinstance(seq_json.get("emails", None), list):
                    top_ok = False
            checks["sequence_top_level_fields"] = bool(top_ok)

            # Trigger mentions "report" or exact phrase
            trigger = seq_json.get("trigger", "")
            trig_lc = trigger.lower() if isinstance(trigger, str) else ""
            if "report" in trig_lc or "2026 state of operations automation".lower() in trig_lc:
                checks["trigger_mentions_report"] = True

            # Emails validations
            emails = seq_json.get("emails", []) if isinstance(seq_json.get("emails", None), list) else []
            if len(emails) == 7:
                checks["emails_count_is_7"] = True

            # Process emails if count is 7
            if len(emails) == 7:
                numbers = []
                subjects_len_ok = True
                email1_immediate_ok = False
                email7_cta_ok = False
                case_study_found = False
                cta_links_ok = True
                body_ok = True

                for email in emails:
                    num = email.get("number", None)
                    numbers.append(num)

                    # Required fields per email
                    name = email.get("name", "")
                    send = email.get("send", "")
                    subject = email.get("subject", "")
                    preview = email.get("preview", "")
                    body = email.get("body", {})
                    cta_text = email.get("cta_text", "")
                    cta_link = email.get("cta_link", "")

                    # Track for cross-file checks
                    if isinstance(num, int) and 1 <= num <= 7 and is_nonempty_string(subject) and is_nonempty_string(preview):
                        subjects_by_num[num] = subject
                        previews_by_num[num] = preview
                        send_by_num[num] = send
                        cta_text_by_num[num] = cta_text
                        cta_link_by_num[num] = cta_link
                        body_by_num[num] = body

                    # Subject length 40-60 inclusive
                    if not (isinstance(subject, str) and 40 <= len(subject) <= 60):
                        subjects_len_ok = False

                    # Email 1 send indicates immediate
                    if num == 1 and isinstance(send, str):
                        s = send.strip().lower()
                        if ("immediate" in s) or ("immediately" in s) or re.search(r"\bday\s*0\b", s):
                            email1_immediate_ok = True

                    # Email 7 CTA text contains 'demo' or 'book'
                    if num == 7 and isinstance(cta_text, str):
                        ctalc = cta_text.lower()
                        if ("demo" in ctalc) or ("book" in ctalc):
                            email7_cta_ok = True

                    # At least one case study among emails 2-6
                    if isinstance(num, int) and 2 <= num <= 6:
                        text_fields = []
                        if isinstance(name, str):
                            text_fields.append(name)
                        if isinstance(subject, str):
                            text_fields.append(subject)
                        val_text = ""
                        if isinstance(body, dict):
                            val_text = body.get("value", "")
                            if isinstance(val_text, str):
                                text_fields.append(val_text)
                        joined = " ".join([t for t in text_fields if isinstance(t, str)])
                        if "case study" in joined.lower():
                            case_study_found = True

                    # CTA link format
                    link_ok = isinstance(cta_link, str) and (cta_link.startswith("https://") or cta_link.startswith("/"))
                    if not link_ok:
                        cta_links_ok = False

                    # Body structure
                    if not isinstance(body, dict):
                        body_ok = False
                    else:
                        for key in ["hook", "context", "value", "cta", "sign_off"]:
                            if not is_nonempty_string(body.get(key, "")):
                                body_ok = False
                                break

                # numbers correctness: ints 1..7, unique
                checks["email_numbers_correct"] = set(numbers) == set(range(1, 8)) and all(isinstance(n, int) for n in numbers)
                checks["subjects_length_valid_all"] = subjects_len_ok
                checks["email1_send_immediate"] = email1_immediate_ok
                checks["email7_cta_has_demo_or_book"] = email7_cta_ok
                checks["has_case_study_email"] = case_study_found
                checks["cta_links_valid"] = cta_links_ok
                checks["body_structure_valid"] = body_ok

    # Validate copy files
    copy_files_map = {}  # num -> filepath
    if checks["copy_dir_exists_and_files"]:
        try:
            for i in range(1, 8):
                prefix = f"E{i}_"
                candidates = [name for name in os.listdir(copy_dir) if name.startswith(prefix) and name.endswith(".md")]
                if candidates:
                    # choose the first sorted candidate deterministically
                    chosen = sorted(candidates)[0]
                    copy_files_map[i] = os.path.join(copy_dir, chosen)
            # Named correctly if we have an entry for each 1..7
            checks["copy_files_named_correctly"] = (set(copy_files_map.keys()) == set(range(1, 8)))
        except Exception:
            checks["copy_files_named_correctly"] = False

        # Sections present and subject/preview matching
        sections_ok = True
        subj_prev_match_ok = True
        if checks["copy_files_named_correctly"] and checks["sequence_plan_json_valid"] and checks["emails_count_is_7"]:
            for i in range(1, 8):
                path = copy_files_map.get(i)
                content, err = read_text_file(path)
                if content is None:
                    sections_ok = False
                    subj_prev_match_ok = False
                    break
                # Find labeled lines
                # Use regex with multiline start anchor
                patterns = {
                    "Subject": r"^Subject:\s*(.+)\s*$",
                    "Preview": r"^Preview:\s*(.+)\s*$",
                    "Hook": r"^Hook:\s*(.+)\s*$",
                    "Context": r"^Context:\s*(.+)\s*$",
                    "Value": r"^Value:\s*(.+)\s*$",
                    "CTA": r"^CTA:\s*(.+)\s*$",
                    "Sign-off": r"^Sign-off:\s*(.+)\s*$",
                }
                found = {}
                for key, pat in patterns.items():
                    m = re.search(pat, content, flags=re.MULTILINE)
                    if not m:
                        found[key] = ""
                    else:
                        found[key] = m.group(1).strip()

                # Check non-empty
                for key in ["Subject", "Preview", "Hook", "Context", "Value", "CTA", "Sign-off"]:
                    if not is_nonempty_string(found.get(key, "")):
                        sections_ok = False

                # Match subject and preview with JSON
                json_subject = subjects_by_num.get(i, None)
                json_preview = previews_by_num.get(i, None)
                if json_subject is None or json_preview is None:
                    subj_prev_match_ok = False
                else:
                    if found.get("Subject", "") != json_subject or found.get("Preview", "") != json_preview:
                        subj_prev_match_ok = False

            checks["copy_files_sections_present"] = sections_ok
            checks["copy_subjects_previews_match"] = subj_prev_match_ok
        else:
            # Cannot verify content if earlier requirements not met
            checks["copy_files_sections_present"] = False
            checks["copy_subjects_previews_match"] = False

    # Validate schedule.tsv
    schedule_rows = []
    if checks["schedule_exists"]:
        text, err = read_text_file(schedule_path)
        if text is not None:
            lines = [ln for ln in text.splitlines() if ln.strip() != ""]
            if lines:
                header = lines[0].rstrip("\n")
                if header == "email_number\tday_offset\tsubject":
                    checks["schedule_header_valid"] = True
                data_lines = lines[1:]
                if len(data_lines) == 7:
                    checks["schedule_rows_count_7"] = True
                # Parse rows
                parsed_ok = []
                for ln in data_lines:
                    parts = ln.split("\t")
                    if len(parts) != 3:
                        parsed_ok.append(False)
                        continue
                    num_str, day_str, subj = parts[0], parts[1], parts[2]
                    try:
                        num = int(num_str)
                        day = int(day_str)
                        schedule_rows.append((num, day, subj))
                        parsed_ok.append(True)
                    except Exception:
                        parsed_ok.append(False)
                # Numbers correct
                nums = [r[0] for r in schedule_rows]
                checks["schedule_numbers_correct"] = set(nums) == set(range(1, 8))
                # Offsets valid and email 1 is 0
                offsets_ok = True
                email1_zero = False
                for num, day, subj in schedule_rows:
                    if not (0 <= day <= 21):
                        offsets_ok = False
                    if num == 1 and day == 0:
                        email1_zero = True
                checks["schedule_offsets_valid"] = offsets_ok and email1_zero
                # Subjects match JSON subjects
                subj_match = True
                if checks["sequence_plan_json_valid"] and checks["emails_count_is_7"]:
                    for num, day, subj in schedule_rows:
                        json_subj = subjects_by_num.get(num, None)
                        if json_subj is None or subj != json_subj:
                            subj_match = False
                            break
                else:
                    subj_match = False
                checks["schedule_subjects_match"] = subj_match

    # Validate metrics_plan.json
    if checks["metrics_exists"]:
        metrics, err = read_json_file(metrics_path)
        if metrics is not None and err is None:
            checks["metrics_json_valid"] = True
            overall = metrics.get("overall_kpis", None)
            per_email = metrics.get("per_email", None)
            overall_ok = isinstance(overall, list) and len(overall) > 0 and all(isinstance(x, str) and x.strip() != "" for x in overall)
            checks["metrics_overall_kpis_present"] = overall_ok

            per_ok = False
            if isinstance(per_email, list) and len(per_email) == 7:
                try:
                    nums = []
                    for item in per_email:
                        if not isinstance(item, dict):
                            raise ValueError("per_email item not dict")
                        en = item.get("email_number", None)
                        pk = item.get("primary_kpi", None)
                        if not isinstance(en, int) or en < 1 or en > 7:
                            raise ValueError("email_number invalid")
                        if not is_nonempty_string(pk):
                            raise ValueError("primary_kpi invalid")
                        nums.append(en)
                    if set(nums) == set(range(1, 8)):
                        per_ok = True
                except Exception:
                    per_ok = False
            checks["metrics_per_email_valid"] = per_ok

    # Gate: if any required artifact missing, reward must be 0.0
    required_present = checks["has_sequence_plan"] and checks["schedule_exists"] and checks["metrics_exists"] and checks["copy_dir_exists_and_files"]

    # Compute reward as fraction of passed checks if required are present, else 0.0
    check_items = {k: v for k, v in checks.items()}
    passed = sum(1 for v in check_items.values() if v is True)
    total = len(check_items)

    if not required_present:
        reward = 0.0
    else:
        # Exclude presence checks from scoring? Keep them included since they are objective and present.
        reward = passed / total if total > 0 else 0.0

    # Print single JSON line
    result = {"reward": float(round(reward, 6))}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()