import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

def read_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def get_counts_for_slug(root: Any, slug: str) -> List[Tuple[int, float]]:
    """
    Try to extract a list of (year, count) for the slug from publication_counts.json.
    Be robust to a variety of reasonable shapes.
    """
    results: List[Tuple[int, float]] = []

    def extract_series(series: Any) -> Optional[List[Tuple[int, float]]]:
        tmp: List[Tuple[int, float]] = []
        if isinstance(series, list):
            for item in series:
                if isinstance(item, dict) and "year" in item and "count" in item:
                    y = item["year"]
                    c = item["count"]
                    if isinstance(y, int) and (isinstance(c, (int, float)) and c is not True and c is not False):
                        tmp.append((y, float(c)))
            if tmp:
                return tmp
        return None

    # Case 1: dict mapping slug -> list[{year,count}]
    if isinstance(root, dict):
        if slug in root:
            s = extract_series(root[slug])
            if s:
                return sorted(s, key=lambda t: t[0])
        # Case 2: dict mapping slug -> dict with 'data'/'counts'/... containing list
        if slug in root and isinstance(root[slug], dict):
            for key in ("data", "counts", "series", "timeseries", "values"):
                if key in root[slug]:
                    s = extract_series(root[slug][key])
                    if s:
                        return sorted(s, key=lambda t: t[0])
        # Case 3: dict with a collection field
        for k, v in root.items():
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        # item with slug match and inner list under known keys
                        if item.get("slug") == slug or item.get("keyword") == slug or item.get("name") == slug:
                            for key in ("data", "counts", "series", "timeseries", "values"):
                                if key in item:
                                    s = extract_series(item[key])
                                    if s:
                                        return sorted(s, key=lambda t: t[0])
                        # Or direct year/count entries grouped by slug
                        if item.get("slug") == slug and "year" in item and "count" in item:
                            # collect all items with this slug
                            pass
                # If list is flat timeseries with slug field
                flat: List[Tuple[int, float]] = []
                for item in v:
                    if isinstance(item, dict) and item.get("slug") == slug and "year" in item and "count" in item:
                        y = item["year"]; c = item["count"]
                        if isinstance(y, int) and isinstance(c, (int, float)):
                            flat.append((y, float(c)))
                if flat:
                    return sorted(flat, key=lambda t: t[0])
    # Case 4: root list
    if isinstance(root, list):
        # items grouped by slug
        for item in root:
            if isinstance(item, dict):
                if item.get("slug") == slug or item.get("keyword") == slug or item.get("name") == slug:
                    for key in ("data", "counts", "series", "timeseries", "values"):
                        if key in item:
                            s = extract_series(item[key])
                            if s:
                                return sorted(s, key=lambda t: t[0])
        # flat list records with slug-year-count
        flat: List[Tuple[int, float]] = []
        for item in root:
            if isinstance(item, dict) and item.get("slug") == slug and "year" in item and "count" in item:
                y = item["year"]; c = item["count"]
                if isinstance(y, int) and isinstance(c, (int, float)):
                    flat.append((y, float(c)))
        if flat:
            return sorted(flat, key=lambda t: t[0])

    return results

def words_count(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)

def get_section(text: str, header_substring: str) -> Optional[str]:
    """
    Extract text of a section starting at a line containing header_substring (case-insensitive)
    until the next markdown header (# ...) or EOF.
    """
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if header_substring.lower() in line.lower():
            start_idx = i
            break
    if start_idx is None:
        return None
    # Collect until next header (line starting with #) excluding the header line itself
    collected: List[str] = []
    for j in range(start_idx + 1, len(lines)):
        if re.match(r"^\s*#+\s", lines[j]):
            break
        collected.append(lines[j])
    return "\n".join(collected).strip()

