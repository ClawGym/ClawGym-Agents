import json
import csv
import re
import sys
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json_print(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _parse_product_html(html_text: str) -> Optional[Dict[str, object]]:
    # Extract product block attributes and fields using regex
    try:
        div_match = re.search(r'<div\s+class="product"[^>]*data-slug="([^"]+)"[^>]*>', html_text, re.DOTALL)
        if not div_match:
            return None
        slug = div_match.group(1).strip()

        def extract_tag(cls: str, tag: str = "p") -> Optional[str]:
            m = re.search(rf'<{tag}\s+class="{re.escape(cls)}">\s*(.*?)\s*</{tag}>', html_text, re.DOTALL | re.IGNORECASE)
            return m.group(1).strip() if m else None

        name = extract_tag("name", tag="h1")
        tagline = extract_tag("tagline", tag="p")
        usage = extract_tag("usage", tag="p")

        def extract_list(ul_class: str) -> Optional[List[str]]:
            m = re.search(rf'<ul\s+class="{re.escape(ul_class)}">\s*(.*?)\s*</ul>', html_text, re.DOTALL | re.IGNORECASE)
            if not m:
                return None
            inner = m.group(1)
            items = re.findall(r'<li>\s*(.*?)\s*</li>', inner, re.DOTALL | re.IGNORECASE)
            items = [re.sub(r'\s+', ' ', it).strip() for it in items]
            return items

        ingredients = extract_list("ingredients")
        concerns = extract_list("concerns")

        if not all([slug, name, tagline, usage, ingredients, concerns]):
            return None

        product = {
            "product_slug": slug,
            "name": re.sub(r'\s+', ' ', name).strip(),
            "tagline": re.sub(r'\s+', ' ', tagline).strip(),
            "ingredients": ingredients,
            "concerns": [c.lower() for c in concerns],
            "usage": re.sub(r'\s+', ' ', usage).strip(),
        }
        return product
    except Exception:
        return None


def _parse_products_from_html_dir(html_dir: Path) -> Optional[List[Dict[str, object]]]:
    try:
        if not html_dir.exists():
            return None
        products = []
        for p in sorted(html_dir.glob("*.html")):
            txt = _read_text(p)
            if txt is None:
                return None
            prod = _parse_product_html(txt)
            if prod is None:
                return None
            products.append(prod)
        # sort by product_slug
        products.sort(key=lambda x: x.get("product_slug", ""))
        return products
    except Exception:
        return None


def _load_products_json(path: Path) -> Optional[List[Dict[str, object]]]:
    data = _read_json(path)
    if not isinstance(data, list):
        return None
    # Verify each has required keys and types
    required_keys = {"product_slug", "name", "tagline", "ingredients", "concerns", "usage"}
    for item in data:
        if not isinstance(item, dict):
            return None
        if not required_keys.issubset(item.keys()):
            return None
        if not isinstance(item["product_slug"], str):
            return None
        if not isinstance(item["name"], str):
            return None
        if not isinstance(item["tagline"], str):
            return None
        if not isinstance(item["ingredients"], list) or not all(isinstance(x, str) for x in item["ingredients"]):
            return None
        if not isinstance(item["concerns"], list) or not all(isinstance(x, str) for x in item["concerns"]):
            return None
        if not isinstance(item["usage"], str):
            return None
        # concerns must be lowercase
        for c in item["concerns"]:
            if c != c.lower():
                return None
    # Check sorted by product_slug
    slugs = [i["product_slug"] for i in data]
    if slugs != sorted(slugs):
        return None
    return data


def _compute_concerns_summary_from_csv(csv_path: Path) -> Optional[Dict[str, int]]:
    rows = _read_csv_dicts(csv_path)
    if rows is None:
        return None
    counts: Dict[str, int] = {}
    for r in rows:
        if "skin_concern" not in r:
            return None
        val = (r.get("skin_concern") or "").strip().lower()
        if val == "":
            return None
        counts[val] = counts.get(val, 0) + 1
    return counts


def _load_concerns_summary_json(path: Path) -> Optional[Dict[str, int]]:
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    # ensure all int values and lowercase keys
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, int):
            return None
        if k != k.lower():
            return None
    return data


def _normalize_heading(line: str) -> str:
    # strip leading markdown heading markers and spaces
    s = line.lstrip()
    s = re.sub(r'^[#]+\s*', '', s)
    return s.strip()


