import json
import os
import sys
import csv
import datetime
import re

def parse_rfc3339(ts: str) -> bool:
    if not isinstance(ts, str):
        return False
    s = ts.strip()
    if not s:
        return False
    # Replace Z with +00:00 for fromisoformat
    s2 = s.replace("Z", "+00:00")
    try:
        datetime.datetime.fromisoformat(s2)
        return True
    except Exception:
        # Fallback regex for common RFC3339 patterns
        # Examples: 2025-01-31T12:34:56Z, 2025-01-31T12:34:56+00:00, 2025-01-31T12:34:56.123Z
        pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+\-]\d{2}:\d{2})$'
        return re.match(pattern, s) is not None

def safe_lower(s):
    try:
        return str(s).lower()
    except Exception:
        return ""

def keyword_matches(skill, keywords):
    fields = []
    fields.append(safe_lower(skill.get("name", "")))
    fields.append(safe_lower(skill.get("description", "")))
    tags = skill.get("tags", [])
    tag_strs = []
    if isinstance(tags, list):
        for t in tags:
            tag_strs.append(safe_lower(t))
    elif tags is None:
        tag_strs = []
    else:
        # if tags is a string or other type, include it as a single tag string
        tag_strs.append(safe_lower(tags))
    fields.extend(tag_strs)
    matched = []
    for kw in keywords:
        kw_l = safe_lower(kw)
        if not kw_l:
            continue
        found = False
        for f in fields:
            if kw_l in f:
                found = True
                break
        if found:
            matched.append(kw)
    return matched

def join_tags(tags):
    if isinstance(tags, list):
        return ";".join([str(t) for t in tags])
    return ""

def ensure_int(v):
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return 0

def ensure_str(v):
    if v is None:
        return ""
    return str(v)

def compute_expected(all_skills, req):
    categories = req.get("categories", [])
    keywords = req.get("keywords", [])
    min_downloads = ensure_int(req.get("min_downloads", 0))
    min_updated_at = ensure_str(req.get("min_updated_at", ""))
    top_n = ensure_int(req.get("top_n_per_category", 0))

    # Base filtering: category + downloads + updated_at
    def base_pass(s):
        cat = s.get("category")
        if cat not in categories:
            return False
        dls = ensure_int(s.get("downloads", 0))
        if dls < min_downloads:
            return False
        ua = ensure_str(s.get("updated_at", ""))
        # ISO8601 lexical comparison allowed per spec
        if ua < min_updated_at:
            return False
        return True

    base_filtered = [s for s in all_skills if base_pass(s)]
    # After keywords
    keyword_filtered = []
    skill_matched_keywords = {}
    for s in base_filtered:
        m = keyword_matches(s, keywords)
        if len(m) > 0:
            keyword_filtered.append(s)
            skill_matched_keywords[s.get("slug", "")] = m

    # Group by category
    grouped = {cat: [] for cat in categories}
    for s in keyword_filtered:
        cat = s.get("category")
        if cat in grouped:
            grouped[cat].append(s)

    # Sort within each category
    for cat in categories:
        lst = grouped.get(cat, [])
        # Sort by downloads desc, stars desc, updated_at desc (lex)
        lst.sort(key=lambda x: (
            ensure_int(x.get("downloads", 0)),
            ensure_int(x.get("stars", 0)),
            ensure_str(x.get("updated_at", "")),
        ), reverse=True)
        # Take top N
        grouped[cat] = lst[:top_n] if top_n >= 0 else lst

    # Build expected CSV rows per category
    expected_csv_rows = {cat: [] for cat in categories}
    for cat in categories:
        rows = []
        for idx, s in enumerate(grouped.get(cat, []), start=1):
            slug = ensure_str(s.get("slug", ""))
            name = ensure_str(s.get("name", ""))
            dls = ensure_int(s.get("downloads", 0))
            stars = ensure_int(s.get("stars", 0))
            ua = ensure_str(s.get("updated_at", ""))
            mk = skill_matched_keywords.get(slug, [])
            mk_str = ",".join([str(k) for k in mk])
            tags_field = join_tags(s.get("tags", []) if isinstance(s.get("tags", []), list) else [])
            row = {
                "category": cat,
                "rank": str(idx),
                "slug": slug,
                "name": name,
                "downloads": str(dls),
                "stars": str(stars),
                "updated_at": ua,
                "matched_keywords": mk_str,
                "tags": tags_field
            }
            rows.append(row)
        expected_csv_rows[cat] = rows

    # Build expected catalog categories object
    expected_catalog_categories = {cat: [] for cat in categories}
    for cat in categories:
        items = []
        for s in grouped.get(cat, []):
            item = {
                "slug": ensure_str(s.get("slug", "")),
                "name": ensure_str(s.get("name", "")),
                "downloads": ensure_int(s.get("downloads", 0)),
                "stars": ensure_int(s.get("stars", 0)),
                "updated_at": ensure_str(s.get("updated_at", "")),
                "tags": s.get("tags", []) if isinstance(s.get("tags", []), list) else []
            }
            items.append(item)
        expected_catalog_categories[cat] = items

    counts = {
        "total_in_input": len(all_skills),
        "total_after_category_downloads_date": len(base_filtered),
        "total_after_keywords": len(keyword_filtered)
    }

    return expected_csv_rows, expected_catalog_categories, counts

