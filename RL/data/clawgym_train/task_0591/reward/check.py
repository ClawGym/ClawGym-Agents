import json
import os
import re
import sys
from typing import List, Dict, Any, Tuple

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def is_lowercase_list(lst: List[str]) -> bool:
    if not isinstance(lst, list) or not lst:
        return False
    for s in lst:
        if not isinstance(s, str):
            return False
        if s != s.lower():
            return False
    return True

def slugify(topic: str) -> str:
    s = topic.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s

def last_non_empty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return ""

def check_generated_at_iso(s: str) -> bool:
    if not isinstance(s, str):
        return False
    # Minimal plausibility: starts with YYYY-MM-DDT
    return re.match(r"^\d{4}-\d{2}-\d{2}T", s) is not None

def parse_headings(lines: List[str]) -> List[Tuple[int, str]]:
    # Returns list of (line_index, heading_text) where heading starts with # characters
    res = []
    for i, line in enumerate(lines):
        if line.startswith("#"):
            res.append((i, line.rstrip("\n")))
    return res

def find_line_index(lines: List[str], start_idx: int, end_idx: int, exact_line: str) -> int:
    for i in range(start_idx, min(end_idx, len(lines))):
        if lines[i].rstrip("\n").strip() == exact_line:
            return i
    return -1

def find_section_bounds(lines: List[str], section_start_line_idx: int, section_marker: str = "## ") -> Tuple[int, int]:
    # Given the index of a "## <topic>" line, find [start, end) bounds of this topic section.
    start = section_start_line_idx
    # End is next "## " at a later line or EOF
    for i in range(start + 1, len(lines)):
        if lines[i].startswith(section_marker) and i > start:
            return (start, i)
    return (start, len(lines))

def find_subsection_bounds(lines: List[str], start_idx: int, end_idx: int, subsection_title: str) -> Tuple[int, int]:
    # Given a "### ..." line, find [start, end) bounds within [start_idx, end_idx)
    # Start at the line of subsection_title, and end before next "### " or "## " or EOF
    start = start_idx
    end = end_idx
    for i in range(start + 1, end):
        if lines[i].startswith("### ") or lines[i].startswith("## "):
            end = i
            break
    return (start, end)

def find_heading_indices(lines: List[str], start: int, end: int, prefix: str) -> Dict[str, int]:
    # Returns mapping from heading text (without prefix) to its line index within [start, end)
    res = {}
    for i in range(start, end):
        if lines[i].startswith(prefix):
            label = lines[i].strip()[len(prefix):]
            res[label] = i
    return res

def count_bullets_under_block(lines: List[str], block_start: int, block_end: int) -> int:
    count = 0
    for i in range(block_start + 1, block_end):
        if lines[i].lstrip().startswith("- "):
            count += 1
    return count

