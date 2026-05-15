import json
import os
import sys
import csv
import re

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

def parse_csv_rows(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Normalize BOM in header keys (e.g., '\ufeffFrom')
            fieldnames = [fn.lstrip("\ufeff") for fn in (reader.fieldnames or [])]
            # Rebuild reader with normalized fieldnames if needed
            if reader.fieldnames and fieldnames != reader.fieldnames:
                f.seek(0)
                reader = csv.DictReader(f)
                # monkey-patch fieldnames for consistent access
                reader.fieldnames = fieldnames
            for r in reader:
                # Normalize keys access with expected names
                def get_field(name):
                    # Try exact, then potential BOM variant
                    if name in r:
                        return r[name]
                    if "\ufeff" + name in r:
                        return r["\ufeff" + name]
                    # Try case variations fallback
                    for k in r.keys():
                        if k.strip().lower() == name.lower():
                            return r[k]
                    return None
                rows.append({
                    "From": get_field("From"),
                    "To": get_field("To"),
                    "Type": get_field("Type"),
                    "Strength": get_field("Strength"),
                })
        # Filter out rows missing required fields (None)
        rows = [row for row in rows if all(v is not None for v in row.values())]
    except Exception:
        return []
    return rows

def parse_targets_yaml(path):
    """
    Minimal YAML parser for a flat mapping of activity -> required (int), possibly nested under a key (e.g., 'targets:').
    It also supports the file being valid JSON mapping as a fallback.
    Returns dict[str, int].
    """
    # Try JSON first (some datasets may use JSON content)
    try:
        data = load_json(path)
        if isinstance(data, dict):
            # If nested 'targets' with dict
            if "targets" in data and isinstance(data["targets"], dict):
                out = {}
                for k, v in data["targets"].items():
                    try:
                        out[str(k)] = int(v)
                    except Exception:
                        continue
                if out:
                    return out
            else:
                out = {}
                for k, v in data.items():
                    try:
                        out[str(k)] = int(v)
                    except Exception:
                        continue
                if out:
                    return out
    except Exception:
        pass

    # YAML lightweight parse: collect lines like "Key: 3" (3 is an int)
    mapping = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n\r")
                # Remove comments (#...) outside simple context: naive approach trims from first # if present
                # but only if there is no colon before it forming a URL-like "http://"
                if "#" in line:
                    hash_pos = line.find("#")
                    before = line[:hash_pos]
                    after = line[hash_pos+1:]
                    # Keep content before # if not empty
                    line = before
                if not line.strip():
                    continue
                # Match "key: value"
                m = re.match(r'^\s*([^:#][^:]*?)\s*:\s*([+-]?\d+)\s*$', line)
                if m:
                    key = m.group(1).strip()
                    try:
                        val = int(m.group(2))
                        mapping[key] = val
                    except Exception:
                        continue
                # If line is just "something:" then ignore; we only capture integer leaf mappings
        return mapping
    except Exception:
        return {}

def get_activity_name(obj):
    for k in ["name", "activity", "title"]:
        if k in obj and isinstance(obj[k], str):
            return obj[k]
    return None

def get_activity_current_level(obj):
    numeric_keys = ["current", "current_capability", "currentCapability", "capability", "level"]
    for k in numeric_keys:
        if k in obj:
            v = obj[k]
            try:
                # Accept int-like floats too
                if isinstance(v, (int, float, str)):
                    n = float(v)
                    # Keep int cast if integer-like
                    if abs(n - int(n)) < 1e-9:
                        return int(n)
                    return n
            except Exception:
                continue
    # Also try to detect if there's a key with 'current' substring and numeric
    for k, v in obj.items():
        if "current" in k.lower():
            try:
                n = float(v)
                if abs(n - int(n)) < 1e-9:
                    return int(n)
                return n
            except Exception:
                continue
    return None

def count_numbered_items_in_recommendations(md_text):
    # Find the "### Recommendations" section
    idx = md_text.find("### Recommendations")
    if idx == -1:
        return 0
    section = md_text[idx:]
    # End at next "### " heading (excluding the starting one)
    m = re.search(r'\n###\s+', section[1:])
    end = len(section) if not m else (1 + m.start())
    rec_text = section[:end]
    # Count lines that look like numbered list items
    count = 0
    for line in rec_text.splitlines():
        if re.match(r'^\s*\d+\.\s', line):
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks to False
    checks = {
        "activity_map_md_exists": False,
        "activity_map_has_required_sections": False,
        "recommendations_at_least_7": False,
        "map_json_exists": False,
        "map_json_valid_schema": False,
        "categories_exact_coverage": False,
        "relationships_covered_in_map_json": False,
        "gaps_all_present": False,
        "gaps_values_correct": False,
    }

    # Paths
    activities_path = os.path.join(input_dir, "activities.json")
    relationships_path = os.path.join(input_dir, "relationships.csv")
    targets_path = os.path.join(input_dir, "targets.yaml")

    md_path = os.path.join(output_dir, "activity_map.md")
    map_json_path = os.path.join(output_dir, "map.json")

    # Read inputs (no credit for this alone)
    activities = load_json(activities_path) or []
    if not isinstance(activities, list):
        activities = []
    relationships_rows = parse_csv_rows(relationships_path)
    targets_map = parse_targets_yaml(targets_path)

    # Extract activity info from inputs
    input_activity_names = []
    input_activity_current = {}
    for item in activities:
        name = get_activity_name(item)
        current = get_activity_current_level(item)
        if name is not None and current is not None:
            input_activity_names.append(name)
            input_activity_current[name] = current
    input_activity_set = set(input_activity_names)

    # Output: activity_map.md checks
    md_text = read_text(md_path)
    if md_text is not None:
        checks["activity_map_md_exists"] = True
        required_sections = [
            "## Activity Map:",
            "### Core Activities",
            "### Critical Activities",
            "### Supporting Activities",
            "### Outsourceable Activities",
            "### Activity Relationships",
            "### Gap Analysis",
            "### Recommendations",
        ]
        if all(s in md_text for s in required_sections):
            checks["activity_map_has_required_sections"] = True
        # Recommendations count
        if count_numbered_items_in_recommendations(md_text) >= 7:
            checks["recommendations_at_least_7"] = True

    # Output: map.json checks
    map_json = load_json(map_json_path)
    if isinstance(map_json, dict):
        checks["map_json_exists"] = True
        has_required_keys = all(k in map_json for k in ["categories", "relationships", "gaps"])
        categories_ok = False
        rels_ok_type = False
        gaps_ok_type = False
        if has_required_keys and isinstance(map_json.get("categories"), dict) and isinstance(map_json.get("relationships"), list) and isinstance(map_json.get("gaps"), list):
            # categories must have exactly four keys
            cat = map_json["categories"]
            expected_cat_keys = {"Core", "Critical", "Supporting", "Outsourceable"}
            if set(cat.keys()) == expected_cat_keys and all(isinstance(cat[k], list) for k in expected_cat_keys):
                # Also ensure all items in lists are strings
                all_str = True
                for k in expected_cat_keys:
                    for v in cat[k]:
                        if not isinstance(v, str):
                            all_str = False
                            break
                    if not all_str:
                        break
                categories_ok = all_str
            # relationships type
            rels = map_json["relationships"]
            rels_ok_type = isinstance(rels, list) and all(isinstance(r, dict) for r in rels)
            # gaps type
            gaps = map_json["gaps"]
            gaps_ok_type = isinstance(gaps, list) and all(isinstance(g, dict) for g in gaps)
        checks["map_json_valid_schema"] = has_required_keys and categories_ok and rels_ok_type and gaps_ok_type

        # categories coverage check
        if checks["map_json_valid_schema"]:
            cat_lists = []
            seen = set()
            duplicates = set()
            foreign = set()
            for k in ["Core", "Critical", "Supporting", "Outsourceable"]:
                lst = map_json["categories"].get(k, [])
                cat_lists.extend(lst)
            # Check duplicates
            for name in cat_lists:
                if name in seen:
                    duplicates.add(name)
                seen.add(name)
                if name not in input_activity_set:
                    foreign.add(name)
            union_set = set(cat_lists)
            categories_exact = (union_set == input_activity_set) and (len(cat_lists) == len(union_set)) and (len(duplicates) == 0) and (len(foreign) == 0)
            checks["categories_exact_coverage"] = categories_exact

        # relationships coverage check (every CSV row must appear in map.json relationships)
        if checks["map_json_valid_schema"]:
            rels = map_json.get("relationships", [])
            rels_set = set()
            for r in rels:
                try:
                    rf = r["from"]
                    rt = r["to"]
                    rtype = r["type"]
                    rstr = r["strength"]
                    # Ensure types are strings
                    if not all(isinstance(x, str) for x in [rf, rt, rtype, rstr]):
                        continue
                    rels_set.add((rf, rt, rtype, rstr))
                except Exception:
                    continue
            missing = []
            for row in relationships_rows:
                tpl = (row["From"], row["To"], row["Type"], row["Strength"])
                if tpl not in rels_set:
                    missing.append(tpl)
            checks["relationships_covered_in_map_json"] = (len(relationships_rows) > 0 and len(missing) == 0) if relationships_rows else False

        # gaps checks
        if checks["map_json_valid_schema"]:
            gaps = map_json.get("gaps", [])
            # Build index by activity
            gap_by_activity = {}
            valid_entries = True
            for g in gaps:
                if not isinstance(g, dict):
                    valid_entries = False
                    break
                if "activity" not in g or "current" not in g or "required" not in g or "gap" not in g:
                    valid_entries = False
                    break
                act = g["activity"]
                if not isinstance(act, str):
                    valid_entries = False
                    break
                # If duplicate activities in gaps, last one wins
                gap_by_activity[act] = g
            # Coverage: all input activities must be present
            coverage_ok = valid_entries and len(input_activity_set) > 0 and all(a in gap_by_activity for a in input_activity_set)
            checks["gaps_all_present"] = coverage_ok

            # Values: for each activity, current and required and gap must match inputs
            values_ok = coverage_ok
            if coverage_ok:
                for a in input_activity_set:
                    g = gap_by_activity.get(a, {})
                    # Fetch numbers safely
                    try:
                        current_out = float(g["current"])
                        required_out = float(g["required"])
                        gap_out = float(g["gap"])
                    except Exception:
                        values_ok = False
                        break
                    # Input values
                    current_in = input_activity_current.get(a, None)
                    required_in = targets_map.get(a, None)
                    if current_in is None or required_in is None:
                        values_ok = False
                        break
                    # Compare numerically
                    if abs(float(current_in) - current_out) > 1e-9:
                        values_ok = False
                        break
                    if abs(float(required_in) - required_out) > 1e-9:
                        values_ok = False
                        break
                    expected_gap = float(required_in) - float(current_in)
                    if abs(expected_gap - gap_out) > 1e-9:
                        values_ok = False
                        break
            checks["gaps_values_correct"] = values_ok

    # Compute reward as average of True checks among scored checks
    scored_keys = [
        "activity_map_md_exists",
        "activity_map_has_required_sections",
        "recommendations_at_least_7",
        "map_json_exists",
        "map_json_valid_schema",
        "categories_exact_coverage",
        "relationships_covered_in_map_json",
        "gaps_all_present",
        "gaps_values_correct",
    ]
    total = len(scored_keys)
    passed = sum(1 for k in scored_keys if checks[k])
    reward = (passed / total) if total > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()