def _find_section_lines(md_text: str, heading: str) -> List[str]:
    lines = md_text.splitlines()
    section_lines: List[str] = []
    in_section = False
    for i, line in enumerate(lines):
        norm = _normalize_heading(line)
        if not in_section:
            if norm == heading:
                in_section = True
                continue
        else:
            # stop at next heading
            if line.lstrip().startswith("#"):
                break
            section_lines.append(line)
    return section_lines


def _extract_bullet_lines(lines: List[str]) -> List[str]:
    bullets = []
    for line in lines:
        if re.match(r'^\s*[-\*\u2022]\s+', line):
            bullets.append(line.strip())
    return bullets


def _find_script_path(workspace: Path) -> Optional[Path]:
    candidates = [
        workspace / "scripts" / "generate_blog_plan.py",
        workspace / "scripts" / "generate_blog_plan.js",
        workspace / "scripts" / "generate_blog_plan.sh",
        workspace / "scripts" / "generate_blog_plan.rb",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _parse_run_log_counts(log_text: str) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[str], Optional[int]]:
    # Returns tuple: (products_count, unique_ingredients_count, unique_concerns_count, command_line, exit_status)
    products_count = None
    ingredients_count = None
    concerns_count = None
    command_line = None
    exit_status = None

    for line in log_text.splitlines():
        lower = line.lower()
        # command line
        if "scripts/generate_blog_plan" in line and command_line is None:
            # take the whole line as command or extract after a colon
            m = re.search(r'[:]\s*(.*scripts/generate_blog_plan[^\n]*)', line)
            command_line = m.group(1).strip() if m else line.strip()
        # exit status
        if "exit status" in lower or "status" in lower:
            nums = re.findall(r'(-?\d+)', line)
            if nums:
                exit_status = int(nums[-1])
        # products extracted
        if ("product" in lower and "extract" in lower) or ("products" in lower and "count" in lower):
            nums = re.findall(r'(-?\d+)', line)
            if nums:
                products_count = int(nums[-1])
        # unique ingredients
        if "unique" in lower and "ingredient" in lower:
            nums = re.findall(r'(-?\d+)', line)
            if nums:
                ingredients_count = int(nums[-1])
        # unique concerns
        if "unique" in lower and "concern" in lower:
            nums = re.findall(r'(-?\d+)', line)
            if nums:
                concerns_count = int(nums[-1])

    return products_count, ingredients_count, concerns_count, command_line, exit_status


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_file_present": 0.0,
        "run_sh_present_and_invokes_script": 0.0,
        "products_json_structure_and_sorting": 0.0,
        "products_json_matches_input_html": 0.0,
        "concerns_summary_counts_match": 0.0,
        "blog_launch_guide_headings_present": 0.0,
        "blog_launch_guide_top3_based_on_data": 0.0,
        "first_post_references_products_and_ingredients": 0.0,
        "first_post_what_actually_worked_section": 0.0,
        "content_calendar_structure_and_weeks": 0.0,
        "content_calendar_keywords_and_slugs_valid": 0.0,
        "run_log_command_and_status_present": 0.0,
        "run_log_counts_consistent": 0.0,
        "writing_emphasizes_sensitive_dry": 0.0,
    }

    # Paths
    input_dir = workspace / "input"
    product_html_dir = input_dir / "product_pages"
    testimonials_csv = input_dir / "testimonials.csv"
    persona_md = input_dir / "persona_notes.md"

    products_json_path = workspace / "output" / "extracted" / "products.json"
    concerns_summary_path = workspace / "output" / "analysis" / "concerns_summary.json"
    blog_launch_guide_path = workspace / "output" / "writing" / "blog_launch_guide.md"
    first_post_path = workspace / "output" / "writing" / "first_post_draft.md"
    content_calendar_path = workspace / "output" / "writing" / "content_calendar.csv"
    run_log_path = workspace / "output" / "logs" / "run_log.txt"
    run_sh_path = workspace / "run.sh"

    # Check script existence
    script_path = _find_script_path(workspace)
    if script_path is not None and script_path.exists():
        scores["script_file_present"] = 1.0

    # run.sh present and invokes script
    run_sh_ok = False
    if run_sh_path.exists():
        run_sh_text = _read_text(run_sh_path) or ""
        # Checks that it invokes scripts/generate_blog_plan with any extension
        if re.search(r'scripts/generate_blog_plan\.(py|js|sh|rb)', run_sh_text):
            run_sh_ok = True
            # optionally ensure the invoked extension matches existing
            if script_path is not None:
                ext = script_path.suffix
                if f"scripts/generate_blog_plan{ext}" not in run_sh_text:
                    # allow flexible invocation as long as it contains base name
                    run_sh_ok = True
        else:
            run_sh_ok = False
    scores["run_sh_present_and_invokes_script"] = 1.0 if run_sh_ok else 0.0

    # Load products.json
    products_json = _load_products_json(products_json_path) if products_json_path.exists() else None
    if products_json is not None and isinstance(products_json, list) and len(products_json) > 0:
        scores["products_json_structure_and_sorting"] = 1.0

    # Parse products from HTML inputs and compare
    parsed_products = _parse_products_from_html_dir(product_html_dir) if product_html_dir.exists() else None
    products_match = False
    if products_json is not None and parsed_products is not None:
        # Compare lengths and content (order must match sorted by slug)
        if len(products_json) == len(parsed_products) == len(list(product_html_dir.glob("*.html"))):
            # compare each dict for required keys and values
            products_match = True
            for a, b in zip(products_json, parsed_products):
                # Only compare required keys
                for k in ["product_slug", "name", "tagline", "ingredients", "concerns", "usage"]:
                    if a.get(k) != b.get(k):
                        products_match = False
                        break
                if not products_match:
                    break
    scores["products_json_matches_input_html"] = 1.0 if products_match else 0.0

    # Concerns summary check
    expected_summary = _compute_concerns_summary_from_csv(testimonials_csv) if testimonials_csv.exists() else None
    actual_summary = _load_concerns_summary_json(concerns_summary_path) if concerns_summary_path.exists() else None
    if expected_summary is not None and actual_summary is not None and expected_summary == actual_summary:
        scores["concerns_summary_counts_match"] = 1.0

    # Blog launch guide checks
    blog_text = _read_text(blog_launch_guide_path) if blog_launch_guide_path.exists() else None
    if blog_text is not None:
        required_headings = [
            "Positioning",
            "Audience",
            "Editorial pillars",
            "SEO basics",
            "Tech stack basics",
            "Based on data",
        ]
        headings_present = True
        norms = [_normalize_heading(line) for line in blog_text.splitlines()]
        for h in required_headings:
            if h not in norms:
                headings_present = False
                break
        scores["blog_launch_guide_headings_present"] = 1.0 if headings_present else 0.0

        # Based on data: top-3 concerns with counts
        based_lines = _find_section_lines(blog_text, "Based on data")
        bullets = _extract_bullet_lines(based_lines)
        valid_top3 = False
        if bullets and expected_summary:
            # Determine 3rd order statistic
            counts_sorted = sorted(expected_summary.values(), reverse=True)
            if len(counts_sorted) >= 3:
                third = counts_sorted[2]
            elif len(counts_sorted) > 0:
                third = counts_sorted[-1]
            else:
                third = 0
            valid_concerns = {k: v for k, v in expected_summary.items() if v >= third}
            found_concerns = set()
            # For each bullet, check if it contains a valid concern and its count
            for line in bullets:
                for c, cnt in valid_concerns.items():
                    if c.lower() in line.lower() and re.search(rf'\b{cnt}\b', line):
                        found_concerns.add(c)
            # Need at least 3 unique concerns captured
            if len(found_concerns) >= 3:
                valid_top3 = True
        scores["blog_launch_guide_top3_based_on_data"] = 1.0 if valid_top3 else 0.0

        # Emphasize sensitive/dry
        lt = blog_text.lower()
        if ("sensitive" in lt) and ("dry" in lt or "dryness" in lt):
            scores["writing_emphasizes_sensitive_dry"] = 1.0

    # First post draft checks
    first_post_text = _read_text(first_post_path) if first_post_path.exists() else None
    if first_post_text is not None and products_json is not None:
        includes_products = ("Calm Restore Serum" in first_post_text) and ("Hydra Night Repair Cream" in first_post_text)
        # Collect all ingredient names from products.json
        all_ingredients = []
        for p in products_json:
            all_ingredients.extend(p.get("ingredients", []))
        ing_found = set()
        for ing in all_ingredients:
            if ing and ing in first_post_text:
                ing_found.add(ing)
            # also check lowercase version presence if casing varies
            elif ing and ing.lower() in first_post_text.lower():
                ing_found.add(ing)
        includes_two_ingredients = len(ing_found) >= 2
        if includes_products and includes_two_ingredients:
            scores["first_post_references_products_and_ingredients"] = 1.0

        # What actually worked section with bullets >=3: at least two ingredient callouts and one routine change
        section_lines = _find_section_lines(first_post_text, "What actually worked")
        bullets = _extract_bullet_lines(section_lines)
        ok_bullets = False
        if len(bullets) >= 3:
            # Ingredient callouts: bullet lines containing ingredient names
            ing_bullets = 0
            routine_keywords = ["routine", "am", "pm", "morning", "night", "last step", "after cleansing", "cleanser", "serum", "cream"]
            routine_bullet = False
            for b in bullets:
                for ing in all_ingredients:
                    if ing and (ing in b or ing.lower() in b.lower()):
                        ing_bullets += 1
                        break
                for rk in routine_keywords:
                    if rk in b.lower():
                        routine_bullet = True
            if ing_bullets >= 2 and routine_bullet:
                ok_bullets = True
        scores["first_post_what_actually_worked_section"] = 1.0 if ok_bullets else 0.0

    # Content calendar checks
    calendar_ok = False
    calendar_keywords_slugs_ok = False
    if content_calendar_path.exists() and products_json is not None and expected_summary is not None:
        try:
            with content_calendar_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                expected_header = ["week", "post_title", "content_type", "target_keyword", "primary_product_slug"]
                if header == expected_header:
                    data_rows = rows[1:]
                    # weeks 1..8 present exactly
                    weeks = []
                    content_types = []
                    target_keywords = []
                    primary_slugs = []
                    for r in data_rows:
                        if len(r) != 5:
                            raise ValueError("Row length mismatch")
                        weeks.append(r[0].strip())
                        content_types.append(r[2].strip())
                        target_keywords.append(r[3].strip())
                        primary_slugs.append(r[4].strip())
                    # Check weeks 1..8
                    expected_weeks = [str(i) for i in range(1, 9)]
                    if sorted(weeks) == expected_weeks and len(weeks) == 8:
                        # Check at least one evergreen and one comparison
                        if any(ct == "evergreen" for ct in content_types) and any(ct == "comparison" for ct in content_types):
                            calendar_ok = True
                    # Check slugs and keywords
                    product_slugs = {p["product_slug"] for p in products_json}
                    # Build S = unique ingredients (lowercased) ∪ concerns (lowercased) ∪ skin_concern from testimonials.csv (lowercased)
                    ingredients_set = {ing.strip().lower() for p in products_json for ing in p.get("ingredients", []) if isinstance(ing, str)}
                    concerns_set = {c.strip().lower() for p in products_json for c in p.get("concerns", []) if isinstance(c, str)}
                    testimonial_set = set(expected_summary.keys())
                    S = ingredients_set | concerns_set | testimonial_set
                    slugs_ok = all(slug in product_slugs for slug in primary_slugs)
                    keywords_ok = all((kw.strip().lower() in S and kw.strip() != "") for kw in target_keywords)
                    if slugs_ok and keywords_ok:
                        calendar_keywords_slugs_ok = True
        except Exception:
            calendar_ok = False
            calendar_keywords_slugs_ok = False
    scores["content_calendar_structure_and_weeks"] = 1.0 if calendar_ok else 0.0
    scores["content_calendar_keywords_and_slugs_valid"] = 1.0 if calendar_keywords_slugs_ok else 0.0

    # Run log checks
    run_log_text = _read_text(run_log_path) if run_log_path.exists() else None
    cmd_status_ok = False
    counts_ok = False
    if run_log_text is not None:
        products_count, ingredients_count, concerns_count, command_line, exit_status = _parse_run_log_counts(run_log_text)
        # command and status present
        if command_line is not None and exit_status is not None:
            # Ensure command references generate_blog_plan and exit status is integer
            if "scripts/generate_blog_plan" in command_line and isinstance(exit_status, int):
                cmd_status_ok = True
        # counts check against products.json
        if products_json is not None:
            expected_products_count = len(products_json)
            expected_unique_ingredients = len({ing.strip().lower() for p in products_json for ing in p.get("ingredients", []) if isinstance(ing, str)})
            expected_unique_concerns = len({c.strip().lower() for p in products_json for c in p.get("concerns", []) if isinstance(c, str)})
            if (products_count == expected_products_count and
                ingredients_count == expected_unique_ingredients and
                concerns_count == expected_unique_concerns):
                counts_ok = True
    scores["run_log_command_and_status_present"] = 1.0 if cmd_status_ok else 0.0
    scores["run_log_counts_consistent"] = 1.0 if counts_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    _write_json_print(result)


if __name__ == "__main__":
    main()