import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(row) for row in reader]
            return headers, rows
    except Exception:
        return None, None


def _to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        s = str(val).strip()
        if s == "" or s.lower() == "nan":
            return None
        return float(s)
    except Exception:
        return None


def _to_int(val: Any) -> Optional[int]:
    f = _to_float(val)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None


def _almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _near_equal(a: float, b: float, abs_tol: float = 0.05) -> bool:
    return abs(a - b) <= abs_tol


def _normalize_type(t: str) -> str:
    return str(t).strip().lower()


def _load_canonical_mapping(workspace: Path) -> Optional[Dict[str, str]]:
    headers, rows = _safe_read_csv(workspace / "input" / "period_map.csv")
    if headers is None or rows is None:
        return None
    mapping = {}
    for r in rows:
        sp = (r.get("source_period") or "").strip()
        cp = (r.get("canonical_period") or "").strip()
        if sp:
            mapping[sp] = cp if cp else sp
    return mapping


def _load_artworks_with_canonical(workspace: Path, mapping: Dict[str, str]) -> Optional[List[Dict[str, Any]]]:
    headers, rows = _safe_read_csv(workspace / "input" / "artworks.csv")
    if headers is None or rows is None:
        return None
    out = []
    for r in rows:
        src_period = (r.get("period") or "").strip()
        canon = mapping.get(src_period, src_period)
        rec = dict(r)
        rec["canonical_period"] = canon
        out.append(rec)
    return out


