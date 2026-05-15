import json
import os
import sys
import re
import csv

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception:
        return False, ""

def parse_csv(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return True, [], []
        header = rows[0]
        data = rows[1:]
        return True, header, data
    except Exception:
        return False, [], []

def is_str(x):
    return isinstance(x, str)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # enrichment.json presence and structure
        "enrichment_exists": False,
        "enrichment_json_parsed": False,
        "enrichment_is_array": False,
        "enrichment_length_ge_1": False,
        # per-object schema and field validations
        "enrichment_objects_have_required_keys": False,
        "enrichment_field_types_valid": False,
        "enrichment_status_values_valid": False,
        "enrichment_error_field_valid": False,
        "enrichment_queried_at_format_valid": False,
        "enrichment_geo_schema_valid": False,
        "enrichment_rdap_schema_valid": False,
        # summary.csv checks
        "summary_exists": False,
        "summary_header_valid": False,
        "summary_row_count_matches_json": False,
        "summary_order_matches_json": False,
        "summary_values_map_correct": False,
        # notes.md checks
        "notes_exists": False,
        "notes_word_count_valid": False,
        "notes_contains_required_terms": False,
    }

    # Initialize variables used across checks
    enrichment = None
    enrichment_len = 0

    # Paths
    enrichment_path = os.path.join(output_dir, "enrichment.json")
    summary_path = os.path.join(output_dir, "summary.csv")
    notes_path = os.path.join(output_dir, "notes.md")

    # Check enrichment.json existence and parsing
    if os.path.isfile(enrichment_path):
        checks["enrichment_exists"] = True
        parsed, enrichment_obj = load_json_file(enrichment_path)
        if parsed:
            checks["enrichment_json_parsed"] = True
            if isinstance(enrichment_obj, list):
                enrichment = enrichment_obj
                checks["enrichment_is_array"] = True
                enrichment_len = len(enrichment)
                if enrichment_len >= 1:
                    checks["enrichment_length_ge_1"] = True

    # Validate enrichment schema if available
    if enrichment is not None and isinstance(enrichment, list):
        # Required keys and types per object
        required_top_keys = [
            "input", "label", "ip", "hostname", "queried_at", "status", "error", "geo", "ptr", "rdap"
        ]
        geo_keys = ["source", "country", "country_code", "region", "city", "isp", "asn"]
        rdap_keys = ["network_name", "cidr", "abuse_email"]

        all_have_keys = True
        all_types_valid = True
        all_status_values_valid = True
        all_error_rules_valid = True
        all_times_valid = True
        all_geo_valid = True
        all_rdap_valid = True

        time_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

        for obj in enrichment:
            # must be dict
            if not isinstance(obj, dict):
                all_have_keys = False
                all_types_valid = False
                all_status_values_valid = False
                all_error_rules_valid = False
                all_times_valid = False
                all_geo_valid = False
                all_rdap_valid = False
                break

            # required keys
            for k in required_top_keys:
                if k not in obj:
                    all_have_keys = False
            # type checks
            # strings
            for k in ["input", "label", "ip", "queried_at", "status", "error", "ptr"]:
                if k in obj and not is_str(obj[k]):
                    all_types_valid = False
            # hostname can be string or None
            if "hostname" in obj and not (obj["hostname"] is None or is_str(obj["hostname"])):
                all_types_valid = False
            # geo and rdap must be dicts
            if "geo" in obj and not isinstance(obj["geo"], dict):
                all_types_valid = False
            if "rdap" in obj and not isinstance(obj["rdap"], dict):
                all_types_valid = False

            # status values
            status = obj.get("status")
            if status not in ("ok", "error"):
                all_status_values_valid = False

            # error rules
            error_val = obj.get("error")
            if status == "error":
                if not (is_str(error_val) and error_val.strip() != ""):
                    all_error_rules_valid = False
            elif status == "ok":
                if not (is_str(error_val) and error_val == ""):
                    all_error_rules_valid = False

            # time format
            t = obj.get("queried_at")
            if not (is_str(t) and time_re.match(t or "")):
                all_times_valid = False

            # geo schema
            geo = obj.get("geo")
            if isinstance(geo, dict):
                for gk in geo_keys:
                    if gk not in geo or not is_str(geo[gk]):
                        all_geo_valid = False
            else:
                all_geo_valid = False

            # rdap schema
            rdap = obj.get("rdap")
            if isinstance(rdap, dict):
                for rk in rdap_keys:
                    if rk not in rdap or not is_str(rdap[rk]):
                        all_rdap_valid = False
            else:
                all_rdap_valid = False

        if all_have_keys:
            checks["enrichment_objects_have_required_keys"] = True
        if all_types_valid:
            checks["enrichment_field_types_valid"] = True
        if all_status_values_valid:
            checks["enrichment_status_values_valid"] = True
        if all_error_rules_valid:
            checks["enrichment_error_field_valid"] = True
        if all_times_valid:
            checks["enrichment_queried_at_format_valid"] = True
        if all_geo_valid:
            checks["enrichment_geo_schema_valid"] = True
        if all_rdap_valid:
            checks["enrichment_rdap_schema_valid"] = True

    # summary.csv checks
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        parsed_csv, header, rows = parse_csv(summary_path)
        if parsed_csv:
            expected_header = ["input", "label", "ip", "country", "asn", "isp", "ptr_present", "rdap_network"]
            if header == expected_header:
                checks["summary_header_valid"] = True

            # Only attempt cross-checks if enrichment is validly parsed as list
            if enrichment is not None and isinstance(enrichment, list):
                # row count matches
                if len(rows) == len(enrichment):
                    checks["summary_row_count_matches_json"] = True

                # order and mapping checks
                order_ok = True
                mapping_ok = True
                for idx, row in enumerate(rows):
                    # Each row should have exactly 8 columns; if not, mapping fails
                    if len(row) != 8:
                        order_ok = False
                        mapping_ok = False
                        break
                    r_input, r_label, r_ip, r_country, r_asn, r_isp, r_ptr_present, r_rdap_network = [col.strip() for col in row]
                    obj = enrichment[idx] if idx < len(enrichment) else None
                    if obj is None:
                        order_ok = False
                        mapping_ok = False
                        break
                    # order
                    if r_input != str(obj.get("input", "")):
                        order_ok = False
                    # mapping
                    geo = obj.get("geo", {}) if isinstance(obj.get("geo", {}), dict) else {}
                    rdap = obj.get("rdap", {}) if isinstance(obj.get("rdap", {}), dict) else {}
                    ptr_val = obj.get("ptr", "")
                    ptr_present_expected = "yes" if (isinstance(ptr_val, str) and ptr_val != "") else "no"

                    if r_label != str(obj.get("label", "")):
                        mapping_ok = False
                    if r_ip != str(obj.get("ip", "")):
                        mapping_ok = False
                    if r_country != str(geo.get("country", "")):
                        mapping_ok = False
                    if r_asn != str(geo.get("asn", "")):
                        mapping_ok = False
                    if r_isp != str(geo.get("isp", "")):
                        mapping_ok = False
                    if r_ptr_present != ptr_present_expected:
                        mapping_ok = False
                    if r_rdap_network != str(rdap.get("network_name", "")):
                        mapping_ok = False

                if order_ok:
                    checks["summary_order_matches_json"] = True
                if mapping_ok:
                    checks["summary_values_map_correct"] = True

    # notes.md checks
    if os.path.isfile(notes_path):
        checks["notes_exists"] = True
        ok_text, text = read_text(notes_path)
        if ok_text:
            # Word count between 80 and 300 inclusive
            words = [w for w in re.split(r"\s+", text.strip()) if w]
            wc = len(words)
            if 80 <= wc <= 300:
                checks["notes_word_count_valid"] = True
            # Contains at least two of the required terms (case-insensitive)
            lc = text.lower()
            terms = ["geolocation", "ptr", "rdap", "isp", "asn", "limitations", "dynamic", "false positive"]
            found = 0
            for term in terms:
                if term in lc:
                    found += 1
            if found >= 2:
                checks["notes_contains_required_terms"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

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