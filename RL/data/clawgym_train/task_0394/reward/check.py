import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                return None, None
            rows: List[Dict[str, str]] = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return fieldnames, rows
    except Exception:
        return None, None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_float(value: str) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    if s.lower() in {"na", "nan", "n/a", "null", "none", "."}:
        return None
    try:
        x = float(s)
        if math.isnan(x):
            return None
        return x
    except Exception:
        return None


def _safe_int(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = 0.0
    denx = 0.0
    deny = 0.0
    for x, y in zip(xs, ys):
        dx = x - mean_x
        dy = y - mean_y
        num += dx * dy
        denx += dx * dx
        deny += dy * dy
    den = math.sqrt(denx * deny)
    if den == 0.0:
        return None
    return num / den


def _approx_equal(a: Optional[float], b: Optional[float], tol: float = 1e-9) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _get_field(d: Dict[str, Any], keys: List[str]) -> Any:
    for k in keys:
        if k in d:
            return d[k]
    return None


def _is_worldbank_domain(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        # Handle possible credentials or ports: strip port if present
        if ":" in host:
            host = host.split(":", 1)[0]
        return host.endswith("worldbank.org")
    except Exception:
        return False


def _load_expected_countries(workspace: Path) -> Optional[List[str]]:
    path = workspace / "input" / "countries.csv"
    header, rows = _read_csv_dicts(path)
    if not header or not rows or "iso3" not in header:
        return None
    out: List[str] = []
    for r in rows:
        code = (r.get("iso3") or "").strip().upper()
        if code:
            out.append(code)
    return out


def _load_expected_years(workspace: Path) -> Optional[List[str]]:
    path = workspace / "input" / "years.csv"
    header, rows = _read_csv_dicts(path)
    if not header or not rows or "year" not in header:
        return None
    years: List[str] = []
    for r in rows:
        y = (r.get("year") or "").strip()
        if y:
            # Keep as string for exact match with CSV content
            years.append(y)
    return years


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "provenance_structure": 0.0,
        "provenance_provider_domain_urls": 0.0,
        "series_structure_and_values": 0.0,
        "series_coverage_countries": 0.0,
        "correlations_structure": 0.0,
        "correlations_recomputed_match": 0.0,
        "validation_artifacts": 0.0,
    }

    # Load expected countries and years
    expected_countries = _load_expected_countries(workspace) or []
    expected_years = _load_expected_years(workspace) or []

    # 1) Check provenance.json
    prov_path = workspace / "output" / "provenance.json"
    prov = _load_json(prov_path)
    expected_indicator_names = {
        "Military expenditure (% of GDP)",
        "Intentional homicides (per 100,000 people)",
    }
    prov_ok_structure = False
    prov_ok_provider_domain_urls = False
    if prov is not None:
        # Accept either list at top-level or dict with "indicators"
        if isinstance(prov, list):
            entries = prov
        elif isinstance(prov, dict):
            entries = prov.get("indicators")
        else:
            entries = None

        if isinstance(entries, list) and len(entries) >= 2:
            # Try to map indicator_name -> entry
            by_name: Dict[str, Dict[str, Any]] = {}
            for e in entries:
                if not isinstance(e, dict):
                    continue
                name = _get_field(e, ["indicator_name", "name"])
                if isinstance(name, str):
                    by_name[name] = e

            # Check presence of both indicators
            if expected_indicator_names.issubset(set(by_name.keys())):
                # Validate fields for each
                all_fields_ok = True
                all_provider_domain_ok = True
                for name in expected_indicator_names:
                    e = by_name[name]
                    provider = _get_field(e, ["provider"])
                    domain = _get_field(e, ["domain", "domain_pattern"])
                    dataset_title = _get_field(e, ["dataset_title", "title"])
                    access_date = _get_field(e, ["access_date", "accessDate"])
                    data_format = _get_field(e, ["data_format", "format"])

                    # search queries (allow several key names)
                    queries = _get_field(e, ["search_queries", "search_engine_queries", "queries", "searchTerms"])
                    # resource URLs (allow several key names; also single string)
                    urls = _get_field(e, ["resource_urls", "final_urls", "urls", "sources", "resource_url", "url"])
                    if isinstance(urls, str):
                        urls = [urls]

                    # Field-level checks
                    fields_ok = True
                    if not isinstance(provider, str) or provider.strip() != "World Bank Open Data":
                        fields_ok = False
                    if not isinstance(domain, str) or "worldbank.org" not in domain.lower():
                        fields_ok = False
                    if not isinstance(dataset_title, str) or not dataset_title.strip():
                        fields_ok = False
                    try:
                        if not isinstance(access_date, str):
                            raise ValueError("bad date")
                        datetime.strptime(access_date.strip(), "%Y-%m-%d")
                    except Exception:
                        fields_ok = False
                    if not isinstance(data_format, str) or not data_format.strip():
                        fields_ok = False
                    if not isinstance(queries, list) or len(queries) == 0 or not all(isinstance(q, str) and q.strip() for q in queries):
                        fields_ok = False
                    if not isinstance(urls, list) or len(urls) == 0 or not all(isinstance(u, str) and u.strip() for u in urls):
                        fields_ok = False

                    # Provider/domain/url domain checks
                    provider_domain_ok = True
                    if not (isinstance(provider, str) and provider.strip() == "World Bank Open Data"):
                        provider_domain_ok = False
                    if not (isinstance(domain, str) and "worldbank.org" in domain.lower()):
                        provider_domain_ok = False
                    # All resource URLs must be worldbank.org domain
                    if isinstance(urls, list):
                        if not all(_is_worldbank_domain(u) for u in urls if isinstance(u, str)):
                            provider_domain_ok = False
                    else:
                        provider_domain_ok = False

                    all_fields_ok = all_fields_ok and fields_ok
                    all_provider_domain_ok = all_provider_domain_ok and provider_domain_ok

                prov_ok_structure = all_fields_ok
                prov_ok_provider_domain_urls = all_provider_domain_ok

    scores["provenance_structure"] = 1.0 if prov_ok_structure else 0.0
    scores["provenance_provider_domain_urls"] = 1.0 if prov_ok_provider_domain_urls else 0.0

    # 2) Check output/series.csv structure and values
    series_path = workspace / "output" / "series.csv"
    expected_series_header = ["iso3", "year", "military_expenditure_gdp_pct", "intentional_homicide_per_100k"]
    series_ok = False
    series_covers_all = False
    series_rows: List[Dict[str, str]] = []
    if series_path.exists():
        header, rows = _read_csv_dicts(series_path)
        if header == expected_series_header and isinstance(rows, list):
            valid_rows = True
            seen_iso3: set = set()
            # Validate each row
            for r in rows:
                iso3 = (r.get("iso3") or "").strip().upper()
                year = (r.get("year") or "").strip()
                mx = _safe_float(r.get("military_expenditure_gdp_pct") or "")
                hy = _safe_float(r.get("intentional_homicide_per_100k") or "")
                # iso3 checks
                if not (len(iso3) == 3 and iso3.isalnum() and iso3 == iso3.upper()):
                    valid_rows = False
                    break
                if expected_countries:
                    if iso3 not in expected_countries:
                        valid_rows = False
                        break
                # year checks
                if expected_years:
                    if year not in expected_years:
                        valid_rows = False
                        break
                else:
                    # fallback basic int check
                    if _safe_int(year) is None:
                        valid_rows = False
                        break
                # values: allow None (missing), or float
                if r.get("military_expenditure_gdp_pct") not in (None, "") and mx is None:
                    valid_rows = False
                    break
                if r.get("intentional_homicide_per_100k") not in (None, "") and hy is None:
                    valid_rows = False
                    break
                seen_iso3.add(iso3)
            if valid_rows:
                series_ok = True
                series_rows = rows
                # coverage: every expected iso3 appears at least once
                if expected_countries:
                    series_covers_all = set(expected_countries).issubset(seen_iso3)
                else:
                    # If no expected list loaded, cannot assert coverage
                    series_covers_all = False

    scores["series_structure_and_values"] = 1.0 if series_ok else 0.0
    scores["series_coverage_countries"] = 1.0 if series_covers_all else 0.0

    # 3) correlations.csv: structure + recomputed match
    corr_path = workspace / "output" / "correlations.csv"
    expected_corr_header = ["year", "pearson_r", "n_pairs"]
    corr_ok_structure = False
    corr_ok_values = False
    if corr_path.exists() and series_ok:
        cheader, crows = _read_csv_dicts(corr_path)
        if cheader == expected_corr_header and isinstance(crows, list):
            # Build set of required years + 'overall'
            required_year_labels = set(expected_years)
            required_year_labels.add("overall")
            years_in_corr = [ (r.get("year") or "").strip() for r in crows ]
            # Structure: exact number of rows and exact set of year labels
            structure_ok = set(years_in_corr) == required_year_labels and len(crows) == len(required_year_labels)
            # Validate types and positivity of n_pairs
            n_types_ok = True
            for r in crows:
                n_pairs = _safe_int(r.get("n_pairs") or "")
                pr = _safe_float(r.get("pearson_r") or "")
                y = (r.get("year") or "").strip()
                if n_pairs is None or n_pairs <= 0:
                    n_types_ok = False
                    break
                if pr is None or not math.isfinite(pr):
                    n_types_ok = False
                    break
                # Year must be overall or one of expected years
                if y != "overall" and y not in expected_years:
                    n_types_ok = False
                    break
            corr_ok_structure = structure_ok and n_types_ok

            # Recompute correlations from series.csv and compare
            if corr_ok_structure:
                # Build by-year pairs
                def collect_pairs_for_year(year_label: str) -> Tuple[List[float], List[float]]:
                    xs: List[float] = []
                    ys: List[float] = []
                    for r in series_rows:
                        y = (r.get("year") or "").strip()
                        if y != year_label:
                            continue
                        x = _safe_float(r.get("military_expenditure_gdp_pct") or "")
                        h = _safe_float(r.get("intentional_homicide_per_100k") or "")
                        if x is None or h is None:
                            continue
                        xs.append(x)
                        ys.append(h)
                    return xs, ys

                # Compute and compare per year
                all_match = True
                # Create quick lookup for correlations.csv rows
                by_year_row: Dict[str, Dict[str, str]] = { (r.get("year") or "").strip(): r for r in crows }
                # Per-year checks
                for y in expected_years:
                    xs, ys = collect_pairs_for_year(y)
                    n_pairs_calc = len(xs)
                    r_calc = _pearson(xs, ys) if n_pairs_calc >= 2 else None
                    row = by_year_row.get(y)
                    if row is None:
                        all_match = False
                        break
                    n_pairs_file = _safe_int(row.get("n_pairs") or "")
                    r_file = _safe_float(row.get("pearson_r") or "")
                    # n_pairs must match exactly
                    if n_pairs_file != n_pairs_calc:
                        all_match = False
                        break
                    # If at least 2 pairs, r must match within tolerance
                    if n_pairs_calc >= 2:
                        if not _approx_equal(r_calc, r_file, tol=1e-9):
                            all_match = False
                            break
                # Overall check across all listed countries and years
                xs_all: List[float] = []
                ys_all: List[float] = []
                for r in series_rows:
                    year = (r.get("year") or "").strip()
                    if expected_years and year not in expected_years:
                        continue
                    x = _safe_float(r.get("military_expenditure_gdp_pct") or "")
                    h = _safe_float(r.get("intentional_homicide_per_100k") or "")
                    if x is None or h is None:
                        continue
                    xs_all.append(x)
                    ys_all.append(h)
                n_all = len(xs_all)
                r_all = _pearson(xs_all, ys_all) if n_all >= 2 else None
                overall_row = by_year_row.get("overall")
                if overall_row is None:
                    all_match = False
                else:
                    n_pairs_over_file = _safe_int(overall_row.get("n_pairs") or "")
                    r_over_file = _safe_float(overall_row.get("pearson_r") or "")
                    if n_pairs_over_file != n_all:
                        all_match = False
                    elif n_all >= 2:
                        if not _approx_equal(r_all, r_over_file, tol=1e-9):
                            all_match = False

                corr_ok_values = all_match

    scores["correlations_structure"] = 1.0 if corr_ok_structure else 0.0
    scores["correlations_recomputed_match"] = 1.0 if corr_ok_values else 0.0

    # 5) validation artifacts present
    validate_sh = workspace / "tests" / "validate.sh"
    validation_report = workspace / "tests" / "validation_report.txt"
    val_ok = False
    try:
        sh_exists = validate_sh.exists()
        rep_exists = validation_report.exists()
        sh_executable = False
        if sh_exists:
            try:
                mode = validate_sh.stat().st_mode
                sh_executable = (mode & 0o111) != 0
            except Exception:
                sh_executable = False
            # Also accept shebang presence even if not executable
            if not sh_executable:
                try:
                    with validate_sh.open("r", encoding="utf-8") as f:
                        first = f.readline()
                        if first.startswith("#!"):
                            sh_executable = True
                except Exception:
                    pass
        rep_nonempty = False
        rep_contains_overall = False
        if rep_exists:
            try:
                text = validation_report.read_text(encoding="utf-8", errors="ignore")
                rep_nonempty = len(text.strip()) > 0
                rep_contains_overall = "overall" in text
            except Exception:
                rep_nonempty = False
                rep_contains_overall = False
        val_ok = sh_exists and sh_executable and rep_exists and rep_nonempty and rep_contains_overall
    except Exception:
        val_ok = False

    scores["validation_artifacts"] = 1.0 if val_ok else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()