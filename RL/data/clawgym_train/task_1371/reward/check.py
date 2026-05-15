import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def lines(text):
    return text.splitlines() if text is not None else []

def find_day_blocks(week_text):
    # Returns dict of day -> (start_idx, end_idx) and list of lines
    day_headers = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    lns = lines(week_text)
    indices = []
    for i, ln in enumerate(lns):
        for d in day_headers:
            if re.match(rf"^##\s+{re.escape(d)}\s*$", ln.strip()):
                indices.append((d, i))
                break
    blocks = {}
    for idx, (day, start) in enumerate(indices):
        end = len(lns)
        if idx + 1 < len(indices):
            end = indices[idx+1][1]
        blocks[day] = (start, end, lns[start:end])
    return blocks

def contains_shellfish(text):
    if text is None:
        return False
    t = text.lower()
    banned = ["shrimp","prawn","lobster","crab","scallop","shellfish","clam","oyster"]
    return any(b in t for b in banned)

def extract_referenced_recipes(text):
    if text is None:
        return []
    # Pattern: Recipe: `recipes/{filename}.md`
    pattern = r"Recipe:\s*`recipes/([^`]+?\.md)`"
    return list(dict.fromkeys(re.findall(pattern, text)))

def recipe_has_required_sections(text):
    if text is None:
        return False
    has_header = any(ln.strip().startswith("# ") for ln in text.splitlines())
    has_time = "Time:" in text
    has_ingredients = "Ingredients" in text
    has_instructions = "Instructions" in text
    return has_header and has_time and has_ingredients and has_instructions

