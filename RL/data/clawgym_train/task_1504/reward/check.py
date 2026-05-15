import csv
import json
import os
import sys
import xml.etree.ElementTree as ET

def read_csv_rows(csv_path):
    rows = []
    if not os.path.isfile(csv_path):
        return None, 0, 0  # indicate missing input
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalize keys and values
            norm = { (k.strip().lower() if k is not None else ""): (v.strip() if v is not None else "") for k, v in row.items() }
            if not norm.get("type") and not norm.get("date"):
                continue  # skip empty lines
            rows.append(norm)
    # Count with_fortune=true
    fortune_true_count = 0
    for r in rows:
        wf = r.get("with_fortune", "")
        if isinstance(wf, str) and wf.lower() == "true":
            fortune_true_count += 1
    return rows, len(rows), fortune_true_count

def get_child_text(node, tag):
    child = node.find(tag)
    if child is not None and child.text is not None:
        return child.text.strip()
    return ""

def parse_itinerary(xml_path):
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        return tree, root, None
    except Exception as e:
        return None, None, str(e)

def collect_entries(root):
    entries = []
    for child in list(root):
        if child.tag != "lunar_query_result":
            continue
        entry = {}
        entry["solar_date"] = get_child_text(child, "solar_date")
        lunar_node = child.find("lunar_date")
        if lunar_node is not None:
            entry["lunar_year"] = get_child_text(lunar_node, "year")
            entry["lunar_month"] = get_child_text(lunar_node, "month")
            entry["lunar_day"] = get_child_text(lunar_node, "day")
            entry["lunar_festival"] = get_child_text(lunar_node, "festival")
        else:
            entry["lunar_year"] = ""
            entry["lunar_month"] = ""
            entry["lunar_day"] = ""
            entry["lunar_festival"] = ""
        fortune_node = child.find("fortune")
        if fortune_node is not None:
            entry["fortune_suitable"] = get_child_text(fortune_node, "suitable")
            entry["fortune_avoid"] = get_child_text(fortune_node, "avoid")
        else:
            entry["fortune_suitable"] = ""
            entry["fortune_avoid"] = ""
        entries.append(entry)
    return entries

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    csv_path = os.path.join(input_dir, "requests.csv")
    xml_path = os.path.join(output_dir, "itinerary.xml")
    summary_path = os.path.join(output_dir, "summary.md")

    # Initialize checks (artifact-dependent defaults False)
    checks = {
        "has_itinerary_xml": False,
        "xml_well_formed_and_root_lunar_queries": False,
        "xml_count_matches_csv_rows": False,
        "xml_contains_2026_02_17_solar_newyear": False,
        "xml_contains_2037_10_13_from_lunar_2037_09_05": False,
        "xml_has_leap_month_label": False,
        "fortunes_nonempty_count_matches_requested_true": False,
        "has_summary_md": False,
        "summary_processed_count_correct": False,
        "summary_contains_out_of_range_1899_12_31": False,
    }

    # Read CSV
    csv_rows, expected_rows, fortune_true_count = read_csv_rows(csv_path)

    # XML checks
    if os.path.isfile(xml_path):
        checks["has_itinerary_xml"] = True
        tree, root, parse_err = parse_itinerary(xml_path)
        if root is not None and parse_err is None and root.tag == "lunar_queries":
            checks["xml_well_formed_and_root_lunar_queries"] = True

            entries = collect_entries(root)

            # Row count match requires CSV present
            if csv_rows is not None:
                if len(entries) == expected_rows:
                    checks["xml_count_matches_csv_rows"] = True

            # Specific content checks
            # 2026-02-17 solar date with 正月 and 初一
            for e in entries:
                if e.get("solar_date") == "2026-02-17":
                    month_text = e.get("lunar_month", "")
                    day_text = e.get("lunar_day", "")
                    if ("正月" in month_text) and ("初一" in day_text):
                        checks["xml_contains_2026_02_17_solar_newyear"] = True
                        break

            # 2037-10-13 solar date present (from lunar 2037-09-05 leap=false)
            if any(e.get("solar_date") == "2037-10-13" for e in entries):
                checks["xml_contains_2037_10_13_from_lunar_2037_09_05"] = True

            # Leap month label presence "闰" in lunar month
            if any("闰" in (e.get("lunar_month") or "") for e in entries):
                checks["xml_has_leap_month_label"] = True

            # Fortune non-empty count equals requested count
            nonempty_fortune_count = 0
            for e in entries:
                suitable = (e.get("fortune_suitable") or "").strip()
                avoid = (e.get("fortune_avoid") or "").strip()
                if suitable and avoid:
                    nonempty_fortune_count += 1
            if csv_rows is not None and nonempty_fortune_count == fortune_true_count:
                checks["fortunes_nonempty_count_matches_requested_true"] = True

    # Summary checks
    if os.path.isfile(summary_path):
        checks["has_summary_md"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n").strip() for ln in f.readlines()]
        except Exception:
            lines = []

        # Processed: N requests (require CSV present)
        if csv_rows is not None:
            expected_line = f"Processed: {expected_rows} requests"
            if any(line == expected_line for line in lines):
                checks["summary_processed_count_correct"] = True

        # Out-of-range line
        if any(line == "Out-of-range: 1899-12-31" for line in lines):
            checks["summary_contains_out_of_range_1899_12_31"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward is 0.0 if outputs are entirely missing (no-op baseline)
    output_exists = os.path.isdir(output_dir) and (os.path.isfile(xml_path) or os.path.isfile(summary_path))
    if not output_exists:
        reward = 0.0

    # Print final JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()