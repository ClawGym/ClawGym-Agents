import csv
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


def _read_csv_dicts(path: Path) -> Tuple[List[Dict[str, str]], Optional[str], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows, None, reader.fieldnames if reader.fieldnames is not None else []
    except Exception as e:
        return [], str(e), None


def _safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _parse_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s == "" or s.lower() in {"na", "n/a", "null"}:
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return None


def _years_from_headers(headers: List[str]) -> List[int]:
    years = []
    for h in headers:
        hs = h.strip()
        if hs.isdigit():
            try:
                years.append(int(hs))
            except Exception:
                pass
    years.sort()
    return years


def _parse_worldbank_indicator_csv(path: Path) -> Tuple[Dict[str, float], Optional[str]]:
    rows, err, headers = _read_csv_dicts(path)
    if err or headers is None:
        return {}, err or "Failed to read headers"

    country_code_field = None
    for cand in ["country code", "country_code", "countrycode", "Country Code"]:
        for h in headers:
            if h.lower() == cand.lower():
                country_code_field = h
                break
        if country_code_field:
            break
    if not country_code_field:
        for h in headers:
            if h.lower().replace(" ", "") == "countrycode":
                country_code_field = h
                break

    values: Dict[str, float] = {}

    has_year_col = any(h.lower() == "year" for h in headers) or any(h.lower() == "time" for h in headers)
    has_value_col = any(h.lower() == "value" for h in headers)

    if has_year_col and has_value_col and country_code_field:
        year_field = None
        value_field = None
        for h in headers:
            if h.lower() == "year" or h.lower() == "time":
                year_field = h
            if h.lower() == "value":
                value_field = h
        if not year_field or not value_field:
            return {}, "Missing year/value columns"
        by_country: Dict[str, List[Tuple[int, float]]] = {}
        for row in rows:
            cc = row.get(country_code_field, "").strip()
            if not cc:
                continue
            y = _parse_float(row.get(year_field))
            v = _parse_float(row.get(value_field))
            if y is None or v is None:
                continue
            yi = int(round(y))
            by_country.setdefault(cc, []).append((yi, v))
        for cc, items in by_country.items():
            items.sort(key=lambda t: t[0], reverse=True)
            for yi, v in items:
                if v is not None:
                    values[cc] = v
                    break
        return values, None

    years = _years_from_headers(headers)
    if years and country_code_field:
        years_sorted_desc = sorted(years, reverse=True)
        for row in rows:
            cc = row.get(country_code_field, "").strip()
            if not cc:
                continue
            for y in years_sorted_desc:
                val = row.get(str(y))
                fv = _parse_float(val)
                if fv is not None:
                    values[cc] = fv
                    break
        return values, None

    if not country_code_field and years:
        return {}, "Country Code column not found"

    return {}, "Unrecognized CSV structure"


def _load_candidates(workspace: Path) -> Tuple[List[str], Optional[str]]:
    candidates_path = workspace / "input" / "markets.csv"
    rows, err, headers = _read_csv_dicts(candidates_path)
    if err:
        return [], err
    header_lc = [h.lower() for h in (headers or [])]
    if "country_code" not in header_lc:
        return [], "Header missing country_code"
    idx = header_lc.index("country_code")
    header_name = (headers or [])[idx]
    codes = []
    for r in rows:
        code = (r.get(header_name) or "").strip()
        if code:
            codes.append(code)
    return codes, None


def _parse_market_priorities(workspace: Path) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[List[str]]]:
    out_path = workspace / "outputs" / "market_priorities.csv"
    rows, err, headers = _read_csv_dicts(out_path)
    if err:
        return [], err, None
    expected_headers = [
        "country_code",
        "population",
        "internet_users_percent",
        "internet_users_estimate",
        "ux_reach_score",
        "tier",
    ]
    if headers is None or headers != expected_headers:
        return [], "Header mismatch", headers
    parsed_rows: List[Dict[str, Any]] = []
    for r in rows:
        code = (r.get("country_code") or "").strip()
        pop = _parse_float(r.get("population"))
        pct = _parse_float(r.get("internet_users_percent"))
        est = _parse_float(r.get("internet_users_estimate"))
        score = _parse_float(r.get("ux_reach_score"))
        tier = (r.get("tier") or "").strip()
        if not code or pop is None or pct is None or est is None or score is None or not tier:
            return [], "Row with missing/invalid values", headers
        parsed_rows.append(
            {
                "country_code": code,
                "population": pop,
                "internet_users_percent": pct,
                "internet_users_estimate": est,
                "ux_reach_score": score,
                "tier": tier,
            }
        )
    return parsed_rows, None, headers


