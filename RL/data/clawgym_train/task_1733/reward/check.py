import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _normalize_title(title: str) -> str:
    return title.strip().casefold()


def _split_themes(theme_str: str) -> List[str]:
    parts = [p.strip() for p in theme_str.split(";")]
    return [p for p in parts if p != ""]


def _compute_expected_curated(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    books_path = workspace / "input" / "books_catalog.csv"
    recs_path = workspace / "input" / "recommendations_from_network.jsonl"
    allowed_path = workspace / "input" / "allowed_grade_bands.json"

    books = _read_csv_dicts(books_path)
    recs = _read_jsonl(recs_path)
    allowed = _read_json(allowed_path)
    if books is None or recs is None or allowed is None:
        return None

    # Build catalog map by normalized title
    catalog_map: Dict[str, Dict[str, Any]] = {}
    for b in books:
        title = b.get("title", "")
        author = b.get("author", "")
        grade_band = b.get("grade_band", "")
        theme_tags = b.get("theme_tags", "")
        pages_str = b.get("pages", "").strip()
        try:
            pages = int(pages_str)
        except Exception:
            return None
        catalog_map[_normalize_title(title)] = {
            "title": title,
            "author": author,
            "grade_band": grade_band,
            "themes": _split_themes(theme_tags),
            "pages": pages,
        }

    allowed_list = allowed.get("allowed")
    if not isinstance(allowed_list, list):
        return None
    allowed_order = {band: idx for idx, band in enumerate(allowed_list)}

    # Match recommendations
    curated: List[Dict[str, Any]] = []
    for rec in recs:
        rec_title = rec.get("title", "")
        reason = rec.get("reason", "")
        if not isinstance(rec_title, str) or not isinstance(reason, str):
            continue
        norm = _normalize_title(rec_title)
        if norm in catalog_map:
            book = catalog_map[norm]
            curated.append({
                "title": book["title"],
                "author": book["author"],
                "grade_band": book["grade_band"],
                "themes": book["themes"],
                "pages": book["pages"],
                "recommendation_reason": reason,
                "source": "network_pro",
            })

    # Sort by grade_band (allowed order) then by title A–Z (case-insensitive)
    def sort_key(item: Dict[str, Any]) -> Tuple[int, str]:
        gb = item["grade_band"]
        gb_idx = allowed_order.get(gb, 10**6)
        return (gb_idx, item["title"].casefold())

    curated.sort(key=sort_key)
    return curated


def _compute_expected_stats(curated: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(curated)
    by_grade: Dict[str, int] = {}
    pages_list: List[int] = []
    theme_counts: Dict[str, int] = {}

    for item in curated:
        gb = item["grade_band"]
        by_grade[gb] = by_grade.get(gb, 0) + 1
        pages_list.append(int(item["pages"]))
        for t in item["themes"]:
            theme_counts[t] = theme_counts.get(t, 0) + 1

    # top themes: top 5, count desc, then alphabetically (case-insensitive) for tie
    sorted_themes = sorted(theme_counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))
    top_themes = [{"theme": t, "count": c} for t, c in sorted_themes[:5]]

    # mean and median
    if total == 0:
        pages_mean = 0.0
        pages_median = 0.0
    else:
        pages_mean = sum(pages_list) / total
        pages_list_sorted = sorted(pages_list)
        mid = total // 2
        if total % 2 == 1:
            pages_median = float(pages_list_sorted[mid])
        else:
            pages_median = (pages_list_sorted[mid - 1] + pages_list_sorted[mid]) / 2.0

    return {
        "total": total,
        "by_grade_band": by_grade,
        "top_themes": top_themes,
        "pages_mean": pages_mean,
        "pages_median": pages_median,
    }


def _approx_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _extract_marked_section(text: str, begin_marker: str, end_marker: str) -> Optional[Tuple[str, str, str]]:
    start_idx = text.find(begin_marker)
    end_idx = text.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return None
    pre = text[: start_idx + len(begin_marker)]
    between = text[start_idx + len(begin_marker): end_idx]
    post = text[end_idx:]
    return pre, between, post


def _sentence_count(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    segments = re.split(r'(?<=[.!?])\s+', stripped)
    segments = [s for s in segments if s.strip()]
    return len(segments)


def _build_expected_bullet(item: Dict[str, Any]) -> str:
    # Format: "- Title — Author (Grade band) — Themes: theme1, theme2, ..."
    title = item["title"]
    author = item["author"]
    grade_band = item["grade_band"]
    themes = item["themes"]
    themes_str = ", ".join(themes)
    return f"- {title} — {author} ({grade_band}) — Themes: {themes_str}"


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "curated_file_valid_json": 0.0,
        "curated_schema_fields": 0.0,
        "curated_content_and_sorting": 0.0,
        "stats_file_valid_json": 0.0,
        "stats_values_correct": 0.0,
        "syllabus_markers_preserved": 0.0,
        "syllabus_paragraph_and_bullets": 0.0,
        "validation_script_present": 0.0,
        "validation_report_all_checks_pass": 0.0,
    }

    # Paths
    curated_path = workspace / "output" / "recommendations_curated.json"
    stats_path = workspace / "output" / "recommendation_stats.json"
    syllabus_input_path = workspace / "input" / "syllabus.md"
    syllabus_output_path = workspace / "output" / "syllabus_updated.md"
    validation_report_path = workspace / "output" / "validation_report.txt"

    # Load curated
    curated_data = _read_json(curated_path)
    if isinstance(curated_data, list):
        scores["curated_file_valid_json"] = 1.0

    # Schema check for curated
    required_keys = {"title", "author", "grade_band", "themes", "pages", "recommendation_reason", "source"}
    schema_ok = True
    if isinstance(curated_data, list):
        for obj in curated_data:
            if not isinstance(obj, dict):
                schema_ok = False
                break
            if set(obj.keys()) != required_keys:
                schema_ok = False
                break
            if not isinstance(obj.get("title"), str):
                schema_ok = False
                break
            if not isinstance(obj.get("author"), str):
                schema_ok = False
                break
            if not isinstance(obj.get("grade_band"), str):
                schema_ok = False
                break
            if not isinstance(obj.get("themes"), list) or not all(isinstance(t, str) for t in obj.get("themes")):
                schema_ok = False
                break
            if not isinstance(obj.get("pages"), int):
                schema_ok = False
                break
            if not isinstance(obj.get("recommendation_reason"), str):
                schema_ok = False
                break
            if obj.get("source") != "network_pro":
                schema_ok = False
                break
    else:
        schema_ok = False
    if schema_ok:
        scores["curated_schema_fields"] = 1.0

    # Compute expected curated and compare
    expected_curated = _compute_expected_curated(workspace)
    curated_match = False
    if expected_curated is not None and isinstance(curated_data, list):
        # Strict comparison: same order and items
        curated_match = curated_data == expected_curated
    if curated_match:
        scores["curated_content_and_sorting"] = 1.0

    # Stats file existence and parse
    stats_data = _read_json(stats_path)
    stats_parse_ok = False
    if isinstance(stats_data, dict):
        # Basic structure validation
        base_fields = {"total", "by_grade_band", "top_themes", "pages_mean", "pages_median"}
        if base_fields.issubset(stats_data.keys()):
            total_ok = isinstance(stats_data.get("total"), int)
            by_grade_ok = isinstance(stats_data.get("by_grade_band"), dict) and all(
                isinstance(k, str) and isinstance(v, int) for k, v in stats_data.get("by_grade_band").items()
            )
            top_themes_ok = isinstance(stats_data.get("top_themes"), list) and all(
                isinstance(x, dict) and set(x.keys()) == {"theme", "count"} and isinstance(x.get("theme"), str) and isinstance(x.get("count"), int)
                for x in stats_data.get("top_themes")
            )
            mean_ok = isinstance(stats_data.get("pages_mean"), (int, float))
            median_ok = isinstance(stats_data.get("pages_median"), (int, float))
            stats_parse_ok = total_ok and by_grade_ok and top_themes_ok and mean_ok and median_ok
    if stats_parse_ok:
        scores["stats_file_valid_json"] = 1.0

    # Stats values correctness
    stats_correct = False
    if expected_curated is not None and isinstance(stats_data, dict) and stats_parse_ok:
        expected_stats = _compute_expected_stats(expected_curated)
        # Compare totals and by_grade_band exact
        by_grade_equal = stats_data.get("by_grade_band") == expected_stats.get("by_grade_band")
        top_themes_equal = stats_data.get("top_themes") == expected_stats.get("top_themes")
        totals_equal = stats_data.get("total") == expected_stats.get("total")
        mean_equal = _approx_equal(float(stats_data.get("pages_mean")), float(expected_stats.get("pages_mean")))
        median_equal = _approx_equal(float(stats_data.get("pages_median")), float(expected_stats.get("pages_median")))
        stats_correct = by_grade_equal and top_themes_equal and totals_equal and mean_equal and median_equal
    if stats_correct:
        scores["stats_values_correct"] = 1.0

    # Syllabus markers preserved and only section replaced
    syllabus_in_text = _read_text(syllabus_input_path)
    syllabus_out_text = _read_text(syllabus_output_path)
    markers_ok = False
    if syllabus_in_text is not None and syllabus_out_text is not None:
        begin_marker = "<!-- BEGIN:RECOMMENDATIONS -->"
        end_marker = "<!-- END:RECOMMENDATIONS -->"
        extracted_in = _extract_marked_section(syllabus_in_text, begin_marker, end_marker)
        extracted_out = _extract_marked_section(syllabus_out_text, begin_marker, end_marker)
        if extracted_in and extracted_out:
            pre_in, between_in, post_in = extracted_in
            pre_out, between_out, post_out = extracted_out
            # Outside content equality
            if pre_in == pre_out and post_in == post_out:
                # Ensure placeholder removed
                if "(placeholder)" not in between_out:
                    markers_ok = True
    if markers_ok:
        scores["syllabus_markers_preserved"] = 1.0

    # Syllabus content: paragraph and bullets
    syllabus_content_ok = False
    if expected_curated is not None and syllabus_out_text is not None:
        begin_marker = "<!-- BEGIN:RECOMMENDATIONS -->"
        end_marker = "<!-- END:RECOMMENDATIONS -->"
        extracted_out = _extract_marked_section(syllabus_out_text, begin_marker, end_marker)
        if extracted_out:
            _, between_out, _ = extracted_out
            # Normalize lines inside section
            inner = between_out.strip("\n")
            lines = [ln.rstrip() for ln in inner.splitlines()]
            # Determine paragraph (before first bullet starting with "- ")
            para_lines: List[str] = []
            bullet_lines: List[str] = []
            in_bullets = False
            for ln in lines:
                if ln.strip().startswith("- "):
                    in_bullets = True
                    bullet_lines.append(ln.strip())
                else:
                    if not in_bullets:
                        para_lines.append(ln)
                    else:
                        if ln.strip() == "":
                            continue
                        bullet_lines.append(ln.strip())

            # Clean paragraph lines: remove leading/trailing empty lines
            while para_lines and not para_lines[0].strip():
                para_lines.pop(0)
            while para_lines and not para_lines[-1].strip():
                para_lines.pop()
            paragraph_text = " ".join([pl.strip() for pl in para_lines if pl.strip() != ""]).strip()

            # Check paragraph sentence count 3-5
            sent_count = _sentence_count(paragraph_text)
            para_ok = 3 <= sent_count <= 5 and len(paragraph_text) > 0

            # Check paragraph mentions: all top theme names and all grade bands present
            expected_stats = _compute_expected_stats(expected_curated)
            top_theme_names = [tt["theme"] for tt in expected_stats["top_themes"]]
            bands = list(expected_stats["by_grade_band"].keys())
            paragraph_lower = paragraph_text.casefold()
            themes_mentioned = all(t.casefold() in paragraph_lower for t in top_theme_names) or (len(top_theme_names) == 0)
            bands_mentioned = all(b.casefold() in paragraph_lower for b in bands) or (len(bands) == 0)

            # Build expected bullets set
            expected_bullets = set(_build_expected_bullet(item) for item in expected_curated)
            # Collect provided bullets set (strip trailing spaces)
            provided_bullets = set([bl.strip() for bl in bullet_lines if bl.strip()])

            bullets_ok = (len(provided_bullets) == len(expected_bullets)) and (provided_bullets == expected_bullets)

            syllabus_content_ok = para_ok and themes_mentioned and bands_mentioned and bullets_ok

    if syllabus_content_ok:
        scores["syllabus_paragraph_and_bullets"] = 1.0

    # Validation script presence (scripts/validate, scripts/validate.py, scripts/validate.js)
    validate_candidates = [
        workspace / "scripts" / "validate",
        workspace / "scripts" / "validate.py",
        workspace / "scripts" / "validate.js",
    ]
    script_present = any(p.exists() and p.is_file() for p in validate_candidates)
    if script_present:
        scores["validation_script_present"] = 1.0

    # Validation report check: PASS for all four checks and no FAIL
    report_text = _read_text(validation_report_path)
    if report_text is not None:
        lines = report_text.splitlines()
        # Ensure no FAIL present
        any_fail = any("FAIL" in ln for ln in lines)
        # Check labeled passes
        def has_pass(label: str) -> bool:
            return any((label in ln) and ("PASS" in ln) for ln in lines)

        schema_pass = has_pass("Schema check")
        crossref_pass = has_pass("Cross-reference")
        count_pass = has_pass("Count consistency")
        syllabus_link_pass = has_pass("Syllabus linkage")
        if (not any_fail) and schema_pass and crossref_pass and count_pass and syllabus_link_pass:
            scores["validation_report_all_checks_pass"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()