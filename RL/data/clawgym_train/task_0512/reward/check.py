import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Tuple[Optional[Any], bool]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False


def _compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _list_input_files(input_dir: Path) -> List[Path]:
    if not input_dir.exists() or not input_dir.is_dir():
        return []
    return sorted([p for p in input_dir.rglob("*") if p.is_file()])


def _is_hex_string(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]+", s))


def _parse_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _to_float(s: Any) -> Optional[float]:
    try:
        if isinstance(s, (int, float)):
            return float(s)
        if isinstance(s, str):
            return float(s.strip())
    except Exception:
        return None
    return None


def _approx_equal(a: float, b: float, eps: float = 1e-6) -> bool:
    return abs(a - b) <= eps


def _iso8601_parseable(ts: str) -> bool:
    if not isinstance(ts, str):
        return False
    try:
        t = ts.replace("Z", "+00:00")
        datetime.fromisoformat(t)
        return True
    except Exception:
        return False


def _manufacturer_match_in_sources(sources: List[Dict[str, Any]], manufacturers: List[str]) -> bool:
    mans = [m.lower() for m in manufacturers]
    for s in sources:
        if not isinstance(s, dict):
            continue
        org_type = s.get("org_type")
        if org_type != "manufacturer":
            continue
        title = str(s.get("title", "")).lower()
        domain = str(s.get("domain", "")).lower()
        for m in mans:
            if m in title or m in domain:
                return True
    return False


def _has_government_or_standards_source(sources: List[Dict[str, Any]]) -> bool:
    for s in sources:
        if not isinstance(s, dict):
            continue
        if s.get("org_type") in ("government", "standards_org"):
            return True
    return False


def _sources_structure_valid(sources: Any) -> bool:
    if not isinstance(sources, list) or len(sources) == 0:
        return False
    for s in sources:
        if not isinstance(s, dict):
            return False
        if not isinstance(s.get("domain"), str) or not s.get("domain"):
            return False
        if not isinstance(s.get("title"), str) or not s.get("title"):
            return False
        if s.get("org_type") not in ("manufacturer", "government", "standards_org"):
            return False
        kp = s.get("key_points")
        if not isinstance(kp, list) or any(not isinstance(x, str) or not x for x in kp):
            return False
        dom = s.get("domain", "")
        # Disallow full URLs or spaces; allow subdomains like 'www.'
        if any(x in dom for x in ("/", "http://", "https://")) or " " in dom:
            return False
    return True


def _queries_valid(queries: Any) -> bool:
    if not isinstance(queries, list) or len(queries) == 0:
        return False
    return all(isinstance(q, str) and q.strip() for q in queries)


def _policy_structure_valid(policy: Any) -> bool:
    if not isinstance(policy, dict):
        return False
    dt = policy.get("default_tolerance_f")
    if _to_float(dt) is None:
        return False
    rules = policy.get("rules", [])
    if rules is None:
        rules = []
    if not isinstance(rules, list):
        return False
    for r in rules:
        if not isinstance(r, dict):
            return False
        if not isinstance(r.get("type_contains"), str) or not r.get("type_contains"):
            return False
        if _to_float(r.get("tolerance_f")) is None:
            return False
        if not isinstance(r.get("source_domain"), str) or not r.get("source_domain"):
            return False
    return True


def _rules_source_domain_match_sources(policy: Dict[str, Any], sources: List[Dict[str, Any]]) -> bool:
    if not isinstance(policy, dict):
        return False
    rules = policy.get("rules", [])
    if rules is None:
        rules = []
    if not isinstance(rules, list):
        return False
    if len(rules) == 0:
        return True
    source_domains = {str(s.get("domain")) for s in sources if isinstance(s, dict) and isinstance(s.get("domain"), str)}
    for r in rules:
        if not isinstance(r, dict):
            return False
        sd = r.get("source_domain")
        if not isinstance(sd, str):
            return False
        if sd not in source_domains:
            return False
    return True


def _get_type_by_unit(inventory: List[Dict[str, Any]]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for item in inventory:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("type"), str):
            mapping[item["id"]] = item["type"]
    return mapping


