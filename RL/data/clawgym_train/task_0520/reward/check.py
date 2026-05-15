import json
import csv
import sys
import re
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_csv_safe(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                return None, None
            rows = [row for row in reader]
            return fieldnames, rows
    except Exception:
        return None, None


def _parse_islands_yaml(path: Path) -> Optional[List[Dict[str, str]]]:
    """
    Minimal YAML parser tailored to the given structure:
    islands:
      - code: ISL
        name: Iceland
        region_group: North Atlantic
      ...
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    lines = text.splitlines()
    islands: List[Dict[str, str]] = []
    in_islands = False
    current: Optional[Dict[str, str]] = None
    for raw in lines:
        line = raw.rstrip("\n")
        if not in_islands:
            if line.strip() == "islands:":
                in_islands = True
            continue
        # in islands section
        if line.strip().startswith("- "):
            # start a new item
            if current is not None:
                islands.append(current)
            current = {}
            # handle inline "- key: value" if any (not expected here)
            after_dash = line.strip()[2:]
            if after_dash:
                if ": " in after_dash:
                    k, v = after_dash.split(": ", 1)
                    current[k.strip()] = v.strip()
        else:
            # property lines with indentation
            if current is None:
                # Unexpected structure
                continue
            stripped = line.strip()
            if ": " in stripped:
                k, v = stripped.split(": ", 1)
                current[k.strip()] = v.strip()
            elif stripped == "" or stripped.startswith("#"):
                continue
            else:
                # Unrecognized, ignore
                continue
    if current is not None:
        islands.append(current)
    # Normalize and validate
    cleaned: List[Dict[str, str]] = []
    for it in islands:
        code = it.get("code")
        name = it.get("name")
        region = it.get("region_group")
        if code and name and region:
            cleaned.append({"code": code.strip(), "name": name.strip(), "region_group": region.strip()})
    if not cleaned:
        return None
    return cleaned


def _find_indicator_in_json(obj: Any, expected_id: str) -> bool:
    """
    Recursively search for a World Bank 'indicator' occurrence matching expected_id.
    Accepts formats like:
      {"indicator": {"id": "SP.POP.TOTL", "value": "..."}}
      {"indicator": "SP.POP.TOTL"}
    """
    try:
        if isinstance(obj, dict):
            if "indicator" in obj:
                ind = obj["indicator"]
                if isinstance(ind, dict) and ind.get("id") == expected_id:
                    return True
                if isinstance(ind, str) and ind == expected_id:
                    return True
            for v in obj.values():
                if _find_indicator_in_json(v, expected_id):
                    return True
        elif isinstance(obj, list):
            for v in obj:
                if _find_indicator_in_json(v, expected_id):
                    return True
    except Exception:
        return False
    return False


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s.strip())
    except Exception:
        return None


def _safe_float(s: str) -> Tuple[bool, Optional[float]]:
    if s is None:
        return (True, None)
    t = str(s).strip()
    if t == "" or t.lower() in {"na", "nan", "null", "none"}:
        return (True, None)
    try:
        return (True, float(t))
    except Exception:
        return (False, None)


def _almost_equal(a: float, b: float, rel_tol: float = 1e-9, abs_tol: float = 1e-6) -> bool:
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "population_raw_json_valid": 0.0,
        "gdp_per_capita_raw_json_valid": 0.0,
        "merged_csv_header_and_types": 0.0,
        "merged_country_mapping_valid": 0.0,
        "merged_year_range_and_uniqueness": 0.0,
        "summary_csv_header_valid": 0.0,
        "summary_aggregates_match_merged": 0.0,
        "status_json_structure_and_content": 0.0,
        "run_log_contains_expected_markers": 0.0,
    }

    # Paths
    input_islands = workspace / "input" / "islands.yaml"
    raw_population = workspace / "data" / "raw" / "population.json"
    raw_gdp = workspace / "data" / "raw" / "gdp_per_capita.json"
    merged_csv = workspace / "output" / "merged.csv"
    summary_csv = workspace / "output" / "summary_by_region.csv"
    status_json = workspace / "output" / "status.json"
    run_log = workspace / "output" / "run_log.txt"

    # Load islands mapping
    islands = _parse_islands_yaml(input_islands)
    code_to_name_region: Dict[str, Tuple[str, str]] = {}
    if islands is not None:
        for it in islands:
            code_to_name_region[it["code"]] = (it["name"], it["region_group"])

    # 1) Validate raw population JSON structure
    pop_obj = _load_json_safe(raw_population)
    if pop_obj is not None and _find_indicator_in_json(pop_obj, "SP.POP.TOTL"):
        scores["population_raw_json_valid"] = 1.0

    # 2) Validate raw GDP per capita JSON structure
    gdp_obj = _load_json_safe(raw_gdp)
    if gdp_obj is not None and _find_indicator_in_json(gdp_obj, "NY.GDP.PCAP.CD"):
        scores["gdp_per_capita_raw_json_valid"] = 1.0

    # 3) Validate merged CSV header and types
    merged_fields, merged_rows = _parse_csv_safe(merged_csv)
    merged_header_expected = ["country_code", "country_name", "region_group", "year", "population", "gdp_per_capita_usd"]
    merged_header_ok = False
    merged_types_ok = False
    if merged_fields is not None and merged_rows is not None:
        if merged_fields == merged_header_expected:
            merged_header_ok = True
            bad_type = False
            for r in merged_rows:
                # year must be present and int
                year_str = r.get("year", "")
                year_val = _safe_int(year_str)
                if year_val is None:
                    bad_type = True
                    break
                # population numeric or empty
                ok_pop, _pop = _safe_float(r.get("population", ""))
                if not ok_pop:
                    bad_type = True
                    break
                # gdp numeric or empty
                ok_gdp, _gdp = _safe_float(r.get("gdp_per_capita_usd", ""))
                if not ok_gdp:
                    bad_type = True
                    break
            merged_types_ok = not bad_type and (len(merged_rows) >= 0)  # allow empty file to fail later checks
    if merged_header_ok and merged_types_ok and merged_rows is not None and len(merged_rows) > 0:
        scores["merged_csv_header_and_types"] = 1.0

    # 4) merged country mapping valid
    merged_mapping_ok = False
    if merged_rows is not None and len(merged_rows) > 0 and code_to_name_region:
        ok = True
        for r in merged_rows:
            code = r.get("country_code", "").strip()
            name = r.get("country_name", "").strip()
            region = r.get("region_group", "").strip()
            if code not in code_to_name_region:
                ok = False
                break
            exp_name, exp_region = code_to_name_region[code]
            if name != exp_name or region != exp_region:
                ok = False
                break
        if ok:
            merged_mapping_ok = True
    if merged_mapping_ok:
        scores["merged_country_mapping_valid"] = 1.0

    # 5) year range and uniqueness
    year_range_ok = False
    uniqueness_ok = False
    if merged_rows is not None and len(merged_rows) > 0:
        ok_range = True
        seen: set = set()
        unique_ok = True
        for r in merged_rows:
            y = _safe_int(r.get("year", ""))
            code = r.get("country_code", "").strip()
            if y is None or y < 1980 or y > 2015:
                ok_range = False
                break
            key = (code, y)
            if key in seen:
                unique_ok = False
                break
            seen.add(key)
        year_range_ok = ok_range
        uniqueness_ok = unique_ok
    if year_range_ok and uniqueness_ok and merged_rows is not None and len(merged_rows) > 0:
        scores["merged_year_range_and_uniqueness"] = 1.0

    # 6) summary CSV header valid
    summary_fields, summary_rows = _parse_csv_safe(summary_csv)
    summary_header_expected = ["region_group", "year", "total_population", "mean_gdp_per_capita_usd"]
    summary_header_ok = False
    summary_types_ok = False
    if summary_fields is not None and summary_rows is not None:
        if summary_fields == summary_header_expected:
            summary_header_ok = True
            bad_type = False
            for r in summary_rows:
                y = _safe_int(r.get("year", ""))
                if y is None:
                    bad_type = True
                    break
                ok_pop, _ = _safe_float(r.get("total_population", ""))
                if not ok_pop:
                    bad_type = True
                    break
                ok_gdp, _ = _safe_float(r.get("mean_gdp_per_capita_usd", ""))
                if not ok_gdp:
                    bad_type = True
                    break
            summary_types_ok = not bad_type
    if summary_header_ok and summary_types_ok and summary_rows is not None and len(summary_rows) > 0:
        scores["summary_csv_header_valid"] = 1.0

    # 7) summary aggregates match merged
    def compute_expected_from_merged(rows: List[Dict[str, str]]) -> Dict[Tuple[str, int], Tuple[float, Optional[float], int, int]]:
        # returns mapping: (region, year) -> (sum_pop, mean_gdp or None, count_gdp, count_pop)
        agg: Dict[Tuple[str, int], Dict[str, float]] = {}
        counts_gdp: Dict[Tuple[str, int], int] = {}
        counts_pop: Dict[Tuple[str, int], int] = {}
        for r in rows:
            region = (r.get("region_group") or "").strip()
            y = _safe_int(r.get("year", ""))
            if region == "" or y is None:
                continue
            key = (region, y)
            if key not in agg:
                agg[key] = {"sum_pop": 0.0, "sum_gdp": 0.0}
                counts_gdp[key] = 0
                counts_pop[key] = 0
            ok_pop, pop_v = _safe_float(r.get("population", ""))
            if ok_pop and pop_v is not None:
                agg[key]["sum_pop"] += pop_v
                counts_pop[key] += 1
            ok_gdp, gdp_v = _safe_float(r.get("gdp_per_capita_usd", ""))
            if ok_gdp and gdp_v is not None:
                agg[key]["sum_gdp"] += gdp_v
                counts_gdp[key] += 1
        result: Dict[Tuple[str, int], Tuple[float, Optional[float], int, int]] = {}
        for key, vals in agg.items():
            c_gdp = counts_gdp.get(key, 0)
            c_pop = counts_pop.get(key, 0)
            mean_gdp = (vals["sum_gdp"] / c_gdp) if c_gdp > 0 else None
            result[key] = (vals["sum_pop"], mean_gdp, c_gdp, c_pop)
        return result

    def parse_summary_rows(rows: List[Dict[str, str]]) -> Dict[Tuple[str, int], Tuple[Optional[float], Optional[float]]]:
        out: Dict[Tuple[str, int], Tuple[Optional[float], Optional[float]]] = {}
        for r in rows:
            region = (r.get("region_group") or "").strip()
            y = _safe_int(r.get("year", ""))
            if region == "" or y is None:
                continue
            ok_pop, pop_v = _safe_float(r.get("total_population", ""))
            ok_gdp, gdp_v = _safe_float(r.get("mean_gdp_per_capita_usd", ""))
            if not ok_pop or not ok_gdp:
                # mark as unparsable by setting None; caller will treat as mismatch
                out[(region, y)] = (None, None)
            else:
                out[(region, y)] = (pop_v, gdp_v)
        return out

    agg_ok = False
    if merged_rows is not None and summary_rows is not None and len(merged_rows) > 0 and len(summary_rows) > 0:
        expected = compute_expected_from_merged(merged_rows)
        summary_map = parse_summary_rows(summary_rows)
        expected_keys = set(expected.keys())
        summary_keys = set(summary_map.keys())
        if expected_keys == summary_keys:
            all_match = True
            for key in expected_keys:
                exp_sum_pop, exp_mean_gdp, c_gdp, _c_pop = expected[key]
                sum_cell, mean_cell = summary_map[key]
                # population must be present and match (allow tolerance)
                if sum_cell is None:
                    all_match = False
                    break
                if not _almost_equal(float(exp_sum_pop), float(sum_cell), rel_tol=1e-9, abs_tol=1e-4):
                    all_match = False
                    break
                # mean gdp: if we had at least one gdp value, must match; else allow None/empty
                if c_gdp > 0:
                    if mean_cell is None:
                        all_match = False
                        break
                    if not _almost_equal(float(exp_mean_gdp), float(mean_cell), rel_tol=1e-9, abs_tol=1e-4):
                        all_match = False
                        break
                else:
                    # allow None or NaN-like empties
                    if mean_cell is not None and not math.isnan(mean_cell):
                        # They provided a numeric even though no data existed; treat as mismatch
                        all_match = False
                        break
            if all_match:
                agg_ok = True
    if agg_ok:
        scores["summary_aggregates_match_merged"] = 1.0

    # 8) status.json structure and content
    status_obj = _load_json_safe(status_json)
    status_ok = False
    if isinstance(status_obj, dict):
        required_inds = ["SP.POP.TOTL", "NY.GDP.PCAP.CD"]
        have_all = all(k in status_obj for k in required_inds)
        if have_all:
            all_good = True
            for ind in required_inds:
                entry = status_obj.get(ind)
                if not isinstance(entry, dict):
                    all_good = False
                    break
                http_status = entry.get("http_status")
                ok_flag = entry.get("ok")
                economies = entry.get("economies")
                years = entry.get("years")
                if not isinstance(http_status, int):
                    all_good = False
                    break
                if not isinstance(ok_flag, bool):
                    all_good = False
                    break
                if not isinstance(economies, int):
                    all_good = False
                    break
                if not isinstance(years, dict):
                    all_good = False
                    break
                start = years.get("start")
                end = years.get("end")
                if start != 1980 or end != 2015:
                    all_good = False
                    break
                # Consistency: ok True implies 200, ok False implies not 200
                if ok_flag and http_status != 200:
                    all_good = False
                    break
                if (not ok_flag) and http_status == 200:
                    all_good = False
                    break
                # Economies count reasonable: between 0 and number of configured islands
                if code_to_name_region:
                    if economies < 0 or economies > len(code_to_name_region):
                        all_good = False
                        break
            if all_good:
                status_ok = True
    if status_ok:
        scores["status_json_structure_and_content"] = 1.0

    # 9) run_log markers
    log_text = _read_text_safe(run_log)
    if log_text is not None:
        lower = log_text.lower()
        has_domain = ("api.worldbank.org" in lower) or ("worldbank" in lower)
        has_pop = "sp.pop.totl" in lower
        has_gdp = "ny.gdp.pcap.cd" in lower
        has_status = bool(re.search(r"\b[1-5]\d{2}\b", log_text)) or ("http" in lower) or ("status" in lower) or ("retry" in lower)
        if has_domain and has_pop and has_gdp and has_status:
            scores["run_log_contains_expected_markers"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()