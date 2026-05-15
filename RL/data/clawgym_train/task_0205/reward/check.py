import json
import csv
import sys
import re
import os
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _extract_claim_texts_from_sitrep(path: Path) -> Optional[Dict[str, str]]:
    text = _read_text(path)
    if text is None:
        return None
    claim_texts: Dict[str, str] = {}
    for line in text.splitlines():
        # Pattern: "- [C1] Delivered 152 hygiene kits to Sector 7 on 2025-09-21."
        m = re.match(r'^\s*-\s*\[(C\d+)\]\s*(.+?)\s*$', line.strip())
        if m:
            cid = m.group(1)
            ctext = m.group(2)
            claim_texts[cid] = ctext
    # Only return dict if we found at least one claim
    return claim_texts if claim_texts else {}


def _group_totals(rows: List[Dict[str, str]], date_key: str, sector_key: str, item_key: str, qty_key: str) -> Dict[Tuple[str, int, str], int]:
    grouped: Dict[Tuple[str, int, str], int] = {}
    for r in rows:
        date = r.get(date_key, "")
        sector_s = r.get(sector_key, "")
        item = r.get(item_key, "")
        qty_s = r.get(qty_key, "")
        sector = _parse_int(sector_s)
        qty = _parse_int(qty_s)
        if date == "" or sector is None or item == "" or qty is None:
            # Malformed row; to be strict, consider it invalid by skipping aggregation for this row
            # The grader later can detect malformed CSV by comparing expected values (if any)
            continue
        key = (date, sector, item)
        grouped[key] = grouped.get(key, 0) + qty
    return grouped


def _compute_expected_results(
    claims_rows: List[Dict[str, str]],
    dispatch_rows: List[Dict[str, str]],
    receipt_rows: List[Dict[str, str]],
    sitrep_claim_texts: Dict[str, str],
) -> Optional[List[Dict[str, Any]]]:
    # Validate required columns exist
    required_claim_cols = {"claim_id", "date", "sector", "item", "claimed_quantity"}
    if not claims_rows or not all(required_claim_cols.issubset(set(r.keys())) for r in claims_rows):
        return None
    required_disp_cols = {"date", "sector", "item", "quantity"}
    if not dispatch_rows or not all(required_disp_cols.issubset(set(r.keys())) for r in dispatch_rows):
        return None
    required_rec_cols = {"date", "sector", "item", "quantity"}
    if not receipt_rows or not all(required_rec_cols.issubset(set(r.keys())) for r in receipt_rows):
        return None

    disp_group = _group_totals(dispatch_rows, "date", "sector", "item", "quantity")
    rec_group = _group_totals(receipt_rows, "date", "sector", "item", "quantity")

    expected: List[Dict[str, Any]] = []
    for r in claims_rows:
        cid = r.get("claim_id", "")
        date = r.get("date", "")
        item = r.get("item", "")
        sector = _parse_int(r.get("sector", ""))
        claimed_qty = _parse_int(r.get("claimed_quantity", ""))

        if not cid or sector is None or claimed_qty is None or not date or not item:
            return None  # malformed claims csv

        dispatch_total = disp_group.get((date, sector, item), 0)
        receipt_total = rec_group.get((date, sector, item), 0)

        # Verdict logic (order matters)
        verdict: str
        if dispatch_total == claimed_qty and receipt_total == claimed_qty:
            verdict = "confirmed"
        elif ((dispatch_total == claimed_qty) ^ (receipt_total == claimed_qty)):
            verdict = "partially_confirmed"
        elif dispatch_total != receipt_total and dispatch_total != claimed_qty and receipt_total != claimed_qty:
            verdict = "inconsistent"
        elif dispatch_total == receipt_total and dispatch_total != claimed_qty:
            verdict = "incorrect"
        else:
            # Fallback should not occur given the above exhaustive logic, but for completeness:
            verdict = "inconsistent"

        claim_text = sitrep_claim_texts.get(cid, "")

        expected.append({
            "claim_id": cid,
            "claim_text": claim_text,
            "date": date,
            "sector": sector,
            "item": item,
            "claimed_quantity": claimed_qty,
            "dispatch_total": dispatch_total,
            "receipt_total": receipt_total,
            "verdict": verdict,
        })
    return expected


