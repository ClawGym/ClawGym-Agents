import json
import os
import sys

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            # splitlines() avoids issues with trailing newline
            return f.read().splitlines()
    except Exception:
        return None

def load_jsonl(path):
    lines = read_text_lines(path)
    if lines is None:
        return None
    objs = []
    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)
            objs.append(obj)
        except Exception:
            return None
    return objs

def count_tokens_in_text(text, tokens):
    counts = {t: 0 for t in tokens}
    for t in tokens:
        counts[t] += text.count(t)
    return counts

def sum_counts(count_dicts):
    total = {}
    for d in count_dicts:
        for k, v in d.items():
            total[k] = total.get(k, 0) + int(v)
    return total

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "messages_exists": False,
        "messages_line_count_6": False,
        "messages_content_expected": False,
        "emails_exists": False,
        "emails_line_count_3": False,
        "emails_all_json_valid": False,
        "emails_ids_correct": False,
        "emails_subject_body_expected": False,
        "summary_exists": False,
        "summary_json_valid": False,
        "summary_keys_expected": False,
        "summary_counts_match_outputs": False,
        "summary_counts_expected_values": False,
        "preexisting_tokens_preserved": False,
    }

    # Expected artifacts
    messages_path = os.path.join(output_dir, "anonymized_messages.txt")
    emails_path = os.path.join(output_dir, "anonymized_emails.jsonl")
    summary_path = os.path.join(output_dir, "anonymization_summary.json")

    # Expected contents
    expected_messages = [
        "Call me at [PHONE] or [PHONE]. SSN [SSN]. Email: [EMAIL]",
        "My name is [NAME] and my wallet [WALLET] was compromised at [IP].",
        "Logs saved to [PATH]/Projects/app/logs and also at [PATH]\\Desktop\\report.docx",
        "Already anonymized: [NAME], [EMAIL], [SSN], [PHONE], [WALLET], [IP], [PATH]",
        "Contact [NAME] at [EMAIL] or [PHONE].",
        "Router set to [IP]; path: [PATH]/tmp",
    ]
    expected_emails_by_id = {
        "e1": {
            "subject": "Billing issue for [NAME]",
            "body": "Hi, I'm [NAME]. My SSN is [SSN]; you can reach me at [EMAIL] or [PHONE]. My home folder is [PATH]. Thanks!",
        },
        "e2": {
            "subject": "Access from IP [IP]",
            "body": "This is [NAME] confirming access from [IP]; config resides at [PATH]\\AppData\\Roaming. Please call [PHONE].",
        },
        "e3": {
            "subject": "Re: Update for [NAME]",
            "body": "[NAME] moved her files from [PATH]/Documents to [PATH]/Downloads. Contact at [EMAIL].",
        },
    }
    token_list = ["[NAME]", "[EMAIL]", "[SSN]", "[PHONE]", "[WALLET]", "[IP]", "[PATH]"]
    expected_totals = {"[NAME]": 8, "[EMAIL]": 5, "[SSN]": 3, "[PHONE]": 6, "[WALLET]": 2, "[IP]": 5, "[PATH]": 8}

    # 1) Check anonymized_messages.txt
    if os.path.isfile(messages_path):
        checks["messages_exists"] = True
        msg_lines = read_text_lines(messages_path)
        if isinstance(msg_lines, list):
            if len(msg_lines) == 6:
                checks["messages_line_count_6"] = True
                if msg_lines == expected_messages:
                    checks["messages_content_expected"] = True
                # Specific check for pre-existing tokens preserved (line 4)
                if len(msg_lines) >= 4 and msg_lines[3] == expected_messages[3]:
                    checks["preexisting_tokens_preserved"] = True

    # 2) Check anonymized_emails.jsonl
    emails_objs = None
    if os.path.isfile(emails_path):
        checks["emails_exists"] = True
        emails_objs = load_jsonl(emails_path)
        if isinstance(emails_objs, list):
            if len(emails_objs) == 3:
                checks["emails_line_count_3"] = True
            # Validate each line JSON and key set
            all_valid = True
            ids = []
            only_expected_keys = True
            for obj in emails_objs:
                if not isinstance(obj, dict):
                    all_valid = False
                    break
                keys = set(obj.keys())
                if keys != {"id", "subject", "body"}:
                    only_expected_keys = False
                # also ensure types
                if not isinstance(obj.get("id", None), str):
                    all_valid = False
                    break
                if not isinstance(obj.get("subject", None), str):
                    all_valid = False
                    break
                if not isinstance(obj.get("body", None), str):
                    all_valid = False
                    break
                ids.append(obj["id"])
            if all_valid and only_expected_keys:
                checks["emails_all_json_valid"] = True
            # IDs correct set
            if all_valid:
                if set(ids) == {"e1", "e2", "e3"}:
                    checks["emails_ids_correct"] = True
            # Subject/body exact by id
            if all_valid:
                content_match = True
                objs_by_id = {o["id"]: o for o in emails_objs}
                for eid, exp in expected_emails_by_id.items():
                    o = objs_by_id.get(eid)
                    if not o:
                        content_match = False
                        break
                    if o.get("subject") != exp["subject"]:
                        content_match = False
                        break
                    if o.get("body") != exp["body"]:
                        content_match = False
                        break
                if content_match:
                    checks["emails_subject_body_expected"] = True

    # 3) Check anonymization_summary.json
    summary_obj = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_obj = json.load(f)
            if isinstance(summary_obj, dict):
                checks["summary_json_valid"] = True
        except Exception:
            summary_obj = None

        if summary_obj is not None and checks["summary_json_valid"]:
            # keys expected
            if set(summary_obj.keys()) == set(token_list):
                # ensure all ints
                all_ints = all(isinstance(summary_obj[k], int) for k in token_list)
                if all_ints:
                    checks["summary_keys_expected"] = True

            # Compute counts from outputs (only if we could read them)
            computed_counts = None
            # Count from messages
            if checks["messages_exists"]:
                msg_text = "\n".join(read_text_lines(messages_path) or [])
                counts_msgs = count_tokens_in_text(msg_text, token_list)
            else:
                counts_msgs = {t: 0 for t in token_list}

            # Count from emails (subject/body only)
            if emails_objs is not None:
                counts_emails = {t: 0 for t in token_list}
                for obj in emails_objs:
                    subj = obj.get("subject", "")
                    body = obj.get("body", "")
                    c_subj = count_tokens_in_text(subj, token_list)
                    c_body = count_tokens_in_text(body, token_list)
                    for t in token_list:
                        counts_emails[t] += c_subj[t] + c_body[t]
            else:
                counts_emails = {t: 0 for t in token_list}

            computed_counts = sum_counts([counts_msgs, counts_emails])

            # Compare summary to computed
            if computed_counts is not None and set(computed_counts.keys()) == set(token_list):
                if all(summary_obj.get(t) == computed_counts.get(t) for t in token_list):
                    checks["summary_counts_match_outputs"] = True

            # Compare to expected totals
            if all(summary_obj.get(t) == expected_totals.get(t) for t in token_list):
                checks["summary_counts_expected_values"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if no outputs or nothing passed, ensure 0.0
    if passed == 0:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()