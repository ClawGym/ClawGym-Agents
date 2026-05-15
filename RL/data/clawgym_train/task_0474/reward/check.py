import json
import csv
import sys
import os
import re
from pathlib import Path


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception:
        try:
            return path.read_text(encoding="utf-8-sig"), None
        except Exception as e2:
            return None, str(e2)


def _safe_load_jsonl(path: Path):
    try:
        records = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    return None
        return records
    except Exception:
        return None


def _parse_csv_strict(path: Path, expected_header: list):
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None
            header = [h.strip() for h in header]
            if header != expected_header:
                return None
            rows = []
            for row in reader:
                if not any(cell.strip() for cell in row):
                    continue
                if len(row) != len(expected_header):
                    return None
                row_dict = {expected_header[i]: row[i].strip() for i in range(len(expected_header))}
                rows.append(row_dict)
            return rows
    except Exception:
        return None


def _parse_geonames_countryinfo(path: Path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except Exception:
            return None
    header = None
    for line in lines:
        if line.startswith("#ISO"):
            header = line.lstrip("#").strip().split("\t")
            break
    if not header:
        for line in lines:
            if line.startswith("#") and "\t" in line:
                candidate = line.lstrip("#").strip().split("\t")
                if "ISO" in candidate and "Continent" in candidate:
                    header = candidate
                    break
    if not header or "ISO" not in header or "Continent" not in header:
        return None
    iso_idx = header.index("ISO")
    cont_idx = header.index("Continent")
    mapping = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) <= max(iso_idx, cont_idx):
            continue
        iso = parts[iso_idx].strip().upper()
        cont = parts[cont_idx].strip().upper()
        if iso and cont:
            mapping[iso] = cont
    if not mapping:
        return None
    return mapping


def _compute_expected_from_stories(stories):
    by_country = {}
    by_sector = {}
    years = []
    for rec in stories:
        cc = rec.get("country_code")
        sector = rec.get("sector")
        year = rec.get("award_year")
        if not isinstance(cc, str) or not isinstance(sector, str) or not isinstance(year, int):
            return None
        cc = cc.strip().upper()
        sector = sector.strip()
        by_country[cc] = by_country.get(cc, 0) + 1
        by_sector[sector] = by_sector.get(sector, 0) + 1
        years.append(year)
    if not years:
        return None
    min_year = min(years)
    max_year = max(years)
    total_profiles = len(stories)
    unique_countries = len(by_country)
    sorted_countries = sorted(by_country.items(), key=lambda kv: (-kv[1], kv[0]))
    top3 = sorted_countries[:3]
    return {
        "by_country": by_country,
        "by_sector": by_sector,
        "min_year": min_year,
        "max_year": max_year,
        "total_profiles": total_profiles,
        "unique_countries": unique_countries,
        "top3": top3,
    }


def _compute_expected_by_continent(stories, iso_to_cont):
    counts = {}
    for rec in stories:
        cc = rec.get("country_code")
        if not isinstance(cc, str):
            return None
        iso = cc.strip().upper()
        cont = iso_to_cont.get(iso)
        if not cont:
            return None
        counts[cont] = counts.get(cont, 0) + 1
    counts = {k: v for k, v in counts.items() if v > 0}
    return counts


def _csv_counts_map(rows, key_field, count_field):
    seen = set()
    result = {}
    for row in rows:
        if key_field not in row or count_field not in row:
            return None
        key = row[key_field].strip()
        if key in seen:
            return None
        seen.add(key)
        try:
            cnt = int(row[count_field])
        except Exception:
            return None
        if cnt < 0:
            return None
        result[key] = cnt
    return result


def _report_contains_overview(text: str, total: int, unique_countries: int, continents: int) -> bool:
    if re.search(r'\boverview\b', text, re.IGNORECASE) is None:
        return False
    patterns = [
        r'\b{}\b'.format(total),
        r'\b{}\b'.format(unique_countries),
        r'\b{}\b'.format(continents),
    ]
    for pat in patterns:
        if re.search(pat, text) is None:
            return False
    return True


def _report_contains_years_range(text: str, min_year: int, max_year: int) -> bool:
    for line in text.splitlines():
        if re.search(r'year', line, re.IGNORECASE):
            if str(min_year) in line and str(max_year) in line:
                return True
    return False


