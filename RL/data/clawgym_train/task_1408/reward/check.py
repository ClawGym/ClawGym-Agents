import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _parse_markdown_sections(md_text: str) -> List[Dict[str, str]]:
    sections = []
    current = None
    lines = md_text.splitlines()
    for line in lines:
        m = re.match(r'^\s*(#{1,6})\s+(.*\S)\s*$', line)
        if m:
            if current is not None:
                sections.append(current)
            title = m.group(2).strip()
            current = {"title": title, "title_lower": title.lower(), "body": "", "body_lower": ""}
        else:
            if current is None:
                continue
            current["body"] += (line + "\n")
    if current is not None:
        sections.append(current)
    for s in sections:
        s["body_lower"] = s["body"].lower()
    return sections


def _find_section_by_title_substring(sections: List[Dict[str, str]], title_substring_lower: str) -> Optional[Dict[str, str]]:
    for s in sections:
        if title_substring_lower in s["title_lower"]:
            return s
    return None


def _normalize_semicolon_or_comma_list(value: str) -> List[str]:
    if value is None:
        return []
    v = str(value).strip()
    if not v:
        return []
    items = []
    # Try JSON array first
    try:
        data = json.loads(v)
        if isinstance(data, list):
            for x in data:
                s = str(x).strip()
                if s:
                    items.append(s)
            return items
    except Exception:
        pass
    # Fallback: split by semicolon, then by comma if no semicolons present
    if ";" in v:
        parts = v.split(";")
    elif "," in v:
        parts = v.split(",")
    else:
        parts = [v]
    for p in parts:
        s = p.strip()
        if s:
            items.append(s)
    return items


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _coverage_ratio_str_candidates(val: float) -> List[str]:
    candidates = set()
    for fmt in ["{}", "{:.1f}", "{:.2f}", "{:.3f}", "{:.4f}", "{:.6f}"]:
        s = fmt.format(val).rstrip()
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        candidates.add(s if s else "0")
    return list(candidates)


def _compute_clause_results(agreement_text: str, sections: List[Dict[str, str]], requirements: dict, statutes: dict) -> Dict[str, Tuple[bool, str]]:
    results: Dict[str, Tuple[bool, str]] = {}
    agreement_lower = agreement_text.lower()
    allowed_citations = [c.lower() for c in statutes.get("allowed_citations", [])] if isinstance(statutes, dict) else []
    for clause in requirements.get("mandatory_clauses", []):
        key = clause.get("key", "")
        title = clause.get("title", "")
        must_include = clause.get("must_include", [])
        title_lower = title.lower()
        sec = _find_section_by_title_substring(sections, title_lower)
        if sec is None:
            results[key] = (False, "missing section heading containing title")
            continue
        if key == "statutory_citation":
            matched = None
            for c in allowed_citations:
                if c in agreement_lower:
                    matched = c
                    break
            if matched is not None:
                results[key] = (True, f"found citation: {matched}")
            else:
                results[key] = (False, "no allowed citation found")
        else:
            missing = []
            body_lower = sec["body_lower"]
            for phrase in must_include:
                if phrase.lower() not in body_lower:
                    missing.append(phrase)
            if missing:
                results[key] = (False, "missing phrases: " + ", ".join(missing))
            else:
                results[key] = (True, "section and phrases present")
    return results


