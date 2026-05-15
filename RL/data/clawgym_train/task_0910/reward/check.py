import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames if reader.fieldnames is not None else []
            return rows, headers
    except Exception:
        return None, None


def _parse_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _parse_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _parse_date(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except Exception:
        return None


def _sort_pages(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    def sort_key(r: Dict[str, str]):
        t = _parse_int(r.get("traffic_30d", ""))
        b = _parse_float(r.get("bounce_rate", ""))
        d = _parse_date(r.get("last_updated", ""))
        # For robustness: use fallbacks so sorting still works deterministically if parsing fails
        t = t if t is not None else -10**12
        b = b if b is not None else -10**12
        d = d if d is not None else datetime.max
        # traffic desc, bounce desc, last_updated asc
        return (-t, -b, d)
    return sorted(rows, key=sort_key)


def _split_markdown_after_first_paragraph(text: str) -> Tuple[Optional[str], str, str]:
    lines = text.splitlines()
    if not lines:
        return None, "", ""
    h1_line = None
    idx = 0
    if lines[0].lstrip().startswith("# "):
        h1_line = lines[0].strip()
        idx = 1
    # skip blank lines
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    first_para_start = idx
    while idx < len(lines) and lines[idx].strip() != "":
        idx += 1
    first_para_end = idx
    first_para_lines = lines[first_para_start:first_para_end]
    first_para_text = "\n".join(first_para_lines)
    rest_lines = lines[first_para_end:]
    rest_text = "\n".join(rest_lines)
    return h1_line, first_para_text, rest_text


def _extract_internal_link_targets(paragraph: str) -> List[str]:
    # Matches [text](/slug-or-path)
    pattern = re.compile(r"\[[^\]]+\]\((/[^)]+)\)")
    return pattern.findall(paragraph)


def _count_occurrences_insensitive(text: str, phrase: str) -> int:
    return text.lower().count(phrase.lower())


def _first_n_words_text(text: str, n: int) -> str:
    words = re.findall(r"\S+", text)
    return " ".join(words[:n])


def _line_contains_all(line: str, tokens: List[str]) -> bool:
    l = line.lower()
    return all(tok.lower() in l for tok in tokens)


def _find_lines_with_all_tokens(lines: List[str], tokens: List[str]) -> bool:
    for line in lines:
        if _line_contains_all(line, tokens):
            return True
    return False


def _get_section_text(full_text: str, start_marker: str, end_marker: Optional[str] = None) -> str:
    text = full_text
    lower = text.lower()
    start_idx = lower.find(start_marker.lower())
    if start_idx == -1:
        return ""
    section = text[start_idx:]
    if end_marker:
        end_idx = section.lower().find(end_marker.lower())
        if end_idx != -1:
            section = section[:end_idx]
    return section


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "priority_ranked_structure": 0.0,
        "priority_ranked_order_and_rank_positions": 0.0,
        "priority_ranked_values_match_input": 0.0,
        "optimized_files_present_top5": 0.0,
        "metadata_updates_structure": 0.0,
        "metadata_updates_rows_correct": 0.0,
        "metadata_new_title_meta_requirements": 0.0,
        "content_h1_matches_new_title": 0.0,
        "content_first_paragraph_keyword_once_within_120_words": 0.0,
        "content_internal_links_preserved": 0.0,
        "content_only_first_paragraph_changed": 0.0,
        "report_exists_and_overview": 0.0,
        "report_ranked_top5_list_correct": 0.0,
        "report_changes_summary_quality": 0.0,
        "report_next_steps_top3_present": 0.0,
    }

    # Load input pages.csv
    pages_csv_path = workspace / "input" / "pages.csv"
    pages_rows, pages_headers = _safe_read_csv(pages_csv_path)
    if not pages_rows or not pages_headers:
        # Cannot proceed; return zeros
        return scores

    # Create slug map and compute expected ranking
    slug_to_row: Dict[str, Dict[str, str]] = {}
    for r in pages_rows:
        if "slug" in r:
            slug_to_row[r["slug"]] = r

    expected_sorted_rows = _sort_pages(pages_rows)
    expected_sorted_slugs = [r["slug"] for r in expected_sorted_rows]

    # 1) Validate priority_ranked.csv
    out_ranked_path = workspace / "output" / "priority_ranked.csv"
    ranked_rows, ranked_headers = _safe_read_csv(out_ranked_path)

    expected_ranked_headers = [
        "slug",
        "title",
        "category",
        "traffic_30d",
        "bounce_rate",
        "last_updated",
        "rank_position",
    ]

    if ranked_rows is not None and ranked_headers is not None:
        # Structure check: header exact and rowcount match
        if ranked_headers == expected_ranked_headers and len(ranked_rows) == len(pages_rows):
            scores["priority_ranked_structure"] = 1.0
        else:
            scores["priority_ranked_structure"] = 0.0

        # Order and rank_positions
        order_ok = False
        rank_ok = False
        values_ok = False

        # Check order
        ranked_slugs = [r.get("slug", "") for r in ranked_rows]
        if ranked_slugs == expected_sorted_slugs:
            order_ok = True

        # Check rank positions
        rank_ok_list = []
        values_ok_list = []
        if ranked_rows:
            for idx, rr in enumerate(ranked_rows, start=1):
                # rank position
                rp = rr.get("rank_position", "")
                rp_int = _parse_int(str(rp))
                rank_ok_list.append(rp_int == idx)

                # Values match input for critical columns
                slug = rr.get("slug", "")
                src = slug_to_row.get(slug)
                if src is None:
                    values_ok_list.append(False)
                else:
                    vals_match = (
                        rr.get("title", "") == src.get("title", "") and
                        rr.get("category", "") == src.get("category", "") and
                        rr.get("traffic_30d", "") == src.get("traffic_30d", "") and
                        rr.get("bounce_rate", "") == src.get("bounce_rate", "") and
                        rr.get("last_updated", "") == src.get("last_updated", "")
                    )
                    values_ok_list.append(vals_match)
        rank_ok = all(rank_ok_list) if rank_ok_list else False
        values_ok = all(values_ok_list) if values_ok_list else False

        scores["priority_ranked_order_and_rank_positions"] = 1.0 if (order_ok and rank_ok) else 0.0
        scores["priority_ranked_values_match_input"] = 1.0 if values_ok else 0.0
    else:
        scores["priority_ranked_structure"] = 0.0
        scores["priority_ranked_order_and_rank_positions"] = 0.0
        scores["priority_ranked_values_match_input"] = 0.0

    # Determine top5 and next3 by expected ranking
    top5_slugs = expected_sorted_slugs[:5]
    next3_slugs = expected_sorted_slugs[5:8]

    # 2) Optimizations and metadata
    # Check optimized content files exist
    optimized_dir = workspace / "output" / "optimized_content"
    exist_count = 0
    for slug in top5_slugs:
        if (optimized_dir / f"{slug}.md").is_file():
            exist_count += 1
    if top5_slugs:
        scores["optimized_files_present_top5"] = exist_count / len(top5_slugs)
    else:
        scores["optimized_files_present_top5"] = 0.0

    # Metadata updates
    metadata_path = workspace / "output" / "metadata_updates.csv"
    metadata_rows, metadata_headers = _safe_read_csv(metadata_path)

    if metadata_rows is not None and metadata_headers is not None and metadata_headers == [
        "slug", "old_title", "new_title", "old_meta_description", "new_meta_description", "title_length", "meta_length"
    ]:
        # Expect exactly one row per top5 slug
        slug_to_meta_rows: Dict[str, List[Dict[str, str]]] = {}
        for mr in metadata_rows:
            slug = mr.get("slug", "")
            slug_to_meta_rows.setdefault(slug, []).append(mr)

        # Structure: exactly 5 rows (one per top5)
        if len(metadata_rows) == len(top5_slugs) and all(len(slug_to_meta_rows.get(s, [])) == 1 for s in top5_slugs):
            scores["metadata_updates_structure"] = 1.0
        else:
            scores["metadata_updates_structure"] = 0.0

        # Rows correct: old values match input, lengths correct
        correct_count = 0
        title_meta_req_count = 0
        h1_match_count = 0
        first_para_kw_count = 0
        internal_links_count = 0
        rest_unchanged_count = 0

        for slug in top5_slugs:
            src = slug_to_row.get(slug)
            meta_list = slug_to_meta_rows.get(slug, [])
            if not src or len(meta_list) != 1:
                continue
            meta = meta_list[0]
            old_title = meta.get("old_title", "")
            old_md = meta.get("old_meta_description", "")
            new_title = meta.get("new_title", "")
            new_md = meta.get("new_meta_description", "")
            title_len_str = meta.get("title_length", "")
            meta_len_str = meta.get("meta_length", "")

            # Old values match input
            old_match = (old_title == src.get("title", "")) and (old_md == src.get("meta_description", ""))
            # Lengths correct
            tlen = _parse_int(str(title_len_str))
            mlen = _parse_int(str(meta_len_str))
            lengths_match = (tlen == len(new_title)) and (mlen == len(new_md))
            if old_match and lengths_match:
                correct_count += 1

            # Title/meta requirements: include primary keyword, title <= 60, meta 120..155 inclusive
            primary_kw = src.get("primary_keyword", "") or ""
            includes_title = primary_kw.lower() in new_title.lower()
            includes_meta = primary_kw.lower() in new_md.lower()
            title_len_ok = len(new_title) <= 60
            meta_len_ok = 120 <= len(new_md) <= 155
            if includes_title and includes_meta and title_len_ok and meta_len_ok:
                title_meta_req_count += 1

            # Content validations
            # Compare optimized content with original
            original_content_path = workspace / (src.get("content_file", ""))
            new_content_path = optimized_dir / f"{slug}.md"
            original_text = _safe_read_text(original_content_path)
            new_text = _safe_read_text(new_content_path)
            if original_text is None or new_text is None:
                continue

            # H1 matches new_title
            new_h1, new_first_para, new_rest = _split_markdown_after_first_paragraph(new_text)
            if new_h1 is not None and new_h1.strip() == f"# {new_title}".strip():
                h1_match_count += 1

            orig_h1, orig_first_para, orig_rest = _split_markdown_after_first_paragraph(original_text)

            # First paragraph keyword exactly once and within 120 words
            occ = _count_occurrences_insensitive(new_first_para, primary_kw)
            within_120 = primary_kw.lower() in _first_n_words_text(new_first_para, 120).lower()
            if occ == 1 and within_120:
                first_para_kw_count += 1

            # Internal links preserved (original targets must be present in new first paragraph)
            orig_targets = set(_extract_internal_link_targets(orig_first_para))
            new_targets = set(_extract_internal_link_targets(new_first_para))
            if orig_targets.issubset(new_targets):
                internal_links_count += 1

            # Only first paragraph changed: rest must be identical (excluding H1 which is allowed to change)
            if orig_rest == new_rest:
                rest_unchanged_count += 1

        n = len(top5_slugs) if top5_slugs else 0
        scores["metadata_updates_rows_correct"] = (correct_count / n) if n else 0.0
        scores["metadata_new_title_meta_requirements"] = (title_meta_req_count / n) if n else 0.0
        scores["content_h1_matches_new_title"] = (h1_match_count / n) if n else 0.0
        scores["content_first_paragraph_keyword_once_within_120_words"] = (first_para_kw_count / n) if n else 0.0
        scores["content_internal_links_preserved"] = (internal_links_count / n) if n else 0.0
        scores["content_only_first_paragraph_changed"] = (rest_unchanged_count / n) if n else 0.0
    else:
        scores["metadata_updates_structure"] = 0.0
        scores["metadata_updates_rows_correct"] = 0.0
        scores["metadata_new_title_meta_requirements"] = 0.0
        scores["content_h1_matches_new_title"] = 0.0
        scores["content_first_paragraph_keyword_once_within_120_words"] = 0.0
        scores["content_internal_links_preserved"] = 0.0
        scores["content_only_first_paragraph_changed"] = 0.0

    # 3) Report checks
    report_path = workspace / "output" / "seo_update_report.md"
    report_text = _safe_read_text(report_path)
    if report_text is not None:
        # Overview section mentions goals and sorting rule fields
        # Require presence of keywords 'Overview', 'traffic_30d', 'bounce_rate', 'last_updated', and at least 'descending' and ('ascending' or 'older')
        overview_ok = ("overview" in report_text.lower()) and \
                      ("traffic_30d" in report_text) and \
                      ("bounce_rate" in report_text) and \
                      ("last_updated" in report_text) and \
                      ("descending" in report_text.lower()) and \
                      (("ascending" in report_text.lower()) or ("older" in report_text.lower()))
        scores["report_exists_and_overview"] = 1.0 if overview_ok else 0.0

        # Ranked Pages: a list of the top 5 with their metrics
        lines = report_text.splitlines()
        top5_list_count = 0
        # determine expected token strings from CSV
        for slug in top5_slugs:
            src = slug_to_row.get(slug, {})
            t = src.get("traffic_30d", "")
            b = src.get("bounce_rate", "")
            d = src.get("last_updated", "")
            found = _find_lines_with_all_tokens(lines, [slug, t, b, d])
            if found:
                top5_list_count += 1
        scores["report_ranked_top5_list_correct"] = (top5_list_count / len(top5_slugs)) if top5_slugs else 0.0

        # Changes Summary: for each optimized page, bullets of what changed (title, first paragraph keyword inclusion, meta description) and rationale tied to metrics
        # We'll look within the 'Changes' or 'Changes Summary' section up to 'Next Steps'
        changes_section = _get_section_text(report_text, "Changes Summary", "Next Steps")
        if not changes_section:
            changes_section = _get_section_text(report_text, "Changes", "Next Steps")
        changes_lines = changes_section.splitlines() if changes_section else []
        changes_ok_count = 0
        for slug in top5_slugs:
            # Find lines mentioning slug
            slug_lines = [ln for ln in changes_lines if slug in ln]
            if not slug_lines:
                continue
            # Combine lines for this slug vicinity (use simple join for keyword presence)
            slug_block = "\n".join(slug_lines).lower()
            # require mention of title, meta, keyword
            mentions = all(word in slug_block for word in ["title", "meta", "keyword"])
            # require some tie to metrics: presence of metric names or specific values
            src = slug_to_row.get(slug, {})
            t = src.get("traffic_30d", "")
            b = src.get("bounce_rate", "")
            d = src.get("last_updated", "")
            metrics_tie = any(tok in slug_block for tok in ["traffic", "bounce", "last_updated", t, b, d])
            if mentions and metrics_tie:
                changes_ok_count += 1
        scores["report_changes_summary_quality"] = (changes_ok_count / len(top5_slugs)) if top5_slugs else 0.0

        # Next Steps: next 3 pages by rank present in Next Steps section
        next_steps_section = _get_section_text(report_text, "Next Steps", None)
        next_steps_lines = next_steps_section.splitlines() if next_steps_section else []
        next3_count = 0
        for slug in next3_slugs:
            if any(slug in ln for ln in next_steps_lines):
                next3_count += 1
        scores["report_next_steps_top3_present"] = (next3_count / len(next3_slugs)) if next3_slugs else 0.0
    else:
        scores["report_exists_and_overview"] = 0.0
        scores["report_ranked_top5_list_correct"] = 0.0
        scores["report_changes_summary_quality"] = 0.0
        scores["report_next_steps_top3_present"] = 0.0

    # Ensure all scores are floats within [0,1]
    for k, v in list(scores.items()):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        if fv < 0.0:
            fv = 0.0
        if fv > 1.0:
            fv = 1.0
        scores[k] = fv

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()