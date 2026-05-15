import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks as False (no vacuous passes)
    checks = {
        # Redacted input checks
        "redacted_exists": False,
        "redacted_non_empty": False,
        "redacted_has_email_placeholder": False,
        "redacted_has_phone_placeholder": False,
        "redacted_has_address_placeholder": False,
        "redacted_has_id_placeholder": False,
        "redacted_ok": False,

        # Extracted entities checks
        "extracted_exists": False,
        "extracted_valid_json": False,
        "extracted_has_keys": False,
        "phenotypes_array_valid": False,
        "phenotypes_contains_min_two": False,
        "meds_array_valid": False,
        "meds_contains_metformin": False,
        "meds_contains_atorvastatin": False,
        "meds_contains_lisinopril": False,
        "extracted_ok": False,

        # Manifest checks
        "manifest_exists": False,
        "manifest_valid_json": False,
        "manifest_paths_ok": False,
        "manifest_used_local_extractor_true": False,
        "manifest_timestamp_format_ok": False,
        "manifest_ok": False,
    }

    # Paths
    redacted_path = os.path.join(output_dir, "redacted_input.txt")
    extracted_path = os.path.join(output_dir, "extracted_entities.json")
    manifest_path = os.path.join(output_dir, "manifest.json")

    # 1) Redacted input checks
    redacted_text = None
    if os.path.isfile(redacted_path):
        checks["redacted_exists"] = True
        try:
            with open(redacted_path, "r", encoding="utf-8") as f:
                redacted_text = f.read()
            if isinstance(redacted_text, str) and len(redacted_text.strip()) > 0:
                checks["redacted_non_empty"] = True
                checks["redacted_has_email_placeholder"] = "[REDACTED_EMAIL]" in redacted_text
                checks["redacted_has_phone_placeholder"] = "[REDACTED_PHONE]" in redacted_text
                checks["redacted_has_address_placeholder"] = "[REDACTED_ADDRESS]" in redacted_text
                checks["redacted_has_id_placeholder"] = "[REDACTED_ID]" in redacted_text
        except Exception:
            # leave as False if any exception occurs
            pass

    checks["redacted_ok"] = all([
        checks["redacted_exists"],
        checks["redacted_non_empty"],
        checks["redacted_has_email_placeholder"],
        checks["redacted_has_phone_placeholder"],
        checks["redacted_has_address_placeholder"],
        checks["redacted_has_id_placeholder"],
    ])

    # 2) Extracted entities checks
    extracted_json = None
    if os.path.isfile(extracted_path):
        checks["extracted_exists"] = True
        try:
            with open(extracted_path, "r", encoding="utf-8") as f:
                extracted_json = json.load(f)
            checks["extracted_valid_json"] = isinstance(extracted_json, dict)
        except Exception:
            extracted_json = None
            checks["extracted_valid_json"] = False

    phenotypes_list = []
    meds_list = []
    if checks["extracted_valid_json"]:
        # Must have keys "phenotypes" (array) and "medications" (array)
        has_phenotypes = "phenotypes" in extracted_json
        has_meds = "medications" in extracted_json
        checks["extracted_has_keys"] = has_phenotypes and has_meds

        if has_phenotypes and isinstance(extracted_json.get("phenotypes"), list):
            checks["phenotypes_array_valid"] = True
            phenotypes_list = extracted_json.get("phenotypes", [])
            # Must include at least two of the following (case-insensitive):
            # "fatigue", "polyuria", "blurry vision", "hypertension", "type 2 diabetes mellitus"
            required_phenos = [
                "fatigue",
                "polyuria",
                "blurry vision",
                "hypertension",
                "type 2 diabetes mellitus",
            ]
            phenos_norm = set([str(p).strip().lower() for p in phenotypes_list if isinstance(p, str)])
            count_matches = sum(1 for p in required_phenos if p in phenos_norm)
            checks["phenotypes_contains_min_two"] = count_matches >= 2

        if has_meds and isinstance(extracted_json.get("medications"), list):
            checks["meds_array_valid"] = True
            meds_list = extracted_json.get("medications", [])
            # For each required medication, ensure an object exists with case-insensitive name match
            # and non-empty string fields: name, dose, frequency
            required_meds = ["metformin", "atorvastatin", "lisinopril"]
            def has_med(target):
                for m in meds_list:
                    if not isinstance(m, dict):
                        continue
                    name = m.get("name")
                    dose = m.get("dose")
                    freq = m.get("frequency")
                    if isinstance(name, str) and isinstance(dose, str) and isinstance(freq, str):
                        if name.strip() and dose.strip() and freq.strip():
                            nlow = name.lower()
                            if re.search(r"\b" + re.escape(target) + r"\b", nlow):
                                return True
                return False

            checks["meds_contains_metformin"] = has_med("metformin")
            checks["meds_contains_atorvastatin"] = has_med("atorvastatin")
            checks["meds_contains_lisinopril"] = has_med("lisinopril")

    checks["extracted_ok"] = all([
        checks["extracted_exists"],
        checks["extracted_valid_json"],
        checks["extracted_has_keys"],
        checks["phenotypes_array_valid"],
        checks["phenotypes_contains_min_two"],
        checks["meds_array_valid"],
        checks["meds_contains_metformin"],
        checks["meds_contains_atorvastatin"],
        checks["meds_contains_lisinopril"],
    ])

    # 3) Manifest checks
    manifest_json = None
    if os.path.isfile(manifest_path):
        checks["manifest_exists"] = True
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_json = json.load(f)
            checks["manifest_valid_json"] = isinstance(manifest_json, dict)
        except Exception:
            manifest_json = None
            checks["manifest_valid_json"] = False

    if checks["manifest_valid_json"]:
        red_path_ok = manifest_json.get("redacted_path") == "output/redacted_input.txt"
        ext_path_ok = manifest_json.get("extracted_path") == "output/extracted_entities.json"
        checks["manifest_paths_ok"] = bool(red_path_ok and ext_path_ok)

        checks["manifest_used_local_extractor_true"] = manifest_json.get("used_local_extractor") is True

        ts = manifest_json.get("timestamp")
        if isinstance(ts, str) and re.fullmatch(r"^\d{8}_\d{6}$", ts):
            checks["manifest_timestamp_format_ok"] = True

    checks["manifest_ok"] = all([
        checks["manifest_exists"],
        checks["manifest_valid_json"],
        checks["manifest_paths_ok"],
        checks["manifest_used_local_extractor_true"],
        checks["manifest_timestamp_format_ok"],
    ])

    # Reward: 1/3 for each major section (redacted_ok, extracted_ok, manifest_ok)
    # No-op baseline: if no outputs, this evaluates to 0.0
    major_checks = [checks["redacted_ok"], checks["extracted_ok"], checks["manifest_ok"]]
    reward = sum(1 for c in major_checks if c) / 3.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()