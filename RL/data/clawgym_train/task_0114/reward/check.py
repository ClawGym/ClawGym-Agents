import csv
import json
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    items: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def _parse_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip()
        if s == "" or s.lower() == "null" or s.lower() == "none":
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _safe_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        # accept whole floats
        if abs(x - int(x)) < 1e-9:
            return int(x)
        return None
    if isinstance(x, str):
        s = x.strip()
        if s == "" or s.lower() == "null" or s.lower() == "none":
            return None
        try:
            return int(s)
        except Exception:
            # try float-to-int if whole
            try:
                fx = float(s)
                if abs(fx - int(fx)) < 1e-9:
                    return int(fx)
            except Exception:
                pass
            return None
    return None


def _safe_bool(x: Any) -> Optional[bool]:
    if x is None:
        return None
    if isinstance(x, bool):
        return x
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("true", "t", "1", "yes"):
            return True
        if s in ("false", "f", "0", "no"):
            return False
    return None


def _almost_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _domain_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return None


def _domain_match(source_domain: str, url: str) -> bool:
    sd = (source_domain or "").lower().strip()
    nd = _domain_from_url(url) or ""
    if sd == "" or nd == "":
        return False
    if sd == nd:
        return True
    if nd.endswith("." + sd):
        return True
    if sd.endswith("." + nd):
        return True
    return False


def _is_regulator_domain(name: str) -> bool:
    # Accept known regulators or any .gov (but exclude clinicaltrials.gov and ncbi.nlm.nih.gov)
    n = name.lower()
    if n in ("clinicaltrials.gov", "ncbi.nlm.nih.gov"):
        return False
    if "fda.gov" in n:
        return True
    if n.endswith(".gov") or ".gov." in n:
        return True
    if n.endswith(".gov.uk"):
        return True
    if "ema.europa.eu" in n:
        return True
    return False


def _validate_record_against_schema(record: Dict[str, Any], schema: Dict[str, Any]) -> bool:
    # Check required keys
    required = schema.get("required", [])
    props = schema.get("properties", {})
    for key in required:
        if key not in record:
            return False
    # Type validation for properties we know
    for key, spec in props.items():
        expected_types = spec.get("type")
        if expected_types is None:
            continue
        if not isinstance(expected_types, list):
            expected_types = [expected_types]
        val = record.get(key, None)
        # Map JSON types to Python checks
        ok = False
        for et in expected_types:
            if et == "null" and val is None:
                ok = True
            elif et == "string" and isinstance(val, str):
                ok = True
            elif et == "boolean" and isinstance(val, bool):
                ok = True
            elif et == "integer" and isinstance(val, int):
                ok = True
            elif et == "number" and isinstance(val, (int, float)):
                ok = True
        if not ok:
            # Allow numbers represented as numeric strings when not strict? The spec says JSON, so be strict.
            return False
    # Additional range checks for rates if present
    sae = record.get("serious_adverse_event_rate", None)
    if sae is not None:
        if not isinstance(sae, (int, float)):
            return False
        if not (0.0 <= float(sae) <= 1.0):
            return False
    dr = record.get("dropout_rate", None)
    if dr is not None:
        if not isinstance(dr, (int, float)):
            return False
        if not (0.0 <= float(dr) <= 1.0):
            return False
    ssz = record.get("sample_size_total", None)
    if ssz is not None:
        if not isinstance(ssz, int):
            return False
        if ssz < 0:
            return False
    # URL-domain consistency
    url = record.get("url", "")
    sd = record.get("source_domain", "")
    if not isinstance(url, str) or not isinstance(sd, str) or not _domain_match(sd, url):
        return False
    return True


