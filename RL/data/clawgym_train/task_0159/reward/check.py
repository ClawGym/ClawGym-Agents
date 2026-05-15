import json
import os
import sys
import csv

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected data from the offline catalog snapshot embedded deterministically
    expected_airports = ["AAL", "ABV", "ACC", "ACE"]
    expected_ids_by_airport = {
        "AAL": ["AAL-aal-aalborg-airport-lounge-2"],
        "ABV": [
            "ABV-abv1-sds-lounge-35",
            "ABV-abv2-lounge-one-34",
            "ABV-abv3-9tysix-lounge-33",
            "ABV-abv4-the-gabfol-lounge-36",
            "ABV-abv6-pearl-lounge-32",
        ],
        "ACC": [
            "ACC-acc-adinkra-lounge-43",
            "ACC-acc1-akwaaba-pearl-lounge-40",
            "ACC-acc2-sanbra-priority-lounge-41",
            "ACC-acc3-adinkra-lounge-42",
        ],
        "ACE": ["ACE-ace-sala-guacimeta-44"],
    }
    expected_name_terminal = {
        "AAL-aal-aalborg-airport-lounge-2": ("Aalborg Airport Lounge", "Unknown"),
        "ABV-abv1-sds-lounge-35": ("SDS Lounge", "New International Terminal"),
        "ABV-abv2-lounge-one-34": ("Lounge One", "Domestic Terminal"),
        "ABV-abv3-9tysix-lounge-33": ("@9tysix Lounge", "Domestic Terminal"),
        "ABV-abv4-the-gabfol-lounge-36": ("The Gabfol Lounge", "International Terminal"),
        "ABV-abv6-pearl-lounge-32": ("Pearl Lounge", "New International Terminal"),
        "ACC-acc-adinkra-lounge-43": ("Adinkra Lounge", "Terminal 3"),
        "ACC-acc1-akwaaba-pearl-lounge-40": ("Akwaaba Pearl Lounge", "Terminal 3"),
        "ACC-acc2-sanbra-priority-lounge-41": ("Sanbra Priority Lounge", "Terminal 3"),
        "ACC-acc3-adinkra-lounge-42": ("Adinkra Lounge", "Terminal 2"),
        "ACE-ace-sala-guacimeta-44": ("Sala Guacimeta", "Terminal 1"),
    }
    # Expected best picks and reasons
    expected_best_pick = {
        "AAL": ("AAL-aal-aalborg-airport-lounge-2", False, "has all required facilities (no showers available)"),
        "ABV": ("ABV-abv6-pearl-lounge-32", True, "has all required facilities + preferred showers"),
        "ACC": ("ACC-acc1-akwaaba-pearl-lounge-40", True, "has all required facilities + preferred showers"),
        "ACE": ("ACE-ace-sala-guacimeta-44", False, "has all required facilities (no showers available)"),
    }

    checks = {
        "has_lounges_json": False,
        "lounges_json_valid": False,
        "lounges_json_keys_exact": False,
        "lounges_json_ids_per_airport_match": False,
        "lounges_name_terminal_match": False,
        "lounges_facilities_include_required": False,
        "has_best_picks_csv": False,
        "best_picks_header_ok": False,
        "best_picks_rows_count_ok": False,
        "best_picks_airports_set_ok": False,
        "best_picks_ids_ok": False,
        "best_picks_name_terminal_match": False,
        "best_picks_has_showers_reason_ok": False,
        "picks_exist_in_json": False,
    }

    lounges_json_path = os.path.join(output_dir, "lounges_by_airport.json")
    best_picks_csv_path = os.path.join(output_dir, "best_picks.csv")

    lounges_data = None
    if os.path.isfile(lounges_json_path):
        checks["has_lounges_json"] = True
        try:
            with open(lounges_json_path, "r", encoding="utf-8") as f:
                lounges_data = json.load(f)
            if isinstance(lounges_data, dict):
                checks["lounges_json_valid"] = True
        except Exception:
            lounges_data = None

    # Validate lounges_by_airport.json structure and content
    ids_in_json_by_airport = {}
    facilities_by_lounge_id = {}
    if checks["lounges_json_valid"]:
        # Keys exact
        try:
            keys = list(lounges_data.keys())
            # Must match exactly expected keys (order doesn't matter)
            if set(keys) == set(expected_airports) and len(keys) == len(expected_airports):
                checks["lounges_json_keys_exact"] = True
        except Exception:
            pass

        # Validate entries per airport, collect IDs, check fields and facilities
        name_terminal_ok = True
        ids_match = True
        facilities_ok = True

        for airport in expected_airports:
            value = lounges_data.get(airport)
            if not isinstance(value, list):
                ids_match = False
                name_terminal_ok = False
                facilities_ok = False
                break
            # Collect ids and validate structure
            ids_found = []
            for item in value:
                if not isinstance(item, dict):
                    facilities_ok = False
                    name_terminal_ok = False
                    continue
                # Required fields
                if not all(k in item for k in ["id", "name", "terminal", "openingHours", "facilities"]):
                    facilities_ok = False
                    name_terminal_ok = False
                    continue
                # Types
                if not isinstance(item["id"], str) or not isinstance(item["name"], str) or not isinstance(item["terminal"], str) or not isinstance(item["openingHours"], str):
                    facilities_ok = False
                    name_terminal_ok = False
                if not isinstance(item["facilities"], list):
                    facilities_ok = False
                # Facilities must include exact strings
                facs = [str(x) for x in item.get("facilities", [])]
                if ("Digital card accepted" not in facs) or ("Wi-Fi" not in facs):
                    facilities_ok = False
                # Track
                lid = item["id"]
                ids_found.append(lid)
                facilities_by_lounge_id[lid] = set(facs)
                # Name & terminal match expected for known IDs
                if lid in expected_name_terminal:
                    exp_name, exp_term = expected_name_terminal[lid]
                    if item["name"] != exp_name or item["terminal"] != exp_term:
                        name_terminal_ok = False
            ids_in_json_by_airport[airport] = ids_found
            # IDs must match exactly the expected set
            expected_ids = expected_ids_by_airport.get(airport, [])
            if sorted(ids_found) != sorted(expected_ids):
                ids_match = False

        if ids_match:
            checks["lounges_json_ids_per_airport_match"] = True
        if name_terminal_ok:
            checks["lounges_name_terminal_match"] = True
        if facilities_ok:
            checks["lounges_facilities_include_required"] = True

    # Validate best_picks.csv
    rows = []
    if os.path.isfile(best_picks_csv_path):
        checks["has_best_picks_csv"] = True
        try:
            with open(best_picks_csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                all_rows = list(reader)
            if all_rows:
                header = all_rows[0]
                expected_header = ["airport_code", "lounge_id", "lounge_name", "terminal", "has_showers", "reason"]
                if header == expected_header:
                    checks["best_picks_header_ok"] = True
                data_rows = all_rows[1:]
                rows = data_rows
                if len(data_rows) == 4:
                    checks["best_picks_rows_count_ok"] = True
        except Exception:
            pass

    # Further CSV validations if we have rows
    csv_airport_set_ok = False
    csv_ids_ok = False
    csv_name_terminal_ok = False
    csv_showers_reason_ok = False
    csv_picks_in_json = False

    if rows:
        try:
            # Check airport set
            airports_in_csv = [r[0] for r in rows if len(r) >= 6]
            if set(airports_in_csv) == set(expected_airports) and len(airports_in_csv) == 4:
                csv_airport_set_ok = True

            # Check ids and names/terminals
            ids_ok = True
            nt_ok = True
            showers_reason_ok = True
            picks_in_json_ok = True

            for r in rows:
                if len(r) != 6:
                    ids_ok = False
                    nt_ok = False
                    showers_reason_ok = False
                    picks_in_json_ok = False
                    break
                airport_code, lounge_id, lounge_name, terminal, has_showers, reason = r
                # ID must match expected best pick for this airport
                expected_id, expected_has_showers_bool, expected_reason = expected_best_pick.get(airport_code, (None, None, None))
                if lounge_id != expected_id:
                    ids_ok = False
                # Name & terminal must match catalog mapping
                exp_name, exp_term = expected_name_terminal.get(lounge_id, ("", ""))
                if lounge_name != exp_name or terminal != exp_term:
                    nt_ok = False
                # has_showers must be 'true'/'false'
                if has_showers not in ("true", "false"):
                    showers_reason_ok = False
                # Compare reason exact wording
                if reason != expected_reason:
                    showers_reason_ok = False
                # If we have lounges JSON, ensure the pick exists under that airport
                if ids_in_json_by_airport:
                    ids_list = ids_in_json_by_airport.get(airport_code, [])
                    if lounge_id not in ids_list:
                        picks_in_json_ok = False
                # Also ensure has_showers matches facilities in lounges JSON if available
                if facilities_by_lounge_id and lounge_id in facilities_by_lounge_id:
                    facs = facilities_by_lounge_id[lounge_id]
                    actual_has_showers = "Showers" in facs
                    if (has_showers == "true") != actual_has_showers:
                        showers_reason_ok = False
                else:
                    # Fallback to expected mapping when lounges JSON not available or lounge not present
                    if expected_has_showers_bool is not None:
                        if (has_showers == "true") != expected_has_showers_bool:
                            showers_reason_ok = False

            if ids_ok:
                csv_ids_ok = True
            if nt_ok:
                csv_name_terminal_ok = True
            if showers_reason_ok:
                csv_showers_reason_ok = True
            # picks in json validation only if lounges json is valid and keys exact and ids matched
            if ids_in_json_by_airport:
                csv_picks_in_json = picks_in_json_ok
            else:
                # If lounges JSON not present/valid, cannot verify; keep as False
                csv_picks_in_json = False
        except Exception:
            pass

    checks["best_picks_airports_set_ok"] = csv_airport_set_ok
    checks["best_picks_ids_ok"] = csv_ids_ok
    checks["best_picks_name_terminal_match"] = csv_name_terminal_ok
    checks["best_picks_has_showers_reason_ok"] = csv_showers_reason_ok
    checks["picks_exist_in_json"] = csv_picks_in_json

    # Compute reward
    # Enforce no-op baseline: if any required artifact missing, reward = 0.0
    required_files_present = checks["has_lounges_json"] and checks["has_best_picks_csv"]
    if not required_files_present:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Fractional score based on checks passed
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Clamp to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()