def _parse_missing_data(workspace: Path) -> Tuple[List[Dict[str, str]], Optional[str]]:
    path = workspace / "outputs" / "missing_data.csv"
    rows, err, headers = _read_csv_dicts(path)
    if err:
        return [], err
    if headers is None:
        return [], "Missing headers"
    header_lc = [h.lower() for h in headers]
    if "country_code" not in header_lc or "reason" not in header_lc:
        return [], "Headers must include country_code and reason"
    cc_name = headers[header_lc.index("country_code")]
    reason_name = headers[header_lc.index("reason")]
    out = []
    for r in rows:
        code = (r.get(cc_name) or "").strip()
        reason = (r.get(reason_name) or "").strip()
        if code and reason:
            out.append({"country_code": code, "reason": reason})
        else:
            return [], "Missing values in missing_data.csv"
    return out, None


def _compute_estimate(pop: float, pct: float) -> float:
    return pop * pct / 100.0


def _compute_score(pop: float, est: float) -> float:
    return 0.7 * est + 0.3 * pop


def _is_sorted_desc(values: List[float]) -> bool:
    return all(values[i] >= values[i + 1] for i in range(len(values) - 1))


def _tiers_contiguous(rows: List[Dict[str, Any]]) -> bool:
    order_map = {"Tier 1": 1, "Tier 2": 2, "Tier 3": 3}
    last = 0
    for r in rows:
        t = r["tier"]
        if t not in order_map:
            return False
        val = order_map[t]
        if val < last:
            return False
        last = val
    return all(t in order_map for t in [r["tier"] for r in rows])


def _tiers_proportion_ok(rows: List[Dict[str, Any]]) -> bool:
    n = len(rows)
    if n == 0:
        return False
    counts = {"Tier 1": 0, "Tier 2": 0, "Tier 3": 0}
    for r in rows:
        if r["tier"] in counts:
            counts[r["tier"]] += 1
        else:
            return False
    t1_expected_low = math.floor(0.2 * n)
    t1_expected_high = math.ceil(0.2 * n)
    t2_expected_low = math.floor(0.3 * n)
    t2_expected_high = math.ceil(0.3 * n)
    t1_ok = t1_expected_low <= counts["Tier 1"] <= t1_expected_high
    t2_ok = t2_expected_low <= counts["Tier 2"] <= t2_expected_high
    t3_ok = counts["Tier 1"] + counts["Tier 2"] + counts["Tier 3"] == n
    return t1_ok and t2_ok and t3_ok


def _alpha2_to_alpha3_map() -> Dict[str, str]:
    return {
        "US": "USA",
        "IN": "IND",
        "BR": "BRA",
        "DE": "DEU",
        "JP": "JPN",
        "NG": "NGA",
        "ID": "IDN",
        "GB": "GBR",
        "FR": "FRA",
        "MX": "MEX",
    }


def _compute_expected_from_downloads(workspace: Path, candidates_alpha2: List[str]) -> Tuple[Dict[str, Dict[str, float]], Dict[str, str], Optional[str]]:
    pop_path = workspace / "downloads" / "population.csv"
    net_path = workspace / "downloads" / "internet_users_percent.csv"
    pop_map, pop_err = _parse_worldbank_indicator_csv(pop_path)
    net_map, net_err = _parse_worldbank_indicator_csv(net_path)
    if pop_err or net_err:
        err = pop_err or net_err
        return {}, {}, err

    a2_to_a3 = _alpha2_to_alpha3_map()
    expected: Dict[str, Dict[str, float]] = {}
    missing: Dict[str, str] = {}
    for a2 in candidates_alpha2:
        a3 = a2_to_a3.get(a2)
        if not a3:
            missing[a2] = "missing country code mapping"
            continue
        pop = pop_map.get(a3)
        pct = net_map.get(a3)
        if pop is None and pct is None:
            missing[a2] = "missing population and internet_users_percent"
        elif pop is None:
            missing[a2] = "missing population"
        elif pct is None:
            missing[a2] = "missing internet_users_percent"
        else:
            expected[a2] = {"population": float(pop), "internet_users_percent": float(pct)}
    return expected, missing, None


def _float_equal(a: float, b: float, rel: float = 1e-9, abs_tol: float = 1e-6) -> bool:
    return abs(a - b) <= max(rel * max(abs(a), abs(b)), abs_tol)


def _normalize_lines(text: str) -> List[str]:
    return [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]


ORIGINAL_LOCALIZATION_PLAN_MD = """# Global Onboarding Localization Plan

## Background
Our product has growing usage across multiple regions. To ensure equitable access and a smooth onboarding experience, we plan to prioritize markets for localized onboarding.

## Localization priorities
Placeholder: This section will be updated with a ranked list of target markets based on a data-driven reach score.

## Research timeline
- Week 1–2: Data collection and prioritization
- Week 3–4: Content audits, translation scoping
- Week 5+: Pilot rollout in top-tier markets

## Accessibility considerations
We will apply WCAG 2.2 AA standards, ensure readable typography across scripts, and validate contrast for localized palettes.
"""


