import json
import os
import sys
from typing import List, Dict, Tuple

def read_workspace_root() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def load_input_questions(input_path: str) -> Tuple[List[Dict], Dict[str, str], List[str], bool]:
    items = []
    id_to_question = {}
    ids_in_order = []
    input_ok = True
    if not os.path.isfile(input_path):
        return items, id_to_question, ids_in_order, False
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip("\n")
                if not line.strip():
                    # ignore empty/whitespace-only lines in input
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and "id" in obj and "question" in obj:
                        items.append(obj)
                        _id = str(obj["id"])
                        ids_in_order.append(_id)
                        id_to_question[_id] = obj["question"]
                    else:
                        input_ok = False
                except json.JSONDecodeError:
                    input_ok = False
    except Exception:
        input_ok = False
    return items, id_to_question, ids_in_order, input_ok

def parse_answers_jsonl(path: str) -> Tuple[bool, List[Dict], int]:
    """
    Returns: (valid_jsonl, records, non_empty_line_count)
    valid_jsonl is True only if every non-empty line parses as a JSON object.
    """
    records = []
    valid = True
    non_empty_lines = 0
    if not os.path.isfile(path):
        return False, records, 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line.strip():
                    # treat empty lines as not counting toward expected count, but invalid for strict jsonl?
                    # For robustness, ignore empty lines here but they will affect count checks.
                    continue
                non_empty_lines += 1
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        valid = False
                    records.append(obj)
                except json.JSONDecodeError:
                    valid = False
    except Exception:
        return False, [], 0
    return valid, records, non_empty_lines

def main():
    workspace_root = read_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # answers.jsonl related
        "answers_exists": False,
        "answers_jsonl_valid": False,
        "answers_line_count_matches": False,
        "answers_has_required_fields": False,
        "answers_ids_unique": False,
        "answers_ids_match_input": False,
        "answers_questions_preserved": False,
        "answers_source_correct": False,
        "answers_answer_length_sufficient": False,
        # manifest.json related
        "manifest_exists": False,
        "manifest_valid_json": False,
        "manifest_counts_correct": False,
        "manifest_ids_sorted_match": False,
        # summary.md related
        "summary_exists": False,
        "summary_total_line_correct": False,
        "summary_lists_all_ids": False,
    }

    input_path = os.path.join(input_dir, "questions.jsonl")
    input_items, id_to_question, input_ids_in_order, input_ok = load_input_questions(input_path)
    input_ids_set = set(input_ids_in_order)
    input_count = len(input_items)

    # answers.jsonl validation
    answers_path = os.path.join(output_dir, "answers.jsonl")
    if os.path.isfile(answers_path):
        checks["answers_exists"] = True
        valid_jsonl, answers_records, answers_non_empty_lines = parse_answers_jsonl(answers_path)
        if valid_jsonl:
            checks["answers_jsonl_valid"] = True

        # Count check: exact number of records equals input_count
        if answers_non_empty_lines == input_count and len(answers_records) == input_count:
            checks["answers_line_count_matches"] = True

        # Validate structure and content only if we have records count
        required_fields_ok = True
        ids_seen = []
        questions_preserved_ok = True
        source_ok = True
        answer_len_ok = True
        ids_in_answers = []

        if answers_records:
            for rec in answers_records:
                # required fields present
                if not (isinstance(rec, dict) and
                        "id" in rec and "question" in rec and "answer" in rec and "source" in rec):
                    required_fields_ok = False
                    break
                # id as string
                rec_id = str(rec["id"])
                ids_seen.append(rec_id)
                ids_in_answers.append(rec_id)

                # question exact match
                expected_q = id_to_question.get(rec_id, None)
                if expected_q is None or rec["question"] != expected_q:
                    questions_preserved_ok = False

                # source literal "council"
                if rec.get("source") != "council":
                    source_ok = False

                # answer >= 15 trimmed chars and non-empty
                ans = rec.get("answer")
                if not isinstance(ans, str) or len(ans.strip()) < 15:
                    answer_len_ok = False

            # uniqueness
            ids_unique_ok = len(ids_seen) == len(set(ids_seen))
            checks["answers_ids_unique"] = ids_unique_ok

            # ids match input set exactly
            if set(ids_in_answers) == input_ids_set and len(ids_in_answers) == input_count:
                checks["answers_ids_match_input"] = True

            checks["answers_has_required_fields"] = required_fields_ok
            checks["answers_questions_preserved"] = questions_preserved_ok
            checks["answers_source_correct"] = source_ok
            checks["answers_answer_length_sufficient"] = answer_len_ok

    # manifest.json validation
    manifest_path = os.path.join(output_dir, "manifest.json")
    manifest_data = None
    if os.path.isfile(manifest_path):
        checks["manifest_exists"] = True
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            if isinstance(manifest_data, dict):
                checks["manifest_valid_json"] = True
        except Exception:
            checks["manifest_valid_json"] = False

        if checks["manifest_valid_json"]:
            # counts
            inp_cnt = manifest_data.get("input_count")
            ans_cnt = manifest_data.get("answered_count")
            if isinstance(inp_cnt, int) and isinstance(ans_cnt, int):
                if inp_cnt == input_count and ans_cnt == input_count:
                    checks["manifest_counts_correct"] = True
            # ids sorted and match
            ids_list = manifest_data.get("ids")
            if isinstance(ids_list, list) and all(isinstance(x, str) for x in ids_list):
                expected_sorted = sorted(input_ids_in_order)
                if ids_list == expected_sorted and set(ids_list) == input_ids_set:
                    checks["manifest_ids_sorted_match"] = True

    # summary.md validation
    summary_path = os.path.join(output_dir, "summary.md")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_text = f.read()
        except Exception:
            summary_text = ""

        # "Total answered: N" exact line presence
        total_line = f"Total answered: {input_count}"
        if total_line in summary_text:
            checks["summary_total_line_correct"] = True

        # each id appears somewhere in the document
        all_ids_present = True
        for _id in input_ids_in_order:
            if _id not in summary_text:
                all_ids_present = False
                break
        checks["summary_lists_all_ids"] = all_ids_present

    # Compute reward as fraction of checks passed
    # Ensure baseline no-op (no outputs) -> reward 0.0 since all checks remain False
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Print final JSON result
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()