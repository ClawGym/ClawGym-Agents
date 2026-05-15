import json
import os
import sys
import csv

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # CSV checks
        "csv_exists": False,
        "csv_header_exact": False,
        "csv_min_rows": False,
        "csv_homeowners_not_available_in_restricted_states": False,
        "csv_has_umbrella_recommendation": False,
        "csv_discounts_include_drive_safe_and_save": False,
        "csv_discounts_include_steer_clear": False,
        # Proposal.md checks
        "proposal_exists": False,
        "proposal_min_headings": False,
        "proposal_contains_disclaimer_sentence_exact": False,
        "proposal_contains_agent_link": False,
        "proposal_contains_auto_terms_all_three": False,
        "proposal_contains_dwelling": False,
        "proposal_contains_drive_safe_and_save": False,
        "proposal_contains_steer_clear": False,
        "proposal_contains_claims_subsection": False,
        "proposal_contains_claims_channel_statefarm_com_claims": False,
        "proposal_contains_claims_channel_mobile_app": False,
        "proposal_contains_life_entity_statement": False,
        # Checklist checks
        "checklist_exists": False,
        "checklist_line_count_between_5_15": False,
        "checklist_agent_appointment_line_with_link": False,
        "checklist_contains_drive_safe_and_save": False,
        "checklist_separate_lines_auto_and_home": False,
        # Assumptions checks
        "assumptions_exists": False,
        "assumptions_valid_json_structure": False,
        "assumptions_disclaimer_true": False,
        "assumptions_customers_count_matches": False,
    }

    # Variables for cross-file consistency
    csv_rows_count = 0  # number of data rows (excluding header)
    proposal_headings_count = 0

    # 1) Validate coverage_recommendations.csv
    csv_path = os.path.join(output_dir, "coverage_recommendations.csv")
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        expected_header = [
            "customer_id",
            "state",
            "product_line",
            "recommended_coverages",
            "key_discounts",
            "notes",
        ]
        rows = []
        header = None
        try:
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                for idx, row in enumerate(reader):
                    if idx == 0:
                        header = row
                    else:
                        rows.append(row)
        except Exception:
            # If unable to read, keep checks as False
            rows = []
            header = None

        if header == expected_header:
            checks["csv_header_exact"] = True

        csv_rows_count = len(rows)
        if csv_rows_count >= 3:
            checks["csv_min_rows"] = True

        # Evaluate content-based checks only if there are rows
        if rows:
            # Check homeowners not available in CA/MA/RI with notes contains "not available"
            restricted_states = {"CA", "MA", "RI"}
            found_not_available = False
            found_umbrella = False
            discounts_concat = ""

            for r in rows:
                # Ensure row has expected number of columns
                if len(r) >= 6:
                    state = r[1].strip()
                    product_line = r[2].strip().lower()
                    recommended_coverages = r[3]
                    key_discounts = r[4]
                    notes = r[5]

                    # Restricted states + homeowners + "not available" in notes (case-insensitive)
                    if (state in restricted_states and product_line == "homeowners"
                            and ("not available" in notes.lower())):
                        found_not_available = True

                    # "umbrella" in recommended_coverages (case-insensitive)
                    if "umbrella" in recommended_coverages.lower():
                        found_umbrella = True

                    if isinstance(key_discounts, str):
                        discounts_concat += " " + key_discounts

            if found_not_available:
                checks["csv_homeowners_not_available_in_restricted_states"] = True
            if found_umbrella:
                checks["csv_has_umbrella_recommendation"] = True

            # Check for exact substrings in discounts across all rows (case-sensitive)
            if "Drive Safe & Save" in discounts_concat:
                checks["csv_discounts_include_drive_safe_and_save"] = True
            if "Steer Clear" in discounts_concat:
                checks["csv_discounts_include_steer_clear"] = True

    # 2) Validate proposal.md
    proposal_path = os.path.join(output_dir, "proposal.md")
    proposal_text = ""
    if os.path.isfile(proposal_path):
        checks["proposal_exists"] = True
        try:
            with open(proposal_path, "r", encoding="utf-8") as f:
                proposal_text = f.read()
        except Exception:
            proposal_text = ""

        # Count headings starting with "## "
        proposal_headings_count = sum(
            1 for line in proposal_text.splitlines() if line.startswith("## ")
        )
        if proposal_headings_count >= 3:
            checks["proposal_min_headings"] = True

        # Exact disclaimer sentence
        disclaimer_sentence = "This is informational guidance only; for quotes, purchases, or claims, contact State Farm directly via statefarm.com, the mobile app, or a licensed agent."
        if disclaimer_sentence in proposal_text:
            checks["proposal_contains_disclaimer_sentence_exact"] = True

        # Agent link
        if "statefarm.com/agent" in proposal_text:
            checks["proposal_contains_agent_link"] = True

        # Auto terms: Liability, Collision, Comprehensive must all appear at least once
        if ("Liability" in proposal_text and
            "Collision" in proposal_text and
            "Comprehensive" in proposal_text):
            checks["proposal_contains_auto_terms_all_three"] = True

        # Home term: Dwelling
        if "Dwelling" in proposal_text:
            checks["proposal_contains_dwelling"] = True

        # Discounts mentions
        if "Drive Safe & Save" in proposal_text:
            checks["proposal_contains_drive_safe_and_save"] = True
        if "Steer Clear" in proposal_text:
            checks["proposal_contains_steer_clear"] = True

        # Claims subsection indicator and channels
        if "Claims" in proposal_text:
            checks["proposal_contains_claims_subsection"] = True
        if "statefarm.com/claims" in proposal_text:
            checks["proposal_contains_claims_channel_statefarm_com_claims"] = True
        if "mobile app" in proposal_text:
            checks["proposal_contains_claims_channel_mobile_app"] = True

        # Life insurer entity nuance
        if "State Farm Life and Accident Assurance Company" in proposal_text:
            checks["proposal_contains_life_entity_statement"] = True

    # 3) Validate next_steps_checklist.txt
    checklist_path = os.path.join(output_dir, "next_steps_checklist.txt")
    checklist_lines = []
    if os.path.isfile(checklist_path):
        checks["checklist_exists"] = True
        try:
            with open(checklist_path, "r", encoding="utf-8") as f:
                checklist_lines = [ln.rstrip("\n") for ln in f.readlines()]
        except Exception:
            checklist_lines = []

        non_empty_lines = [ln for ln in checklist_lines if ln.strip() != ""]
        if 5 <= len(non_empty_lines) <= 15:
            checks["checklist_line_count_between_5_15"] = True

        # Line starting with "Agent appointment:" and includes "statefarm.com/agent"
        found_agent_line = False
        for ln in checklist_lines:
            if ln.startswith("Agent appointment:") and "statefarm.com/agent" in ln:
                found_agent_line = True
                break
        if found_agent_line:
            checks["checklist_agent_appointment_line_with_link"] = True

        # Contains "Drive Safe & Save"
        if any("Drive Safe & Save" in ln for ln in checklist_lines):
            checks["checklist_contains_drive_safe_and_save"] = True

        # Separate lines that mention gathering info for auto and home (check substrings on distinct lines, case-insensitive)
        auto_line_exists = False
        home_line_exists = False
        for ln in checklist_lines:
            low = ln.lower()
            if "auto" in low:
                auto_line_exists = True
            if "home" in low:
                home_line_exists = True
        # Ensure they appear on distinct lines
        if auto_line_exists and home_line_exists:
            # Additional check: ensure there exist at least two different lines (not the same line only)
            auto_lines_idx = [i for i, ln in enumerate(checklist_lines) if "auto" in ln.lower()]
            home_lines_idx = [i for i, ln in enumerate(checklist_lines) if "home" in ln.lower()]
            separate = False
            for ai in auto_lines_idx:
                for hi in home_lines_idx:
                    if ai != hi:
                        separate = True
                        break
                if separate:
                    break
            if separate:
                checks["checklist_separate_lines_auto_and_home"] = True

    # 4) Validate assumptions.json
    assumptions_path = os.path.join(output_dir, "assumptions.json")
    if os.path.isfile(assumptions_path):
        checks["assumptions_exists"] = True
        assumptions = None
        try:
            with open(assumptions_path, "r", encoding="utf-8") as f:
                assumptions = json.load(f)
        except Exception:
            assumptions = None

        if isinstance(assumptions, dict):
            # Validate required keys and types
            has_keys = all(k in assumptions for k in ["version", "customers_count", "disclaimer_acknowledged", "notes"])
            types_ok = (
                isinstance(assumptions.get("version"), str) and
                isinstance(assumptions.get("customers_count"), int) and
                isinstance(assumptions.get("disclaimer_acknowledged"), bool) and
                isinstance(assumptions.get("notes"), str)
            )
            if has_keys and types_ok:
                checks["assumptions_valid_json_structure"] = True

            if assumptions.get("disclaimer_acknowledged") is True:
                checks["assumptions_disclaimer_true"] = True

            # Match customers_count to CSV data rows and proposal headings
            if isinstance(assumptions.get("customers_count"), int):
                cc = assumptions.get("customers_count")
                if (cc == csv_rows_count) and (cc == proposal_headings_count):
                    checks["assumptions_customers_count_matches"] = True

    # Compute reward as fraction of passed checks; ensure 0.0 for no-op
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed_checks > 0:
        reward = passed_checks / total_checks
        # Clip to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()