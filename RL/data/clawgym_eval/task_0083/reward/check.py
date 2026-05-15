import csv
import json
import os
import re
import sys
from collections import defaultdict, OrderedDict

def normalize_whitespace(s: str) -> str:
    if s is None:
        return ""
    # collapse any whitespace, strip ends
    return " ".join(str(s).split())

def norm_title_key(title: str) -> str:
    return normalize_whitespace(title).casefold()

def load_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            title = normalize_whitespace(obj.get("title", ""))
            category = normalize_whitespace(obj.get("category", ""))
            platform = normalize_whitespace(obj.get("platform", ""))
            source_url = normalize_whitespace(obj.get("source_url", ""))
            items.append({"title": title, "category": category, "platform": platform, "source_url": source_url, "source": "jsonl"})
    return items

def load_csv(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = normalize_whitespace(row.get("title", ""))
            category = normalize_whitespace(row.get("category", ""))
            platform = normalize_whitespace(row.get("platform", ""))
            source_url = normalize_whitespace(row.get("source_url", ""))
            items.append({"title": title, "category": category, "platform": platform, "source_url": source_url, "source": "csv"})
    return items

def parse_markdown_catalog(text):
    # Returns ordered list of (category, count_in_header, bullets list)
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    cat_sections = []
    current_cat = None
    current_count = None
    current_bullets = []
    header_re = re.compile(r"^## (.+) \((\d+)\)$")
    bullet_re = re.compile(r"^- (.+) — (.+) — Source: (.+)$")  # em dash U+2014
    for ln in lines:
        m = header_re.match(ln.strip())
        if m:
            # push previous
            if current_cat is not None:
                cat_sections.append((current_cat, current_count, current_bullets))
                current_bullets = []
            current_cat = m.group(1)
            current_count = int(m.group(2))
            continue
        # bullets
        if ln.strip().startswith("- "):
            mb = bullet_re.match(ln.strip())
            if mb:
                title = mb.group(1)
                platform = mb.group(2)
                url = mb.group(3)
                current_bullets.append({"title": title, "platform": platform, "source_url": url})
            else:
                # malformed bullet; still capture raw line to count but mark format later
                current_bullets.append({"title": None, "platform": None, "source_url": None, "raw": ln.strip()})
    # final push
    if current_cat is not None:
        cat_sections.append((current_cat, current_count, current_bullets))
    return cat_sections

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    allowed_categories = [
        "Messaging & Communication Automation",
        "Calendar & Scheduling",
        "Remote Coding & Development",
        "Price Monitoring & Shopping",
        "Smart Home & IoT",
    ]

    checks = OrderedDict()
    # Initialize all checks to False
    for key in [
        "has_summary",
        "has_catalog",
        "has_validation_report",
        "summary_schema_valid",
        "summary_counts_match_computed",
        "summary_categories_set_and_counts_valid",
        "summary_source_counts_match_computed",
        "summary_totals_match_categories_sum",
        "summary_expected_constants_match",  # jsonl=7,csv=3,total_unique=9,duplicates_removed=1
        "catalog_headers_in_alphabetical_order",
        "catalog_headers_counts_match",
        "catalog_bullets_format_valid",
        "catalog_total_bullets_count_match",
        "catalog_bullets_sorted_by_title_ci",
        "catalog_bullets_match_expected_records",
        "dedup_prefer_jsonl_on_conflict",
        "validation_report_has_required_lines",
        "numbers_consistent_across_files"
    ]:
        checks[key] = False

    # Resolve paths
    jsonl_path = os.path.join(input_dir, "usecases.jsonl")
    csv_path = os.path.join(input_dir, "more_usecases.csv")
    summary_path = os.path.join(output_dir, "usecases_summary.json")
    catalog_path = os.path.join(output_dir, "catalog_by_category.md")
    validation_path = os.path.join(output_dir, "validation_report.txt")

    # Read inputs; if inputs missing, we cannot compute, leave checks as False
    computed = None
    try:
        if os.path.isfile(jsonl_path) and os.path.isfile(csv_path):
            jsonl_items = load_jsonl(jsonl_path)
            csv_items = load_csv(csv_path)

            # Filter to allowed categories (exact match after normalization)
            jsonl_filt = [r for r in jsonl_items if normalize_whitespace(r["category"]) in allowed_categories]
            csv_filt = [r for r in csv_items if normalize_whitespace(r["category"]) in allowed_categories]

            jsonl_count = len(jsonl_filt)
            csv_count = len(csv_filt)

            # Merge with dedup by title, prefer jsonl
            merged_map = {}
            # track duplicates across sources
            titles_in_jsonl = set()
            for r in jsonl_filt:
                key = norm_title_key(r["title"])
                if key not in merged_map:
                    merged_map[key] = r
                else:
                    # duplicate within jsonl; keep first
                    pass
                titles_in_jsonl.add(key)
            duplicate_keys_across_sources = set()
            for r in csv_filt:
                key = norm_title_key(r["title"])
                if key in merged_map:
                    # duplicate across sources
                    duplicate_keys_across_sources.add(key)
                    # prefer existing (jsonl), so skip
                    continue
                merged_map[key] = r

            unique_items = list(merged_map.values())
            total_unique = len(unique_items)
            duplicates_removed = (jsonl_count + csv_count) - total_unique

            # Per-category counts for JSON summary; must include all five categories
            cat_counts = {cat: 0 for cat in allowed_categories}
            for r in unique_items:
                cat = normalize_whitespace(r["category"])
                if cat in cat_counts:
                    cat_counts[cat] += 1
            # Expected alphabetical order of categories for Markdown (headers)
            categories_alpha = sorted(allowed_categories, key=lambda s: s.lower())

            # Build expected bullets per category sorted by title case-insensitive
            expected_by_cat = {cat: [] for cat in allowed_categories}
            for r in unique_items:
                cat = normalize_whitespace(r["category"])
                if cat in expected_by_cat:
                    expected_by_cat[cat].append(r)
            for cat in expected_by_cat:
                expected_by_cat[cat].sort(key=lambda r: norm_title_key(r["title"]))

            computed = {
                "jsonl_count": jsonl_count,
                "csv_count": csv_count,
                "total_unique": total_unique,
                "duplicates_removed": duplicates_removed,
                "cat_counts": cat_counts,
                "categories_alpha": categories_alpha,
                "expected_by_cat": expected_by_cat,
                "duplicate_keys_across_sources": duplicate_keys_across_sources,
                "merged_map": merged_map,
            }
    except Exception:
        computed = None

    # Check files existence
    if os.path.isfile(summary_path):
        checks["has_summary"] = True
    if os.path.isfile(catalog_path):
        checks["has_catalog"] = True
    if os.path.isfile(validation_path):
        checks["has_validation_report"] = True

    # If any required output is missing, further checks that depend on them should not pass
    if checks["has_summary"] and computed is not None:
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            # schema validation
            schema_ok = (
                isinstance(summary, dict)
                and set(summary.keys()) == {"total_unique", "duplicates_removed", "categories", "source_counts"}
                and isinstance(summary.get("total_unique"), int)
                and isinstance(summary.get("duplicates_removed"), int)
                and isinstance(summary.get("categories"), list)
                and isinstance(summary.get("source_counts"), dict)
            )
            if schema_ok:
                checks["summary_schema_valid"] = True

                # categories array contains exactly the five categories, counts correct, and sum check
                cats_list = summary["categories"]
                names = [c.get("name") for c in cats_list if isinstance(c, dict)]
                counts = [c.get("count") for c in cats_list if isinstance(c, dict)]
                names_set_ok = set(names) == set(allowed_categories) and len(cats_list) == 5
                counts_ok = all(isinstance(x, int) for x in counts)
                cat_counts_match = True
                if computed is not None:
                    # match computed counts
                    for cobj in cats_list:
                        cname = cobj["name"]
                        ccount = cobj["count"]
                        if computed["cat_counts"].get(cname, None) != ccount:
                            cat_counts_match = False
                            break
                if names_set_ok and counts_ok and cat_counts_match:
                    checks["summary_categories_set_and_counts_valid"] = True

                # source_counts match
                sc = summary["source_counts"]
                src_ok = (
                    set(sc.keys()) == {"jsonl", "csv"}
                    and isinstance(sc["jsonl"], int)
                    and isinstance(sc["csv"], int)
                )
                if src_ok and computed is not None:
                    if sc["jsonl"] == computed["jsonl_count"] and sc["csv"] == computed["csv_count"]:
                        checks["summary_source_counts_match_computed"] = True

                # totals match
                totals_ok = False
                if computed is not None:
                    totals_ok = (
                        summary["total_unique"] == computed["total_unique"]
                        and summary["duplicates_removed"] == computed["duplicates_removed"]
                    )
                if totals_ok:
                    checks["summary_counts_match_computed"] = True

                # categories sum equals total_unique
                if sum(counts) == summary["total_unique"]:
                    checks["summary_totals_match_categories_sum"] = True

                # expected constants (based on dataset) check
                if (
                    summary["total_unique"] == 9
                    and summary["duplicates_removed"] == 1
                    and summary.get("source_counts", {}).get("jsonl") == 7
                    and summary.get("source_counts", {}).get("csv") == 3
                ):
                    checks["summary_expected_constants_match"] = True
        except Exception:
            pass

    # Parse markdown catalog and validate structure/content
    parsed_sections = None
    if checks["has_catalog"] and computed is not None:
        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                text = f.read()
            parsed_sections = parse_markdown_catalog(text)

            # 1) Headers in alphabetical order and exactly five categories
            header_names = [sec[0] for sec in parsed_sections]
            header_counts = [sec[1] for sec in parsed_sections]
            if header_names == computed["categories_alpha"] and len(parsed_sections) == 5:
                checks["catalog_headers_in_alphabetical_order"] = True

            # 2) Header counts match computed per-category counts (in that alpha order)
            header_counts_match = True
            for cat, count in zip(header_names, header_counts):
                if computed["cat_counts"].get(cat, -1) != count:
                    header_counts_match = False
                    break
            if header_counts_match:
                checks["catalog_headers_counts_match"] = True

            # 3) Bullets format valid and total count matches total_unique
            bullet_format_ok = True
            total_bullets = 0
            bullet_re = re.compile(r"^- (.+) — (.+) — Source: (.+)$")
            for _, _, bullets in parsed_sections:
                for bl in bullets:
                    total_bullets += 1
                    raw_line = None
                    if bl.get("title") is None:
                        bullet_format_ok = False
                    else:
                        # validate URL non-empty
                        if not bl.get("source_url"):
                            bullet_format_ok = False
                # note: format check above relies on parser; if parser stored "raw", format invalid
            if bullet_format_ok:
                checks["catalog_bullets_format_valid"] = True
            if total_bullets == computed["total_unique"]:
                checks["catalog_total_bullets_count_match"] = True

            # 4) Bullets sorted by title (case-insensitive) within each category
            bullets_sorted_ok = True
            for (cat, _count, bullets) in parsed_sections:
                titles_norm = [normalize_whitespace(b.get("title") or "") for b in bullets]
                titles_key = [t.casefold() for t in titles_norm]
                if titles_key != sorted(titles_key):
                    bullets_sorted_ok = False
                    break
            if bullets_sorted_ok:
                checks["catalog_bullets_sorted_by_title_ci"] = True

            # 5) Bullets match expected records (titles set and each platform/url matches chosen record)
            match_ok = True
            by_cat_expected = computed["expected_by_cat"]
            # Build lookup: for each category, map normalized title key -> (platform, url)
            lookups = {}
            for cat, items in by_cat_expected.items():
                lk = {}
                for r in items:
                    lk[norm_title_key(r["title"])] = (r["platform"], r["source_url"])
                lookups[cat] = lk

            for (cat, _count, bullets) in parsed_sections:
                expected_lookup = lookups.get(cat, {})
                seen_titles = set()
                for bl in bullets:
                    t_norm = norm_title_key(bl.get("title") or "")
                    if t_norm not in expected_lookup:
                        match_ok = False
                        break
                    exp_platform, exp_url = expected_lookup[t_norm]
                    # compare trimmed for platform and url
                    if normalize_whitespace(bl.get("platform") or "") != exp_platform:
                        match_ok = False
                        break
                    if normalize_whitespace(bl.get("source_url") or "") != exp_url:
                        match_ok = False
                        break
                    seen_titles.add(t_norm)
                if not match_ok:
                    break
                # Also ensure counts match exactly set, no missing or extra
                if len(seen_titles) != len(expected_lookup):
                    # However, some categories may have zero; accounted since both zero
                    if len(expected_lookup) != len(bullets):
                        match_ok = False
                        break
            if match_ok:
                checks["catalog_bullets_match_expected_records"] = True

            # 6) Dedup preference: if duplicates across sources exist, ensure JSONL fields used
            dedup_ok = True
            # Find duplicates keys across sources
            for dup_key in computed["duplicate_keys_across_sources"]:
                # Find which category this record belongs to
                rec = computed["merged_map"][dup_key]
                cat = rec["category"]
                # Now locate in parsed bullets
                section = None
                for (cname, _cnt, bullets) in parsed_sections:
                    if cname == cat:
                        section = bullets
                        break
                if section is None:
                    dedup_ok = False
                    break
                # find bullet with matching normalized title
                found = False
                for bl in section:
                    if norm_title_key(bl.get("title") or "") == dup_key:
                        found = True
                        # Must match jsonl record details, since rec is from merged_map which prefers jsonl
                        if normalize_whitespace(bl.get("platform") or "") != rec["platform"]:
                            dedup_ok = False
                        if normalize_whitespace(bl.get("source_url") or "") != rec["source_url"]:
                            dedup_ok = False
                        break
                if not found:
                    dedup_ok = False
                if not dedup_ok:
                    break
            if dedup_ok:
                checks["dedup_prefer_jsonl_on_conflict"] = True

        except Exception:
            pass

    # Validation report checks
    if checks["has_validation_report"]:
        try:
            with open(validation_path, "r", encoding="utf-8") as f:
                vtext = f.read()
            lines = [ln.strip() for ln in vtext.splitlines() if ln.strip() != ""]
            # Required exact lines
            has_total = ("Total unique: 9" in lines)
            has_dups = ("Duplicates removed: 1" in lines)
            has_cats = ("Categories: 5" in lines)
            if has_total and has_dups and has_cats:
                checks["validation_report_has_required_lines"] = True
        except Exception:
            pass

    # Cross-file consistency checks
    if checks["has_summary"] and checks["has_catalog"] and checks["has_validation_report"]:
        try:
            numbers_ok = False
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            with open(catalog_path, "r", encoding="utf-8") as f:
                cat_text = f.read()
            sections = parse_markdown_catalog(cat_text)
            total_bullets = sum(len(sec[2]) for sec in sections)
            # Extract from validation report
            with open(validation_path, "r", encoding="utf-8") as f:
                vtext = f.read()
            vlines = [ln.strip() for ln in vtext.splitlines() if ln.strip()]
            v_total = None
            v_dups = None
            for ln in vlines:
                if ln.startswith("Total unique:"):
                    try:
                        v_total = int(ln.split(":", 1)[1].strip())
                    except Exception:
                        pass
                if ln.startswith("Duplicates removed:"):
                    try:
                        v_dups = int(ln.split(":", 1)[1].strip())
                    except Exception:
                        pass
            if v_total is not None and v_dups is not None:
                if (
                    summary.get("total_unique") == v_total
                    and summary.get("duplicates_removed") == v_dups
                    and total_bullets == summary.get("total_unique")
                ):
                    numbers_ok = True
            if numbers_ok:
                checks["numbers_consistent_across_files"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks; ensure 0.0 when outputs missing
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # If outputs are completely missing or no artifact-dependent checks passed, reward should be 0.0
    reward = 0.0
    if passed > 0:
        reward = round(passed / total_checks, 6)

    # Print single JSON object
    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()