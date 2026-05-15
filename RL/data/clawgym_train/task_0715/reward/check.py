import json
import os
import sys
import re
import csv

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_export_json": False,
        "has_export_csv": False,
        "has_audit_summary": False,
        "json_parse_ok": False,
        "json_has_required_fields": False,
        "json_has_required_categories": False,
        "pipeline_entry_with_phrase": False,
        "csv_header_ok": False,
        "csv_has_rows": False,
        "csv_rows_well_formed": False,
        "csv_json_category_alignment": False,
        "summary_total_entries_line_ok": False,
        "summary_categories_line_ok": False,
        "summary_count_matches_csv": False,
        "summary_categories_cover_csv_types": False,
    }

    # Paths
    json_path = os.path.join(output_dir, "export.json")
    csv_path = os.path.join(output_dir, "export.csv")
    summary_path = os.path.join(output_dir, "audit_summary.txt")

    # Existence checks
    if os.path.isfile(json_path):
        checks["has_export_json"] = True
    if os.path.isfile(csv_path):
        checks["has_export_csv"] = True
    if os.path.isfile(summary_path):
        checks["has_audit_summary"] = True

    # Parse JSON export
    json_array = None
    json_types = set()
    if checks["has_export_json"]:
        try:
            with open(json_path, "r", encoding="utf-8") as jf:
                data = json.load(jf)
            if isinstance(data, list) and len(data) >= 1:
                checks["json_parse_ok"] = True
                json_array = data
                # Validate fields and collect types
                required_fields_ok = True
                has_required_categories = False
                required_types = {"ingest", "transform", "validate", "aggregate", "pipeline", "profile"}
                json_types = set()
                pipeline_phrase_ok = False
                for item in data:
                    if not isinstance(item, dict):
                        required_fields_ok = False
                        break
                    if not all(k in item for k in ("type", "time", "value")):
                        required_fields_ok = False
                        break
                    # Ensure field types are strings
                    if not isinstance(item.get("type"), str) or not isinstance(item.get("time"), str) or not isinstance(item.get("value"), str):
                        required_fields_ok = False
                        break
                    t = item["type"]
                    v = item["value"]
                    json_types.add(t)
                    if t == "pipeline" and "Daily ETL completed" in v:
                        pipeline_phrase_ok = True

                checks["json_has_required_fields"] = required_fields_ok
                if required_fields_ok:
                    checks["json_has_required_categories"] = required_types.issubset(json_types)
                    checks["pipeline_entry_with_phrase"] = pipeline_phrase_ok
        except Exception:
            checks["json_parse_ok"] = False

    # Parse CSV export
    csv_types = set()
    csv_data_rows_count = 0
    if checks["has_export_csv"]:
        try:
            # Read raw header line for exact match
            with open(csv_path, "r", encoding="utf-8", newline="") as cf:
                # Read first line as raw
                first_line = cf.readline()
                if first_line is not None:
                    header = first_line.rstrip("\n").rstrip("\r")
                    if header == "type,time,value":
                        checks["csv_header_ok"] = True
                # Now parse the rest of the file
                reader = csv.reader(cf)
                well_formed = True
                for row in reader:
                    # Skip possible empty lines
                    if len(row) == 0:
                        continue
                    csv_data_rows_count += 1
                    if len(row) != 3:
                        well_formed = False
                    else:
                        t = row[0]
                        csv_types.add(t)
                checks["csv_has_rows"] = csv_data_rows_count >= 1
                checks["csv_rows_well_formed"] = well_formed and csv_data_rows_count >= 1
        except Exception:
            # leave defaults as False
            pass

    # CSV/JSON categories alignment
    if checks["json_parse_ok"] and checks["has_export_csv"] and checks["csv_has_rows"]:
        # align sets: they must be equal
        checks["csv_json_category_alignment"] = (json_types == csv_types)

    # Audit summary checks
    summary_total = None
    summary_categories_list = []
    if checks["has_audit_summary"]:
        try:
            text = load_text(summary_path) or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
            # Total Entries: exact pattern
            total_line = None
            for ln in lines:
                if re.fullmatch(r"Total Entries: \d+", ln):
                    total_line = ln
                    break
            if total_line:
                checks["summary_total_entries_line_ok"] = True
                try:
                    summary_total = int(total_line.split(":")[1].strip())
                except Exception:
                    summary_total = None

            # Categories: line
            categories_line = None
            for ln in lines:
                if ln.startswith("Categories: "):
                    categories_line = ln
                    break
            if categories_line:
                checks["summary_categories_line_ok"] = True
                cats_part = categories_line[len("Categories: "):]
                # split by comma and trim spaces; ignore empties
                summary_categories_list = [c.strip() for c in cats_part.split(",") if c.strip() != ""]

            # Count match with CSV (number of data rows)
            if summary_total is not None:
                checks["summary_count_matches_csv"] = (summary_total == csv_data_rows_count)

            # Categories cover CSV types
            if summary_categories_list:
                summary_cat_set = set(summary_categories_list)
                checks["summary_categories_cover_csv_types"] = csv_types.issubset(summary_cat_set) and len(csv_types) > 0
        except Exception:
            # keep defaults
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # If output dir is empty or required artifacts missing, ensure possible 0 remains if nothing passed
    # But our fractional scoring already handles this; ensure numeric bounds
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()