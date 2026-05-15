import json
import os
import sys
import re
from typing import Any, Dict, List

def main():
    # Resolve workspace root
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks with all False
    checks: Dict[str, bool] = {
        # File presence and basic structure
        "file_exists_jsonl": False,
        "jsonl_two_lines": False,
        "line1_valid_json": False,
        "line2_valid_json": False,

        # Required fields and types
        "line1_required_fields": False,
        "line2_required_fields": False,

        # Key takeaways correctness
        "line1_key_takeaways_three_nonempty": False,
        "line2_key_takeaways_three_nonempty": False,

        # Reading level
        "line1_reading_level_contains_grade_6_8": False,
        "line2_reading_level_contains_grade": False,

        # Word count accuracy and limits
        "line1_word_count_matches": False,
        "line2_word_count_matches": False,
        "line1_within_word_limit": False,
        "line2_within_word_limit": False,

        # Jargon replacement logging validity
        "line1_jargon_replaced_valid": False,
        "line2_jargon_replaced_valid": False,

        # No jargon present in lay summaries
        "line1_no_jargon_in_summary": False,
        "line2_no_jargon_in_summary": False,

        # README existence and content
        "readme_exists": False,
        "readme_min_length": False,
    }

    def count_words(text: str) -> int:
        return len(text.strip().split())

    def has_required_fields(obj: Dict[str, Any]) -> bool:
        # Must contain keys with correct types
        if not isinstance(obj, dict):
            return False
        required = {
            "lay_summary": str,
            "reading_level": str,
            "key_takeaways": list,
            "word_count": int,
            "jargon_replaced": list,
        }
        for k, t in required.items():
            if k not in obj:
                return False
            # For word_count ensure exact int type (not float, not str)
            if k == "word_count":
                if not isinstance(obj[k], int):
                    return False
            else:
                if not isinstance(obj[k], t):
                    return False
        return True

    def key_takeaways_valid(arr: List[Any]) -> bool:
        if not isinstance(arr, list) or len(arr) != 3:
            return False
        for item in arr:
            if not isinstance(item, str):
                return False
            if len(item.strip()) == 0:
                return False
        return True

    def reading_level_ok_line1(s: str) -> bool:
        # Must include "Grade" (case-insensitive) and indicate 6-8 target:
        # Accept "6-8" or "6" or "7" or "8" directly after "Grade" (allowing non-digits in between)
        if not isinstance(s, str):
            return False
        if re.search(r"grade", s, re.IGNORECASE) is None:
            return False
        # Look for a 6/7/8 mention near grade
        return re.search(r"grade[^0-9]*((6-8)|\b6\b|\b7\b|\b8\b)", s, re.IGNORECASE) is not None

    def reading_level_ok_line2(s: str) -> bool:
        if not isinstance(s, str):
            return False
        return re.search(r"grade", s, re.IGNORECASE) is not None

    JARGON_TERMS = [
        "randomized controlled trial",
        "placebo",
        "efficacy",
        "adverse events",
    ]

    def summary_has_no_jargon(summary: str) -> bool:
        if not isinstance(summary, str):
            return False
        low = summary.lower()
        for term in JARGON_TERMS:
            if term.lower() in low:
                return False
        return True

    def jargon_log_valid(arr: List[Any]) -> bool:
        # At least 2 items; each item must be either:
        # - string containing at least one of the target substrings (case-insensitive), or
        # - object with original term key (term|original) and plain explanation key (plain|explanation) (case-insensitive)
        if not isinstance(arr, list) or len(arr) < 2:
            return False

        def string_item_ok(s: str) -> bool:
            low = s.lower()
            return any(term.lower() in low for term in JARGON_TERMS)

        def object_item_ok(o: Dict[str, Any]) -> bool:
            if not isinstance(o, dict):
                return False
            keys_lower = {k.lower(): k for k in o.keys()}
            orig_key = None
            expl_key = None
            for candidate in ["term", "original"]:
                if candidate in keys_lower:
                    orig_key = keys_lower[candidate]
                    break
            for candidate in ["plain", "explanation"]:
                if candidate in keys_lower:
                    expl_key = keys_lower[candidate]
                    break
            if not orig_key or not expl_key:
                return False
            # Values must be non-empty strings
            return isinstance(o[orig_key], str) and len(o[orig_key].strip()) > 0 and isinstance(o[expl_key], str) and len(o[expl_key].strip()) > 0

        for item in arr:
            if isinstance(item, str):
                if not string_item_ok(item):
                    return False
            elif isinstance(item, dict):
                if not object_item_ok(item):
                    return False
            else:
                return False
        return True

    # Paths
    jsonl_path = os.path.join(output_dir, "patient_summaries.jsonl")
    readme_path = os.path.join(output_dir, "README.md")

    # Process JSONL file
    if os.path.isfile(jsonl_path):
        checks["file_exists_jsonl"] = True
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                raw_lines = f.read().splitlines()
            # Filter out empty lines
            lines = [ln for ln in raw_lines if ln.strip() != ""]
            if len(lines) == 2:
                checks["jsonl_two_lines"] = True
                # Parse lines
                objs: List[Dict[str, Any]] = []
                for idx, ln in enumerate(lines, start=1):
                    try:
                        obj = json.loads(ln)
                        objs.append(obj)
                        checks[f"line{idx}_valid_json"] = True
                    except Exception:
                        objs.append(None)
                        # leave valid_json False

                # Validate each object if it parsed successfully
                for idx in (1, 2):
                    obj = objs[idx - 1]
                    if isinstance(obj, dict) and checks[f"line{idx}_valid_json"]:
                        if has_required_fields(obj):
                            checks[f"line{idx}_required_fields"] = True

                            # Key takeaways
                            if key_takeaways_valid(obj["key_takeaways"]):
                                checks[f"line{idx}_key_takeaways_three_nonempty"] = True

                            # Reading level
                            if idx == 1:
                                if reading_level_ok_line1(obj["reading_level"]):
                                    checks["line1_reading_level_contains_grade_6_8"] = True
                            else:
                                if reading_level_ok_line2(obj["reading_level"]):
                                    checks["line2_reading_level_contains_grade"] = True

                            # Word count match
                            lay_summary = obj["lay_summary"]
                            actual_wc = count_words(lay_summary)
                            if actual_wc == obj["word_count"]:
                                checks[f"line{idx}_word_count_matches"] = True

                            # Word limit
                            if idx == 1:
                                if actual_wc <= 180:
                                    checks["line1_within_word_limit"] = True
                            else:
                                if actual_wc <= 120:
                                    checks["line2_within_word_limit"] = True

                            # Jargon replaced validity
                            if jargon_log_valid(obj["jargon_replaced"]):
                                checks[f"line{idx}_jargon_replaced_valid"] = True

                            # No jargon in lay summary
                            if summary_has_no_jargon(lay_summary):
                                checks[f"line{idx}_no_jargon_in_summary"] = True
                        # If required fields missing, all subsequent checks for this line remain False
            else:
                # Not exactly two non-empty lines; subsequent checks remain False
                pass
        except Exception:
            # If file cannot be read or other error, keep defaults
            pass

    # README checks
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                content = f.read()
            if isinstance(content, str) and len(content) >= 50:
                checks["readme_min_length"] = True
        except Exception:
            pass

    # Compute reward: fraction of passed checks; ensure no-op baseline gets 0.0
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # If output directory missing or both primary output artifacts missing, maintain baseline 0.0
    # (However, above logic already ensures if nothing exists, passed_checks == 0)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()