def _choose_tolerance_for_type(device_type: str, policy: Dict[str, Any]) -> Optional[float]:
    default_tol = _to_float(policy.get("default_tolerance_f"))
    if default_tol is None:
        return None
    rules = policy.get("rules", [])
    best_match = None
    best_len = -1
    if isinstance(rules, list):
        for r in rules:
            if not isinstance(r, dict):
                continue
            tc = r.get("type_contains")
            tol = _to_float(r.get("tolerance_f"))
            if not isinstance(tc, str) or tol is None:
                continue
            if tc.strip() == "":
                continue
            if tc.lower() in device_type.lower():
                l = len(tc)
                if l > best_len:
                    best_len = l
                    best_match = tol
    return best_match if best_match is not None else default_tol


def _parse_inventory(path: Path) -> Optional[List[Dict[str, Any]]]:
    data, ok = _load_json(path)
    if not ok or not isinstance(data, list):
        return None
    return data


def _number_strings(n: float) -> List[str]:
    vals = []
    try:
        if float(int(n)) == float(n):
            vals.append(str(int(n)))
    except Exception:
        pass
    s = str(float(n))
    if "." in s:
        vals.append(s.rstrip("0").rstrip("."))
    else:
        vals.append(s)
    # Ensure unique while preserving order
    seen = set()
    out = []
    for x in vals:
        if x not in seen and x != "":
            seen.add(x)
            out.append(x)
    return out


