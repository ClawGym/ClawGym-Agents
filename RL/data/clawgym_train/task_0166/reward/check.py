import json
import os
import sys
import csv

def read_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
                items.append(obj)
            except Exception:
                raise
    return items

def is_int_like(x):
    if isinstance(x, bool):
        return False
    if isinstance(x, int):
        return True
    if isinstance(x, float):
        return x.is_integer()
    return False

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def risk_from_policy(lipinski_viol, veber_viol, qed, pains):
    if lipinski_viol == 0 and pains == 0 and (qed is not None and qed > 0.5):
        return "Low"
    if lipinski_viol >= 3 or pains > 0 or veber_viol == 2:
        return "High"
    return "Medium"

def safe_float_equal(a, b, tol=1e-6):
    return abs(a - b) <= tol

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        "profiles_exists": False,
        "summary_exists": False,
        "invalid_exists_and_header": False,
        "invalid_reasons_nonempty_and_rows_from_input": False,
        "profiles_valid_jsonl_format_types": False,
        "profiles_unique_candidate_ids": False,
        "risk_policy_consistent": False,
        "profiles_match_validity_from_input": False,
        "summary_shape_valid": False,
        "summary_counts_match_profiles": False,
        "summary_top3_sorted_and_matches_profiles": False
    }

    profiles_path = os.path.join(output_dir, "profiles.jsonl")
    summary_path = os.path.join(output_dir, "summary.json")
    invalid_path = os.path.join(output_dir, "invalid.csv")
    input_csv_path = os.path.join(input_dir, "candidates.csv")

    profiles = []
    profiles_by_id = {}
    profiles_risk_counts = {"Low": 0, "Medium": 0, "High": 0}
    parsed_profiles_ok = True
    profiles_types_ok = True
    risk_consistent_ok = True
    unique_ids_ok = True

    # Read input rows
    input_rows = []
    input_rows_pairs = set()
    input_rows_by_id = {}
    input_loaded = False
    try:
        if os.path.isfile(input_csv_path):
            with open(input_csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    # Normalize missing keys to empty string
                    cid = (r.get("candidate_id") or "").strip()
                    smi = (r.get("smiles") or "").strip()
                    name = r.get("name")  # not used
                    input_rows.append({"candidate_id": cid, "smiles": smi, "name": name})
                    input_rows_pairs.add((cid, smi))
                    # Track seen candidate_ids (may be duplicates; store set of smiles)
                    input_rows_by_id.setdefault(cid, set()).add(smi)
            input_loaded = True
    except Exception:
        input_loaded = False

    # Parse invalid.csv
    invalid_rows = []
    invalid_header_ok = False
    invalid_rows_reason_ok = True
    invalid_rows_in_input_ok = True
    invalid_cids_from_invalid_csv = set()
    try:
        if os.path.isfile(invalid_path):
            with open(invalid_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header is not None and [h.strip() for h in header] == ["candidate_id", "smiles", "reason"]:
                    invalid_header_ok = True
                    for row in reader:
                        # Pad rows if short
                        while len(row) < 3:
                            row.append("")
                        cid = (row[0] or "").strip()
                        smi = (row[1] or "").strip()
                        reason = (row[2] or "").strip()
                        invalid_rows.append({"candidate_id": cid, "smiles": smi, "reason": reason})
                        if reason == "":
                            invalid_rows_reason_ok = False
                        if input_loaded and (cid, smi) not in input_rows_pairs:
                            invalid_rows_in_input_ok = False
                        invalid_cids_from_invalid_csv.add(cid)
                else:
                    invalid_header_ok = False
        # Set check for invalid header
        checks["invalid_exists_and_header"] = os.path.isfile(invalid_path) and invalid_header_ok
        # Reasons and membership
        if checks["invalid_exists_and_header"]:
            checks["invalid_reasons_nonempty_and_rows_from_input"] = invalid_rows_reason_ok and invalid_rows_in_input_ok
    except Exception:
        # If invalid.csv cannot be parsed, keep checks as False
        pass

    # Profiles parsing
    if os.path.isfile(profiles_path):
        checks["profiles_exists"] = True
        try:
            profiles = read_jsonl(profiles_path)
        except Exception:
            parsed_profiles_ok = False
            profiles_types_ok = False
            risk_consistent_ok = False
            unique_ids_ok = False

        if parsed_profiles_ok:
            # Validate each profile object
            required_top_keys = {"candidate_id", "smiles", "lipinski_viol", "veber_viol", "qed", "pains", "risk", "props"}
            required_props_keys = {"mw", "logp", "tpsa", "hbd", "hba", "rotb", "rings", "arom"}
            seen_ids = set()
            for obj in profiles:
                # Keys presence
                if not isinstance(obj, dict):
                    profiles_types_ok = False
                    break
                if not required_top_keys.issubset(obj.keys()):
                    profiles_types_ok = False
                    break
                # Types and ranges
                cid = obj.get("candidate_id")
                smi = obj.get("smiles")
                lip = obj.get("lipinski_viol")
                veb = obj.get("veber_viol")
                qed = obj.get("qed")
                pains = obj.get("pains")
                risk = obj.get("risk")
                props = obj.get("props")

                # candidate_id and smiles must be non-empty strings
                if not isinstance(cid, str) or cid is None or cid == "":
                    profiles_types_ok = False
                    break
                if not isinstance(smi, str) or smi is None or smi == "":
                    profiles_types_ok = False
                    break

                # Integer-like fields and ranges
                if not is_int_like(lip) or int(lip) < 0 or int(lip) > 4:
                    profiles_types_ok = False
                    break
                if not is_int_like(veb) or int(veb) < 0 or int(veb) > 2:
                    profiles_types_ok = False
                    break
                if not is_number(qed) or float(qed) < 0.0 or float(qed) > 1.0:
                    profiles_types_ok = False
                    break
                if not is_int_like(pains) or int(pains) < 0:
                    profiles_types_ok = False
                    break
                if risk not in {"Low", "Medium", "High"}:
                    profiles_types_ok = False
                    break
                if not isinstance(props, dict) or not required_props_keys.issubset(props.keys()):
                    profiles_types_ok = False
                    break

                # Props numeric types
                # Float-like numbers for mw, logp, tpsa
                for k in ["mw", "logp", "tpsa"]:
                    if not is_number(props.get(k)):
                        profiles_types_ok = False
                        break
                if not profiles_types_ok:
                    break
                # Int-like for hbd, hba, rotb, rings, arom
                for k in ["hbd", "hba", "rotb", "rings", "arom"]:
                    if not is_int_like(props.get(k)):
                        profiles_types_ok = False
                        break
                if not profiles_types_ok:
                    break

                # Risk policy consistency
                expected_risk = risk_from_policy(int(lip), int(veb), float(qed), int(pains))
                if expected_risk != risk:
                    risk_consistent_ok = False

                # Unique candidate_ids
                if cid in seen_ids:
                    unique_ids_ok = False
                seen_ids.add(cid)

                # Build map for later
                profiles_by_id[cid] = {
                    "obj": obj,
                    "qed": float(qed),
                    "risk": risk
                }

                # Count risks if valid so far
                if risk in profiles_risk_counts:
                    profiles_risk_counts[risk] += 1

            checks["profiles_valid_jsonl_format_types"] = profiles_types_ok
            checks["profiles_unique_candidate_ids"] = unique_ids_ok
            checks["risk_policy_consistent"] = risk_consistent_ok

    # Determine valid vs invalid based on input and invalid.csv
    valid_ids_expected = set()
    invalid_due_to_missing_fields_pairs = set()
    valid_input_loaded = False
    if input_loaded and checks["invalid_exists_and_header"]:
        for r in input_rows:
            cid = r.get("candidate_id", "")
            smi = r.get("smiles", "")
            missing = (cid == "" or smi == "")
            if missing:
                invalid_due_to_missing_fields_pairs.add((cid, smi))
            # A row is invalid if missing fields OR candidate_id appears in invalid.csv
            if (not missing) and (cid not in invalid_cids_from_invalid_csv):
                valid_ids_expected.add(cid)
        valid_input_loaded = True
    elif input_loaded:
        # If invalid.csv missing or header bad, we can still compute valid by missing fields only
        for r in input_rows:
            cid = r.get("candidate_id", "")
            smi = r.get("smiles", "")
            if cid != "" and smi != "":
                valid_ids_expected.add(cid)
        valid_input_loaded = True

    # Check that invalid.csv includes all rows with missing fields
    if checks["invalid_exists_and_header"] and input_loaded:
        # Build set of pairs from invalid.csv
        invalid_pairs_from_file = set((row["candidate_id"], row["smiles"]) for row in invalid_rows)
        missing_in_invalid_file = [pair for pair in invalid_due_to_missing_fields_pairs if pair not in invalid_pairs_from_file]
        # If any missing required-invalid rows are not captured, reasons check fails
        if missing_in_invalid_file:
            checks["invalid_reasons_nonempty_and_rows_from_input"] = False

    # Cross-check profiles vs expected validity
    profiles_vs_valid_ok = False
    if checks["profiles_exists"] and parsed_profiles_ok and valid_input_loaded:
        prof_ids = set(profiles_by_id.keys())
        # No invalid ids should appear in profiles
        if checks["invalid_exists_and_header"]:
            invalid_ids = set(invalid_cids_from_invalid_csv)
        else:
            invalid_ids = set()
        # Check exact match: profiles ids equal expected valid ids
        profiles_vs_valid_ok = (prof_ids == valid_ids_expected)
        # Additional: ensure count matches
        profiles_vs_valid_ok = profiles_vs_valid_ok and (len(prof_ids) == len(valid_ids_expected))
        # Ensure no invalid id leaked
        profiles_vs_valid_ok = profiles_vs_valid_ok and not (prof_ids & invalid_ids)
    checks["profiles_match_validity_from_input"] = profiles_vs_valid_ok

    # Summary checks
    summary = None
    summary_shape_ok = False
    summary_counts_ok = False
    summary_top3_ok = False
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            if isinstance(summary, dict) and \
               "total_valid" in summary and \
               "risk_counts" in summary and \
               "top_3_by_qed" in summary and \
               isinstance(summary["total_valid"], int) and \
               isinstance(summary["risk_counts"], dict) and \
               all(k in summary["risk_counts"] and isinstance(summary["risk_counts"][k], int) for k in ["Low", "Medium", "High"]) and \
               isinstance(summary["top_3_by_qed"], list):
                summary_shape_ok = True
        except Exception:
            summary_shape_ok = False

        if summary_shape_ok and checks["profiles_exists"] and parsed_profiles_ok:
            # Counts
            total_lines = len(profiles_by_id)
            rc = summary["risk_counts"]
            counts_match = (summary["total_valid"] == total_lines) and \
                           (rc.get("Low", 0) == profiles_risk_counts["Low"]) and \
                           (rc.get("Medium", 0) == profiles_risk_counts["Medium"]) and \
                           (rc.get("High", 0) == profiles_risk_counts["High"])
            summary_counts_ok = counts_match

            # Top 3 by qed
            included = summary["top_3_by_qed"]
            # Length must equal min(3, total_valid)
            if summary["total_valid"] == total_lines and len(included) == min(3, total_lines):
                # Build list of (cid, qed) from profiles
                all_qeds = [(cid, data["qed"]) for cid, data in profiles_by_id.items()]
                # Validate included entries exist and match qed values
                included_ok = True
                for item in included:
                    if not isinstance(item, dict) or "candidate_id" not in item or "qed" not in item:
                        included_ok = False
                        break
                    cid = item["candidate_id"]
                    qed_val = item["qed"]
                    if cid not in profiles_by_id:
                        included_ok = False
                        break
                    if not is_number(qed_val):
                        included_ok = False
                        break
                    prof_qed = profiles_by_id[cid]["qed"]
                    if not safe_float_equal(float(qed_val), float(prof_qed)):
                        included_ok = False
                        break
                # Check sorted non-increasing by qed
                sorted_ok = True
                for i in range(len(included) - 1):
                    if included[i]["qed"] < included[i+1]["qed"] - 1e-9:
                        sorted_ok = False
                        break
                # Check no omission of strictly higher qeds
                omission_ok = True
                if len(included) > 0:
                    min_included_qed = included[-1]["qed"]
                    included_ids_set = set([item["candidate_id"] for item in included])
                    for cid, q in all_qeds:
                        if q > min_included_qed and cid not in included_ids_set:
                            omission_ok = False
                            break
                summary_top3_ok = included_ok and sorted_ok and omission_ok
            else:
                summary_top3_ok = False

    checks["summary_shape_valid"] = summary_shape_ok
    checks["summary_counts_match_profiles"] = summary_counts_ok
    checks["summary_top3_sorted_and_matches_profiles"] = summary_top3_ok

    # Final reward calculation
    # Gate: if any required output is missing, reward is 0.0
    required_all_exist = checks["profiles_exists"] and checks["summary_exists"] and checks["invalid_exists_and_header"]
    if not required_all_exist:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Normalize reward between 0 and 1
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()