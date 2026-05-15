import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Tuple[bool, List[Dict[str, str]], List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames or []
        return True, rows, header
    except Exception:
        return False, [], []


def _parse_int(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _strip(s: str) -> str:
    return s.strip() if isinstance(s, str) else s


def _compute_expected_for_row(row: Dict[str, str]) -> Tuple[int, List[str]]:
    tokens: List[str] = []
    score = 0

    inconsistencies = (_strip(row.get("InconsistenciesFlag", "")) == "Y")
    prior_claims = _parse_int(row.get("PriorClaimsCount", "0")) or 0
    surveillance = (_strip(row.get("SurveillanceFlag", "")) == "Y")
    prop_damage = _parse_int(row.get("PropertyDamageUSD", "0")) or 0
    witness_count = _parse_int(row.get("WitnessCount", "0")) or 0
    strict_pleading = (_strip(row.get("StrictPleadingVenueFlag", "")) == "Y")
    severity = _strip(row.get("InjurySeverityReported", ""))
    social = (_strip(row.get("ClaimantSocialMediaFlag", "")) == "Y")
    demand = _parse_int(row.get("DemandUSD", "0")) or 0

    if inconsistencies:
        score += 3
        tokens.append("Inconsistencies")

    if prior_claims >= 2:
        score += 2
        tokens.append(f"PriorClaims({prior_claims})")
    elif prior_claims == 1:
        score += 1
        tokens.append("PriorClaims(1)")

    if surveillance:
        score += 2
        tokens.append("Surveillance")

    if prop_damage < 1000:
        score += 1
        tokens.append("LowPropertyDamage")

    if witness_count == 0:
        score += 1
        tokens.append("NoWitnesses")

    if strict_pleading:
        score += 1
        tokens.append("StrictPleadingVenue")

    if severity == "Minor":
        score += 1
        tokens.append("SeverityMinor")
    elif severity == "Severe":
        score -= 1
        tokens.append("SeveritySevere")

    if social:
        score += 1
        tokens.append("SocialMedia")

    if demand > 30000:
        score -= 1
        tokens.append("HighDemand")

    return score, tokens


def _expected_sorted_order(rows: List[Dict[str, str]]) -> List[str]:
    computed = []
    for r in rows:
        score, _ = _compute_expected_for_row(r)
        demand = _parse_int(r.get("DemandUSD", "0")) or 0
        computed.append((r.get("ClaimID", ""), score, demand))
    computed.sort(key=lambda x: (-x[1], x[2], x[0]))
    return [cid for cid, _, _ in computed]


def _tokenize_rationale(rationale: str) -> List[str]:
    parts = [p.strip() for p in rationale.split(";")]
    return [p for p in parts if p]


def _original_header() -> List[str]:
    return [
        "ClaimID",
        "ClaimantName",
        "AccidentType",
        "DemandUSD",
        "PriorClaimsCount",
        "InjurySeverityReported",
        "PropertyDamageUSD",
        "WitnessCount",
        "InconsistenciesFlag",
        "SurveillanceFlag",
        "StrictPleadingVenueFlag",
        "ClaimantSocialMediaFlag",
    ]


def _factor_keywords_for_tokens(tokens: List[str]) -> List[str]:
    mapping = {
        "Inconsistencies": ["inconsist"],
        "PriorClaims": ["prior"],
        "Surveillance": ["surveillance"],
        "LowPropertyDamage": ["property"],
        "NoWitnesses": ["witness"],
        "StrictPleadingVenue": ["pleading", "venue"],
        "SeverityMinor": ["severity"],
        "SeveritySevere": ["severity"],
        "SocialMedia": ["social"],
        "HighDemand": ["demand"],
    }
    keywords: List[str] = []
    for t in tokens:
        base = t
        if t.startswith("PriorClaims"):
            base = "PriorClaims"
        kws = mapping.get(base, [])
        keywords.extend(kws)
    seen = set()
    dk: List[str] = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            dk.append(k)
    return dk


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "ranked_cases_exists_and_columns": 0.0,
        "ranked_cases_row_count": 0.0,
        "ranked_cases_scores_correct": 0.0,
        "ranked_cases_rationale_tokens_and_order": 0.0,
        "ranked_cases_sorted_correctly": 0.0,
        "ranked_cases_source_fields_preserved": 0.0,
        "talking_points_top3_sections_and_order": 0.0,
        "talking_points_placeholders_replaced": 0.0,
        "talking_points_include_scores_and_vulnerabilities": 0.0,
        "meeting_notes_intro_and_structure": 0.0,
        "meeting_notes_top5_with_actions_roles": 0.0,
        "client_email_word_count_and_placeholders": 0.0,
        "client_email_lists_top5_with_scores_and_rationales": 0.0,
        "client_email_mentions_ranked_and_next_steps": 0.0,
        "outputs_reference_claimids": 0.0,
    }

    input_cases_path = workspace / "input" / "cases.csv"
    ok_input, input_rows, input_header = _safe_read_csv_dicts(input_cases_path)
    if not ok_input or not input_rows:
        return scores

    input_by_id = {r.get("ClaimID", ""): r for r in input_rows}
    expected_header = _original_header()

    expected_scores: Dict[str, int] = {}
    expected_tokens: Dict[str, List[str]] = {}
    for r in input_rows:
        cid = r.get("ClaimID", "")
        sc, toks = _compute_expected_for_row(r)
        expected_scores[cid] = sc
        expected_tokens[cid] = toks
    expected_order = _expected_sorted_order(input_rows)
    top3 = expected_order[:3]
    top5 = expected_order[:5]

    ranked_path = workspace / "output" / "ranked_cases.csv"
    ok_ranked, ranked_rows, ranked_header = _safe_read_csv_dicts(ranked_path)
    if ok_ranked and ranked_rows:
        expected_ranked_header = expected_header + ["DismissalScore", "Rationale"]
        if ranked_header == expected_ranked_header:
            scores["ranked_cases_exists_and_columns"] = 1.0

        if len(ranked_rows) == len(input_rows):
            scores["ranked_cases_row_count"] = 1.0

        scores_ok = True
        rationale_ok = True
        source_preserved_ok = True
        file_order: List[str] = []

        for rr in ranked_rows:
            cid = rr.get("ClaimID", "")
            if not cid or cid not in input_by_id:
                scores_ok = False
                rationale_ok = False
                source_preserved_ok = False
                continue
            file_order.append(cid)
            ds = _parse_int(rr.get("DismissalScore", ""))
            if ds is None or ds != expected_scores[cid]:
                scores_ok = False

            rationale_str = rr.get("Rationale", "")
            rtoks = _tokenize_rationale(rationale_str)
            if rtoks != expected_tokens[cid]:
                rationale_ok = False

            for col in expected_header:
                in_val = _strip(input_by_id[cid].get(col, ""))
                out_val = _strip(rr.get(col, ""))
                if col in ("DemandUSD", "PriorClaimsCount", "PropertyDamageUSD", "WitnessCount"):
                    in_num = _parse_int(in_val)
                    out_num = _parse_int(out_val)
                    if in_num is None or out_num is None or in_num != out_num:
                        source_preserved_ok = False
                        break
                else:
                    if in_val != out_val:
                        source_preserved_ok = False
                        break

        if scores_ok:
            scores["ranked_cases_scores_correct"] = 1.0
        if rationale_ok:
            scores["ranked_cases_rationale_tokens_and_order"] = 1.0
        if source_preserved_ok:
            scores["ranked_cases_source_fields_preserved"] = 1.0

        if file_order == expected_order:
            scores["ranked_cases_sorted_correctly"] = 1.0

    tp_path = workspace / "output" / "talking_points_top3.md"
    tp_text = _safe_read_text(tp_path)
    if tp_text:
        found_ids = []
        for m in re.finditer(r"CID-\d{4}", tp_text):
            cid = m.group(0)
            if cid not in found_ids:
                found_ids.append(cid)
        if found_ids[:3] == top3 and len([cid for cid in found_ids if cid in top3]) >= 3:
            scores["talking_points_top3_sections_and_order"] = 1.0

        placeholders = [
            "[CLAIMID]", "[CLAIMANT]", "[ACCIDENT_TYPE]", "[SEVERITY]", "[DEMAND]",
            "[STRICT_PLEADING]", "[INCONSISTENCIES]", "[PRIOR_CLAIMS]", "[SURVEILLANCE]",
            "[PROPERTY_DAMAGE]", "[WITNESSES]", "[SOCIAL_MEDIA]"
        ]
        if not any(ph in tp_text for ph in placeholders):
            scores["talking_points_placeholders_replaced"] = 1.0

        lines = tp_text.splitlines()
        case_indices = [i for i, ln in enumerate(lines) if ln.strip().lower().startswith("case:")]
        section_ok_count = 0
        for idx, start in enumerate(case_indices[:3]):
            end = case_indices[idx + 1] if idx + 1 < len(case_indices) else len(lines)
            section_lines = lines[start:end]
            section_text = "\n".join(section_lines)
            cid_match = re.search(r"CID-\d{4}", section_lines[0]) if section_lines else None
            if not cid_match:
                continue
            cid = cid_match.group(0)
            claimant_name = input_by_id.get(cid, {}).get("ClaimantName", "")
            if claimant_name and claimant_name not in section_text:
                continue
            if "Snapshot" not in section_text:
                continue
            exp_score = expected_scores.get(cid)
            if exp_score is None or str(exp_score) not in section_text:
                continue
            toks = expected_tokens.get(cid, [])
            kws = _factor_keywords_for_tokens(toks)
            vuln_hits = 0
            for kw in kws:
                if re.search(rf"{re.escape(kw)}", section_text, flags=re.IGNORECASE):
                    vuln_hits += 1
            if vuln_hits >= 2:
                section_ok_count += 1
        if section_ok_count == 3:
            scores["talking_points_include_scores_and_vulnerabilities"] = 1.0

    mn_path = workspace / "output" / "meeting_notes.md"
    mn_text = _safe_read_text(mn_path)
    if mn_text:
        mn_lines = [ln for ln in mn_text.splitlines()]
        nonempty = [ln for ln in mn_lines if ln.strip()]
        intro_ok = False
        if nonempty:
            intro_ok = bool(re.search(r"ordered\s+by\s+dismissalscore", nonempty[0], flags=re.IGNORECASE))
        if intro_ok:
            scores["meeting_notes_intro_and_structure"] = 1.0

        roles = ["Attorney", "Paralegal", "Investigator"]
        total_cases_ok = 0
        for cid in top5:
            name = input_by_id[cid]["ClaimantName"]
            occ_indices = [i for i, ln in enumerate(mn_lines) if cid in ln]
            if not occ_indices:
                continue
            start_idx = occ_indices[0]
            end_idx = min(len(mn_lines), start_idx + 12)
            block_lines = mn_lines[start_idx:end_idx]
            if not any(name in bl for bl in block_lines):
                continue
            toks = expected_tokens.get(cid, [])
            kws = _factor_keywords_for_tokens(toks)
            actionable = 0
            for bl in block_lines[1:]:
                if not bl.strip().startswith(("-", "*")):
                    continue
                if not any(role.lower() in bl.lower() for role in roles):
                    continue
                if any(re.search(rf"{re.escape(kw)}", bl, flags=re.IGNORECASE) for kw in kws):
                    actionable += 1
            if actionable >= 2:
                total_cases_ok += 1
        if total_cases_ok == 5:
            scores["meeting_notes_top5_with_actions_roles"] = 1.0

    ce_path = workspace / "output" / "client_email.txt"
    ce_text = _safe_read_text(ce_path)
    if ce_text:
        words = re.findall(r"\b\w+\b", ce_text)
        length_ok = 250 <= len(words) <= 350
        no_placeholders = all(p not in ce_text for p in ["[TEAM]", "[ATTORNEY]", "Placeholder"])
        first_nonempty = [ln for ln in ce_text.splitlines() if ln.strip()][:3]
        team_ok = any(re.search(r"\bteam\b", ln, flags=re.IGNORECASE) for ln in first_nonempty) if first_nonempty else False
        if length_ok and no_placeholders and team_ok:
            scores["client_email_word_count_and_placeholders"] = 1.0

        per_case_ok = 0
        ce_lines = ce_text.splitlines()
        for cid in top5:
            idxs = [i for i, ln in enumerate(ce_lines) if cid in ln]
            if not idxs:
                continue
            idx = idxs[0]
            line = ce_lines[idx]
            next_line = ce_lines[idx + 1] if idx + 1 < len(ce_lines) else ""
            exp_score = expected_scores[cid]
            score_present = (str(exp_score) in line) or (str(exp_score) in next_line)
            kws = _factor_keywords_for_tokens(expected_tokens[cid])
            kw_present = any(re.search(rf"{re.escape(kw)}", line, flags=re.IGNORECASE) for kw in kws) or any(
                re.search(rf"{re.escape(kw)}", next_line, flags=re.IGNORECASE) for kw in kws
            )
            if score_present and kw_present:
                per_case_ok += 1
        if per_case_ok == 5:
            scores["client_email_lists_top5_with_scores_and_rationales"] = 1.0

        ranked_mention = bool(re.search(r"\brank", ce_text, flags=re.IGNORECASE))
        next_steps_mention = bool(re.search(r"next steps", ce_text, flags=re.IGNORECASE))
        if ranked_mention and next_steps_mention:
            scores["client_email_mentions_ranked_and_next_steps"] = 1.0

    tp_has_id = bool(tp_text and re.search(r"CID-\d{4}", tp_text))
    mn_has_id = bool(mn_text and re.search(r"CID-\d{4}", mn_text))
    ce_has_id = bool(ce_text and re.search(r"CID-\d{4}", ce_text))
    if tp_has_id and mn_has_id and ce_has_id:
        scores["outputs_reference_claimids"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()