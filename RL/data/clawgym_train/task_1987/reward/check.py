import json
import os
import sys
import csv

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_competitors(competitors_csv_path):
    names = []
    try:
        with open(competitors_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Ensure 'name' column exists
            if "name" not in reader.fieldnames:
                return None
            for row in reader:
                if row.get("name") is not None:
                    names.append(row["name"].strip())
    except Exception:
        return None
    return names

def parse_csv_matrix(path):
    try:
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for r in reader:
                # skip empty lines gracefully
                if r and any(cell.strip() != "" for cell in r):
                    rows.append([cell.strip() for cell in r])
        if not rows:
            return None, None
        header = rows[0]
        data_rows = rows[1:]
        return header, data_rows
    except Exception:
        return None, None

def detect_header_lines(lines, target_headers):
    # Returns dict of header -> line index where it appears as a standalone heading
    found = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        # normalize markdown heading forms by removing leading '#' and whitespace
        normalized = stripped.lstrip("#").strip()
        for h in target_headers:
            if stripped == h or normalized == h:
                if h not in found:
                    found[h] = idx
    return found

def extract_section(lines, start_idx, other_headers):
    # Extract text from after start_idx line to the next line that is any of the other_headers
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        s = lines[i].strip()
        normalized = s.lstrip("#").strip()
        if s in other_headers or normalized in other_headers:
            end_idx = i
            break
    # Return the block lines between (start_idx+1) and (end_idx-1) inclusive
    return "\n".join(lines[start_idx + 1:end_idx])

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    competitors_csv_path = os.path.join(input_dir, "competitors.csv")
    profiles_json_path = os.path.join(output_dir, "competitor_profiles.json")
    matrix_csv_path = os.path.join(output_dir, "comparison_matrix.csv")
    report_md_path = os.path.join(output_dir, "competitor_analysis_report.md")

    checks = {
        "has_profiles_file": False,
        "has_matrix_file": False,
        "has_report_file": False,
        "profiles_json_valid": False,
        "profiles_count_match": False,
        "profiles_keys_complete": False,
        "profiles_names_match": False,
        "matrix_csv_valid": False,
        "matrix_header_has_dimension_first": False,
        "matrix_header_has_us": False,
        "matrix_header_has_all_competitors": False,
        "matrix_has_required_rows": False,
        "report_has_all_headers": False,
        "report_competitors_listed_in_section": False
    }

    # Load competitors list from input
    competitors = load_competitors(competitors_csv_path)
    # Required files existence
    if os.path.isfile(profiles_json_path):
        checks["has_profiles_file"] = True
    if os.path.isfile(matrix_csv_path):
        checks["has_matrix_file"] = True
    if os.path.isfile(report_md_path):
        checks["has_report_file"] = True

    # Check competitor_profiles.json
    if checks["has_profiles_file"] and competitors is not None:
        try:
            with open(profiles_json_path, "r", encoding="utf-8") as f:
                profiles_data = json.load(f)
            # Must be array
            if isinstance(profiles_data, list):
                checks["profiles_json_valid"] = True
                # Count match
                if len(profiles_data) == len(competitors):
                    checks["profiles_count_match"] = True
                # Keys presence
                required_keys = ["name", "who", "what", "where", "how", "why", "financials",
                                 "market_position", "offerings", "capabilities", "performance",
                                 "strategy", "strengths", "weaknesses"]
                keys_ok = True
                names_in_profiles = []
                for obj in profiles_data:
                    if not isinstance(obj, dict):
                        keys_ok = False
                        break
                    for rk in required_keys:
                        if rk not in obj:
                            keys_ok = False
                            break
                    if not keys_ok:
                        break
                    # Collect trimmed name
                    nm = obj.get("name", "")
                    if isinstance(nm, str):
                        names_in_profiles.append(nm.strip())
                    else:
                        names_in_profiles.append("")
                if keys_ok:
                    checks["profiles_keys_complete"] = True
                # Names match competitor set
                comp_set = set([n.strip() for n in competitors])
                prof_set = set(names_in_profiles)
                if prof_set == comp_set and len(names_in_profiles) == len(competitors):
                    checks["profiles_names_match"] = True
        except Exception:
            # Leave checks as False
            pass

    # Check comparison_matrix.csv
    if checks["has_matrix_file"] and competitors is not None:
        header, data_rows = parse_csv_matrix(matrix_csv_path)
        if header is not None and data_rows is not None and len(header) >= 3:
            checks["matrix_csv_valid"] = True
            # Header first column 'Dimension'
            if header[0] == "Dimension":
                checks["matrix_header_has_dimension_first"] = True
            # 'Us' present somewhere after first column
            if any(h == "Us" for h in header[1:]):
                checks["matrix_header_has_us"] = True
            # Competitor columns present (order can vary)
            header_set = set(header[1:])  # columns after Dimension
            comp_set = set([n.strip() for n in competitors])
            # Ensure all competitor names appear exactly once among header columns
            if comp_set.issubset(header_set):
                # Also ensure no duplicates in columns for competitors; not strictly required but fine
                checks["matrix_header_has_all_competitors"] = True
            # Rows include required Dimensions in first column
            dims_required = [
                "Market Share",
                "Growth Rate",
                "Price Position",
                "Product Breadth",
                "Quality Perception",
                "Innovation",
                "Customer Service",
                "Financial Strength"
            ]
            dims_present = set()
            for r in data_rows:
                if len(r) >= 1:
                    dims_present.add(r[0])
            if all(dim in dims_present for dim in dims_required):
                checks["matrix_has_required_rows"] = True

    # Check competitor_analysis_report.md
    if checks["has_report_file"]:
        text = read_file_text(report_md_path)
        if text is not None:
            lines = text.splitlines()
            required_headers = [
                "Competitive Set",
                "Competitor Profiles",
                "Competitive Comparison Matrix",
                "Strategic Groups",
                "Key Findings",
                "Strategic Implications",
                "Assumptions & Data Gaps"
            ]
            found_headers = detect_header_lines(lines, required_headers)
            if all(h in found_headers for h in required_headers):
                checks["report_has_all_headers"] = True

            # Check that all competitor names appear under Competitive Set section
            if "Competitive Set" in found_headers and competitors is not None:
                # Build set of other headers for boundary detection
                other_headers = set(required_headers)
                start_idx = found_headers["Competitive Set"]
                block_text = extract_section(lines, start_idx, other_headers)
                block_ok = True
                for name in competitors:
                    # exact substring check for the name within the block
                    if name not in block_text:
                        block_ok = False
                        break
                if block_ok:
                    checks["report_competitors_listed_in_section"] = True

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # No-op baseline: if output dir missing or all three required artifacts missing -> reward 0.0
    required_artifacts_exist = checks["has_profiles_file"] or checks["has_matrix_file"] or checks["has_report_file"]
    if not required_artifacts_exist:
        reward = 0.0
    else:
        # Proportional scoring
        reward = passed / total_checks if total_checks > 0 else 0.0

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