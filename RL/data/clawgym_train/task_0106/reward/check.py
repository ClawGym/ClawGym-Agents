import json
import sys
import csv
import re
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        body = rows[1:] if len(rows) > 1 else []
        return header, body
    except Exception:
        return None, None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_bool(s: str) -> Optional[bool]:
    s = s.strip().lower()
    if s in ("true", "yes"):
        return True
    if s in ("false", "no"):
        return False
    return None


def _parse_queries_yaml_minimal(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal, ad-hoc parser for the specific structure of input/queries.yaml provided.
    Returns dict with keys: queries (list of dicts), output_paths (dict), constraints (dict).
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()

    data: Dict[str, Any] = {"queries": [], "output_paths": {}, "constraints": {}}
    section = None
    current_query: Optional[Dict[str, Any]] = None
    in_domains = False

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Top-level sections
        if not line.startswith(" ") and stripped.endswith(":"):
            key = stripped[:-1].strip()
            if key in ("queries", "output_paths", "constraints"):
                section = key
                continue

        if section == "queries":
            # New query item
            m_q = re.match(r'^\s*-\s*query\s*:\s*(".*"|\'[^\']*\')\s*$', line)
            if m_q:
                if current_query is not None:
                    data["queries"].append(current_query)
                qval = _strip_quotes(m_q.group(1))
                current_query = {"query": qval, "allowed_domains": [], "max_per_query": None}
                in_domains = False
                continue

            # allowed_domains section
            if re.match(r'^\s*allowed_domains\s*:\s*$', line):
                in_domains = True
                continue

            if in_domains:
                m_dom = re.match(r'^\s*-\s*(".*"|\'[^\']*\')\s*$', line)
                if m_dom and current_query is not None:
                    dval = _strip_quotes(m_dom.group(1))
                    current_query["allowed_domains"].append(dval)
                    continue
                # If we encounter something else, stop domains mode
                # but we don't continue to avoid missing parsing of next fields
                in_domains = False

            # max_per_query
            m_max = re.match(r'^\s*max_per_query\s*:\s*(\d+)\s*$', line)
            if m_max and current_query is not None:
                current_query["max_per_query"] = int(m_max.group(1))
                continue

        elif section == "output_paths":
            m_kv = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*(".*"|\'[^\']*\')\s*$', line)
            if m_kv:
                key = m_kv.group(1)
                val = _strip_quotes(m_kv.group(2))
                data["output_paths"][key] = val
                continue

        elif section == "constraints":
            m_int = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*(\d+)\s*$', line)
            if m_int:
                key = m_int.group(1)
                data["constraints"][key] = int(m_int.group(2))
                continue
            m_bool = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*(true|false|True|False|yes|no)\s*$', line)
            if m_bool:
                key = m_bool.group(1)
                b = _parse_bool(m_bool.group(2))
                data["constraints"][key] = b
                continue

    if section == "queries" and current_query is not None:
        data["queries"].append(current_query)

    # Validate minimal structure
    if not isinstance(data.get("queries"), list):
        return None
    return data


def _normalize_domain(domain: str) -> str:
    d = domain.strip().lower()
    # remove port if present
    if ":" in d:
        d = d.split(":", 1)[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def _extract_domain_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        host = parsed.netloc
        if not host:
            return None
        return _normalize_domain(host)
    except Exception:
        return None


def _is_isoformat_datetime(s: str) -> bool:
    if not isinstance(s, str):
        return False
    t = s.strip()
    if not t:
        return False
    # Accept plain date YYYY-MM-DD or full datetime; handle 'Z' as UTC.
    candidate = t
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        # Try datetime parse
        datetime.fromisoformat(candidate)
        return True
    except Exception:
        # Try date only
        try:
            datetime.fromisoformat(candidate + "T00:00:00")
            return True
        except Exception:
            return False


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child_res = child.resolve()
        parent_res = parent.resolve()
        return str(child_res).startswith(str(parent_res) + str(Path.sep)) or child_res == parent_res
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Initialize score keys
    scores = {
        "results_json_present": 0.0,
        "min_total_entries_satisfied": 0.0,
        "schema_validation_passed": 0.0,
        "fields_and_types_valid": 0.0,
        "retrieval_date_and_publication_year_valid": 0.0,
        "content_files_cached": 0.0,
        "query_values_valid": 0.0,
        "official_domain_constraints_respected": 0.0,
        "result_url_and_source_domain_consistent": 0.0,
        "per_query_max_respected": 0.0,
        "domain_stats_csv_header_valid": 0.0,
        "domain_stats_match": 0.0,
        "validation_report_present": 0.0,
        "validation_report_indicates_success": 0.0,
        "organization_field_nonempty": 0.0,
    }

    # Load configuration files
    queries_yaml_path = workspace / "input" / "queries.yaml"
    schema_json_path = workspace / "input" / "schema.json"

    cfg = _parse_queries_yaml_minimal(queries_yaml_path)
    # Derive expected output paths with fallbacks
    default_results_json = workspace / "workspace" / "output" / "search_results.json"
    default_domain_csv = workspace / "workspace" / "output" / "domain_stats.csv"
    default_webcache_dir = workspace / "workspace" / "webcache"
    default_test_report = workspace / "workspace" / "reports" / "test_report.txt"

    if cfg and "output_paths" in cfg:
        op = cfg["output_paths"]
        results_json_path = workspace / op.get("results_json", str(default_results_json))
        domain_csv_path = workspace / op.get("domain_stats_csv", str(default_domain_csv))
        webcache_dir = workspace / op.get("webcache_dir", str(default_webcache_dir))
        validation_report_path = workspace / op.get("test_report", str(default_test_report))
    else:
        results_json_path = default_results_json
        domain_csv_path = default_domain_csv
        webcache_dir = default_webcache_dir
        validation_report_path = default_test_report

    # Constraints
    min_total_entries = 3
    if cfg and "constraints" in cfg and isinstance(cfg["constraints"].get("min_total_entries"), int):
        min_total_entries = cfg["constraints"]["min_total_entries"]

    # Allowed queries and domains mapping
    query_to_allowed_domains: Dict[str, List[str]] = {}
    query_to_max: Dict[str, Optional[int]] = {}
    if cfg and isinstance(cfg.get("queries"), list):
        for q in cfg["queries"]:
            qtext = q.get("query")
            adoms = q.get("allowed_domains") or []
            if isinstance(qtext, str) and isinstance(adoms, list):
                query_to_allowed_domains[qtext] = adoms
                query_to_max[qtext] = q.get("max_per_query", None)

    # Load schema
    schema = _load_json(schema_json_path)
    schema_fields: Dict[str, str] = {}
    required_fields: List[str] = []
    if isinstance(schema, dict):
        if isinstance(schema.get("fields"), dict):
            schema_fields = schema["fields"]
        if isinstance(schema.get("required_fields"), list):
            required_fields = list(schema["required_fields"])

    # Load results json
    results = _load_json(results_json_path)
    if isinstance(results, list):
        scores["results_json_present"] = 1.0
    else:
        # If results missing or malformed, many subsequent checks cannot proceed.
        return scores

    # min_total_entries_satisfied
    if len(results) >= min_total_entries:
        scores["min_total_entries_satisfied"] = 1.0

    # schema_validation_passed and fields_and_types_valid
    def _validate_type(val: Any, type_decl: str) -> bool:
        if type_decl == "string":
            return isinstance(val, str)
        if type_decl == "integer":
            return isinstance(val, int)
        if type_decl == "integer|null":
            return isinstance(val, int) or val is None
        if type_decl == "string|null":
            return isinstance(val, str) or val is None
        # default: accept
        return True

    schema_ok = True
    fields_types_ok = True
    for idx, item in enumerate(results):
        if not isinstance(item, dict):
            schema_ok = False
            fields_types_ok = False
            break
        # required fields present
        for rf in required_fields:
            if rf not in item:
                schema_ok = False
        # field types as per schema_fields
        for fkey, ftype in schema_fields.items():
            if fkey in item:
                if not _validate_type(item[fkey], ftype):
                    fields_types_ok = False
            else:
                # If a non-required field absent, it's okay. If required, handled above.
                pass
        # Additionally ensure some structural expectations for string fields where applicable
        # but keep within schema pass: only type checking
    if required_fields and schema_fields and schema_ok:
        scores["schema_validation_passed"] = 1.0
    if fields_types_ok:
        scores["fields_and_types_valid"] = 1.0

    # retrieval_date_and_publication_year_valid
    now_year = datetime.utcnow().year
    date_year_ok = True
    for item in results:
        if not isinstance(item, dict):
            date_year_ok = False
            break
        rd = item.get("retrieval_date")
        if not _is_isoformat_datetime(rd):
            date_year_ok = False
            break
        py = item.get("publication_year", None)
        if py is not None:
            if not isinstance(py, int) or py < 1900 or py > now_year + 1:
                date_year_ok = False
                break
    if date_year_ok:
        scores["retrieval_date_and_publication_year_valid"] = 1.0

    # content_files_cached
    content_ok = True
    for item in results:
        if not isinstance(item, dict):
            content_ok = False
            break
        cpath = item.get("content_path")
        if not isinstance(cpath, str):
            content_ok = False
            break
        target = (workspace / cpath) if not Path(cpath).is_absolute() else Path(cpath)
        if not target.exists():
            content_ok = False
            break
        if not _is_within(target, webcache_dir):
            content_ok = False
            break
    if content_ok:
        scores["content_files_cached"] = 1.0

    # organization_field_nonempty
    org_ok = True
    for item in results:
        org = item.get("organization")
        if not isinstance(org, str) or not org.strip():
            org_ok = False
            break
    if org_ok:
        scores["organization_field_nonempty"] = 1.0

    # query_values_valid
    if query_to_allowed_domains:
        qvals_ok = True
        allowed_queries_set = set(query_to_allowed_domains.keys())
        for item in results:
            qv = item.get("query")
            if qv not in allowed_queries_set:
                qvals_ok = False
                break
        if qvals_ok:
            scores["query_values_valid"] = 1.0

    # official_domain_constraints_respected and result_url_and_source_domain_consistent
    domains_ok = True
    url_vs_source_ok = True
    if query_to_allowed_domains:
        for item in results:
            if not isinstance(item, dict):
                domains_ok = False
                url_vs_source_ok = False
                break
            qv = item.get("query")
            item_source_domain = item.get("source_domain")
            res_url = item.get("result_url")

            if not isinstance(qv, str) or not isinstance(item_source_domain, str) or not isinstance(res_url, str):
                domains_ok = False
                url_vs_source_ok = False
                break

            norm_source = _normalize_domain(item_source_domain)
            url_domain = _extract_domain_from_url(res_url)
            if not url_domain:
                url_vs_source_ok = False
                break

            # URL domain should be the same as or a subdomain/superdomain of source_domain
            def matches(a: str, b: str) -> bool:
                # accept if equal or endswith .other
                return a == b or a.endswith("." + b) or b.endswith("." + a)

            if not matches(url_domain, norm_source):
                url_vs_source_ok = False
                break

            # Check against allowed domains for this query
            allowed = query_to_allowed_domains.get(qv, [])
            allowed_norm = [_normalize_domain(x) for x in allowed]
            allowed_match = any(matches(norm_source, ad) and matches(url_domain, ad) for ad in allowed_norm)
            if not allowed_match:
                domains_ok = False
                break
        if domains_ok:
            scores["official_domain_constraints_respected"] = 1.0
        if url_vs_source_ok:
            scores["result_url_and_source_domain_consistent"] = 1.0

    # per_query_max_respected
    if query_to_max:
        per_max_ok = True
        counts: Dict[str, int] = {}
        for item in results:
            qv = item.get("query")
            if not isinstance(qv, str):
                per_max_ok = False
                break
            counts[qv] = counts.get(qv, 0) + 1
        if per_max_ok:
            for qv, maxv in query_to_max.items():
                if isinstance(maxv, int):
                    if counts.get(qv, 0) > maxv:
                        per_max_ok = False
                        break
        if per_max_ok:
            scores["per_query_max_respected"] = 1.0

    # domain_stats_csv_header_valid
    header, rows = _parse_csv(domain_csv_path)
    header_ok = False
    if header is not None:
        expected_header = ["source_domain", "organization", "count"]
        if header == expected_header:
            header_ok = True
    if header_ok:
        scores["domain_stats_csv_header_valid"] = 1.0

    # domain_stats_match
    stats_match_ok = False
    if header_ok and rows is not None:
        # Build stats from CSV
        csv_counts: Dict[Tuple[str, str], int] = {}
        try:
            for r in rows:
                if len(r) != 3:
                    csv_counts = {}
                    raise ValueError("Bad row length")
                sdom = r[0].strip()
                sorg = r[1].strip()
                try:
                    cnt = int(r[2].strip())
                except Exception:
                    csv_counts = {}
                    raise
                key = (sdom, sorg)
                csv_counts[key] = csv_counts.get(key, 0) + cnt  # combine duplicates if any
        except Exception:
            csv_counts = {}

        # Build stats from JSON
        json_counts: Dict[Tuple[str, str], int] = {}
        json_ok = True
        for item in results:
            if not isinstance(item, dict):
                json_ok = False
                break
            sdom = item.get("source_domain")
            sorg = item.get("organization")
            if not isinstance(sdom, str) or not isinstance(sorg, str):
                json_ok = False
                break
            key = (sdom.strip(), sorg.strip())
            json_counts[key] = json_counts.get(key, 0) + 1

        if json_ok and csv_counts and json_counts == csv_counts:
            stats_match_ok = True

    if stats_match_ok:
        scores["domain_stats_match"] = 1.0

    # validation_report_present and indicates_success
    report_text = _read_text(validation_report_path)
    if report_text is not None:
        scores["validation_report_present"] = 1.0
        low = report_text.lower()
        # success if contains 'success' or 'passed' and does not contain 'fail' or 'error'
        indicates_success = (("success" in low) or ("passed" in low)) and ("fail" not in low) and ("error" not in low)
        if indicates_success:
            scores["validation_report_indicates_success"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()