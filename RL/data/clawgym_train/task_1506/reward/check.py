import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False until proven True)
    checks: Dict[str, bool] = {
        "rewrites_json_exists": False,
        "rewrites_json_valid": False,
        "rewrites_has_two_items": False,
        "rewrites_filenames_correct": False,
        "rewrites_items_have_required_keys": False,
        "rewrites_before_after_valid": False,
        "changes_summary_min_length": False,
        "clean_text_blog_matches_after": False,
        "clean_text_newsletter_matches_after": False,
        "quality_report_exists": False,
        "quality_report_valid_json": False,
        "quality_report_has_required_structure": False,
        "voice_alignment_exists": False,
        "voice_alignment_has_required_phrases": False,
        "patterns_no_em_dash": False,
        "patterns_no_curly_quotes": False,
        "patterns_no_boldface": False,
        "patterns_no_chatbot_artifacts": False,
        "patterns_no_ai_vocabulary": False,
        "patterns_no_emoji": False,
    }

    # Helper paths
    humanized_dir = os.path.join(output_dir, "humanized")
    rewrites_path = os.path.join(humanized_dir, "rewrites.json")
    clean_texts_dir = os.path.join(humanized_dir, "clean_texts")
    blog_clean_path = os.path.join(clean_texts_dir, "blog-draft.md")
    newsletter_clean_path = os.path.join(clean_texts_dir, "newsletter-draft.md")
    quality_report_path = os.path.join(humanized_dir, "quality_report.json")
    voice_alignment_path = os.path.join(humanized_dir, "voice_alignment.md")

    # Load rewrites.json
    rewrites_data: Optional[List[Dict[str, Any]]] = None
    if os.path.isfile(rewrites_path):
        checks["rewrites_json_exists"] = True
        rewrites_data = load_json(rewrites_path)
        if isinstance(rewrites_data, list):
            checks["rewrites_json_valid"] = True

    # Validate rewrites.json structure
    after_map: Dict[str, str] = {}
    before_map: Dict[str, str] = {}
    if checks["rewrites_json_valid"]:
        # Check array length
        if len(rewrites_data) == 2:
            checks["rewrites_has_two_items"] = True

        # Filenames must be exactly these two (order not enforced)
        expected_filenames = {"blog-draft.md", "newsletter-draft.md"}
        found_filenames = set()
        required_keys = {"filename", "before", "after", "changes_summary", "voice_notes"}
        items_have_keys = True
        before_after_ok = True
        changes_summary_ok = True

        for item in rewrites_data:
            if not isinstance(item, dict):
                items_have_keys = False
                before_after_ok = False
                changes_summary_ok = False
                break

            # Check required keys
            if not required_keys.issubset(item.keys()):
                items_have_keys = False

            # Accumulate filename
            fname = item.get("filename")
            if isinstance(fname, str):
                found_filenames.add(fname)

            # Validate before/after
            before = item.get("before")
            after = item.get("after")
            if isinstance(fname, str) and isinstance(after, str):
                after_map[fname] = after
            if isinstance(fname, str) and isinstance(before, str):
                before_map[fname] = before

            if not (isinstance(before, str) and isinstance(after, str)):
                before_after_ok = False
            else:
                # Non-empty and different
                if len(before.strip()) == 0 or len(after.strip()) == 0 or before == after:
                    before_after_ok = False

            # changes_summary length check
            changes_summary = item.get("changes_summary")
            if not isinstance(changes_summary, str) or len(changes_summary) < 100:
                changes_summary_ok = False

        if found_filenames == expected_filenames:
            checks["rewrites_filenames_correct"] = True
        if items_have_keys:
            checks["rewrites_items_have_required_keys"] = True
        if before_after_ok:
            checks["rewrites_before_after_valid"] = True
        if changes_summary_ok:
            checks["changes_summary_min_length"] = True

    # Compare clean_texts contents to after fields (normalize trailing newline only)
    if checks["rewrites_before_after_valid"] and checks["rewrites_filenames_correct"]:
        # Blog
        if os.path.isfile(blog_clean_path):
            blog_file_content = read_text(blog_clean_path)
            blog_after = after_map.get("blog-draft.md")
            if isinstance(blog_after, str):
                if normalize_trailing_newline(blog_file_content) == normalize_trailing_newline(blog_after):
                    checks["clean_text_blog_matches_after"] = True

        # Newsletter
        if os.path.isfile(newsletter_clean_path):
            newsletter_file_content = read_text(newsletter_clean_path)
            newsletter_after = after_map.get("newsletter-draft.md")
            if isinstance(newsletter_after, str):
                if normalize_trailing_newline(newsletter_file_content) == normalize_trailing_newline(newsletter_after):
                    checks["clean_text_newsletter_matches_after"] = True

    # Validate quality_report.json
    if os.path.isfile(quality_report_path):
        checks["quality_report_exists"] = True
        quality_data = load_json(quality_report_path)
        if isinstance(quality_data, dict):
            checks["quality_report_valid_json"] = True
            files_entry = quality_data.get("files")
            if isinstance(files_entry, list) and len(files_entry) == 2:
                struct_ok = True
                for entry in files_entry:
                    if not isinstance(entry, dict):
                        struct_ok = False
                        break
                    if not isinstance(entry.get("filename"), str):
                        struct_ok = False
                        break
                    awc = entry.get("after_word_count")
                    if not (isinstance(awc, int) or isinstance(awc, float)):
                        struct_ok = False
                        break
                    apf = entry.get("ai_pattern_flags")
                    if not isinstance(apf, list):
                        struct_ok = False
                        break
                if struct_ok:
                    checks["quality_report_has_required_structure"] = True

    # Validate voice_alignment.md
    if os.path.isfile(voice_alignment_path):
        checks["voice_alignment_exists"] = True
        va_text = read_text(voice_alignment_path)
        # Count occurrences of required substrings
        need_substrings = [
            "We are:",
            "We are not:",
            "Sounds like:",
            "Does NOT sound like:",
        ]
        counts = {s: va_text.count(s) for s in need_substrings}
        if all(counts[s] >= 3 for s in need_substrings):
            checks["voice_alignment_has_required_phrases"] = True

    # Pattern checks on "after" texts from rewrites.json
    if checks["rewrites_before_after_valid"] and checks["rewrites_filenames_correct"]:
        after_texts = [after_map.get("blog-draft.md", ""), after_map.get("newsletter-draft.md", "")]
        # 1) No em dashes
        if all("—" not in t for t in after_texts):
            checks["patterns_no_em_dash"] = True
        # 2) No curly quotes (double)
        if all(("“" not in t and "”" not in t) for t in after_texts):
            checks["patterns_no_curly_quotes"] = True
        # 3) No boldface markers
        if all("**" not in t for t in after_texts):
            checks["patterns_no_boldface"] = True
        # 4) No chatbot artifacts (case-insensitive)
        chatbot_phrases = [
            "i hope this helps",
            "let me know",
            "certainly",
            "of course",
            "great question",
            "you're absolutely right",
        ]
        if all(not contains_any(t.lower(), chatbot_phrases) for t in after_texts):
            checks["patterns_no_chatbot_artifacts"] = True
        # 5) No AI vocabulary (case-insensitive substring acceptable)
        banned_ai_vocab = [
            "additionally",
            "landscape",
            "pivotal",
            "underscore",
            "testament",
            "showcase",
            "vibrant",
            "boasts",
            "serves as",
            "stands as",
            "enduring",
            "commitment to",
            "broader",
            "fostering",
            "enhance",
        ]
        if all(not contains_any(t.lower(), banned_ai_vocab) for t in after_texts):
            checks["patterns_no_ai_vocabulary"] = True
        # 6) No emoji (common ranges)
        if all(not contains_emoji(t) for t in after_texts):
            checks["patterns_no_emoji"] = True

    # Compute reward as fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Print final JSON result (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

