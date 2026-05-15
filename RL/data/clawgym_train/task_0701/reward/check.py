import json
import os
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def file_exists_nonempty(path):
    return os.path.isfile(path) and os.path.getsize(path) > 0

def is_positive_int(value):
    return isinstance(value, int) and value > 0

def has_required_headings(content, headings):
    # All given headings must appear as substrings in the content
    return all(h in content for h in headings)

def extract_section_lines(content, start_heading, end_heading_candidates):
    # Return lines of section starting at start_heading (exclusive) until any end_heading appears
    lines = content.splitlines()
    in_section = False
    collected = []
    for line in lines:
        if not in_section:
            if line.strip() == start_heading:
                in_section = True
            continue
        # in_section is True
        if any(line.strip() == eh for eh in end_heading_candidates):
            break
        collected.append(line)
    return collected

def validate_content_signal(obj):
    # Must be a dict with ai-input, search, ai-train keys, string lowercase values
    if not isinstance(obj, dict):
        return False
    keys = ["ai-input", "search", "ai-train"]
    for k in keys:
        if k not in obj:
            return False
        v = obj[k]
        if not isinstance(v, str):
            return False
        if v != v.lower():
            return False
    return True

def validate_source_url(url, require_http=False, require_no_fragment=False, require_redaction=False):
    if not isinstance(url, str):
        return False
    if require_http and "http" not in url.lower():
        return False
    if require_no_fragment and "#" in url:
        return False
    if require_redaction:
        if ("[redacted]" not in url) and ("[masked]" not in url):
            return False
    return True

