import json
import csv
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    items = []
    try:
        with path.open(encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def _parse_float(s: Any) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _parse_int(s: Any) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _read_sources_yaml(path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    # Minimal YAML parser for the specific expected structure:
    # sources:
    #   key:
    #     type: ...
    #     reliability: 0.9
    try:
        with path.open(encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f]
    except Exception:
        return None
    sources: Dict[str, Dict[str, Any]] = {}
    in_sources = False
    current_key = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not in_sources:
            if line == "sources:":
                in_sources = True
            else:
                # ignore other top-level keys
                continue
        else:
            # Inside sources block: expect indentation
            if raw.startswith("  ") and not raw.startswith("    "):
                # Two spaces indent: a new source_id key
                if not line.endswith(":"):
                    return None
                current_key = line[:-1].strip()
                if not current_key:
                    return None
                if current_key in sources:
                    return None
                sources[current_key] = {}
            elif raw.startswith("    "):
                # Four spaces indent: property of current_key
                if current_key is None:
                    return None
                if ":" not in line:
                    return None
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip()
                # Remove possible quotes from v
                if v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) >= 2:
                    v = v[1:-1]
                # Try parse number for reliability
                if k == "reliability":
                    num = _parse_float(v)
                    if num is None:
                        return None
                    sources[current_key][k] = num
                else:
                    sources[current_key][k] = v
            else:
                # Dedentation - leave sources block
                break
    if not in_sources:
        return None
    return {"sources": sources}


def _extract_earliest_latest(d: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    # Try a variety of keys to find earliest/min and latest/max
    earliest_keys = ["earliest", "min", "min_observed", "min_value"]
    latest_keys = ["latest", "max", "max_observed", "max_value"]
    earliest = None
    latest = None
    for k in earliest_keys:
        if k in d:
            earliest = d[k]
            break
    for k in latest_keys:
        if k in d:
            latest = d[k]
            break
    return earliest, latest


def _compute_expected_validation(roster: List[Dict[str, str]],
                                 census: List[Dict[str, str]],
                                 obits: List[Dict[str, Any]],
                                 sources_yaml: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    # Schema checks based on required columns
    required = {
        "roster": ["person_id", "name", "birth_year", "founding_member"],
        "census_index": ["person_id", "name", "birth_year_reported", "year", "location", "source_id"],
        "obituaries": ["person_id", "name", "birth_year_obit", "death_year", "source_id"],
    }
    def cols_of(records: List[Dict[str, Any]]) -> List[str]:
        if not records:
            return []
        # union of keys across all rows
        cols = set()
        for r in records:
            for k in r.keys():
                cols.add(k)
        return list(cols)

    schema_checks = {}
    actual_cols = {
        "roster": cols_of(roster),
        "census_index": cols_of(census),
        "obituaries": cols_of(obits),
    }
    for key, req_cols in required.items():
        missing = [c for c in req_cols if c not in actual_cols.get(key, [])]
        schema_checks[key] = {
            "has_required_columns": len(missing) == 0,
            "missing_columns": missing,
        }

    # Uniqueness check for roster person_id
    seen = set()
    dupes = []
    for r in roster:
        pid = r.get("person_id")
        if pid in seen:
            dupes.append(pid)
        else:
            seen.add(pid)
    uniqueness_check = {
        "person_id_unique": len(dupes) == 0,
        "duplicates": dupes,
    }

    # Range checks: compute min/max observed
    def get_ints(values: List[Any]) -> List[int]:
        out = []
        for v in values:
            iv = _parse_int(v)
            if iv is None:
                return []
            out.append(iv)
        return out

    # roster.birth_year in [1850,2005]
    roster_births = get_ints([r.get("birth_year") for r in roster])
    if roster_births:
        roster_min = min(roster_births)
        roster_max = max(roster_births)
        roster_within = 1850 <= roster_min and roster_max <= 2005
    else:
        roster_min = None
        roster_max = None
        roster_within = False

    # obituaries.birth_year_obit in [1850,2005]; death_year in [1900,2020]
    obit_births = get_ints([o.get("birth_year_obit") for o in obits])
    if obit_births:
        obit_bmin = min(obit_births)
        obit_bmax = max(obit_births)
        obit_b_within = 1850 <= obit_bmin and obit_bmax <= 2005
    else:
        obit_bmin = None
        obit_bmax = None
        obit_b_within = False

    obit_deaths = get_ints([o.get("death_year") for o in obits])
    if obit_deaths:
        obit_dmin = min(obit_deaths)
        obit_dmax = max(obit_deaths)
        obit_d_within = 1900 <= obit_dmin and obit_dmax <= 2020
    else:
        obit_dmin = None
        obit_dmax = None
        obit_d_within = False

    # census_index.year in [1880,1960]
    census_years = get_ints([c.get("year") for c in census])
    if census_years:
        cmin = min(census_years)
        cmax = max(census_years)
        c_within = 1880 <= cmin and cmax <= 1960
    else:
        cmin = None
        cmax = None
        c_within = False

    range_checks = {
        "roster.birth_year": {"earliest": roster_min, "latest": roster_max, "within_range": roster_within},
        "obituaries.birth_year_obit": {"earliest": obit_bmin, "latest": obit_bmax, "within_range": obit_b_within},
        "obituaries.death_year": {"earliest": obit_dmin, "latest": obit_dmax, "within_range": obit_d_within},
        "census_index.year": {"earliest": cmin, "latest": cmax, "within_range": c_within},
    }

    # Foreign key checks: person_ids in census_index and obituaries exist in roster
    roster_ids = set([r.get("person_id") for r in roster])
    census_unknown = sorted({c.get("person_id") for c in census if c.get("person_id") not in roster_ids})
    obit_unknown = sorted({o.get("person_id") for o in obits if o.get("person_id") not in roster_ids})
    foreign_key_checks = {
        "census_index": census_unknown,
        "obituaries": obit_unknown,
    }

    # Source_id validation: source_ids in census_index and obituaries appear in sources.yaml
    yaml_sources = sources_yaml.get("sources", {}) if sources_yaml else {}
    allowed_source_ids = set(yaml_sources.keys())
    used_source_ids = set()
    for c in census:
        sid = c.get("source_id")
        if sid:
            used_source_ids.add(sid)
    for o in obits:
        sid = o.get("source_id")
        if sid:
            used_source_ids.add(sid)
    unknown_source_ids = sorted([sid for sid in used_source_ids if sid not in allowed_source_ids])
    source_id_validation = {
        "unknown_source_ids": unknown_source_ids
    }

    # Summary counts
    summary_counts = {
        "roster": len(roster),
        "census_index": len(census),
        "obituaries": len(obits),
    }

    return {
        "schema_checks": schema_checks,
        "uniqueness_check": uniqueness_check,
        "range_checks": range_checks,
        "foreign_key_checks": foreign_key_checks,
        "source_id_validation": source_id_validation,
        "summary_counts": summary_counts,
    }


def _compute_verified_and_conflicts(roster: List[Dict[str, str]],
                                    census: List[Dict[str, str]],
                                    obits: List[Dict[str, Any]],
                                    sources_yaml: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    # Build indices
    roster_by_id = {r["person_id"]: r for r in roster if "person_id" in r}
    founding_ids = [r["person_id"] for r in roster if str(r.get("founding_member", "")).strip().lower() == "yes" and "person_id" in r]
    # Build per-person sources
    sources_info = sources_yaml.get("sources", {}) if sources_yaml else {}
    census_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for c in census:
        pid = c.get("person_id")
        if not pid:
            continue
        census_by_id.setdefault(pid, []).append(c)
    obit_by_id: Dict[str, Dict[str, Any]] = {}
    for o in obits:
        pid = o.get("person_id")
        if pid:
            obit_by_id[pid] = o

    verified_rows: List[Dict[str, Any]] = []
    for pid in founding_ids:
        r = roster_by_id.get(pid, {})
        name = r.get("name", "")
        roster_birth_year = _parse_int(r.get("birth_year"))
        # Gather records
        records = []
        # roster as a record
        if roster_birth_year is not None:
            records.append({"value": roster_birth_year, "source": "roster", "weight": 0.0, "census_year": None})
        # census records
        for c in census_by_id.get(pid, []):
            val = _parse_int(c.get("birth_year_reported"))
            cyear = _parse_int(c.get("year"))
            sid = c.get("source_id")
            weight = 0.0
            if sid and sid in sources_info:
                rel = sources_info[sid].get("reliability")
                weight = _parse_float(rel) if rel is not None else 0.0
                if weight is None:
                    weight = 0.0
            if val is not None:
                records.append({"value": val, "source": sid or "", "weight": weight, "census_year": cyear})
        # obituary
        if pid in obit_by_id:
            obit = obit_by_id[pid]
            val = _parse_int(obit.get("birth_year_obit"))
            sid = obit.get("source_id")
            weight = 0.0
            if sid and sid in sources_info:
                rel = sources_info[sid].get("reliability")
                weight = _parse_float(rel) if rel is not None else 0.0
                if weight is None:
                    weight = 0.0
            if val is not None:
                records.append({"value": val, "source": sid or "", "weight": weight, "census_year": None})
        # Calculate stats
        total_sources = len(records)
        value_counts: Dict[int, int] = {}
        weight_sums: Dict[int, float] = {}
        recent_census_year: Dict[int, int] = {}
        for rec in records:
            val = rec["value"]
            value_counts[val] = value_counts.get(val, 0) + 1
            weight_sums[val] = weight_sums.get(val, 0.0) + (rec.get("weight") or 0.0)
            cy = rec.get("census_year")
            if cy is not None:
                if val not in recent_census_year:
                    recent_census_year[val] = cy
                else:
                    if cy is not None and recent_census_year[val] is not None and cy > recent_census_year[val]:
                        recent_census_year[val] = cy
        distinct_years = len(value_counts)
        # Majority vote selection
        # Step 1: max count
        candidates: List[int] = []
        if value_counts:
            max_count = max(value_counts.values())
            candidates = [val for val, cnt in value_counts.items() if cnt == max_count]
        selected_birth_year = None
        if len(candidates) == 1:
            selected_birth_year = candidates[0]
        elif len(candidates) > 1:
            # Step 2: tie-break by weight
            max_w = max(weight_sums.get(val, 0.0) for val in candidates)
            candidates2 = [val for val in candidates if abs(weight_sums.get(val, 0.0) - max_w) < 1e-9]
            if len(candidates2) == 1:
                selected_birth_year = candidates2[0]
            else:
                # Step 3: tie-break by most recent census year among the tied values
                max_year = None
                chosen = None
                for val in candidates2:
                    yr = recent_census_year.get(val, -1)
                    if (max_year is None) or (yr > max_year):
                        max_year = yr
                        chosen = val
                # If all -1 equal, chosen will be first encountered; need final tie-break
                # Step 4: if still tied with identical recent years, prefer roster.birth_year if among candidates
                if chosen is not None:
                    same_year_vals = [val for val in candidates2 if recent_census_year.get(val, -1) == max_year]
                    if len(same_year_vals) == 1:
                        selected_birth_year = chosen
                    else:
                        if roster_birth_year in same_year_vals:
                            selected_birth_year = roster_birth_year
                        else:
                            selected_birth_year = sorted(same_year_vals)[0]
                else:
                    if roster_birth_year in candidates2:
                        selected_birth_year = roster_birth_year
                    else:
                        selected_birth_year = sorted(candidates2)[0]
        else:
            selected_birth_year = roster_birth_year

        sources_supporting = value_counts.get(selected_birth_year, 0)
        status = "confirmed" if distinct_years == 1 else "conflict"

        verified_rows.append({
            "person_id": pid,
            "name": name,
            "roster_birth_year": roster_birth_year,
            "selected_birth_year": selected_birth_year,
            "status": status,
            "distinct_years": distinct_years,
            "sources_supporting": sources_supporting,
            "total_sources": total_sources,
        })

    # Conflicts ranking
    conflicts = []
    for row in verified_rows:
        conflict_score = int(row["total_sources"]) - int(row["sources_supporting"])
        conflicts.append({
            "person_id": row["person_id"],
            "name": row["name"],
            "conflict_score": conflict_score,
            "distinct_years": row["distinct_years"],
            "total_sources": row["total_sources"],
        })
    conflicts_sorted = sorted(conflicts, key=lambda x: (-int(x["conflict_score"]), x["name"]))
    return verified_rows, conflicts_sorted


def _read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            return header
    except Exception:
        return None


def _read_csv_rows_dict(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validation_report_present": 0.0,
        "schema_checks_correct": 0.0,
        "uniqueness_check_correct": 0.0,
        "range_checks_correct": 0.0,
        "foreign_key_checks_correct": 0.0,
        "source_id_validation_correct": 0.0,
        "summary_counts_correct": 0.0,
        "verified_birth_years_exists_and_columns": 0.0,
        "verified_birth_years_content_correct": 0.0,
        "conflict_rankings_exists_and_columns": 0.0,
        "conflict_rankings_sorted_and_content_correct": 0.0,
    }

    # Load inputs
    roster_path = workspace / "input" / "roster.csv"
    census_path = workspace / "input" / "census_index.csv"
    obits_path = workspace / "input" / "obituaries.jsonl"
    sources_path = workspace / "input" / "sources.yaml"

    roster = _read_csv_dicts(roster_path) or []
    census = _read_csv_dicts(census_path) or []
    obits = _read_jsonl(obits_path) or []
    sources_yaml = _read_sources_yaml(sources_path)

    # Compute expected validation values if inputs are good
    expected_validation = None
    if roster and census and obits and sources_yaml is not None:
        expected_validation = _compute_expected_validation(roster, census, obits, sources_yaml)

    # Check validation/report.json
    report_path = workspace / "validation" / "report.json"
    report = _read_json(report_path)
    if isinstance(report, dict):
        scores["validation_report_present"] = 1.0

    # Schema checks correctness
    if expected_validation is not None and isinstance(report, dict):
        schema = report.get("schema_checks")
        if isinstance(schema, dict):
            ok = True
            for key in ["roster", "census_index", "obituaries"]:
                entry = schema.get(key)
                if not isinstance(entry, dict):
                    ok = False
                    break
                has_req = entry.get("has_required_columns")
                missing = entry.get("missing_columns")
                exp = expected_validation["schema_checks"][key]
                if has_req is not exp["has_required_columns"]:
                    ok = False
                    break
                # Compare missing columns as sorted lists
                if not isinstance(missing, list):
                    ok = False
                    break
                if sorted(missing) != sorted(exp["missing_columns"]):
                    ok = False
                    break
            if ok:
                scores["schema_checks_correct"] = 1.0

    # Uniqueness check correctness
    if expected_validation is not None and isinstance(report, dict):
        uniq = report.get("uniqueness_check") or report.get("uniqueness") or report.get("unique_checks")
        if isinstance(uniq, dict):
            exp = expected_validation["uniqueness_check"]
            pid_unique = uniq.get("person_id_unique")
            duplicates = uniq.get("duplicates")
            if isinstance(pid_unique, bool) and isinstance(duplicates, list):
                if pid_unique is exp["person_id_unique"] and sorted(duplicates) == sorted(exp["duplicates"]):
                    scores["uniqueness_check_correct"] = 1.0

    # Range checks correctness
    if expected_validation is not None and isinstance(report, dict):
        rc = report.get("range_checks") or report.get("ranges")
        if isinstance(rc, dict):
            ok = True
            for field in ["roster.birth_year", "obituaries.birth_year_obit", "obituaries.death_year", "census_index.year"]:
                entry = rc.get(field)
                if not isinstance(entry, dict):
                    ok = False
                    break
                within = entry.get("within_range")
                e_entry = expected_validation["range_checks"][field]
                if within is not e_entry["within_range"]:
                    ok = False
                    break
                # Extract earliest/latest with flexible keys
                e1, l1 = _extract_earliest_latest(entry)
                if e1 is None or l1 is None:
                    ok = False
                    break
                if e1 != e_entry["earliest"] or l1 != e_entry["latest"]:
                    ok = False
                    break
            if ok:
                scores["range_checks_correct"] = 1.0

    # Foreign key checks correctness
    if expected_validation is not None and isinstance(report, dict):
        fk = report.get("foreign_key_checks") or report.get("foreign_keys") or report.get("fk_checks")
        if isinstance(fk, dict):
            census_unknown = fk.get("census_index")
            obit_unknown = fk.get("obituaries")
            if isinstance(census_unknown, list) and isinstance(obit_unknown, list):
                exp = expected_validation["foreign_key_checks"]
                if sorted(census_unknown) == sorted(exp["census_index"]) and sorted(obit_unknown) == sorted(exp["obituaries"]):
                    scores["foreign_key_checks_correct"] = 1.0

    # Source id validation correctness
    if expected_validation is not None and isinstance(report, dict):
        sidv = report.get("source_id_validation") or report.get("source_ids") or report.get("sources_validation")
        if isinstance(sidv, dict):
            unknown = sidv.get("unknown_source_ids")
            if isinstance(unknown, list):
                exp_unknown = expected_validation["source_id_validation"]["unknown_source_ids"]
                if sorted(unknown) == sorted(exp_unknown):
                    scores["source_id_validation_correct"] = 1.0
        elif isinstance(sidv, list):
            exp_unknown = expected_validation["source_id_validation"]["unknown_source_ids"]
            if sorted(sidv) == sorted(exp_unknown):
                scores["source_id_validation_correct"] = 1.0

    # Summary counts correctness
    if expected_validation is not None and isinstance(report, dict):
        sc = report.get("summary_counts") or report.get("counts") or report.get("summary")
        if isinstance(sc, dict):
            ok = True
            for key in ["roster", "census_index", "obituaries"]:
                val = sc.get(key)
                if val != expected_validation["summary_counts"][key]:
                    ok = False
                    break
            if ok:
                scores["summary_counts_correct"] = 1.0

    # Compute expected verified and conflicts
    expected_verified: List[Dict[str, Any]] = []
    expected_conflicts: List[Dict[str, Any]] = []
    if roster and census and obits and sources_yaml is not None:
        expected_verified, expected_conflicts = _compute_verified_and_conflicts(roster, census, obits, sources_yaml)

    # Check output/verified_birth_years.csv
    vfy_path = workspace / "output" / "verified_birth_years.csv"
    vfy_header = _read_csv_header(vfy_path)
    expected_vfy_header = ["person_id", "name", "roster_birth_year", "selected_birth_year", "status", "distinct_years", "sources_supporting", "total_sources"]
    if vfy_header == expected_vfy_header:
        scores["verified_birth_years_exists_and_columns"] = 1.0

    if vfy_header is not None and vfy_header == expected_vfy_header and expected_verified:
        vfy_rows = _read_csv_rows_dict(vfy_path) or []
        # Normalize and compare content ignoring row order
        def normalize_vfy(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
            try:
                return {
                    "person_id": row["person_id"],
                    "name": row["name"],
                    "roster_birth_year": _parse_int(row["roster_birth_year"]),
                    "selected_birth_year": _parse_int(row["selected_birth_year"]),
                    "status": row["status"],
                    "distinct_years": _parse_int(row["distinct_years"]),
                    "sources_supporting": _parse_int(row["sources_supporting"]),
                    "total_sources": _parse_int(row["total_sources"]),
                }
            except Exception:
                return None

        normalized: List[Dict[str, Any]] = []
        for r in vfy_rows:
            nr = normalize_vfy(r)
            if nr is None:
                normalized = []
                break
            normalized.append(nr)

        if normalized:
            # Compare by mapping person_id
            got_by_id = {r["person_id"]: r for r in normalized}
            exp_by_id = {r["person_id"]: r for r in expected_verified}
            content_ok = True
            if set(got_by_id.keys()) != set(exp_by_id.keys()):
                content_ok = False
            else:
                for pid, exp in exp_by_id.items():
                    got = got_by_id.get(pid)
                    if got != exp:
                        content_ok = False
                        break
            if content_ok:
                scores["verified_birth_years_content_correct"] = 1.0

    # Check output/conflict_rankings.csv
    conf_path = workspace / "output" / "conflict_rankings.csv"
    conf_header = _read_csv_header(conf_path)
    expected_conf_header = ["person_id", "name", "conflict_score", "distinct_years", "total_sources"]
    if conf_header == expected_conf_header:
        scores["conflict_rankings_exists_and_columns"] = 1.0

    if conf_header is not None and conf_header == expected_conf_header and expected_conflicts:
        conf_rows = _read_csv_rows_dict(conf_path) or []
        # Normalize types
        def normalize_conf(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
            try:
                return {
                    "person_id": row["person_id"],
                    "name": row["name"],
                    "conflict_score": _parse_int(row["conflict_score"]),
                    "distinct_years": _parse_int(row["distinct_years"]),
                    "total_sources": _parse_int(row["total_sources"]),
                }
            except Exception:
                return None

        normalized: List[Dict[str, Any]] = []
        for r in conf_rows:
            nr = normalize_conf(r)
            if nr is None:
                normalized = []
                break
            normalized.append(nr)

        if normalized:
            # Check content as a list as ordering matters
            # First, verify set equality
            got_set = {(r["person_id"], r["name"], r["conflict_score"], r["distinct_years"], r["total_sources"]) for r in normalized}
            exp_set = {(r["person_id"], r["name"], r["conflict_score"], r["distinct_years"], r["total_sources"]) for r in expected_conflicts}
            content_ok = got_set == exp_set
            # Check sorting: descending conflict_score then ascending name
            sort_ok = True
            if content_ok:
                # Verify that current order matches expected_conflicts order
                if len(normalized) != len(expected_conflicts):
                    sort_ok = False
                else:
                    for i, exp in enumerate(expected_conflicts):
                        got = normalized[i]
                        if not (got["person_id"] == exp["person_id"]
                                and got["name"] == exp["name"]
                                and got["conflict_score"] == exp["conflict_score"]
                                and got["distinct_years"] == exp["distinct_years"]
                                and got["total_sources"] == exp["total_sources"]):
                            sort_ok = False
                            break
            if content_ok and sort_ok:
                scores["conflict_rankings_sorted_and_content_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()