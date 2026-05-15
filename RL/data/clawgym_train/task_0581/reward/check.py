import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_markdown_sections(md_text):
    # Returns dict: section_name_lower -> list of lines (content under that heading)
    lines = md_text.splitlines()
    sections = {}
    current = None
    current_lines = []
    for line in lines:
        if line.strip().startswith("## "):
            # save previous
            if current is not None:
                sections[current] = current_lines
            name = line.strip()[3:].strip()
            current = name.lower()
            current_lines = []
        else:
            if current is not None:
                current_lines.append(line)
    if current is not None:
        sections[current] = current_lines
    return sections, lines

def line_contains_all(s, substrs, case_insensitive=True):
    if case_insensitive:
        s_comp = s.lower()
        for sub in substrs:
            if sub.lower() not in s_comp:
                return False
        return True
    else:
        for sub in substrs:
            if sub not in s:
                return False
        return True

def file_contains_substring(text, substring, case_insensitive=False):
    if text is None:
        return False
    if case_insensitive:
        return substring.lower() in text.lower()
    return substring in text

def find_store(stores, name):
    if not isinstance(stores, list):
        return None
    for s in stores:
        if isinstance(s, dict) and s.get("name") == name:
            return s
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # config.json checks
        "has_config": False,
        "config_has_target_store": False,
        "config_wholefoods_hours_updated": False,
        "config_primary_store_target": False,
        "config_fallback_order_correct": False,
        "config_category_map_mappings": False,
        # list.md checks
        "has_list": False,
        "list_has_wholefoods_header": False,
        "list_has_milk_under_wholefoods_with_added_by": False,
        "list_eggs_merged_to_18": False,
        "list_no_olive_oil": False,
        "list_has_unassigned_header": False,
        "list_unassigned_has_batteries_x4": False,
        # history.md checks
        "has_history": False,
        "history_has_add_milk": False,
        "history_has_remove_olive_oil": False,
        "history_has_merge_eggs_quantities": False,
        # view_list.txt checks
        "has_view_list": False,
        "view_contains_wholefoods_heading_line": False,
        "view_contains_costco_heading_line": False,
        "view_contains_target_heading_line": False,
        "view_contains_total_items_3": False,
        # summary.md checks
        "has_summary": False,
        "summary_non_empty": False,
        "summary_mentions_primary_store": False,
        "summary_mentions_fallback_order": False,
        "summary_mentions_category": False,
        "summary_mentions_merge": False,
    }

    # Paths
    out_grocery_dir = os.path.join(output_dir, "grocery_data")
    config_path = os.path.join(out_grocery_dir, "config.json")
    list_path = os.path.join(out_grocery_dir, "list.md")
    history_path = os.path.join(out_grocery_dir, "history.md")
    view_list_path = os.path.join(output_dir, "view_list.txt")
    summary_path = os.path.join(output_dir, "summary.md")

    # Check config.json
    cfg = read_json(config_path)
    if cfg is not None:
        checks["has_config"] = True
        # Target store exists with exact fields
        stores = cfg.get("stores", [])
        target_store = find_store(stores, "Target")
        if isinstance(target_store, dict):
            if target_store.get("address") == "789 Elm Rd, Anytown" and target_store.get("hours") == "8am–10pm daily":
                checks["config_has_target_store"] = True

        # Whole Foods hours updated exactly
        wf_store = find_store(stores, "Whole Foods")
        if isinstance(wf_store, dict):
            if wf_store.get("hours") == "Mon–Sun 8am–9pm":
                checks["config_wholefoods_hours_updated"] = True

        # primary_store exact "Target"
        if cfg.get("primary_store") == "Target":
            checks["config_primary_store_target"] = True

        # fallback_order exact sequence
        if cfg.get("fallback_order") == ["Target", "Costco", "Whole Foods"]:
            checks["config_fallback_order_correct"] = True

        # category mappings include specified keys and values exactly
        csm = cfg.get("category_store_map", {})
        if (
            isinstance(csm, dict)
            and csm.get("dairy") == "Whole Foods"
            and csm.get("produce") == "Whole Foods"
            and csm.get("electronics") == "Target"
        ):
            checks["config_category_map_mappings"] = True

    # Check list.md
    list_text = read_text(list_path)
    if list_text is not None:
        checks["has_list"] = True
        sections, all_lines = parse_markdown_sections(list_text)

        # Whole Foods header present
        if any(l.strip().lower() == "## whole foods" for l in all_lines):
            checks["list_has_wholefoods_header"] = True

        # Milk (2L) under Whole Foods with "added by Abhishek"
        wf_lines = sections.get("whole foods", [])
        found_milk = False
        for ln in wf_lines:
            if line_contains_all(ln, ["milk", "2l", "added by abhishek"], case_insensitive=True):
                found_milk = True
                break
        if found_milk:
            checks["list_has_milk_under_wholefoods_with_added_by"] = True

        # Eggs merged to x18 anywhere
        eggs_merged = False
        for ln in all_lines:
            if line_contains_all(ln, ["eggs", "x18"], case_insensitive=True):
                eggs_merged = True
                break
        if eggs_merged:
            checks["list_eggs_merged_to_18"] = True

        # No "Olive oil" anywhere
        if not file_contains_substring(list_text, "Olive oil", case_insensitive=True):
            checks["list_no_olive_oil"] = True

        # Unassigned presence and Batteries (x4) under it
        if any(l.strip().lower() == "## unassigned" for l in all_lines):
            checks["list_has_unassigned_header"] = True
            unassigned_lines = sections.get("unassigned", [])
            bat_ok = False
            for ln in unassigned_lines:
                if line_contains_all(ln, ["batteries", "x4"], case_insensitive=True):
                    bat_ok = True
                    break
            if bat_ok:
                checks["list_unassigned_has_batteries_x4"] = True

    # Check history.md
    history_text = read_text(history_path)
    if history_text is not None:
        checks["has_history"] = True
        hist_lines = history_text.splitlines()

        # ADD milk
        add_milk = any(("ADD" in ln) and ("milk" in ln.lower()) for ln in hist_lines)
        if add_milk:
            checks["history_has_add_milk"] = True

        # REMOVE olive oil
        remove_oo = any(("REMOVE" in ln) and ("olive oil" in ln.lower()) for ln in hist_lines)
        if remove_oo:
            checks["history_has_remove_olive_oil"] = True

        # MERGE eggs with quantities 12, 6, 18 in the same line
        merge_ok = False
        for ln in hist_lines:
            lnu = ln.lower()
            if "merge" in lnu and "eggs" in lnu and ("12" in ln) and ("6" in ln) and ("18" in ln):
                merge_ok = True
                break
        if merge_ok:
            checks["history_has_merge_eggs_quantities"] = True

    # Check view_list.txt
    view_text = read_text(view_list_path)
    if view_text is not None:
        checks["has_view_list"] = True
        if "🏪 Whole Foods (123 Main St, Anytown) — Mon–Sun 8am–9pm" in view_text:
            checks["view_contains_wholefoods_heading_line"] = True
        if "🏪 Costco (456 Oak Ave, Anytown) — Mon–Fri 10am–8:30pm, Sat 9:30am–6pm, Sun 10am–6pm" in view_text:
            checks["view_contains_costco_heading_line"] = True
        if "🏪 Target (789 Elm Rd, Anytown) — 8am–10pm daily" in view_text:
            checks["view_contains_target_heading_line"] = True
        if "Total items: 3" in view_text:
            checks["view_contains_total_items_3"] = True

    # Check summary.md
    summary_text = read_text(summary_path)
    if summary_text is not None:
        checks["has_summary"] = True
        if len(summary_text.strip()) > 0:
            checks["summary_non_empty"] = True
            st_lower = summary_text.lower()
            if "primary store" in st_lower:
                checks["summary_mentions_primary_store"] = True
            if "fallback order" in st_lower:
                checks["summary_mentions_fallback_order"] = True
            if "category" in st_lower:
                checks["summary_mentions_category"] = True
            if ("merge" in st_lower) or ("merg" in st_lower):  # crude but inclusive
                checks["summary_mentions_merge"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline is 0.0 when nothing exists
    # This is already the case since passed == 0 when no files exist.

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()