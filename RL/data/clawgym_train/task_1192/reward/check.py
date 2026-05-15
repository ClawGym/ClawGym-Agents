import json
import os
import re
import sys

def count_words_from_text(text: str) -> int:
    tokens = re.split(r"\s+", text.strip())
    return len([t for t in tokens if t])

def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def possible_integer_targets(value: float):
    from math import floor, ceil
    return {int(floor(value)), int(round(value)), int(ceil(value))}

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    book_path = os.path.join(input_dir, "book.txt")
    summary_md_path = os.path.join(output_dir, "summary.md")
    report_json_path = os.path.join(output_dir, "summary_report.json")

    # Initialize checks (artifact-dependent checks default to False)
    checks = {
        "input_exists": False,
        "summary_exists": False,
        "summary_heading_correct": False,
        "ratio_in_range": False,
        "report_exists": False,
        "report_valid_json": False,
        "report_fields_present": False,
        "report_types_correct": False,
        "report_values_match_counts": False,
        "report_values_match_ratio": False,
        "report_values_match_bounds": False,
        "report_bounds_cover_summary": False,
    }

    # Validate presence of input (does not contribute positive reward directly)
    if os.path.isfile(book_path):
        checks["input_exists"] = True

    # Prepare computed values
    original_words = None
    summary_words = None
    actual_ratio = None
    first_line = None
    report_obj = None

    # Read and compute counts only if artifacts exist
    if checks["input_exists"] and os.path.isfile(summary_md_path):
        checks["summary_exists"] = True
        try:
            book_text = read_file(book_path)
            original_words = count_words_from_text(book_text)
        except Exception:
            original_words = None

        try:
            summary_text = read_file(summary_md_path)
            # First line must be exactly "Summary"
            first_line = summary_text.splitlines()[0] if summary_text.splitlines() else ""
            if first_line == "Summary":
                checks["summary_heading_correct"] = True
            # Count words across entire file (including the first line)
            summary_words = count_words_from_text(summary_text)
        except Exception:
            summary_words = None

        # Compute ratio if possible
        if original_words and original_words > 0 and summary_words is not None:
            actual_ratio = summary_words / original_words
            if 0.18 <= actual_ratio <= 0.22:
                checks["ratio_in_range"] = True

    # Read and validate report JSON
    if os.path.isfile(report_json_path):
        checks["report_exists"] = True
        try:
            with open(report_json_path, "r", encoding="utf-8") as rf:
                report_obj = json.load(rf)
            checks["report_valid_json"] = True
        except Exception:
            report_obj = None

    # Validate report fields, types, and values if we have counts and report
    if (
        report_obj is not None
        and isinstance(report_obj, dict)
        and original_words is not None
        and summary_words is not None
        and actual_ratio is not None
    ):
        required_fields = [
            "source_word_count",
            "target_min_words",
            "target_max_words",
            "summary_word_count",
            "actual_ratio",
        ]
        if all(f in report_obj for f in required_fields):
            checks["report_fields_present"] = True

            # Types check: counts are ints, ratio is float
            types_ok = (
                isinstance(report_obj.get("source_word_count"), int)
                and isinstance(report_obj.get("target_min_words"), int)
                and isinstance(report_obj.get("target_max_words"), int)
                and isinstance(report_obj.get("summary_word_count"), int)
                and isinstance(report_obj.get("actual_ratio"), (float, int))  # allow int for numerical JSON, will cast
            )
            if types_ok:
                checks["report_types_correct"] = True

                # Value checks
                src_count_ok = (report_obj["source_word_count"] == original_words)
                sum_count_ok = (report_obj["summary_word_count"] == summary_words)
                if src_count_ok and sum_count_ok:
                    checks["report_values_match_counts"] = True

                # Ratio precision check
                reported_ratio = float(report_obj["actual_ratio"])
                computed_ratio_rounded = round(actual_ratio, 4)
                if abs(reported_ratio - computed_ratio_rounded) < 1e-9:
                    checks["report_values_match_ratio"] = True

                # Bounds checks with rounding flexibility
                target_min = report_obj["target_min_words"]
                target_max = report_obj["target_max_words"]
                # Acceptable targets: floor, round, or ceil of 18% and 22%
                min_candidates = possible_integer_targets(original_words * 0.18)
                max_candidates = possible_integer_targets(original_words * 0.22)
                bounds_values_ok = (target_min in min_candidates) and (target_max in max_candidates) and (target_min <= target_max)
                if bounds_values_ok:
                    checks["report_values_match_bounds"] = True

                # Ensure summary count lies within reported bounds
                if target_min <= summary_words <= target_max:
                    checks["report_bounds_cover_summary"] = True

    # Compute final reward: 1.0 only if all artifact-dependent checks pass
    required_for_success = [
        "summary_exists",
        "summary_heading_correct",
        "ratio_in_range",
        "report_exists",
        "report_valid_json",
        "report_fields_present",
        "report_types_correct",
        "report_values_match_counts",
        "report_values_match_ratio",
        "report_values_match_bounds",
        "report_bounds_cover_summary",
    ]
    all_pass = all(checks[k] for k in required_for_success)
    reward = 1.0 if all_pass else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()