import json
import os
import sys
import csv
import re

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = [row for row in reader]
        return rows
    except Exception:
        return None

def is_valid_date_yyyy_mm_dd(s):
    # Simple strict check for YYYY-MM-DD
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # JSON artifact checks
        "has_json": False,
        "json_required_keys": False,
        "json_frequency_and_date": False,
        "json_amounts": False,
        "json_stages_structure": False,
        "json_stages_values": False,

        # CSV artifact checks
        "has_csv": False,
        "csv_header_ok": False,
        "csv_rows_order_ok": False,
        "csv_draft_totals_ok": False,
        "csv_stage_status_match_json": False,

        # Notes artifact checks
        "has_notes": False,
        "notes_min_words": False,
        "notes_required_keywords": False,
    }

    # Expected spec constants
    expected_frequency = "monthly"
    expected_as_of_date = "2026-02-01"
    expected_initial_amount = "5000.00"
    expected_amended_amount = "4500.00"
    expected_stages = [
        {"stage": "generated_draft", "status": "draft"},
        {"stage": "submitted_original", "status": "submitted"},
        {"stage": "cancelled_original", "status": "cancelled"},
        {"stage": "amended_draft", "status": "draft"},
        {"stage": "submitted_amended", "status": "submitted"},
    ]

    # Paths
    json_path = os.path.join(output_dir, "journal_lifecycle.json")
    csv_path = os.path.join(output_dir, "summary.csv")
    notes_path = os.path.join(output_dir, "notes.md")

    # -----------------------
    # Validate JSON artifact
    # -----------------------
    jl = None
    if os.path.isfile(json_path):
        checks["has_json"] = True
        jl = load_json(json_path)

    if checks["has_json"] and isinstance(jl, dict):
        # Required keys presence and basic types
        required_keys = [
            "company_id", "template_name", "frequency", "as_of_date",
            "initial_amount", "amended_amount", "stages"
        ]
        has_all = all(k in jl for k in required_keys)
        types_ok = (
            isinstance(jl.get("company_id"), str) and
            isinstance(jl.get("template_name"), str) and
            isinstance(jl.get("frequency"), str) and
            isinstance(jl.get("as_of_date"), str) and
            isinstance(jl.get("initial_amount"), str) and
            isinstance(jl.get("amended_amount"), str) and
            isinstance(jl.get("stages"), list)
        )
        checks["json_required_keys"] = has_all and types_ok

        # frequency and as_of_date
        freq_ok = jl.get("frequency") == expected_frequency
        date_ok = jl.get("as_of_date") == expected_as_of_date and is_valid_date_yyyy_mm_dd(jl.get("as_of_date", ""))
        checks["json_frequency_and_date"] = bool(freq_ok and date_ok)

        # amounts
        init_amt_ok = jl.get("initial_amount") == expected_initial_amount
        amend_amt_ok = jl.get("amended_amount") == expected_amended_amount
        checks["json_amounts"] = bool(init_amt_ok and amend_amt_ok)

        # stages structure and values
        stages = jl.get("stages") if isinstance(jl.get("stages"), list) else []
        structure_ok = len(stages) == 5 and all(isinstance(s, dict) for s in stages)
        if structure_ok:
            names_ok = True
            status_ok = True
            order_ok = True
            draft_values_ok = True

            # Check order, stage names and statuses
            for idx, expected in enumerate(expected_stages):
                s = stages[idx]
                if s.get("stage") != expected["stage"]:
                    order_ok = False
                    names_ok = False
                if s.get("status") != expected["status"]:
                    status_ok = False

            # Check totals for draft stages
            # generated_draft
            gd = stages[0]
            if gd.get("status") == "draft":
                td = gd.get("total_debit")
                tc = gd.get("total_credit")
                if not (td == expected_initial_amount and tc == expected_initial_amount):
                    draft_values_ok = False
                # also ensure equals initial_amount field
                if jl.get("initial_amount") != expected_initial_amount:
                    draft_values_ok = False
            else:
                draft_values_ok = False

            # amended_draft
            ad = stages[3]
            if ad.get("status") == "draft":
                td2 = ad.get("total_debit")
                tc2 = ad.get("total_credit")
                if not (td2 == expected_amended_amount and tc2 == expected_amended_amount):
                    draft_values_ok = False
                # ensure equals amended_amount field
                if jl.get("amended_amount") != expected_amended_amount:
                    draft_values_ok = False
            else:
                draft_values_ok = False

            checks["json_stages_structure"] = bool(structure_ok and order_ok and names_ok)
            checks["json_stages_values"] = bool(status_ok and draft_values_ok)
        else:
            checks["json_stages_structure"] = False
            checks["json_stages_values"] = False

    # -----------------------
    # Validate CSV artifact
    # -----------------------
    csv_rows = None
    if os.path.isfile(csv_path):
        checks["has_csv"] = True
        csv_rows = read_csv_rows(csv_path)

    if checks["has_csv"] and isinstance(csv_rows, list) and len(csv_rows) >= 1:
        header = csv_rows[0]
        header_joined = ",".join([h.strip() for h in header])
        checks["csv_header_ok"] = (header_joined == "stage,status,total_debit,total_credit")

        data_rows = csv_rows[1:]
        # At least 5 data rows
        if len(data_rows) >= 5:
            # Check order of first 5 rows
            order_ok = True
            draft_totals_ok = True
            stage_status_match = True

            # If JSON present, use JSON stages for status matching; else cannot pass this check
            json_for_match = jl if checks["has_json"] and isinstance(jl, dict) and isinstance(jl.get("stages"), list) and len(jl["stages"]) >= 5 else None

            for i in range(5):
                row = data_rows[i]
                # Ensure row has at least 2 columns
                stage = row[0].strip() if len(row) > 0 else ""
                status = row[1].strip() if len(row) > 1 else ""
                td = row[2].strip() if len(row) > 2 else ""
                tc = row[3].strip() if len(row) > 3 else ""

                if stage != expected_stages[i]["stage"]:
                    order_ok = False

                # For draft totals checks
                if stage == "generated_draft":
                    if not (td == expected_initial_amount and tc == expected_initial_amount):
                        draft_totals_ok = False
                if stage == "amended_draft":
                    if not (td == expected_amended_amount and tc == expected_amended_amount):
                        draft_totals_ok = False

                # Match status to JSON
                if json_for_match is not None:
                    json_status = json_for_match["stages"][i].get("status", "")
                    if status != json_status:
                        stage_status_match = False
                else:
                    stage_status_match = False

            checks["csv_rows_order_ok"] = order_ok
            checks["csv_draft_totals_ok"] = draft_totals_ok
            checks["csv_stage_status_match_json"] = stage_status_match
        else:
            checks["csv_rows_order_ok"] = False
            checks["csv_draft_totals_ok"] = False
            checks["csv_stage_status_match_json"] = False
    # -----------------------
    # Validate notes artifact
    # -----------------------
    notes_text = None
    if os.path.isfile(notes_path):
        checks["has_notes"] = True
        notes_text = read_text(notes_path)

    if checks["has_notes"] and isinstance(notes_text, str):
        # Word count (split by whitespace)
        words = [w for w in notes_text.strip().split() if w.strip()]
        checks["notes_min_words"] = len(words) >= 200

        lower = notes_text.lower()
        required_keywords = ["double-entry", "recurring template", "submit", "cancel", "amend"]
        checks["notes_required_keywords"] = all(k in lower for k in required_keywords)

    # -----------------------
    # Aggregate reward
    # -----------------------
    json_group_pass = (
        checks["has_json"] and
        checks["json_required_keys"] and
        checks["json_frequency_and_date"] and
        checks["json_amounts"] and
        checks["json_stages_structure"] and
        checks["json_stages_values"]
    )

    csv_group_pass = (
        checks["has_csv"] and
        checks["csv_header_ok"] and
        checks["csv_rows_order_ok"] and
        checks["csv_draft_totals_ok"] and
        checks["csv_stage_status_match_json"]
    )

    notes_group_pass = (
        checks["has_notes"] and
        checks["notes_min_words"] and
        checks["notes_required_keywords"]
    )

    # No-op baseline: if output dir missing or no artifacts, reward = 0.0
    any_artifact = checks["has_json"] or checks["has_csv"] or checks["has_notes"]
    if not any_artifact:
        reward = 0.0
    else:
        # Average across three groups
        passed_groups = sum([1 if json_group_pass else 0,
                             1 if csv_group_pass else 0,
                             1 if notes_group_pass else 0])
        reward = passed_groups / 3.0

    # Print single JSON line
    result = {
        "reward": round(reward, 6),

        # individual checks
        **checks,

        # group summaries
        "json_group_pass": json_group_pass,
        "csv_group_pass": csv_group_pass,
        "notes_group_pass": notes_group_pass,
    }
    print(json.dumps(result))

if __name__ == "__main__":
    main()