def _count_calibrate_rows(results_rows: List[Dict[str, Any]]) -> Optional[int]:
    try:
        cnt = 0
        for r in results_rows:
            if str(r.get("status", "")).strip() == "calibrate":
                cnt += 1
        return cnt
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "manifest_exists": 0.0,
        "manifest_structure_valid": 0.0,
        "manifest_complete_files_match": 0.0,
        "manifest_hashes_and_sizes_match": 0.0,
        "findings_exists": 0.0,
        "findings_structure_valid": 0.0,
        "findings_has_required_sources": 0.0,
        "findings_policy_valid": 0.0,
        "findings_rules_source_domain_valid": 0.0,
        "findings_retrieved_at_valid": 0.0,
        "test_results_exists": 0.0,
        "test_results_headers_correct": 0.0,
        "test_results_row_count_match_logs": 0.0,
        "test_results_computation_correct": 0.0,
        "test_results_status_consistent_with_policy": 0.0,
        "testplan_exists": 0.0,
        "testplan_sections_present": 0.0,
        "testplan_sources_listed": 0.0,
        "testplan_tolerance_policy_cited": 0.0,
        "email_exists": 0.0,
        "email_subject_line_present": 0.0,
        "email_word_count_120_200": 0.0,
        "email_mentions_sources_without_urls": 0.0,
        "email_calibration_count_matches": 0.0,
        "email_mentions_attachments": 0.0,
        "email_proposes_two_time_windows": 0.0,
    }

    # Paths
    input_dir = workspace / "input"
    manifest_path = workspace / "audit" / "input_manifest.json"
    findings_path = workspace / "research" / "findings.json"
    results_path = workspace / "tests" / "oven_test_results.csv"
    testplan_path = workspace / "tests" / "oven_calibration_testplan.md"
    email_path = workspace / "communications" / "email_to_manager.txt"
    logs_path = workspace / "input" / "oven_temp_logs.csv"
    inventory_path = workspace / "input" / "device_inventory.json"

    # 1) Manifest checks
    manifest_data, manifest_ok = _load_json(manifest_path)
    if manifest_ok and isinstance(manifest_data, list):
        scores["manifest_exists"] = 1.0
        structure_valid = True
        for item in manifest_data:
            if not isinstance(item, dict):
                structure_valid = False
                break
            if not isinstance(item.get("path"), str):
                structure_valid = False
                break
            if not isinstance(item.get("size_bytes"), int):
                structure_valid = False
                break
            if not isinstance(item.get("sha256"), str) or not _is_hex_string(item.get("sha256")):
                structure_valid = False
                break
        if structure_valid:
            scores["manifest_structure_valid"] = 1.0

        actual_files = _list_input_files(input_dir)
        actual_rel = [str(p.relative_to(input_dir).as_posix()) for p in actual_files]
        manifest_paths = [item.get("path") for item in manifest_data if isinstance(item, dict)]
        if set(manifest_paths) == set(actual_rel):
            scores["manifest_complete_files_match"] = 1.0

        hashes_sizes_ok = True
        manifest_map = {item.get("path"): item for item in manifest_data if isinstance(item, dict) and isinstance(item.get("path"), str)}
        for p in actual_files:
            rel = str(p.relative_to(input_dir).as_posix())
            if rel not in manifest_map:
                hashes_sizes_ok = False
                break
            ent = manifest_map[rel]
            size_ok = isinstance(ent.get("size_bytes"), int) and ent.get("size_bytes") == p.stat().st_size
            sha = _compute_sha256(p)
            hash_ok = isinstance(ent.get("sha256"), str) and sha is not None and ent.get("sha256").lower() == sha.lower()
            if not (size_ok and hash_ok):
                hashes_sizes_ok = False
                break
        if hashes_sizes_ok and scores["manifest_structure_valid"] == 1.0 and scores["manifest_complete_files_match"] == 1.0:
            scores["manifest_hashes_and_sizes_match"] = 1.0

    # Load inputs for later checks
    inventory = _parse_inventory(inventory_path)
    logs_rows, logs_headers = _parse_csv_dicts(logs_path)

    # 2) Findings checks
    findings, findings_ok = _load_json(findings_path)
    if findings_ok and isinstance(findings, dict):
        scores["findings_exists"] = 1.0
        sources = findings.get("sources")
        queries = findings.get("queries")
        policy = findings.get("chosen_tolerance_policy")
        retrieved_at = findings.get("retrieved_at")

        structure_ok = _sources_structure_valid(sources) and _queries_valid(queries) and _policy_structure_valid(policy) and isinstance(retrieved_at, str)
        if structure_ok:
            scores["findings_structure_valid"] = 1.0

        manufacturers_list: List[str] = []
        if isinstance(inventory, list):
            manufacturers_list = sorted({str(it.get("manufacturer")) for it in inventory if isinstance(it, dict) and it.get("manufacturer")})
        required_sources_ok = False
        if isinstance(sources, list):
            man_ok = _manufacturer_match_in_sources(sources, manufacturers_list) if manufacturers_list else False
            gov_std_ok = _has_government_or_standards_source(sources)
            required_sources_ok = man_ok and gov_std_ok
        if required_sources_ok:
            scores["findings_has_required_sources"] = 1.0

        if _policy_structure_valid(policy):
            scores["findings_policy_valid"] = 1.0

        if isinstance(policy, dict) and isinstance(sources, list) and _rules_source_domain_match_sources(policy, sources):
            scores["findings_rules_source_domain_valid"] = 1.0

        if isinstance(retrieved_at, str) and _iso8601_parseable(retrieved_at):
            scores["findings_retrieved_at_valid"] = 1.0

    # 3) Validation and tests CSV
    results_rows, results_headers = _parse_csv_dicts(results_path)
    if isinstance(results_rows, list) and isinstance(results_headers, list):
        scores["test_results_exists"] = 1.0
        expected_headers = ["unit_id", "setpoint_f", "measured_f", "delta_f", "tolerance_f", "status"]
        if results_headers == expected_headers:
            scores["test_results_headers_correct"] = 1.0

        if isinstance(logs_rows, list):
            if len(results_rows) == len(logs_rows):
                scores["test_results_row_count_match_logs"] = 1.0

        comp_ok = True
        status_ok = True
        local_policy = findings.get("chosen_tolerance_policy") if isinstance(findings, dict) else None
        if isinstance(local_policy, dict) and isinstance(inventory, list) and isinstance(logs_rows, list):
            inv_type_map = _get_type_by_unit(inventory)
            res_map: Dict[Tuple[str, float, float], Dict[str, Any]] = {}
            for r in results_rows:
                uid = r.get("unit_id")
                sp = _to_float(r.get("setpoint_f"))
                mv = _to_float(r.get("measured_f"))
                if uid is None or sp is None or mv is None:
                    comp_ok = False
                    status_ok = False
                    break
                res_map[(str(uid), float(sp), float(mv))] = r
            if comp_ok:
                for log in logs_rows:
                    uid = log.get("unit_id")
                    sp = _to_float(log.get("setpoint_f"))
                    mv = _to_float(log.get("measured_f"))
                    if uid not in inv_type_map or sp is None or mv is None:
                        comp_ok = False
                        status_ok = False
                        break
                    key = (str(uid), float(sp), float(mv))
                    if key not in res_map:
                        comp_ok = False
                        status_ok = False
                        break
                    res = res_map[key]
                    delta = float(mv) - float(sp)
                    dev_type = inv_type_map[str(uid)]
                    tol = _choose_tolerance_for_type(dev_type, local_policy)
                    if tol is None:
                        comp_ok = False
                        status_ok = False
                        break
                    r_delta = _to_float(res.get("delta_f"))
                    r_tol = _to_float(res.get("tolerance_f"))
                    if r_delta is None or r_tol is None:
                        comp_ok = False
                    else:
                        if not _approx_equal(r_delta, delta, 1e-6):
                            comp_ok = False
                        if not _approx_equal(r_tol, tol, 1e-6):
                            comp_ok = False
                    expected_status = "within_tolerance" if abs(delta) <= float(tol) else "calibrate"
                    if str(res.get("status", "")).strip() != expected_status:
                        status_ok = False
            if comp_ok:
                scores["test_results_computation_correct"] = 1.0
            if status_ok:
                scores["test_results_status_consistent_with_policy"] = 1.0

    # 4) Test plan markdown checks
    tp_text = _read_text(testplan_path)
    if isinstance(tp_text, str):
        scores["testplan_exists"] = 1.0
        lc = tp_text.lower()
        sections_ok = ("sources consulted" in lc) and ("tolerance policy" in lc) and ("step-by-step check" in lc)
        if sections_ok:
            scores["testplan_sections_present"] = 1.0
        findings_sources_ok = False
        if isinstance(findings, dict) and isinstance(findings.get("sources"), list) and len(findings["sources"]) > 0:
            s_ok = True
            for s in findings["sources"]:
                title = str(s.get("title", ""))
                domain = str(s.get("domain", ""))
                if not title or not domain:
                    s_ok = False
                    break
                if title.lower() not in lc or domain.lower() not in lc:
                    s_ok = False
                    break
            findings_sources_ok = s_ok
        if findings_sources_ok:
            scores["testplan_sources_listed"] = 1.0
        tolerance_policy_cited = False
        if isinstance(findings, dict) and isinstance(findings.get("chosen_tolerance_policy"), dict):
            pol = findings["chosen_tolerance_policy"]
            numbers_to_find: List[str] = []
            dt = _to_float(pol.get("default_tolerance_f"))
            if dt is not None:
                numbers_to_find.extend(_number_strings(dt))
            rules = pol.get("rules", [])
            if isinstance(rules, list):
                for r in rules:
                    t = _to_float(r.get("tolerance_f"))
                    if t is not None:
                        numbers_to_find.extend(_number_strings(t))
            all_present = True
            for n in set(numbers_to_find):
                if n and n not in tp_text:
                    all_present = False
                    break
            if all_present:
                tolerance_policy_cited = True
        if tolerance_policy_cited:
            scores["testplan_tolerance_policy_cited"] = 1.0

    # 5) Email checks
    email_text = _read_text(email_path)
    if isinstance(email_text, str):
        scores["email_exists"] = 1.0
        lines = email_text.splitlines()
        if len(lines) >= 1 and lines[0].startswith("Subject:"):
            scores["email_subject_line_present"] = 1.0
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        words = [w for w in re.findall(r"\b\S+\b", body)]
        if 120 <= len(words) <= 200:
            scores["email_word_count_120_200"] = 1.0
        body_lc = body.lower()
        mentions_sources = ("manufacturer" in body_lc) and ("safety" in body_lc or "standards" in body_lc)
        no_urls = ("http://" not in body) and ("https://" not in body)
        if mentions_sources and no_urls:
            scores["email_mentions_sources_without_urls"] = 1.0
        calib_match_ok = False
        if isinstance(results_rows, list):
            calib_count = _count_calibrate_rows(results_rows)
            if calib_count is not None:
                if re.search(r"\b" + re.escape(str(calib_count)) + r"\b", body):
                    calib_match_ok = True
        if calib_match_ok:
            scores["email_calibration_count_matches"] = 1.0
        attach_ok = False
        if ("test plan" in body_lc) and (("csv" in body_lc) or ("results" in body_lc)):
            attach_ok = True
        if attach_ok:
            scores["email_mentions_attachments"] = 1.0
        time_range_pattern = re.compile(
            r"\b(\d{1,2})(?::\d{2})?\s*(am|pm)?\s*(?:-|–|—|to)\s*(\d{1,2})(?::\d{2})?\s*(am|pm)?\b",
            re.IGNORECASE,
        )
        matches = time_range_pattern.findall(body)
        if len(matches) >= 2:
            scores["email_proposes_two_time_windows"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()