def _compute_group_stats(records: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    by_source: Dict[str, Dict[str, Any]] = {}
    for r in records:
        src = r.get("source_domain", None)
        if not isinstance(src, str):
            continue
        group = by_source.setdefault(src, {"count": 0, "sae_values": [], "drop_values": [], "sample_sizes": []})
        group["count"] += 1
        sae = r.get("serious_adverse_event_rate", None)
        if isinstance(sae, (int, float)):
            group["sae_values"].append(float(sae))
        dr = r.get("dropout_rate", None)
        if isinstance(dr, (int, float)):
            group["drop_values"].append(float(dr))
        ssz = r.get("sample_size_total", None)
        if isinstance(ssz, int):
            group["sample_sizes"].append(int(ssz))
    # Build summary rows
    group_rows: Dict[str, Dict[str, Any]] = {}
    for src, g in by_source.items():
        count = g["count"]
        sae_mean = sum(g["sae_values"]) / len(g["sae_values"]) if g["sae_values"] else None
        drop_mean = sum(g["drop_values"]) / len(g["drop_values"]) if g["drop_values"] else None
        total_ssz = sum(g["sample_sizes"]) if g["sample_sizes"] else 0
        group_rows[src] = {
            "count_of_records": count,
            "mean_serious_adverse_event_rate": sae_mean,
            "mean_dropout_rate": drop_mean,
            "total_sample_size": total_ssz,
        }
    # Overall
    all_sae: List[float] = []
    all_drop: List[float] = []
    all_ssz: List[int] = []
    for r in records:
        sae = r.get("serious_adverse_event_rate", None)
        if isinstance(sae, (int, float)):
            all_sae.append(float(sae))
        dr = r.get("dropout_rate", None)
        if isinstance(dr, (int, float)):
            all_drop.append(float(dr))
        ssz = r.get("sample_size_total", None)
        if isinstance(ssz, int):
            all_ssz.append(int(ssz))
    overall = {
        "total_records": len(records),
        "mean_serious_adverse_event_rate": (sum(all_sae) / len(all_sae)) if all_sae else None,
        "mean_dropout_rate": (sum(all_drop) / len(all_drop)) if all_drop else None,
        "total_sample_size": sum(all_ssz) if all_ssz else 0,
    }
    return group_rows, overall


def _load_schema(workspace: Path) -> Optional[Dict[str, Any]]:
    schema_path = workspace / "input" / "schema.json"
    return _load_json(schema_path)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "raw_clinicaltrials_saved": 0.0,
        "raw_pubmed_saved": 0.0,
        "raw_regulator_saved": 0.0,
        "search_log_structure_and_coverage": 0.0,
        "extracted_jsonl_valid": 0.0,
        "extracted_csv_valid": 0.0,
        "extracted_deduplicated": 0.0,
        "summaries_consistent_with_extracted": 0.0,
        "ranking_top_concerns_valid": 0.0,
        "ranking_low_evidence_flags_coverage": 0.0,
        "validate_script_runs_and_outputs": 0.0,
        "draft_email_content": 0.0,
    }

    # Paths
    search_terms_path = workspace / "input" / "search_terms.txt"
    schema = _load_schema(workspace)
    sample_records_csv = workspace / "input" / "sample_records.csv"
    email_recipients_csv = workspace / "input" / "email_recipients.csv"

    search_log_path = workspace / "output" / "search" / "search_log.jsonl"
    raw_base = workspace / "output" / "raw"
    extracted_jsonl_path = workspace / "output" / "extracted" / "studies.jsonl"
    extracted_csv_path = workspace / "output" / "extracted" / "studies.csv"
    stats_by_source_path = workspace / "output" / "summary" / "stats_by_source.csv"
    stats_overall_path = workspace / "output" / "summary" / "stats_overall.json"
    top_concerns_path = workspace / "output" / "ranked" / "top_concerns.csv"
    low_evidence_flags_path = workspace / "output" / "ranked" / "low_evidence_flags.csv"
    draft_email_path = workspace / "output" / "report" / "draft_email.txt"
    validate_script_path = workspace / "scripts" / "validate.py"
    validation_report_path = workspace / "output" / "validation" / "report.txt"
    validation_ranking_path = workspace / "output" / "validation" / "ranking_on_sample.txt"

    # 1) Search log structure and coverage
    search_terms: List[str] = []
    if search_terms_path.exists():
        txt = _read_text(search_terms_path)
        if txt is not None:
            search_terms = [line.strip() for line in txt.splitlines() if line.strip() != ""]

    log_items = _parse_jsonl(search_log_path) or []
    query_coverage_ok = True
    structure_ok = True
    downloaded_domains: set = set()
    if not log_items or not search_terms:
        structure_ok = False
        query_coverage_ok = False
    else:
        # Coverage
        queries_in_log = [item.get("query_string", "") for item in log_items if isinstance(item, dict)]
        for q in search_terms:
            if q not in queries_in_log:
                query_coverage_ok = False
                break
        # Structure
        for item in log_items:
            if not isinstance(item, dict):
                structure_ok = False
                break
            if "query_string" not in item or "timestamp" not in item or "engine_name" not in item or "considered_results" not in item:
                structure_ok = False
                break
            cr = item.get("considered_results", [])
            if not isinstance(cr, list):
                structure_ok = False
                break
            for res in cr:
                if not isinstance(res, dict):
                    structure_ok = False
                    break
                if "title" not in res or "url" not in res or "source_domain" not in res or "downloaded" not in res:
                    structure_ok = False
                    break
                if not isinstance(res.get("downloaded"), bool):
                    structure_ok = False
                    break
                if res.get("downloaded"):
                    sd = res.get("source_domain", "")
                    if isinstance(sd, str):
                        downloaded_domains.add(sd)
            if not structure_ok:
                break
    if structure_ok and query_coverage_ok:
        scores["search_log_structure_and_coverage"] = 1.0

    # 2) Raw files per domain
    def _domain_dir_ok(domain_name: str) -> bool:
        d = raw_base / domain_name
        if not d.exists() or not d.is_dir():
            return False
        ok_file = False
        for p in d.rglob("*"):
            if p.is_file() and p.stat().st_size > 0 and p.suffix.lower() in (".html", ".json", ".xml"):
                ok_file = True
                break
        if not ok_file:
            return False
        # Cross-check against downloaded domains in search log
        # Accept match if exact or any downloaded domain matches equality or parent/child.
        for dd in downloaded_domains:
            if dd == domain_name or dd.endswith("." + domain_name) or domain_name.endswith("." + dd):
                return True
        # If no search log or no downloaded flags, be strict: require match; else fail
        return False

    if _domain_dir_ok("clinicaltrials.gov"):
        scores["raw_clinicaltrials_saved"] = 1.0
    if _domain_dir_ok("ncbi.nlm.nih.gov"):
        scores["raw_pubmed_saved"] = 1.0
    # Regulator: find any domain directory matching regulator criteria and check it
    regulator_ok = False
    if raw_base.exists():
        for child in raw_base.iterdir():
            if child.is_dir() and _is_regulator_domain(child.name):
                if _domain_dir_ok(child.name):
                    regulator_ok = True
                    break
    if regulator_ok:
        scores["raw_regulator_saved"] = 1.0

    # 3) Extracted files validation
    records_jsonl = _parse_jsonl(extracted_jsonl_path)
    schema_ok = bool(schema and isinstance(schema, dict) and "properties" in schema)
    extracted_jsonl_ok = False
    extracted_records: List[Dict[str, Any]] = []
    if schema_ok and records_jsonl is not None and len(records_jsonl) > 0:
        all_ok = True
        for rec in records_jsonl:
            if not _validate_record_against_schema(rec, schema):  # strict schema check with ranges and domain check
                all_ok = False
                break
        if all_ok:
            extracted_jsonl_ok = True
            extracted_records = records_jsonl
    if extracted_jsonl_ok:
        scores["extracted_jsonl_valid"] = 1.0

    # CSV extracted file check
    csv_ok = False
    csv_rows = _parse_csv(extracted_csv_path)
    if csv_rows is not None and len(csv_rows) == len(extracted_records) and schema_ok:
        headers = []
        try:
            with extracted_csv_path.open("r", encoding="utf-8", newline="") as f:
                headers = list(csv.DictReader(f).fieldnames or [])
        except Exception:
            headers = []
        schema_props = list(schema["properties"].keys())
        missing_cols = [c for c in schema_props if c not in headers]
        if not missing_cols:
            # Check that IDs set matches between csv and jsonl
            ids_csv = {row.get("id", "") for row in csv_rows}
            ids_jsonl = {rec.get("id", "") for rec in extracted_records}
            if ids_csv == ids_jsonl:
                csv_ok = True
    if csv_ok:
        scores["extracted_csv_valid"] = 1.0

    # Dedup by id and url
    dedup_ok = False
    if extracted_records:
        ids = [rec.get("id") for rec in extracted_records]
        urls = [rec.get("url") for rec in extracted_records]
        if len(ids) == len(set(ids)) and len(urls) == len(set(urls)):
            dedup_ok = True
    if dedup_ok:
        scores["extracted_deduplicated"] = 1.0

    # 4) Summaries consistency
    summaries_ok = False
    if extracted_records:
        group_stats, overall_stats = _compute_group_stats(extracted_records)
        # Check stats_by_source.csv
        by_source_rows = _parse_csv(stats_by_source_path)
        stats_overall = _load_json(stats_overall_path)
        by_source_ok = False
        overall_ok = False
        if by_source_rows is not None:
            # Build mapping from file
            file_map: Dict[str, Dict[str, Any]] = {}
            for row in by_source_rows:
                src = (row.get("source_domain") or row.get("source") or "").strip()
                if not src:
                    continue
                file_map[src] = {
                    "count_of_records": _safe_int(row.get("count_of_records")),
                    "mean_serious_adverse_event_rate": _safe_float(row.get("mean_serious_adverse_event_rate")),
                    "mean_dropout_rate": _safe_float(row.get("mean_dropout_rate")),
                    "total_sample_size": _safe_int(row.get("total_sample_size")),
                }
            if set(file_map.keys()) == set(group_stats.keys()):
                comp_ok = True
                for src, expected in group_stats.items():
                    got = file_map.get(src, {})
                    if _safe_int(got.get("count_of_records")) != expected["count_of_records"]:
                        comp_ok = False
                        break
                    if not _almost_equal(_safe_float(got.get("mean_serious_adverse_event_rate")), expected["mean_serious_adverse_event_rate"]):
                        comp_ok = False
                        break
                    if not _almost_equal(_safe_float(got.get("mean_dropout_rate")), expected["mean_dropout_rate"]):
                        comp_ok = False
                        break
                    if _safe_int(got.get("total_sample_size")) != expected["total_sample_size"]:
                        comp_ok = False
                        break
                by_source_ok = comp_ok
        if isinstance(stats_overall, dict):
            tr = stats_overall.get("total_records")
            ms = stats_overall.get("mean_serious_adverse_event_rate")
            md = stats_overall.get("mean_dropout_rate")
            ts = stats_overall.get("total_sample_size")
            if (
                isinstance(tr, int)
                and (isinstance(ms, (int, float)) or ms is None)
                and (isinstance(md, (int, float)) or md is None)
                and isinstance(ts, int)
                and tr == overall_stats["total_records"]
                and _almost_equal(_safe_float(ms), overall_stats["mean_serious_adverse_event_rate"])
                and _almost_equal(_safe_float(md), overall_stats["mean_dropout_rate"])
                and ts == overall_stats["total_sample_size"]
            ):
                overall_ok = True
        summaries_ok = by_source_ok and overall_ok
    if summaries_ok:
        scores["summaries_consistent_with_extracted"] = 1.0

    # 5) Ranking validation
    ranking_ok = False
    low_evidence_ok = False
    top_rows = _parse_csv(top_concerns_path) or []
    low_rows = _parse_csv(low_evidence_flags_path) or []
    if top_rows:
        # Check columns include schema fields plus 'rank'
        top_headers = []
        try:
            with top_concerns_path.open("r", encoding="utf-8", newline="") as f:
                top_headers = list(csv.DictReader(f).fieldnames or [])
        except Exception:
            top_headers = []
        schema_cols = list(schema["properties"].keys()) if schema_ok else []
        if all(c in top_headers for c in schema_cols) and "rank" in top_headers:
            # Check length <= 10
            if len(top_rows) <= 10:
                # Validate filtered criteria and sort order
                ranks = []
                sort_tuples: List[Tuple[float, float, int]] = []
                include_ok = True
                for i, row in enumerate(top_rows):
                    rstr = row.get("rank", "")
                    r = _safe_int(rstr)
                    if r is None or r != i:
                        include_ok = False
                        break
                    ranks.append(r)
                    ir = _safe_bool(row.get("is_randomized"))
                    sae = _safe_float(row.get("serious_adverse_event_rate"))
                    dr = _safe_float(row.get("dropout_rate"))
                    ssz = _safe_int(row.get("sample_size_total"))
                    if ir is not True or sae is None:
                        include_ok = False
                        break
                    if dr is None:
                        dr = -1.0
                    if ssz is None:
                        ssz = -1
                    sort_tuples.append((float(sae), float(dr), int(ssz)))
                # Check descending order
                if include_ok:
                    sorted_ok = True
                    for i in range(1, len(sort_tuples)):
                        if sort_tuples[i] > sort_tuples[i - 1]:
                            # Should be descending; compare tuples reversed sign; Instead check not greater than previous
                            sorted_ok = False
                            break
                        # Alternatively, ensure custom compare: prev >= curr in lexicographic desc
                        prev = sort_tuples[i - 1]
                        curr = sort_tuples[i]
                        if not (prev[0] > curr[0] or (prev[0] == curr[0] and (prev[1] > curr[1] or (prev[1] == curr[1] and prev[2] >= curr[2])))):
                            # if prev not >= curr under desc, fail
                            sorted_ok = False
                            break
                    if sorted_ok:
                        # Ensure IDs subset of extracted IDs
                        if extracted_records:
                            ids_top = {row.get("id", "") for row in top_rows}
                            ids_ext = {rec.get("id", "") for rec in extracted_records}
                            if ids_top.issubset(ids_ext):
                                ranking_ok = True
                        else:
                            # If we can't cross-check, accept as long as sort is ok
                            ranking_ok = True
    if ranking_ok:
        scores["ranking_top_concerns_valid"] = 1.0

    # Low evidence flags coverage: ensure all records excluded by criteria are present
    if low_rows is not None:
        low_ids = {row.get("id", "") for row in low_rows}
        reasons_present = all((row.get("reason", "") or "").strip() != "" for row in low_rows) if low_rows else True
        if extracted_records:
            excluded_ids = set()
            for rec in extracted_records:
                ir = rec.get("is_randomized", None) is True
                sae = rec.get("serious_adverse_event_rate", None)
                if not (ir and isinstance(sae, (int, float))):
                    excluded_ids.add(rec.get("id", ""))
            if excluded_ids.issubset(low_ids) and reasons_present:
                low_evidence_ok = True
        else:
            # If no extracted records, consider not ok
            low_evidence_ok = False
    if low_evidence_ok:
        scores["ranking_low_evidence_flags_coverage"] = 1.0

    # 6) Validate script run and outputs
    validate_ok = False
    if validate_script_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(validate_script_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
            rc_ok = (proc.returncode == 0)
        except Exception:
            rc_ok = False
        # Check outputs exist
        files_ok = validation_report_path.exists() and validation_ranking_path.exists()
        # Additionally verify ranking_on_sample.txt ordering matches expected
        expected_ids: List[str] = []
        sample_rows = _parse_csv(sample_records_csv) or []
        if sample_rows:
            # Build list of tuples (sae desc, dropout desc, sample size desc)
            tuples = []
            for row in sample_rows:
                sid = row.get("study_id", "")
                sae = _safe_float(row.get("serious_adverse_event_rate"))
                dr = _safe_float(row.get("dropout_rate"))
                ssz = _safe_int(row.get("sample_size_total"))
                if sae is None or dr is None or ssz is None:
                    tuples.append((sid, -1.0, -1.0, -1))
                else:
                    tuples.append((sid, float(sae), float(dr), int(ssz)))
            tuples_sorted = sorted(tuples, key=lambda x: (-x[1], -x[2], -x[3]))
            expected_ids = [t[0] for t in tuples_sorted]
        if validation_ranking_path.exists():
            txt = _read_text(validation_ranking_path) or ""
            got_ids = [line.strip() for line in txt.splitlines() if line.strip() != ""]
            ranking_check_ok = (expected_ids == got_ids) if expected_ids else False
        else:
            ranking_check_ok = False
        if rc_ok and files_ok and ranking_check_ok:
            validate_ok = True
    if validate_ok:
        scores["validate_script_runs_and_outputs"] = 1.0

    # 7) Draft email content
    email_ok = False
    email_txt = _read_text(draft_email_path) or ""
    recipients_ok = False
    recipients_rows = _parse_csv(email_recipients_csv) or []
    if email_txt and recipients_rows:
        emails = [row.get("email", "") for row in recipients_rows if row.get("email", "")]
        if emails and all(e in email_txt for e in emails):
            recipients_ok = True
    # Check mentions of ranking criteria
    criteria_ok = False
    if email_txt:
        crit_terms = ["serious adverse event", "SAE", "dropout"]
        if any(term.lower() in email_txt.lower() for term in crit_terms) and ("rank" in email_txt.lower() or "descending" in email_txt.lower()):
            criteria_ok = True
    # Check top 3 items mentioned
    top3_ok = False
    if top_rows and email_txt:
        top3_ids = [row.get("id", "") for row in top_rows[:3] if row.get("id", "")]
        if top3_ids and all((tid in email_txt) for tid in top3_ids):
            top3_ok = True
    # Check sources and counts mentioned
    sources_ok = False
    counts_ok = False
    if stats_by_source_path.exists() and email_txt:
        by_source_rows = _parse_csv(stats_by_source_path) or []
        domains = []
        counts = []
        for row in by_source_rows:
            dom = row.get("source_domain") or row.get("source") or ""
            if dom:
                domains.append(dom)
            cnt = _safe_int(row.get("count_of_records"))
            if cnt is not None:
                counts.append(str(cnt))
        if domains and all(d in email_txt for d in domains):
            sources_ok = True
        if counts and all(c in email_txt for c in counts):
            counts_ok = True
    if recipients_ok and criteria_ok and top3_ok and sources_ok and counts_ok:
        email_ok = True
    if email_ok:
        scores["draft_email_content"] = 1.0

    return scores


def main() -> None:
        workspace_path = "."
        if len(sys.argv) >= 2:
            workspace_path = sys.argv[1]
        result = grade(transcript=[], workspace_path=workspace_path)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()