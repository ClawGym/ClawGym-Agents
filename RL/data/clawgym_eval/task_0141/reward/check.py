import os
import sys
import json
import re
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_csv(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize all checks to False
    checks = {
        # inventory checks
        "inventory_exists": False,
        "inventory_valid_json": False,
        "inventory_is_array_length_ge5": False,
        "inventory_elements_have_required_keys": False,
        "inventory_source_ids_unique_and_pattern": False,
        "inventory_filenames_match_inputs": False,
        "inventory_types_valid": False,
        "inventory_credibility_valid": False,
        # coverage matrix checks
        "coverage_exists": False,
        "coverage_header_exact": False,
        "coverage_rows_match_inventory": False,
        "coverage_values_0_or_1": False,
        "coverage_each_row_has_at_least_one_1": False,
        # synthesis checks
        "synthesis_exists": False,
        "synthesis_has_sections_in_order": False,
        "synthesis_sources_count_matches_inventory": False,
        "synthesis_synopsis_min_words": False,
        "synthesis_key_insights_min5_with_citations": False,
        "synthesis_tensions_at_least2_blocks": False,
        "synthesis_all_sources_cited": False,
    }

    # Prepare allowed input filenames
    allowed_files = set()
    try:
        if os.path.isdir(input_dir):
            for name in os.listdir(input_dir):
                # Only include files with allowed extensions
                allowed_files.add(name)
                allowed_files.add(f"input/{name}")
    except Exception:
        pass

    # Paths
    inventory_path = os.path.join(output_dir, "inventory.json")
    coverage_path = os.path.join(output_dir, "coverage_matrix.csv")
    synthesis_path = os.path.join(output_dir, "synthesis.md")

    # Inventory checks
    inventory = None
    if os.path.isfile(inventory_path):
        checks["inventory_exists"] = True
        inventory = load_json(inventory_path)
        if isinstance(inventory, list):
            checks["inventory_valid_json"] = True
            if len(inventory) >= 5:
                checks["inventory_is_array_length_ge5"] = True

            # Required keys per element
            required_keys = {"source_id", "filename", "title", "type", "date", "credibility", "scope"}
            elements_ok = True
            src_ids = []
            filenames_ok = True
            types_ok = True
            cred_ok = True

            valid_types = {"Primary", "Secondary", "Tertiary"}
            valid_cred = {"high", "medium", "low"}
            for el in inventory:
                if not isinstance(el, dict):
                    elements_ok = False
                    break
                if not required_keys.issubset(el.keys()):
                    elements_ok = False
                    break
                # source_id
                src_id = el.get("source_id")
                if not isinstance(src_id, str):
                    elements_ok = False
                    break
                src_ids.append(src_id)
                # filename
                filename = el.get("filename")
                if not isinstance(filename, str) or filename.strip() == "":
                    filenames_ok = False
                else:
                    # If we have allowed_files set (from input_dir), validate against it
                    if allowed_files:
                        if filename not in allowed_files:
                            # allow basenames by comparing basename
                            base = os.path.basename(filename)
                            if base not in {os.path.basename(x) for x in allowed_files}:
                                filenames_ok = False
                    # if no allowed_files available, do not award this check later
                # type
                typ = el.get("type")
                if typ not in valid_types:
                    types_ok = False
                # credibility
                cred = el.get("credibility")
                if cred not in valid_cred:
                    cred_ok = False

            if elements_ok:
                checks["inventory_elements_have_required_keys"] = True

            # source_id uniqueness and pattern
            pattern_ok = True
            seen = set()
            for sid in src_ids:
                if not re.fullmatch(r"S\d+", sid or ""):
                    pattern_ok = False
                    break
                if sid in seen:
                    pattern_ok = False
                    break
                seen.add(sid)
            if pattern_ok and len(src_ids) == len(inventory):
                checks["inventory_source_ids_unique_and_pattern"] = True

            # filenames match inputs
            if filenames_ok and allowed_files:
                checks["inventory_filenames_match_inputs"] = True

            # type validity
            if types_ok:
                checks["inventory_types_valid"] = True

            # credibility validity
            if cred_ok:
                checks["inventory_credibility_valid"] = True

    # Coverage matrix checks
    csv_rows = None
    if os.path.isfile(coverage_path):
        checks["coverage_exists"] = True
        csv_rows = parse_csv(coverage_path)
        if isinstance(csv_rows, list) and len(csv_rows) >= 1:
            header = csv_rows[0]
            expected_header = ["source_id", "theme_productivity", "theme_methodology", "theme_scope", "theme_timeframe"]
            if header == expected_header:
                checks["coverage_header_exact"] = True

            # Only proceed if we have valid inventory for cross-check
            if inventory and checks["inventory_valid_json"]:
                # Gather source_ids from CSV
                csv_ids = []
                values_ok = True
                at_least_one_1_ok = True
                row_ids_set = set()
                for row in csv_rows[1:]:
                    # row length must be exactly 5
                    if len(row) != 5:
                        values_ok = False
                        at_least_one_1_ok = False
                        break
                    sid = row[0].strip()
                    csv_ids.append(sid)
                    row_ids_set.add(sid)
                    vals = row[1:]
                    # Validate 0/1
                    row_vals_ok = True
                    ones_count = 0
                    for v in vals:
                        v_stripped = str(v).strip()
                        if v_stripped not in ("0", "1"):
                            row_vals_ok = False
                            break
                        if v_stripped == "1":
                            ones_count += 1
                    if not row_vals_ok:
                        values_ok = False
                        # continue checking but mark as false
                    if ones_count < 1:
                        at_least_one_1_ok = False

                inv_ids = {el.get("source_id") for el in inventory if isinstance(el, dict)}
                # rows must match inventory set exactly (no missing/no extra)
                if set(csv_ids) == inv_ids and len(csv_ids) == len(inv_ids):
                    checks["coverage_rows_match_inventory"] = True

                if values_ok:
                    checks["coverage_values_0_or_1"] = True
                if at_least_one_1_ok and len(csv_rows) > 1:
                    checks["coverage_each_row_has_at_least_one_1"] = True

    # Synthesis checks
    synthesis_text = None
    if os.path.isfile(synthesis_path):
        checks["synthesis_exists"] = True
        synthesis_text = read_text(synthesis_path)
        if synthesis_text is None:
            synthesis_text = ""
        lines = [ln.rstrip("\n") for ln in synthesis_text.splitlines()]

        # Find section labels in order
        # SOURCES: line contains integer on same line
        sources_idx = None
        synthesis_idx = None
        key_idx = None
        tensions_idx = None
        gaps_idx = None

        for i, ln in enumerate(lines):
            if sources_idx is None and ln.strip().startswith("SOURCES:"):
                sources_idx = i
                continue
        for i, ln in enumerate(lines):
            if ln.strip() == "SYNTHESIS:":
                synthesis_idx = i
                break
        for i, ln in enumerate(lines):
            if ln.strip() == "KEY INSIGHTS:":
                key_idx = i
                break
        for i, ln in enumerate(lines):
            if ln.strip() == "TENSIONS:":
                tensions_idx = i
                break
        for i, ln in enumerate(lines):
            if ln.strip() == "GAPS:":
                gaps_idx = i
                break

        if (sources_idx is not None and synthesis_idx is not None and key_idx is not None
            and tensions_idx is not None and gaps_idx is not None
            and sources_idx < synthesis_idx < key_idx < tensions_idx < gaps_idx):
            checks["synthesis_has_sections_in_order"] = True

        # SOURCES count matches inventory length
        sources_count_ok = False
        if sources_idx is not None and inventory and checks["inventory_valid_json"]:
            line = lines[sources_idx].strip()
            # Extract first integer after 'SOURCES:'
            m = re.search(r"SOURCES:\s*(\d+)", line)
            if m:
                count = int(m.group(1))
                if count == len(inventory):
                    sources_count_ok = True
        if sources_count_ok:
            checks["synthesis_sources_count_matches_inventory"] = True

        # SYNTHESIS min 150 words
        synopsis_ok = False
        if synthesis_idx is not None and key_idx is not None and synthesis_idx < key_idx:
            synopsis_lines = lines[synthesis_idx + 1:key_idx]
            synopsis_text = " ".join(synopsis_lines).strip()
            # Count words by splitting on whitespace
            words = re.findall(r"\b\w+\b", synopsis_text)
            if len(words) >= 150:
                synopsis_ok = True
        if synopsis_ok:
            checks["synthesis_synopsis_min_words"] = True

        # KEY INSIGHTS: at least 5 bullets each with at least one [S#]
        key_insights_ok = False
        if key_idx is not None and tensions_idx is not None and key_idx < tensions_idx:
            section_lines = lines[key_idx + 1:tensions_idx]
            bullets = []
            for ln in section_lines:
                stripped = ln.lstrip()
                if stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("• "):
                    bullets.append(stripped)
            if len(bullets) >= 5:
                # Each bullet must contain at least one [S#]
                per_bullet_ok = all(re.search(r"\[S\d+\]", b) for b in bullets)
                if per_bullet_ok:
                    key_insights_ok = True
        if key_insights_ok:
            checks["synthesis_key_insights_min5_with_citations"] = True

        # TENSIONS: at least 2 conflict blocks
        tensions_ok = False
        if tensions_idx is not None and gaps_idx is not None and tensions_idx < gaps_idx:
            t_lines = lines[tensions_idx + 1:gaps_idx]
            conflict_blocks = 0
            i = 0
            while i < len(t_lines):
                ln = t_lines[i].strip()
                if ln.startswith("CONFLICT:"):
                    # Extract citations and ensure at least two distinct sources
                    cites = re.findall(r"\[S\d+\]", ln)
                    if len(set(cites)) >= 2:
                        # Find next non-empty line that starts with "Resolution:"
                        j = i + 1
                        res_found = False
                        while j < len(t_lines):
                            nxt = t_lines[j].strip()
                            if nxt == "":
                                j += 1
                                continue
                            if nxt.startswith("CONCLUSION:"):
                                # Not expected, break to avoid crossing into unrelated sections
                                break
                            if nxt.startswith("Resolution:"):
                                # Ensure non-empty resolution text
                                if len(nxt[len("Resolution:"):].strip()) > 0:
                                    res_found = True
                                break
                            # If another conflict begins, stop searching resolution for this block
                            if nxt.startswith("CONFLICT:"):
                                break
                            j += 1
                        if res_found:
                            conflict_blocks += 1
                            # Move i to j to continue after resolution line
                            i = j
                i += 1
            if conflict_blocks >= 2:
                tensions_ok = True
        if tensions_ok:
            checks["synthesis_tensions_at_least2_blocks"] = True

        # Coverage: every source_id cited at least once as [S#]
        all_sources_cited_ok = False
        if inventory and checks["inventory_valid_json"]:
            # Extract all [S#] tokens across entire synthesis.md
            all_cites = set(re.findall(r"\[S\d+\]", synthesis_text or ""))
            inv_ids = {el.get("source_id") for el in inventory if isinstance(el, dict)}
            needed = {"[" + sid + "]" for sid in inv_ids if isinstance(sid, str)}
            if needed and needed.issubset(all_cites):
                all_sources_cited_ok = True
        if all_sources_cited_ok:
            checks["synthesis_all_sources_cited"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # No-op baseline: if output dir missing or required files are missing, ensure reward is 0.0
    required_files_exist = all([
        checks["inventory_exists"],
        checks["coverage_exists"],
        checks["synthesis_exists"],
    ])
    if not required_files_exist:
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()