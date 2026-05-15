import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urlparse


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _safe_read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _parse_domains_yaml(path: Path) -> List[str]:
    text = _safe_read_text(path)
    if text is None:
        return []
    patterns = []
    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("domain_pattern:"):
            parts = line_stripped.split(":", 1)
            if len(parts) == 2:
                val = parts[1].strip()
                if val:
                    patterns.append(val)
    return patterns


def _load_spec_columns(path: Path) -> Optional[List[str]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
        cols = data.get("columns")
        if isinstance(cols, list) and all(isinstance(c, str) for c in cols):
            return cols
    except Exception:
        return None
    return None


def _read_urls(path: Path) -> Optional[List[str]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    urls = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        urls.append(line)
    return urls


def _domain_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url.strip())
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return None


def _domain_matches_pattern(domain: str, pattern: str) -> bool:
    domain = domain.lower()
    pattern = pattern.lower()
    if domain == pattern:
        return True
    if domain.endswith("." + pattern):
        return True
    return False


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        s2 = s.replace("Z", "+00:00")
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _compute_sha256(path: Path) -> Optional[str]:
    data = _safe_read_bytes(path)
    if data is None:
        return None
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _parse_jsonl(path: Path) -> Optional[List[dict]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    records = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                records.append(obj)
            else:
                return None
        except Exception:
            return None
    return records


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def _read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            first = f.readline()
            if not first:
                return None
            header = [h.strip() for h in first.strip().split(",")]
            return header
    except Exception:
        return None


def _number_token_present(text: str, n: int) -> bool:
    pattern = r"(?<!\d){}(?!\d)".format(re.escape(str(n)))
    return re.search(pattern, text) is not None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "architecture_doc_present": 0.0,
        "run_script_and_logs_present": 0.0,
        "requirements_present": 0.0,
        "urls_count_and_allowed_domains": 0.0,
        "urls_unique_domains_min_two": 0.0,
        "manifest_fields_and_integrity": 0.0,
        "raw_html_files_for_each_url": 0.0,
        "clean_texts_for_each_url": 0.0,
        "placenames_csv_header_exact": 0.0,
        "csv_source_linkage": 0.0,
        "origin_type_values_valid": 0.0,
        "summary_metrics_consistent": 0.0,
    }

    domains_yaml = workspace / "input" / "domains.yaml"
    spec_json = workspace / "input" / "spec_fields.json"
    allowed_patterns = _parse_domains_yaml(domains_yaml)

    # Architecture doc
    arch = workspace / "docs" / "architecture.md"
    arch_text = _safe_read_text(arch)
    if arch_text and arch_text.strip():
        scores["architecture_doc_present"] = 1.0

    # Run script and logs
    run_sh = workspace / "run.sh"
    run_sh_text = _safe_read_text(run_sh)
    logs_log = workspace / "logs" / "run.log"
    log_text = _safe_read_text(logs_log)
    run_ok = False
    if run_sh_text and run_sh_text.strip():
        if run_sh_text.lstrip().startswith("#!") or "python" in run_sh_text or "bash" in run_sh_text or "sh " in run_sh_text:
            run_ok = True
    log_ok = False
    if log_text and re.search(r"\d{4}-\d{2}-\d{2}", log_text):
        log_ok = True
    if run_ok and log_ok:
        scores["run_script_and_logs_present"] = 1.0

    # requirements.txt
    req = workspace / "requirements.txt"
    req_text = _safe_read_text(req)
    if req_text is not None and req_text.strip() != "":
        scores["requirements_present"] = 1.0

    # URLs selection
    urls_path = workspace / "data" / "raw" / "urls.txt"
    urls = _read_urls(urls_path)
    allowed_urls = []
    urls_ok = False
    if urls is not None:
        distinct_urls = list(dict.fromkeys(urls))
        if 3 <= len(distinct_urls) <= 8:
            all_allowed = True
            for u in distinct_urls:
                if not (u.startswith("http://") or u.startswith("https://")):
                    all_allowed = False
                    break
                d = _domain_from_url(u)
                if not d:
                    all_allowed = False
                    break
                matched = any(_domain_matches_pattern(d, p) for p in allowed_patterns)
                if not matched:
                    all_allowed = False
                    break
                allowed_urls.append(u)
            if all_allowed:
                urls_ok = True
    if urls_ok:
        scores["urls_count_and_allowed_domains"] = 1.0
        # ensure at least two allowed domain patterns used
        patterns_used = set()
        for u in allowed_urls:
            dom = _domain_from_url(u) or ""
            for p in allowed_patterns:
                if _domain_matches_pattern(dom, p):
                    patterns_used.add(p)
                    break
        if len(patterns_used) >= 2:
            scores["urls_unique_domains_min_two"] = 1.0

    # Manifest and files
    manifest_path = workspace / "data" / "raw" / "sources.jsonl"
    manifest = _parse_jsonl(manifest_path)
    manifest_ok = False
    raw_html_ok = False
    clean_txt_ok = False

    if manifest is not None and urls is not None and urls_ok:
        required_fields = {"source_title", "source_domain", "source_url", "accessed_utc", "local_path", "sha256"}
        url_set = set(list(dict.fromkeys(urls)))
        if len(manifest) == len(url_set):
            entries_ok = True
            seen_urls = set()
            for obj in manifest:
                if not required_fields.issubset(set(obj.keys())):
                    entries_ok = False
                    break
                su = obj.get("source_url", "")
                sd = obj.get("source_domain", "")
                ts = obj.get("accessed_utc", "")
                lp = obj.get("local_path", "")
                sh = obj.get("sha256", "")
                if not isinstance(su, str) or not su:
                    entries_ok = False
                    break
                if su not in url_set:
                    entries_ok = False
                    break
                if su in seen_urls:
                    entries_ok = False
                    break
                seen_urls.add(su)
                url_dom = _domain_from_url(su) or ""
                if not isinstance(sd, str) or not sd:
                    entries_ok = False
                    break
                sd_norm = sd.lower().lstrip("www.")
                if sd_norm != url_dom:
                    if not (_domain_matches_pattern(url_dom, sd_norm) or _domain_matches_pattern(sd_norm, url_dom)):
                        entries_ok = False
                        break
                if not _is_iso8601(ts):
                    entries_ok = False
                    break
                local_path = (workspace / lp) if not Path(lp).is_absolute() else Path(lp)
                if not local_path.exists() or not local_path.is_file():
                    entries_ok = False
                    break
                calc = _compute_sha256(local_path)
                if calc is None or calc.lower() != sh.lower():
                    entries_ok = False
                    break
            if entries_ok:
                manifest_ok = True

        if manifest_ok:
            all_html = True
            for obj in manifest:
                lp = obj.get("local_path", "")
                local_path = (workspace / lp) if not Path(lp).is_absolute() else Path(lp)
                if not local_path.exists():
                    all_html = False
                    break
            if all_html:
                raw_html_ok = True

        if manifest_ok:
            all_clean = True
            for obj in manifest:
                lp = obj.get("local_path", "")
                local_path = (workspace / lp) if not Path(lp).is_absolute() else Path(lp)
                slug = local_path.stem
                clean_path = workspace / "data" / "clean" / f"{slug}.txt"
                if not clean_path.exists() or not clean_path.is_file():
                    all_clean = False
                    break
            if all_clean:
                clean_txt_ok = True

    if manifest_ok:
        scores["manifest_fields_and_integrity"] = 1.0
    if raw_html_ok and urls_ok:
        scores["raw_html_files_for_each_url"] = 1.0
    if clean_txt_ok and urls_ok:
        scores["clean_texts_for_each_url"] = 1.0

    # CSV structure
    placenames_csv = workspace / "data" / "derived" / "placenames.csv"
    expected_cols = _load_spec_columns(spec_json) if spec_json.exists() else None
    header = _read_csv_header(placenames_csv) if placenames_csv.exists() else None
    if expected_cols and header and header == expected_cols:
        scores["placenames_csv_header_exact"] = 1.0

    # CSV linkage and origin types
    csv_rows = _read_csv_rows(placenames_csv) if placenames_csv.exists() else None
    csv_link_ok = False
    origin_ok = False
    if csv_rows is not None and manifest is not None and manifest_ok:
        manifest_map = {}
        for obj in manifest:
            manifest_map[obj.get("source_url")] = (obj.get("source_domain"), obj.get("accessed_utc"))
        link_all = True
        allowed_origin_types = {"person", "indigenous", "geographic", "other", "unknown", ""}
        origin_all = True
        for row in csv_rows:
            su = (row.get("source_url") or "").strip()
            sd_row = (row.get("source_domain") or "").strip()
            ts_row = (row.get("accessed_utc") or "").strip()
            if su not in manifest_map:
                link_all = False
                break
            sd_mani, ts_mani = manifest_map[su]
            sd_row_norm = sd_row.lower().lstrip("www.")
            su_dom = _domain_from_url(su) or ""
            if not (sd_row_norm == su_dom or _domain_matches_pattern(su_dom, sd_row_norm) or _domain_matches_pattern(sd_row_norm, su_dom)):
                link_all = False
                break
            if ts_row != ts_mani:
                link_all = False
                break
            ot = (row.get("origin_type") or "").strip()
            ot_norm = ot.lower()
            if ot_norm not in allowed_origin_types:
                origin_all = False
                break
        if link_all:
            csv_link_ok = True
        if origin_all:
            origin_ok = True

    if csv_link_ok:
        scores["csv_source_linkage"] = 1.0
    if origin_ok:
        scores["origin_type_values_valid"] = 1.0

    # Summary consistency
    summary_path = workspace / "data" / "derived" / "summary.txt"
    summary_text = _safe_read_text(summary_path)
    summary_ok = False
    if summary_text and manifest is not None and csv_rows is not None:
        sources_processed = len(manifest)
        total_rows = len(csv_rows)
        distinct_places = len({(row.get("place_name") or "").strip() for row in csv_rows if (row.get("place_name") or "").strip() != ""})
        county_counts: Dict[str, int] = {}
        for row in csv_rows:
            county = (row.get("county") or "").strip()
            if county:
                county_counts[county] = county_counts.get(county, 0) + 1

        has_sources_num = _number_token_present(summary_text, sources_processed)
        has_rows_num = _number_token_present(summary_text, total_rows)
        has_places_num = _number_token_present(summary_text, distinct_places)

        counties_ok = True
        if county_counts:
            for c, n in county_counts.items():
                found = False
                for line in summary_text.splitlines():
                    if c.lower() in line.lower() and _number_token_present(line, n):
                        found = True
                        break
                if not found:
                    counties_ok = False
                    break

        if has_sources_num and has_rows_num and has_places_num and counties_ok:
            summary_ok = True

    if summary_ok:
        scores["summary_metrics_consistent"] = 1.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()