def validate_normalized_json(obj, expected_format=None, expected_policy=None, expected_fallback=None, require_http=False, require_no_fragment=False, require_redaction=True):
    # Base schema checks
    if not isinstance(obj, dict):
        return {
            "valid_schema": False,
            "policy_ok": False,
            "format_ok": False,
            "fallback_ok": False,
            "token_ok": False,
            "signal_ok": False,
            "source_url_ok": False,
        }
    valid_schema = True
    # content string
    if not isinstance(obj.get("content"), str) or len(obj.get("content", "")) == 0:
        valid_schema = False
    # format
    fmt = obj.get("format")
    if not isinstance(fmt, str) or fmt not in ["markdown", "html-fallback", "text"]:
        valid_schema = False
    # token_estimate positive int
    token_ok = is_positive_int(obj.get("token_estimate"))
    if not token_ok:
        valid_schema = False
    # content_signal object
    signal_ok = validate_content_signal(obj.get("content_signal"))
    if not signal_ok:
        valid_schema = False
    # policy_action
    policy = obj.get("policy_action")
    if not isinstance(policy, str) or policy not in ["allow_input", "block_input", "needs_review"]:
        valid_schema = False
    # source_url string
    source_url = obj.get("source_url")
    source_url_ok = validate_source_url(
        source_url,
        require_http=require_http,
        require_no_fragment=require_no_fragment,
        require_redaction=require_redaction,
    )
    if not source_url_ok:
        valid_schema = False
    # status_code can be int or null; spec doesn't require strict type here, but we accept int or None
    status_ok = obj.get("status_code") is None or isinstance(obj.get("status_code"), int)

    if not status_ok:
        valid_schema = False
    # fallback_used boolean
    fallback_val = obj.get("fallback_used")
    if not isinstance(fallback_val, bool):
        valid_schema = False

    # Specific expectations
    policy_ok = (expected_policy is None) or (policy == expected_policy)
    format_ok = (expected_format is None) or (fmt == expected_format)
    fallback_ok = (expected_fallback is None) or (fallback_val is expected_fallback)

    return {
        "valid_schema": valid_schema,
        "policy_ok": policy_ok,
        "format_ok": format_ok,
        "fallback_ok": fallback_ok,
        "token_ok": token_ok,
        "signal_ok": signal_ok,
        "source_url_ok": source_url_ok,
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir available if needed
    # reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Normalization presence
        "normalized_news_json_exists": False,
        "normalized_blog_json_exists": False,
        # Schema and field checks
        "news_json_valid_schema": False,
        "blog_json_valid_schema": False,
        "news_policy_action_correct": False,
        "blog_policy_action_correct": False,
        "news_format_correct": False,
        "blog_format_correct": False,
        "news_fallback_used_true": False,
        "blog_fallback_used_false": False,
        "news_token_estimate_positive_int": False,
        "blog_token_estimate_positive_int": False,
        "news_content_signal_fields_ok": False,
        "blog_content_signal_fields_ok": False,
        "news_source_url_redacted_no_fragment": False,
        "blog_source_url_redacted": False,
        # Markdown content files exist
        "news_md_exists_nonempty": False,
        "blog_md_exists_nonempty": False,
        # MVP scope headings present
        "mvp_scope_exists_and_has_headings": False,
        # Lyrics translation structure and content
        "lyrics_translation_exists_and_has_sections": False,
        "lyrics_translation_has_5_nonempty_lines_in_translation": False,
        # Memory defrag outputs
        "defrag_analysis_json_valid": False,
        "defrag_plan_md_has_required_sections_and_execution_notes": False,
        "defrag_verify_json_valid": False,
    }

    # 1) Normalization outputs
    news_json_path = os.path.join(output_dir, "normalized", "news.json")
    blog_json_path = os.path.join(output_dir, "normalized", "blog.json")
    news_md_path = os.path.join(output_dir, "normalized", "news.md")
    blog_md_path = os.path.join(output_dir, "normalized", "blog.md")

    if file_exists_nonempty(news_json_path):
        checks["normalized_news_json_exists"] = True
        news_obj, news_err = load_json_file(news_json_path)
        if news_obj is not None:
            res = validate_normalized_json(
                news_obj,
                expected_format="html-fallback",
                expected_policy="block_input",
                expected_fallback=True,
                require_http=True,
                require_no_fragment=True,
                require_redaction=True,
            )
            checks["news_json_valid_schema"] = res["valid_schema"]
            checks["news_policy_action_correct"] = res["policy_ok"]
            checks["news_format_correct"] = res["format_ok"]
            checks["news_fallback_used_true"] = res["fallback_ok"]
            checks["news_token_estimate_positive_int"] = res["token_ok"]
            checks["news_content_signal_fields_ok"] = res["signal_ok"]
            checks["news_source_url_redacted_no_fragment"] = res["source_url_ok"]
    if file_exists_nonempty(blog_json_path):
        checks["normalized_blog_json_exists"] = True
        blog_obj, blog_err = load_json_file(blog_json_path)
        if blog_obj is not None:
            resb = validate_normalized_json(
                blog_obj,
                expected_format="markdown",
                expected_policy="allow_input",
                expected_fallback=False,
                require_http=False,
                require_no_fragment=False,
                require_redaction=True,
            )
            checks["blog_json_valid_schema"] = resb["valid_schema"]
            checks["blog_policy_action_correct"] = resb["policy_ok"]
            checks["blog_format_correct"] = resb["format_ok"]
            checks["blog_fallback_used_false"] = resb["fallback_ok"]
            checks["blog_token_estimate_positive_int"] = resb["token_ok"]
            checks["blog_content_signal_fields_ok"] = resb["signal_ok"]
            checks["blog_source_url_redacted"] = resb["source_url_ok"]

    if file_exists_nonempty(news_md_path):
        checks["news_md_exists_nonempty"] = True
    if file_exists_nonempty(blog_md_path):
        checks["blog_md_exists_nonempty"] = True

    # 2) MVP scope document
    mvp_scope_path = os.path.join(output_dir, "mvp_scope.md")
    req_headings_mvp = [
        "MVP SCOPE DOCUMENT",
        "HYPOTHESIS:",
        "CORE VALUE DELIVERED:",
        "MUST-HAVE FEATURES (🔴):",
        "FAKED / MANUAL FEATURES (🟡 deferred to real implementation):",
        "CUT FROM MVP (🟢 — revisit after launch):",
        "LAUNCH CRITERIA (checklist):",
        "WHAT SUCCESS LOOKS LIKE (30-day metrics):",
    ]
    if file_exists_nonempty(mvp_scope_path):
        try:
            with open(mvp_scope_path, "r", encoding="utf-8") as f:
                mvp_content = f.read()
            if has_required_headings(mvp_content, req_headings_mvp):
                checks["mvp_scope_exists_and_has_headings"] = True
        except Exception:
            pass

    # 3) Lyrics translation
    lyrics_out_path = os.path.join(output_dir, "marketing", "translated_lyrics.md")
    if file_exists_nonempty(lyrics_out_path):
        try:
            with open(lyrics_out_path, "r", encoding="utf-8") as f:
                lyr = f.read()
            needed = [
                "### Original (Indonesian)",
                "### Translation (English)",
                "### Notes",
            ]
            if has_required_headings(lyr, needed):
                checks["lyrics_translation_exists_and_has_sections"] = True
                # Count non-empty lines in translation section
                section_lines = extract_section_lines(
                    lyr,
                    "### Translation (English)",
                    ["### Notes", "### Original (Indonesian)"],
                )
                non_empty_lines = [ln for ln in section_lines if ln.strip() != ""]
                if len(non_empty_lines) >= 5:
                    checks["lyrics_translation_has_5_nonempty_lines_in_translation"] = True
        except Exception:
            pass

    # 4) Memory defragmentation outputs
    analysis_json_path = os.path.join(output_dir, "defrag", "analysis.json")
    defrag_plan_md_path = os.path.join(output_dir, "defrag", "defragment-plan.md")
    verify_json_path = os.path.join(output_dir, "defrag", "verify.json")

    if file_exists_nonempty(analysis_json_path):
        analysis_obj, analysis_err = load_json_file(analysis_json_path)
        if analysis_obj is not None and isinstance(analysis_obj, dict):
            tiers_ok = all(k in analysis_obj for k in ["hot", "warm", "cold"])
            if tiers_ok:
                # hot/warm/cold can be list or dict
                tiers_types_ok = (
                    isinstance(analysis_obj["hot"], (list, dict)) and
                    isinstance(analysis_obj["warm"], (list, dict)) and
                    isinstance(analysis_obj["cold"], (list, dict))
                )
            else:
                tiers_types_ok = False
            totals_ok = True
            for k in ["total_files", "total_entries", "total_stale", "total_duplicates"]:
                v = analysis_obj.get(k)
                if not isinstance(v, int) or v < 0:
                    totals_ok = False
                    break
            checks["defrag_analysis_json_valid"] = bool(tiers_ok and tiers_types_ok and totals_ok)

    if file_exists_nonempty(defrag_plan_md_path):
        try:
            with open(defrag_plan_md_path, "r", encoding="utf-8") as f:
                dp = f.read()
            has_sections = all(s in dp for s in [
                "Memory Defragmentation Plan",
                "Merge Duplicates",
                "Archive Stale Content",
                "Format/Compact",
                "Execution",
            ])
            # Execution notes must reference backups-before-changes and archive-only (no deletion)
            exec_has_backup = ("backup" in dp.lower()) or ("backups" in dp.lower())
            exec_has_archive_only = ("archive-only" in dp.lower()) or ("no deletion" in dp.lower()) or ("never delete" in dp.lower()) or ("only archive" in dp.lower())
            if has_sections and exec_has_backup and exec_has_archive_only:
                checks["defrag_plan_md_has_required_sections_and_execution_notes"] = True
        except Exception:
            pass

    if file_exists_nonempty(verify_json_path):
        verify_obj, verify_err = load_json_file(verify_json_path)
        if verify_obj is not None and isinstance(verify_obj, dict):
            tf = verify_obj.get("total_files")
            vf = verify_obj.get("valid_files")
            if isinstance(tf, int) and isinstance(vf, int) and tf >= 0 and vf >= 0:
                checks["defrag_verify_json_valid"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if no outputs or none of the checks passed, reward must be 0.0
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()