import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    if not path.exists():
        return None, None
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _write_json_stdout(data: Dict) -> None:
    print(json.dumps(data, ensure_ascii=False))


def _parse_date(d: str) -> Optional[datetime]:
    try:
        return datetime.strptime(d.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _parse_bool(s: str) -> Optional[bool]:
    if s is None:
        return None
    t = s.strip().lower()
    if t in ("true", "t", "1", "yes"):
        return True
    if t in ("false", "f", "0", "no"):
        return False
    return None


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _compute_expected_from_input(input_path: Path) -> Dict[str, any]:
    rows, header = _read_csv(input_path)
    result = {
        "input_exists": rows is not None,
        "invalid_site_ids": set(),
        "duplicates_expected": [],
        "valid_unique_count": 0,
        "earliest_by_site": {},
    }
    if rows is None:
        return result

    def in_range(lat: float, lon: float) -> bool:
        return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0

    valid_rows = []
    for row in rows:
        lat = _safe_float(row.get("latitude", ""))
        lon = _safe_float(row.get("longitude", ""))
        if lat is None or lon is None or not in_range(lat, lon):
            if row.get("site_id"):
                result["invalid_site_ids"].add(row["site_id"])
        else:
            valid_rows.append(row)

    # Dedup by earliest planned_date
    by_site: Dict[str, List[Dict[str, str]]] = {}
    for row in valid_rows:
        sid = row.get("site_id")
        if not sid:
            continue
        by_site.setdefault(sid, []).append(row)

    earliest_by_site: Dict[str, Dict[str, str]] = {}
    duplicates_expected: List[Dict[str, str]] = []
    for sid, site_rows in by_site.items():
        # pick earliest planned_date
        parsed = [(r, _parse_date(r.get("planned_date", ""))) for r in site_rows]
        # if any date is None, fail gracefully by choosing lexicographically
        if any(p is None for (_, p) in parsed):
            site_rows_sorted = sorted(site_rows, key=lambda r: r.get("planned_date", ""))
            earliest = site_rows_sorted[0]
            rest = site_rows_sorted[1:]
        else:
            parsed.sort(key=lambda rp: rp[1])  # sort by date
            earliest = parsed[0][0]
            rest = [rp[0] for rp in parsed[1:]]
        earliest_by_site[sid] = earliest
        for r in rest:
            duplicates_expected.append(r)

    result["earliest_by_site"] = earliest_by_site
    result["duplicates_expected"] = duplicates_expected
    result["valid_unique_count"] = len(earliest_by_site)
    return result


def _parse_manifest_yaml(text: str) -> Optional[Dict]:
    if text is None:
        return None
    lines = text.splitlines()
    result: Dict[str, any] = {}
    i = 0
    n = len(lines)

    def is_indented(line: str) -> bool:
        return len(line) > 0 and (line[0] == " " or line[0] == "\t")

    while i < n:
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        if re.match(r"^datasets:\s*$", line):
            i += 1
            datasets = []
            current = None
            while i < n and (is_indented(lines[i]) or lines[i].lstrip().startswith("-")):
                l = lines[i]
                if l.lstrip().startswith("-"):
                    # Start a new dataset item
                    if current:
                        datasets.append(current)
                    current = {}
                    # Inline title
                    m = re.match(r"^\s*-\s*title:\s*(.+?)\s*$", l)
                    if m:
                        current["title"] = m.group(1).strip()
                else:
                    m = re.match(r"^\s*([A-Za-z_]+):\s*(.+?)\s*$", l)
                    if m and current is not None:
                        key = m.group(1).strip()
                        val = m.group(2).strip()
                        current[key] = val
                i += 1
            if current:
                datasets.append(current)
            result["datasets"] = datasets
            continue
        if re.match(r"^input:\s*$", line):
            i += 1
            inp = {}
            while i < n and is_indented(lines[i]):
                m = re.match(r"^\s*([A-Za-z_]+):\s*(.+?)\s*$", lines[i])
                if m:
                    inp[m.group(1).strip()] = m.group(2).strip()
                i += 1
            result["input"] = inp
            continue
        i += 1
    return result


def _validate_iso8601_utc(s: str) -> bool:
    if not s:
        return False
    # Accept YYYY-MM-DDTHH:MM:SSZ or with fractional seconds
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", s))


def _teams_to_set(teams_str: str) -> List[str]:
    if teams_str is None:
        return []
    parts = [p.strip() for p in teams_str.split(",")]
    return [p for p in parts if p]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_cli_presence": 0.0,
        "data_zip_downloads_present": 0.0,
        "invalid_sites_validation": 0.0,
        "duplicates_validation": 0.0,
        "enriched_structure_and_count": 0.0,
        "enriched_onshore_distance_rules": 0.0,
        "summary_by_country_consistency": 0.0,
        "manifest_structure_and_values": 0.0,
        "email_draft_content": 0.0,
    }

    # Check script presence and CLI arguments
    script_path = workspace / "scripts" / "enrich_sites.py"
    if script_path.exists():
        content = _read_text(script_path) or ""
        has_argparse = "argparse" in content
        has_input_flag = "--input" in content
        has_outdir_flag = "--outdir" in content
        has_datadir_flag = "--datadir" in content
        if has_argparse and has_input_flag and has_outdir_flag and has_datadir_flag:
            scores["script_cli_presence"] = 1.0

    # Compute expected invalid and duplicates based on input
    input_csv_path = workspace / "input" / "survey_sites.csv"
    expected = _compute_expected_from_input(input_csv_path)

    # Check data zip downloads in datadir
    datadir = workspace / "data"
    if datadir.exists() and datadir.is_dir():
        zips = list(datadir.rglob("*.zip"))
        lower_names = [p.name.lower() for p in zips]
        has_admin0 = any(("admin_0" in n or "admin0" in n) and "10m" in n for n in lower_names)
        has_admin1 = any(("admin_1" in n or "admin1" in n) and "10m" in n for n in lower_names)
        has_coastline = any(("coastline" in n) and "10m" in n for n in lower_names)
        if has_admin0 and has_admin1 and has_coastline:
            scores["data_zip_downloads_present"] = 1.0

    # Validate invalid_sites.csv
    invalid_path = workspace / "outputs" / "invalid_sites.csv"
    invalid_rows, invalid_header = _read_csv(invalid_path)
    if invalid_rows is not None and invalid_header is not None and expected["input_exists"]:
        # Must contain required columns
        required_cols = {"site_id", "latitude", "longitude", "planned_date", "team", "reason"}
        if set(invalid_header) >= required_cols:
            # Build set of invalid site_ids and ensure reason
            file_invalid_ids = set()
            valid_reason = True
            for r in invalid_rows:
                if r.get("site_id"):
                    file_invalid_ids.add(r["site_id"])
                if r.get("reason") != "invalid_lat_lon":
                    valid_reason = False
            if file_invalid_ids == expected["invalid_site_ids"] and valid_reason:
                scores["invalid_sites_validation"] = 1.0

    # Validate duplicates.csv
    duplicates_path = workspace / "outputs" / "duplicates.csv"
    dup_rows, dup_header = _read_csv(duplicates_path)
    if dup_rows is not None and dup_header is not None and expected["input_exists"]:
        required_cols = {"site_id", "latitude", "longitude", "planned_date", "team", "reason"}
        if set(dup_header) >= required_cols:
            # Expected duplicates by site_id and planned_date among valid rows
            exp = {(r.get("site_id", ""), r.get("planned_date", "")) for r in expected["duplicates_expected"]}
            got = {(r.get("site_id", ""), r.get("planned_date", "")) for r in dup_rows}
            reason_ok = all(r.get("reason") == "duplicate_site_id" for r in dup_rows)
            if exp == got and reason_ok:
                scores["duplicates_validation"] = 1.0

    # Validate enriched_sites.csv structure and count
    enriched_path = workspace / "outputs" / "enriched_sites.csv"
    enriched_rows, enriched_header = _read_csv(enriched_path)
    required_enriched_cols = [
        "site_id",
        "planned_date",
        "team",
        "latitude",
        "longitude",
        "country",
        "admin1",
        "onshore",
        "distance_km_to_coast",
    ]
    if enriched_rows is not None and enriched_header is not None and expected["input_exists"]:
        if enriched_header == required_enriched_cols:
            # Count should match valid unique count after dedup and invalid removal
            if len(enriched_rows) == expected["valid_unique_count"]:
                # Also ensure earliest entries kept for duplicates (S2, S7)
                earliest_ok = True
                for sid, earliest_row in expected["earliest_by_site"].items():
                    # Find row in enriched
                    match = [r for r in enriched_rows if r.get("site_id") == sid]
                    if len(match) != 1:
                        earliest_ok = False
                        break
                    if match[0].get("planned_date") != earliest_row.get("planned_date"):
                        earliest_ok = False
                        break
                if earliest_ok:
                    scores["enriched_structure_and_count"] = 1.0

    # Validate onshore/offshore rules and distance formatting
    if scores["enriched_structure_and_count"] > 0 and enriched_rows is not None:
        onshore_zero_ok = True
        s8_offshore_ok = True
        s8_found = False
        for r in enriched_rows:
            onshore_val = _parse_bool(r.get("onshore", ""))
            dist_str = r.get("distance_km_to_coast", "")
            # Onshore must have 0.00 distance
            if onshore_val is True:
                if dist_str != "0.00":
                    onshore_zero_ok = False
            elif onshore_val is False:
                # For offshore, must be positive with two decimals
                # Specifically check S8
                if r.get("site_id") == "S8":
                    s8_found = True
                    # Country must be blank for offshore
                    if r.get("country", "").strip() != "":
                        s8_offshore_ok = False
                    # Admin1 should be blank (not strictly required, but check)
                    if r.get("admin1", "").strip() != "":
                        s8_offshore_ok = False
                    # Distance must be positive with two decimals
                    if not re.match(r"^\d+?\.\d{2}$", dist_str or ""):
                        s8_offshore_ok = False
                    else:
                        try:
                            val = float(dist_str)
                            if not (val > 0):
                                s8_offshore_ok = False
                        except Exception:
                            s8_offshore_ok = False
            else:
                onshore_zero_ok = False
        if onshore_zero_ok and s8_offshore_ok and s8_found:
            scores["enriched_onshore_distance_rules"] = 1.0

    # Validate summary_by_country.csv consistency with enriched onshore points
    summary_path = workspace / "outputs" / "summary_by_country.csv"
    summary_rows, summary_header = _read_csv(summary_path)
    if summary_rows is not None and summary_header is not None and enriched_rows is not None:
        required_summary_cols = ["country", "site_count", "teams", "avg_distance_km_to_coast"]
        if summary_header == required_summary_cols:
            # Compute expected summary from enriched onshore rows
            groups: Dict[str, Dict[str, any]] = {}
            for r in enriched_rows:
                if _parse_bool(r.get("onshore", "")) is True:
                    ctry = r.get("country", "")
                    groups.setdefault(ctry, {"count": 0, "teams": set()})
                    groups[ctry]["count"] += 1
                    t = r.get("team", "")
                    if t:
                        groups[ctry]["teams"].add(t)
            # Build dict from summary file
            summary_ok = True
            file_groups: Dict[str, Dict[str, any]] = {}
            for sr in summary_rows:
                c = sr.get("country", "")
                sc = sr.get("site_count", "")
                teams = sr.get("teams", "")
                avg = sr.get("avg_distance_km_to_coast", "")
                # avg must be 0.00 for onshore
                if avg != "0.00":
                    summary_ok = False
                    break
                # site_count must be int and match
                try:
                    sc_int = int(sc)
                except Exception:
                    summary_ok = False
                    break
                file_groups[c] = {
                    "count": sc_int,
                    "teams": set(_teams_to_set(teams)),
                }
            # Compare groups
            if summary_ok and file_groups.keys() == groups.keys():
                for k in groups.keys():
                    if groups[k]["count"] != file_groups[k]["count"]:
                        summary_ok = False
                        break
                    if groups[k]["teams"] != file_groups[k]["teams"]:
                        summary_ok = False
                        break
            if summary_ok:
                scores["summary_by_country_consistency"] = 1.0

    # Validate manifest structure and values
    manifest_path = workspace / "outputs" / "data_sources.yaml"
    manifest_text = _read_text(manifest_path)
    manifest = _parse_manifest_yaml(manifest_text) if manifest_text is not None else None
    if manifest is not None:
        datasets = manifest.get("datasets")
        inp = manifest.get("input")
        manifest_ok = True
        # Datasets must be present
        if not isinstance(datasets, list) or len(datasets) < 3:
            manifest_ok = False
        else:
            # Check required items and fields
            # Try to identify titles
            titles = [d.get("title", "") for d in datasets]
            # Must include Admin 0 Countries, Admin 1 States and Provinces, and Coastline
            def has_admin0(ts: List[str]) -> bool:
                return any(("admin 0" in t.lower() and "countries" in t.lower()) for t in ts)

            def has_admin1(ts: List[str]) -> bool:
                t_low = [t.lower() for t in ts]
                return any(("admin 1" in t and "states" in t and "provinces" in t) for t in t_low)

            def has_coastline(ts: List[str]) -> bool:
                return any(("coastline" in t.lower()) for t in ts)

            if not (has_admin0(titles) and has_admin1(titles) and has_coastline(titles)):
                manifest_ok = False

            for d in datasets:
                if d.get("scale") != "1:10m":
                    manifest_ok = False
                    break
                if d.get("source_org") != "Natural Earth":
                    manifest_ok = False
                    break
                if not _validate_iso8601_utc(d.get("download_datetime", "")):
                    manifest_ok = False
                    break
                local_path = d.get("local_path", "")
                # local_path must exist relative to workspace
                if not local_path:
                    manifest_ok = False
                    break
                lp = workspace / local_path
                if not lp.exists():
                    manifest_ok = False
                    break

        # Input block must have file and valid_rows_after_dedup
        if not isinstance(inp, dict):
            manifest_ok = False
        else:
            if inp.get("file") != "input/survey_sites.csv":
                manifest_ok = False
            else:
                v = inp.get("valid_rows_after_dedup", "")
                try:
                    v_int = int(str(v).strip())
                except Exception:
                    manifest_ok = False
                else:
                    if expected["input_exists"]:
                        if v_int != expected["valid_unique_count"]:
                            manifest_ok = False
        if manifest_ok:
            scores["manifest_structure_and_values"] = 1.0

    # Validate email draft content
    email_path = workspace / "outputs" / "email_draft.txt"
    email_text = _read_text(email_path)
    if email_text is not None and expected["input_exists"] and summary_rows is not None:
        ok = True
        # Must include total number of valid unique sites processed
        if str(expected["valid_unique_count"]) not in email_text:
            ok = False
        # Must include relative paths to enriched and summary
        if "outputs/enriched_sites.csv" not in email_text or "outputs/summary_by_country.csv" not in email_text:
            ok = False
        # Must include Natural Earth and 1:10m
        if "Natural Earth" not in email_text or "1:10m" not in email_text:
            ok = False
        # Must include a processing date (detect YYYY-MM-DD)
        if not re.search(r"\b\d{4}-\d{2}-\d{2}\b", email_text):
            ok = False
        # Must include a table-like section with first five lines of summary_by_country.csv
        # We will check the presence of these lines in order.
        summary_raw = (workspace / "outputs" / "summary_by_country.csv").read_text(encoding="utf-8").splitlines()
        first_five = summary_raw[:5] if len(summary_raw) >= 5 else summary_raw
        # Check ordered occurrence
        idx = 0
        for line in first_five:
            pos = email_text.find(line)
            if pos == -1:
                ok = False
                break
            # Reduce email_text to substring after found position to enforce order
            email_text = email_text[pos + len(line):]
            idx += 1
        if ok:
            scores["email_draft_content"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    _write_json_stdout(result)


if __name__ == "__main__":
    main()