def _list_to_id_map(items: List[Dict[str, Any]], id_key: str = "claim_id") -> Dict[str, Dict[str, Any]]:
    res: Dict[str, Dict[str, Any]] = {}
    for it in items:
        cid = it.get(id_key)
        if isinstance(cid, str) and cid not in res:
            res[cid] = it
    return res


def _counts_by_verdict(results: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"confirmed": 0, "partially_confirmed": 0, "inconsistent": 0, "incorrect": 0}
    for r in results:
        v = r.get("verdict")
        if v in counts:
            counts[v] += 1
    return counts


def _first_paragraph(text: str) -> str:
    # Paragraph: consecutive non-empty lines from the start until a blank line
    lines = text.splitlines()
    para_lines: List[str] = []
    started = False
    for line in lines:
        if not started and line.strip() == "":
            continue
        if line.strip() == "":
            break
        started = True
        para_lines.append(line)
    return " ".join(para_lines).strip()


def _sentence_count(text: str) -> int:
    # Count sentences by ., !, ? terminal markers
    # Use a simple heuristic: split on [.!?] and count non-empty parts
    parts = re.split(r'[.!?]+', text)
    count = sum(1 for p in parts if p.strip())
    return count


def _extract_claim_blocks(text: str, claim_ids: List[str]) -> Dict[str, str]:
    # Create a regex that matches any claim id as a whole word
    ids_pattern = r'\b(' + '|'.join(re.escape(cid) for cid in claim_ids) + r')\b'
    # Split text into lines and gather blocks starting at lines containing a claim id
    lines = text.splitlines()
    id_positions = []
    for idx, line in enumerate(lines):
        if re.search(ids_pattern, line):
            # Determine which claim id is here; pick the first match
            m = re.search(ids_pattern, line)
            if m:
                id_positions.append((idx, m.group(1)))

    blocks: Dict[str, str] = {}
    for i, (start_idx, cid) in enumerate(id_positions):
        end_idx = len(lines)
        if i + 1 < len(id_positions):
            end_idx = id_positions[i + 1][0]
        block_lines = lines[start_idx:end_idx]
        block_text = "\n".join(block_lines).strip()
        # In case multiple occurrences, keep the first; else combine
        if cid not in blocks:
            blocks[cid] = block_text
        else:
            blocks[cid] += "\n" + block_text
    return blocks


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Initialize scores
    scores: Dict[str, float] = {
        "verification_json_exists": 0.0,
        "verification_json_valid": 0.0,
        "verification_json_values_correct": 0.0,
        "run_script_exists": 0.0,
        "run_script_references_inputs_and_output": 0.0,
        "summary_file_exists": 0.0,
        "summary_paragraph_3_to_6_sentences": 0.0,
        "summary_counts_by_verdict_correct": 0.0,
        "summary_per_claim_listing_complete": 0.0,
        "email_file_exists": 0.0,
        "email_covers_all_claims": 0.0,
        "email_explains_partial_source": 0.0,
        "email_requests_corrections": 0.0,
        "email_corrected_figures_stated": 0.0,
    }

    # Load inputs to compute expected results
    claims_csv_path = workspace / "input" / "student_claims.csv"
    sitrep_md_path = workspace / "input" / "student_sitrep.md"
    dispatch_csv_path = workspace / "input" / "official_dispatches.csv"
    receipts_csv_path = workspace / "input" / "field_receipts.csv"

    claims_rows = _load_csv(claims_csv_path) or []
    dispatch_rows = _load_csv(dispatch_csv_path) or []
    receipt_rows = _load_csv(receipts_csv_path) or []
    sitrep_claim_texts = _extract_claim_texts_from_sitrep(sitrep_md_path) or {}

    expected_results = _compute_expected_results(claims_rows, dispatch_rows, receipt_rows, sitrep_claim_texts)

    # Expected counts for use in summary/email checks if expected_results available
    expected_counts = _counts_by_verdict(expected_results) if expected_results else None

    # 1) Check outputs/verification_results.json
    results_json_path = workspace / "outputs" / "verification_results.json"
    results_json = _load_json(results_json_path)
    if results_json is not None:
        scores["verification_json_exists"] = 1.0
        # Validate structure
        valid_structure = True
        if not isinstance(results_json, list):
            valid_structure = False
        else:
            required_fields = {
                "claim_id": str,
                "claim_text": str,
                "date": str,
                "sector": int,
                "item": str,
                "claimed_quantity": int,
                "dispatch_total": int,
                "receipt_total": int,
                "verdict": str,
            }
            for obj in results_json:
                if not isinstance(obj, dict):
                    valid_structure = False
                    break
                for k, t in required_fields.items():
                    if k not in obj:
                        valid_structure = False
                        break
                    v = obj[k]
                    if t is int and not isinstance(v, int):
                        valid_structure = False
                        break
                    if t is str and not isinstance(v, str):
                        valid_structure = False
                        break
                if not valid_structure:
                    break
        if valid_structure:
            scores["verification_json_valid"] = 1.0

        # Compare values against expected if we could compute expected
        if valid_structure and expected_results is not None:
            json_map = _list_to_id_map(results_json, "claim_id")
            exp_map = _list_to_id_map(expected_results, "claim_id")
            values_match = True
            # The array must have exactly one object per claim (no missing, no extra)
            if len(json_map) != len(exp_map):
                values_match = False
            else:
                for cid, exp in exp_map.items():
                    got = json_map.get(cid)
                    if not got:
                        values_match = False
                        break
                    # Strict comparison for all required fields
                    for k in ["claim_id", "claim_text", "date", "sector", "item", "claimed_quantity", "dispatch_total", "receipt_total", "verdict"]:
                        if got.get(k) != exp.get(k):
                            values_match = False
                            break
                    if not values_match:
                        break
            if values_match:
                scores["verification_json_values_correct"] = 1.0

    # 2) Check scripts/run_verification.sh
    run_script_path = workspace / "scripts" / "run_verification.sh"
    run_script_text = _read_text(run_script_path)
    if run_script_text is not None:
        scores["run_script_exists"] = 1.0
        # Check it references inputs and output paths to indicate it runs deterministically on provided data
        references_ok = False
        try:
            has_outputs_ref = "outputs/verification_results.json" in run_script_text
            has_input_ref = "input/" in run_script_text or "input/student_claims.csv" in run_script_text
            references_ok = has_outputs_ref and has_input_ref
        except Exception:
            references_ok = False
        if references_ok:
            scores["run_script_references_inputs_and_output"] = 1.0

    # 3) Check reports/verification_summary.md
    summary_path = workspace / "reports" / "verification_summary.md"
    summary_text = _read_text(summary_path)
    if summary_text is not None:
        scores["summary_file_exists"] = 1.0
        # Check short paragraph 3–6 sentences
        first_para = _first_paragraph(summary_text)
        sent_count = _sentence_count(first_para) if first_para else 0
        if 3 <= sent_count <= 6:
            scores["summary_paragraph_3_to_6_sentences"] = 1.0

        # Counts by verdict
        if expected_counts is not None:
            # Expect exact literal patterns "confirmed: X", etc.
            counts_ok = True
            for verdict_key in ["confirmed", "partially_confirmed", "inconsistent", "incorrect"]:
                expected_num = expected_counts.get(verdict_key, 0)
                pattern = f"{verdict_key}: {expected_num}"
                if pattern not in summary_text:
                    counts_ok = False
                    break
            if counts_ok:
                scores["summary_counts_by_verdict_correct"] = 1.0

        # Per-claim listing completeness: check each claim has id, exact claim_text, claimed_quantity, dispatch_total, receipt_total, verdict
        if expected_results is not None:
            claim_ids = [r["claim_id"] for r in expected_results]
            blocks = _extract_claim_blocks(summary_text, claim_ids)
            per_claim_ok = True
            for exp in expected_results:
                cid = exp["claim_id"]
                block = blocks.get(cid, "")
                if not block:
                    per_claim_ok = False
                    break
                # Must include claim_text verbatim
                if exp["claim_text"] and exp["claim_text"] not in block:
                    per_claim_ok = False
                    break
                # Must include numeric values and verdict
                nums_ok = all(str(exp[k]) in block for k in ["claimed_quantity", "dispatch_total", "receipt_total"])
                verdict_ok = exp["verdict"] in block
                if not (nums_ok and verdict_ok):
                    per_claim_ok = False
                    break
            if per_claim_ok:
                scores["summary_per_claim_listing_complete"] = 1.0

    # 4) Check reports/email_to_student.txt
    email_path = workspace / "reports" / "email_to_student.txt"
    email_text = _read_text(email_path)
    if email_text is not None:
        scores["email_file_exists"] = 1.0
        if expected_results is not None:
            claim_ids = [r["claim_id"] for r in expected_results]
            blocks = _extract_claim_blocks(email_text, claim_ids)
            # Covers all claims: each claim id should appear somewhere
            all_present = all(cid in blocks and blocks[cid] for cid in claim_ids)
            if all_present:
                scores["email_covers_all_claims"] = 1.0

            # Explain partial source for partially_confirmed (which source matched)
            # Determine which claims are partially confirmed and which source matched
            partial_explained_ok = True
            for exp in expected_results:
                if exp["verdict"] == "partially_confirmed":
                    cid = exp["claim_id"]
                    blk = blocks.get(cid, "")
                    if not blk:
                        partial_explained_ok = False
                        break
                    # Check block mentions both sources and their figures to be explicit
                    # For our inputs, expect dispatch matched claimed (e.g., 400) and receipt was different (e.g., 390)
                    disp_num = exp["dispatch_total"]
                    rec_num = exp["receipt_total"]
                    # Must mention dispatch and its number, and receipt and its number
                    has_dispatch = re.search(r'\bdispatch(es|)?\b', blk, flags=re.IGNORECASE) is not None and str(disp_num) in blk
                    has_receipt = re.search(r'\breceipt(s|)?\b', blk, flags=re.IGNORECASE) is not None and str(rec_num) in blk
                    if not (has_dispatch and has_receipt):
                        partial_explained_ok = False
                        break
            if partial_explained_ok:
                scores["email_explains_partial_source"] = 1.0

            # Requests corrections where needed
            # Look for polite request keywords
            request_corrections = bool(re.search(r'\b(please|kindly)\b', email_text, flags=re.IGNORECASE)) and bool(
                re.search(r'\b(correct|update|revise|amend)\b', email_text, flags=re.IGNORECASE)
            )
            if request_corrections:
                scores["email_requests_corrections"] = 1.0

            # Corrected figures stated for incorrect claims (present corrected totals)
            corrected_ok = True
            for exp in expected_results:
                if exp["verdict"] == "incorrect":
                    cid = exp["claim_id"]
                    blk = blocks.get(cid, "")
                    if not blk:
                        corrected_ok = False
                        break
                    # The corrected figure is the common total (dispatch_total == receipt_total)
                    corrected = exp["dispatch_total"]
                    if str(corrected) not in blk:
                        corrected_ok = False
                        break
            if corrected_ok:
                scores["email_corrected_figures_stated"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()