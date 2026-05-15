import json
import csv
import hashlib
import sys
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import unicodedata


def read_text_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        try:
            return p.read_text(encoding="latin-1")
        except Exception:
            return None


def load_json_safe(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_csv_rows(p: Path):
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = [h.strip() for h in rows[0]]
        data_rows = []
        for r in rows[1:]:
            if len(r) == 0 or all((c is None or str(c).strip() == "") for c in r):
                continue
            # pad shorter rows
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            data_rows.append({header[i]: r[i] if i < len(r) else "" for i in range(len(header))})
        return header, data_rows
    except Exception:
        return None, None


def compute_sha256(p: Path) -> str:
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def normalize_country_name(name: str) -> str:
    if name is None:
        return ""
    # strip accents and punctuation varieties, lower case, collapse spaces
    nk = unicodedata.normalize("NFKD", name)
    nk = "".join(ch for ch in nk if not unicodedata.combining(ch))
    nk = nk.replace("’", "'").replace("`", "'")
    nk = nk.lower().strip()
    nk = re.sub(r"\s+", " ", nk)
    return nk


def parse_float_maybe(s):
    if s is None:
        return None
    ss = str(s).strip()
    if ss == "" or ss.lower() == "na" or ss.lower() == "null":
        return None
    try:
        return float(ss)
    except Exception:
        # sometimes CSV uses commas as thousand separators or decimal commas
        if "," in ss and ss.count(",") == 1 and "." not in ss:
            try:
                return float(ss.replace(",", "."))
            except Exception:
                return None
        try:
            return float(ss.replace(",", ""))
        except Exception:
            return None


def extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return ""


def is_worldbank_domain(domain: str) -> bool:
    domain = domain.lower()
    return domain.endswith("worldbank.org")


def get_worldbank_series_from_csv(csv_path: Path, target_countries: list, years: list) -> dict:
    # Returns mapping normalized_country_name -> {year: value or None}
    series = {}
    header, rows = load_csv_rows(csv_path)
    if not header or not rows:
        return series
    # Determine year columns existing
    year_cols = [str(y) for y in years if str(y) in header]
    # The row should be per country; pick the row whose "Country Name" matches
    # Robustly infer country name column
    cname_candidates = [c for c in header if normalize_country_name(c) in ("country name", "country_name")]
    cname_col = cname_candidates[0] if cname_candidates else "Country Name"
    # Fallback: if not present, try first column
    if cname_col not in header:
        cname_col = header[0]
    # Build mapping for target countries
    target_norms = {normalize_country_name(c): c for c in target_countries}
    for row in rows:
        cname = row.get(cname_col, "")
        norm = normalize_country_name(cname)
        # Allow normalization for Cote d'Ivoire vs Côte d'Ivoire
        if norm in target_norms or any(
            norm == normalize_country_name(alt) for alt in target_countries
        ):
            vals = {}
            for yc in year_cols:
                vals[int(yc)] = parse_float_maybe(row.get(yc))
            series[norm] = vals
    return series


def read_processed_dataset(csv_path: Path):
    header, rows = load_csv_rows(csv_path)
    if not header or not rows:
        return None, None
    # Convert rows ensuring 'year' as int and other fields parsed
    parsed = []
    for r in rows:
        try:
            year = int(str(r.get("year", "")).strip())
        except Exception:
            year = None
        u5 = parse_float_maybe(r.get("ghana_under5_mortality_per_1000"))
        le = parse_float_maybe(r.get("ghana_life_expectancy_years"))
        navg = parse_float_maybe(r.get("neighbors_under5_mortality_avg_per_1000"))
        parsed.append({"year": year, "ghana_u5": u5, "ghana_le": le, "neighbors_u5_avg": navg})
    return header, parsed


def calculate_neighbor_average(series_map: dict, neighbor_names: list, year: int) -> float:
    vals = []
    for n in neighbor_names:
        norm = normalize_country_name(n)
        # Find matching key in series_map
        key = None
        for k in series_map.keys():
            if k == norm:
                key = k
                break
            # Accept close match if names differ slightly
            if normalize_country_name(k) == norm:
                key = k
                break
        if key and series_map.get(key):
            v = series_map[key].get(year)
            if v is not None:
                vals.append(v)
    if len(vals) == 0:
        return None
    return sum(vals) / len(vals)


def approx_equal(a, b, tol=1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def find_summary_entries(summary_obj):
    # Returns a list of tuples (name, entry_dict) where entry_dict has keys value_2010,value_2022,absolute_change,pct_change
    entries = []
    if isinstance(summary_obj, dict):
        # If dict values are dicts, use keys as names
        for k, v in summary_obj.items():
            if isinstance(v, dict):
                keys = set(v.keys())
                if {"value_2010", "value_2022", "absolute_change", "pct_change"}.issubset(keys):
                    entries.append((str(k), v))
            # Some patterns may be nested
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        keys = set(item.keys())
                        if {"value_2010", "value_2022", "absolute_change", "pct_change"}.issubset(keys):
                            name = item.get("indicator") or k
                            entries.append((str(name), item))
    elif isinstance(summary_obj, list):
        for item in summary_obj:
            if isinstance(item, dict):
                keys = set(item.keys())
                if {"value_2010", "value_2022", "absolute_change", "pct_change"}.issubset(keys):
                    name = item.get("indicator") or item.get("name") or "indicator"
                    entries.append((str(name), item))
    return entries


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "provenance_and_raw_files": 0.0,
        "sources_json_completeness": 0.0,
        "ghana_health_trends_structure": 0.0,
        "ghana_health_trends_values_match_raw": 0.0,
        "summary_json_correctness": 0.0,
        "report_content_quality": 0.0,
        "validation_outputs_present_and_passed": 0.0,
    }

    # Constants derived from the explicit task
    years = list(range(2010, 2023))
    expected_row_count = len(years)  # 13
    required_columns = [
        "year",
        "ghana_under5_mortality_per_1000",
        "ghana_life_expectancy_years",
        "neighbors_under5_mortality_avg_per_1000",
    ]
    ghana_name = "Ghana"
    neighbors = ["Cote d'Ivoire", "Togo"]
    under5_title = "Mortality rate, under-5 (per 1,000 live births)"
    lifeexp_title = "Life expectancy at birth, total (years)"

    # Paths
    u5_raw = workspace / "data" / "raw" / "under5_mortality.csv"
    le_raw = workspace / "data" / "raw" / "life_expectancy.csv"
    processed_csv = workspace / "output" / "ghana_health_trends.csv"
    summary_json = workspace / "output" / "summary.json"
    report_md = workspace / "output" / "report.md"
    sources_json = workspace / "output" / "sources.json"
    validation_results = workspace / "output" / "validation_results.json"
    validation_log = workspace / "output" / "validation.log"

    # Check provenance and raw files
    prov_score_parts = []
    src_obj = load_json_safe(sources_json)
    if u5_raw.exists() and u5_raw.is_file() and le_raw.exists() and le_raw.is_file() and src_obj is not None:
        # Determine entries in sources.json
        entries = []
        if isinstance(src_obj, list):
            entries = src_obj
        elif isinstance(src_obj, dict):
            # Could be keyed by indicator
            for v in src_obj.values():
                if isinstance(v, dict):
                    entries.append(v)
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            entries.append(item)
        # Locate entries for each local file path
        def match_entry_for(rel_path: str):
            candidates = []
            for e in entries:
                lfp = e.get("local_file_path")
                if not isinstance(lfp, str):
                    continue
                # Normalize comparisons
                lfp_norm = lfp.replace("\\", "/").strip().lstrip("./")
                if lfp_norm.endswith(rel_path):
                    candidates.append(e)
            return candidates[0] if candidates else None

        u5_entry = match_entry_for("data/raw/under5_mortality.csv")
        le_entry = match_entry_for("data/raw/life_expectancy.csv")

        # For each, verify sha256 and domain
        for file_path, entry, title in [
            (u5_raw, u5_entry, under5_title),
            (le_raw, le_entry, lifeexp_title),
        ]:
            part_checks = 0
            part_total = 6  # sha256, domain matches URL, worldbank domain, organization, indicator_title, non-empty source_page_title
            if entry is not None:
                sha_actual = compute_sha256(file_path)
                sha_recorded = entry.get("file_sha256")
                if sha_actual is not None and isinstance(sha_recorded, str) and sha_actual.lower() == sha_recorded.lower():
                    part_checks += 1
                dl_url = entry.get("download_url") or ""
                dl_domain_recorded = (entry.get("download_url_domain") or "").lower()
                parsed_domain = extract_domain(dl_url)
                if dl_domain_recorded == parsed_domain and dl_domain_recorded != "":
                    part_checks += 1
                if is_worldbank_domain(dl_domain_recorded):
                    part_checks += 1
                if (entry.get("organization") or "").strip() == "World Bank Open Data":
                    part_checks += 1
                if (entry.get("indicator_title") or "").strip() == title:
                    part_checks += 1
                if isinstance(entry.get("source_page_title"), str) and entry.get("source_page_title").strip() != "":
                    part_checks += 1
            prov_score_parts.append(part_checks / part_total if part_total > 0 else 0.0)
        if prov_score_parts:
            scores["provenance_and_raw_files"] = sum(prov_score_parts) / len(prov_score_parts)
    else:
        scores["provenance_and_raw_files"] = 0.0

    # sources_json_completeness: fields presence and plausibility
    if src_obj is not None and isinstance(src_obj, (list, dict)):
        entries = src_obj if isinstance(src_obj, list) else list(src_obj.values())
        # Flatten
        flat = []
        for e in entries:
            if isinstance(e, dict):
                flat.append(e)
            elif isinstance(e, list):
                for x in e:
                    if isinstance(x, dict):
                        flat.append(x)
        total_fields = 0
        ok_fields = 0
        needed_fields = [
            "organization",
            "indicator_title",
            "source_page_title",
            "download_url",
            "download_url_domain",
            "local_file_path",
            "file_sha256",
            "downloaded_at_iso",
            "search_queries_used",
        ]
        for e in flat:
            # Only count entries that reference expected local files
            lfp = str(e.get("local_file_path", ""))
            if not (lfp.replace("\\", "/").endswith("data/raw/under5_mortality.csv") or lfp.replace("\\", "/").endswith("data/raw/life_expectancy.csv")):
                continue
            for field in needed_fields:
                total_fields += 1
                val = e.get(field, None)
                good = False
                if field == "search_queries_used":
                    good = isinstance(val, list) and len(val) >= 1 and all(isinstance(q, str) for q in val)
                elif field == "downloaded_at_iso":
                    if isinstance(val, str):
                        # basic ISO-like check
                        good = bool(re.match(r"^\d{4}-\d{2}-\d{2}T", val))
                elif field == "download_url":
                    good = isinstance(val, str) and val.strip().startswith("http")
                else:
                    good = isinstance(val, str) and val.strip() != ""
                if good:
                    ok_fields += 1
        if total_fields > 0:
            scores["sources_json_completeness"] = ok_fields / total_fields
        else:
            scores["sources_json_completeness"] = 0.0
    else:
        scores["sources_json_completeness"] = 0.0

    # Processed dataset structure
    structure_checks = 0
    structure_total = 4  # header order, row count, year coverage/uniqueness, ascending order
    header, parsed_rows = read_processed_dataset(processed_csv) if processed_csv.exists() else (None, None)
    if header:
        if header == required_columns:
            structure_checks += 1
        if parsed_rows is not None:
            if len(parsed_rows) == expected_row_count:
                structure_checks += 1
            # year coverage and uniqueness
            years_in_file = [r.get("year") for r in parsed_rows if isinstance(r.get("year"), int)]
            if set(years_in_file) == set(years) and len(years_in_file) == expected_row_count:
                structure_checks += 1
            # ascending order
            if [r.get("year") for r in parsed_rows] == years:
                structure_checks += 1
    scores["ghana_health_trends_structure"] = structure_checks / structure_total if structure_total > 0 else 0.0

    # Values consistent with raw CSVs
    if u5_raw.exists() and le_raw.exists() and header and parsed_rows:
        # Build Ghana series and neighbors from raw U5
        countries_needed = [ghana_name] + neighbors
        u5_series_map = get_worldbank_series_from_csv(u5_raw, countries_needed, years)
        ghana_norm = normalize_country_name(ghana_name)
        ghana_u5_series = u5_series_map.get(ghana_norm, {})
        # Life expectancy series Ghana
        le_series_map = get_worldbank_series_from_csv(le_raw, [ghana_name], years)
        ghana_le_series = le_series_map.get(ghana_norm, {})

        total_cells = 0
        matched = 0
        for y in years:
            # Ghana U5
            exp_u5 = ghana_u5_series.get(y)
            obs_u5 = next((r["ghana_u5"] for r in parsed_rows if r["year"] == y), None)
            total_cells += 1
            if approx_equal(exp_u5, obs_u5, tol=1e-6):
                matched += 1
            # Ghana LE
            exp_le = ghana_le_series.get(y)
            obs_le = next((r["ghana_le"] for r in parsed_rows if r["year"] == y), None)
            total_cells += 1
            if approx_equal(exp_le, obs_le, tol=1e-6):
                matched += 1
            # Neighbor avg U5
            exp_nav = calculate_neighbor_average(u5_series_map, neighbors, y)
            obs_nav = next((r["neighbors_u5_avg"] for r in parsed_rows if r["year"] == y), None)
            total_cells += 1
            if approx_equal(exp_nav, obs_nav, tol=1e-6):
                matched += 1
        scores["ghana_health_trends_values_match_raw"] = (matched / total_cells) if total_cells > 0 else 0.0
    else:
        scores["ghana_health_trends_values_match_raw"] = 0.0

    # Summary JSON correctness
    if summary_json.exists() and header and parsed_rows:
        summary_obj = load_json_safe(summary_json)
        if summary_obj is not None:
            entries = find_summary_entries(summary_obj)
            # Compute expected values from processed dataset
            def get_value_for_year(col_key: str, year: int):
                for r in parsed_rows:
                    if r["year"] == year:
                        if col_key == "u5":
                            return r["ghana_u5"]
                        if col_key == "le":
                            return r["ghana_le"]
                return None

            exp_u5_2010 = get_value_for_year("u5", 2010)
            exp_u5_2022 = get_value_for_year("u5", 2022)
            exp_le_2010 = get_value_for_year("le", 2010)
            exp_le_2022 = get_value_for_year("le", 2022)
            # Assign entries corresponding to indicators
            u5_entry = None
            le_entry = None
            for name, ent in entries:
                nm = name.lower()
                # Also check indicator_title field inside ent if present
                indicator_name = (ent.get("indicator") or ent.get("name") or name).lower()
                if ("mortality" in nm or "under" in nm) or ("mortality" in indicator_name or "under" in indicator_name):
                    u5_entry = ent
                if ("life" in nm and "expect" in nm) or ("life" in indicator_name and "expect" in indicator_name):
                    le_entry = ent
            # If ambiguous, try by presence of magnitude (u5 values typically > 10, LE around 60)
            if u5_entry is None or le_entry is None:
                for name, ent in entries:
                    v2010 = parse_float_maybe(ent.get("value_2010"))
                    if v2010 is not None:
                        if v2010 > 10 and u5_entry is None:
                            u5_entry = ent
                        elif v2010 < 15 and le_entry is None:
                            le_entry = ent
            total_checks = 0
            ok_checks = 0

            def check_entry(ent, v2010, v2022):
                nonlocal total_checks, ok_checks
                # value_2010
                total_checks += 1
                if (v2010 is None and ent.get("value_2010") is None) or approx_equal(parse_float_maybe(ent.get("value_2010")), v2010, tol=1e-6):
                    ok_checks += 1
                # value_2022
                total_checks += 1
                if (v2022 is None and ent.get("value_2022") is None) or approx_equal(parse_float_maybe(ent.get("value_2022")), v2022, tol=1e-6):
                    ok_checks += 1
                # absolute_change
                total_checks += 1
                exp_abs = None if (v2010 is None or v2022 is None) else (v2022 - v2010)
                if (exp_abs is None and ent.get("absolute_change") is None) or approx_equal(parse_float_maybe(ent.get("absolute_change")), exp_abs, tol=1e-6):
                    ok_checks += 1
                # pct_change
                total_checks += 1
                exp_pct = None
                if v2010 is not None and v2022 is not None and v2010 != 0:
                    exp_pct = (v2022 - v2010) / v2010 * 100.0
                if (exp_pct is None and ent.get("pct_change") is None) or approx_equal(parse_float_maybe(ent.get("pct_change")), exp_pct, tol=1e-2):
                    ok_checks += 1

            if u5_entry is not None:
                check_entry(u5_entry, exp_u5_2010, exp_u5_2022)
            if le_entry is not None:
                check_entry(le_entry, exp_le_2010, exp_le_2022)
            if total_checks > 0:
                scores["summary_json_correctness"] = ok_checks / total_checks
            else:
                scores["summary_json_correctness"] = 0.0
        else:
            scores["summary_json_correctness"] = 0.0
    else:
        scores["summary_json_correctness"] = 0.0

    # Report content quality
    report_checks = 0
    report_total = 6  # existence, mentions Ghana+World Bank, mentions 2010 and 2022, bullets count 2-3, mentions both indicators
    if report_md.exists():
        txt = read_text_safe(report_md) or ""
        if txt.strip() != "":
            report_checks += 1  # existence
        # Mentions Ghana and World Bank
        if ("ghana" in txt.lower()) and ("world bank" in txt.lower()):
            report_checks += 1
        # Mentions years
        if ("2010" in txt) and ("2022" in txt):
            report_checks += 1
        # Bullet points 2-3
        bullet_lines = [ln for ln in txt.splitlines() if re.match(r"^\s*[-*]\s+", ln)]
        if 2 <= len(bullet_lines) <= 3:
            report_checks += 1
        # Mentions under-5 mortality
        if ("under-5" in txt.lower()) or ("under 5" in txt.lower()) or ("mortality" in txt.lower()):
            report_checks += 1
        # Mentions life expectancy
        if "life expectancy" in txt.lower():
            report_checks += 1
    scores["report_content_quality"] = report_checks / report_total if report_total > 0 else 0.0

    # Validation outputs present and passed
    val_score = 0.0
    if validation_results.exists() and validation_log.exists():
        vobj = load_json_safe(validation_results)
        vlog = read_text_safe(validation_log) or ""
        if isinstance(vobj, dict):
            checks_list = None
            if isinstance(vobj.get("checks"), list):
                checks_list = vobj.get("checks")
            elif isinstance(vobj.get("results"), list):
                checks_list = vobj.get("results")
            # build name->passed mapping (normalize names)
            passed_map = {}
            if checks_list is not None:
                for c in checks_list:
                    if isinstance(c, dict):
                        name = str(c.get("name") or c.get("check") or "").lower()
                        passed = c.get("passed")
                        if isinstance(passed, bool) or passed in (0, 1, True, False, "true", "false", "pass", "fail", "PASS", "FAIL"):
                            is_pass = bool(passed) if isinstance(passed, bool) else str(passed).lower() in ("true", "pass", "1")
                            passed_map[name] = is_pass
            # Required check tokens
            required_tokens = {
                "expected_rows": False,
                "required_columns": False,
                "year": False,  # year range coverage
                "non_null": False,  # minimum non-null ratio
            }
            # Identify presence and pass
            all_present_and_pass = True
            for token in required_tokens.keys():
                # Find any check name containing this token
                found = False
                passed = False
                for name, ok in passed_map.items():
                    if token in name.replace(" ", "_"):
                        found = True
                        passed = ok
                        break
                if not found or not passed:
                    all_present_and_pass = False
            # timestamp presence
            ts_ok = isinstance(vobj.get("timestamp"), str) and re.match(r"^\d{4}-\d{2}-\d{2}T", vobj.get("timestamp")) is not None
            # log mentions pass/fail per check
            log_ok = True
            for token in ["expected", "column", "year", "null"]:
                if token not in vlog.lower():
                    log_ok = False
            if all_present_and_pass and ts_ok and log_ok:
                val_score = 1.0
    scores["validation_outputs_present_and_passed"] = val_score

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip() != "":
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()