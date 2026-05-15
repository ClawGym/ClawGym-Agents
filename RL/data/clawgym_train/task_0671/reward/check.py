import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def is_email_like(s):
    if not isinstance(s, str):
        return False
    return re.search(r".+@.+\..+", s) is not None

def count_sentence_endings(text):
    # Count periods and exclamation marks as sentence endings (naive)
    return text.count(".") + text.count("!")

def last_non_empty_line(text):
    if text is None:
        return ""
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    return lines[-1] if lines else ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks to False
    checks = {
        # File presence
        "press_release_json_exists": False,
        "press_release_md_exists": False,
        "editor_notes_md_exists": False,

        # JSON structural/content checks
        "json_valid": False,
        "json_keys_exact": False,
        "headline_length_ok": False,
        "subheadline_nonempty": False,
        "dateline_pattern_ok": False,
        "lead_length_ok": False,
        "body_length_ok": False,
        "body_has_paragraph_breaks": False,
        "quotes_array_min2": False,
        "quotes_elements_nonempty": False,
        "boilerplate_length_ok": False,
        "boilerplate_sentence_punct_ok": False,
        "media_contact_email_like": False,
        "body_no_overclaim_words": False,

        # Consistency checks with Markdown
        "md_contains_headline": False,
        "md_contains_dateline": False,
        "md_has_quoted_line": False,

        # Editor notes checks
        "editor_notes_has_assumptions": False,
        "editor_notes_has_fact_check_items_heading": False,
        "editor_notes_fact_check_min3_bullets": False,
        "editor_notes_has_style_and_audience_notes": False,
    }

    # Paths
    pr_json_path = os.path.join(output_dir, "press_release.json")
    pr_md_path = os.path.join(output_dir, "press_release.md")
    notes_md_path = os.path.join(output_dir, "editor_notes.md")

    # Check file existence
    if os.path.isfile(pr_json_path):
        checks["press_release_json_exists"] = True
    if os.path.isfile(pr_md_path):
        checks["press_release_md_exists"] = True
    if os.path.isfile(notes_md_path):
        checks["editor_notes_md_exists"] = True

    pr_json = None
    if checks["press_release_json_exists"]:
        pr_json, err = load_json(pr_json_path)
        if pr_json is not None and isinstance(pr_json, dict):
            checks["json_valid"] = True

            required_keys = {"headline", "subheadline", "dateline", "lead", "body", "quotes", "boilerplate", "media_contact"}
            if set(pr_json.keys()) == required_keys:
                checks["json_keys_exact"] = True

                # Field validations (only if keys exact to avoid KeyError)
                headline = pr_json.get("headline")
                subheadline = pr_json.get("subheadline")
                dateline = pr_json.get("dateline")
                lead = pr_json.get("lead")
                body = pr_json.get("body")
                quotes = pr_json.get("quotes")
                boilerplate = pr_json.get("boilerplate")
                media_contact = pr_json.get("media_contact")

                # headline length 15-120 inclusive
                if isinstance(headline, str) and 15 <= len(headline.strip()) <= 120:
                    checks["headline_length_ok"] = True

                # subheadline non-empty string
                if isinstance(subheadline, str) and len(subheadline.strip()) > 0:
                    checks["subheadline_nonempty"] = True

                # dateline matches "City, Month D, YYYY" (Month capitalized)
                if isinstance(dateline, str):
                    if re.fullmatch(r"^.+,\s+[A-Z][a-z]+\s+\d{1,2},\s+20\d{2}$", dateline.strip()) is not None:
                        checks["dateline_pattern_ok"] = True

                # lead length >= 120
                if isinstance(lead, str) and len(lead) >= 120:
                    checks["lead_length_ok"] = True

                # body length >= 300
                if isinstance(body, str) and len(body) >= 300:
                    checks["body_length_ok"] = True
                # body contains at least two paragraph breaks "\n\n"
                if isinstance(body, str) and body.count("\n\n") >= 2:
                    checks["body_has_paragraph_breaks"] = True
                # Safety wording check: body must not contain whole words: cure, guaranteed, miracle
                if isinstance(body, str):
                    if re.search(r"\b(cure|guaranteed|miracle)\b", body, flags=re.IGNORECASE) is None:
                        checks["body_no_overclaim_words"] = True

                # quotes: array with length >= 2 and each element non-empty string
                if isinstance(quotes, list) and len(quotes) >= 2:
                    checks["quotes_array_min2"] = True
                    # each element non-empty string
                    if all(isinstance(q, str) and len(q.strip()) > 0 for q in quotes):
                        checks["quotes_elements_nonempty"] = True

                # boilerplate: length >= 100 and contains at least two sentence-ending periods or exclamations
                if isinstance(boilerplate, str) and len(boilerplate) >= 100:
                    checks["boilerplate_length_ok"] = True
                    if count_sentence_endings(boilerplate) >= 2:
                        checks["boilerplate_sentence_punct_ok"] = True

                # media_contact contains email-like pattern
                if is_email_like(media_contact):
                    checks["media_contact_email_like"] = True

    # Markdown consistency checks
    if checks["press_release_md_exists"]:
        md_text = read_text(pr_md_path)
        if md_text is None:
            md_text = ""
        # headline and dateline must be substrings in md, requires json_valid and keys
        if checks["json_valid"] and checks["json_keys_exact"]:
            headline = pr_json.get("headline") if pr_json else None
            dateline = pr_json.get("dateline") if pr_json else None
            if isinstance(headline, str) and headline in md_text:
                checks["md_contains_headline"] = True
            if isinstance(dateline, str) and dateline in md_text:
                checks["md_contains_dateline"] = True
        # md must contain at least one quoted line containing a double quote
        # We consider any line that has a double quote character
        if any('"' in line for line in md_text.splitlines()):
            checks["md_has_quoted_line"] = True

    # Editor notes checks
    if checks["editor_notes_md_exists"]:
        notes_text = read_text(notes_md_path) or ""
        # Normalize lines for heading detection
        lines = notes_text.splitlines()

        def normalize_heading(s):
            s = s.strip()
            s = re.sub(r"^#{1,6}\s*", "", s)  # remove leading markdown heading markers
            return s.strip().lower()

        # Detect headings
        has_assumptions = any(normalize_heading(ln) == "assumptions" for ln in lines)
        has_fact = any(normalize_heading(ln) == "fact-check items" for ln in lines)
        has_style = any(normalize_heading(ln) == "style and audience notes" for ln in lines)

        checks["editor_notes_has_assumptions"] = has_assumptions
        checks["editor_notes_has_fact_check_items_heading"] = has_fact
        checks["editor_notes_has_style_and_audience_notes"] = has_style

        # Count bullets under "Fact-check items"
        fact_index = None
        for i, ln in enumerate(lines):
            if normalize_heading(ln) == "fact-check items":
                fact_index = i
                break

        bullets_count = 0
        if fact_index is not None:
            # Count lines starting with "- " after the heading
            for ln in lines[fact_index + 1:]:
                # Stop if another section heading encountered (simple heuristic)
                if normalize_heading(ln) in {"assumptions", "style and audience notes"}:
                    break
                if ln.strip().startswith("- "):
                    bullets_count += 1

        if bullets_count >= 3:
            checks["editor_notes_fact_check_min3_bullets"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or none of required files exist, reward must be 0.0
    required_files_exist = checks["press_release_json_exists"] and checks["press_release_md_exists"] and checks["editor_notes_md_exists"]
    if not required_files_exist:
        # If any required file missing, ensure reward 0.0
        reward = 0.0

    # Ensure reward within [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()