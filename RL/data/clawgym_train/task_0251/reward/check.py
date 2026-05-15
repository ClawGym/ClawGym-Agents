import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_scalar(value: str) -> Any:
    v = value.strip()
    v = _strip_quotes(v)
    try:
        if re.fullmatch(r"-?\d+", v):
            return int(v)
    except Exception:
        pass
    try:
        if re.fullmatch(r"-?\d*\.\d+", v):
            return float(v)
    except Exception:
        pass
    return v


def _parse_yaml_simple(text: str) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for a subset:
    - nested mappings with indentation
    - lists with '- ' items
    - scalar values (ints, floats, strings, quoted strings)
    """
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Any]] = [(0, root)]
    potential_list_parent: Dict[int, Tuple[Dict[str, Any], str]] = {}

    lines = text.splitlines()
    for raw_line in lines:
        if not raw_line.strip():
            continue
        if raw_line.strip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while stack and stack[-1][0] > indent:
            stack.pop()
        if not stack:
            return None

        current_container = stack[-1][1]

        if line.startswith("- "):
            item_val_str = line[2:].strip()
            item_val = _parse_scalar(item_val_str) if item_val_str else None
            if indent in potential_list_parent:
                parent_dict, key_name = potential_list_parent[indent]
                parent_dict[key_name] = []
                stack.append((indent, parent_dict[key_name]))
                del potential_list_parent[indent]
                current_container = stack[-1][1]
            if isinstance(current_container, dict):
                return None
            if not isinstance(current_container, list):
                return None
            current_container.append(item_val)
            continue

        if ":" in line:
            key_part, val_part = line.split(":", 1)
            key = key_part.strip()
            val = val_part.strip()
            if val == "":
                if isinstance(current_container, dict):
                    current_container[key] = {}
                    stack.append((indent + 2, current_container[key]))
                    potential_list_parent[indent + 2] = (current_container, key)
                else:
                    return None
            else:
                scalar = _parse_scalar(val)
                if isinstance(current_container, dict):
                    current_container[key] = scalar
                else:
                    return None
        else:
            return None

    return root


def _format_amount(amount: int) -> List[str]:
    with_commas = f"{amount:,}"
    without_commas = f"{amount}"
    return [with_commas, f"${with_commas}", without_commas, f"${without_commas}"]


def _contains_amount(text: str, amount: int) -> bool:
    variants = _format_amount(amount)
    for v in variants:
        if v in text:
            return True
    return False


def _find_section_ranges(text: str, labels: List[str]) -> Optional[Dict[str, Tuple[int, int]]]:
    positions: Dict[str, Tuple[int, int]] = {}
    indices = []
    for label in labels:
        idx = text.find(label)
        if idx == -1:
            return None
        indices.append((label, idx))
    prev = -1
    for _, idx in indices:
        if idx < prev:
            return None
        prev = idx
    for i, (label, start_idx) in enumerate(indices):
        if i + 1 < len(indices):
            end_idx = indices[i + 1][1]
        else:
            end_idx = len(text)
        positions[label] = (start_idx, end_idx)
    return positions


def _get_section_text(text: str, label: str, labels: List[str]) -> Optional[str]:
    ranges = _find_section_ranges(text, labels)
    if not ranges or label not in ranges:
        return None
    start, end = ranges[label]
    content = text[start + len(label):end]
    return content.strip()


def _sentence_count(text: str) -> int:
    parts = re.split(r"[\.!?]", text)
    return sum(1 for p in parts if p.strip())


def _extract_large_integers(text: str, minimum: int = 10000) -> List[int]:
    nums: List[int] = []
    for m in re.finditer(r"\$?\d{1,3}(?:,\d{3})+|\$?\d+", text):
        s = m.group(0)
        s_digits = re.sub(r"[^\d]", "", s)
        if s_digits:
            try:
                val = int(s_digits)
                if val >= minimum:
                    nums.append(val)
            except Exception:
                pass
    return nums


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "meeting_summary_sections_present": 0.0,
        "meeting_summary_bill_overview_correct": 0.0,
        "meeting_summary_key_provisions_match_yaml": 0.0,
        "meeting_summary_assumptions_listed_correct": 0.0,
        "meeting_summary_financial_impact_correct": 0.0,
        "meeting_summary_decisions_followups_owners_present": 0.0,
        "meeting_summary_assumption_check_mentions_mismatch": 0.0,
        "memo_subject_bill_id_correct": 0.0,
        "memo_sections_present": 0.0,
        "memo_executive_summary_sentence_count": 0.0,
        "memo_financial_impact_numbers_correct": 0.0,
        "memo_reimbursement_note_mentions_bps_and_timing": 0.0,
        "memo_appendix_assumptions_keys_values_present": 0.0,
        "memo_retains_notes_and_risks_sections": 0.0,
        "cross_file_incremental_cost_consistent": 0.0,
        "email_to_cc_exact": 0.0,
        "email_subject_contains_bill_and_fy_phrase": 0.0,
        "email_body_paragraphs_count": 0.0,
        "email_body_includes_key_figures_paths_bps_risks": 0.0,
    }

    yaml_path = workspace / "input" / "finance_assumptions.yaml"
    yaml_text = _safe_read_text(yaml_path)
    yaml_data: Optional[Dict[str, Any]] = None
    if yaml_text is not None:
        try:
            yaml_data = _parse_yaml_simple(yaml_text)
        except Exception:
            yaml_data = None

    if yaml_data is None:
        return scores

    try:
        bill = yaml_data.get("bill", {})
        staffing = yaml_data.get("staffing", {})
        costing = yaml_data.get("costing", {})
        reimbursement = yaml_data.get("reimbursement", {})
        recipients = yaml_data.get("recipients", {})

        bill_id = bill.get("id")
        bill_title = bill.get("title")
        effective_date = bill.get("effective_date")
        fiscal_year = bill.get("fiscal_year")

        med_surg_ratio = staffing.get("med_surg_ratio")
        icu_ratio = staffing.get("icu_ratio")
        stepdown_ratio = staffing.get("stepdown_ratio")
        additional_hours_pct = staffing.get("additional_hours_pct")

        baseline_hours = costing.get("baseline_annual_nursing_hours")
        avg_hourly_cost = costing.get("avg_hourly_rn_cost_usd")
        training_cost = costing.get("one_time_training_cost_usd")

        medicaid_bps = reimbursement.get("medicaid_base_rate_bps_change")

        board_to = recipients.get("board_to", [])
        cc_addrs = recipients.get("cc", [])

        if None in [
            bill_id, bill_title, effective_date, fiscal_year,
            med_surg_ratio, icu_ratio, stepdown_ratio,
            additional_hours_pct, baseline_hours, avg_hourly_cost,
            training_cost, medicaid_bps
        ]:
            return scores

        expected_incremental_cost = int(round(baseline_hours * additional_hours_pct * avg_hourly_cost))
    except Exception:
        return scores

    summary_path = workspace / "output" / "Meeting_Summary.md"
    memo_path = workspace / "output" / "Legislation_Impact_Memo_Updated.md"
    email_path = workspace / "output" / "Board_Email_Draft.txt"

    summary_text = _safe_read_text(summary_path)
    memo_text = _safe_read_text(memo_path)
    email_text = _safe_read_text(email_path)

    summary_labels = [
        "Bill Overview:",
        "Key Provisions:",
        "Decisions and Follow-ups:",
        "Assumptions (from finance_assumptions.yaml):",
        "Projected Financial Impact:",
        "Assumption Check:",
    ]
    if summary_text is not None:
        ranges = _find_section_ranges(summary_text, summary_labels)
        if ranges is not None:
            scores["meeting_summary_sections_present"] = 1.0

            bill_overview = _get_section_text(summary_text, "Bill Overview:", summary_labels) or ""
            if (str(bill_id) in bill_overview) and (str(bill_title) in bill_overview):
                scores["meeting_summary_bill_overview_correct"] = 1.0

            key_provisions = _get_section_text(summary_text, "Key Provisions:", summary_labels) or ""
            if (
                str(med_surg_ratio) in key_provisions
                and str(icu_ratio) in key_provisions
                and str(stepdown_ratio) in key_provisions
            ):
                scores["meeting_summary_key_provisions_match_yaml"] = 1.0

            assumptions_sec = _get_section_text(summary_text, "Assumptions (from finance_assumptions.yaml):", summary_labels) or ""
            assumptions_ok = all([
                "baseline_annual_nursing_hours" in assumptions_sec and str(baseline_hours) in assumptions_sec,
                "additional_hours_pct" in assumptions_sec and str(additional_hours_pct) in assumptions_sec,
                "avg_hourly_rn_cost_usd" in assumptions_sec and str(avg_hourly_cost) in assumptions_sec,
                "one_time_training_cost_usd" in assumptions_sec and str(training_cost) in assumptions_sec,
                "medicaid_base_rate_bps_change" in assumptions_sec and str(medicaid_bps) in assumptions_sec,
                "effective_date" in assumptions_sec and str(effective_date) in assumptions_sec,
                "fiscal_year" in assumptions_sec and str(fiscal_year) in assumptions_sec,
            ])
            if assumptions_ok:
                scores["meeting_summary_assumptions_listed_correct"] = 1.0

            fin_impact_sec = _get_section_text(summary_text, "Projected Financial Impact:", summary_labels) or ""
            has_incremental = _contains_amount(fin_impact_sec, expected_incremental_cost)
            has_training = _contains_amount(fin_impact_sec, int(training_cost))
            mentions_bps = ("bps" in fin_impact_sec.lower()) and (str(medicaid_bps) in fin_impact_sec)
            if has_incremental and has_training and mentions_bps:
                scores["meeting_summary_financial_impact_correct"] = 1.0

            decisions_sec = _get_section_text(summary_text, "Decisions and Follow-ups:", summary_labels) or ""
            owners_required = ["J. Gomez", "T. Brooks", "L. Chen", "R. Alvarez"]
            if all(owner in decisions_sec for owner in owners_required):
                scores["meeting_summary_decisions_followups_owners_present"] = 1.0

            assumption_check_sec = _get_section_text(summary_text, "Assumption Check:", summary_labels) or ""
            if ("HB-700" in assumption_check_sec) and (str(bill_id) in assumption_check_sec):
                scores["meeting_summary_assumption_check_mentions_mismatch"] = 1.0

    if memo_text is not None:
        subject_match = re.search(r"^Subject:\s*(.+)$", memo_text, flags=re.MULTILINE)
        if subject_match:
            subject_line = subject_match.group(0)
            if str(bill_id) in subject_line:
                scores["memo_subject_bill_id_correct"] = 1.0

        required_memo_sections = [
            "Executive Summary",
            "Financial Impact",
            "Reimbursement Note",
            "Appendix: Assumptions",
        ]
        if all(s in memo_text for s in required_memo_sections):
            scores["memo_sections_present"] = 1.0

        def _get_memo_section_text(content: str, header: str) -> Optional[str]:
            idx = content.find(header)
            if idx == -1:
                return None
            start = idx + len(header)
            end_candidates = []
            for h in required_memo_sections:
                if h == header:
                    continue
                j = content.find(h, start)
                if j != -1:
                    end_candidates.append(j)
            end = min(end_candidates) if end_candidates else len(content)
            return content[start:end].strip()

        exec_summary_text = _get_memo_section_text(memo_text, "Executive Summary")
        if exec_summary_text:
            sc = _sentence_count(exec_summary_text)
            if 2 <= sc <= 4:
                scores["memo_executive_summary_sentence_count"] = 1.0

        fin_impact_text = _get_memo_section_text(memo_text, "Financial Impact") or ""
        if _contains_amount(fin_impact_text, expected_incremental_cost) and _contains_amount(fin_impact_text, int(training_cost)):
            scores["memo_financial_impact_numbers_correct"] = 1.0

        reimbursement_text = _get_memo_section_text(memo_text, "Reimbursement Note") or ""
        reimburse_ok = ("bps" in reimbursement_text.lower()) and (str(medicaid_bps) in reimbursement_text) and ((str(effective_date) in reimbursement_text) or (str(fiscal_year) in reimbursement_text))
        if reimburse_ok:
            scores["memo_reimbursement_note_mentions_bps_and_timing"] = 1.0

        appendix_text = _get_memo_section_text(memo_text, "Appendix: Assumptions") or ""
        appendix_ok = all([
            "baseline_annual_nursing_hours" in appendix_text and str(baseline_hours) in appendix_text,
            "additional_hours_pct" in appendix_text and str(additional_hours_pct) in appendix_text,
            "avg_hourly_rn_cost_usd" in appendix_text and str(avg_hourly_cost) in appendix_text,
            "one_time_training_cost_usd" in appendix_text and str(training_cost) in appendix_text,
            "medicaid_base_rate_bps_change" in appendix_text and str(medicaid_bps) in appendix_text,
            "effective_date" in appendix_text and str(effective_date) in appendix_text,
            "fiscal_year" in appendix_text and str(fiscal_year) in appendix_text,
        ])
        if appendix_ok:
            scores["memo_appendix_assumptions_keys_values_present"] = 1.0

        if ("Notes" in memo_text) and ("Risks and Considerations" in memo_text):
            scores["memo_retains_notes_and_risks_sections"] = 1.0

    if summary_text is not None and memo_text is not None:
        summary_fin_text = _get_section_text(summary_text, "Projected Financial Impact:", summary_labels) or ""
        memo_fin_text = ""
        if "Financial Impact" in memo_text:
            start_idx = memo_text.find("Financial Impact") + len("Financial Impact")
            memo_fin_text = memo_text[start_idx:]
            next_headers = ["Reimbursement Note", "Appendix: Assumptions", "Executive Summary"]
            cut_points = [p for h in next_headers if (p := memo_fin_text.find(h)) != -1]
            if cut_points:
                memo_fin_text = memo_fin_text[:min(cut_points)]
        summary_amounts = _extract_large_integers(summary_fin_text, minimum=10000)
        memo_amounts = _extract_large_integers(memo_fin_text, minimum=10000)
        if summary_amounts and memo_amounts:
            summary_max = max(summary_amounts)
            memo_max = max(memo_amounts)
            if summary_max == memo_max == expected_incremental_cost:
                scores["cross_file_incremental_cost_consistent"] = 1.0

    if email_text is not None:
        to_match = re.search(r"^To:\s*(.+)$", email_text, flags=re.MULTILINE)
        cc_match = re.search(r"^Cc:\s*(.+)$", email_text, flags=re.MULTILINE)
        subj_match = re.search(r"^Subject:\s*(.+)$", email_text, flags=re.MULTILINE)
        to_ok = False
        cc_ok = False
        subj_ok = False
        email_body = email_text
        if to_match:
            to_line = to_match.group(1).strip()
            to_addrs = [a.strip() for a in to_line.split(",") if a.strip()]
            if set(to_addrs) == set(board_to) and len(to_addrs) == len(board_to):
                to_ok = True
        if cc_match:
            cc_line = cc_match.group(1).strip()
            cc_addrs_found = [a.strip() for a in cc_line.split(",") if a.strip()]
            if set(cc_addrs_found) == set(cc_addrs) and len(cc_addrs_found) == len(cc_addrs):
                cc_ok = True
        if subj_match:
            subject_line = subj_match.group(1)
            subj_ok = (str(bill_id) in subject_line) and ("impact" in subject_line.lower()) and (str(fiscal_year) in subject_line)
        if to_ok and cc_ok:
            scores["email_to_cc_exact"] = 1.0
        if subj_ok:
            scores["email_subject_contains_bill_and_fy_phrase"] = 1.0

        if subj_match:
            start_idx = subj_match.end()
            email_body = email_text[start_idx:].strip()
        paras = [p for p in re.split(r"\n\s*\n", email_body) if p.strip()]
        if 2 <= len(paras) <= 3:
            scores["email_body_paragraphs_count"] = 1.0

        body_ok = True
        body_ok = body_ok and ("output/Meeting_Summary.md" in email_body) and ("output/Legislation_Impact_Memo_Updated.md" in email_body)
        body_ok = body_ok and _contains_amount(email_body, expected_incremental_cost) and _contains_amount(email_body, int(training_cost))
        body_ok = body_ok and ("bps" in email_body.lower()) and (str(medicaid_bps) in email_body)
        risk_follow = ("risk" in email_body.lower()) or ("follow-ups" in email_body.lower()) or ("follow up" in email_body.lower())
        body_ok = body_ok and risk_follow
        if body_ok:
            scores["email_body_includes_key_figures_paths_bps_risks"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()