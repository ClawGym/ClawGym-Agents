import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = {
        "has_formatted_jsonl": False,
        "formatted_nonempty": False,
        "formatted_schema_valid": False,
        "formatted_text_no_tabs_newlines": False,
        "formatted_text_no_double_spaces": False,
        "formatted_text_starts_uppercase": False,
        "formatted_text_uppercase_after_period_space": False,
        "formatted_text_ends_with_punct": False,
        "has_combined_txt": False,
        "combined_blocks_count_match": False,
        "combined_blocks_exact_match": False,
        "has_qc_report": False,
        "qc_processed_count_matches": False,
        "qc_added_terminal_punct_line_present": False,
        "qc_contains_assumption_or_notes": False,
        "qc_mentions_url_or_abbreviation": False,
        "only_expected_outputs_present": False,
    }

    # Paths
    formatted_path = os.path.join(output_dir, "formatted_transcripts.jsonl")
    combined_path = os.path.join(output_dir, "combined_formatted.txt")
    qc_path = os.path.join(output_dir, "qc_report.md")

    records = []
    formatted_texts = []

    # Check formatted_transcripts.jsonl
    if os.path.isfile(formatted_path):
        checks["has_formatted_jsonl"] = True
        try:
            with open(formatted_path, "r", encoding="utf-8") as f:
                raw_lines = f.readlines()
        except Exception:
            raw_lines = []

        # Nonempty means at least one non-empty line present
        nonempty_lines = [ln for ln in raw_lines if ln.strip() != ""]
        if len(nonempty_lines) > 0:
            checks["formatted_nonempty"] = True

            schema_valid = True
            no_tabs_newlines = True
            no_double_spaces = True
            starts_uppercase = True
            uppercase_after_period_space = True
            ends_with_punct = True

            for idx, line in enumerate(raw_lines):
                if line.strip() == "":
                    schema_valid = False
                    break
                try:
                    obj = json.loads(line)
                except Exception:
                    schema_valid = False
                    break
                # Validate keys and types
                if not isinstance(obj, dict):
                    schema_valid = False
                    break
                if "id" not in obj or "formatted_text" not in obj:
                    schema_valid = False
                    break
                # id should be a number (int or float, but not bool)
                id_val = obj["id"]
                if not (isinstance(id_val, (int, float)) and not isinstance(id_val, bool)):
                    schema_valid = False
                    break
                # formatted_text must be string
                ft = obj["formatted_text"]
                if not isinstance(ft, str):
                    schema_valid = False
                    break

                # Collect for later comparison
                records.append(obj)
                formatted_texts.append(ft)

                # Text checks
                if ("\t" in ft) or ("\n" in ft) or ("\r" in ft):
                    no_tabs_newlines = False

                if "  " in ft:
                    no_double_spaces = False

                stripped_left = ft.lstrip()
                if stripped_left == "":
                    starts_uppercase = False
                else:
                    first_char = stripped_left[0]
                    if not ("A" <= first_char <= "Z"):
                        starts_uppercase = False

                # After ". " check
                pos = 0
                ok_after_period = True
                while True:
                    find_idx = ft.find(". ", pos)
                    if find_idx == -1:
                        break
                    next_pos = find_idx + 2
                    if next_pos < len(ft):
                        ch = ft[next_pos]
                        if not ("A" <= ch <= "Z"):
                            ok_after_period = False
                            break
                    pos = next_pos
                if not ok_after_period:
                    uppercase_after_period_space = False

                # Ends with proper punctuation
                if len(ft) == 0 or ft[-1] not in ".!?":
                    ends_with_punct = False

            checks["formatted_schema_valid"] = schema_valid
            # Only set detailed checks True if schema is valid and at least one record exists
            if schema_valid and len(records) > 0:
                checks["formatted_text_no_tabs_newlines"] = no_tabs_newlines
                checks["formatted_text_no_double_spaces"] = no_double_spaces
                checks["formatted_text_starts_uppercase"] = starts_uppercase
                checks["formatted_text_uppercase_after_period_space"] = uppercase_after_period_space
                checks["formatted_text_ends_with_punct"] = ends_with_punct

    # Check combined_formatted.txt
    if os.path.isfile(combined_path):
        checks["has_combined_txt"] = True
        try:
            with open(combined_path, "r", encoding="utf-8") as f:
                combined_content = f.read()
        except Exception:
            combined_content = None

        if combined_content is not None and formatted_texts:
            # Normalize newlines
            content = combined_content.replace("\r\n", "\n")
            blocks = content.split("\n\n")
            # Do not strip; exact match required
            if len(blocks) == len(formatted_texts):
                checks["combined_blocks_count_match"] = True
                # Compare each block exactly
                exact_match = True
                for i, block in enumerate(blocks):
                    if block != formatted_texts[i]:
                        exact_match = False
                        break
                checks["combined_blocks_exact_match"] = exact_match

    # Check qc_report.md
    if os.path.isfile(qc_path):
        checks["has_qc_report"] = True
        try:
            with open(qc_path, "r", encoding="utf-8") as f:
                qc_text = f.read()
        except Exception:
            qc_text = None

        if qc_text is not None:
            # Processed: integer equal to number of jsonl records
            m_proc = re.search(r"Processed:\s*(\d+)", qc_text)
            if m_proc and records:
                proc_num = int(m_proc.group(1))
                if proc_num == len(records):
                    checks["qc_processed_count_matches"] = True

            # Added terminal punctuation: followed by non-negative integer
            m_added = re.search(r"Added terminal punctuation:\s*(\d+)", qc_text)
            if m_added:
                added_num = int(m_added.group(1))
                if added_num >= 0:
                    checks["qc_added_terminal_punct_line_present"] = True

            # Contains "Assumption" or "Notes" (case-insensitive)
            if re.search(r"(?i)\bAssumption\b|\bNotes\b", qc_text):
                checks["qc_contains_assumption_or_notes"] = True

            # Mentions "URL" or "abbreviation" (case-insensitive)
            if re.search(r"(?i)\bURL\b|\babbreviation(s)?\b", qc_text):
                checks["qc_mentions_url_or_abbreviation"] = True

    # Only expected outputs present
    expected_files = {
        os.path.join(output_dir, "formatted_transcripts.jsonl"),
        os.path.join(output_dir, "combined_formatted.txt"),
        os.path.join(output_dir, "qc_report.md"),
    }
    if os.path.isdir(output_dir):
        present_files = set()
        for root, dirs, files in os.walk(output_dir):
            for name in files:
                present_files.add(os.path.join(root, name))
        # Must be exactly the three expected files (no more, no less)
        if present_files == expected_files:
            checks["only_expected_outputs_present"] = True
        else:
            checks["only_expected_outputs_present"] = False
    else:
        checks["only_expected_outputs_present"] = False

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline yields 0.0 when output is empty or missing required artifacts
    # If none of the three primary files exist, force reward to 0.0
    if not (checks["has_formatted_jsonl"] or checks["has_combined_txt"] or checks["has_qc_report"]):
        reward = 0.0

    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()