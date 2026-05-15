import sys
import json
import csv
import re
import ast
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def parse_yaml_required_columns_and_outputs(yaml_text: str) -> Tuple[List[str], Dict[str, str]]:
    required_cols: List[str] = []
    outputs: Dict[str, str] = {}
    lines = yaml_text.splitlines()
    in_required = False
    in_outputs = False
    base_indent_required = None
    base_indent_outputs = None
    for line in lines:
        raw = line.rstrip("\n")
        if re.match(r"^\s*required_columns\s*:\s*$", raw):
            in_required = True
            in_outputs = False
            base_indent_required = len(raw) - len(raw.lstrip(" "))
            continue
        if re.match(r"^\s*outputs\s*:\s*$", raw):
            in_required = False
            in_outputs = True
            base_indent_outputs = len(raw) - len(raw.lstrip(" "))
            continue
        if in_required:
            if raw.strip() == "":
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if base_indent_required is not None and indent <= base_indent_required:
                in_required = False
            else:
                m = re.match(r"^\s*-\s*([A-Za-z0-9_]+)\s*$", raw)
                if m:
                    required_cols.append(m.group(1))
        if in_outputs:
            if raw.strip() == "":
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if base_indent_outputs is not None and indent <= base_indent_outputs:
                in_outputs = False
            else:
                m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$", raw)
                if m:
                    key = m.group(1).strip()
                    val = m.group(2).strip()
                    outputs[key] = val
    return required_cols, outputs


def read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
            return headers, rows
    except Exception:
        return None


def parse_normalize_constants(normalize_text: str) -> Tuple[Optional[Tuple[int, int]], List[str]]:
    try:
        tree = ast.parse(normalize_text)
    except Exception:
        return None, []
    early_period = None
    allowed_countries: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "EARLY_PERIOD":
                    try:
                        val = ast.literal_eval(node.value)
                        if isinstance(val, (tuple, list)) and len(val) == 2:
                            a, b = int(val[0]), int(val[1])
                            early_period = (a, b)
                    except Exception:
                        pass
                if isinstance(t, ast.Name) and t.id == "ALLOWED_COUNTRIES":
                    try:
                        val = ast.literal_eval(node.value)
                        if isinstance(val, list):
                            allowed_countries = [str(x) for x in val]
                    except Exception:
                        pass
    return early_period, allowed_countries


def split_semicolon_list(value: str) -> List[str]:
    if not value:
        return []
    parts = [p.strip() for p in value.split(";")]
    return [p for p in parts if p]


def extract_domain(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"([A-Za-z0-9.-]+\.[A-Za-z]{2,})", text)
    if m:
        domain = m.group(1).lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    return None


