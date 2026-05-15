import json
import os
import re
import sys

def normalize_ws(s: str) -> str:
    return " ".join(s.strip().split())

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "precheck_exists": False,
        "precheck_json_valid": False,
        "precheck_source_correct": False,
        "precheck_summary_quality": False,
        "notes_exists": False,
        "notes_line_count_matches": False,
        "notes_lines_prefix_suffix": False,
        "notes_no_forbidden_tokens": False,
        "notes_content_set_correct": False,
    }

    # Expected constants
    expected_source_type = "Book"
    expected_source_title = "Digital Zettelkasten"
    expected_source_author = "David Kadavy"
    expected_suffix = f" ~ {expected_source_type}, {expected_source_title} by {expected_source_author}"
    forbidden_substrings = ["#", "id::", "block-tags::", "[[", "]]"]
    expected_contents = [
        "rewriting ideas helps decide their importance",
        "fleeting notes: quick notes written anywhere",
        "fleeting notes (quick notes written anywhere) can be captured on paper or digitally",
        "fleeting notes (quick notes written anywhere) when capturing, date entries",
        "keywords should be specific to the idea",
        "a system should encourage links over folders",
        "luhmann emphasized atomicity of notes",
        "link syntax page one and page two should be converted",
    ]
    expected_set_norm = set(normalize_ws(s.lower()) for s in expected_contents)

    # Load precheck.json
    precheck_path = os.path.join(output_dir, "precheck.json")
    precheck_data = None
    if os.path.isfile(precheck_path):
        checks["precheck_exists"] = True
        try:
            with open(precheck_path, "r", encoding="utf-8") as f:
                precheck_data = json.load(f)
        except Exception:
            precheck_data = None

        # Validate structure
        if isinstance(precheck_data, dict):
            has_keys = all(k in precheck_data for k in ["summary", "note_count", "source"])
            source_ok = isinstance(precheck_data.get("source"), dict) and all(
                k in precheck_data["source"] for k in ["type", "title", "author"]
            )
            types_ok = (
                isinstance(precheck_data.get("summary"), str)
                and isinstance(precheck_data.get("note_count"), int)
                and source_ok
                and isinstance(precheck_data["source"].get("type"), str)
                and isinstance(precheck_data["source"].get("title"), str)
                and isinstance(precheck_data["source"].get("author"), str)
            )
            if has_keys and types_ok:
                checks["precheck_json_valid"] = True

            # Source exact values
            if checks["precheck_json_valid"]:
                src = precheck_data["source"]
                if (
                    src.get("type") == expected_source_type
                    and src.get("title") == expected_source_title
                    and src.get("author") == expected_source_author
                ):
                    checks["precheck_source_correct"] = True

            # Summary quality: length 40-400 and contains one of keywords
            if checks["precheck_json_valid"]:
                summary = precheck_data["summary"]
                if isinstance(summary, str):
                    slen = len(summary)
                    lower = summary.lower()
                    has_keyword = (
                        "digital zettelkasten" in lower
                        or "kadavy" in lower
                        or "zettelkasten" in lower
                    )
                    if 40 <= slen <= 400 and has_keyword:
                        checks["precheck_summary_quality"] = True

    # Load notes.txt
    notes_path = os.path.join(output_dir, "notes.txt")
    lines = []
    if os.path.isfile(notes_path):
        checks["notes_exists"] = True
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                # Use non-empty lines to be robust against trailing blanks
                lines = [ln.rstrip("\r\n") for ln in f.readlines()]
                lines = [ln for ln in lines if ln.strip() != ""]
        except Exception:
            lines = []

    # notes_line_count_matches depends on precheck note_count
    note_count = None
    if checks["precheck_json_valid"]:
        note_count = precheck_data.get("note_count")
        if isinstance(note_count, int) and note_count == len(lines):
            checks["notes_line_count_matches"] = True

    # lines must start with "- " and end with expected_suffix
    if checks["notes_exists"] and lines:
        prefix_suffix_ok = True
        no_forbidden = True
        for ln in lines:
            if not (ln.startswith("- ") and ln.endswith(expected_suffix)):
                prefix_suffix_ok = False
            # Forbidden tokens anywhere in the line
            for bad in forbidden_substrings:
                if bad in ln:
                    no_forbidden = False
                    break
            if not prefix_suffix_ok and not no_forbidden:
                # No need to continue if both already failed
                pass
        checks["notes_lines_prefix_suffix"] = prefix_suffix_ok
        checks["notes_no_forbidden_tokens"] = no_forbidden

        # Extract content and compare set
        contents_norm = []
        for ln in lines:
            if ln.startswith("- ") and ln.endswith(expected_suffix):
                content = ln[2 : len(ln) - len(expected_suffix)]
                contents_norm.append(normalize_ws(content.lower()))
            else:
                # If format wrong, we cannot reliably extract; keep placeholder
                contents_norm.append(None)
        if all(c is not None for c in contents_norm):
            set_norm = set(contents_norm)
            if set_norm == expected_set_norm and len(set_norm) == len(expected_set_norm):
                checks["notes_content_set_correct"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure baseline no-op: if output directory missing or both files missing, reward should be 0.0
    if not checks["precheck_exists"] and not checks["notes_exists"]:
        reward = 0.0

    # Print final JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()