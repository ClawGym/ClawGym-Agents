import json
import os
import sys

def read_text_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def count_words(text):
    if not text:
        return 0
    # Simple whitespace token count
    return len([t for t in text.split() if t.strip()])

def has_sequence_in_order(lines, first_line, second_line):
    try:
        idx1 = lines.index(first_line)
        idx2 = lines.index(second_line)
        return idx1 < idx2
    except ValueError:
        return False

def check_ops_sequence(ops_list):
    if not isinstance(ops_list, list):
        return False
    try:
        idx_html = ops_list.index("html_to_pdf")
        idx_text = ops_list.index("pdf_to_text")
        return idx_html < idx_text
    except ValueError:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    policy_text_path = os.path.join(output_dir, "text", "policy_text.txt")
    notes_text_path = os.path.join(output_dir, "text", "notes_text.txt")
    merged_text_path = os.path.join(output_dir, "text", "merged_text.txt")
    combined_html_path = os.path.join(output_dir, "html", "combined.html")
    exec_summary_path = os.path.join(output_dir, "report", "executive_summary.md")
    manifest_path = os.path.join(output_dir, "report", "manifest.json")

    checks = {
        "exists_policy_text": False,
        "exists_notes_text": False,
        "exists_merged_text": False,
        "exists_combined_html": False,
        "exists_executive_summary": False,
        "exists_manifest": False,
        "no_pdfs_in_output": False,
        "policy_text_has_acme_corp_code_of_conduct": False,
        "policy_text_has_data_handling": False,
        "notes_text_has_planning_meeting": False,
        "notes_text_has_action_items": False,
        "notes_text_has_okr_alignment": False,
        "merged_has_headers_in_order": False,
        "merged_has_anchors_from_both": False,
        "combined_html_nonempty_and_title": False,
        "combined_html_has_section_titles": False,
        "combined_html_has_anchors_from_both": False,
        "summary_word_count_at_least_100": False,
        "summary_mentions_company_policy_and_meeting": False,
        "manifest_json_valid": False,
        "manifest_has_required_keys": False,
        "manifest_sources_correct": False,
        "manifest_operations_policy_sequence": False,
        "manifest_operations_notes_sequence": False,
        "manifest_used_pdf_pipeline_true": False,
        "manifest_merge_strategy_correct": False,
        "manifest_summary_word_count_ge_100": False,
    }

    # Existence checks
    if os.path.isfile(policy_text_path):
        checks["exists_policy_text"] = True
    if os.path.isfile(notes_text_path):
        checks["exists_notes_text"] = True
    if os.path.isfile(merged_text_path):
        checks["exists_merged_text"] = True
    if os.path.isfile(combined_html_path):
        checks["exists_combined_html"] = True
    if os.path.isfile(exec_summary_path):
        checks["exists_executive_summary"] = True
    if os.path.isfile(manifest_path):
        checks["exists_manifest"] = True

    # No PDFs in output (only evaluate if output directory exists to avoid awarding on no-op)
    if os.path.isdir(output_dir):
        found_pdf = False
        for root, dirs, files in os.walk(output_dir):
            for fn in files:
                if fn.lower().endswith(".pdf"):
                    found_pdf = True
                    break
            if found_pdf:
                break
        if not found_pdf:
            checks["no_pdfs_in_output"] = True

    # Content checks for policy_text.txt
    if checks["exists_policy_text"]:
        policy_text = read_text_file(policy_text_path) or ""
        if "Acme Corp Code of Conduct" in policy_text:
            checks["policy_text_has_acme_corp_code_of_conduct"] = True
        if "Data Handling" in policy_text:
            checks["policy_text_has_data_handling"] = True

    # Content checks for notes_text.txt
    if checks["exists_notes_text"]:
        notes_text = read_text_file(notes_text_path) or ""
        if "Planning Meeting" in notes_text:
            checks["notes_text_has_planning_meeting"] = True
        if "Action items" in notes_text:
            checks["notes_text_has_action_items"] = True
        if "OKR alignment" in notes_text:
            checks["notes_text_has_okr_alignment"] = True

    # Merged text checks
    if checks["exists_merged_text"]:
        merged_text = read_text_file(merged_text_path) or ""
        lines = merged_text.splitlines()
        header_policy = "=== COMPANY POLICY ==="
        header_notes = "=== MEETING NOTES ==="
        if has_sequence_in_order(lines, header_policy, header_notes):
            checks["merged_has_headers_in_order"] = True
        # Anchors from both sources in merged
        has_policy_anchor = ("Code of Conduct" in merged_text) or ("Acme Corp Code of Conduct" in merged_text)
        has_notes_anchor = ("Action items" in merged_text) or ("OKR alignment" in merged_text) or ("Planning Meeting" in merged_text)
        if has_policy_anchor and has_notes_anchor:
            checks["merged_has_anchors_from_both"] = True

    # Combined HTML checks
    if checks["exists_combined_html"]:
        html_text = read_text_file(combined_html_path) or ""
        if html_text.strip() and ("Combined Document" in html_text):
            checks["combined_html_nonempty_and_title"] = True
        if ("Company Policy" in html_text) and ("Meeting Notes" in html_text):
            checks["combined_html_has_section_titles"] = True
        has_policy_anchor_html = ("Acme Corp Code of Conduct" in html_text) or ("Code of Conduct" in html_text) or ("Data Handling" in html_text)
        has_notes_anchor_html = ("Planning Meeting" in html_text) or ("Action items" in html_text) or ("OKR alignment" in html_text)
        if has_policy_anchor_html and has_notes_anchor_html:
            checks["combined_html_has_anchors_from_both"] = True

    # Executive summary checks
    if checks["exists_executive_summary"]:
        summary_text = read_text_file(exec_summary_path) or ""
        wc = count_words(summary_text)
        if wc >= 100:
            checks["summary_word_count_at_least_100"] = True
        st_lower = summary_text.lower()
        if ("company policy" in st_lower) and ("meeting" in st_lower):
            checks["summary_mentions_company_policy_and_meeting"] = True

    # Manifest checks
    manifest = None
    if checks["exists_manifest"]:
        text = read_text_file(manifest_path)
        if text is not None:
            try:
                manifest = json.loads(text)
                checks["manifest_json_valid"] = True
            except Exception:
                manifest = None

    if manifest is not None:
        # Required keys
        required_keys = {"sources", "operations", "used_pdf_pipeline", "merge_strategy", "summary"}
        if all(k in manifest for k in required_keys):
            checks["manifest_has_required_keys"] = True

            # Sources correctness
            sources = manifest.get("sources", {})
            if (
                isinstance(sources, dict)
                and sources.get("policy_html") == "input/company_policy.html"
                and sources.get("notes_html") == "input/meeting_notes.html"
            ):
                checks["manifest_sources_correct"] = True

            # Operations sequences
            operations = manifest.get("operations", {})
            if isinstance(operations, dict):
                policy_ops = operations.get("policy")
                notes_ops = operations.get("notes")
                if check_ops_sequence(policy_ops):
                    checks["manifest_operations_policy_sequence"] = True
                if check_ops_sequence(notes_ops):
                    checks["manifest_operations_notes_sequence"] = True

            # used_pdf_pipeline true
            if manifest.get("used_pdf_pipeline") is True:
                checks["manifest_used_pdf_pipeline_true"] = True

            # merge_strategy correct
            if manifest.get("merge_strategy") == "concatenate_with_headers":
                checks["manifest_merge_strategy_correct"] = True

            # summary.word_count >= 100
            summary_obj = manifest.get("summary")
            wc_val = None
            if isinstance(summary_obj, dict):
                wc_val = summary_obj.get("word_count")
            if isinstance(wc_val, int) and wc_val >= 100:
                checks["manifest_summary_word_count_ge_100"] = True

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure 0.0 for no-op baseline when output is empty/missing required artifacts
    # If none of the existence checks are true, set reward to 0.0
    if not any(checks[k] for k in [
        "exists_policy_text",
        "exists_notes_text",
        "exists_merged_text",
        "exists_combined_html",
        "exists_executive_summary",
        "exists_manifest"
    ]):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()