def is_institutional_source(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    domain = extract_domain(t) or ""
    institutional_domains = {
        "britannica.com",
        "si.edu",
        "loc.gov",
        "metmuseum.org",
        "moma.org",
        "louvre.fr",
        "vam.ac.uk",
        "tate.org.uk",
        "bnf.fr",
        "oxfordreference.com",
        "encyclopedia.com",
        "riba.org",
        "designmuseum.org",
    }
    if domain.endswith(".edu") or domain.endswith(".gov"):
        return True
    if domain in institutional_domains:
        return True
    keywords = ["museum", "library", "archive", "encyclopedia", "university", "gov"]
    if any(k in t for k in keywords):
        return True
    return False


def parse_example_work(item: str) -> Optional[Tuple[str, str, int]]:
    if not item:
        return None
    item = item.strip()
    m = re.match(r"^(.*)\s\((.*),\s*(\d{4})\)$", item)
    if not m:
        return None
    title = m.group(1).strip()
    city = m.group(2).strip()
    try:
        year = int(m.group(3))
    except Exception:
        return None
    return title, city, year


def compute_aggregates_by_country(rows: List[Dict[str, str]]) -> List[Tuple[str, int, int]]:
    tally: Dict[str, Dict[str, int]] = {}
    for r in rows:
        country = (r.get("country") or "").strip()
        try:
            count = int(str(r.get("early_period_works_count", "")).strip())
        except Exception:
            count = 0
        if country not in tally:
            tally[country] = {"architect_count": 0, "works_total": 0}
        tally[country]["architect_count"] += 1
        tally[country]["works_total"] += count
    out: List[Tuple[str, int, int]] = []
    for c, data in tally.items():
        out.append((c, data["architect_count"], data["works_total"]))
    return out


def compute_aggregates_by_city(rows: List[Dict[str, str]]) -> List[Tuple[str, str, int]]:
    tally: Dict[Tuple[str, str], int] = {}
    for r in rows:
        city = (r.get("primary_city") or "").strip()
        country = (r.get("country") or "").strip()
        try:
            count = int(str(r.get("early_period_works_count", "")).strip())
        except Exception:
            count = 0
        key = (city, country)
        tally[key] = tally.get(key, 0) + count
    out: List[Tuple[str, str, int]] = []
    for (city, country), total in tally.items():
        out.append((city, country, total))
    return out


def compare_aggregate_csv(path: Path, expected_rows: List[Tuple], expected_headers: List[str]) -> bool:
    parsed = read_csv_dicts(path)
    if not parsed:
        return False
    headers, rows = parsed
    if headers != expected_headers:
        return False
    actual_rows: List[Tuple] = []
    for row in rows:
        vals: List = []
        for h in expected_headers:
            val = row.get(h, "")
            if h.endswith("_total") or h.endswith("_count"):
                try:
                    vals.append(int(str(val).strip()))
                except Exception:
                    return False
            else:
                vals.append((val or "").strip())
        actual_rows.append(tuple(vals))
    return sorted(actual_rows) == sorted(expected_rows)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "plan_exists": 0.0,
        "plan_covers_search_vetting": 0.0,
        "plan_covers_normalization": 0.0,
        "plan_covers_early_period": 0.0,
        "plan_covers_validation": 0.0,
        "search_log_exists_and_min_lines": 0.0,
        "enriched_csv_has_required_columns": 0.0,
        "enriched_rows_cover_all_input_names": 0.0,
        "early_period_constants_uniform_and_match": 0.0,
        "numeric_year_fields_valid": 0.0,
        "example_works_format_and_bounds": 0.0,
        "example_works_count_matches_field_and_range": 0.0,
        "primary_city_in_example_works": 0.0,
        "country_values_normalized": 0.0,
        "sources_two_independent_with_institutional": 0.0,
        "aggregates_by_country_correct": 0.0,
        "aggregates_by_city_correct": 0.0,
    }

    input_csv_path = workspace / "input" / "architects.csv"
    parsed_input = read_csv_dicts(input_csv_path)
    input_names: List[str] = []
    if parsed_input:
        _, input_rows = parsed_input
        for r in input_rows:
            name = (r.get("name") or "").strip()
            if name:
                input_names.append(name)

    schema_path = workspace / "config" / "schema.yaml"
    required_cols: List[str] = []
    outputs_paths: Dict[str, str] = {}
    if schema_path.exists():
        schema_text = read_text_safe(schema_path) or ""
        rc, outs = parse_yaml_required_columns_and_outputs(schema_text)
        required_cols = rc
        outputs_paths = outs

    enriched_csv_rel = outputs_paths.get("enriched_csv", "output/architects_enriched.csv")
    aggregates_by_country_rel = outputs_paths.get("aggregates_by_country", "output/aggregates_by_country.csv")
    aggregates_by_city_rel = outputs_paths.get("aggregates_by_city", "output/aggregates_by_city.csv")
    search_log_rel = outputs_paths.get("search_log", "output/search_queries.txt")
    plan_rel = outputs_paths.get("plan", "output/plan.md")

    enriched_csv_path = workspace / enriched_csv_rel
    aggregates_by_country_path = workspace / aggregates_by_country_rel
    aggregates_by_city_path = workspace / aggregates_by_city_rel
    search_log_path = workspace / search_log_rel
    plan_path = workspace / plan_rel

    normalize_path = workspace / "scripts" / "normalize.py"
    early_period_constants: Optional[Tuple[int, int]] = None
    allowed_countries: List[str] = []
    if normalize_path.exists():
        norm_text = read_text_safe(normalize_path) or ""
        ep, ac = parse_normalize_constants(norm_text)
        early_period_constants = ep
        allowed_countries = ac

    plan_text = read_text_safe(plan_path)
    if plan_text is not None and plan_text.strip():
        scores["plan_exists"] = 1.0
        lower = plan_text.lower()
        if "search" in lower and ("vet" in lower or "evaluate" in lower or "credib" in lower or "institution" in lower or ".edu" in lower or ".gov" in lower):
            scores["plan_covers_search_vetting"] = 1.0
        if "normalize" in lower and "country" in lower and "city" in lower:
            scores["plan_covers_normalization"] = 1.0
        has_norm_ref = "scripts/normalize.py" in lower or "early_period" in lower
        has_years = ("1900" in lower and "1939" in lower) or "inclusive" in lower
        if has_norm_ref or has_years:
            scores["plan_covers_early_period"] = 1.0
        if "validate" in lower and ("schema" in lower or "constraint" in lower):
            scores["plan_covers_validation"] = 1.0

    if search_log_path.exists():
        log_text = read_text_safe(search_log_path) or ""
        if log_text:
            lines = [ln for ln in (ln.strip() for ln in log_text.splitlines()) if ln]
            min_required = len(input_names) if input_names else 1
            if len(lines) >= min_required:
                scores["search_log_exists_and_min_lines"] = 1.0

    enriched_parsed = read_csv_dicts(enriched_csv_path)
    if enriched_parsed:
        headers, rows = enriched_parsed
        if required_cols:
            if all(col in headers for col in required_cols):
                scores["enriched_csv_has_required_columns"] = 1.0
        else:
            fallback_cols = [
                "name",
                "birth_year",
                "death_year",
                "primary_city",
                "country",
                "early_period_start_year",
                "early_period_end_year",
                "early_period_works_count",
                "example_works",
                "sources",
            ]
            if all(col in headers for col in fallback_cols):
                scores["enriched_csv_has_required_columns"] = 1.0

        if input_names:
            enriched_names = {(r.get("name") or "").strip() for r in rows}
            if all(n in enriched_names for n in input_names):
                scores["enriched_rows_cover_all_input_names"] = 1.0

        numeric_ok = True
        for r in rows:
            b = (r.get("birth_year") or "").strip()
            d = (r.get("death_year") or "").strip()
            e_start = (r.get("early_period_start_year") or "").strip()
            e_end = (r.get("early_period_end_year") or "").strip()
            if not b.isdigit():
                numeric_ok = False
                break
            if d != "" and not d.isdigit():
                numeric_ok = False
                break
            if not e_start.isdigit() or not e_end.isdigit():
                numeric_ok = False
                break
        if numeric_ok and rows:
            scores["numeric_year_fields_valid"] = 1.0

        ep_ok = False
        if early_period_constants:
            try:
                starts = {int((r.get("early_period_start_year") or "0").strip()) for r in rows}
                ends = {int((r.get("early_period_end_year") or "0").strip()) for r in rows}
                if len(starts) == 1 and len(ends) == 1:
                    s = list(starts)[0]
                    e = list(ends)[0]
                    if (s, e) == early_period_constants:
                        ep_ok = True
            except Exception:
                ep_ok = False
        if ep_ok and rows:
            scores["early_period_constants_uniform_and_match"] = 1.0

        ex_format_ok = True
        ex_count_ok = True
        pc_link_ok = True
        if not early_period_constants:
            ex_format_ok = False
            ex_count_ok = False
            pc_link_ok = False
        else:
            ep_start, ep_end = early_period_constants
            for r in rows:
                ex_field = (r.get("example_works") or "").strip()
                items = split_semicolon_list(ex_field)
                if len(items) == 0:
                    ex_format_ok = False
                    ex_count_ok = False
                    pc_link_ok = False
                    break
                parsed_items: List[Tuple[str, str, int]] = []
                for item in items:
                    parsed = parse_example_work(item)
                    if not parsed:
                        ex_format_ok = False
                        break
                    title, city, year = parsed
                    if not (ep_start <= year <= ep_end):
                        ex_format_ok = False
                        break
                    parsed_items.append(parsed)
                try:
                    count_field = int(str(r.get("early_period_works_count", "")).strip())
                except Exception:
                    ex_count_ok = False
                    count_field = -1
                if count_field != len(items) or not (1 <= len(items) <= 3):
                    ex_count_ok = False
                primary_city = (r.get("primary_city") or "").strip()
                if primary_city:
                    if not any((pcity or "").strip().casefold() == primary_city.casefold() for _, pcity, _ in parsed_items):
                        pc_link_ok = False
                else:
                    pc_link_ok = False
                if not ex_format_ok:
                    break
        if ex_format_ok and rows:
            scores["example_works_format_and_bounds"] = 1.0
        if ex_count_ok and rows:
            scores["example_works_count_matches_field_and_range"] = 1.0
        if pc_link_ok and rows:
            scores["primary_city_in_example_works"] = 1.0

        country_ok = True
        if not allowed_countries:
            country_ok = False
        else:
            for r in rows:
                c = (r.get("country") or "").strip()
                if c != "" and c not in allowed_countries:
                    country_ok = False
                    break
        if country_ok and rows:
            scores["country_values_normalized"] = 1.0

        sources_ok = True
        for r in rows:
            src_field = (r.get("sources") or "").strip()
            items = split_semicolon_list(src_field)
            if len(items) < 2:
                sources_ok = False
                break
            domains = [extract_domain(x or "") for x in items if x]
            distinct_domains = {d for d in domains if d}
            if distinct_domains:
                if len(distinct_domains) < 2:
                    sources_ok = False
                    break
            else:
                if len(set(items)) < 2:
                    sources_ok = False
                    break
            if not any(is_institutional_source(x) for x in items):
                sources_ok = False
                break
        if sources_ok and rows:
            scores["sources_two_independent_with_institutional"] = 1.0

        exp_by_country = compute_aggregates_by_country(rows)
        exp_by_city = compute_aggregates_by_city(rows)

        if aggregates_by_country_path.exists():
            expected_headers_country = ["country", "architect_count", "early_period_works_total"]
            expected_rows_country = [(c, ac, wt) for (c, ac, wt) in exp_by_country]
            if compare_aggregate_csv(aggregates_by_country_path, expected_rows_country, expected_headers_country):
                scores["aggregates_by_country_correct"] = 1.0

        if aggregates_by_city_path.exists():
            expected_headers_city = ["primary_city", "country", "early_period_works_total"]
            expected_rows_city = [(pc, c, wt) for (pc, c, wt) in exp_by_city]
            if compare_aggregate_csv(aggregates_by_city_path, expected_rows_city, expected_headers_city):
                scores["aggregates_by_city_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()