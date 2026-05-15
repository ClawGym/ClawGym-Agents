import sys
import json
import csv
import math
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        lines = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        lines.append(obj)
                    else:
                        return None
                except Exception:
                    return None
        return lines
    except Exception:
        return None


def _normalize_key(city: str, state: str) -> Tuple[str, str]:
    return (city.strip().lower(), state.strip().lower())


def _parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s == "" or s.lower() == "na" or s.lower() == "null":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _parse_int(value: Any) -> Optional[int]:
    f = _parse_float(value)
    if f is None:
        return None
    try:
        return int(f)
    except Exception:
        return None


def _is_yyyy_mm_dd(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _is_domain(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if "http://" in s or "https://" in s or "/" in s:
        return False
    # Basic domain regex (doesn't cover all cases but enforces not URL)
    return re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", s) is not None


def _mean(xs: List[float]) -> Optional[float]:
    if not xs:
        return None
    return sum(xs) / len(xs)


def _median(xs: List[float]) -> Optional[float]:
    if not xs:
        return None
    xs_sorted = sorted(xs)
    n = len(xs_sorted)
    mid = n // 2
    if n % 2 == 1:
        return xs_sorted[mid]
    else:
        return (xs_sorted[mid - 1] + xs_sorted[mid]) / 2.0


def _std_population(xs: List[float]) -> Optional[float]:
    if not xs:
        return None
    n = len(xs)
    if n == 0:
        return None
    m = _mean(xs)
    if m is None:
        return None
    var = sum((x - m) ** 2 for x in xs) / n
    return math.sqrt(var)


def _std_sample(xs: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    m = _mean(xs)
    if m is None:
        return None
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var)


def _pearson(xs: List[float], ys: List[float], sample: bool = True) -> Optional[float]:
    n = len(xs)
    if n != len(ys) or n < 2:
        return None
    mx = _mean(xs)
    my = _mean(ys)
    if mx is None or my is None:
        return None
    cov_num = sum((xi - mx) ** 2 for xi in xs)
    if cov_num == 0:
        # If xs variance is zero, correlation undefined
        return None
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(xs, ys))
    if sample:
        denom_x = _std_sample(xs)
        denom_y = _std_sample(ys)
        if denom_x is None or denom_y is None or denom_x == 0 or denom_y == 0:
            return None
        return cov / ((len(xs) - 1) * denom_x * denom_y)
    else:
        denom_x = _std_population(xs)
        denom_y = _std_population(ys)
        if denom_x is None or denom_y is None or denom_x == 0 or denom_y == 0:
            return None
        return cov / (len(xs) * denom_x * denom_y)


def _float_close(a: Optional[float], b: Optional[float], tol: float = 1e-3) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _extract_markdown_table_headers(md: str) -> List[str]:
    headers = []
    for line in md.splitlines():
        if "|" in line:
            parts = [p.strip().lower() for p in line.strip().split("|")]
            if "city" in parts and "park_access_percent" in parts and "percent_adults_meeting_activity_guidelines" in parts:
                headers.append(line)
    return headers


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "parks_access_file_structure": 0.0,
        "parks_access_rows_coverage": 0.0,
        "parks_access_field_validity": 0.0,
        "search_log_coverage": 0.0,
        "search_log_alignment_with_data": 0.0,
        "summary_json_keys_present": 0.0,
        "summary_json_values_consistent": 0.0,
        "cities_excluded_consistent": 0.0,
        "report_summary_sections": 0.0,
        "report_summary_results_table_and_metrics": 0.0,
        "report_summary_sources_and_dates": 0.0,
        "design_md_content": 0.0,
    }

    # Load inputs
    input_csv_path = workspace / "input" / "cities_health.csv"
    input_rows = _read_csv_dicts(input_csv_path) or []
    input_ok = len(input_rows) > 0 and all("city" in r and "state" in r and "percent_adults_meeting_activity_guidelines" in r for r in input_rows)
    input_keys = set()
    input_map_activity: Dict[Tuple[str, str], float] = {}
    if input_ok:
        for r in input_rows:
            key = _normalize_key(r.get("city", ""), r.get("state", ""))
            input_keys.add(key)
            pa = _parse_float(r.get("percent_adults_meeting_activity_guidelines"))
            if pa is not None:
                input_map_activity[key] = pa

    # Paths
    parks_csv_path = workspace / "outputs" / "data" / "parks_access.csv"
    logs_path = workspace / "outputs" / "logs" / "search_log.jsonl"
    summary_json_path = workspace / "outputs" / "analysis" / "summary.json"
    report_summary_md_path = workspace / "outputs" / "report" / "summary.md"
    design_md_path = workspace / "outputs" / "report" / "design.md"

    # Check parks_access.csv structure
    parks_rows = _read_csv_dicts(parks_csv_path)
    expected_cols = ["city", "state", "park_access_percent", "source_org", "source_title", "source_domain", "retrieval_date"]
    if parks_rows is not None and isinstance(parks_rows, list):
        # Check header order strictly
        try:
            with parks_csv_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            actual_cols = [h.strip() for h in header_line.split(",")]
            header_ok = actual_cols == expected_cols
        except Exception:
            header_ok = False

        rows_ok = isinstance(parks_rows, list)
        if header_ok and rows_ok:
            scores["parks_access_file_structure"] = 1.0
        else:
            scores["parks_access_file_structure"] = 0.0
    else:
        scores["parks_access_file_structure"] = 0.0

    # Check coverage: all input cities present exactly once
    coverage_score = 0.0
    if input_ok and parks_rows:
        parks_keys = [_normalize_key(r.get("city", ""), r.get("state", "")) for r in parks_rows]
        unique_parks_keys = set(parks_keys)
        # Coverage: exact match of sets and no duplicates
        has_all = unique_parks_keys == input_keys
        no_duplicates = len(parks_keys) == len(unique_parks_keys)
        if has_all and no_duplicates:
            coverage_score = 1.0
        else:
            # Partial: proportion of input cities present at least once and penalize duplicates
            present = len(unique_parks_keys & input_keys)
            cover_ratio = present / len(input_keys) if input_keys else 0.0
            dup_penalty = 0.5 if not no_duplicates else 1.0
            coverage_score = max(0.0, cover_ratio * dup_penalty)
    scores["parks_access_rows_coverage"] = coverage_score

    # Field validity checks for parks_access.csv
    validity_score = 0.0
    if parks_rows:
        n = len(parks_rows)
        if n > 0:
            valid_numeric = True
            valid_dates = True
            valid_domains = True
            for r in parks_rows:
                # park_access_percent numeric or missing
                val = r.get("park_access_percent", "")
                if str(val).strip() != "":
                    if _parse_float(val) is None:
                        valid_numeric = False
                # retrieval_date format
                if not _is_yyyy_mm_dd(r.get("retrieval_date", "")):
                    valid_dates = False
                # source_domain format
                if not _is_domain(r.get("source_domain", "")):
                    valid_domains = False
            validity_score = 1.0 if (valid_numeric and valid_dates and valid_domains) else 0.0
    scores["parks_access_field_validity"] = validity_score

    # Load logs
    logs = _load_jsonl(logs_path)

    # Search log coverage: at least one log per input city
    log_cov_score = 0.0
    if input_ok and logs is not None:
        # Validate each log record has required fields
        required_log_fields = {"city", "state", "query", "engine", "timestamp", "chosen_source_title", "chosen_source_domain"}
        logs_valid = all(isinstance(l, dict) and required_log_fields.issubset(set(l.keys())) for l in logs)
        per_city_present = 0
        for key in input_keys:
            city, state = key
            found = any(_normalize_key(l.get("city", ""), l.get("state", "")) == key for l in logs)
            if found:
                per_city_present += 1
        ratio = per_city_present / len(input_keys) if input_keys else 0.0
        log_cov_score = ratio if logs_valid else 0.0
    scores["search_log_coverage"] = log_cov_score

    # Search log alignment with data sources (domain and title alignment per city)
    log_align_score = 0.0
    if parks_rows and logs is not None:
        # Build map from parks data
        parks_map: Dict[Tuple[str, str], Dict[str, str]] = {}
        for r in parks_rows:
            key = _normalize_key(r.get("city", ""), r.get("state", ""))
            parks_map[key] = {
                "source_domain": str(r.get("source_domain", "")).strip(),
                "source_title": str(r.get("source_title", "")).strip(),
            }
        align_hits = 0
        total = 0
        for key in input_keys:
            total += 1
            pdata = parks_map.get(key)
            if pdata is None:
                continue
            domain = pdata["source_domain"]
            title = pdata["source_title"]
            # any log entry for this city matching chosen_source_domain and chosen_source_title?
            match = any(
                _normalize_key(l.get("city", ""), l.get("state", "")) == key and
                str(l.get("chosen_source_domain", "")).strip() == domain and
                str(l.get("chosen_source_title", "")).strip() == title
                for l in logs
            )
            if match:
                align_hits += 1
        log_align_score = (align_hits / total) if total > 0 else 0.0
    scores["search_log_alignment_with_data"] = log_align_score

    # Load summary.json
    summary_obj = _load_json(summary_json_path)
    # Keys present check
    keys_ok = False
    if isinstance(summary_obj, dict):
        required_keys = {
            "n_cities_used",
            "park_access_percent_mean",
            "park_access_percent_median",
            "park_access_percent_std",
            "physical_activity_mean",
            "pearson_r_between_park_access_and_physical_activity",
            "cities_excluded",
        }
        keys_ok = required_keys.issubset(set(summary_obj.keys()))
    scores["summary_json_keys_present"] = 1.0 if keys_ok else 0.0

    # Recompute stats and compare
    stats_match_score = 0.0
    excluded_match_score = 0.0
    if input_ok and parks_rows and isinstance(summary_obj, dict) and keys_ok:
        # Build join
        used_pairs = []
        park_vals = []
        activity_vals = []
        # Identify excluded reasons
        parks_map_rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in parks_rows:
            key = _normalize_key(r.get("city", ""), r.get("state", ""))
            parks_map_rows[key] = r

        for key in input_keys:
            r = parks_map_rows.get(key)
            if r is None:
                continue
            pav = _parse_float(r.get("park_access_percent"))
            if pav is not None and key in input_map_activity:
                used_pairs.append(key)
                park_vals.append(pav)
                activity_vals.append(input_map_activity[key])

        n_used = len(used_pairs)
        recomputed_mean = _mean(park_vals)
        recomputed_median = _median(park_vals)
        recomputed_std_pop = _std_population(park_vals)
        recomputed_std_samp = _std_sample(park_vals)
        recomputed_activity_mean = _mean(activity_vals)
        recomputed_r_sample = _pearson(park_vals, activity_vals, sample=True) if n_used >= 2 else None
        recomputed_r_pop = _pearson(park_vals, activity_vals, sample=False) if n_used >= 2 else None

        # Extract from summary
        n_cities_used_val = _parse_int(summary_obj.get("n_cities_used"))
        mean_val = _parse_float(summary_obj.get("park_access_percent_mean"))
        median_val = _parse_float(summary_obj.get("park_access_percent_median"))
        std_val = _parse_float(summary_obj.get("park_access_percent_std"))
        pa_mean_val = _parse_float(summary_obj.get("physical_activity_mean"))
        r_val = _parse_float(summary_obj.get("pearson_r_between_park_access_and_physical_activity"))

        # Compare with tolerance
        n_ok = (n_cities_used_val == n_used)
        mean_ok = _float_close(mean_val, recomputed_mean) if recomputed_mean is not None else (mean_val is None)
        median_ok = _float_close(median_val, recomputed_median) if recomputed_median is not None else (median_val is None)
        # std can be sample or population - accept either
        std_ok = False
        if std_val is not None:
            if recomputed_std_pop is not None and _float_close(std_val, recomputed_std_pop):
                std_ok = True
            if recomputed_std_samp is not None and _float_close(std_val, recomputed_std_samp):
                std_ok = True
        elif recomputed_std_pop is None and recomputed_std_samp is None:
            std_ok = True

        pa_mean_ok = _float_close(pa_mean_val, recomputed_activity_mean) if recomputed_activity_mean is not None else (pa_mean_val is None)
        # correlation: accept sample or population within tolerance
        r_ok = False
        if n_used >= 2:
            if r_val is not None:
                if recomputed_r_sample is not None and _float_close(r_val, recomputed_r_sample):
                    r_ok = True
                if recomputed_r_pop is not None and _float_close(r_val, recomputed_r_pop):
                    r_ok = True
        else:
            # If not enough data to compute, accept any numeric
            r_ok = (r_val is not None)

        checks = [n_ok, mean_ok, median_ok, std_ok, pa_mean_ok, r_ok]
        stats_match_score = sum(1.0 for c in checks if c) / len(checks)

        # Cities excluded comparison
        # Compute expected excluded: all input cities not used (missing park_access or no match)
        expected_excluded = []
        for key in sorted(input_keys):
            if key not in used_pairs:
                city = next((r.get("city") for r in parks_rows if _normalize_key(r.get("city", ""), r.get("state", "")) == key), None)
                state = next((r.get("state") for r in parks_rows if _normalize_key(r.get("city", ""), r.get("state", "")) == key), None)
                if city is None:
                    # no record at all in parks file; still excluded
                    city = ""
                    state = ""
                    # However parks_access_rows_coverage already scored this
                # Use original cased from parks if present, else from input
                if not city or not state:
                    # fallback to input's casing
                    for r in input_rows:
                        if _normalize_key(r.get("city", ""), r.get("state", "")) == key:
                            city = r.get("city", "")
                            state = r.get("state", "")
                            break
                expected_excluded.append({"city": city, "state": state, "reason": "missing_park_access_or_no_match"})
        reported_excluded = summary_obj.get("cities_excluded")
        if isinstance(reported_excluded, list):
            # Normalize for comparison (case-insensitive city,state)
            def norm_list(lst):
                out = set()
                for e in lst:
                    if not isinstance(e, dict):
                        continue
                    c = str(e.get("city", "")).strip()
                    s = str(e.get("state", "")).strip()
                    r = str(e.get("reason", "")).strip()
                    out.add((_normalize_key(c, s), r))
                return out

            expected_set = norm_list(expected_excluded)
            reported_set = norm_list(reported_excluded)
            if expected_set == reported_set:
                excluded_match_score = 1.0
            else:
                # Partial: Jaccard similarity on (key, reason) pairs
                inter = expected_set & reported_set
                union = expected_set | reported_set
                excluded_match_score = (len(inter) / len(union)) if len(union) > 0 else 0.0
        else:
            excluded_match_score = 0.0

    scores["summary_json_values_consistent"] = stats_match_score
    scores["cities_excluded_consistent"] = excluded_match_score

    # Report summary.md checks
    summary_md = ""
    try:
        summary_md = report_summary_md_path.read_text(encoding="utf-8")
    except Exception:
        summary_md = ""

    # Sections presence
    sections_ok = False
    if summary_md:
        has_objective = re.search(r"\bObjective\b", summary_md, flags=re.IGNORECASE) is not None
        has_data_sources = re.search(r"Data sources and methods", summary_md, flags=re.IGNORECASE) is not None
        has_results = re.search(r"\bResults\b", summary_md, flags=re.IGNORECASE) is not None
        has_limitations = re.search(r"\bLimitations\b", summary_md, flags=re.IGNORECASE) is not None
        has_next_steps = re.search(r"\bNext steps\b", summary_md, flags=re.IGNORECASE) is not None
        count = sum(1 for b in [has_objective, has_data_sources, has_results, has_limitations, has_next_steps] if b)
        sections_ok = count == 5
    scores["report_summary_sections"] = 1.0 if sections_ok else 0.0

    # Results table and metrics in summary.md
    table_ok = False
    corr_ok_md = False
    n_ok_md = False
    if summary_md:
        headers = _extract_markdown_table_headers(summary_md)
        table_ok = len(headers) > 0
        # correlation presence with numeric close to summary.json (if available)
        if isinstance(summary_obj, dict):
            r_val = _parse_float(summary_obj.get("pearson_r_between_park_access_and_physical_activity"))
            if r_val is not None:
                r_strs = {f"{r_val:.3f}", f"{r_val:.2f}", f"{r_val:.4f}"}
                corr_ok_md = any(rs in summary_md for rs in r_strs) and (re.search(r"correlation", summary_md, flags=re.IGNORECASE) is not None)
            else:
                corr_ok_md = re.search(r"correlation", summary_md, flags=re.IGNORECASE) is not None
            # n presence
            n_val = _parse_int(summary_obj.get("n_cities_used"))
            if n_val is not None:
                match = re.search(r"n\s*[:=]\s*(\d+)", summary_md, flags=re.IGNORECASE)
                if match:
                    try:
                        n_in_text = int(match.group(1))
                        n_ok_md = (n_in_text == n_val)
                    except Exception:
                        n_ok_md = False
                else:
                    # Fallback: presence of the exact integer somewhere alongside 'n'
                    n_ok_md = False
            else:
                n_ok_md = False
    # Combine
    sub_checks = [table_ok, corr_ok_md, n_ok_md]
    if sub_checks:
        scores["report_summary_results_table_and_metrics"] = sum(1.0 for b in sub_checks if b) / len(sub_checks)
    else:
        scores["report_summary_results_table_and_metrics"] = 0.0

    # Sources and date range in summary.md
    src_date_score = 0.0
    if parks_rows and summary_md:
        # Unique source_orgs
        orgs = sorted(set(str(r.get("source_org", "")).strip() for r in parks_rows if str(r.get("source_org", "")).strip() != ""))
        # date range
        dates = [str(r.get("retrieval_date", "")).strip() for r in parks_rows if _is_yyyy_mm_dd(str(r.get("retrieval_date", "")).strip())]
        date_min = min(dates) if dates else None
        date_max = max(dates) if dates else None
        # Check bullet list presence lines starting with "-", "*"
        bullet_lines = [ln for ln in summary_md.splitlines() if ln.strip().startswith(("-", "*"))]
        # Each org must appear somewhere (preferably in a bullet)
        org_hits = 0
        for org in orgs:
            found = any(org in ln for ln in bullet_lines) or (org in summary_md)
            if found:
                org_hits += 1
        org_ratio = (org_hits / len(orgs)) if orgs else 1.0
        date_hits = 0
        date_total = 0
        if date_min:
            date_total += 1
            if date_min in summary_md:
                date_hits += 1
        if date_max and date_max != date_min:
            date_total += 1
            if date_max in summary_md:
                date_hits += 1
        date_ratio = (date_hits / date_total) if date_total > 0 else 1.0
        src_date_score = (org_ratio + date_ratio) / 2.0 if (orgs or date_total > 0) else 0.0
    scores["report_summary_sources_and_dates"] = src_date_score

    # design.md content checks
    design_md = ""
    try:
        design_md = design_md_path.read_text(encoding="utf-8")
    except Exception:
        design_md = ""
    design_score = 0.0
    if design_md:
        components_checks = [
            re.search(r"\bweb search\b|\bsearch engine\b", design_md, flags=re.IGNORECASE) is not None,  # data retrieval via web search
            re.search(r"\blog\b|\blogging\b|\bcitation\b", design_md, flags=re.IGNORECASE) is not None,   # structured citation logging
            re.search(r"\bdataset\b|\bassembly\b", design_md, flags=re.IGNORECASE) is not None,          # dataset assembly
            re.search(r"\bjoin\b", design_md, flags=re.IGNORECASE) is not None and
            re.search(r"\bhealth data\b", design_md, flags=re.IGNORECASE) is not None,                   # join with health data
            re.search(r"\bstats?\b|\bstatistics\b", design_md, flags=re.IGNORECASE) is not None,         # stats computation
            re.search(r"\breport generation\b|\breport\b", design_md, flags=re.IGNORECASE) is not None,  # report generation
        ]
        scaling_checks = [
            re.search(r"\bscale|\bscaling", design_md, flags=re.IGNORECASE) is not None,
            re.search(r"\bmodular", design_md, flags=re.IGNORECASE) is not None,
            re.search(r"\bcach(e|ing)", design_md, flags=re.IGNORECASE) is not None,
            re.search(r"\bschema", design_md, flags=re.IGNORECASE) is not None,
            re.search(r"\breproduc", design_md, flags=re.IGNORECASE) is not None,
        ]
        assumptions_checks = [
            re.search(r"\bassumption", design_md, flags=re.IGNORECASE) is not None,
            re.search(r"\bcurated\b|\bdata feed\b|\bfeed\b|\bswap\b", design_md, flags=re.IGNORECASE) is not None,
        ]
        comp_ratio = sum(1 for b in components_checks if b) / len(components_checks) if components_checks else 0.0
        scale_hits = sum(1 for b in scaling_checks if b)
        scale_ratio = min(1.0, scale_hits / 3.0)  # require at least 3 scaling-related mentions for full credit
        assum_ratio = sum(1 for b in assumptions_checks if b) / len(assumptions_checks) if assumptions_checks else 0.0
        design_score = (comp_ratio * 0.5) + (scale_ratio * 0.3) + (assum_ratio * 0.2)
    scores["design_md_content"] = design_score

    return scores


def main() -> None:
        workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade([], workspace_path)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()