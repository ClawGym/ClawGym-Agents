import json
import os
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None

def normalize_str(s):
    if s is None:
        return None
    return s.strip()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected mapping per task spec
    expected_classifications = {
        "Apex Labs": {"stalled": "yes", "route": "Downgrade", "priority": "yes"},
        "Beacon Corp": {"stalled": "yes", "route": "Close Out", "priority": "yes"},
        "Cirrus Cloud": {"stalled": "no", "route": "Watch", "priority": "no"},
        "Dynatek Solutions": {"stalled": "no", "route": "Advance", "priority": "no"},
        "Eclipse Healthcare": {"stalled": "yes", "route": "Close Out", "priority": "no"},
        "Falcon Retail": {"stalled": "yes", "route": "Watch", "priority": "no"},
        "Gemini Systems": {"stalled": "yes", "route": "Downgrade", "priority": "yes"},
        "Halo Networks": {"stalled": "no", "route": "Advance", "priority": "no"},
        "Ion Commerce": {"stalled": "yes", "route": "Recover", "priority": "no"},
        "Jupiter Inc": {"stalled": "yes", "route": "Downgrade", "priority": "yes"},
        "Kestrel AI": {"stalled": "yes", "route": "Downgrade", "priority": "yes"},
        "Lumen Finance": {"stalled": "no", "route": "Advance", "priority": "no"},
        "Matrix Analytics": {"stalled": "yes", "route": "Close Out", "priority": "no"},
    }
    expected_top5 = {"Jupiter Inc", "Apex Labs", "Beacon Corp", "Gemini Systems", "Kestrel AI"}
    expected_reference_date = "2025-06-30"

    # Initialize checks
    checks = {
        "summary_exists": False,
        "summary_sections_ok": False,
        "diagnostic_exists_and_parse": False,
        "diagnostic_reference_date_ok": False,
        "classifications_exists_and_parse": False,
        "classifications_header_ok": False,
        "no_duplicate_deal_names": False,
        "required_deals_present": False,
        "classification_matches_expected": False,
        "top5_set_matches_expected_in_json": False,
        "top5_json_csv_consistent_names": False,
        "top5_json_csv_consistent_routes": False,
        "csv_priority_exactly_expected_five": False,
    }

    # Paths
    summary_path = os.path.join(output_dir, "summary.md")
    diagnostic_path = os.path.join(output_dir, "diagnostic.json")
    classifications_path = os.path.join(output_dir, "classifications.csv")

    # Check summary.md
    summary_content = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        summary_content = read_text(summary_path)
        if isinstance(summary_content, str):
            content_lower = summary_content.lower()
            required_headings = [
                "pipeline health",
                "top 5 to act on now",
                "stalled / false-active deals",
                "stage risks",
                "immediate actions",
            ]
            checks["summary_sections_ok"] = all(h in content_lower for h in required_headings)

    # Check diagnostic.json
    diagnostic_data = None
    if os.path.isfile(diagnostic_path):
        diagnostic_data = load_json(diagnostic_path)
        if isinstance(diagnostic_data, dict):
            checks["diagnostic_exists_and_parse"] = True
            if diagnostic_data.get("reference_date") == expected_reference_date:
                checks["diagnostic_reference_date_ok"] = True

    # Check classifications.csv
    header, rows = (None, None)
    if os.path.isfile(classifications_path):
        header, rows = load_csv_rows(classifications_path)
        if isinstance(header, list) and isinstance(rows, list):
            checks["classifications_exists_and_parse"] = True
            # header must contain at least these columns
            required_cols = {"deal_name", "stage", "stalled", "route", "priority"}
            header_set = set([h.strip() for h in header]) if header else set()
            checks["classifications_header_ok"] = required_cols.issubset(header_set)

            # Check duplicates
            names = [normalize_str(r.get("deal_name")) for r in rows if r.get("deal_name") is not None]
            unique_names = set()
            dup_found = False
            for n in names:
                if n in unique_names:
                    dup_found = True
                    break
                unique_names.add(n)
            checks["no_duplicate_deal_names"] = not dup_found

            # Build mapping of csv rows by deal_name (last occurrence if duplicates; duplicates already handled)
            csv_map = {}
            for r in rows:
                name = normalize_str(r.get("deal_name"))
                if name:
                    csv_map[name] = {
                        "stalled": normalize_str(r.get("stalled") or ""),
                        "route": normalize_str(r.get("route") or ""),
                        "priority": normalize_str(r.get("priority") or ""),
                        "stage": normalize_str(r.get("stage") or "")
                    }

            # Required deals present
            checks["required_deals_present"] = all(d in csv_map for d in expected_classifications.keys())

            # Match expected classifications exactly for required deals
            classifications_ok = True
            if checks["required_deals_present"]:
                for deal, exp in expected_classifications.items():
                    actual = csv_map.get(deal, {})
                    if actual.get("stalled") != exp["stalled"]:
                        classifications_ok = False
                        break
                    if actual.get("route") != exp["route"]:
                        classifications_ok = False
                        break
                    if actual.get("priority") != exp["priority"]:
                        classifications_ok = False
                        break
            else:
                classifications_ok = False
            checks["classification_matches_expected"] = classifications_ok

            # Priority exactly expected five
            yes_priority_names = {name for name, data in csv_map.items() if data.get("priority") == "yes"}
            checks["csv_priority_exactly_expected_five"] = (yes_priority_names == expected_top5)

    # Top 5 from diagnostic.json comparisons
    if checks["diagnostic_exists_and_parse"] and isinstance(diagnostic_data, dict):
        top5 = diagnostic_data.get("top_5_to_act")
        # Validate structure and set of names
        if isinstance(top5, list) and len(top5) == 5:
            top5_names = []
            top5_routes = {}
            valid_objects = True
            for item in top5:
                if not isinstance(item, dict):
                    valid_objects = False
                    break
                deal = normalize_str(item.get("deal"))
                route = normalize_str(item.get("route"))
                if not deal or not route:
                    valid_objects = False
                    break
                top5_names.append(deal)
                top5_routes[deal] = route
            if valid_objects:
                if set(top5_names) == expected_top5:
                    checks["top5_set_matches_expected_in_json"] = True

                # Cross-check JSON top5 with CSV priority yes names
                if "csv_priority_exactly_expected_five" in checks and checks["csv_priority_exactly_expected_five"]:
                    checks["top5_json_csv_consistent_names"] = True  # since both equal expected_top5

                # Route consistency with CSV
                if checks.get("classifications_exists_and_parse", False):
                    header_ok = checks.get("classifications_header_ok", False)
                    if header_ok:
                        # Rebuild csv_map if not built
                        if rows is not None:
                            csv_map_local = {}
                            for r in rows:
                                name = normalize_str(r.get("deal_name"))
                                if name:
                                    csv_map_local[name] = {
                                        "stalled": normalize_str(r.get("stalled") or ""),
                                        "route": normalize_str(r.get("route") or ""),
                                        "priority": normalize_str(r.get("priority") or ""),
                                        "stage": normalize_str(r.get("stage") or "")
                                    }
                            route_ok = True
                            for dname, jroute in top5_routes.items():
                                if dname not in csv_map_local:
                                    route_ok = False
                                    break
                                if csv_map_local[dname].get("route") != jroute:
                                    route_ok = False
                                    break
                            checks["top5_json_csv_consistent_routes"] = route_ok

    # Compute reward
    # Binary pass: reward 1.0 only if all key checks pass; else 0.0.
    # Key checks: summary_exists, summary_sections_ok, diagnostic_exists_and_parse, diagnostic_reference_date_ok,
    # classifications_exists_and_parse, classifications_header_ok, no_duplicate_deal_names, required_deals_present,
    # classification_matches_expected, top5_set_matches_expected_in_json, top5_json_csv_consistent_names,
    # top5_json_csv_consistent_routes, csv_priority_exactly_expected_five
    key_checks = [
        "summary_exists",
        "summary_sections_ok",
        "diagnostic_exists_and_parse",
        "diagnostic_reference_date_ok",
        "classifications_exists_and_parse",
        "classifications_header_ok",
        "no_duplicate_deal_names",
        "required_deals_present",
        "classification_matches_expected",
        "top5_set_matches_expected_in_json",
        "top5_json_csv_consistent_names",
        "top5_json_csv_consistent_routes",
        "csv_priority_exactly_expected_five",
    ]
    all_pass = all(checks.get(k, False) for k in key_checks)
    reward = 1.0 if all_pass else 0.0

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()