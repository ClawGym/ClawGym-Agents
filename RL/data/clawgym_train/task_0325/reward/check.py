import json
import csv
import sys
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from typing import List, Dict, Any, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def _read_jsonl(path: Path) -> Tuple[bool, List[Dict[str, Any]]]:
    items: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return False, []
                if not isinstance(obj, dict):
                    return False, []
                items.append(obj)
        return True, items
    except Exception:
        return False, []


def _parse_simple_yaml_config(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal parser for the provided config/sources.yaml structure using stdlib only.
    Supports:
      search:
        engine_preference:
          - value
          - value
        per_treaty_limit: int
      domains:
        ORG:
          allowed:
            - domain
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    engines: List[str] = []
    per_treaty_limit: Optional[int] = None
    domains: Dict[str, Dict[str, List[str]]] = {}
    section = None
    current_org = None
    within_allowed = False
    expect_engines = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped == "search:":
            section = "search"
            current_org = None
            within_allowed = False
            expect_engines = False
            continue
        if stripped == "domains:":
            section = "domains"
            current_org = None
            within_allowed = False
            expect_engines = False
            continue
        if section == "search":
            if stripped.startswith("engine_preference:"):
                expect_engines = True
                continue
            if stripped.startswith("- ") and expect_engines:
                engines.append(stripped[2:].strip())
                continue
            if stripped.startswith("per_treaty_limit:"):
                expect_engines = False
                parts = stripped.split(":", 1)
                if len(parts) == 2:
                    val = parts[1].strip()
                    try:
                        per_treaty_limit = int(val)
                    except Exception:
                        pass
                continue
        if section == "domains":
            if stripped.endswith(":") and not stripped.startswith("allowed"):
                key = stripped[:-1].strip()
                if key:
                    current_org = key
                    domains[current_org] = {"allowed": []}
                    within_allowed = False
                continue
            if stripped.startswith("allowed:"):
                if current_org is None:
                    continue
                within_allowed = True
                continue
            if stripped.startswith("- ") and within_allowed and current_org is not None:
                domains[current_org]["allowed"].append(stripped[2:].strip())
                continue
            within_allowed = False
    if per_treaty_limit is None:
        return None
    return {
        "search": {
            "engine_preference": engines,
            "per_treaty_limit": per_treaty_limit,
        },
        "domains": domains,
    }


def _host_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = parsed.netloc
        if ":" in host:
            host = host.split(":", 1)[0]
        return host.lower()
    except Exception:
        return None


def _domain_matches_allowed(host: str, allowed_domains: List[str]) -> bool:
    host = host.lower()
    for allowed in allowed_domains:
        a = allowed.lower()
        if host == a or host.endswith("." + a):
            return True
    return False


def _host_matches_domain_col(host: str, domain_col: str) -> bool:
    host = host.lower()
    d = (domain_col or "").strip().lower()
    if not d:
        return False
    return host == d or host.endswith("." + d)


def _parse_bool(val: Any) -> Optional[bool]:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("true", "yes", "1"):
            return True
        if v in ("false", "no", "0"):
            return False
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_output_paths_correct": 0.0,
        "findings_structure": 0.0,
        "all_treaties_covered": 0.0,
        "per_treaty_limit_respected": 0.0,
        "query_includes_site_and_official_text": 0.0,
        "engine_in_preference_list": 0.0,
        "rankings_contiguous_per_treaty": 0.0,
        "url_and_domain_consistent": 0.0,
        "whitelist_consistency": 0.0,
        "retrieved_have_snippets": 0.0,
        "snippet_filenames_correct": 0.0,
        "snippet_length_reasonable": 0.0,
        "search_log_structure": 0.0,
        "log_per_treaty_present": 0.0,
        "log_engine_matches_csv": 0.0,
        "log_chosen_domains_subset_allowed": 0.0,
        "no_whitelisted_result_note_present": 0.0,
    }

    # Paths
    input_csv_path = workspace / "input" / "treaties.csv"
    config_yaml_path = workspace / "config" / "sources.yaml"
    script_path = workspace / "scripts" / "fetch_candidates.py"
    findings_csv_path = workspace / "output" / "findings.csv"
    snippets_dir = workspace / "output" / "snippets"
    search_log_path = workspace / "logs" / "search_log.jsonl"

    # script_output_paths_correct (ensure the starter's wrong paths were corrected)
    script_text = _read_text(script_path) if script_path.exists() else None
    if script_text is not None:
        has_wrong_outputs = ("pathlib.Path(\"outputs\")" in script_text) or ("pathlib.Path('outputs')" in script_text) or ("'outputs'" in script_text) or ('"outputs"' in script_text)
        has_wrong_logs = ("pathlib.Path(\"log/search_log.jsonl\")" in script_text) or ("pathlib.Path('log/search_log.jsonl')" in script_text) or ("'log/search_log.jsonl'" in script_text) or ('"log/search_log.jsonl"' in script_text)
        # Look for clear indications of corrected paths
        has_output_dir_ref = ("pathlib.Path(\"output\")" in script_text) or ("pathlib.Path('output')" in script_text) or ("\"output/findings.csv\"" in script_text) or ("'output/findings.csv'" in script_text)
        has_logs_path_ref = ("logs/search_log.jsonl" in script_text)
        if (not has_wrong_outputs) and (not has_wrong_logs) and has_output_dir_ref and has_logs_path_ref:
            scores["script_output_paths_correct"] = 1.0

    # Load config safely
    cfg = _parse_simple_yaml_config(config_yaml_path) if config_yaml_path.exists() else None

    # findings_structure
    expected_header = [
        "treaty_id",
        "treaty_name",
        "org_hint",
        "query",
        "engine",
        "candidate_rank",
        "url",
        "domain",
        "is_whitelisted",
        "title",
        "status",
        "note",
    ]
    findings_header, findings_rows = _read_csv_dicts(findings_csv_path)
    if findings_header is not None and findings_rows is not None:
        if findings_header == expected_header and len(findings_rows) >= 1:
            scores["findings_structure"] = 1.0

    # all_treaties_covered
    input_header, input_rows = _read_csv_dicts(input_csv_path)
    if input_rows is not None and findings_rows is not None:
        input_ids = {r.get("treaty_id", "").strip() for r in input_rows}
        covered_ids = {r.get("treaty_id", "").strip() for r in findings_rows}
        if input_ids and input_ids.issubset(covered_ids):
            scores["all_treaties_covered"] = 1.0

    # per_treaty_limit_respected
    if cfg is not None and findings_rows is not None:
        per_limit = cfg["search"]["per_treaty_limit"]
        ok = True
        for tid in {r["treaty_id"] for r in findings_rows}:
            t_rows = [r for r in findings_rows if r.get("treaty_id") == tid]
            non_no_rows = [r for r in t_rows if (r.get("status") or "").strip() != "no_whitelisted_result"]
            if len(non_no_rows) > per_limit:
                ok = False
                break
            if len(non_no_rows) == 0:
                no_rows = [r for r in t_rows if (r.get("status") or "").strip() == "no_whitelisted_result"]
                if len(no_rows) != 1:
                    ok = False
                    break
        if ok:
            scores["per_treaty_limit_respected"] = 1.0

    # query_includes_site_and_official_text
    if cfg is not None and findings_rows is not None:
        ok_q = True
        domains_cfg = cfg.get("domains", {})
        for r in findings_rows:
            treaty_name = (r.get("treaty_name") or "").strip()
            org = (r.get("org_hint") or "").strip()
            query = (r.get("query") or "").strip()
            allowed = domains_cfg.get(org, {}).get("allowed", [])
            if "official text".lower() not in query.lower():
                ok_q = False
                break
            has_site_allowed = False
            for ad in allowed:
                if f"site:{ad}".lower() in query.lower():
                    has_site_allowed = True
                    break
            if allowed and not has_site_allowed:
                ok_q = False
                break
            # Soft check: treaty name presence (not strictly enforced)
            if treaty_name and treaty_name.split()[0].lower() not in query.lower():
                pass
        if ok_q:
            scores["query_includes_site_and_official_text"] = 1.0

    # engine_in_preference_list
    if cfg is not None and findings_rows is not None:
        engines_pref = set([e for e in cfg.get("search", {}).get("engine_preference", []) if isinstance(e, str)])
        if engines_pref:
            ok_eng = True
            for r in findings_rows:
                eng = (r.get("engine") or "").strip()
                if eng not in engines_pref:
                    ok_eng = False
                    break
            if ok_eng:
                scores["engine_in_preference_list"] = 1.0

    # rankings_contiguous_per_treaty
    if findings_rows is not None:
        ok_rank = True
        for tid in {r["treaty_id"] for r in findings_rows}:
            t_rows = [r for r in findings_rows if r.get("treaty_id") == tid]
            rank_rows = [r for r in t_rows if (r.get("status") or "").strip() in ("retrieved", "skipped")]
            if rank_rows:
                try:
                    ranks = sorted(int(r.get("candidate_rank", "0")) for r in rank_rows)
                except Exception:
                    ok_rank = False
                    break
                if ranks != list(range(1, len(ranks) + 1)):
                    ok_rank = False
                    break
            else:
                nwr = [r for r in t_rows if (r.get("status") or "").strip() == "no_whitelisted_result"]
                if len(nwr) == 1:
                    try:
                        rnk = int(nwr[0].get("candidate_rank", "0"))
                        if rnk != 1:
                            ok_rank = False
                            break
                    except Exception:
                        ok_rank = False
                        break
        if ok_rank:
            scores["rankings_contiguous_per_treaty"] = 1.0

    # url_and_domain_consistent, whitelist_consistency
    if cfg is not None and findings_rows is not None:
        ok_url_domain = True
        ok_whitelist = True
        for r in findings_rows:
            url = (r.get("url") or "").strip()
            domain_col = (r.get("domain") or "").strip()
            is_wl_val = _parse_bool(r.get("is_whitelisted"))
            org = (r.get("org_hint") or "").strip()
            allowed = cfg.get("domains", {}).get(org, {}).get("allowed", [])
            status = (r.get("status") or "").strip()
            host = _host_from_url(url) if url else None

            # domain consistency with URL host
            if host and domain_col:
                if not _host_matches_domain_col(host, domain_col):
                    ok_url_domain = False

            # whitelist consistency: candidates must be on allowed domains
            if status in ("retrieved", "skipped"):
                # must be whitelisted and within allowed
                if is_wl_val is not True:
                    ok_whitelist = False
                if host is None or not _domain_matches_allowed(host, allowed):
                    ok_whitelist = False
            elif status == "no_whitelisted_result":
                # should mark is_whitelisted false (or absent treated as false)
                if is_wl_val is True:
                    ok_whitelist = False
            else:
                # Unknown status invalidates
                ok_whitelist = False

            # If is_whitelisted explicitly true, ensure host within allowed
            if is_wl_val is True:
                if host is None or not _domain_matches_allowed(host, allowed):
                    ok_whitelist = False

        # Enforce treaty-level rule: if any whitelisted candidate exists, there should be no 'no_whitelisted_result' for that treaty
        if ok_whitelist:
            for tid in {r["treaty_id"] for r in findings_rows}:
                t_rows = [r for r in findings_rows if r.get("treaty_id") == tid]
                any_wl = any(_parse_bool(r.get("is_whitelisted")) is True for r in t_rows if (r.get("status") or "").strip() in ("retrieved", "skipped"))
                any_nwr = any((r.get("status") or "").strip() == "no_whitelisted_result" for r in t_rows)
                if any_wl and any_nwr:
                    ok_whitelist = False
                    break
        if ok_url_domain:
            scores["url_and_domain_consistent"] = 1.0
        if ok_whitelist:
            scores["whitelist_consistency"] = 1.0

    # retrieved_have_snippets and snippet_filenames_correct and snippet_length_reasonable
    if findings_rows is not None:
        has_snippets_dir = snippets_dir.exists() and snippets_dir.is_dir()
        ok_retrieved_files = True
        ok_names = True
        ok_length = True
        for r in findings_rows:
            status = (r.get("status") or "").strip()
            if status == "retrieved":
                tid = (r.get("treaty_id") or "").strip()
                try:
                    rank = int(r.get("candidate_rank", "0"))
                except Exception:
                    ok_names = False
                    ok_retrieved_files = False
                    ok_length = False
                    continue
                expected_name = f"{tid}_{rank}.txt"
                expected_path = snippets_dir / expected_name
                if not has_snippets_dir or not expected_path.exists():
                    ok_retrieved_files = False
                    ok_names = False
                else:
                    try:
                        content = expected_path.read_text(encoding="utf-8")
                        if len(content.strip()) == 0:
                            ok_length = False
                        if len(content) > 2000:
                            ok_length = False
                    except Exception:
                        ok_length = False
        if has_snippets_dir and ok_retrieved_files:
            scores["retrieved_have_snippets"] = 1.0
        if has_snippets_dir and ok_names:
            scores["snippet_filenames_correct"] = 1.0
        if has_snippets_dir and ok_length:
            scores["snippet_length_reasonable"] = 1.0

    # search_log_structure, log_per_treaty_present, log_engine_matches_csv, log_chosen_domains_subset_allowed
    ok_read_log, log_items = _read_jsonl(search_log_path)
    if ok_read_log and log_items:
        structural_ok = True
        for item in log_items:
            ts = item.get("timestamp")
            tid = item.get("treaty_id")
            q = item.get("query")
            eng = item.get("engine")
            rc = item.get("result_count")
            cd = item.get("chosen_domains")
            if not isinstance(ts, str):
                structural_ok = False
                break
            try:
                datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                structural_ok = False
                break
            if not isinstance(tid, str) or not isinstance(q, str) or not isinstance(eng, str):
                structural_ok = False
                break
            if not (isinstance(rc, int) and rc >= 0):
                structural_ok = False
                break
            if not isinstance(cd, list):
                structural_ok = False
                break
        if structural_ok:
            scores["search_log_structure"] = 1.0

        if findings_rows is not None:
            tids_in_findings = {r["treaty_id"] for r in findings_rows}
            logs_by_tid: Dict[str, List[Dict[str, Any]]] = {}
            for item in log_items:
                t = item.get("treaty_id")
                if isinstance(t, str):
                    logs_by_tid.setdefault(t, []).append(item)
            present_ok = all(t in logs_by_tid and len(logs_by_tid[t]) >= 1 for t in tids_in_findings)
            if present_ok:
                scores["log_per_treaty_present"] = 1.0

            engine_match_ok = True
            for tid in tids_in_findings:
                csv_engines = {(r.get("engine") or "").strip() for r in findings_rows if r.get("treaty_id") == tid}
                if not csv_engines:
                    continue
                log_engines = {(li.get("engine") or "").strip() for li in logs_by_tid.get(tid, [])}
                if not (csv_engines & log_engines):
                    engine_match_ok = False
                    break
            if engine_match_ok:
                scores["log_engine_matches_csv"] = 1.0

            if cfg is not None:
                subset_ok = True
                for tid in tids_in_findings:
                    orgs = {(r.get("org_hint") or "").strip() for r in findings_rows if r.get("treaty_id") == tid}
                    org = next(iter(orgs)) if orgs else ""
                    allowed = set([d.lower() for d in cfg.get("domains", {}).get(org, {}).get("allowed", [])])
                    for li in logs_by_tid.get(tid, []):
                        cds = li.get("chosen_domains")
                        if not isinstance(cds, list) or len(cds) == 0:
                            subset_ok = False
                            break
                        for d in cds:
                            if not isinstance(d, str):
                                subset_ok = False
                                break
                            if d.lower() not in allowed:
                                subset_ok = False
                                break
                        if not subset_ok:
                            break
                    if not subset_ok:
                        break
                if subset_ok:
                    scores["log_chosen_domains_subset_allowed"] = 1.0

    # no_whitelisted_result_note_present: ensure a note exists when no_whitelisted_result is used
    if findings_rows is not None:
        ok_note = True
        any_nwr = False
        for r in findings_rows:
            if (r.get("status") or "").strip() == "no_whitelisted_result":
                any_nwr = True
                note = (r.get("note") or "").strip()
                if note == "":
                    ok_note = False
                    break
        if any_nwr and ok_note:
            scores["no_whitelisted_result_note_present"] = 1.0
        elif not any_nwr:
            # If no such rows, consider this check neutral; keep as 0.0
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()