def _compute_service_readiness(services_rows: List[Dict[str, str]], requirements: dict, clause_results: Dict[str, Tuple[bool, str]]) -> List[Dict[str, Any]]:
    readiness: List[Dict[str, Any]] = []
    available_keys = {c.get("key", "") for c in requirements.get("mandatory_clauses", [])}
    for row in services_rows:
        service = (row.get("service") or "").strip()
        req_keys = _normalize_semicolon_or_comma_list(row.get("required_clauses") or "")
        req_keys_filtered = [k for k in req_keys if k in available_keys]
        covered_keys = [k for k in req_keys_filtered if clause_results.get(k, (False, ""))[0]]
        total = len(req_keys_filtered)
        covered = len(covered_keys)
        ratio = (covered / total) if total > 0 else 0.0
        try:
            risk_weight = int(str(row.get("risk_weight") or "").strip())
        except Exception:
            risk_weight = None
        readiness.append({
            "service": service,
            "required_clauses": req_keys_filtered,
            "covered_keys": covered_keys,
            "coverage_ratio": ratio,
            "risk_weight": risk_weight
        })
    readiness.sort(key=lambda x: (-x["coverage_ratio"], x["risk_weight"] if x["risk_weight"] is not None else float('inf'), x["service"]))
    for idx, item in enumerate(readiness, start=1):
        item["rank"] = idx
    return readiness


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validator_script_exists": 0.0,
        "validator_cli_flags_present": 0.0,
        "agreement_placeholders_replaced_correctly": 0.0,
        "agreement_has_term_and_termination_section_with_required_details": 0.0,
        "agreement_has_public_records_and_open_meetings_section": 0.0,
        "agreement_statutory_citation_allowed_present": 0.0,
        "compliance_report_exists_and_structure_valid": 0.0,
        "compliance_report_all_clauses_pass_and_match_recomputation": 0.0,
        "service_readiness_exists_and_structure_valid": 0.0,
        "service_readiness_correct_ranking_and_coverage": 0.0,
        "mayor_update_exists_and_sections_listed": 0.0,
        "mayor_update_summary_matches_report": 0.0,
        "mayor_update_top3_matches_readiness": 0.0,
    }

    validator_path = workspace / "tools" / "validate_agreement.py"
    agreement_path = workspace / "input" / "draft_interlocal_agreement.md"
    requirements_path = workspace / "input" / "requirements.json"
    statutes_path = workspace / "input" / "statutory_refs.json"
    services_path = workspace / "input" / "proposed_services.csv"
    compliance_report_path = workspace / "reports" / "compliance_report.json"
    readiness_csv_path = workspace / "reports" / "service_readiness.csv"
    mayor_update_path = workspace / "reports" / "mayor_update.md"

    # Check validator existence and CLI flags
    if validator_path.exists() and validator_path.is_file():
        scores["validator_script_exists"] = 1.0
        validator_text = _safe_read_text(validator_path) or ""
        required_flags = ["--agreement", "--requirements", "--statutes", "--services", "--out"]
        if all(flag in validator_text for flag in required_flags):
            scores["validator_cli_flags_present"] = 1.0

    agreement_text = _safe_read_text(agreement_path)
    requirements = _safe_load_json(requirements_path) or {}
    statutes = _safe_load_json(statutes_path) or {}
    services_rows = _safe_read_csv(services_path) or []

    placeholders_replaced = False
    if agreement_text is not None:
        expected_values = {
            "[LOCAL_GOV]": "Town of Maple Falls",
            "[PARTNER_GOV]": "Pine Ridge Township",
            "[SERVICE_NAME]": "Public Works Equipment Sharing",
            "[EFFECTIVE_DATE]": "2026-07-01",
        }
        placeholders_absent = all(ph not in agreement_text for ph in expected_values.keys())
        values_present = all(val in agreement_text for val in expected_values.values())
        if placeholders_absent and values_present:
            placeholders_replaced = True
            scores["agreement_placeholders_replaced_correctly"] = 1.0

        sections = _parse_markdown_sections(agreement_text)
        term_sec = _find_section_by_title_substring(sections, "term and termination".lower())
        term_checks = False
        if term_sec is not None:
            body = term_sec["body_lower"]
            has_3_year = re.search(r'\b3\s*[- ]?\s*year', body) is not None
            has_initial_term = ("initial" in body and "term" in body)
            has_either_party = "either party" in body
            has_60_days = re.search(r'\b60\s*day', body) is not None
            has_written_notice = "written notice" in body
            term_checks = all([has_3_year, has_initial_term, has_either_party, has_60_days, has_written_notice])
        if term_sec is not None and term_checks:
            scores["agreement_has_term_and_termination_section_with_required_details"] = 1.0

        prom_sec = _find_section_by_title_substring(sections, "public records and open meetings".lower())
        prom_checks = False
        if prom_sec is not None:
            body = prom_sec["body_lower"]
            prom_checks = ("public records" in body and "open meetings" in body)
        if prom_sec is not None and prom_checks:
            scores["agreement_has_public_records_and_open_meetings_section"] = 1.0

        # Only award statute citation presence if the agreement has been edited (placeholders replaced)
        if placeholders_replaced:
            allowed_citations = [c for c in (statutes.get("allowed_citations") or []) if isinstance(c, str)]
            agreement_lower = agreement_text.lower()
            statute_ok = any(str(c).lower() in agreement_lower for c in allowed_citations)
            if statute_ok:
                scores["agreement_statutory_citation_allowed_present"] = 1.0

    # Recompute clause checks for cross-validation with compliance report and readiness
    clause_results: Dict[str, Tuple[bool, str]] = {}
    if agreement_text is not None and isinstance(requirements, dict) and isinstance(statutes, dict):
        try:
            sections = _parse_markdown_sections(agreement_text)
            clause_results = _compute_clause_results(agreement_text, sections, requirements, statutes)
        except Exception:
            clause_results = {}

    # Validate compliance report JSON
    comp = _safe_load_json(compliance_report_path)
    if isinstance(comp, dict):
        structure_ok = True
        structure_ok = structure_ok and comp.get("checked_file") == "input/draft_interlocal_agreement.md"
        summary = comp.get("summary") if isinstance(comp.get("summary"), dict) else None
        details = comp.get("details") if isinstance(comp.get("details"), list) else None
        if summary is None or details is None:
            structure_ok = False
        else:
            try:
                total = int(summary.get("total"))
                passed = int(summary.get("passed"))
                failed = int(summary.get("failed"))
            except Exception:
                structure_ok = False
                total = passed = failed = 0
            if isinstance(details, list) and len(details) == total:
                for d in details:
                    if not isinstance(d, dict):
                        structure_ok = False
                        break
                    key = d.get("key")
                    title = d.get("title")
                    status = d.get("status")
                    evidence = d.get("evidence")
                    if not (isinstance(key, str) and isinstance(title, str) and isinstance(status, str) and status in ("pass", "fail") and isinstance(evidence, str)):
                        structure_ok = False
                        break
            else:
                structure_ok = False

        if structure_ok:
            scores["compliance_report_exists_and_structure_valid"] = 1.0

        statuses_match = False
        all_pass = False
        if structure_ok and clause_results:
            detail_by_key = {d.get("key"): d for d in details}
            try:
                compare_ok = True
                for clause in requirements.get("mandatory_clauses", []):
                    key = clause.get("key")
                    expected = "pass" if clause_results.get(key, (False, ""))[0] else "fail"
                    actual = detail_by_key.get(key, {}).get("status")
                    if actual != expected:
                        compare_ok = False
                        break
                statuses_match = compare_ok
                total_calc = len(requirements.get("mandatory_clauses", []))
                passed_calc = sum(1 for k, (ok, _) in clause_results.items() if ok)
                failed_calc = total_calc - passed_calc
                all_pass = (passed_calc == total_calc) and (failed_calc == 0)
                if not (total == total_calc and passed == passed_calc and failed == failed_calc):
                    statuses_match = False
            except Exception:
                statuses_match = False
        if statuses_match and all_pass:
            scores["compliance_report_all_clauses_pass_and_match_recomputation"] = 1.0

    # Validate service readiness CSV
    readiness_rows = _safe_read_csv(readiness_csv_path)
    if isinstance(readiness_rows, list) and len(readiness_rows) > 0:
        expected_cols = ["rank", "service", "coverage_ratio", "risk_weight", "required_clauses", "covered_keys"]
        cols_ok = all(all(col in row for col in expected_cols) for row in readiness_rows)
        try:
            ranks = [int(str(row["rank"]).strip()) for row in readiness_rows]
            rank_seq_ok = ranks == list(range(1, len(ranks) + 1))
        except Exception:
            rank_seq_ok = False
        if cols_ok and rank_seq_ok:
            scores["service_readiness_exists_and_structure_valid"] = 1.0

        compare_ok = False
        if clause_results and services_rows:
            recomputed = _compute_service_readiness(services_rows, requirements, clause_results)
            try:
                parsed_rows = []
                for row in readiness_rows:
                    try:
                        coverage_ratio = float(str(row["coverage_ratio"]).strip())
                    except Exception:
                        coverage_ratio = None
                    try:
                        risk_weight = int(str(row["risk_weight"]).strip())
                    except Exception:
                        risk_weight = None
                    parsed_rows.append({
                        "rank": int(str(row["rank"]).strip()),
                        "service": (row["service"] or "").strip(),
                        "coverage_ratio": coverage_ratio,
                        "risk_weight": risk_weight,
                        "required_clauses": _normalize_semicolon_or_comma_list(row.get("required_clauses") or ""),
                        "covered_keys": _normalize_semicolon_or_comma_list(row.get("covered_keys") or ""),
                    })
                order_ok = [r["service"] for r in parsed_rows] == [r["service"] for r in recomputed]
                fields_ok = True
                input_req_map = { (row.get("service") or "").strip(): _normalize_semicolon_or_comma_list(row.get("required_clauses") or "") for row in services_rows }
                for parsed, exp in zip(parsed_rows, recomputed):
                    if parsed["service"] != exp["service"]:
                        fields_ok = False
                        break
                    if not isinstance(parsed["coverage_ratio"], float) or not _float_equal(parsed["coverage_ratio"], exp["coverage_ratio"]):
                        fields_ok = False
                        break
                    if parsed["risk_weight"] != exp["risk_weight"]:
                        fields_ok = False
                        break
                    input_req = input_req_map.get(parsed["service"], [])
                    if set([k.strip() for k in parsed["required_clauses"]]) != set([k.strip() for k in input_req]):
                        fields_ok = False
                        break
                    if set([k.strip() for k in parsed["covered_keys"]]) != set([k.strip() for k in exp["covered_keys"]]):
                        fields_ok = False
                        break
                compare_ok = (order_ok and fields_ok)
            except Exception:
                compare_ok = False
        if compare_ok:
            scores["service_readiness_correct_ranking_and_coverage"] = 1.0

    # Validate mayor update
    mayor_text = _safe_read_text(mayor_update_path)
    if mayor_text is not None:
        has_sections_listed = ("Term and Termination" in mayor_text) and ("Public Records and Open Meetings" in mayor_text)
        if has_sections_listed:
            scores["mayor_update_exists_and_sections_listed"] = 1.0

        comp2 = _safe_load_json(compliance_report_path)
        if isinstance(comp2, dict) and isinstance(comp2.get("summary"), dict):
            try:
                total2 = int(comp2["summary"].get("total"))
                passed2 = int(comp2["summary"].get("passed"))
                failed2 = int(comp2["summary"].get("failed"))
                lines = mayor_text.splitlines()
                found_line = False
                pattern = re.compile(rf'\b{total2}\b.*checked.*\b{passed2}\b.*passed.*\b{failed2}\b.*failed', re.IGNORECASE)
                for line in lines:
                    if pattern.search(line):
                        found_line = True
                        break
                if found_line:
                    scores["mayor_update_summary_matches_report"] = 1.0
            except Exception:
                pass

        readiness_rows2 = _safe_read_csv(readiness_csv_path)
        if readiness_rows2:
            top3 = []
            for row in readiness_rows2[:3]:
                service = (row.get("service") or "").strip()
                cov = (row.get("coverage_ratio") or "").strip()
                risk = (row.get("risk_weight") or "").strip()
                top3.append((service, cov, risk))
            if len(top3) == 3:
                lines = mayor_text.splitlines()
                ok = True
                start_idx = 0
                for (svc, cov, risk) in top3:
                    found_idx = -1
                    for i in range(start_idx, len(lines)):
                        if svc in lines[i]:
                            found_idx = i
                            break
                    if found_idx == -1:
                        ok = False
                        break
                    candidate_ratio_strs = {cov}
                    try:
                        cov_float = float(cov)
                        for cand in _coverage_ratio_str_candidates(cov_float):
                            candidate_ratio_strs.add(cand)
                    except Exception:
                        pass
                    line_window = lines[found_idx]
                    if found_idx + 1 < len(lines):
                        line_window += " " + lines[found_idx + 1]
                    has_ratio = any(rstr in line_window for rstr in candidate_ratio_strs)
                    has_risk = risk in line_window
                    if not (has_ratio and has_risk):
                        ok = False
                        break
                    start_idx = found_idx + 1
                if ok:
                    scores["mayor_update_top3_matches_readiness"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()