def read_jsonl(path):
    skills = []
    if not os.path.isfile(path):
        return skills
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            ln = line.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
                if isinstance(obj, dict):
                    skills.append(obj)
            except Exception:
                # Skip invalid lines
                continue
    return skills

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    request_path = os.path.join(input_dir, "request.json")
    skills_path = os.path.join(input_dir, "skills.jsonl")
    shortlist_path = os.path.join(output_dir, "shortlist.csv")
    catalog_path = os.path.join(output_dir, "catalog.json")

    checks = {
        "has_shortlist_file": False,
        "shortlist_header_ok": False,
        "shortlist_grouped_by_category": False,
        "shortlist_matches_expected": False,
        "has_catalog_file": False,
        "catalog_json_valid": False,
        "catalog_filters_exact": False,
        "catalog_counts_correct": False,
        "catalog_categories_match_expected": False,
        "catalog_generated_at_valid": False,
    }

    # Load inputs (do not award points for this)
    try:
        with open(request_path, "r", encoding="utf-8") as f:
            request_data = json.load(f)
    except Exception:
        request_data = None

    all_skills = read_jsonl(skills_path)

    # Compute expected only if inputs are available
    expected_csv_rows = {}
    expected_catalog_categories = {}
    expected_counts = None
    if request_data is not None and isinstance(request_data, dict) and all_skills is not None:
        expected_csv_rows, expected_catalog_categories, expected_counts = compute_expected(all_skills, request_data)

    # Validate shortlist.csv
    if os.path.isfile(shortlist_path):
        checks["has_shortlist_file"] = True
        try:
            with open(shortlist_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                expected_header = ["category","rank","slug","name","downloads","stars","updated_at","matched_keywords","tags"]
                if header == expected_header:
                    checks["shortlist_header_ok"] = True
                # Parse data rows
                data_rows = rows[1:] if len(rows) > 1 else []
                # Validate grouping by category (no interleaving)
                if data_rows:
                    seen_categories = []
                    last_cat = None
                    grouped_ok = True
                    for r in data_rows:
                        # ensure exactly 9 columns
                        if len(r) != 9:
                            grouped_ok = False
                            break
                        cat = r[0]
                        if last_cat is None:
                            seen_categories.append(cat)
                            last_cat = cat
                        else:
                            if cat == last_cat:
                                pass
                            else:
                                if cat in seen_categories:
                                    grouped_ok = False
                                    break
                                seen_categories.append(cat)
                                last_cat = cat
                    if grouped_ok:
                        checks["shortlist_grouped_by_category"] = True
                else:
                    # Empty data rows can be considered grouped
                    checks["shortlist_grouped_by_category"] = True

                # Compare against expected per category
                # Build actual by category
                actual_by_cat = {}
                for r in rows[1:]:
                    if len(r) != 9:
                        actual_by_cat = None
                        break
                    cat, rank, slug, name, downloads, stars, updated_at, matched_keywords, tags = r
                    actual_by_cat.setdefault(cat, []).append({
                        "category": cat,
                        "rank": rank,
                        "slug": slug,
                        "name": name,
                        "downloads": downloads,
                        "stars": stars,
                        "updated_at": updated_at,
                        "matched_keywords": matched_keywords,
                        "tags": tags
                    })
                if actual_by_cat is not None and expected_csv_rows is not None:
                    # Determine expected categories that have non-empty selections
                    expected_nonempty = {cat for cat, lst in expected_csv_rows.items() if len(lst) > 0}
                    actual_cats = set(actual_by_cat.keys())
                    # There must be no categories outside the requested categories
                    requested_categories = set(request_data.get("categories", [])) if isinstance(request_data, dict) else set()
                    if not actual_cats.issubset(requested_categories):
                        csv_matches = False
                    else:
                        # Actual categories should equal those with non-empty expected (i.e., no rows for empty categories)
                        csv_matches = (actual_cats == expected_nonempty)
                        # And each category's rows must match expected exactly in order and values
                        if csv_matches:
                            for cat in expected_nonempty:
                                exp_rows = expected_csv_rows.get(cat, [])
                                act_rows = actual_by_cat.get(cat, [])
                                if len(exp_rows) != len(act_rows):
                                    csv_matches = False
                                    break
                                for e, a in zip(exp_rows, act_rows):
                                    # Ensure every field matches exactly as strings
                                    for key in ["category","rank","slug","name","downloads","stars","updated_at","matched_keywords","tags"]:
                                        if str(a.get(key, "")) != str(e.get(key, "")):
                                            csv_matches = False
                                            break
                                    if not csv_matches:
                                        break
                            # Also ensure ranks are 1..N within each category
                            if csv_matches:
                                for cat in actual_by_cat:
                                    act_rows = actual_by_cat[cat]
                                    for idx, r in enumerate(act_rows, start=1):
                                        if str(r["rank"]) != str(idx):
                                            csv_matches = False
                                            break
                                    if not csv_matches:
                                        break
                    if csv_matches:
                        checks["shortlist_matches_expected"] = True
                        # ranks check is included above; mark grouped ranks ok if matches expected
                        # We already set shortlist_grouped_by_category separately
                # else leave as False
        except Exception:
            pass

    # Validate catalog.json
    if os.path.isfile(catalog_path):
        checks["has_catalog_file"] = True
        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                catalog = json.load(f)
            checks["catalog_json_valid"] = True

            # filters exact
            if request_data is not None and isinstance(request_data, dict):
                if isinstance(catalog, dict) and "filters" in catalog and catalog["filters"] == request_data:
                    checks["catalog_filters_exact"] = True

            # counts correct
            if expected_counts is not None and isinstance(catalog, dict):
                counts = catalog.get("counts")
                if isinstance(counts, dict):
                    tii = counts.get("total_in_input")
                    tad = counts.get("total_after_category_downloads_date")
                    tak = counts.get("total_after_keywords")
                    if (tii == expected_counts["total_in_input"] and
                        tad == expected_counts["total_after_category_downloads_date"] and
                        tak == expected_counts["total_after_keywords"]):
                        checks["catalog_counts_correct"] = True

            # categories match expected
            if isinstance(catalog, dict) and expected_catalog_categories is not None:
                cats_obj = catalog.get("categories")
                if isinstance(cats_obj, dict):
                    expected_keys = set(expected_catalog_categories.keys())
                    actual_keys = set(cats_obj.keys())
                    # Require exactly the requested categories
                    if actual_keys == expected_keys:
                        cat_match = True
                        for cat, exp_items in expected_catalog_categories.items():
                            act_items = cats_obj.get(cat)
                            if not isinstance(act_items, list):
                                cat_match = False
                                break
                            if len(exp_items) != len(act_items):
                                cat_match = False
                                break
                            for e, a in zip(exp_items, act_items):
                                # Require exactly the expected keys
                                expected_item_keys = {"slug","name","downloads","stars","updated_at","tags"}
                                if set(a.keys()) != expected_item_keys:
                                    cat_match = False
                                    break
                                if (a.get("slug") != e.get("slug") or
                                    a.get("name") != e.get("name") or
                                    a.get("downloads") != e.get("downloads") or
                                    a.get("stars") != e.get("stars") or
                                    a.get("updated_at") != e.get("updated_at") or
                                    a.get("tags") != e.get("tags")):
                                    cat_match = False
                                    break
                            if not cat_match:
                                break
                        if cat_match:
                            checks["catalog_categories_match_expected"] = True

            # generated_at valid RFC3339
            if isinstance(catalog, dict) and "generated_at" in catalog:
                if parse_rfc3339(catalog["generated_at"]):
                    checks["catalog_generated_at_valid"] = True

        except Exception:
            # leave catalog checks as False
            pass

    # Compute reward: only based on output-dependent checks
    # Weights: CSV 0.5, Catalog 0.5
    reward = 0.0
    # CSV contributions
    if checks["has_shortlist_file"]:
        reward += 0.05
    if checks["shortlist_header_ok"]:
        reward += 0.05
    if checks["shortlist_grouped_by_category"]:
        reward += 0.05
    if checks["shortlist_matches_expected"]:
        reward += 0.35
    # Catalog contributions
    if checks["has_catalog_file"]:
        reward += 0.05
    if checks["catalog_json_valid"]:
        reward += 0.05
    if checks["catalog_filters_exact"]:
        reward += 0.05
    if checks["catalog_counts_correct"]:
        reward += 0.15
    if checks["catalog_categories_match_expected"]:
        reward += 0.15
    if checks["catalog_generated_at_valid"]:
        reward += 0.05

    # Clamp reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()