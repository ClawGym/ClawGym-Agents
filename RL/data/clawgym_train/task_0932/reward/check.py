import json
import os
import sys
from typing import List, Dict, Any, Tuple

def is_single_sentence(s: str) -> bool:
    if "\n" in s or "\r" in s:
        return False
    # Count terminators
    term_count = s.count(".") + s.count("!") + s.count("?")
    # Allow zero or one terminator
    return term_count <= 1 and len(s.strip()) > 0

def contains_praise(text: str) -> bool:
    t = text.lower()
    # Match phrases/words
    phrases = [
        "great", "awesome", "nice", "congrats", "well done", "love", "good job"
    ]
    return any(p in t for p in phrases)

def contains_competitor(text: str) -> bool:
    t = text.lower()
    competitors = ["slack", "teams", "discord", "notion", "airbnb", "ebay"]
    return any(c in t for c in competitors)

def load_jsonl_strict(path: str) -> Tuple[bool, List[Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        # No empty lines allowed
        if any(line.strip() == "" for line in lines):
            return False, []
        objs = []
        for line in lines:
            obj = json.loads(line)
            objs.append(obj)
        return True, objs
    except Exception:
        return False, []

def read_user_responses(path: str) -> Dict[Tuple[int, int], str]:
    mapping: Dict[Tuple[int, int], str] = {}
    ok, objs = load_jsonl_strict(path)
    if not ok:
        return mapping
    for obj in objs:
        try:
            st = int(obj.get("stage"))
            rd = int(obj.get("round"))
            ur = obj.get("user_reply")
            if isinstance(ur, str):
                mapping[(st, rd)] = ur
        except Exception:
            continue
    return mapping

def validate_schema(obj: Dict[str, Any], expected_keys: List[str]) -> bool:
    # Object must have exactly expected keys, no more, no less
    if set(obj.keys()) != set(expected_keys):
        return False
    return True

def questions_valid(questions: Any) -> bool:
    if not isinstance(questions, list):
        return False
    if len(questions) < 1 or len(questions) > 2:
        return False
    for q in questions:
        if not isinstance(q, str):
            return False
        if not q.endswith("?"):
            return False
        if len(q.strip()) == 0:
            return False
    return True

def no_praise_in_questions(questions: List[str]) -> bool:
    for q in questions:
        if contains_praise(q):
            return False
    return True

def stage1_no_competitors_in_questions(questions: List[str]) -> bool:
    for q in questions:
        if contains_competitor(q):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "file_exists": False,
        "valid_jsonl": False,
        "correct_line_count": False,
        "stage1_lines_valid": False,
        "stage1_questions_qs_count": False,
        "stage1_no_competitors": False,
        "stage1_no_praise_in_questions": False,
        "transition1_valid": False,
        "stage2_lines_valid": False,
        "stage2_dimensions_order": False,
        "stage2_questions_qs_count": False,
        "stage2_no_praise_in_questions": False,
        "transition2_valid": False,
        "stage3_lines_valid": False,
        "stage3_questions_qs_count": False,
        "stage3_no_praise_in_questions": False,
        "closing_valid": False,
    }

    transcript_path = os.path.join(output_dir, "transcript.jsonl")
    if not os.path.isfile(transcript_path):
        # No output: reward must be 0.0
        print(json.dumps({"reward": 0.0, **checks}))
        return
    checks["file_exists"] = True

    valid, objs = load_jsonl_strict(transcript_path)
    if not valid:
        print(json.dumps({"reward": 0.0, **checks}))
        return
    checks["valid_jsonl"] = True

    # Must be exactly 12 lines
    if len(objs) == 12:
        checks["correct_line_count"] = True

    # Load user responses to verify quotes
    user_responses_path = os.path.join(input_dir, "user_responses.jsonl")
    user_map = read_user_responses(user_responses_path)

    # Validate sequence:
    # 0-2: Stage 1 questions
    # 3: transition 1 (1->2)
    # 4-7: Stage 2 questions with dimensions source, scale, match, direction
    # 8: transition 2 (2->3)
    # 9-10: Stage 3 questions with purposes irreducible_core, side_effect
    # 11: closing

    # Proceed only if correct line count
    if checks["correct_line_count"]:
        # Stage 1 lines
        s1_valid = True
        s1_qs_count_ok = True
        s1_no_comp = True
        s1_no_praise = True

        for i in range(3):
            obj = objs[i]
            expected_keys = ["type", "stage", "round", "questions"]
            if not validate_schema(obj, expected_keys):
                s1_valid = False
                break
            if obj.get("type") != "question":
                s1_valid = False
                break
            if obj.get("stage") != 1:
                s1_valid = False
                break
            if obj.get("round") != (i + 1):
                s1_valid = False
                break
            qs = obj.get("questions")
            if not questions_valid(qs):
                s1_qs_count_ok = False
            if not stage1_no_competitors_in_questions(qs):
                s1_no_comp = False
            if not no_praise_in_questions(qs):
                s1_no_praise = False

        checks["stage1_lines_valid"] = s1_valid
        checks["stage1_questions_qs_count"] = s1_qs_count_ok
        checks["stage1_no_competitors"] = s1_no_comp
        checks["stage1_no_praise_in_questions"] = s1_no_praise

        # Transition 1
        t1_obj = objs[3]
        t1_valid = False
        expected_t1_keys = ["type", "from_stage", "to_stage", "user_quote", "surviving_logic", "testing"]
        if validate_schema(t1_obj, expected_t1_keys):
            if (
                t1_obj.get("type") == "transition" and
                t1_obj.get("from_stage") == 1 and
                t1_obj.get("to_stage") == 2 and
                isinstance(t1_obj.get("testing"), str) and len(t1_obj.get("testing").strip()) > 0 and
                isinstance(t1_obj.get("surviving_logic"), str) and is_single_sentence(t1_obj.get("surviving_logic")) and
                isinstance(t1_obj.get("user_quote"), str)
            ):
                # user_quote must equal user_reply from stage=1 round=2
                expected_quote = user_map.get((1, 2))
                if expected_quote is not None and t1_obj.get("user_quote") == expected_quote:
                    t1_valid = True
        checks["transition1_valid"] = t1_valid

        # Stage 2 lines
        s2_valid = True
        s2_dim_order_ok = True
        s2_qs_count_ok = True
        s2_no_praise = True
        dim_order = ["source", "scale", "match", "direction"]
        for i in range(4):
            obj = objs[4 + i]
            expected_keys = ["type", "stage", "round", "questions", "dimension"]
            if not validate_schema(obj, expected_keys):
                s2_valid = False
                break
            if obj.get("type") != "question":
                s2_valid = False
                break
            if obj.get("stage") != 2:
                s2_valid = False
                break
            if obj.get("round") != (i + 1):
                s2_valid = False
                break
            if obj.get("dimension") != dim_order[i]:
                s2_dim_order_ok = False
            qs = obj.get("questions")
            if not questions_valid(qs):
                s2_qs_count_ok = False
            if not no_praise_in_questions(qs):
                s2_no_praise = False

        checks["stage2_lines_valid"] = s2_valid
        checks["stage2_dimensions_order"] = s2_dim_order_ok
        checks["stage2_questions_qs_count"] = s2_qs_count_ok
        checks["stage2_no_praise_in_questions"] = s2_no_praise

        # Transition 2
        t2_obj = objs[8]
        t2_valid = False
        expected_t2_keys = ["type", "from_stage", "to_stage", "user_quote", "surviving_logic", "testing"]
        if validate_schema(t2_obj, expected_t2_keys):
            if (
                t2_obj.get("type") == "transition" and
                t2_obj.get("from_stage") == 2 and
                t2_obj.get("to_stage") == 3 and
                isinstance(t2_obj.get("testing"), str) and len(t2_obj.get("testing").strip()) > 0 and
                isinstance(t2_obj.get("surviving_logic"), str) and is_single_sentence(t2_obj.get("surviving_logic")) and
                isinstance(t2_obj.get("user_quote"), str)
            ):
                expected_quote2 = user_map.get((2, 3))
                if expected_quote2 is not None and t2_obj.get("user_quote") == expected_quote2:
                    t2_valid = True
        checks["transition2_valid"] = t2_valid

        # Stage 3 lines
        s3_valid = True
        s3_qs_count_ok = True
        s3_no_praise = True
        purposes = ["irreducible_core", "side_effect"]
        for i in range(2):
            obj = objs[9 + i]
            expected_keys = ["type", "stage", "round", "questions", "purpose"]
            if not validate_schema(obj, expected_keys):
                s3_valid = False
                break
            if obj.get("type") != "question":
                s3_valid = False
                break
            if obj.get("stage") != 3:
                s3_valid = False
                break
            if obj.get("round") != (i + 1):
                s3_valid = False
                break
            if obj.get("purpose") != purposes[i]:
                s3_valid = False
                break
            qs = obj.get("questions")
            if not questions_valid(qs):
                s3_qs_count_ok = False
            if not no_praise_in_questions(qs):
                s3_no_praise = False

        checks["stage3_lines_valid"] = s3_valid
        checks["stage3_questions_qs_count"] = s3_qs_count_ok
        checks["stage3_no_praise_in_questions"] = s3_no_praise

        # Closing
        closing_obj = objs[11]
        closing_valid = False
        expected_closing_keys = ["type", "transformation", "core_logic", "go_validate"]
        if validate_schema(closing_obj, expected_closing_keys):
            if closing_obj.get("type") == "closing":
                trans = closing_obj.get("transformation")
                core = closing_obj.get("core_logic")
                gv = closing_obj.get("go_validate")
                if (
                    isinstance(trans, str) and trans.startswith("From ") and (" to " in trans) and
                    isinstance(core, str) and is_single_sentence(core) and
                    isinstance(gv, str) and len(gv.strip()) > 0
                ):
                    closing_valid = True
        checks["closing_valid"] = closing_valid

    # Compute reward
    # If file missing or invalid jsonl, reward is 0
    if not checks["file_exists"] or not checks["valid_jsonl"]:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Enforce baseline: if output file missing required artifacts (e.g., wrong count) => allow fractional.
    # The baseline no-op is handled by file_exists=False -> reward 0.0.

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()