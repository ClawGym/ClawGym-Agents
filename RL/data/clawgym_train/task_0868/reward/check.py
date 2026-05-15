import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_lines(path: Path) -> Optional[List[str]]:
    txt = _read_text(path)
    if txt is None:
        return None
    return txt.splitlines()


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_claim_text(s: str) -> str:
    s = s.strip()
    s = re.sub(r'^[\-\*\u2022]\s*', '', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip().lower()


def _extract_claims_from_rumor(text: str) -> List[str]:
    claims: List[str] = []
    for line in text.splitlines():
        if re.match(r'^\s*-\s+', line):
            claim = re.sub(r'^\s*-\s+', '', line).strip()
            if claim:
                claims.append(claim)
    return claims


def _map_source_name_to_path(workspace: Path, src: str) -> Optional[Path]:
    src_clean = src.strip().lstrip("./")
    base = Path(src_clean)
    known = {
        "event_flyer.md": workspace / "input" / "event_flyer.md",
        "park_permit.txt": workspace / "input" / "park_permit.txt",
        "city_ordinance_excerpt.txt": workspace / "input" / "city_ordinance_excerpt.txt",
        "input/event_flyer.md": workspace / "input" / "event_flyer.md",
        "input/park_permit.txt": workspace / "input" / "park_permit.txt",
        "input/city_ordinance_excerpt.txt": workspace / "input" / "city_ordinance_excerpt.txt",
    }
    if src_clean in known:
        return known[src_clean]
    name = base.name
    if name in known:
        return known[name]
    ipath = workspace / "input" / name
    if ipath.exists():
        return ipath
    return None


def _join_lines_by_numbers(lines: List[str], nums: List[int]) -> Optional[str]:
    try:
        selected = [lines[i - 1] for i in nums]
        return "\n".join(selected)
    except Exception:
        return None


def _validate_evidence_item(item: Any, workspace: Path) -> bool:
    if not isinstance(item, dict):
        return False
    for key in ("source_file", "line_numbers", "excerpt"):
        if key not in item:
            return False
    if not isinstance(item["source_file"], str):
        return False
    if not isinstance(item["line_numbers"], list) or not all(isinstance(x, int) and x >= 1 for x in item["line_numbers"]):
        return False
    if not isinstance(item["excerpt"], str):
        return False
    src_path = _map_source_name_to_path(workspace, item["source_file"])
    if src_path is None or not src_path.exists():
        return False
    src_lines = _read_lines(src_path)
    if src_lines is None:
        return False
    expected_excerpt = _join_lines_by_numbers(src_lines, item["line_numbers"])
    if expected_excerpt is None:
        return False
    return item["excerpt"] == expected_excerpt


def _contains_relevant_token(text: str, tokens: List[str]) -> bool:
    low = text.lower()
    return any(tok in low for tok in tokens)


def _compute_expected_status(claim: str) -> str:
    c = claim.lower()
    if any(w in c for w in ["beer", "wine", "alcohol"]):
        return "Contradicted"
    if "vape" in c or "vaping" in c:
        return "Contradicted"
    if "music" in c and ("11:00" in c or "11" in c):
        return "Contradicted"
    if any(w in c for w in ["dogs", "dog", "pet-friendly", "pets", "pet friendly"]):
        return "Contradicted"
    if "proceeds" in c and "youth center" in c:
        return "Supported"
    return "Not Found"


def _parse_summary_claim_lines(lines: List[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for line in lines:
        if "Claim:" in line and "Status:" in line:
            m = re.search(r'Claim:\s*(.+?)\s*(?:—|-)?\s*Status:\s*([A-Za-z ]+)\s*$', line)
            if not m:
                m = re.search(r'Claim:\s*(.+?)\s*Status:\s*([A-Za-z ]+)\s*$', line)
            if m:
                claim_text = m.group(1).strip()
                status = m.group(2).strip()
                mapping[_normalize_claim_text(claim_text)] = status
    return mapping


def _find_bottom_line_block(lines: List[str]) -> Optional[str]:
    for idx, line in enumerate(lines):
        if re.search(r'bottom\s*line', line, flags=re.IGNORECASE):
            block_lines = [line]
            j = idx + 1
            while j < len(lines) and lines[j].strip() != "":
                block_lines.append(lines[j])
                j += 1
            return "\n".join(block_lines)
    return None


def _has_file_citation_with_line_numbers(text: str) -> bool:
    patterns = [
        r'(event_flyer\.md).{0,80}\bline[s]?\s*\d',
        r'(park_permit\.txt).{0,80}\bline[s]?\s*\d',
        r'(city_ordinance_excerpt\.txt).{0,80}\bline[s]?\s*\d',
        r'(event_flyer\.md).{0,5}L\d',
        r'(park_permit\.txt).{0,5}L\d',
        r'(city_ordinance_excerpt\.txt).{0,5}L\d',
    ]
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "outputs_exist": 0.0,
        "findings_json_parseable": 0.0,
        "findings_length_matches_claims": 0.0,
        "findings_schema_valid": 0.0,
        "findings_status_correct": 0.0,
        "findings_evidence_sides_correct": 0.0,
        "findings_evidence_lines_and_excerpts_valid": 0.0,
        "findings_evidence_relevant": 0.0,
        "summary_has_title": 0.0,
        "summary_claim_lines_correct": 0.0,
        "summary_bottom_line_quality": 0.0,
        "email_has_subject": 0.0,
        "email_content_coverage": 0.0,
        "email_citation_present": 0.0,
        "script_exists_and_references": 0.0,
        "run_command_present_and_valid": 0.0,
    }

    rumor_path = workspace / "input" / "rumor_message.txt"
    flyer_path = workspace / "input" / "event_flyer.md"
    permit_path = workspace / "input" / "park_permit.txt"
    ordinance_path = workspace / "input" / "city_ordinance_excerpt.txt"

    findings_path = workspace / "output" / "factcheck" / "findings.json"
    summary_path = workspace / "output" / "reports" / "summary.md"
    email_path = workspace / "output" / "email" / "family_update.txt"
    script_path = workspace / "scripts" / "factcheck.py"
    run_cmd_path = workspace / "output" / "run_command.txt"

    rumor_text = _read_text(rumor_path) or ""
    flyer_lines = _read_lines(flyer_path)
    permit_lines = _read_lines(permit_path)
    ordinance_lines = _read_lines(ordinance_path)

    claims = _extract_claims_from_rumor(rumor_text) if rumor_text else []
    expected_status_by_claim = {_normalize_claim_text(c): _compute_expected_status(c) for c in claims}

    out_exist_count = sum(1 for p in [findings_path, summary_path, email_path] if p.exists())
    if out_exist_count == 3:
        scores["outputs_exist"] = 1.0
    elif out_exist_count > 0:
        scores["outputs_exist"] = out_exist_count / 3.0
    else:
        scores["outputs_exist"] = 0.0

    findings_json: Any = None
    if findings_path.exists():
        findings_json = _load_json(findings_path)

    if isinstance(findings_json, list):
        scores["findings_json_parseable"] = 1.0
    else:
        scores["findings_json_parseable"] = 0.0

    if isinstance(findings_json, list) and claims:
        scores["findings_length_matches_claims"] = 1.0 if len(findings_json) == len(claims) else 0.0
    elif isinstance(findings_json, list) and not claims:
        scores["findings_length_matches_claims"] = 1.0 if len(findings_json) == 0 else 0.0
    else:
        scores["findings_length_matches_claims"] = 0.0

    schema_ok = True
    status_correct_count = 0
    sides_correct_count = 0
    total_claims = len(claims) if claims else 0
    evidence_items_total = 0
    evidence_items_valid = 0
    evidence_relevant_count = 0

    if isinstance(findings_json, list) and claims:
        found_by_claim: Dict[str, Dict[str, Any]] = {}
        for item in findings_json:
            if not isinstance(item, dict):
                schema_ok = False
                continue
            for key in ("claim_text", "status", "supporting_evidence", "contradicting_evidence"):
                if key not in item:
                    schema_ok = False
            if not isinstance(item.get("claim_text"), str):
                schema_ok = False
            if item.get("status") not in ("Supported", "Contradicted", "Not Found", "Inconsistent"):
                schema_ok = False
            if not isinstance(item.get("supporting_evidence"), list) or not isinstance(item.get("contradicting_evidence"), list):
                schema_ok = False
            norm_claim = _normalize_claim_text(item.get("claim_text", ""))
            found_by_claim[norm_claim] = item

        for orig_claim in claims:
            norm = _normalize_claim_text(orig_claim)
            expected_status = expected_status_by_claim.get(norm, "Not Found")
            item = found_by_claim.get(norm)
            if item is None:
                continue
            actual_status = item.get("status")
            if actual_status == expected_status:
                status_correct_count += 1

            sup = item.get("supporting_evidence", [])
            con = item.get("contradicting_evidence", [])
            sup_nonempty = isinstance(sup, list) and len(sup) > 0
            con_nonempty = isinstance(con, list) and len(con) > 0
            sides_ok = False
            if expected_status == "Supported":
                sides_ok = sup_nonempty and not con_nonempty
            elif expected_status == "Contradicted":
                sides_ok = con_nonempty
            elif expected_status == "Not Found":
                sides_ok = not sup_nonempty and not con_nonempty
            elif expected_status == "Inconsistent":
                sides_ok = sup_nonempty and con_nonempty
            if sides_ok:
                sides_correct_count += 1

            relevant_tokens_supported: List[str] = []
            relevant_tokens_contradicted: List[str] = []
            lc = norm
            if any(k in lc for k in ["beer", "wine", "alcohol"]):
                relevant_tokens_supported = ["alcohol permitted", "alcohol allowed"]
                relevant_tokens_contradicted = ["no alcohol", "alcohol allowed: no", "alcoholic beverages are prohibited"]
            elif "vape" in lc or "vaping" in lc:
                relevant_tokens_supported = ["vape"]
                relevant_tokens_contradicted = ["no smoking or vaping", "vapor products is prohibited", "vapor products are prohibited", "prohibited at city-permitted events"]
            elif "music" in lc and ("11:00" in lc or "11" in lc):
                relevant_tokens_supported = ["11:00", "11 pm"]
                relevant_tokens_contradicted = ["10:00–20:00", "20:00", "8:00 pm", "amplified sound end time"]
            elif any(w in lc for w in ["dogs", "dog", "pets", "pet-friendly", "pet friendly"]):
                relevant_tokens_supported = ["dogs are welcome", "pet-friendly"]
                relevant_tokens_contradicted = ["service animals only", "only service animals"]
            elif "proceeds" in lc and "youth center" in lc:
                relevant_tokens_supported = ["proceeds", "youth center"]
                relevant_tokens_contradicted = []

            for ev in sup + con:
                evidence_items_total += 1
                if _validate_evidence_item(ev, workspace):
                    evidence_items_valid += 1

            relevance_ok = False
            if expected_status == "Supported":
                if isinstance(sup, list) and any(_contains_relevant_token(e.get("excerpt", ""), relevant_tokens_supported) for e in sup if isinstance(e, dict)):
                    relevance_ok = True
            elif expected_status == "Contradicted":
                if isinstance(con, list) and any(_contains_relevant_token(e.get("excerpt", ""), relevant_tokens_contradicted) for e in con if isinstance(e, dict)):
                    relevance_ok = True
            elif expected_status == "Inconsistent":
                sup_ok = isinstance(sup, list) and any(_contains_relevant_token(e.get("excerpt", ""), relevant_tokens_supported) for e in sup if isinstance(e, dict))
                con_ok = isinstance(con, list) and any(_contains_relevant_token(e.get("excerpt", ""), relevant_tokens_contradicted) for e in con if isinstance(e, dict))
                relevance_ok = sup_ok and con_ok
            elif expected_status == "Not Found":
                relevance_ok = True

            if relevance_ok:
                evidence_relevant_count += 1

    scores["findings_schema_valid"] = 1.0 if schema_ok and isinstance(findings_json, list) else 0.0
    if total_claims > 0:
        scores["findings_status_correct"] = status_correct_count / total_claims
        scores["findings_evidence_sides_correct"] = sides_correct_count / total_claims
        scores["findings_evidence_relevant"] = evidence_relevant_count / total_claims
    else:
        scores["findings_status_correct"] = 0.0
        scores["findings_evidence_sides_correct"] = 0.0
        scores["findings_evidence_relevant"] = 0.0
    if evidence_items_total > 0:
        scores["findings_evidence_lines_and_excerpts_valid"] = evidence_items_valid / evidence_items_total
    else:
        scores["findings_evidence_lines_and_excerpts_valid"] = 0.0

    summary_text = _read_text(summary_path) or ""
    summary_lines = summary_text.splitlines() if summary_text else []

    first_nonempty = ""
    for ln in summary_lines:
        if ln.strip():
            first_nonempty = ln.strip()
            break
    scores["summary_has_title"] = 1.0 if first_nonempty else 0.0

    if summary_lines and claims:
        mapping = _parse_summary_claim_lines(summary_lines)
        correct = 0
        for c in claims:
            norm = _normalize_claim_text(c)
            expected = expected_status_by_claim.get(norm, "Not Found")
            actual = mapping.get(norm)
            if actual == expected:
                correct += 1
        if len(claims) > 0:
            scores["summary_claim_lines_correct"] = correct / len(claims)
        else:
            scores["summary_claim_lines_correct"] = 0.0
    else:
        scores["summary_claim_lines_correct"] = 0.0

    bottom_block = _find_bottom_line_block(summary_lines) if summary_lines else None
    if bottom_block:
        low = bottom_block.lower()
        topics = {
            "alcohol": any(w in low for w in ["alcohol", "beer", "wine"]),
            "vaping": any(w in low for w in ["vaping", "vape", "tobacco"]),
            "music_hours": any(w in low for w in ["music", "11:00", "11 pm", "late", "20:00", "8:00", "8 pm"]),
            "pets": any(w in low for w in ["dogs", "pets", "service animals"]),
            "proceeds": "youth center" in low and "proceed" in low,
            "citations": any(name in bottom_block for name in ["park_permit.txt", "city_ordinance_excerpt.txt", "event_flyer.md"]),
        }
        passed = topics["alcohol"] and topics["vaping"] and topics["proceeds"] and topics["citations"] and (topics["music_hours"] or topics["pets"])
        scores["summary_bottom_line_quality"] = 1.0 if passed else 0.0
    else:
        scores["summary_bottom_line_quality"] = 0.0

    email_text = _read_text(email_path) or ""
    email_lines = email_text.splitlines() if email_text else []
    if email_lines:
        first_line = email_lines[0].strip()
        scores["email_has_subject"] = 1.0 if re.match(r'^\s*subject\s*:', first_line, flags=re.IGNORECASE) else 0.0
    else:
        scores["email_has_subject"] = 0.0

    if email_text:
        lowe = email_text.lower()
        coverage_points = 0
        total_points = 5
        if any(w in lowe for w in ["alcohol", "beer", "wine"]) and any(w in lowe for w in ["not allowed", "prohibited", "illegal", "no alcohol"]):
            coverage_points += 1
        if any(w in lowe for w in ["vaping", "vape", "tobacco"]) and any(w in lowe for w in ["prohibited", "not allowed", "illegal"]):
            coverage_points += 1
        if any(w in lowe for w in ["music", "11:00", "11 pm", "late"]) and any(w in lowe for w in ["8:00", "20:00", "8 pm"]):
            coverage_points += 1
        if any(w in lowe for w in ["dogs", "pets", "service animals"]) and any(w in lowe for w in ["service animals only", "not allowed", "only service"]):
            coverage_points += 1
        if "youth center" in lowe and any(w in lowe for w in ["true", "supported", "correct", "confirmed"]):
            coverage_points += 1
        scores["email_content_coverage"] = coverage_points / total_points
        scores["email_citation_present"] = 1.0 if _has_file_citation_with_line_numbers(email_text) else 0.0
    else:
        scores["email_content_coverage"] = 0.0
        scores["email_citation_present"] = 0.0

    script_score = 0.0
    if script_path.exists():
        script_score += 0.5
        content = _read_text(script_path) or ""
        refs = 0
        if "input/rumor_message.txt" in content:
            refs += 1
        if "input/event_flyer.md" in content:
            refs += 1
        if "input/park_permit.txt" in content:
            refs += 1
        if "input/city_ordinance_excerpt.txt" in content:
            refs += 1
        if "output/factcheck/findings.json" in content:
            refs += 1
        if "output/reports/summary.md" in content:
            refs += 1
        if "output/email/family_update.txt" in content:
            refs += 1
        if refs >= 3:
            script_score += 0.5
    scores["script_exists_and_references"] = min(script_score, 1.0)

    run_cmd_ok = 0.0
    run_cmd_text = _read_text(run_cmd_path) or ""
    if run_cmd_text:
        if re.search(r'\bpython(\d*\.?\d*)?\b', run_cmd_text) and "scripts/factcheck.py" in run_cmd_text:
            run_cmd_ok = 1.0
    scores["run_command_present_and_valid"] = run_cmd_ok

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()