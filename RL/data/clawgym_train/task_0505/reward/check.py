import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def _read_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_csv_strict(path: Path, expected_header: List[str]) -> Optional[List[Dict[str, str]]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            # Enforce exact header order and names
            if reader.fieldnames != expected_header:
                return None
            rows: List[Dict[str, str]] = []
            for row in reader:
                # Ensure mapping contains all expected keys
                if any(k not in row for k in expected_header):
                    return None
                # Normalize to strings (keep as-is, but ensure not None)
                clean = {k: (row.get(k, "") if row.get(k) is not None else "") for k in expected_header}
                rows.append(clean)
            return rows
    except Exception:
        return None


def _load_institutions_list(path: Path) -> Optional[List[str]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    insts: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            insts.append(line)
    return insts


def _extract_markdown_sections(content: str, section_names: List[str]) -> Dict[str, str]:
    lines = content.splitlines()
    # Match headings of the form "## Name" or "Name" possibly followed by ":"
    patterns = {
        name.lower(): re.compile(rf'^\s*(?:#{1,6}\s*)?{re.escape(name)}\s*:?\s*$', re.IGNORECASE)
        for name in section_names
    }
    section_positions: List[Tuple[str, int]] = []
    for idx, line in enumerate(lines):
        for key, pat in patterns.items():
            if pat.match(line):
                section_positions.append((key, idx))
                break
    # Sort by position
    section_positions.sort(key=lambda x: x[1])
    sections: Dict[str, str] = {}
    for i, (key, start_idx) in enumerate(section_positions):
        end_idx = section_positions[i + 1][1] if i + 1 < len(section_positions) else len(lines)
        body_lines = lines[start_idx + 1:end_idx]
        # Trim surrounding blank lines
        while body_lines and body_lines[0].strip() == "":
            body_lines.pop(0)
        while body_lines and body_lines[-1].strip() == "":
            body_lines.pop()
        sections[key] = "\n".join(body_lines).strip()
    return sections


def _count_sentences(text: str) -> int:
    if not text:
        return 0
    t = text.strip()
    parts = re.split(r'[.!?]+(?:\s+|$)', t)
    parts = [p for p in parts if p and re.search(r'[A-Za-z0-9]', p)]
    return len(parts)


def _contains_url(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r'https?://|www\.', text))


def _compute_catalog_stats(rows: List[Dict[str, str]]) -> Dict[str, object]:
    inst_counts: Dict[str, int] = {}
    theme_counts: Dict[str, int] = {}
    years: List[int] = []
    for r in rows:
        inst = (r.get("institution") or "").strip()
        theme = (r.get("theme") or "").strip()
        year_str = (r.get("year") or "").strip()
        if inst:
            inst_counts[inst] = inst_counts.get(inst, 0) + 1
        if theme:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
        if year_str.isdigit() and len(year_str) == 4:
            years.append(int(year_str))
    stats = {
        "total_entries": len(rows),
        "counts_per_institution": inst_counts,
        "counts_per_theme": theme_counts,
        "min_year": min(years) if years else None,
        "max_year": max(years) if years else None,
    }
    return stats


def _load_search_queries(path: Path) -> Optional[List[str]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "catalog_file_exists_and_header": 0.0,
        "catalog_minimum_entries_met": 0.0,
        "catalog_institutions_coverage_met": 0.0,
        "catalog_themes_coverage_met": 0.0,
        "catalog_ids_unique": 0.0,
        "catalog_years_in_range": 0.0,
        "catalog_rights_status_allowed": 0.0,
        "catalog_themes_allowed_values": 0.0,
        "catalog_institutions_in_allowed_list": 0.0,
        "catalog_aesthetic_note_sentence_count": 0.0,
        "no_urls_in_outputs": 0.0,
        "search_queries_file_exists_and_count": 0.0,
        "search_queries_unique": 0.0,
        "research_summary_sections_present": 0.0,
        "research_summary_scope_mentions_period": 0.0,
        "research_summary_institutions_counts_match_catalog": 0.0,
        "research_summary_search_queries_listed": 0.0,
        "research_summary_highlights_count_and_one_sentence_each": 0.0,
        "validate_script_exists_and_contains_expected_paths": 0.0,
        "stats_json_exists_and_matches_catalog": 0.0,
        "validation_txt_exists_and_contains_checks": 0.0,
    }

    # Load inputs
    institutions_path = workspace / "input" / "institutions.txt"
    themes_path = workspace / "input" / "themes.json"
    institutions_list = _load_institutions_list(institutions_path)
    themes_cfg = _read_json_safe(themes_path)

    # Prepare expected values from themes_cfg
    expected_header = [
        "id",
        "title",
        "year",
        "creator",
        "institution",
        "collection",
        "rights_status",
        "theme",
        "aesthetic_note",
    ]
    period_start = None
    period_end = None
    allowed_themes: List[str] = []
    allowed_rights: List[str] = []
    min_entries = None
    min_institutions = None
    min_themes = None

    if isinstance(themes_cfg, dict):
        period_start = themes_cfg.get("period_start")
        period_end = themes_cfg.get("period_end")
        allowed_themes = themes_cfg.get("themes") or []
        allowed_rights = themes_cfg.get("allowed_rights") or []
        min_entries = themes_cfg.get("min_entries")
        min_institutions = themes_cfg.get("min_institutions")
        min_themes = themes_cfg.get("min_themes")

    # Parse catalog
    catalog_path = workspace / "data" / "catalog.csv"
    rows = _parse_csv_strict(catalog_path, expected_header) if catalog_path.exists() else None

    if rows is not None:
        scores["catalog_file_exists_and_header"] = 1.0

        # Minimum entries
        if isinstance(min_entries, int) and len(rows) >= min_entries:
            scores["catalog_minimum_entries_met"] = 1.0

        # Unique IDs
        ids = [(r.get("id") or "").strip() for r in rows]
        if all(i != "" for i in ids) and len(set(ids)) == len(ids):
            scores["catalog_ids_unique"] = 1.0

        # Years within range
        years_ok = True
        if isinstance(period_start, int) and isinstance(period_end, int):
            for r in rows:
                y_str = (r.get("year") or "").strip()
                if not (y_str.isdigit() and len(y_str) == 4):
                    years_ok = False
                    break
                y_int = int(y_str)
                if not (period_start <= y_int <= period_end):
                    years_ok = False
                    break
            if years_ok:
                scores["catalog_years_in_range"] = 1.0

        # Rights status allowed
        rights_ok = True
        if allowed_rights:
            for r in rows:
                rs = (r.get("rights_status") or "").strip()
                if rs not in allowed_rights:
                    rights_ok = False
                    break
            if rights_ok:
                scores["catalog_rights_status_allowed"] = 1.0

        # Themes allowed
        themes_ok = True
        if allowed_themes:
            for r in rows:
                th = (r.get("theme") or "").strip()
                if th not in allowed_themes:
                    themes_ok = False
                    break
            if themes_ok:
                scores["catalog_themes_allowed_values"] = 1.0

        # Institutions in allowed list
        insts_ok = True
        if institutions_list:
            for r in rows:
                inst = (r.get("institution") or "").strip()
                if inst not in institutions_list:
                    insts_ok = False
                    break
            if insts_ok:
                scores["catalog_institutions_in_allowed_list"] = 1.0

        # Institutions/theme coverage
        unique_insts = set((r.get("institution") or "").strip() for r in rows if (r.get("institution") or "").strip())
        unique_themes = set((r.get("theme") or "").strip() for r in rows if (r.get("theme") or "").strip())
        if isinstance(min_institutions, int) and len(unique_insts) >= min_institutions:
            scores["catalog_institutions_coverage_met"] = 1.0
        if isinstance(min_themes, int) and len(unique_themes) >= min_themes:
            scores["catalog_themes_coverage_met"] = 1.0

        # Aesthetic note sentence count 1–2 per row
        an_ok = True
        for r in rows:
            note = (r.get("aesthetic_note") or "").strip()
            scount = _count_sentences(note)
            if scount < 1 or scount > 2:
                an_ok = False
                break
        if an_ok:
            scores["catalog_aesthetic_note_sentence_count"] = 1.0

    # Search queries log checks
    queries_path = workspace / "logs" / "search_queries.txt"
    queries = _load_search_queries(queries_path) if queries_path.exists() else None
    if queries is not None:
        if len(queries) >= 5:
            scores["search_queries_file_exists_and_count"] = 1.0
        # Distinct queries
        norm = [q.strip() for q in queries if q.strip()]
        if len(set(norm)) >= 5 and len(set(norm)) == len(norm):
            scores["search_queries_unique"] = 1.0

    # Research summary markdown checks
    summary_path = workspace / "reports" / "research_summary.md"
    summary_text = _read_text_safe(summary_path) if summary_path.exists() else None
    required_sections = ["Scope", "Institutions covered", "Search strategy", "Highlights"]
    sections: Dict[str, str] = {}
    if summary_text is not None:
        sections = _extract_markdown_sections(summary_text, required_sections)
        if all(name.lower() in sections for name in [s.lower() for s in required_sections]):
            scores["research_summary_sections_present"] = 1.0

        # Scope mentions period (either period_start and period_end numbers or period label)
        if themes_cfg and isinstance(themes_cfg, dict):
            scope_text = sections.get("scope", "")
            period_ok = False
            if isinstance(period_start, int) and isinstance(period_end, int):
                if str(period_start) in scope_text and str(period_end) in scope_text:
                    period_ok = True
            if not period_ok:
                label = themes_cfg.get("period_label") or ""
                if label and label.lower() in scope_text.lower():
                    period_ok = True
            if period_ok:
                scores["research_summary_scope_mentions_period"] = 1.0

        # Institutions covered list each with count of entries (match catalog)
        if rows is not None:
            inst_counts = _compute_catalog_stats(rows)["counts_per_institution"]
            inst_section = sections.get("institutions covered", "")
            inst_lines = [ln for ln in inst_section.splitlines() if ln.strip()]
            all_match = True
            for inst, cnt in inst_counts.items():
                found = False
                for ln in inst_lines:
                    if inst in ln:
                        nums = re.findall(r'\d+', ln)
                        if nums:
                            try:
                                num = int(nums[0])
                                if num == cnt:
                                    found = True
                                    break
                            except Exception:
                                pass
                if not found:
                    all_match = False
                    break
            if all_match and inst_counts:
                scores["research_summary_institutions_counts_match_catalog"] = 1.0

        # Search strategy includes queries from the log
        if queries is not None:
            search_section = sections.get("search strategy", "")
            has_all = True
            for q in queries:
                if q not in search_section:
                    has_all = False
                    break
            if has_all and queries:
                scores["research_summary_search_queries_listed"] = 1.0

        # Highlights 3–5 items with one-sentence notes
        highlights_section = sections.get("highlights", "")
        if highlights_section:
            hl_lines = [ln.strip() for ln in highlights_section.splitlines() if ln.strip()]
            items = list(hl_lines)
            count_ok = 3 <= len(items) <= 5
            sentence_ok = True
            for it in items:
                sc = _count_sentences(it)
                if sc != 1:
                    sentence_ok = False
                    break
            if count_ok and sentence_ok:
                scores["research_summary_highlights_count_and_one_sentence_each"] = 1.0

    # Validate script existence and minimal structure
    validate_script_path = workspace / "scripts" / "validate_catalog.py"
    validate_script_text = _read_text_safe(validate_script_path) if validate_script_path.exists() else None
    if validate_script_text is not None:
        expected_refs = [
            "input/institutions.txt",
            "input/themes.json",
            "data/catalog.csv",
            "reports/stats.json",
            "reports/validation.txt",
        ]
        refs_ok = all(ref in validate_script_text for ref in expected_refs)
        has_main_guard = "if __name__" in validate_script_text
        if refs_ok and has_main_guard:
            scores["validate_script_exists_and_contains_expected_paths"] = 1.0

    # stats.json exists and matches catalog
    stats_path = workspace / "reports" / "stats.json"
    stats_json = _read_json_safe(stats_path) if stats_path.exists() else None
    if stats_json is not None and rows is not None:
        computed = _compute_catalog_stats(rows)
        try:
            total_ok = stats_json.get("total_entries") == computed["total_entries"]
            inst_ok = stats_json.get("counts_per_institution") == computed["counts_per_institution"]
            theme_ok = stats_json.get("counts_per_theme") == computed["counts_per_theme"]
            min_ok = stats_json.get("min_year") == computed["min_year"]
            max_ok = stats_json.get("max_year") == computed["max_year"]
            if total_ok and inst_ok and theme_ok and min_ok and max_ok:
                scores["stats_json_exists_and_matches_catalog"] = 1.0
        except Exception:
            pass

    # validation.txt exists and contains required checks summary
    validation_txt_path = workspace / "reports" / "validation.txt"
    validation_text = _read_text_safe(validation_txt_path) if validation_txt_path.exists() else None
    if validation_text is not None:
        vt = validation_text.lower()
        has_pass_fail = ("pass" in vt) or ("fail" in vt)
        contains_checks = all(k in vt for k in [
            "minimum entries",
            "institutions",
            "themes",
            "unique",
            "year",
            "rights",
        ])
        if has_pass_fail and contains_checks:
            scores["validation_txt_exists_and_contains_checks"] = 1.0

    # Check direct URLs not present in outputs (only if all deliverables exist)
    deliverable_paths = [
        catalog_path,
        queries_path,
        summary_path,
        stats_path,
        validation_txt_path,
    ]
    if all(p.exists() for p in deliverable_paths):
        no_urls = True
        for p in deliverable_paths:
            text = _read_text_safe(p)
            if text and _contains_url(text):
                no_urls = False
                break
        if no_urls:
            scores["no_urls_in_outputs"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()