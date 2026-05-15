import json
import os
import sys
import csv
import re
from datetime import datetime

def is_iso8601_z(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    # Accept YYYY-MM-DDTHH:MM:SSZ with optional fractional seconds
    return re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", s) is not None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    txt = read_text(path)
    if txt is None:
        return None
    return txt.splitlines()

def count_lines(path):
    lines = read_lines(path)
    if lines is None:
        return None
    return len(lines)

def parse_preferences_file(path):
    lines = read_lines(path)
    if lines is None:
        return None
    prefs = [ln.strip() for ln in lines if ln.strip() != ""]
    return prefs

def find_section_positions(lines, section_title):
    # returns start index of section header and start index of next section or len(lines)
    start_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == section_title:
            start_idx = i
            break
    if start_idx is None:
        return None, None
    # find next header "## " after start_idx
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip().startswith("## "):
            end_idx = j
            break
    return start_idx, end_idx

def extract_bullet_items(lines):
    items = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("- "):
            items.append(s[2:].strip())
        elif s.startswith("* "):
            items.append(s[2:].strip())
    return items

def parse_markdown_table(lines, header_predicate):
    """
    Finds the first markdown table whose header row satisfies header_predicate(header_cells:list[str]).
    Returns (header_cells, data_rows) where data_rows is list of list of cells (trimmed strings).
    """
    header_idx = None
    header_cells = None
    for i, ln in enumerate(lines):
        if "|" in ln:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if header_predicate(cells):
                header_idx = i
                header_cells = cells
                break
    if header_idx is None:
        return None, []

    # Skip separator line if present
    data_rows = []
    j = header_idx + 1
    # Skip lines that are separator (e.g., |----|----|)
    if j < len(lines):
        sep = lines[j].strip()
        sep_no = sep.replace("|", "").replace("-", "").replace(":", "").replace(" ", "")
        if sep_no == "":
            # blank after header, not a separator
            pass
        else:
            # consider it a separator if it has only - : | and spaces
            if re.match(r"^[\|\-\:\s]+$", sep):
                j += 1
    # Collect data rows until a non-table line
    while j < len(lines):
        ln = lines[j]
        if "|" not in ln:
            break
        # Heuristic: ignore lines that are pure separators
        pure = ln.strip().replace("|", "").replace("-", "").replace(":", "").replace(" ", "")
        if pure == "":
            j += 1
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        data_rows.append(cells)
        j += 1
    return header_cells, data_rows

def parse_errors_csv(csv_path):
    rows = []
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                # Normalize keys by exact expected names
                date = (r.get("Date") or "").strip()
                wrong = (r.get("What I Got Wrong") or "").strip()
                correct = (r.get("Correct Answer") or "").strip()
                # Skip completely empty rows
                if date == "" and wrong == "" and correct == "":
                    continue
                rows.append((date, wrong, correct))
    except Exception:
        return None
    return rows

def get_index_table_rows(lines):
    def header_pred(cells):
        wanted = ["File", "Lines", "Last Updated"]
        return [c.strip() for c in cells] == wanted
    header_cells, data_rows = parse_markdown_table(lines, header_pred)
    return header_cells, data_rows

def find_row_by_filename(data_rows, filename, header_cells):
    # Build mapping of column names to indices
    col_map = {name: idx for idx, name in enumerate(header_cells)}
    target = None
    for row in data_rows:
        # Pad row if shorter
        if len(row) < len(header_cells):
            row = row + [""] * (len(header_cells) - len(row))
        file_cell = row[col_map["File"]].strip()
        if file_cell == filename:
            lines_val = row[col_map["Lines"]].strip()
            last_updated = row[col_map["Last Updated"]].strip()
            return lines_val, last_updated
    return None

def parse_heartbeat_state(lines):
    vals = {
        "last_heartbeat_started_at": None,
        "last_reviewed_change_at": None,
        "last_heartbeat_result": None,
        "last_actions": []
    }
    for ln in lines:
        s = ln.strip()
        if s.startswith("last_heartbeat_started_at:"):
            vals["last_heartbeat_started_at"] = s.split(":", 1)[1].strip()
        elif s.startswith("last_reviewed_change_at:"):
            vals["last_reviewed_change_at"] = s.split(":", 1)[1].strip()
        elif s.startswith("last_heartbeat_result:"):
            vals["last_heartbeat_result"] = s.split(":", 1)[1].strip()
    # Extract last actions bullets
    # Find "## Last actions" section
    start_idx, end_idx = None, None
    for i, ln in enumerate(lines):
        if ln.strip() == "## Last actions":
            start_idx = i
            break
    if start_idx is not None:
        end_idx = len(lines)
        for j in range(start_idx + 1, len(lines)):
            if lines[j].strip().startswith("## "):
                end_idx = j
                break
        section_lines = lines[start_idx + 1:end_idx]
        vals["last_actions"] = extract_bullet_items(section_lines)
    return vals

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    base_out = os.path.join(output_dir, "self-improving")
    dirs_expected = {
        "dir_self_improving_exists": base_out,
        "dir_domains_exists": os.path.join(base_out, "domains"),
        "dir_projects_exists": os.path.join(base_out, "projects"),
        "dir_archive_exists": os.path.join(base_out, "archive"),
    }
    files_expected = {
        "file_memory_exists": os.path.join(base_out, "memory.md"),
        "file_corrections_exists": os.path.join(base_out, "corrections.md"),
        "file_heartbeat_rules_exists": os.path.join(base_out, "heartbeat-rules.md"),
        "file_heartbeat_state_exists": os.path.join(base_out, "heartbeat-state.md"),
        "file_index_exists": os.path.join(base_out, "index.md"),
        "file_setup_exists": os.path.join(base_out, "setup.md"),
    }
    input_paths = {
        "preferences": os.path.join(input_dir, "preferences.txt"),
        "errors": os.path.join(input_dir, "errors.csv"),
        "heartbeat_rules_in": os.path.join(input_dir, "heartbeat-rules.md"),
    }

    checks = {}
    # Initialize all checks to False
    for k in [
        "dir_self_improving_exists","dir_domains_exists","dir_projects_exists","dir_archive_exists",
        "file_memory_exists","memory_header_correct","memory_has_preferences_section","memory_has_patterns_section","memory_has_rules_section","preferences_bullets_match",
        "file_corrections_exists","corrections_header_correct","corrections_table_header_correct","corrections_rows_count_correct","corrections_rows_content_match",
        "file_heartbeat_rules_exists","heartbeat_rules_header_near_top","heartbeat_rules_mentions_iso8601",
        "file_heartbeat_state_exists","heartbeat_state_started_iso","heartbeat_state_reviewed_iso","heartbeat_state_result_ok","heartbeat_state_last_actions_two_plus","heartbeat_state_last_actions_mentions_memory","heartbeat_state_last_actions_mentions_corrections",
        "file_index_exists","index_has_table_header","index_has_memory_row","index_has_corrections_row","index_lines_match_memory","index_lines_match_corrections","index_last_updated_iso_memory","index_last_updated_iso_corrections",
        "file_setup_exists","setup_mentions_structure"
    ]:
        checks[k] = False

    # Directory checks
    for check_key, path in dirs_expected.items():
        if os.path.isdir(path):
            checks[check_key] = True

    # File existence checks
    for check_key, path in files_expected.items():
        if os.path.isfile(path):
            checks[check_key] = True

    # memory.md checks
    mem_path = files_expected["file_memory_exists"]
    if checks["file_memory_exists"]:
        mem_lines = read_lines(mem_path)
        if mem_lines is None:
            mem_lines = []
        # Must start with "# Memory (HOT Tier)"
        first_line = mem_lines[0].strip() if mem_lines else ""
        if first_line == "# Memory (HOT Tier)":
            checks["memory_header_correct"] = True
        # Sections existence
        if any(ln.strip() == "## Preferences" for ln in mem_lines):
            checks["memory_has_preferences_section"] = True
        if any(ln.strip() == "## Patterns" for ln in mem_lines):
            checks["memory_has_patterns_section"] = True
        if any(ln.strip() == "## Rules" for ln in mem_lines):
            checks["memory_has_rules_section"] = True
        # Preferences bullet items match input/preferences.txt
        prefs_input = parse_preferences_file(input_paths["preferences"])
        if prefs_input is not None and checks["memory_has_preferences_section"]:
            pref_start, pref_end = find_section_positions(mem_lines, "## Preferences")
            if pref_start is not None:
                section_lines = mem_lines[pref_start+1:pref_end if pref_end is not None else len(mem_lines)]
                bullets = extract_bullet_items(section_lines)
                # For each non-empty line in input, ensure it appears exactly as a bullet item
                ok = True
                for item in prefs_input:
                    if item not in bullets:
                        ok = False
                        break
                checks["preferences_bullets_match"] = ok

    # corrections.md checks
    corr_path = files_expected["file_corrections_exists"]
    if checks["file_corrections_exists"]:
        corr_lines = read_lines(corr_path) or []
        # Must start with "# Corrections Log"
        if corr_lines and corr_lines[0].strip() == "# Corrections Log":
            checks["corrections_header_correct"] = True
        # Parse table
        def corr_header_pred(cells):
            return [c.strip() for c in cells] == ["Date", "What I Got Wrong", "Correct Answer", "Status"]
        header_cells, data_rows = parse_markdown_table(corr_lines, corr_header_pred)
        if header_cells is not None and [c.strip() for c in header_cells] == ["Date", "What I Got Wrong", "Correct Answer", "Status"]:
            checks["corrections_table_header_correct"] = True
        # Compare counts and content with input/errors.csv
        csv_rows = parse_errors_csv(input_paths["errors"])
        if csv_rows is not None:
            # Normalize data_rows cells lengths to at least 4
            norm_rows = []
            for r in data_rows:
                if len(r) < 4:
                    r = r + [""] * (4 - len(r))
                # Trim cells
                norm_rows.append([c.strip() for c in r[:4]])
            if len(norm_rows) == len(csv_rows):
                checks["corrections_rows_count_correct"] = True
            # For content, ensure each csv row appears with Status "Logged"
            all_match = True
            for (date, wrong, correct) in csv_rows:
                found = False
                for cells in norm_rows:
                    if len(cells) >= 4:
                        if cells[0] == date and cells[1] == wrong and cells[2] == correct and cells[3] == "Logged":
                            found = True
                            break
                if not found:
                    all_match = False
                    break
            checks["corrections_rows_content_match"] = all_match

    # heartbeat-rules.md checks
    hr_path = files_expected["file_heartbeat_rules_exists"]
    if checks["file_heartbeat_rules_exists"]:
        hr_lines = read_lines(hr_path) or []
        # Contains the phrase "Heartbeat Rules" in first 5 lines
        top_n = hr_lines[:5]
        if any("Heartbeat Rules" in (ln or "") for ln in top_n):
            checks["heartbeat_rules_header_near_top"] = True
        hr_text = "\n".join(hr_lines)
        if "ISO 8601" in hr_text:
            checks["heartbeat_rules_mentions_iso8601"] = True

    # heartbeat-state.md checks
    hs_path = files_expected["file_heartbeat_state_exists"]
    if checks["file_heartbeat_state_exists"]:
        hs_lines = read_lines(hs_path) or []
        state_vals = parse_heartbeat_state(hs_lines)
        started = state_vals.get("last_heartbeat_started_at")
        reviewed = state_vals.get("last_reviewed_change_at")
        result = state_vals.get("last_heartbeat_result")
        if started and started.lower() != "never" and is_iso8601_z(started):
            checks["heartbeat_state_started_iso"] = True
        if reviewed and reviewed.lower() != "never" and is_iso8601_z(reviewed):
            checks["heartbeat_state_reviewed_iso"] = True
        if result == "HEARTBEAT_UPDATED":
            checks["heartbeat_state_result_ok"] = True
        actions = state_vals.get("last_actions") or []
        # At least two bullet items
        if isinstance(actions, list) and len(actions) >= 2:
            checks["heartbeat_state_last_actions_two_plus"] = True
        # Mentions memory.md and corrections.md in bullets
        if any("memory.md" in a for a in actions):
            checks["heartbeat_state_last_actions_mentions_memory"] = True
        if any("corrections.md" in a for a in actions):
            checks["heartbeat_state_last_actions_mentions_corrections"] = True

    # index.md checks
    idx_path = files_expected["file_index_exists"]
    if checks["file_index_exists"]:
        idx_lines = read_lines(idx_path) or []
        header_cells, data_rows = get_index_table_rows(idx_lines)
        if header_cells is not None and [c.strip() for c in header_cells] == ["File", "Lines", "Last Updated"]:
            checks["index_has_table_header"] = True
        # Find rows for memory.md and corrections.md
        mem_row = None
        corr_row = None
        if header_cells is not None:
            mem_row = find_row_by_filename(data_rows, "memory.md", header_cells)
            corr_row = find_row_by_filename(data_rows, "corrections.md", header_cells)
        if mem_row is not None:
            checks["index_has_memory_row"] = True
            mem_lines_count_str, mem_last_updated = mem_row
            mem_count = count_lines(files_expected["file_memory_exists"])
            if mem_count is not None and mem_lines_count_str.isdigit() and int(mem_lines_count_str) == mem_count:
                checks["index_lines_match_memory"] = True
            if is_iso8601_z(mem_last_updated):
                checks["index_last_updated_iso_memory"] = True
        if corr_row is not None:
            checks["index_has_corrections_row"] = True
            corr_lines_count_str, corr_last_updated = corr_row
            corr_count = count_lines(files_expected["file_corrections_exists"])
            if corr_count is not None and corr_lines_count_str.isdigit() and int(corr_lines_count_str) == corr_count:
                checks["index_lines_match_corrections"] = True
            if is_iso8601_z(corr_last_updated):
                checks["index_last_updated_iso_corrections"] = True

    # setup.md checks
    setup_path = files_expected["file_setup_exists"]
    if checks["file_setup_exists"]:
        setup_txt = read_text(setup_path) or ""
        low = setup_txt.lower()
        if all(word in low for word in ["domains", "projects", "archive"]):
            checks["setup_mentions_structure"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output/self-improving missing or empty, ensure reward is 0.0
    # If none of the file existence checks are True and none of the dir checks are True, reward should be 0.0
    any_output_artifact = any(checks[k] for k in checks if k.startswith("file_") or k.startswith("dir_"))
    if not any_output_artifact:
        reward = 0.0

    # Print result JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()