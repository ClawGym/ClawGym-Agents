import json
import os
import sys
import re

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected constants
    expected_features = [
        "Event registration with custom forms",
        "Agenda scheduling and speaker management",
        "QR-based attendee check-in",
        "Live polling and Q&A during sessions",
        "Post-event analytics and feedback collection",
    ]
    expected_feature_set = set(expected_features)

    expected_metadata_fields = {
        "brand": "mesagona",
        "tagline": "Events from planning to post-mortem",
        "company": "Netsnek e.U.",
        "domain": "event-management",
        "website": "https://netsnek.com",
        "license": "All rights reserved",
    }

    positioning_substrings = [
        "For event and conference managers who need to streamline registration to analytics across the event lifecycle",
        "Mesagona is a",
        "event management platform",
        "that delivers end-to-end workflows from registration to post-event insights",
        "Unlike manual spreadsheets and disjointed point tools, we provide integrated check-in, live engagement, and analytics in one system",
    ]

    checks = {
        # Raw features file checks
        "features_txt_exists": False,
        "features_txt_five_lines": False,
        "features_txt_match_expected_set": False,

        # Raw metadata JSON checks
        "metadata_json_exists": False,
        "metadata_json_valid": False,
        "metadata_min_fields_ok": False,
        "metadata_features_match_expected": False,

        # One-pager checks
        "one_pager_exists": False,
        "title_has_phrase": False,
        "product_summary_section_present": False,
        "summary_word_count_ok": False,
        "core_features_section_has_all_five": False,
        "positioning_section_single_line_and_substrings_ok": False,
        "call_to_action_section_has_phrase": False,

        # Checklist checks
        "checklist_exists": False,
        "checklist_min_lines_ok": False,

        # Rubric-report-only (non-scoring) signals
        "rubric_signal_summary_mentions_qr_or_live": False,
        "rubric_signal_has_all_required_headings": False,
    }

    # Helper: read lines safely
    def read_lines(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().splitlines()
        except Exception:
            return None

    # Helper: get section lines between headings
    def get_section(lines, heading_name):
        # returns (exists, section_lines, start_index, end_index)
        start = None
        for i, line in enumerate(lines):
            if line.strip() == f"## {heading_name}":
                start = i
                break
        if start is None:
            return False, [], None, None
        # find next heading starting with "## "
        end = None
        for j in range(start + 1, len(lines)):
            if lines[j].startswith("## "):
                end = j
                break
        if end is None:
            end = len(lines)
        # section content is lines between start+1 and end-1 inclusive
        content = lines[start + 1:end]
        return True, content, start, end

    # 1) Validate raw brand outputs
    features_txt_path = os.path.join(output_dir, "raw", "mesagona_features.txt")
    if os.path.isfile(features_txt_path):
        checks["features_txt_exists"] = True
        flines = read_lines(features_txt_path) or []
        # Count non-empty lines
        non_empty = [ln for ln in flines if ln.strip() != ""]
        if len(non_empty) == 5:
            checks["features_txt_five_lines"] = True
            # Verify each line exactly matches one of expected strings and set equality
            line_set = set(non_empty)
            if line_set == expected_feature_set:
                checks["features_txt_match_expected_set"] = True

    metadata_json_path = os.path.join(output_dir, "raw", "mesagona_metadata.json")
    metadata_obj = None
    if os.path.isfile(metadata_json_path):
        checks["metadata_json_exists"] = True
        try:
            with open(metadata_json_path, "r", encoding="utf-8") as f:
                metadata_obj = json.load(f)
            if isinstance(metadata_obj, dict):
                checks["metadata_json_valid"] = True
                # Check minimal required fields
                min_fields_ok = True
                for k, v in expected_metadata_fields.items():
                    if k not in metadata_obj or metadata_obj[k] != v:
                        min_fields_ok = False
                        break
                checks["metadata_min_fields_ok"] = min_fields_ok
                # Check features array equality (order-insensitive)
                feats = metadata_obj.get("features")
                if isinstance(feats, list):
                    # Ensure all items are strings
                    if all(isinstance(x, str) for x in feats):
                        if set(feats) == expected_feature_set and len(feats) == 5:
                            checks["metadata_features_match_expected"] = True
        except Exception:
            # keep as False
            pass

    # 2) Validate the one-pager
    one_pager_path = os.path.join(output_dir, "mesagona_one_pager.md")
    one_lines = None
    if os.path.isfile(one_pager_path):
        checks["one_pager_exists"] = True
        one_lines = read_lines(one_pager_path) or []
        full_text = "\n".join(one_lines)

        # Title phrase presence anywhere
        title_phrase = "Mesagona — Events from planning to post-mortem"
        if title_phrase in full_text:
            checks["title_has_phrase"] = True

        # Product Summary section and word count
        exists_ps, ps_content, _, _ = get_section(one_lines, "Product Summary")
        if exists_ps:
            checks["product_summary_section_present"] = True
            # Count words in ps_content
            ps_text = "\n".join(ps_content).strip()
            # Use regex word boundaries to count words
            words = re.findall(r"\b\w+\b", ps_text)
            if len(words) <= 100:
                checks["summary_word_count_ok"] = True
            # Rubric signal: mentions QR or live in summary
            lower_ps = ps_text.lower()
            if ("qr" in lower_ps) or ("live polling" in lower_ps) or ("q&a" in lower_ps):
                checks["rubric_signal_summary_mentions_qr_or_live"] = True

        # Core Features section and presence of all five features
        exists_cf, cf_content, _, _ = get_section(one_lines, "Core Features")
        cf_has_all = False
        if exists_cf:
            # For each expected feature, ensure it appears exactly (case-sensitive) in at least one line
            present = []
            for feat in expected_features:
                found_feat = any(feat in ln for ln in cf_content)
                present.append(found_feat)
            if all(present):
                cf_has_all = True
        checks["core_features_section_has_all_five"] = cf_has_all

        # Positioning section
        exists_pos, pos_content, _, _ = get_section(one_lines, "Positioning")
        pos_ok = False
        if exists_pos:
            # Filter non-empty, non-heading lines
            meaningful = [ln.strip() for ln in pos_content if ln.strip() and not ln.strip().startswith("#")]
            if len(meaningful) == 1:
                line = meaningful[0]
                # Check substrings in order
                idx = -1
                in_order = True
                for sub in positioning_substrings:
                    nxt = line.find(sub, idx + 1)
                    if nxt == -1 or nxt <= idx:
                        in_order = False
                        break
                    idx = nxt
                if in_order:
                    pos_ok = True
        checks["positioning_section_single_line_and_substrings_ok"] = pos_ok

        # Call to Action section
        exists_cta, cta_content, _, _ = get_section(one_lines, "Call to Action")
        cta_ok = False
        if exists_cta:
            phrase = "Contact Netsnek e.U."
            if any(phrase in ln for ln in cta_content):
                cta_ok = True
        checks["call_to_action_section_has_phrase"] = cta_ok

        # Rubric signal: has all required headings present
        checks["rubric_signal_has_all_required_headings"] = (
            checks["product_summary_section_present"]
            and exists_cf
            and exists_pos
            and exists_cta
        )

    # 3) Validate the checklist
    checklist_path = os.path.join(output_dir, "checklist.txt")
    if os.path.isfile(checklist_path):
        checks["checklist_exists"] = True
        clines = read_lines(checklist_path) or []
        count_checked = sum(1 for ln in clines if ln.startswith("[x]"))
        if count_checked >= 5:
            checks["checklist_min_lines_ok"] = True

    # Compute reward: only objective checks contribute
    objective_keys = [
        "features_txt_exists",
        "features_txt_five_lines",
        "features_txt_match_expected_set",
        "metadata_json_exists",
        "metadata_json_valid",
        "metadata_min_fields_ok",
        "metadata_features_match_expected",
        "one_pager_exists",
        "title_has_phrase",
        "product_summary_section_present",
        "summary_word_count_ok",
        "core_features_section_has_all_five",
        "positioning_section_single_line_and_substrings_ok",
        "call_to_action_section_has_phrase",
        "checklist_exists",
        "checklist_min_lines_ok",
    ]
    total_objective = len(objective_keys)
    passed_objective = sum(1 for k in objective_keys if checks.get(k, False))
    reward = passed_objective / total_objective if total_objective > 0 else 0.0

    # Ensure within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()