import json
import csv
import re
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    items: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, str]]:
    text = _read_text(path)
    if text is None:
        return None
    result: Dict[str, str] = {}
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.*)$", line)
            if not m:
                continue
            key = m.group(1)
            val = m.group(2).strip()
            if " #" in val:
                val = val.split(" #", 1)[0].rstrip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            result[key] = val
        return result
    except Exception:
        return None


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _extract_meta_strong_label(html: str, label: str) -> Optional[str]:
    pattern = re.compile(rf"<strong>\s*{re.escape(label)}\s*</strong>\s*:\s*([^<\n]+)", re.IGNORECASE)
    m = pattern.search(html)
    if m:
        return _strip_tags(m.group(1)).strip()
    return None


def _extract_table_value(html: str, label: str) -> Optional[str]:
    pattern = re.compile(
        rf"<tr>\s*<td>\s*{re.escape(label)}\s*</td>\s*<td>\s*(.*?)\s*</td>\s*</tr>",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(html)
    if m:
        return _strip_tags(m.group(1)).strip()
    return None


def _parse_title_commitment_html(html: str) -> Optional[Dict[str, Any]]:
    try:
        data = {}
        data["commitment_no"] = _extract_meta_strong_label(html, "Commitment No.")
        data["effective_date"] = _extract_meta_strong_label(html, "Effective Date")
        data["property_address"] = _extract_meta_strong_label(html, "Property Address")
        data["apn"] = _extract_meta_strong_label(html, "APN")
        data["proposed_insured"] = _extract_table_value(html, "Proposed Insured")
        data["title_vested_in"] = _extract_table_value(html, "Title Vested In")
        data["legal_description"] = _extract_table_value(html, "Legal Description")
        return data
    except Exception:
        return None


def _normalize_name(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    s = re.sub(r"[^A-Za-z0-9]+", "", name).lower()
    return s


def _is_fee_transfer(instrument: str) -> bool:
    inst = (instrument or "").lower()
    if "deed of trust" in inst:
        return False
    return "deed" in inst


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "chain_csv_exists_and_header": 0.0,
        "chain_csv_row_count": 0.0,
        "chain_csv_contents_match_inputs": 0.0,
        "discrepancy_json_parses_and_keys": 0.0,
        "owner_name_values_correct_in_json": 0.0,
        "owner_name_match_flag_correct": 0.0,
        "apn_match_flag_correct": 0.0,
        "legal_description_present_flag_correct": 0.0,
        "chain_gap_llp_mismatch_present": 0.0,
        "chain_gaps_count_correct": 0.0,
        "email_subject_format_correct": 0.0,
        "email_repro_command_included": 0.0,
        "email_addresses_client_by_name": 0.0,
        "email_references_both_reports": 0.0,
        "email_chain_narrative_keywords": 0.0,
    }

    title_path = workspace / "input" / "title_commitment.html"
    deeds_path = workspace / "input" / "deed_abstracts.jsonl"
    tax_path = workspace / "input" / "county_tax_roll.csv"
    case_path = workspace / "input" / "case.yaml"

    chain_csv_path = workspace / "output" / "chain_of_title.csv"
    discrepancy_json_path = workspace / "output" / "discrepancy_report.json"
    email_txt_path = workspace / "output" / "draft_email_to_client.txt"

    title_html = _read_text(title_path)
    deeds = _load_jsonl(deeds_path)
    tax_rows = _load_csv_dicts(tax_path)
    case_yaml = _parse_simple_yaml(case_path)

    expected_title = _parse_title_commitment_html(title_html) if title_html else None

    expected_deeds_sorted: Optional[List[Dict[str, Any]]] = None
    if deeds is not None:
        try:
            expected_deeds_sorted = sorted(deeds, key=lambda d: d.get("record_date", ""))
        except Exception:
            expected_deeds_sorted = None

    expected_latest_grantee = None
    if expected_deeds_sorted:
        last_rec = expected_deeds_sorted[-1]
        expected_latest_grantee = last_rec.get("grantee")

    expected_tax_owner = None
    expected_tax_apn = None
    case_parcel = case_yaml.get("parcel_number") if case_yaml else None
    title_apn = expected_title.get("apn") if expected_title else None
    target_parcel = case_parcel or title_apn
    if tax_rows is not None and target_parcel:
        try:
            for r in tax_rows:
                if (r.get("parcel_number") or "").strip() == target_parcel:
                    expected_tax_owner = r.get("owner_name")
                    expected_tax_apn = r.get("parcel_number")
                    break
        except Exception:
            expected_tax_owner = None
            expected_tax_apn = None

    expected_apn_match: Optional[bool] = None
    if title_apn and case_parcel and expected_tax_apn:
        expected_apn_match = (title_apn == case_parcel == expected_tax_apn)

    expected_legal_desc_present: Optional[bool] = None
    if expected_title is not None:
        ld = expected_title.get("legal_description")
        expected_legal_desc_present = bool(ld and ld.strip())

    expected_owner_match: Optional[bool] = None
    title_owner = expected_title.get("title_vested_in") if expected_title else None
    if title_owner and expected_latest_grantee and expected_tax_owner:
        n_title = _normalize_name(title_owner)
        n_deed = _normalize_name(expected_latest_grantee)
        n_tax = _normalize_name(expected_tax_owner)
        expected_owner_match = (n_title == n_deed == n_tax)

    expected_chain_gaps: Optional[List[Dict[str, Any]]] = None
    if expected_deeds_sorted is not None:
        expected_chain_gaps = []
        last_fee_grantee_norm: Optional[str] = None
        last_fee_grantee_raw: Optional[str] = None
        for idx, rec in enumerate(expected_deeds_sorted):
            instrument = rec.get("instrument") or ""
            if _is_fee_transfer(instrument):
                current_grantor = rec.get("grantor") or ""
                current_grantee = rec.get("grantee") or ""
                current_grantor_norm = _normalize_name(current_grantor) or ""
                if last_fee_grantee_norm is not None and current_grantor_norm != last_fee_grantee_norm:
                    expected_chain_gaps.append({
                        "index": idx,
                        "prior_grantee": last_fee_grantee_raw,
                        "current_grantor": current_grantor,
                        "note": "grantor does not match prior grantee (fee transfer continuity break)"
                    })
                last_fee_grantee_norm = _normalize_name(current_grantee) or ""
                last_fee_grantee_raw = current_grantee

    chain_rows: Optional[List[Dict[str, str]]] = None
    if chain_csv_path.exists():
        try:
            with chain_csv_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames or []
                expected_header = ["record_date", "instrument", "grantor", "grantee", "recording_reference", "legal_snippet"]
                if header == expected_header:
                    scores["chain_csv_exists_and_header"] = 1.0
                chain_rows = list(reader)
        except Exception:
            chain_rows = None
    else:
        chain_rows = None

    if chain_rows is not None and expected_deeds_sorted is not None:
        if len(chain_rows) == len(expected_deeds_sorted) == 4:
            scores["chain_csv_row_count"] = 1.0

    if chain_rows is not None and expected_deeds_sorted is not None and len(chain_rows) == len(expected_deeds_sorted):
        all_match = True
        for row, exp in zip(chain_rows, expected_deeds_sorted):
            if (
                (row.get("record_date") == exp.get("record_date")) and
                (row.get("instrument") == exp.get("instrument")) and
                (row.get("grantor") == exp.get("grantor")) and
                (row.get("grantee") == exp.get("grantee")) and
                (row.get("recording_reference") == exp.get("recording_reference")) and
                (row.get("legal_snippet") == exp.get("legal_description_snippet"))
            ):
                continue
            else:
                all_match = False
                break
        if all_match:
            scores["chain_csv_contents_match_inputs"] = 1.0

    discrepancy = _load_json(discrepancy_json_path) if discrepancy_json_path.exists() else None
    if discrepancy is not None and isinstance(discrepancy, dict):
        has_ok_keys = (
            "owner_name_comparison" in discrepancy and
            isinstance(discrepancy.get("owner_name_comparison"), dict) and
            "apn_match" in discrepancy and
            "legal_description_present" in discrepancy and
            "chain_gaps" in discrepancy and
            isinstance(discrepancy.get("chain_gaps"), list)
        )
        if has_ok_keys:
            scores["discrepancy_json_parses_and_keys"] = 1.0

        onc = discrepancy.get("owner_name_comparison") if isinstance(discrepancy.get("owner_name_comparison"), dict) else None
        if onc and expected_title is not None and expected_deeds_sorted is not None and expected_tax_owner is not None:
            raw_ok = (
                onc.get("title_commitment") == title_owner and
                onc.get("deed_latest_grantee") == expected_latest_grantee and
                onc.get("tax_roll") == expected_tax_owner
            )
            if raw_ok:
                scores["owner_name_values_correct_in_json"] = 1.0

            match_flag = onc.get("match")
            if isinstance(match_flag, bool) and expected_owner_match is not None:
                if match_flag == expected_owner_match:
                    scores["owner_name_match_flag_correct"] = 1.0

        apn_match_flag = discrepancy.get("apn_match")
        if isinstance(apn_match_flag, bool) and expected_apn_match is not None:
            if apn_match_flag == expected_apn_match:
                scores["apn_match_flag_correct"] = 1.0

        ldp_flag = discrepancy.get("legal_description_present")
        if isinstance(ldp_flag, bool) and expected_legal_desc_present is not None:
            if ldp_flag == expected_legal_desc_present:
                scores["legal_description_present_flag_correct"] = 1.0

        reported_gaps = discrepancy.get("chain_gaps") if isinstance(discrepancy.get("chain_gaps"), list) else []
        expected_gaps_list = expected_chain_gaps if expected_chain_gaps is not None else []
        exp_gap_present = False
        if expected_gaps_list:
            for g in expected_gaps_list:
                pg = g.get("prior_grantee") or ""
                cg = g.get("current_grantor") or ""
                if _normalize_name(pg) == "bayviewholdingslp" and _normalize_name(cg) == "bayviewholdingsllp":
                    exp_gap_present = True
                    break
        rep_gap_present = False
        for g in reported_gaps:
            pg = (g.get("prior_grantee") or "")
            cg = (g.get("current_grantor") or "")
            if _normalize_name(pg) == "bayviewholdingslp" and _normalize_name(cg) == "bayviewholdingsllp":
                rep_gap_present = True
                break
        if exp_gap_present and rep_gap_present:
            scores["chain_gap_llp_mismatch_present"] = 1.0
        if expected_chain_gaps is not None and isinstance(reported_gaps, list):
            if len(reported_gaps) == len(expected_chain_gaps):
                scores["chain_gaps_count_correct"] = 1.0

    email_text = _read_text(email_txt_path) if email_txt_path.exists() else None
    if email_text:
        lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        if case_yaml is not None:
            expected_subject_prefix = f"Title Review - {case_yaml.get('matter_id')}: {case_yaml.get('property_address')}"
            if lines and isinstance(lines[0], str) and lines[0].startswith(expected_subject_prefix):
                scores["email_subject_format_correct"] = 1.0
        if len(lines) >= 2:
            second = lines[1]
            tokens_required = [
                "tools/title_audit.py",
                "input/title_commitment.html",
                "input/deed_abstracts.jsonl",
                "input/county_tax_roll.csv",
                "input/case.yaml",
                "output",
            ]
            if all(tok in second for tok in tokens_required):
                scores["email_repro_command_included"] = 1.0
        if case_yaml is not None:
            cname = case_yaml.get("client_name")
            if cname:
                txt_lower = email_text.lower()
                has_dear = "dear" in txt_lower
                has_name = cname in email_text
                if has_dear and has_name:
                    scores["email_addresses_client_by_name"] = 1.0
        if "output/chain_of_title.csv" in email_text and "output/discrepancy_report.json" in email_text:
            scores["email_references_both_reports"] = 1.0
        keywords = ["Grant Deed", "Quitclaim", "Deed of Trust", "chain", "timeline"]
        if any(kw.lower() in email_text.lower() for kw in keywords):
            scores["email_chain_narrative_keywords"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()