def extract_narrative_after_ranking(md_text: str) -> str:
    """
    Find the 'Ranking by current velocity' section, skip its 1./2./3. lines,
    then return the following paragraph (until blank line or next header).
    """
    lines = md_text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if "Ranking by current velocity" in line:
            start_idx = i
            break
    if start_idx is None:
        return ""
    # Find three numbered lines starting with 1., 2., 3. after start_idx
    idx = start_idx + 1
    found = []
    while idx < len(lines) and len(found) < 3:
        if re.match(r"^\s*(\d\.)\s", lines[idx]):
            found.append(idx)
        idx += 1
    # Narrative starts after the last of these three lines
    if len(found) < 3:
        # If not all ranking lines found, fallback to the next non-empty paragraph
        base = start_idx + 1
    else:
        base = found[-1] + 1
    # Skip blank lines
    while base < len(lines) and lines[base].strip() == "":
        base += 1
    # Collect paragraph until blank line or next header
    para_lines: List[str] = []
    while base < len(lines):
        if lines[base].strip() == "":
            break
        if re.match(r"^\s*#+\s", lines[base]):
            break
        para_lines.append(lines[base])
        base += 1
    return "\n".join(para_lines).strip()

def check_prediction_years(pred_obj: Any, expected_start_year: int) -> Tuple[bool, bool]:
    """
    Returns (has_three_consecutive_years, values_schema_ok)
    Checks keys exactly next three consecutive years as strings.
    """
    if not isinstance(pred_obj, dict):
        return (False, False)
    keys = list(pred_obj.keys())
    # must be exactly 3 keys
    if len(keys) != 3:
        return (False, False)
    try:
        years_int = sorted([int(k) for k in keys])
    except Exception:
        return (False, False)
    expected = [expected_start_year + 1, expected_start_year + 2, expected_start_year + 3]
    if years_int != expected:
        has_three = False
    else:
        has_three = True
    values_ok = True
    for k in keys:
        v = pred_obj[k]
        if not isinstance(v, dict):
            values_ok = False
            break
        if "estimated_count" not in v or "confidence" not in v:
            values_ok = False
            break
        if not isinstance(v["estimated_count"], int):
            values_ok = False
            break
        conf = v["confidence"]
        if not (is_number(conf) and 0.0 <= float(conf) <= 1.0):
            values_ok = False
            break
    return (has_three, values_ok)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected artifacts
    slugs = ["foundation-models", "diffusion-models", "federated-learning"]
    metrics_paths = {slug: os.path.join(output_dir, "metrics", f"{slug}.json") for slug in slugs}
    summary_path = os.path.join(output_dir, "summary", "comparison.md")
    machine_index_path = os.path.join(output_dir, "checks", "index.json")

    # Load input references (for objective checks that relate outputs to inputs)
    keywords_path = os.path.join(input_dir, "keywords.json")
    counts_path = os.path.join(input_dir, "publication_counts.json")
    keywords_json = read_json(keywords_path)
    counts_json = read_json(counts_path)

    # Build input-derived expectations per slug
    input_years_by_slug: Dict[str, List[int]] = {}
    last_two_counts_by_slug: Dict[str, Optional[Tuple[float, float]]] = {}
    for slug in slugs:
        series = get_counts_for_slug(counts_json, slug) if counts_json is not None else []
        years = [y for (y, _) in series]
        input_years_by_slug[slug] = years
        if len(series) >= 2:
            prev, curr = series[-2][1], series[-1][1]
            last_two_counts_by_slug[slug] = (prev, curr)
        else:
            last_two_counts_by_slug[slug] = None

    checks: Dict[str, bool] = {}

    # Initialize existence checks
    for slug, path in metrics_paths.items():
        checks[f"metrics_{slug}_exists"] = os.path.isfile(path)

    checks["summary_exists"] = os.path.isfile(summary_path)
    checks["machine_index_exists"] = os.path.isfile(machine_index_path)

    # Per-metric file schema checks
    allowed_stages = {"embryonic", "growth", "mature", "decline"}
    allowed_trends = {"growth", "stable", "decline"}

    for slug, path in metrics_paths.items():
        # Initialize dependent checks to False
        checks[f"schema_fields_{slug}"] = False
        checks[f"series_length_matches_input_{slug}"] = False
        checks[f"series_years_sorted_{slug}"] = False
        checks[f"current_velocity_type_{slug}"] = False
        checks[f"current_acceleration_numeric_{slug}"] = False
        checks[f"stage_conf_in_range_{slug}"] = False
        checks[f"stage_value_valid_{slug}"] = False
        checks[f"trend_value_valid_{slug}"] = False
        checks[f"prediction_years_ok_{slug}"] = False
        checks[f"prediction_values_ok_{slug}"] = False
        checks[f"insights_length_ok_{slug}"] = False
        checks[f"analysis_period_matches_input_{slug}"] = False

        if not checks[f"metrics_{slug}_exists"]:
            continue

        data = read_json(path)
        if not isinstance(data, dict):
            continue

        # Required fields presence
        required_fields = [
            "keyword", "analysis_period", "current_velocity", "current_acceleration",
            "stage", "stage_confidence", "trend", "velocity_series",
            "prediction", "insights"
        ]
        has_fields = all(k in data for k in required_fields)
        if not has_fields or not isinstance(data.get("analysis_period"), dict):
            # keep False
            pass
        else:
            # Validate basic types
            ap = data["analysis_period"]
            vs = data["velocity_series"]
            pred = data["prediction"]
            insights = data["insights"]
            if (
                isinstance(ap.get("start"), int) and isinstance(ap.get("end"), int)
                and isinstance(vs, list)
                and isinstance(pred, dict)
                and isinstance(insights, list)
            ):
                checks[f"schema_fields_{slug}"] = True

        # Validate analysis_period vs input years if available
        years_in = input_years_by_slug.get(slug) or []
        ap_ok = False
        if years_in and isinstance(data.get("analysis_period"), dict):
            ap = data["analysis_period"]
            if isinstance(ap.get("start"), int) and isinstance(ap.get("end"), int):
                if ap["start"] == min(years_in) and ap["end"] == max(years_in):
                    ap_ok = True
        checks[f"analysis_period_matches_input_{slug}"] = ap_ok

        # velocity_series checks
        series = data.get("velocity_series")
        series_years_sorted = False
        series_len_ok = False
        if isinstance(series, list) and series:
            # basic structure
            struct_ok_all = True
            series_years: List[int] = []
            prev_year = None
            for item in series:
                if not isinstance(item, dict):
                    struct_ok_all = False
                    break
                if "year" not in item or "velocity" not in item or "acceleration" not in item:
                    struct_ok_all = False
                    break
                y = item["year"]
                if not isinstance(y, int):
                    struct_ok_all = False
                    break
                v = item["velocity"]
                a = item["acceleration"]
                # velocity: number, None, or "inf"
                v_ok = (v is None) or (is_number(v)) or (v == "inf")
                a_ok = (a is None) or is_number(a)
                if not (v_ok and a_ok):
                    struct_ok_all = False
                    break
                # ascending years
                if prev_year is not None and y <= prev_year:
                    series_years_sorted = False
                    struct_ok_all = False
                    break
                series_years.append(y)
                prev_year = y
            if struct_ok_all:
                series_years_sorted = True
            # length equals number of input years (if known)
            if years_in:
                series_len_ok = (len(series) == len(years_in))
            else:
                # cannot verify against input; leave as False (objective check ties to input)
                series_len_ok = False
        checks[f"series_years_sorted_{slug}"] = series_years_sorted
        checks[f"series_length_matches_input_{slug}"] = series_len_ok

        # Stage/trend and confidence
        stage = data.get("stage")
        trend = data.get("trend")
        stage_conf = data.get("stage_confidence")
        checks[f"stage_value_valid_{slug}"] = stage in allowed_stages
        checks[f"trend_value_valid_{slug}"] = trend in allowed_trends
        if is_number(stage_conf) and 0.0 <= float(stage_conf) <= 1.0:
            checks[f"stage_conf_in_range_{slug}"] = True

        # Current velocity / acceleration
        curr_v = data.get("current_velocity")
        cv_ok = False
        if curr_v == "inf":
            # Only valid if previous count == 0 and current > 0
            prev_curr = last_two_counts_by_slug.get(slug)
            if prev_curr is not None:
                prev_c, curr_c = prev_curr
                if prev_c == 0 and curr_c > 0:
                    cv_ok = True
        elif is_number(curr_v) or curr_v is None:
            # accept numeric (None should not be used according to spec, but be tolerant only for schema; however here we require numeric or "inf")
            cv_ok = is_number(curr_v)
        checks[f"current_velocity_type_{slug}"] = cv_ok

        curr_a = data.get("current_acceleration")
        checks[f"current_acceleration_numeric_{slug}"] = is_number(curr_a)

        # Prediction checks
        # Prefer using input-derived last year; fallback to analysis_period.end if missing
        last_input_year = max(years_in) if years_in else (data.get("analysis_period", {}).get("end") if isinstance(data.get("analysis_period"), dict) else None)
        if isinstance(last_input_year, int):
            has_three, values_ok = check_prediction_years(data.get("prediction"), last_input_year)
            checks[f"prediction_years_ok_{slug}"] = has_three
            checks[f"prediction_values_ok_{slug}"] = values_ok
        else:
            # cannot validate; leave False
            pass

        # Insights length 3-6 and string items
        insights = data.get("insights")
        insights_ok = False
        if isinstance(insights, list) and 3 <= len(insights) <= 6 and all(isinstance(x, str) for x in insights):
            insights_ok = True
        checks[f"insights_length_ok_{slug}"] = insights_ok

    # Summary checks
    checks["summary_has_ranking_header"] = False
    checks["summary_has_numbered_list_three"] = False
    checks["summary_list_mentions_all_slugs"] = False
    checks["summary_narrative_len_150_250"] = False
    checks["assumptions_section_present"] = False
    checks["assumptions_mentions_required"] = False

    if checks["summary_exists"]:
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                md = f.read()
        except Exception:
            md = ""

        if "Ranking by current velocity" in md:
            checks["summary_has_ranking_header"] = True

            # Find lines after header with 1., 2., 3.
            lines = md.splitlines()
            start_idx = None
            for i, line in enumerate(lines):
                if "Ranking by current velocity" in line:
                    start_idx = i
                    break
            found_lines: Dict[int, str] = {}
            if start_idx is not None:
                for j in range(start_idx + 1, len(lines)):
                    m = re.match(r"^\s*(\d)\.\s*(.*)$", lines[j])
                    if m:
                        num = int(m.group(1))
                        if num in (1, 2, 3) and num not in found_lines:
                            found_lines[num] = lines[j]
                    # stop if we reached assumptions or another header and we already have some lines
                    if re.match(r"^\s*#+\s", lines[j]) and len(found_lines) > 0:
                        break
            if len(found_lines) == 3:
                checks["summary_has_numbered_list_three"] = True
                # Validate mentions of slugs across the three lines
                mentions = set()
                for _, txt in sorted(found_lines.items()):
                    for s in slugs:
                        if s in txt:
                            mentions.add(s)
                if set(slugs) == mentions:
                    checks["summary_list_mentions_all_slugs"] = True

        # Narrative length check
        narrative = extract_narrative_after_ranking(md)
        wc = words_count(narrative)
        if 150 <= wc <= 250:
            checks["summary_narrative_len_150_250"] = True

        # Assumptions & Settings section
        section = get_section(md, "Assumptions & Settings")
        if section is not None:
            checks["assumptions_section_present"] = True
            section_lower = section.lower()
            has_assumption_word = ("assumption" in section_lower or "assumptions" in section_lower)
            has_smoothing = ("smoothing" in section_lower)
            has_factor = bool(re.search(r"\b\d+(\.\d+)?\b", section_lower))
            has_no_smoothing = ("no smoothing" in section_lower)
            if has_assumption_word and has_smoothing and (has_factor or has_no_smoothing):
                checks["assumptions_mentions_required"] = True

    # Machine index checks
    checks["machine_index_files_ok"] = False
    checks["machine_index_ok_true"] = False
    if checks["machine_index_exists"]:
        idx_json = read_json(machine_index_path)
        if isinstance(idx_json, dict):
            files = idx_json.get("files")
            ok_flag = idx_json.get("ok")
            expected_files = [f"output/metrics/{slug}.json" for slug in slugs]
            if isinstance(files, list) and all(isinstance(x, str) for x in files):
                # Must contain exactly the three expected paths (any order, no extras)
                if set(files) == set(expected_files) and len(files) == 3:
                    checks["machine_index_files_ok"] = True
            if ok_flag is True and checks["machine_index_files_ok"]:
                checks["machine_index_ok_true"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
    # Ensure baseline no-op = 0.0 (already ensured since no files => all False)

    # Print final JSON (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, separators=(",", ":")))

if __name__ == "__main__":
    main()