def _compute_metrics(artworks: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    periods = set([a["canonical_period"] for a in artworks])
    metrics = {}
    types_2d = {"painting", "print", "drawing"}

    for p in periods:
        metrics[p] = {
            "total_works_all_types": 0,
            "two_d_on_display_count": 0,
            "two_d_on_display_total_area_cm2": 0.0,
            "two_d_on_display_avg_area_cm2": 0.0,
        }

    for a in artworks:
        p = a["canonical_period"]
        metrics[p]["total_works_all_types"] += 1
        a_type = _normalize_type(a.get("type", ""))
        on_display = (a.get("on_display") or "").strip().upper() == "Y"
        if a_type in types_2d and on_display:
            h = _to_float(a.get("height_cm"))
            w = _to_float(a.get("width_cm"))
            # If dimensions missing, treat as invalid for area (skip contribution)
            if h is not None and w is not None:
                area = h * w
                metrics[p]["two_d_on_display_count"] += 1
                metrics[p]["two_d_on_display_total_area_cm2"] += area

    for p, m in metrics.items():
        cnt = m["two_d_on_display_count"]
        tot = m["two_d_on_display_total_area_cm2"]
        m["two_d_on_display_avg_area_cm2"] = (tot / cnt) if cnt > 0 else 0.0

    return metrics


def _expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    mapping = _load_canonical_mapping(workspace)
    if mapping is None:
        return None
    artworks = _load_artworks_with_canonical(workspace, mapping)
    if artworks is None:
        return None
    metrics = _compute_metrics(artworks)
    # Large 2D on display works >= 15000 cm2
    types_2d = {"painting", "print", "drawing"}
    large = []
    for a in artworks:
        a_type = _normalize_type(a.get("type", ""))
        if a_type in types_2d and (a.get("on_display") or "").strip().upper() == "Y":
            h = _to_float(a.get("height_cm"))
            w = _to_float(a.get("width_cm"))
            if h is None or w is None:
                continue
            area = h * w
            if area >= 15000:
                large.append({
                    "id": a.get("id"),
                    "title": a.get("title"),
                    "artist": a.get("artist"),
                    "canonical_period": a.get("canonical_period"),
                    "type": a.get("type"),
                    "year": a.get("year"),
                    "area_cm2": area
                })
    # Sort large by area desc then id
    large_sorted = sorted(large, key=lambda x: (-x["area_cm2"], x["id"]))
    return {
        "metrics": metrics,
        "large": large_sorted,
        "artworks": artworks
    }


def _read_period_metrics_csv(path: Path) -> Tuple[bool, Optional[List[Dict[str, str]]], Optional[List[str]]]:
    headers, rows = _safe_read_csv(path)
    if headers is None or rows is None:
        return False, None, None
    return True, rows, headers


def _read_large_two_d_csv(path: Path) -> Tuple[bool, Optional[List[Dict[str, str]]], Optional[List[str]]]:
    headers, rows = _safe_read_csv(path)
    if headers is None or rows is None:
        return False, None, None
    return True, rows, headers


def _parse_float_field(row: Dict[str, str], key: str) -> Optional[float]:
    return _to_float(row.get(key))


def _parse_int_field(row: Dict[str, str], key: str) -> Optional[int]:
    return _to_int(row.get(key))


def _find_numbers_in_text(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r'(?<![\w.])(-?\d+(?:\.\d+)?)', text):
        try:
            nums.append(float(m.group(1)))
        except Exception:
            pass
    return nums


def _line_contains_unit(text: str) -> bool:
    t = text.lower()
    return ("m^2" in t) or ("m²" in t) or (" m2" in t) or ("square meter" in t) or ("sq m" in t) or ("sqm" in t)


def _near_value_present_near_anchor(lines: List[str], anchor: str, expected: float, abs_tol: float = 0.05, window: int = 1) -> bool:
    # Search for expected number near the anchor line (same line or +/- window lines)
    indices = [i for i, ln in enumerate(lines) if anchor in ln]
    for idx in indices:
        start = max(0, idx - window)
        end = min(len(lines), idx + window + 1)
        for j in range(start, end):
            ln = lines[j]
            nums = _find_numbers_in_text(ln)
            if _line_contains_unit(ln):
                for n in nums:
                    if _near_equal(n, expected, abs_tol=abs_tol):
                        return True
    return False


def _number_present_near_anchor(lines: List[str], anchor: str, expected: float, window: int = 1, tol: float = 1e-6) -> bool:
    indices = [i for i, ln in enumerate(lines) if anchor in ln]
    for idx in indices:
        start = max(0, idx - window)
        end = min(len(lines), idx + window + 1)
        for j in range(start, end):
            ln = lines[j]
            nums = _find_numbers_in_text(ln)
            for n in nums:
                if _almost_equal(n, expected, tol=tol):
                    return True
    return False


def _id_block_has_title_period_and_area(lines: List[str], the_id: str, title: str, period: str, expected_area_m2: float, search_radius_chars: int = 150) -> bool:
    # Join text and search around ID occurrence
    full_text = "\n".join(lines)
    for m in re.finditer(re.escape(the_id), full_text):
        start = max(0, m.start() - search_radius_chars)
        end = min(len(full_text), m.end() + search_radius_chars)
        snippet = full_text[start:end]
        has_title = title in snippet
        has_period = period in snippet
        # area with units
        has_area = False
        if _line_contains_unit(snippet):
            nums = _find_numbers_in_text(snippet)
            for n in nums:
                if _near_equal(n, expected_area_m2, abs_tol=0.05):
                    has_area = True
                    break
        if has_title and has_period and has_area:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "period_metrics_file_exists": 0.0,
        "period_metrics_columns_correct": 0.0,
        "period_metrics_period_rows_complete": 0.0,
        "period_metrics_total_works_correct": 0.0,
        "period_metrics_two_d_on_display_counts_correct": 0.0,
        "period_metrics_two_d_on_display_total_area_correct": 0.0,
        "period_metrics_two_d_on_display_avg_area_correct": 0.0,
        "large_two_d_works_file_exists": 0.0,
        "large_two_d_works_columns_correct": 0.0,
        "large_two_d_works_ids_correct": 0.0,
        "large_two_d_works_areas_correct": 0.0,
        "tests_log_exists": 0.0,
        "tests_log_includes_required_checks": 0.0,
        "tests_log_pass_indicator_present": 0.0,
        "meeting_notes_exists": 0.0,
        "notes_period_counts_and_avg_present_correct": 0.0,
        "notes_wall_area_per_period_present_correct": 0.0,
        "notes_two_largest_listed_correct": 0.0,
        "notes_action_items_present": 0.0,
    }

    # Load expected (derived) metrics from inputs
    derived = _expected_from_inputs(workspace)

    # Validate period_metrics.csv
    period_metrics_path = workspace / "output" / "period_metrics.csv"
    ok, pm_rows, pm_headers = _read_period_metrics_csv(period_metrics_path)
    if ok and pm_rows is not None and pm_headers is not None:
        scores["period_metrics_file_exists"] = 1.0
        expected_headers = [
            "period",
            "total_works_all_types",
            "two_d_on_display_count",
            "two_d_on_display_total_area_cm2",
            "two_d_on_display_avg_area_cm2",
        ]
        if pm_headers == expected_headers:
            scores["period_metrics_columns_correct"] = 1.0

        if derived is not None:
            metrics = derived["metrics"]
            expected_periods = set(["Renaissance", "Baroque", "Modern"])
            file_periods = [r.get("period", "") for r in pm_rows]
            if set(file_periods) == expected_periods and len(pm_rows) == 3:
                scores["period_metrics_period_rows_complete"] = 1.0

            # Build dict from file rows
            pm_by_period = {r.get("period", ""): r for r in pm_rows}

            # total_works_all_types
            totals_match = True
            counts_match = True
            sums_match = True
            avgs_match = True
            for p in expected_periods:
                r = pm_by_period.get(p)
                m = metrics.get(p)
                if r is None or m is None:
                    totals_match = counts_match = sums_match = avgs_match = False
                    break
                # Totals
                v = _parse_int_field(r, "total_works_all_types")
                if v is None or v != int(m["total_works_all_types"]):
                    totals_match = False
                # 2D count
                v2 = _parse_int_field(r, "two_d_on_display_count")
                if v2 is None or v2 != int(m["two_d_on_display_count"]):
                    counts_match = False
                # Sum area
                v3 = _parse_float_field(r, "two_d_on_display_total_area_cm2")
                if v3 is None or not _almost_equal(v3, float(m["two_d_on_display_total_area_cm2"])):
                    sums_match = False
                # Avg area
                v4 = _parse_float_field(r, "two_d_on_display_avg_area_cm2")
                if v4 is None or not _almost_equal(v4, float(m["two_d_on_display_avg_area_cm2"])):
                    avgs_match = False

            if totals_match:
                scores["period_metrics_total_works_correct"] = 1.0
            if counts_match:
                scores["period_metrics_two_d_on_display_counts_correct"] = 1.0
            if sums_match:
                scores["period_metrics_two_d_on_display_total_area_correct"] = 1.0
            if avgs_match:
                scores["period_metrics_two_d_on_display_avg_area_correct"] = 1.0

    # Validate large_two_d_works.csv
    large_path = workspace / "output" / "large_two_d_works.csv"
    ok, large_rows, large_headers = _read_large_two_d_csv(large_path)
    if ok and large_rows is not None and large_headers is not None:
        scores["large_two_d_works_file_exists"] = 1.0
        expected_headers = ["id", "title", "artist", "canonical_period", "type", "year", "area_cm2"]
        if large_headers == expected_headers:
            scores["large_two_d_works_columns_correct"] = 1.0

        if derived is not None:
            expected_large_ids = set([d["id"] for d in derived["large"]])
            file_ids = set([r.get("id") for r in large_rows])
            if file_ids == expected_large_ids:
                scores["large_two_d_works_ids_correct"] = 1.0

            # Validate each row's area matches recomputation and canonical period matches mapping
            mapping = _load_canonical_mapping(workspace) or {}
            artworks_list = derived["artworks"]
            by_id = {a.get("id"): a for a in artworks_list}
            areas_ok = True
            for r in large_rows:
                rid = r.get("id")
                a = by_id.get(rid)
                if a is None:
                    areas_ok = False
                    break
                # Check 2D and on_display
                a_type_norm = _normalize_type(a.get("type", ""))
                if a_type_norm not in {"painting", "print", "drawing"} or (a.get("on_display") or "").strip().upper() != "Y":
                    areas_ok = False
                    break
                h = _to_float(a.get("height_cm"))
                w = _to_float(a.get("width_cm"))
                if h is None or w is None:
                    areas_ok = False
                    break
                comp_area = h * w
                file_area = _to_float(r.get("area_cm2"))
                if file_area is None or not _almost_equal(file_area, comp_area):
                    areas_ok = False
                    break
                # canonical period
                if (r.get("canonical_period") or "").strip() != (a.get("canonical_period") or "").strip():
                    areas_ok = False
                    break
            if areas_ok:
                scores["large_two_d_works_areas_correct"] = 1.0

    # Validate tests/test_results.txt
    tests_log_path = workspace / "tests" / "test_results.txt"
    log_text = _safe_read_text(tests_log_path)
    if log_text is not None:
        scores["tests_log_exists"] = 1.0
        # presence of required checks
        required_tokens = [
            "period_counts_all",
            "two_d_on_display_counts",
            "two_d_on_display_total_area_cm2",
            "large_two_d_on_display_ids_above_15000",
        ]
        has_all = all(tok in log_text for tok in required_tokens)
        if has_all:
            scores["tests_log_includes_required_checks"] = 1.0
        # pass indicator must be last non-empty line and equal to "ALL CHECKS PASSED"
        lines = [ln.rstrip("\n\r") for ln in log_text.splitlines()]
        last_non_empty = ""
        for ln in reversed(lines):
            if ln.strip() != "":
                last_non_empty = ln.strip()
                break
        if last_non_empty.lower() == "all checks passed":
            scores["tests_log_pass_indicator_present"] = 1.0

    # Validate meeting notes
    notes_path = workspace / "output" / "meeting_notes.md"
    notes_text = _safe_read_text(notes_path)
    if notes_text is not None:
        scores["meeting_notes_exists"] = 1.0
        lines = notes_text.splitlines()

        if derived is not None:
            metrics = derived["metrics"]
            # Check per-period counts and avg present near period names
            counts_avgs_ok = True
            for period in ["Renaissance", "Baroque", "Modern"]:
                m = metrics.get(period)
                if not m:
                    counts_avgs_ok = False
                    break
                count_expected = int(m["total_works_all_types"])
                avg_expected = float(m["two_d_on_display_avg_area_cm2"])
                # Look near period anchor for count and avg (within same or adjacent lines)
                has_count = _number_present_near_anchor(lines, period, float(count_expected), window=1, tol=1e-6)
                has_avg = _number_present_near_anchor(lines, period, float(avg_expected), window=1, tol=1e-6)
                if not (has_count and has_avg):
                    counts_avgs_ok = False
                    break
            if counts_avgs_ok:
                scores["notes_period_counts_and_avg_present_correct"] = 1.0

            # Check wall area per period in square meters (convert total cm2 to m2)
            wall_ok = True
            for period in ["Renaissance", "Baroque", "Modern"]:
                m = metrics.get(period)
                tot_cm2 = float(m["two_d_on_display_total_area_cm2"])
                expected_m2 = tot_cm2 / 10000.0
                # Find near period anchor a number close to expected_m2 with unit markers
                if not _near_value_present_near_anchor(lines, period, expected_m2, abs_tol=0.05, window=1):
                    wall_ok = False
                    break
            if wall_ok:
                scores["notes_wall_area_per_period_present_correct"] = 1.0

            # Two largest 2D-on-display works by area with IDs, titles, canonical periods, and areas in m^2
            largest = derived["large"]
            largest_sorted = sorted(largest, key=lambda x: (-x["area_cm2"], x["id"]))
            top2 = largest_sorted[:2]
            two_largest_ok = True
            for item in top2:
                the_id = item["id"]
                title = item["title"]
                period = item["canonical_period"]
                expected_m2 = item["area_cm2"] / 10000.0
                if not _id_block_has_title_period_and_area(lines, the_id, title, period, expected_m2, search_radius_chars=150):
                    two_largest_ok = False
                    break
            if two_largest_ok:
                scores["notes_two_largest_listed_correct"] = 1.0

        # Action items: at least 3 bullet/numbered lines containing some numeric data
        bullet_pattern = re.compile(r'^\s*(?:[-*]\s+|\d+\.\s+)(.+)$')
        bullet_lines = []
        for ln in lines:
            m = bullet_pattern.match(ln)
            if m:
                content = m.group(1)
                if re.search(r'\d', content):  # data-driven: contains a number
                    bullet_lines.append(ln)
        if len(bullet_lines) >= 3:
            scores["notes_action_items_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()