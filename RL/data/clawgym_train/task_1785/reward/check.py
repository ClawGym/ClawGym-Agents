import json
import os
import sys
import csv
import re
from typing import List, Dict, Any

def has_cjk(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return re.search(r'[\u4e00-\u9fff]', text) is not None

def load_jsonl(path: str) -> List[Dict[str, Any]]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                items.append(obj)
    return items

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def parse_csv_with_header(path: str):
    with open(path, "r", encoding="utf-8", newline="") as f:
        content = f.read()
    lines = [ln for ln in content.splitlines()]
    return lines

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    tickets_path = os.path.join(input_dir, "tickets.jsonl")
    report_path = os.path.join(output_dir, "triage_report.json")
    summary_path = os.path.join(output_dir, "triage_summary.csv")
    drafts_dir = os.path.join(output_dir, "drafts")

    allowed_platforms = {
        "Meta", "TikTok Ads", "Google Ads", "YouTube", "X", "LinkedIn",
        "Snapchat", "Pinterest", "Reddit", "DV360", "Taboola", "Outbrain"
    }
    allowed_categories = {
        "Account setup",
        "Business structure / asset ownership",
        "Permissions or access",
        "Payment or billing",
        "Account suspension or restriction",
        "Policy or compliance",
        "Launch readiness",
        "Ongoing ad operations",
    }

    # Initialize checks (all False by default)
    checks = {
        "found_input": False,  # does not contribute positive reward
        "report_exists": False,
        "report_json_valid": False,
        "report_length_matches": False,
        "report_ids_cover_all_input": False,
        "report_fields_valid": False,
        "summary_exists": False,
        "summary_header_valid": False,
        "summary_rows_count_match": False,
        "summary_consistency_with_report": False,
        "drafts_dir_exists": False,
        "drafts_exist_for_all": False,
        "drafts_content_valid": False,
    }

    # Load input tickets
    input_tickets = []
    input_ticket_ids = []
    try:
        if os.path.isfile(tickets_path):
            input_tickets = load_jsonl(tickets_path)
            input_ticket_ids = []
            for t in input_tickets:
                tid = t.get("ticket_id")
                if isinstance(tid, str):
                    input_ticket_ids.append(tid)
            checks["found_input"] = True
    except Exception:
        # keep defaults, do not award for input-only success
        input_tickets = []
        input_ticket_ids = []

    N = len(input_ticket_ids)

    # Validate triage_report.json
    report_items = None
    report_by_id: Dict[str, Dict[str, Any]] = {}

    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                report_items = data
                checks["report_json_valid"] = True
            else:
                report_items = None
        except Exception:
            report_items = None

    # If report parsed, do deeper validation
    if report_items is not None and checks["found_input"]:
        # length matches
        if len(report_items) == N:
            checks["report_length_matches"] = True

        # collect ids and validate fields
        fields_valid_all = True
        ids_in_report = []
        for item in report_items:
            # Each element must be dict
            if not isinstance(item, dict):
                fields_valid_all = False
                break

            # Required keys
            required_keys = [
                "ticket_id", "platform", "category",
                "qualification_questions", "actionable_insight",
                "consultation_recommendation"
            ]
            for k in required_keys:
                if k not in item:
                    fields_valid_all = False
                    break
            if not fields_valid_all:
                break

            # Types and values
            ticket_id = item.get("ticket_id")
            platform = item.get("platform")
            category = item.get("category")
            questions = item.get("qualification_questions")
            actionable = item.get("actionable_insight")
            consult = item.get("consultation_recommendation")

            if not isinstance(ticket_id, str) or ticket_id == "":
                fields_valid_all = False
                break

            if platform not in allowed_platforms:
                fields_valid_all = False
                break

            if category not in allowed_categories:
                fields_valid_all = False
                break

            if not isinstance(questions, list) or not (2 <= len(questions) <= 4):
                fields_valid_all = False
                break

            # Questions: all strings ending with '?'
            for q in questions:
                if not isinstance(q, str):
                    fields_valid_all = False
                    break
                if not q.strip().endswith("?"):
                    fields_valid_all = False
                    break
                if has_cjk(q):
                    fields_valid_all = False
                    break
            if not fields_valid_all:
                break

            # actionable_insight checks
            if not isinstance(actionable, str) or len(actionable.strip()) == 0 or len(actionable.strip()) < 20:
                fields_valid_all = False
                break
            if has_cjk(actionable):
                fields_valid_all = False
                break

            # consultation_recommendation checks
            if not isinstance(consult, str) or len(consult.strip()) == 0:
                fields_valid_all = False
                break
            if ("@Mangozhuang" not in consult) or ("+1 765 409 6799" not in consult):
                fields_valid_all = False
                break
            if has_cjk(consult):
                fields_valid_all = False
                break

            # No Chinese characters in platform, category, ticket_id
            for s in [ticket_id, platform, category]:
                if has_cjk(s):
                    fields_valid_all = False
                    break
            if not fields_valid_all:
                break

            ids_in_report.append(ticket_id)
            report_by_id[ticket_id] = item

        if fields_valid_all:
            checks["report_fields_valid"] = True

        # ids cover all input
        if set(ids_in_report) == set(input_ticket_ids) and len(ids_in_report) == N:
            checks["report_ids_cover_all_input"] = True

    # Validate triage_summary.csv
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            lines = parse_csv_with_header(summary_path)
            if lines:
                header_line = lines[0].strip()
                expected_header = "ticket_id,platform,category,questions_count,has_actionable_insight,recommends_consultation"
                if header_line == expected_header:
                    checks["summary_header_valid"] = True

                # Parse with csv module for rows after header
                rows = []
                # Re-open with csv to parse records
                with open(summary_path, "r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        rows.append(row)

                # Row count equals N
                if checks["found_input"] and len(rows) == N:
                    checks["summary_rows_count_match"] = True

                # Consistency with report
                consistency_ok = True
                if report_by_id and rows:
                    # Build map from CSV by ticket_id
                    csv_by_id = {}
                    for r in rows:
                        tid = r.get("ticket_id")
                        csv_by_id[tid] = r

                    for tid, rpt in report_by_id.items():
                        if tid not in csv_by_id:
                            consistency_ok = False
                            break
                        r = csv_by_id[tid]
                        # questions_count
                        try:
                            q_count_csv = int(r.get("questions_count", "").strip())
                        except Exception:
                            consistency_ok = False
                            break
                        q_count_expected = len(rpt.get("qualification_questions", []))
                        if q_count_csv != q_count_expected:
                            consistency_ok = False
                            break
                        # has_actionable_insight
                        actionable = rpt.get("actionable_insight", "")
                        has_action_expected = "Yes" if isinstance(actionable, str) and len(actionable.strip()) > 0 else "No"
                        if r.get("has_actionable_insight") != has_action_expected:
                            consistency_ok = False
                            break
                        # recommends_consultation
                        consult = rpt.get("consultation_recommendation", "")
                        consult_ok = isinstance(consult, str) and ("@Mangozhuang" in consult) and ("+1 765 409 6799" in consult)
                        consult_expected = "Yes" if consult_ok else "No"
                        if r.get("recommends_consultation") != consult_expected:
                            consistency_ok = False
                            break
                else:
                    consistency_ok = False

                if consistency_ok:
                    checks["summary_consistency_with_report"] = True
        except Exception:
            # leave defaults
            pass

    # Validate drafts
    if os.path.isdir(drafts_dir):
        checks["drafts_dir_exists"] = True

        drafts_exist_all = True
        drafts_content_ok_all = True

        # Only proceed if we have report_by_id (for platform/category cross-check) and input ids
        if checks["found_input"] and report_by_id:
            for tid in input_ticket_ids:
                draft_path = os.path.join(drafts_dir, f"ticket_{tid}.txt")
                if not os.path.isfile(draft_path):
                    drafts_exist_all = False
                    drafts_content_ok_all = False  # content cannot be validated
                    continue

                # Existence per file is ok
                # Now validate content
                try:
                    content = read_text(draft_path)
                except Exception:
                    drafts_content_ok_all = False
                    continue

                if has_cjk(content):
                    drafts_content_ok_all = False
                    continue

                # Contains platform and category strings from report
                rpt = report_by_id.get(tid)
                if not rpt:
                    drafts_content_ok_all = False
                    continue
                platform = rpt.get("platform", "")
                category = rpt.get("category", "")

                if not (isinstance(platform, str) and isinstance(category, str)):
                    drafts_content_ok_all = False
                    continue

                if (platform not in content) or (category not in content):
                    drafts_content_ok_all = False
                    continue

                # Count lines ending with '?'
                lines = [ln.rstrip() for ln in content.splitlines()]
                question_lines = [ln for ln in lines if ln.strip().endswith("?")]
                if not (2 <= len(question_lines) <= 4):
                    drafts_content_ok_all = False
                    continue

                # Contains "Next step:" line with non-empty text following
                next_step_lines = [ln for ln in lines if ln.strip().lower().startswith("next step:")]
                if not next_step_lines:
                    drafts_content_ok_all = False
                    continue
                # Validate non-empty after colon
                valid_next = False
                for ln in next_step_lines:
                    after = ln.split(":", 1)[1] if ":" in ln else ""
                    if isinstance(after, str) and len(after.strip()) > 0:
                        valid_next = True
                        break
                if not valid_next:
                    drafts_content_ok_all = False
                    continue

                # Contains both contact details
                if ("@Mangozhuang" not in content) or ("+1 765 409 6799" not in content):
                    drafts_content_ok_all = False
                    continue

            if drafts_exist_all:
                checks["drafts_exist_for_all"] = True
            if drafts_content_ok_all:
                checks["drafts_content_valid"] = True
        else:
            # If we cannot validate due to missing report or input, keep false
            pass

    # Compute reward: pass only if all output-dependent checks succeed
    required_checks = [
        "report_exists",
        "report_json_valid",
        "report_length_matches",
        "report_ids_cover_all_input",
        "report_fields_valid",
        "summary_exists",
        "summary_header_valid",
        "summary_rows_count_match",
        "summary_consistency_with_report",
        "drafts_dir_exists",
        "drafts_exist_for_all",
        "drafts_content_valid",
    ]
    all_pass = all(checks.get(k, False) for k in required_checks)
    reward = 1.0 if all_pass else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()