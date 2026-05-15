import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple


def safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        text = path.read_text(encoding="utf-8")
        return True, text
    except Exception:
        try:
            text = path.read_text(encoding="latin-1")
            return True, text
        except Exception:
            return False, ""


def safe_load_json(path: Path) -> Tuple[bool, Any]:
    ok, txt = safe_read_text(path)
    if not ok:
        return False, None
    try:
        return True, json.loads(txt)
    except Exception:
        return False, None


def parse_nginx_access_log(text: str) -> List[Dict[str, Any]]:
    # Nginx combined log format approximated:
    # ip - - [date] "METHOD path HTTP/version" status bytes "ref" "ua"
    entries = []
    log_re = re.compile(
        r'^(?P<ip>\S+) \S+ \S+ \[[^\]]+\] "(?P<method>[A-Z]+) (?P<target>\S+) HTTP/[0-9.]+" (?P<status>\d{3}) \S+ "([^"]*)" "([^"]*)"$'
    )
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = log_re.match(line)
        if not m:
            continue
        ip = m.group("ip")
        method = m.group("method")
        target = m.group("target")
        status = m.group("status")
        # Split target into path and query
        path_only = target.split("?", 1)[0]
        ua = line.split('"')[-2] if '"' in line else ""
        entries.append({
            "ip": ip,
            "method": method,
            "target": target,
            "path": path_only,
            "status": int(status),
            "ua": ua
        })
    return entries


def overall_status_counts(entries: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"2xx": 0, "4xx_5xx": 0, "total": 0}
    for e in entries:
        counts["total"] += 1
        s = e["status"]
        if 200 <= s <= 299:
            counts["2xx"] += 1
        if 400 <= s <= 599:
            counts["4xx_5xx"] += 1
    return counts


def unique_ips(entries: List[Dict[str, Any]]) -> List[str]:
    seen = []
    for e in entries:
        ip = e["ip"]
        if ip not in seen:
            seen.append(ip)
    return seen