def get_budget_amount(text):
    if text is None:
        return None
    m = re.search(r"Budget estimate:\s*\$([0-9]+(?:\.[0-9]{1,2})?)", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None

def compute_meatless_dinners_count(week_text, recipes_dir):
    # Count dinners that are meatless by keywords in dinner line or in linked recipe within the same day block.
    if week_text is None:
        return 0
    meatless_keywords = ["vegetarian", "vegan", "tofu", "lentil", "lentils", "chickpea", "chickpeas", "beans", "bean"]
    blocks = find_day_blocks(week_text)
    count = 0
    for day, (start, end, block_lines) in blocks.items():
        block_text = "\n".join(block_lines)
        # Find dinner line within block
        dinner_line = None
        for ln in block_lines:
            if re.search(r"\bDinner\s*:", ln, flags=re.IGNORECASE):
                dinner_line = ln
                break
        if dinner_line is None:
            continue
        dinner_meatless = False
        dl = dinner_line.lower()
        if any(kw in dl for kw in meatless_keywords):
            dinner_meatless = True
        else:
            # If not in dinner line, check recipe content referenced within this block (first recipe link)
            recs_in_block = extract_referenced_recipes(block_text)
            if recs_in_block:
                first_rec = recs_in_block[0]
                rec_path = os.path.join(recipes_dir, first_rec)
                # Normalize path to prevent directory traversal out of recipes_dir
                rec_path_norm = os.path.normpath(rec_path)
                if rec_path_norm.startswith(os.path.normpath(recipes_dir) + os.sep) or os.path.normpath(rec_path_norm) == os.path.normpath(recipes_dir):
                    rec_text = read_text(rec_path_norm)
                    if rec_text:
                        rtl = rec_text.lower()
                        if any(kw in rtl for kw in meatless_keywords):
                            dinner_meatless = True
        if dinner_meatless:
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    week_path = os.path.join(output_dir, "weeks", "2026-W22.md")
    shopping_path = os.path.join(output_dir, "shopping", "2026-05-31.md")
    recipes_root = os.path.join(output_dir, "recipes")

    checks = {
        "has_week_file": False,
        "week_title_ok": False,
        "has_overview": False,
        "has_all_days": False,
        "has_batch_prep": False,
        "has_flex": False,
        "no_shellfish_in_week": False,
        "at_least_two_meatless_dinners": False,
        "at_least_two_recipes_referenced": False,
        "all_recipes_exist": False,
        "recipes_have_required_sections": False,
        "no_shellfish_in_recipes": False,
        "has_shopping_file": False,
        "shopping_has_sections": False,
        "shopping_has_checklist_items": False,
        "shopping_items_mostly_linked": False,
        "budget_estimate_within_cap": False,
        "no_shellfish_in_shopping": False,
        "no_staple_duplicates": False
    }

    referenced_recipes = []

    # Week file checks
    if os.path.isfile(week_path):
        checks["has_week_file"] = True
        week_text = read_text(week_path) or ""
        week_lines = lines(week_text)

        # Title
        title_ok = False
        for ln in week_lines:
            if ln.strip():
                if ln.strip().startswith("# Week 2026-W22"):
                    title_ok = True
                break
        checks["week_title_ok"] = title_ok

        # Overview
        checks["has_overview"] = "## Overview" in week_text

        # Days Monday..Sunday
        day_ok = True
        for d in ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]:
            if not re.search(rf"^##\s+{re.escape(d)}\s*$", week_text, flags=re.MULTILINE):
                day_ok = False
                break
        checks["has_all_days"] = day_ok

        # Batch Prep
        checks["has_batch_prep"] = bool(re.search(r"^##\s+Batch Prep(\s|\(|$)", week_text, flags=re.MULTILINE))

        # Flex slot mention
        checks["has_flex"] = re.search(r"\bflex\b", week_text, flags=re.IGNORECASE) is not None

        # Shellfish in week
        checks["no_shellfish_in_week"] = not contains_shellfish(week_text)

        # Recipe references
        referenced_recipes = extract_referenced_recipes(week_text)
        checks["at_least_two_recipes_referenced"] = len(referenced_recipes) >= 2

        # Meatless dinners count
        meatless_count = compute_meatless_dinners_count(week_text, recipes_root)
        checks["at_least_two_meatless_dinners"] = meatless_count >= 2

    # Recipe files checks (dependent on references)
    recipe_exist_all = True
    recipe_sections_all = True
    recipe_shellfish_ok_all = True
    if referenced_recipes:
        for rec in referenced_recipes:
            rec_path = os.path.join(recipes_root, rec)
            rec_path_norm = os.path.normpath(rec_path)
            # Must be under recipes_root
            if not (rec_path_norm.startswith(os.path.normpath(recipes_root) + os.sep) or os.path.normpath(rec_path_norm) == os.path.normpath(recipes_root)):
                recipe_exist_all = False
                recipe_sections_all = False
                recipe_shellfish_ok_all = False
                break
            if not os.path.isfile(rec_path_norm):
                recipe_exist_all = False
                recipe_sections_all = False
                recipe_shellfish_ok_all = False
                break
            rtext = read_text(rec_path_norm) or ""
            if not recipe_has_required_sections(rtext):
                recipe_sections_all = False
            if contains_shellfish(rtext):
                recipe_shellfish_ok_all = False
    else:
        # If no recipes referenced, these checks remain False
        recipe_exist_all = False
        recipe_sections_all = False
        recipe_shellfish_ok_all = False

    checks["all_recipes_exist"] = recipe_exist_all
    checks["recipes_have_required_sections"] = recipe_sections_all
    checks["no_shellfish_in_recipes"] = recipe_shellfish_ok_all

    # Shopping file checks
    if os.path.isfile(shopping_path):
        checks["has_shopping_file"] = True
        shop_text = read_text(shopping_path) or ""
        shop_lines = lines(shop_text)

        # Sections
        has_produce = "### Produce" in shop_text
        has_pantry = "### Pantry / Dry Goods" in shop_text
        checks["shopping_has_sections"] = has_produce and has_pantry

        # Checklist items
        checklist_lines = [ln for ln in shop_lines if ln.strip().startswith("- [ ]")]
        checks["shopping_has_checklist_items"] = len(checklist_lines) >= 1

        # 80% with em dash linking
        linked_count = 0
        for ln in checklist_lines:
            if " — " in ln:
                linked_count += 1
        ratio = (linked_count / len(checklist_lines)) if checklist_lines else 0.0
        checks["shopping_items_mostly_linked"] = ratio >= 0.8

        # Budget estimate within cap
        amt = get_budget_amount(shop_text)
        checks["budget_estimate_within_cap"] = (amt is not None) and (amt <= 198.0)

        # Shellfish in shopping
        checks["no_shellfish_in_shopping"] = not contains_shellfish(shop_text)

        # No staple duplicates in checklist lines
        staples = ["rice", "pasta", "canned tomatoes", "oats"]
        staple_ok = True
        for ln in checklist_lines:
            low = ln.lower()
            if any(st in low for st in staples):
                staple_ok = False
                break
        checks["no_staple_duplicates"] = staple_ok

    # All checks list for reward calculation
    check_values = list(checks.values())
    total_checks = len(check_values)
    true_count = sum(1 for v in check_values if v)
    reward = (true_count / total_checks) if total_checks > 0 else 0.0

    # Explicitly ensure no-op baseline 0.0 when output absent or empty
    output_exists = os.path.isdir(output_dir) and any(True for _ in os.scandir(output_dir))  # any entry
    if not output_exists:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()