def _split_sections(md_text: str) -> Tuple[str, Dict[str, List[str]]]:
    lines = _normalize_lines(md_text)
    h1 = ""
    sections: Dict[str, List[str]] = {}
    current_section = None
    current_content: List[str] = []
    for i, line in enumerate(lines):
        if i == 0 and line.startswith("# "):
            h1 = line
            continue
        if line.startswith("## "):
            if current_section is not None:
                sections[current_section] = current_content
            current_section = line[len("## "):].strip()
            current_content = []
        else:
            if current_section is not None:
                current_content.append(line)
    if current_section is not None:
        sections[current_section] = current_content
    return h1, sections


def _contains_justification_sentence(section_lines: List[str]) -> bool:
    pattern_data = re.compile(r"\bdata\b|\bdata-driven\b", re.IGNORECASE)
    pattern_tz = re.compile(r"\btime\s*zones?\b|\btimezones?\b", re.IGNORECASE)
    for line in section_lines:
        if pattern_data.search(line) and pattern_tz.search(line):
            return True
    return False


def _extract_bullets(section_lines: List[str]) -> List[str]:
    bullets = []
    for line in section_lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullets.append(stripped)
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "downloads_population_csv_present": 0.0,
        "downloads_internet_csv_present": 0.0,
        "outputs_market_priorities_structure": 0.0,
        "candidate_countries_only": 0.0,
        "outputs_market_priorities_sorted_desc": 0.0,
        "calculated_columns_correct": 0.0,
        "tiers_contiguous_order": 0.0,
        "tiers_proportion_approx": 0.0,
        "recomputed_values_match_downloads": 0.0,
        "missing_data_csv_valid": 0.0,
        "summary_json_structure_valid": 0.0,
        "summary_counts_consistent": 0.0,
        "localization_plan_section_updated": 0.0,
        "localization_plan_top10_matches_outputs": 0.0,
        "localization_plan_justification_sentence": 0.0,
    }

    pop_csv = workspace / "downloads" / "population.csv"
    net_csv = workspace / "downloads" / "internet_users_percent.csv"
    if pop_csv.exists() and pop_csv.is_file():
        pop_map, pop_err = _parse_worldbank_indicator_csv(pop_csv)
        if not pop_err and isinstance(pop_map, dict):
            scores["downloads_population_csv_present"] = 1.0
    if net_csv.exists() and net_csv.is_file():
        net_map, net_err = _parse_worldbank_indicator_csv(net_csv)
        if not net_err and isinstance(net_map, dict):
            scores["downloads_internet_csv_present"] = 1.0

    candidates, candidates_err = _load_candidates(workspace)
    out_rows, out_err, out_headers = _parse_market_priorities(workspace)
    if not out_err:
        scores["outputs_market_priorities_structure"] = 1.0

    if not out_err and not candidates_err:
        out_codes = [r["country_code"] for r in out_rows]
        if all(code in set(candidates) for code in out_codes):
            scores["candidate_countries_only"] = 1.0

    if not out_err:
        scores_list = [r["ux_reach_score"] for r in out_rows]
        if _is_sorted_desc(scores_list):
            scores["outputs_market_priorities_sorted_desc"] = 1.0

    if not out_err:
        ok = True
        for r in out_rows:
            pop = r["population"]
            pct = r["internet_users_percent"]
            est = r["internet_users_estimate"]
            score_val = r["ux_reach_score"]
            est_calc = _compute_estimate(pop, pct)
            score_calc = _compute_score(pop, est_calc)
            if not (_float_equal(est, est_calc) and _float_equal(score_val, score_calc)):
                ok = False
                break
        if ok:
            scores["calculated_columns_correct"] = 1.0

    if not out_err:
        if _tiers_contiguous(out_rows):
            scores["tiers_contiguous_order"] = 1.0
        if _tiers_proportion_ok(out_rows):
            scores["tiers_proportion_approx"] = 1.0

    if scores["downloads_population_csv_present"] == 1.0 and scores["downloads_internet_csv_present"] == 1.0 and not out_err and not candidates_err:
        expected_values, missing_map, exp_err = _compute_expected_from_downloads(workspace, candidates)
        if not exp_err:
            ok = True
            for r in out_rows:
                code = r["country_code"]
                if code not in expected_values:
                    ok = False
                    break
                exp_pop = expected_values[code]["population"]
                exp_pct = expected_values[code]["internet_users_percent"]
                if not (_float_equal(r["population"], exp_pop) and _float_equal(r["internet_users_percent"], exp_pct)):
                    ok = False
                    break
            if ok:
                scores["recomputed_values_match_downloads"] = 1.0

    missing_rows, missing_err = _parse_missing_data(workspace)
    if not missing_err:
        valid = True
        if not candidates_err:
            cand_set = set(candidates)
            if any(r["country_code"] not in cand_set for r in missing_rows):
                valid = False
        if not out_err:
            out_set = set(r["country_code"] for r in out_rows)
            if any(r["country_code"] in out_set for r in missing_rows):
                valid = False
        if valid:
            scores["missing_data_csv_valid"] = 1.0

    summary_path = workspace / "outputs" / "summary.json"
    summary, summary_err = _safe_load_json(summary_path)
    if not summary_err and isinstance(summary, dict):
        ds = summary.get("data_sources")
        cc = summary.get("candidates_count")
        mc = summary.get("missing_count")
        ds_ok = isinstance(ds, list) and len(ds) == 2
        ids_expected = {"SP.POP.TOTL": "Total population", "IT.NET.USER.ZS": "Individuals using the Internet (% of population)"}
        sources_ok = True
        if ds_ok:
            found_ids = set()
            for item in ds:
                if not isinstance(item, dict):
                    sources_ok = False
                    break
                if item.get("source") != "The World Bank Open Data":
                    sources_ok = False
                    break
                ind_id = item.get("indicator_id")
                title = item.get("title")
                access_date = item.get("access_date")
                if ind_id not in ids_expected:
                    sources_ok = False
                    break
                if ids_expected[ind_id] not in title:
                    sources_ok = False
                    break
                try:
                    datetime.strptime(access_date, "%Y-%m-%d")
                except Exception:
                    sources_ok = False
                    break
                found_ids.add(ind_id)
            if found_ids != set(ids_expected.keys()):
                sources_ok = False
        else:
            sources_ok = False
        counts_ok = isinstance(cc, int) and isinstance(mc, int) and cc >= 0 and mc >= 0
        if sources_ok and counts_ok:
            scores["summary_json_structure_valid"] = 1.0

    if scores["summary_json_structure_valid"] == 1.0:
        processed_count = len(out_rows) if not out_err else None
        missing_count = len(missing_rows) if not missing_err else None
        candidates_list, candidates_list_err = _load_candidates(workspace)
        total_candidates = len(candidates_list) if not candidates_list_err else None
        summary, _ = _safe_load_json(workspace / "outputs" / "summary.json")
        if processed_count is not None and missing_count is not None and total_candidates is not None and isinstance(summary, dict):
            if (summary.get("candidates_count") == processed_count and
                summary.get("missing_count") == missing_count and
                processed_count + missing_count == total_candidates):
                scores["summary_counts_consistent"] = 1.0

    lp_path = workspace / "input" / "localization_plan.md"
    lp_text, lp_err = _safe_read_text(lp_path)
    if not lp_err and lp_text is not None:
        updated_h1, updated_sections = _split_sections(lp_text)
        orig_h1, orig_sections = _split_sections(ORIGINAL_LOCALIZATION_PLAN_MD)
        preserve_ok = updated_h1 == orig_h1
        for sec_name, content in orig_sections.items():
            if sec_name == "Localization priorities":
                continue
            updated_content = updated_sections.get(sec_name)
            if updated_content is None or updated_content != content:
                preserve_ok = False
                break
        loc_sec = updated_sections.get("Localization priorities")
        # Must be updated: contains bullet list and does not contain the placeholder text
        bullets = _extract_bullets(loc_sec or [])
        placeholder_present = any("Placeholder" in (line or "") for line in (loc_sec or []))
        section_updated_ok = preserve_ok and (len(bullets) >= 1) and (not placeholder_present)
        if section_updated_ok:
            scores["localization_plan_section_updated"] = 1.0

        if not out_err and loc_sec is not None and len(bullets) >= 1:
            top_n = min(10, len(out_rows))
            if len(bullets) >= top_n and top_n > 0:
                ok = True
                for i in range(top_n):
                    expected_code = out_rows[i]["country_code"]
                    expected_score = out_rows[i]["ux_reach_score"]
                    bullet = bullets[i]
                    if expected_code not in bullet:
                        ok = False
                        break
                    nums = re.findall(r"[-+]?\d*\.\d+|\d+", bullet)
                    if not nums:
                        ok = False
                        break
                    num_val = float(nums[0])
                    if abs(num_val - expected_score) > 0.5 and abs(num_val - round(expected_score)) > 0.5:
                        ok = False
                        break
                if ok:
                    scores["localization_plan_top10_matches_outputs"] = 1.0

        if loc_sec is not None:
            if _contains_justification_sentence(loc_sec):
                scores["localization_plan_justification_sentence"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()