import json
import os
import sys
import re

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def split_csv_data_line(line):
    # Split into exactly 3 fields: timestamp, command, value (value may contain commas)
    c1 = line.find(",")
    if c1 == -1:
        return None
    c2 = line.find(",", c1 + 1)
    if c2 == -1:
        return None
    ts = line[:c1]
    cmd = line[c1 + 1:c2]
    val = line[c2 + 1:]
    return ts, cmd, val

def count_term_matches(values, term):
    if term is None:
        return 0
    t = term.lower()
    return sum(1 for v in values if isinstance(v, str) and t in v.lower())

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False)
    checks = {
        # CSV checks
        "csv_exists": False,
        "csv_header_correct": False,
        "csv_rowcount_correct": False,
        "csv_values_cover_expected": False,
        "csv_removed_absent": False,
        # JSON checks
        "json_exists": False,
        "json_linecount_correct": False,
        "json_schema_valid": False,
        "json_cmds_all_add": False,
        "json_values_cover_expected": False,
        "json_removed_absent": False,
        # Analysis checks
        "analysis_exists": False,
        "analysis_entries_line_correct": False,
        "analysis_search_lines_correct": False,
        "analysis_narrative_min_sentences": False,
        # Manifest checks
        "manifest_exists": False,
        "manifest_valid_json": False,
        "manifest_fields_correct": False,
        "manifest_search_terms_match": False,
        "manifest_csv_rows_match": False,
    }

    # Load input plan
    plan_path = os.path.join(input_dir, "pilot_plan.json")
    plan = read_json(plan_path)

    entries = []
    remove_index = None
    search_terms = []
    valid_plan = False
    if isinstance(plan, dict):
        entries = plan.get("entries", [])
        remove_index = plan.get("remove_index", plan.get("remove", None))
        search_terms = plan.get("search_terms", plan.get("search", []))
        if isinstance(entries, list) and isinstance(search_terms, list) and isinstance(remove_index, int):
            valid_plan = True

    # Compute expected values
    expected_entries_added = len(entries) if valid_plan else None
    expected_entries_final = None
    removed_value = None
    remaining_values = None
    if valid_plan and 1 <= remove_index <= len(entries):
        expected_entries_final = len(entries) - 1
        removed_value = entries[remove_index - 1]
        remaining_values = entries[:remove_index - 1] + entries[remove_index:]
    else:
        # Invalid plan (cannot verify outputs without a valid plan)
        remaining_values = None

    # Paths to outputs
    csv_path = os.path.join(output_dir, "log_export.csv")
    json_path = os.path.join(output_dir, "log_export.json")
    analysis_path = os.path.join(output_dir, "analysis.md")
    manifest_path = os.path.join(output_dir, "run_manifest.json")

    # CSV checks
    csv_lines = read_text_lines(csv_path)
    if csv_lines is not None:
        checks["csv_exists"] = True
        if len(csv_lines) >= 1 and csv_lines[0] == "timestamp,command,value":
            checks["csv_header_correct"] = True

        # data lines excluding header
        data_lines = csv_lines[1:] if len(csv_lines) >= 1 else []
        csv_values = []
        csv_cmds = []
        parse_ok = True
        for line in data_lines:
            # Allow empty lines if any; ignore them
            if line.strip() == "":
                continue
            parsed = split_csv_data_line(line)
            if not parsed:
                parse_ok = False
                break
            ts, cmd, val = parsed
            csv_values.append(val)
            csv_cmds.append(cmd)

        # Actual number of data rows (excluding header) should be count of non-empty data lines
        data_row_count = sum(1 for l in data_lines if l.strip() != "")

        if expected_entries_final is not None and parse_ok:
            if data_row_count == expected_entries_final:
                checks["csv_rowcount_correct"] = True

            # Verify all remaining values present at least once
            if remaining_values is not None:
                all_present = True
                for v in remaining_values:
                    if v not in csv_values:
                        all_present = False
                        break
                checks["csv_values_cover_expected"] = all_present

            # Verify removed value absent
            if removed_value is not None:
                checks["csv_removed_absent"] = removed_value not in csv_values

    # JSON checks
    json_lines = read_text_lines(json_path)
    json_vals = []
    json_cmds = []
    json_all_valid = True
    nonempty_json_lines = []
    if json_lines is not None:
        checks["json_exists"] = True
        nonempty_json_lines = [l for l in json_lines if l.strip() != ""]
        if expected_entries_final is not None:
            if len(nonempty_json_lines) == expected_entries_final:
                checks["json_linecount_correct"] = True

        # Validate schema and collect vals and cmds
        for line in nonempty_json_lines:
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    json_all_valid = False
                    break
                keys_ok = set(obj.keys()) == {"ts", "cmd", "val"}
                types_ok = isinstance(obj.get("ts"), str) and isinstance(obj.get("cmd"), str) and isinstance(obj.get("val"), str)
                if not (keys_ok and types_ok):
                    json_all_valid = False
                    break
                json_vals.append(obj["val"])
                json_cmds.append(obj["cmd"])
            except Exception:
                json_all_valid = False
                break
        if json_lines is not None and json_all_valid and len(nonempty_json_lines) > 0 or (json_all_valid and expected_entries_final == 0):
            checks["json_schema_valid"] = True

        if json_all_valid and len(nonempty_json_lines) >= 0:
            # If there are zero lines, it's vacuously true that all cmds are "add", but we only set True if expected_entries_final == 0
            if expected_entries_final == 0:
                checks["json_cmds_all_add"] = True
            elif len(json_cmds) > 0 and all(c == "add" for c in json_cmds):
                checks["json_cmds_all_add"] = True

        if expected_entries_final is not None and json_all_valid:
            if remaining_values is not None:
                all_present = True
                for v in remaining_values:
                    if v not in json_vals:
                        all_present = False
                        break
                checks["json_values_cover_expected"] = all_present

            if removed_value is not None:
                checks["json_removed_absent"] = removed_value not in json_vals

    # Analysis checks
    analysis_lines = read_text_lines(analysis_path)
    if analysis_lines is not None:
        checks["analysis_exists"] = True
        # Entries after removal line
        if expected_entries_final is not None:
            entries_line_pattern = re.compile(r"^Entries after removal:\s+(\d+)\s*$")
            entries_line_ok = False
            for line in analysis_lines:
                m = entries_line_pattern.match(line)
                if m:
                    try:
                        n_val = int(m.group(1))
                        if n_val == expected_entries_final:
                            entries_line_ok = True
                    except Exception:
                        pass
                    break
            checks["analysis_entries_line_correct"] = entries_line_ok

        # Search lines
        search_lines_ok = False
        if remaining_values is not None and isinstance(search_terms, list):
            # Build a map of expected counts
            expected_counts = {}
            for term in search_terms:
                if not isinstance(term, str):
                    continue
                expected_counts[term] = count_term_matches(remaining_values, term)
            # Build a set of lines from analysis
            line_set = set(analysis_lines)
            # Verify each required line exists exactly
            found_all = True
            for term, cnt in expected_counts.items():
                line_text = f"search '{term}': {cnt}"
                if line_text not in line_set:
                    found_all = False
                    break
            search_lines_ok = found_all
        checks["analysis_search_lines_correct"] = search_lines_ok

        # Narrative sentences: at least 3 sentences in total in the file, excluding required structured lines
        # Remove lines that are exactly the structured ones
        filtered_lines = []
        for l in analysis_lines:
            if l.startswith("Entries after removal:"):
                continue
            if l.startswith("search '"):
                continue
            filtered_lines.append(l)
        narrative_text = "\n".join(filtered_lines).strip()
        # Count sentence-like endings (., !, ?)
        sentences = re.findall(r"[^\s].*?[\.!\?](?:\s|$)", narrative_text, flags=re.DOTALL)
        if len(sentences) >= 3:
            checks["analysis_narrative_min_sentences"] = True

    # Manifest checks
    manifest = read_json(manifest_path)
    if manifest is not None:
        checks["manifest_exists"] = True
        if isinstance(manifest, dict):
            checks["manifest_valid_json"] = True

            fields_ok = False
            search_terms_match = False
            csv_rows_match = False

            # Validate fields if we have a valid plan
            if valid_plan and expected_entries_final is not None:
                data_dir_ok = manifest.get("data_dir") == ".cache/pilot_store"
                entries_added_ok = manifest.get("entries_added") == expected_entries_added
                entry_removed_ok = manifest.get("entry_removed_index") == remove_index
                entries_final_ok = manifest.get("entries_final") == expected_entries_final
                # search_terms exactly matches
                st = manifest.get("search_terms")
                if isinstance(st, list) and st == search_terms:
                    search_terms_match = True
                # csv_rows matches actual CSV data rows
                csv_rows_field = manifest.get("csv_rows")
                # compute actual data rows (excluding header and empty lines)
                actual_csv_rows = None
                if isinstance(csv_lines, list) and len(csv_lines) >= 1:
                    actual_csv_rows = sum(1 for l in csv_lines[1:] if l.strip() != "")
                if actual_csv_rows is not None and isinstance(csv_rows_field, int) and csv_rows_field == actual_csv_rows:
                    csv_rows_match = True

                fields_ok = data_dir_ok and entries_added_ok and entry_removed_ok and entries_final_ok

            checks["manifest_fields_correct"] = fields_ok
            checks["manifest_search_terms_match"] = search_terms_match
            checks["manifest_csv_rows_match"] = csv_rows_match

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Enforce no-op baseline: if output directory missing or empty, reward must be 0.0
    # If none of the existence checks passed, passed_checks will be 0 and reward 0.0 already.
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()