def _report_contains_top3(text: str, top3_codes_counts: list) -> bool:
    lines = text.splitlines()
    ok = True
    for code, cnt in top3_codes_counts:
        found = False
        pat_code = re.compile(r'\b{}\b'.format(re.escape(code)))
        pat_cnt = re.compile(r'\b{}\b'.format(cnt))
        for line in lines:
            if pat_code.search(line) and pat_cnt.search(line):
                found = True
                break
        if not found:
            ok = False
            break
    return ok


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "script_executable_or_shebang": 0.0,
        "script_supports_refresh_flag": 0.0,
        "country_reference_present": 0.0,
        "by_country_csv_valid": 0.0,
        "by_sector_csv_valid": 0.0,
        "by_continent_csv_valid": 0.0,
        "report_overview_stats_correct": 0.0,
        "report_years_range_correct": 0.0,
        "report_top3_countries_correct": 0.0,
        "build_log_contains_entries": 0.0,
    }

    script_path = workspace / "scripts" / "build_diaspora_report.sh"
    if script_path.exists() and script_path.is_file():
        scores["script_exists"] = 1.0
        text, _ = _safe_read_text(script_path)
        is_exec = os.access(str(script_path), os.X_OK)
        has_shebang = False
        if text:
            first_line = text.splitlines()[0] if text.splitlines() else ""
            if first_line.startswith("#!"):
                if "bash" in first_line or "sh" in first_line:
                    has_shebang = True
            if "--refresh" in text:
                scores["script_supports_refresh_flag"] = 1.0
        if is_exec or has_shebang:
            scores["script_executable_or_shebang"] = 1.0

    stories_path = workspace / "input" / "stories.jsonl"
    stories = _safe_load_jsonl(stories_path)
    expected = None
    if stories is not None:
        expected = _compute_expected_from_stories(stories)

    country_info_path = workspace / "data" / "countryInfo.txt"
    iso_to_cont = None
    if country_info_path.exists() and country_info_path.is_file():
        scores["country_reference_present"] = 1.0
        iso_to_cont = _parse_geonames_countryinfo(country_info_path)

    by_country_path = workspace / "outputs" / "summary" / "by_country.csv"
    if expected is not None and by_country_path.exists():
        rows = _parse_csv_strict(by_country_path, ["country_code", "count"])
        if rows is not None:
            got = _csv_counts_map(rows, "country_code", "count")
            if got is not None and got == expected["by_country"]:
                scores["by_country_csv_valid"] = 1.0

    by_sector_path = workspace / "outputs" / "summary" / "by_sector.csv"
    if expected is not None and by_sector_path.exists():
        rows = _parse_csv_strict(by_sector_path, ["sector", "count"])
        if rows is not None:
            got = _csv_counts_map(rows, "sector", "count")
            if got is not None and got == expected["by_sector"]:
                scores["by_sector_csv_valid"] = 1.0

    by_continent_path = workspace / "outputs" / "summary" / "by_continent.csv"
    if expected is not None and iso_to_cont is not None and by_continent_path.exists():
        rows = _parse_csv_strict(by_continent_path, ["continent_code", "count"])
        if rows is not None:
            got = _csv_counts_map(rows, "continent_code", "count")
            exp_cont = _compute_expected_by_continent(stories, iso_to_cont)
            if got is not None and exp_cont is not None and got == exp_cont:
                scores["by_continent_csv_valid"] = 1.0

    report_path = workspace / "outputs" / "report.md"
    if expected is not None and iso_to_cont is not None and report_path.exists():
        text, _ = _safe_read_text(report_path)
        if text is not None:
            exp_cont_counts = _compute_expected_by_continent(stories, iso_to_cont)
            if exp_cont_counts is not None:
                n_continents = len(exp_cont_counts)
                if _report_contains_overview(
                    text,
                    expected["total_profiles"],
                    expected["unique_countries"],
                    n_continents,
                ):
                    scores["report_overview_stats_correct"] = 1.0
            if _report_contains_years_range(text, expected["min_year"], expected["max_year"]):
                scores["report_years_range_correct"] = 1.0
            top3_codes_counts = [(code, cnt) for code, cnt in expected["top3"]]
            if _report_contains_top3(text, top3_codes_counts):
                scores["report_top3_countries_correct"] = 1.0

    build_log_path = workspace / "outputs" / "build.log"
    if build_log_path.exists():
        text, _ = _safe_read_text(build_log_path)
        if text is not None:
            lines = [ln for ln in text.splitlines() if ln.strip()]
            satisfied = 0
            total_requirements = 1
            if any(re.search(r'start', ln, re.IGNORECASE) for ln in lines):
                satisfied += 1
            produced_files = [
                "outputs/summary/by_country.csv",
                "outputs/summary/by_continent.csv",
                "outputs/summary/by_sector.csv",
                "outputs/report.md",
            ]
            total_requirements += len(produced_files)
            for p in produced_files:
                match_lines = [ln for ln in lines if p in ln]
                if match_lines:
                    if p.endswith(".csv"):
                        if any(re.search(r'\d+', ml) for ml in match_lines):
                            satisfied += 1
                    else:
                        satisfied += 1
            scores["build_log_contains_entries"] = satisfied / total_requirements if total_requirements > 0 else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()