def load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def normalize_trailing_newline(s: str) -> str:
    # Remove trailing CR/LF characters but keep internal whitespace intact
    return s.rstrip("\r\n")

def contains_any(hay: str, needles: List[str]) -> bool:
    return any(n in hay for n in needles)

def contains_emoji(text: str) -> bool:
    # Check commonly used emoji ranges:
    # - Miscellaneous Symbols and Pictographs: U+1F300–U+1F5FF
    # - Emoticons: U+1F600–U+1F64F
    # - Transport and Map Symbols: U+1F680–U+1F6FF
    # - Supplemental Symbols and Pictographs: U+1F900–U+1F9FF
    # - Symbols and Pictographs Extended-A: U+1FA70–U+1FAFF
    # - Miscellaneous Symbols: U+2600–U+26FF
    # - Dingbats: U+2700–U+27BF
    ranges: List[Tuple[int, int]] = [
        (0x1F300, 0x1F5FF),
        (0x1F600, 0x1F64F),
        (0x1F680, 0x1F6FF),
        (0x1F900, 0x1F9FF),
        (0x1FA70, 0x1FAFF),
        (0x2600, 0x26FF),
        (0x2700, 0x27BF),
    ]
    for ch in text:
        cp = ord(ch)
        for lo, hi in ranges:
            if lo <= cp <= hi:
                return True
    return False

if __name__ == "__main__":
    main()