def count_bullets_under_heading(lines: List[str], heading_idx: int, end_idx: int) -> int:
    # Count "- " bullets after heading_idx until next heading (####, ###, or ##) or end_idx
    count = 0
    for i in range(heading_idx + 1, end_idx):
        if lines[i].startswith("#### ") or lines[i].startswith("### ") or lines[i].startswith("## "):
            break
        if lines[i].lstrip().startswith("- "):
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    raw_dir = os.path.join(output_dir, "raw")

    checks: Dict[str, bool] = {
        "index_exists": False,
        "index_valid_json": False,
        "index_non_empty_array": False,
        "index_min_len_3": False,
        "index_elements_schema": False,
        "index_modifiers_non_empty": False,
        "index_modifiers_lowercase_all": False,
        "index_slug_correct_all": False,
        "shared_modifiers_identical": False,
        "raw_files_exist_all": False,
        "raw_valid_json_all": False,
        "raw_schema_all": False,
        "raw_topic_match_all": False,
        "raw_modifiers_match_index_all": False,
        "raw_modifiers_lowercase_all": False,
        "raw_results_keys_match_modifiers_all": False,
        "raw_generated_at_iso_all": False,
        "counts_match_raw_all": False,
        "totals_correct_all": False,
        "summary_exists": False,
        "summary_title_at_top": False,
        "summary_has_all_topic_sections": False,
        "summary_top_suggestions_section_all": False,
        "summary_modifier_subheadings_all": False,
        "summary_any_bullet_under_any_modifier_all": False,
        "summary_categorized_section_all": False,
        "summary_at_least_two_categories_all": False,
        "summary_min_three_category_bullets_all": False,
    }

    # Early exits depend on existence of files; no-op baseline remains all False -> reward 0.0
    index_path = os.path.join(output_dir, "index.json")
    index_data: Any = None
    if os.path.isfile(index_path):
        checks["index_exists"] = True
        try:
            index_data = read_json(index_path)
            checks["index_valid_json"] = True
        except Exception:
            index_data = None

    # Validate index.json structure
    index_entries: List[Dict[str, Any]] = []
    common_modifiers: List[str] = []
    if checks["index_valid_json"] and isinstance(index_data, list) and len(index_data) > 0:
        checks["index_non_empty_array"] = True
        if len(index_data) >= 3:
            checks["index_min_len_3"] = True

        schema_ok_all = True
        modifiers_non_empty_all = True
        modifiers_lower_all = True
        slug_correct_all = True
        totals_correct_all = True
        shared_identical = True

        first_modifiers: List[str] = None  # type: ignore

        for entry in index_data:
            # Entry schema
            if not isinstance(entry, dict):
                schema_ok_all = False
                continue
            keys_ok = all(k in entry for k in ["topic", "slug", "modifiers", "counts", "total"])
            types_ok = (
                isinstance(entry.get("topic"), str) and
                isinstance(entry.get("slug"), str) and
                isinstance(entry.get("modifiers"), list) and
                isinstance(entry.get("counts"), dict) and
                isinstance(entry.get("total"), int)
            )
            if not (keys_ok and types_ok):
                schema_ok_all = False
                continue

            topic = entry["topic"]
            slug = entry["slug"]
            modifiers = entry["modifiers"]
            counts = entry["counts"]
            total = entry["total"]

            if not modifiers or not all(isinstance(m, str) for m in modifiers):
                modifiers_non_empty_all = False
            if not is_lowercase_list(modifiers):
                modifiers_lower_all = False

            # counts must have exactly same keys as modifiers
            if set(counts.keys()) != set(modifiers):
                schema_ok_all = False
            else:
                # each value int >= 0
                if not all(isinstance(counts[m], int) and counts[m] >= 0 for m in modifiers):
                    schema_ok_all = False

            # total equals sum
            if isinstance(counts, dict) and isinstance(total, int):
                if total != sum(counts.values()):
                    totals_correct_all = False

            # slug correctness
            expected_slug = slugify(topic)
            if slug != expected_slug:
                slug_correct_all = False

            if first_modifiers is None:
                first_modifiers = list(modifiers)
            else:
                if list(modifiers) != first_modifiers:
                    shared_identical = False

            index_entries.append(entry)

        checks["index_elements_schema"] = schema_ok_all
        checks["index_modifiers_non_empty"] = modifiers_non_empty_all and schema_ok_all
        checks["index_modifiers_lowercase_all"] = modifiers_lower_all and schema_ok_all
        checks["index_slug_correct_all"] = slug_correct_all and schema_ok_all
        checks["totals_correct_all"] = totals_correct_all and schema_ok_all
        if first_modifiers is not None and shared_identical:
            checks["shared_modifiers_identical"] = True
            common_modifiers = first_modifiers

    # Validate raw files against index
    if index_entries and checks["index_elements_schema"]:
        raw_exists_all = True
        raw_valid_all = True
        raw_schema_all = True
        raw_topic_match_all = True
        raw_modifiers_match_index_all = True
        raw_modifiers_lowercase_all = True
        raw_results_keys_match_all = True
        raw_generated_at_iso_all = True
        counts_match_raw_all = True

        for entry in index_entries:
            slug = entry["slug"]
            topic = entry["topic"]
            modifiers = entry["modifiers"]
            counts = entry["counts"]

            raw_path = os.path.join(raw_dir, f"{slug}.json")
            if not os.path.isfile(raw_path):
                raw_exists_all = False
                # If file missing, all dependent checks for this file must remain False
                raw_valid_all = False
                raw_schema_all = False
                raw_topic_match_all = False
                raw_modifiers_match_index_all = False
                raw_modifiers_lowercase_all = False
                raw_results_keys_match_all = False
                raw_generated_at_iso_all = False
                counts_match_raw_all = False
                continue
            try:
                raw = read_json(raw_path)
            except Exception:
                raw_valid_all = False
                # Keep evaluating other files to set global flags accurately
                continue

            if isinstance(raw, dict):
                # schema
                keys_ok = all(k in raw for k in ["topic", "modifiers", "generated_at", "results"])
                types_ok = (
                    isinstance(raw.get("topic"), str) and
                    isinstance(raw.get("modifiers"), list) and
                    isinstance(raw.get("generated_at"), str) and
                    isinstance(raw.get("results"), dict)
                )
                if not (keys_ok and types_ok):
                    raw_schema_all = False
                else:
                    # topic match
                    if raw["topic"] != topic:
                        raw_topic_match_all = False
                    # modifiers match and lowercase
                    raw_mods = raw["modifiers"]
                    if list(raw_mods) != list(modifiers):
                        raw_modifiers_match_index_all = False
                    if not is_lowercase_list(raw_mods):
                        raw_modifiers_lowercase_all = False
                    # results keys equal modifiers
                    res = raw["results"]
                    if set(res.keys()) != set(modifiers):
                        raw_results_keys_match_all = False
                    # generated_at plausibility
                    if not check_generated_at_iso(raw["generated_at"]):
                        raw_generated_at_iso_all = False
                    # counts match lengths in results
                    # Ensure each res[key] is a list
                    for m in modifiers:
                        v = res.get(m, None)
                        if not isinstance(v, list):
                            raw_schema_all = False
                        else:
                            # all suggestions must be strings (if present)
                            if not all(isinstance(s, str) for s in v):
                                raw_schema_all = False
                            if isinstance(counts, dict) and isinstance(counts.get(m, None), int):
                                if counts[m] != len(v):
                                    counts_match_raw_all = False
            else:
                raw_schema_all = False

        checks["raw_files_exist_all"] = raw_exists_all and len(index_entries) > 0
        checks["raw_valid_json_all"] = raw_valid_all and raw_exists_all
        checks["raw_schema_all"] = raw_schema_all and raw_valid_all and raw_exists_all
        checks["raw_topic_match_all"] = raw_topic_match_all and checks["raw_schema_all"]
        checks["raw_modifiers_match_index_all"] = raw_modifiers_match_index_all and checks["raw_schema_all"]
        checks["raw_modifiers_lowercase_all"] = raw_modifiers_lowercase_all and checks["raw_schema_all"]
        checks["raw_results_keys_match_modifiers_all"] = raw_results_keys_match_all and checks["raw_schema_all"]
        checks["raw_generated_at_iso_all"] = raw_generated_at_iso_all and checks["raw_schema_all"]
        checks["counts_match_raw_all"] = counts_match_raw_all and checks["raw_schema_all"] and checks["index_elements_schema"]

    # Validate summary.md
    summary_path = os.path.join(output_dir, "summary.md")
    summary_text = ""
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            summary_text = read_text(summary_path)
        except Exception:
            summary_text = ""

    if checks["summary_exists"] and summary_text:
        lines = summary_text.splitlines()
        # first non-empty line starts with "# "
        first_non_empty = ""
        for line in lines:
            if line.strip():
                first_non_empty = line
                break
        if first_non_empty.startswith("# "):
            checks["summary_title_at_top"] = True

        # Only proceed if we have valid index entries and common modifiers
        if index_entries and common_modifiers:
            has_all_topic_sections = True
            top_suggestions_section_all = True
            modifier_subheadings_all = True
            any_bullet_under_any_modifier_all = True
            categorized_section_all = True
            at_least_two_categories_all = True
            min_three_category_bullets_all = True

            # We'll find each topic section and validate internal structure
            # Build helper: locate "## <topic>"
            for topic_entry in index_entries:
                topic = topic_entry["topic"]
                topic_header = f"## {topic}"
                # find topic section start
                topic_line_idx = find_line_index(lines, 0, len(lines), topic_header)
                if topic_line_idx == -1:
                    has_all_topic_sections = False
                    # Subsequent per-topic checks cannot be True if no section
                    top_suggestions_section_all = False
                    modifier_subheadings_all = False
                    any_bullet_under_any_modifier_all = False
                    categorized_section_all = False
                    at_least_two_categories_all = False
                    min_three_category_bullets_all = False
                    continue
                # Determine topic section bounds
                t_start, t_end = find_section_bounds(lines, topic_line_idx, section_marker="## ")

                # Top suggestions subsection check
                top_title = "### Top suggestions by modifier"
                top_idx = find_line_index(lines, t_start, t_end, top_title)
                if top_idx == -1:
                    top_suggestions_section_all = False
                else:
                    ss_start, ss_end = find_subsection_bounds(lines, top_idx, t_end, top_title)
                    # For every modifier, require "#### <modifier>" within this subsection
                    found_all_mods = True
                    modifier_heading_indices: Dict[str, int] = {}
                    for m in common_modifiers:
                        mod_heading = f"#### {m}"
                        idx = find_line_index(lines, ss_start + 1, ss_end, mod_heading)
                        if idx == -1:
                            found_all_mods = False
                        else:
                            modifier_heading_indices[m] = idx
                    if not found_all_mods:
                        modifier_subheadings_all = False
                    # At least one bullet under at least one modifier subheading
                    bullets_ok_for_topic = False
                    for m, hidx in modifier_heading_indices.items():
                        # end boundary for this modifier: next heading or end of subsection
                        end_for_mod = ss_end
                        for i in range(hidx + 1, ss_end):
                            if lines[i].startswith("#### ") or lines[i].startswith("### ") or lines[i].startswith("## "):
                                end_for_mod = i
                                break
                        if count_bullets_under_heading(lines, hidx, end_for_mod) > 0:
                            bullets_ok_for_topic = True
                            break
                    if not bullets_ok_for_topic:
                        any_bullet_under_any_modifier_all = False

                # Categorized ideas subsection
                cat_title = "### Categorized ideas"
                cat_idx = find_line_index(lines, t_start, t_end, cat_title)
                if cat_idx == -1:
                    categorized_section_all = False
                    at_least_two_categories_all = False
                    min_three_category_bullets_all = False
                else:
                    cs_start, cs_end = find_subsection_bounds(lines, cat_idx, t_end, cat_title)
                    allowed_categories = {"How-to", "Comparison", "Cost", "Troubleshooting"}
                    # Find category subheadings within this subsection
                    categories_found: Dict[str, int] = {}
                    i = cs_start + 1
                    while i < cs_end:
                        if lines[i].startswith("#### "):
                            label = lines[i].strip()[5:]
                            if label in allowed_categories:
                                categories_found[label] = i
                            # Move to next line
                        i += 1
                    if len(categories_found) < 2:
                        at_least_two_categories_all = False
                        # If fewer than 2 categories, bullet total check also fails
                        min_three_category_bullets_all = False
                    else:
                        # Count total bullets across allowed categories used
                        bullet_total = 0
                        # For each category heading, count bullets until next heading or end of subsection
                        # Sort indices to compute end ranges
                        cat_items = sorted(categories_found.items(), key=lambda kv: kv[1])
                        for idx_i, (label, hidx) in enumerate(cat_items):
                            end_for_cat = cs_end
                            # Find the next heading after this one within subsection
                            for j in range(hidx + 1, cs_end):
                                if lines[j].startswith("#### ") or lines[j].startswith("### ") or lines[j].startswith("## "):
                                    end_for_cat = j
                                    break
                            bullet_total += count_bullets_under_heading(lines, hidx, end_for_cat)
                        if bullet_total < 3:
                            min_three_category_bullets_all = False

            checks["summary_has_all_topic_sections"] = has_all_topic_sections
            checks["summary_top_suggestions_section_all"] = top_suggestions_section_all and has_all_topic_sections
            checks["summary_modifier_subheadings_all"] = modifier_subheadings_all and checks["summary_top_suggestions_section_all"]
            checks["summary_any_bullet_under_any_modifier_all"] = any_bullet_under_any_modifier_all and checks["summary_modifier_subheadings_all"]
            checks["summary_categorized_section_all"] = categorized_section_all and has_all_topic_sections
            checks["summary_at_least_two_categories_all"] = at_least_two_categories_all and checks["summary_categorized_section_all"]
            checks["summary_min_three_category_bullets_all"] = min_three_category_bullets_all and checks["summary_categorized_section_all"]

    # Compute reward as average of passed checks
    passed = [v for v in checks.values() if isinstance(v, bool) and v]
    total_checks = len([v for v in checks.values() if isinstance(v, bool)])
    reward = (sum(1.0 for _ in passed) / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline is exactly 0.0: if there are no output artifacts of interest, keep reward at 0
    # This naturally holds because no checks would be True. But guard against accidental positives:
    if not checks["index_exists"] and not checks["summary_exists"]:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()