def infer_suspicious_ips(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    # Rule-based heuristics to identify suspicious IPs and reasons
    suspicious_patterns = [
        r"/wp-login\.php",
        r"/xmlrpc\.php",
        r"/phpMyAdmin/?",
        r"/phpmyadmin/?",
        r"/server-status",
        r"/cgi-bin",
        r"/\.env",
        r"/\.git",
    ]
    sqli_patterns = [
        r"(%27|\')\s*or\s*1\s*=\s*1",
        r"(%3C|<)script(%3E|>)",
    ]
    sus_ips: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        ip = e["ip"]
        reason_hits = 0
        reasons = set()
        path = e["target"].lower()
        ua = e["ua"].lower()
        for p in suspicious_patterns:
            if re.search(p, path):
                reason_hits += 1
                reasons.add("probe_path")
        for p in sqli_patterns:
            if re.search(p, path):
                reason_hits += 1
                reasons.add("injection_pattern")
        if "curl" in ua or "python-requests" in ua or "scanner" in ua:
            reason_hits += 1
            reasons.add("automated_ua")
        if reason_hits > 0:
            if ip not in sus_ips:
                sus_ips[ip] = {"score": 0, "reasons": set()}
            sus_ips[ip]["score"] += reason_hits
            sus_ips[ip]["reasons"].update(reasons)
    for ip in sus_ips:
        sus_ips[ip]["reasons"] = list(sus_ips[ip]["reasons"])
    return sus_ips


def read_csv_with_headers(path: Path) -> Tuple[bool, List[str], List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [row for row in reader]
            return True, headers, rows
    except Exception:
        return False, [], []


def is_sorted_desc(rows: List[Dict[str, Any]], primary: str, secondary: str) -> bool:
    last_primary = None
    last_secondary = None
    for _, row in enumerate(rows):
        try:
            p = float(row[primary])
        except Exception:
            return False
        try:
            s = int(row[secondary])
        except Exception:
            return False
        if last_primary is None:
            last_primary, last_secondary = p, s
            continue
        if p > last_primary:
            return False
        if p == last_primary and s > last_secondary:
            return False
        last_primary, last_secondary = p, s
    return True


def count_improvements_in_nginx_conf(conf_text: str) -> Dict[str, bool]:
    t = conf_text.lower()
    categories = {
        "csp": "content-security-policy" in t,
        "x_content_type_options": "x-content-type-options" in t,
        "referrer_policy": "referrer-policy" in t,
        "frame_control": ("x-frame-options" in t) or ("frame-ancestors" in t),
        "hsts": "strict-transport-security" in t,
        "tls_protocols": "ssl_protocols" in t,
        "tls_ciphers": "ssl_ciphers" in t,
        "rate_limiting": "limit_req" in t,
        "rate_limiting_zone": "limit_req_zone" in t,
        "block_probes": bool(re.search(r"location\s+~\s*/(wp-login|xmlrpc|phpmyadmin|server-status|cgi-bin|\.env|\.git)", t)),
        "redirect_https": ("return 301 https" in t) or ("return 308 https" in t) or ("rewrite" in t and "https://" in t),
    }
    return categories


def extract_source_ids_from_report(report: Dict[str, Any]) -> List[str]:
    srcs = report.get("sources", [])
    ids = []
    if isinstance(srcs, list):
        for s in srcs:
            if isinstance(s, dict):
                sid = s.get("id")
                if isinstance(sid, str):
                    ids.append(sid)
    return ids


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "has_suspicious_ips_csv_structure": 0.0,
        "suspicious_ips_count_and_sorting": 0.0,
        "suspicious_ips_includes_expected_bad_ips": 0.0,
        "has_top_paths_csv_structure": 0.0,
        "top_paths_totals_match_log": 0.0,
        "hardened_nginx_has_min_improvements": 0.0,
        "hardened_nginx_references_sources": 0.0,
        "patch_diff_is_unified": 0.0,
        "report_json_structure": 0.0,
        "report_sources_count": 0.0,
        "report_sources_authoritative_heuristic": 0.0,
        "report_scoring_rules_present": 0.0,
        "report_config_changes_linked_to_sources": 0.0,
        "report_next_steps_min_two": 0.0,
    }

    # Load inputs for recomputation
    access_log_path = workspace / "input" / "logs" / "access.log"
    ok_log, access_text = safe_read_text(access_log_path)
    entries: List[Dict[str, Any]] = []
    if ok_log:
        entries = parse_nginx_access_log(access_text)

    # Suspicious IPs CSV checks
    sus_csv_path = workspace / "outputs" / "analysis" / "suspicious_ips.csv"
    ok_csv, headers, rows = read_csv_with_headers(sus_csv_path)
    expected_headers = ["ip", "suspicious_score", "total_requests", "distinct_suspicious_paths", "example_user_agents"]
    if ok_csv and headers == expected_headers:
        scores["has_suspicious_ips_csv_structure"] = 1.0
        if entries:
            unique = unique_ips(entries)
            expected_count = min(10, len(unique))
            try:
                ips_in_csv = [r["ip"] for r in rows]
                unique_ips_csv = len(set(ips_in_csv)) == len(ips_in_csv)
                correct_count = len(rows) == expected_count
                all_from_log = all(ip in unique for ip in ips_in_csv)
                numeric_ok = True
                for r in rows:
                    try:
                        float(r["suspicious_score"])
                        int(r["total_requests"])
                        int(r["distinct_suspicious_paths"])
                    except Exception:
                        numeric_ok = False
                        break
                sorted_ok = is_sorted_desc(rows, "suspicious_score", "total_requests")
                if unique_ips_csv and correct_count and all_from_log and numeric_ok and sorted_ok:
                    scores["suspicious_ips_count_and_sorting"] = 1.0
            except Exception:
                pass

        if entries:
            sus_map = infer_suspicious_ips(entries)
            expected_sus_ips = set(sus_map.keys())
            ips_in_csv = {r["ip"] for r in rows}
            if expected_sus_ips.issubset(ips_in_csv):
                benign_ips = [ip for ip in unique_ips(entries) if ip not in expected_sus_ips]
                if benign_ips:
                    order = [r["ip"] for r in rows]
                    sus_best = min((order.index(ip) for ip in expected_sus_ips if ip in order), default=None)
                    benign_worst = max((order.index(ip) for ip in benign_ips if ip in order), default=None)
                    if sus_best is not None and benign_worst is not None and sus_best <= benign_worst:
                        scores["suspicious_ips_includes_expected_bad_ips"] = 1.0
                else:
                    scores["suspicious_ips_includes_expected_bad_ips"] = 1.0

    # Top paths CSV checks
    top_paths_path = workspace / "outputs" / "analysis" / "top_paths.csv"
    ok_tp, tp_headers, tp_rows = read_csv_with_headers(top_paths_path)
    expected_tp_headers = ["path", "hits", "status_2xx", "status_4xx_5xx"]
    if ok_tp and tp_headers == expected_tp_headers:
        numeric_ok = True
        sorted_ok = True
        last_hits = None
        for r in tp_rows:
            try:
                hits = int(r["hits"])
                s2 = int(r["status_2xx"])
                s45 = int(r["status_4xx_5xx"])
            except Exception:
                numeric_ok = False
                break
            if last_hits is None:
                last_hits = hits
            else:
                if hits > last_hits:
                    sorted_ok = False
                last_hits = hits
        if numeric_ok and sorted_ok:
            scores["has_top_paths_csv_structure"] = 1.0

        if entries and numeric_ok:
            totals = overall_status_counts(entries)
            sum_hits = sum(int(r["hits"]) for r in tp_rows)
            sum_2xx = sum(int(r["status_2xx"]) for r in tp_rows)
            sum_45x = sum(int(r["status_4xx_5xx"]) for r in tp_rows)
            if sum_hits == totals["total"] and sum_2xx == totals["2xx"] and sum_45x == totals["4xx_5xx"]:
                scores["top_paths_totals_match_log"] = 1.0

    # Hardened nginx config checks
    hardened_conf_path = workspace / "outputs" / "hardened" / "nginx.conf"
    ok_conf, conf_text = safe_read_text(hardened_conf_path)
    report_path = workspace / "outputs" / "report.json"
    ok_report, report_obj = safe_load_json(report_path)

    if ok_conf:
        improvements = count_improvements_in_nginx_conf(conf_text)
        improvements_count = sum(1 for v in improvements.values() if v)
        if improvements_count >= 5:
            scores["hardened_nginx_has_min_improvements"] = 1.0

        valid_ids = []
        if ok_report and isinstance(report_obj, dict):
            valid_ids = extract_source_ids_from_report(report_obj)
        ref_count = 0
        if valid_ids:
            for sid in valid_ids:
                pattern = f"# Source: [{sid}]"
                ref_count += conf_text.count(pattern)
        else:
            ref_count = len(re.findall(r"#\s*Source:\s*\[S\d+\]", conf_text))
        if ref_count >= 5:
            scores["hardened_nginx_references_sources"] = 1.0

    # Patch diff check
    patch_path = workspace / "outputs" / "patch.diff"
    ok_patch, patch_text = safe_read_text(patch_path)
    if ok_patch:
        has_headers = ("---" in patch_text and "+++" in patch_text)
        has_hunk = "@@" in patch_text
        mentions_nginx = "nginx.conf" in patch_text
        if has_headers and has_hunk and mentions_nginx:
            scores["patch_diff_is_unified"] = 1.0

    # Report JSON structure checks
    if ok_report and isinstance(report_obj, dict):
        persona = report_obj.get("persona_context")
        persona_ok = isinstance(persona, str) and len(persona.strip()) > 0
        persona_contains_domain = False
        if persona_ok:
            low = persona.lower()
            persona_contains_domain = ("ceramic" in low) and ("denmark" in low or "danish" in low)
        sources = report_obj.get("sources")
        sources_ok = isinstance(sources, list) and len(sources) >= 2
        scoring_rules = report_obj.get("scoring_rules")
        scoring_ok = isinstance(scoring_rules, list) and len(scoring_rules) >= 1 and all(isinstance(s, str) for s in scoring_rules)
        top_risks = report_obj.get("top_risks")
        top_risks_ok = isinstance(top_risks, list) and len(top_risks) <= 5
        if top_risks_ok:
            for tr in top_risks:
                if not isinstance(tr, dict):
                    top_risks_ok = False
                    break
                if "rank" not in tr or "description" not in tr or "evidence" not in tr:
                    top_risks_ok = False
                    break
                if not isinstance(tr["rank"], int) or not isinstance(tr["description"], str) or not isinstance(tr["evidence"], dict):
                    top_risks_ok = False
                    break
                ev = tr["evidence"]
                if not isinstance(ev.get("ips"), list) or not isinstance(ev.get("example_paths"), list) or not isinstance(ev.get("counts"), dict):
                    top_risks_ok = False
                    break
        config_changes = report_obj.get("config_changes")
        changes_ok = isinstance(config_changes, list) and len(config_changes) >= 1
        if changes_ok:
            for ch in config_changes:
                if not isinstance(ch, dict):
                    changes_ok = False
                    break
                if "directive_or_block" not in ch or "reason" not in ch or "source_ids" not in ch:
                    changes_ok = False
                    break
                if not isinstance(ch["directive_or_block"], str) or not isinstance(ch["reason"], str) or not isinstance(ch["source_ids"], list) or len(ch["source_ids"]) == 0:
                    changes_ok = False
                    break
        next_steps = report_obj.get("next_steps")
        next_steps_ok = isinstance(next_steps, list) and len(next_steps) >= 2 and all(isinstance(n, str) for n in next_steps)

        if persona_ok and persona_contains_domain and sources_ok and scoring_ok and top_risks_ok and changes_ok and next_steps_ok:
            scores["report_json_structure"] = 1.0

        if sources_ok:
            shape_ok = True
            for s in sources:
                if not isinstance(s, dict):
                    shape_ok = False
                    break
                if not isinstance(s.get("id"), str) or not re.match(r"^S\d+$", s.get("id", "")):
                    shape_ok = False
                    break
                if not isinstance(s.get("organization"), str) or not s.get("organization").strip():
                    shape_ok = False
                    break
                if not isinstance(s.get("doc_title"), str) or not s.get("doc_title").strip():
                    shape_ok = False
                    break
                q = s.get("queries_used")
                if not isinstance(q, list) or len(q) == 0 or not all(isinstance(x, str) for x in q):
                    shape_ok = False
                    break
                if not isinstance(s.get("retrieved_at_utc"), str) or not s.get("retrieved_at_utc").strip():
                    shape_ok = False
                    break
            if shape_ok:
                scores["report_sources_count"] = 1.0

            auth_keywords = ["nginx", "owasp", "cert", "cisa", "ncsc", "enisa", "nist", "cis", "iso"]
            auth_count = 0
            for s in sources:
                org = str(s.get("organization", "")).lower()
                if any(k in org for k in auth_keywords):
                    auth_count += 1
            if auth_count >= 2:
                scores["report_sources_authoritative_heuristic"] = 1.0

        if scoring_ok:
            scores["report_scoring_rules_present"] = 1.0

        if changes_ok and sources_ok:
            source_ids = {s.get("id") for s in sources if isinstance(s, dict)}
            valid_linkage = True
            for ch in config_changes:
                ids = ch.get("source_ids", [])
                if not isinstance(ids, list) or len(ids) == 0:
                    valid_linkage = False
                    break
                if not all(isinstance(i, str) and i in source_ids for i in ids):
                    valid_linkage = False
                    break
            if valid_linkage and len(config_changes) >= 5:
                scores["report_config_changes_linked_to_sources"] = 1.0

        if next_steps_ok:
            scores["report_next_steps_min_two"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()