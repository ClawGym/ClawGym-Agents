#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False until proven True)
    checks = {
        "audit_json_exists": False,
        "audit_json_is_valid_json": False,
        "audit_json_required_fields_present": False,
        "page_audited_is_string": False,
        "audit_date_valid_format": False,
        "overall_score_is_int": False,
        "factors_is_list_len_8": False,
        "factor_items_have_required_fields": False,
        "factor_names_match_expected": False,
        "factor_scores_int_and_in_range": False,
        "overall_equals_sum_of_factor_scores": False,
        "quick_wins_len_3": False,
        "quick_wins_items_nonempty_strings": False,
        "strategic_fixes_len_3": False,
        "strategic_fixes_items_nonempty_strings": False,
        "executive_summary_is_string": False,
        "executive_summary_sentence_count_4_to_6": False,
        "audit_md_exists": False,
        "audit_md_contains_required_markers": False,
    }

    expected_factor_names = [
        "Headline Clarity & Value Proposition",
        "Subheadline & Supporting Copy",
        "Social Proof",
        "Call-to-Action",
        "Visual Hierarchy & Scan Path",
        "Trust Signals & Objection Handling",
        "Page Speed & Mobile Experience",
        "Offer Clarity & Pricing Transparency",
    ]

    # Paths
    audit_json_path = os.path.join(output_dir, "audit.json")
    audit_md_path = os.path.join(output_dir, "audit.md")

    audit_data = None

    # Check existence of audit.json
    if os.path.isfile(audit_json_path):
        checks["audit_json_exists"] = True

        # Validate JSON parsing
        try:
            with open(audit_json_path, "r", encoding="utf-8") as f:
                audit_data = json.load(f)
            if isinstance(audit_data, dict):
                checks["audit_json_is_valid_json"] = True
        except Exception:
            audit_data = None

    # Validate JSON structure and fields
    factors = None
    factor_scores = []
    if checks["audit_json_is_valid_json"]:
        required_top_fields = [
            "page_audited",
            "audit_date",
            "overall_score",
            "factors",
            "quick_wins",
            "strategic_fixes",
            "executive_summary",
        ]
        missing = [k for k in required_top_fields if k not in audit_data]
        if not missing:
            checks["audit_json_required_fields_present"] = True

            # page_audited
            if isinstance(audit_data.get("page_audited"), str) and audit_data.get("page_audited").strip() != "":
                checks["page_audited_is_string"] = True

            # audit_date YYYY-MM-DD and valid calendar date
            audit_date = audit_data.get("audit_date")
            if isinstance(audit_date, str):
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", audit_date or ""):
                    try:
                        # Validate actual date
                        datetime.strptime(audit_date, "%Y-%m-%d")
                        checks["audit_date_valid_format"] = True
                    except Exception:
                        pass

            # overall_score int
            overall_score = audit_data.get("overall_score")
            if isinstance(overall_score, int):
                checks["overall_score_is_int"] = True

            # factors list length 8
            factors = audit_data.get("factors")
            if isinstance(factors, list) and len(factors) == 8:
                checks["factors_is_list_len_8"] = True

                # Validate each factor object
                factor_items_ok = True
                names = []
                factor_scores = []
                for item in factors:
                    if not isinstance(item, dict):
                        factor_items_ok = False
                        break
                    # required fields
                    if not all(k in item for k in ("name", "score", "rationale")):
                        factor_items_ok = False
                        break
                    # types
                    if not isinstance(item["name"], str):
                        factor_items_ok = False
                        break
                    if not isinstance(item["score"], int):
                        factor_items_ok = False
                        break
                    if not (isinstance(item["rationale"], str) and item["rationale"].strip() != ""):
                        factor_items_ok = False
                        break
                    names.append(item["name"])
                    factor_scores.append(item["score"])
                if factor_items_ok:
                    checks["factor_items_have_required_fields"] = True

                    # names match expected exactly (set equality and count 8 ensures no duplicates)
                    if set(names) == set(expected_factor_names) and len(names) == 8:
                        checks["factor_names_match_expected"] = True

                    # scores in range 0..10
                    if all(isinstance(s, int) and 0 <= s <= 10 for s in factor_scores):
                        checks["factor_scores_int_and_in_range"] = True

                    # overall equals sum of scores and within 0..80
                    if isinstance(overall_score, int):
                        if overall_score == sum(factor_scores) and 0 <= overall_score <= 80:
                            checks["overall_equals_sum_of_factor_scores"] = True

            # quick_wins
            qw = audit_data.get("quick_wins")
            if isinstance(qw, list) and len(qw) == 3:
                checks["quick_wins_len_3"] = True
                if all(isinstance(x, str) and x.strip() != "" for x in qw):
                    checks["quick_wins_items_nonempty_strings"] = True

            # strategic_fixes
            sf = audit_data.get("strategic_fixes")
            if isinstance(sf, list) and len(sf) == 3:
                checks["strategic_fixes_len_3"] = True
                if all(isinstance(x, str) and x.strip() != "" for x in sf):
                    checks["strategic_fixes_items_nonempty_strings"] = True

            # executive_summary
            es = audit_data.get("executive_summary")
            if isinstance(es, str) and es.strip() != "":
                checks["executive_summary_is_string"] = True
                # Count sentence-ending periods: compress ellipses to single period, then count '.'
                compressed = re.sub(r"\.{2,}", ".", es)
                period_count = compressed.count(".")
                if 4 <= period_count <= 6:
                    checks["executive_summary_sentence_count_4_to_6"] = True

    # audit.md checks
    if os.path.isfile(audit_md_path):
        checks["audit_md_exists"] = True
        try:
            with open(audit_md_path, "r", encoding="utf-8") as f:
                md_content = f.read()
            required_markers = [
                "Landing Page Conversion Audit",
                "Page audited:",
                "Audit date:",
                "Overall Score:",
                "Factor Breakdown",
                "Top 3 Quick Wins",
                "Top 3 Strategic Fixes",
                "Executive Summary",
            ]
            if all(marker in md_content for marker in required_markers):
                checks["audit_md_contains_required_markers"] = True
        except Exception:
            pass

    # Compute reward: fraction of checks passed; if nothing exists, reward should be 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if passed > 0 else 0.0

    # Output exactly one JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()