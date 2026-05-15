import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


BRAND_NAME = "New Hope Community Church"
OLD_BRAND_NAME = "First United Church"
CTA_PHRASES = [
    "Plan Your Visit",
    "Join us Sunday",
    "Get Connected",
    "Serve with Us",
]


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_csv_safe(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None, None


def write_json_stdout(data: Dict) -> None:
    print(json.dumps(data, ensure_ascii=False))


def parse_keyword_map_yaml(path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    """
    Minimal YAML parser tailored to the provided keyword_map.yaml structure.
    Returns dict: {slug: {"primary": str, "secondary": [str, ...]}}
    """
    text = read_text_safe(path)
    if text is None:
        return None
    result: Dict[str, Dict[str, object]] = {}
    current_slug: Optional[str] = None
    in_secondary_list = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if not line.startswith(" "):  # top-level slug
            if ":" in line:
                key = line.split(":", 1)[0].strip()
                current_slug = key
                result[current_slug] = {"primary": "", "secondary": []}
                in_secondary_list = False
            continue
        # nested under slug
        if current_slug is None:
            continue
        # two-space indent entries
        stripped = line.strip()
        if stripped.startswith("primary:"):
            val = stripped.split(":", 1)[1].strip()
            val = val.strip('"').strip("'")
            result[current_slug]["primary"] = val
            in_secondary_list = False
        elif stripped.startswith("secondary:"):
            in_secondary_list = True
        elif in_secondary_list and stripped.startswith("-"):
            item = stripped[1:].strip()
            item = item.strip('"').strip("'")
            sec = result[current_slug].get("secondary")
            if isinstance(sec, list):
                sec.append(item)
    # Validate minimal structure
    try:
        final: Dict[str, Dict[str, str]] = {}
        for slug, data in result.items():
            primary = data.get("primary", "")
            if not isinstance(primary, str):
                return None
            final[slug] = {"primary": primary}
        return final
    except Exception:
        return None


def list_to_map(rows: List[Dict[str, str]], key_field: str) -> Dict[str, Dict[str, str]]:
    return {row.get(key_field, ""): row for row in rows}


def get_h1_and_opening_paragraph(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns the H1 line and opening paragraph (text between the H1 and first blank line).
    """
    if text is None:
        return None, None
    lines = text.splitlines()
    h1_line = None
    idx = 0
    # Find first h1 starting with '#'
    for i, line in enumerate(lines):
        if line.strip().startswith("#"):
            h1_line = line.strip()
            idx = i + 1
            break
    # Collect opening paragraph until blank line
    para_lines = []
    for j in range(idx, len(lines)):
        ln = lines[j]
        if not ln.strip():  # blank line ends paragraph
            break
        para_lines.append(ln)
    opening = "\n".join(para_lines).strip() if para_lines else None
    return h1_line, opening


def keyword_in_h1_or_opening(text: Optional[str], keyword: Optional[str]) -> bool:
    if text is None or keyword is None:
        return False
    h1, opening = get_h1_and_opening_paragraph(text)
    kw = (keyword or "").lower()
    if not kw:
        return False
    for segment in [h1 or "", opening or ""]:
        if kw in segment.lower():
            return True
    return False


def last_nonempty_line(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return None


def has_cta_at_end(text: Optional[str]) -> bool:
    ln = last_nonempty_line(text)
    if ln is None:
        return False
    for phrase in CTA_PHRASES:
        if phrase in ln:
            return True
    return False


def contains_brand_exact(text: Optional[str]) -> bool:
    if text is None:
        return False
    return BRAND_NAME in text


def contains_old_brand(text: Optional[str]) -> bool:
    if text is None:
        return False
    return OLD_BRAND_NAME in text


def count_occurrences(haystack: str, needle: str) -> int:
    return haystack.count(needle)


def safe_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def compute_normalized_traffic(rows: List[Dict[str, str]]) -> Dict[str, float]:
    traffs = [safe_int(r.get("traffic_last_30_days", "0"), 0) for r in rows]
    if not traffs:
        return {}
    mn = min(traffs)
    mx = max(traffs)
    norm = {}
    if mx == mn:
        for r in rows:
            slug = r.get("slug", "")
            norm[slug] = 0.5
        return norm
    for r in rows:
        slug = r.get("slug", "")
        t = safe_int(r.get("traffic_last_30_days", "0"), 0)
        norm[slug] = (t - mn) / (mx - mn)
    return norm


def close_enough(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        # Content rewrites existence
        "rewrite_about_exists": 0.0,
        "rewrite_ministries_exists": 0.0,
        "rewrite_visit_exists": 0.0,
        # Brand replacement checks
        "about_replaced_brand_exact": 0.0,
        "ministries_replaced_brand_exact": 0.0,
        "visit_replaced_brand_exact": 0.0,
        "about_no_old_name": 0.0,
        "ministries_no_old_name": 0.0,
        "visit_no_old_name": 0.0,
        # Primary keyword placement checks
        "about_primary_keyword_in_h1_or_opening": 0.0,
        "ministries_primary_keyword_in_h1_or_opening": 0.0,
        "visit_primary_keyword_in_h1_or_opening": 0.0,
        # Springfield retention checks (where applicable)
        "about_springfield_retained": 0.0,
        "visit_springfield_retained": 0.0,
        # CTA at end
        "about_cta_at_end": 0.0,
        "ministries_cta_at_end": 0.0,
        "visit_cta_at_end": 0.0,
        # Optimized meta checks
        "optimized_meta_exists": 0.0,
        "optimized_meta_columns_correct": 0.0,
        "optimized_meta_rows_complete": 0.0,
        "optimized_meta_brand_in_both_fields_all_rows": 0.0,
        "optimized_meta_primary_keyword_flag_correct": 0.0,
        "optimized_meta_length_constraints_all_rows": 0.0,
        "optimized_meta_old_fields_match_input": 0.0,
        "optimized_meta_flag_fields_correct": 0.0,
        # Priority report checks
        "priority_report_exists": 0.0,
        "priority_report_columns_correct": 0.0,
        "priority_report_rows_complete": 0.0,
        "priority_report_computed_values_correct": 0.0,
        "priority_report_sorted_correct": 0.0,
        "priority_report_rank_correct": 0.0,
        # Issues report checks
        "issues_exists": 0.0,
        "issues_columns_match_priority_report": 0.0,
        "issues_filtered_correct": 0.0,
        "issues_sorted_correct": 0.0,
        # Status update checks
        "status_update_exists": 0.0,
        "status_addressed_to_stakeholders": 0.0,
        "status_summary_counts_correct": 0.0,
        "status_top_priorities_listed": 0.0,
        "status_before_after_visit_includes_old_and_new": 0.0,
        "status_next_steps_section_present": 0.0,
    }

    # Load inputs
    input_site_pages_path = workspace / "input" / "site_pages.csv"
    site_headers, site_rows = read_csv_safe(input_site_pages_path)
    site_loaded = site_headers is not None and site_rows is not None

    keyword_map_path = workspace / "input" / "keyword_map.yaml"
    keyword_map = parse_keyword_map_yaml(keyword_map_path)

    brand_guidelines_path = workspace / "input" / "brand_guidelines.md"
    brand_guidelines = read_text_safe(brand_guidelines_path)

    about_in_path = workspace / "input" / "content" / "about.md"
    ministries_in_path = workspace / "input" / "content" / "ministries.md"
    visit_in_path = workspace / "input" / "content" / "visit.md"
    about_in_text = read_text_safe(about_in_path)
    ministries_in_text = read_text_safe(ministries_in_path)
    visit_in_text = read_text_safe(visit_in_path)

    # Content rewrites output paths
    about_out_path = workspace / "output" / "content" / "about.md"
    ministries_out_path = workspace / "output" / "content" / "ministries.md"
    visit_out_path = workspace / "output" / "content" / "visit.md"

    about_out_text = read_text_safe(about_out_path)
    ministries_out_text = read_text_safe(ministries_out_path)
    visit_out_text = read_text_safe(visit_out_path)

    # Existence checks
    if about_out_text is not None:
        scores["rewrite_about_exists"] = 1.0
    if ministries_out_text is not None:
        scores["rewrite_ministries_exists"] = 1.0
    if visit_out_text is not None:
        scores["rewrite_visit_exists"] = 1.0

    # Brand replacement checks
    def brand_checks(out_text: Optional[str], key_prefix: str) -> None:
        if out_text is None:
            return
        # Must include brand name somewhere and exclude old brand entirely
        replaced_ok = contains_brand_exact(out_text) and not contains_old_brand(out_text)
        scores[f"{key_prefix}_replaced_brand_exact"] = 1.0 if replaced_ok else 0.0
        scores[f"{key_prefix}_no_old_name"] = 1.0 if not contains_old_brand(out_text) else 0.0

    brand_checks(about_out_text, "about")
    brand_checks(ministries_out_text, "ministries")
    brand_checks(visit_out_text, "visit")

    # Primary keyword in H1 or opening paragraph checks
    def primary_kw_for(slug: str) -> Optional[str]:
        if keyword_map is None:
            return None
        entry = keyword_map.get(slug)
        if not entry:
            return None
        return entry.get("primary")

    if keyword_map is not None:
        about_kw = primary_kw_for("about")
        ministries_kw = primary_kw_for("ministries")
        visit_kw = primary_kw_for("visit")
        if about_out_text is not None and about_kw:
            scores["about_primary_keyword_in_h1_or_opening"] = 1.0 if keyword_in_h1_or_opening(about_out_text, about_kw) else 0.0
        if ministries_out_text is not None and ministries_kw:
            scores["ministries_primary_keyword_in_h1_or_opening"] = 1.0 if keyword_in_h1_or_opening(ministries_out_text, ministries_kw) else 0.0
        if visit_out_text is not None and visit_kw:
            scores["visit_primary_keyword_in_h1_or_opening"] = 1.0 if keyword_in_h1_or_opening(visit_out_text, visit_kw) else 0.0

    # Springfield retention checks only for pages that originally mentioned Springfield
    def had_springfield(text: Optional[str]) -> bool:
        if text is None:
            return False
        return "Springfield" in text

    if about_out_text is not None and about_in_text is not None:
        scores["about_springfield_retained"] = 1.0 if (not had_springfield(about_in_text) or "Springfield" in about_out_text) else 0.0
    if visit_out_text is not None and visit_in_text is not None:
        scores["visit_springfield_retained"] = 1.0 if (not had_springfield(visit_in_text) or "Springfield" in visit_out_text) else 0.0

    # CTA at end checks
    if about_out_text is not None:
        scores["about_cta_at_end"] = 1.0 if has_cta_at_end(about_out_text) else 0.0
    if ministries_out_text is not None:
        scores["ministries_cta_at_end"] = 1.0 if has_cta_at_end(ministries_out_text) else 0.0
    if visit_out_text is not None:
        scores["visit_cta_at_end"] = 1.0 if has_cta_at_end(visit_out_text) else 0.0

    # Optimized meta checks
    optimized_meta_path = workspace / "output" / "seo" / "optimized_meta.csv"
    opt_headers, opt_rows = read_csv_safe(optimized_meta_path)
    expected_opt_cols = [
        "slug",
        "old_title",
        "old_meta_description",
        "new_title",
        "new_meta_description",
        "new_title_length",
        "new_meta_length",
        "includes_primary_keyword(0/1)",
        "includes_brand_name(0/1)",
    ]
    if opt_rows is not None:
        scores["optimized_meta_exists"] = 1.0
        if opt_headers == expected_opt_cols:
            scores["optimized_meta_columns_correct"] = 1.0

        if site_loaded:
            input_slugs = [r.get("slug", "") for r in site_rows]
            output_slugs = [r.get("slug", "") for r in opt_rows]
            if sorted(input_slugs) == sorted(output_slugs) and len(input_slugs) == len(output_slugs):
                scores["optimized_meta_rows_complete"] = 1.0

            # Old fields match input
            input_map = list_to_map(site_rows, "slug")
            old_match_ok = True
            for row in opt_rows:
                slug = row.get("slug", "")
                in_row = input_map.get(slug)
                if not in_row:
                    old_match_ok = False
                    break
                if row.get("old_title", "") != in_row.get("title", ""):
                    old_match_ok = False
                    break
                if row.get("old_meta_description", "") != in_row.get("meta_description", ""):
                    old_match_ok = False
                    break
            scores["optimized_meta_old_fields_match_input"] = 1.0 if old_match_ok else 0.0

        # Brand and keyword inclusion, lengths, flags
        brand_both_ok = True
        length_ok = True
        primary_flag_ok = True
        flag_fields_ok = True

        # Determine primary keywords per slug
        primary_by_slug = {}
        if keyword_map is not None:
            for slug, entry in keyword_map.items():
                primary_by_slug[slug] = entry.get("primary", "")

        for row in opt_rows:
            slug = row.get("slug", "")
            new_title = row.get("new_title", "") or ""
            new_meta = row.get("new_meta_description", "") or ""
            # Brand name must appear in both
            brand_in_title = BRAND_NAME in new_title
            brand_in_meta = BRAND_NAME in new_meta
            if not (brand_in_title and brand_in_meta):
                brand_both_ok = False
            # Length constraints and recorded lengths
            title_len = len(new_title)
            meta_len = len(new_meta)
            if not (45 <= title_len <= 60):
                length_ok = False
            if not (150 <= meta_len <= 160):
                length_ok = False
            # Check recorded lengths
            try:
                rec_title_len = int(row.get("new_title_length", ""))
                rec_meta_len = int(row.get("new_meta_length", ""))
            except Exception:
                flag_fields_ok = False
                rec_title_len = -1
                rec_meta_len = -1
            if rec_title_len != title_len or rec_meta_len != meta_len:
                flag_fields_ok = False
            # Primary keyword flag correctness (1 if present in either title or meta)
            primary_kw = primary_by_slug.get(slug, "")
            present_kw = False
            if primary_kw:
                if primary_kw.lower() in new_title.lower() or primary_kw.lower() in new_meta.lower():
                    present_kw = True
            else:
                # If no keyword available, we cannot validate; mark as False
                present_kw = False
            rec_primary_flag_str = (row.get("includes_primary_keyword(0/1)", "") or "").strip()
            try:
                rec_primary_flag = int(rec_primary_flag_str)
            except Exception:
                rec_primary_flag = -1
            if (1 if present_kw else 0) != rec_primary_flag:
                primary_flag_ok = False
            # Brand flag correctness
            rec_brand_flag_str = (row.get("includes_brand_name(0/1)", "") or "").strip()
            try:
                rec_brand_flag = int(rec_brand_flag_str)
            except Exception:
                rec_brand_flag = -1
            if (1 if (brand_in_title and brand_in_meta) else 0) != rec_brand_flag:
                flag_fields_ok = False

        scores["optimized_meta_brand_in_both_fields_all_rows"] = 1.0 if brand_both_ok else 0.0
        scores["optimized_meta_primary_keyword_flag_correct"] = 1.0 if primary_flag_ok else 0.0
        scores["optimized_meta_length_constraints_all_rows"] = 1.0 if length_ok else 0.0
        scores["optimized_meta_flag_fields_correct"] = 1.0 if flag_fields_ok else 0.0

    # Priority report checks
    priority_path = workspace / "output" / "seo" / "priority_report.csv"
    pr_headers, pr_rows = read_csv_safe(priority_path)
    expected_pr_cols = [
        "slug",
        "traffic_last_30_days",
        "word_count",
        "page_type",
        "primary_keyword",
        "title_contains_primary",
        "meta_length_ok",
        "content_short",
        "normalized_traffic",
        "priority_score",
        "rank",
    ]
    if pr_rows is not None:
        scores["priority_report_exists"] = 1.0
        if pr_headers == expected_pr_cols:
            scores["priority_report_columns_correct"] = 1.0
        if site_loaded:
            input_slugs = [r.get("slug", "") for r in site_rows]
            output_slugs = [r.get("slug", "") for r in pr_rows]
            if sorted(input_slugs) == sorted(output_slugs) and len(input_slugs) == len(output_slugs):
                scores["priority_report_rows_complete"] = 1.0

            # Compute values and verify
            input_map = list_to_map(site_rows, "slug")
            norm = compute_normalized_traffic(site_rows)
            values_ok = True
            # Build expected sorted order for later checks
            comp_list = []
            for row in pr_rows:
                slug = row.get("slug", "")
                in_row = input_map.get(slug)
                if not in_row or keyword_map is None:
                    values_ok = False
                    break
                primary_kw = keyword_map.get(slug, {}).get("primary", "")
                # verify primary_keyword field
                if row.get("primary_keyword", "") != primary_kw:
                    values_ok = False
                    break
                old_title = in_row.get("title", "") or ""
                old_meta = in_row.get("meta_description", "") or ""
                title_contains_primary = 1 if (primary_kw.lower() in old_title.lower()) else 0
                meta_length_ok = 1 if (150 <= len(old_meta) <= 160) else 0
                content_short = 1 if (safe_int(in_row.get("word_count", "0"), 0) < 400) else 0
                normalized_traffic = norm.get(slug, 0.0)
                page_type_bonus = 1 if (in_row.get("page_type", "") == "Core") else 0
                priority_score = (
                    0.5 * normalized_traffic
                    + 0.2 * content_short
                    + 0.15 * (1 - title_contains_primary)
                    + 0.1 * (1 - meta_length_ok)
                    + 0.05 * page_type_bonus
                )
                # compare fields
                try:
                    file_title_contains_primary = int(row.get("title_contains_primary", ""))
                    file_meta_length_ok = int(row.get("meta_length_ok", ""))
                    file_content_short = int(row.get("content_short", ""))
                except Exception:
                    values_ok = False
                    break
                try:
                    file_norm = float(row.get("normalized_traffic", ""))
                    file_pri = float(row.get("priority_score", ""))
                except Exception:
                    values_ok = False
                    break
                if file_title_contains_primary != title_contains_primary:
                    values_ok = False
                    break
                if file_meta_length_ok != meta_length_ok:
                    values_ok = False
                    break
                if file_content_short != content_short:
                    values_ok = False
                    break
                if not close_enough(file_norm, normalized_traffic):
                    values_ok = False
                    break
                if not close_enough(file_pri, priority_score):
                    values_ok = False
                    break
                comp_list.append({
                    "slug": slug,
                    "traffic": safe_int(in_row.get("traffic_last_30_days", "0"), 0),
                    "priority_score": priority_score
                })
            scores["priority_report_computed_values_correct"] = 1.0 if values_ok else 0.0

            # Sorting and rank checks
            if values_ok:
                # Expected sort: priority_score desc; ties by traffic desc; then slug asc
                expected_sorted = sorted(
                    comp_list,
                    key=lambda x: (-x["priority_score"], -x["traffic"], x["slug"])
                )
                pr_order_slugs = [r.get("slug", "") for r in pr_rows]
                expected_order_slugs = [x["slug"] for x in expected_sorted]
                scores["priority_report_sorted_correct"] = 1.0 if pr_order_slugs == expected_order_slugs else 0.0
                # Rank correctness: 1-based in this sorted order
                rank_ok = True
                for i, r in enumerate(pr_rows, start=1):
                    try:
                        rk = int(r.get("rank", ""))
                    except Exception:
                        rank_ok = False
                        break
                    if rk != i:
                        rank_ok = False
                        break
                scores["priority_report_rank_correct"] = 1.0 if rank_ok else 0.0

    # Issues report checks
    issues_path = workspace / "output" / "seo" / "issues.csv"
    issues_headers, issues_rows = read_csv_safe(issues_path)
    if issues_rows is not None:
        scores["issues_exists"] = 1.0
        # Columns match priority report
        if pr_headers is not None and issues_headers == pr_headers:
            scores["issues_columns_match_priority_report"] = 1.0
        # Filter correctness: subset where content_short==1 or title_contains_primary==0 or meta_length_ok==0
        if pr_rows is not None and pr_headers == expected_pr_cols:
            # Build expected filtered ordered rows based on pr_rows as they should be sorted same
            expected_filtered = []
            for row in pr_rows:
                try:
                    t_flag = int(row.get("title_contains_primary", ""))
                    m_flag = int(row.get("meta_length_ok", ""))
                    c_flag = int(row.get("content_short", ""))
                except Exception:
                    t_flag = 1
                    m_flag = 1
                    c_flag = 0
                if c_flag == 1 or t_flag == 0 or m_flag == 0:
                    expected_filtered.append(row)
            # Check equality by slug sequence
            expected_slugs = [r.get("slug", "") for r in expected_filtered]
            actual_slugs = [r.get("slug", "") for r in issues_rows]
            scores["issues_filtered_correct"] = 1.0 if expected_slugs == actual_slugs else 0.0
            # Sorted same order as priority
            scores["issues_sorted_correct"] = 1.0 if expected_slugs == actual_slugs else 0.0

    # Status update checks
    status_path = workspace / "output" / "report" / "status_update.md"
    status_text = read_text_safe(status_path)
    if status_text is not None:
        scores["status_update_exists"] = 1.0
        # Addressed to Senior Pastor and Communications Team
        addressed_ok = ("Senior Pastor" in status_text) and ("Communications Team" in status_text)
        scores["status_addressed_to_stakeholders"] = 1.0 if addressed_ok else 0.0

        # Parse sections by headings
        def parse_sections_md(text: str) -> Dict[str, str]:
            sections: Dict[str, str] = {}
            current = None
            buf: List[str] = []
            for line in text.splitlines():
                if line.strip().startswith("#"):
                    # store previous
                    if current is not None:
                        sections[current] = "\n".join(buf).strip()
                        buf = []
                    # normalize heading title by stripping leading hashes
                    title = line.strip().lstrip("#").strip()
                    current = title
                else:
                    buf.append(line)
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            return sections

        sections = parse_sections_md(status_text)
        summary = ""
        top_priorities = ""
        before_after = ""
        next_steps = ""
        # Try to find sections by title names; allow variants
        for name, content in sections.items():
            lname = name.lower()
            if "summary" in lname:
                summary = content
            elif "top" in lname and "priority" in lname:
                top_priorities = content
            elif "before" in lname and "after" in lname:
                before_after = content
            elif "next" in lname and "step" in lname:
                next_steps = content

        # Summary counts correctness
        if site_rows is not None and issues_rows is not None:
            total_pages = len(site_rows)
            issues_count = len(issues_rows)
            # Check both numbers appear in summary section
            summary_ok = (str(total_pages) in summary) and (str(issues_count) in summary)
            # also ensure mentions of rewritten pages
            pages_mentioned = all(w in summary.lower() for w in ["about", "ministries", "visit"])
            scores["status_summary_counts_correct"] = 1.0 if (summary_ok and pages_mentioned) else 0.0

        # Top priorities listed: include top 3 slugs and their scores referenced
        if pr_rows is not None:
            top3_slugs = [r.get("slug", "") for r in pr_rows[:3]]
            top3_scores = []
            for r in pr_rows[:3]:
                try:
                    top3_scores.append(float(r.get("priority_score", "0")))
                except Exception:
                    top3_scores.append(0.0)
            listed_all = True
            for i, slug in enumerate(top3_slugs):
                if slug == "":
                    listed_all = False
                    break
                if slug not in top_priorities:
                    listed_all = False
                    break
                # Check score presence in some formatted way
                score = top3_scores[i]
                cand_formats = [
                    f"{score:.2f}",
                    f"{score:.3f}",
                    str(score),
                ]
                if not any(cf in top_priorities for cf in cand_formats):
                    # Not strictly require exact formatting near slug; presence anywhere is acceptable
                    listed_all = False
                    break
            scores["status_top_priorities_listed"] = 1.0 if listed_all else 0.0

        # Before/After example using 'visit' page old vs new values
        if before_after and opt_rows is not None and site_rows is not None:
            input_map = list_to_map(site_rows, "slug")
            opt_map = list_to_map(opt_rows, "slug")
            visit_in = input_map.get("visit", {})
            visit_opt = opt_map.get("visit", {})
            old_title = visit_in.get("title", "")
            old_meta = visit_in.get("meta_description", "")
            new_title = visit_opt.get("new_title", "")
            new_meta = visit_opt.get("new_meta_description", "")
            ba_ok = all([
                old_title and old_title in before_after,
                old_meta and old_meta in before_after,
                new_title and new_title in before_after,
                new_meta and new_meta in before_after,
            ])
            scores["status_before_after_visit_includes_old_and_new"] = 1.0 if ba_ok else 0.0

        # Next Steps section presence with actionable language
        if next_steps:
            # Check presence of guidance keywords
            guidance_words = ["keyword", "meta", "content", "Springfield", "brand"]
            guidance_ok = any(w.lower() in next_steps.lower() for w in guidance_words)
            scores["status_next_steps_section_present"] = 1.0 if guidance_ok else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    write_json_stdout(result)


if __name__ == "__main__":
    main()