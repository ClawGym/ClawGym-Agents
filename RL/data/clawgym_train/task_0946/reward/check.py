import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        records: List[Dict[str, Any]] = []
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        return None
                    records.append(obj)
                except Exception:
                    return None
        return records
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows: List[Dict[str, str]] = []
            for row in reader:
                # Ensure all headers exist
                if row is None:
                    return None
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _normalize_year(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        try:
            return int(value)
        except Exception:
            return None
    if isinstance(value, str):
        v = value.strip()
        if v == "" or v.lower() == "null":
            return None
        try:
            return int(v)
        except Exception:
            return None
    return None


def _compute_expected(
    claims: List[Dict[str, Any]],
    facts: List[Dict[str, Any]],
    corrections: List[Dict[str, str]],
) -> Dict[str, Dict[str, Any]]:
    # Build indices for efficient matching
    # facts keyed by (subject, claim_type, title)
    facts_by_sct: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    facts_by_title_year: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for f in facts:
        subj = f.get("subject")
        ctype = f.get("claim_type")
        title = f.get("title")
        year = _normalize_year(f.get("year"))
        if not (isinstance(subj, str) and isinstance(ctype, str) and isinstance(title, str)) or year is None:
            # facts are expected to be structured; skip malformed facts entirely
            continue
        key_sct = (subj, ctype, title)
        facts_by_sct.setdefault(key_sct, []).append(f)
        key_ty = (title, year)
        facts_by_title_year.setdefault(key_ty, []).append(f)

    # Prepare corrections index
    corrections_idx: List[Dict[str, Any]] = []
    for row in corrections:
        corrections_idx.append({
            "subject": row.get("subject", "").strip(),
            "claim_type": row.get("claim_type", "").strip(),
            "wrong_title": row.get("wrong_title", "").strip(),
            "wrong_year": _normalize_year(row.get("wrong_year", "")),
            "correction_note": row.get("correction_note", "").strip(),
            "raw": row,
        })

    expected: Dict[str, Dict[str, Any]] = {}

    for claim in claims:
        cid = str(claim.get("id"))
        subj = claim.get("subject")
        ctype = claim.get("claim_type")
        title = claim.get("title")
        cyear = _normalize_year(claim.get("year"))
        # Default expected
        exp_status = "not_found"
        exp_matched: List[str] = []
        exp_conflicting: List[str] = []
        exp_correction_note = ""

        if not (isinstance(subj, str) and isinstance(ctype, str) and isinstance(title, str)):
            # malformed claim fields => leave as not_found
            expected[cid] = {
                "status": exp_status,
                "matched": exp_matched,
                "conflicting": exp_conflicting,
                "correction_note": exp_correction_note,
            }
            continue

        # Matching logic
        # Exact/partial matches by (subject, claim_type, title)
        matches_no_year = facts_by_sct.get((subj, ctype, title), [])
        matches_with_year = [f for f in matches_no_year if _normalize_year(f.get("year")) == cyear] if cyear is not None else []

        # Ambiguity logic: if claim year is null and there are >=2 matches with different years
        different_years = set(_normalize_year(f.get("year")) for f in matches_no_year if _normalize_year(f.get("year")) is not None)

        # Verified rule
        # If year is provided: require matching fact with correct year
        # If year is null: verified only when there is exactly one match (unambiguous)
        if cyear is not None:
            if len(matches_with_year) >= 1:
                exp_status = "verified"
                exp_matched = [f.get("id") for f in matches_with_year if isinstance(f.get("id"), str)]
        else:
            if len(matches_no_year) == 1:
                exp_status = "verified"
                exp_matched = [matches_no_year[0].get("id")] if isinstance(matches_no_year[0].get("id"), str) else []

        # Ambiguous rule
        if exp_status != "verified" and cyear is None and len(matches_no_year) >= 2 and len(different_years) >= 2:
            exp_status = "ambiguous"
            exp_matched = [f.get("id") for f in matches_no_year if isinstance(f.get("id"), str)]

        # Disputed rule
        if exp_status not in ("verified", "ambiguous"):
            # Correction match (a)
            corr_match = None
            for corr in corrections_idx:
                if corr["subject"] == subj and corr["claim_type"] == ctype and corr["wrong_title"] == title:
                    if cyear is None:
                        corr_match = corr
                        break
                    else:
                        if corr["wrong_year"] == cyear:
                            corr_match = corr
                            break
            # Conflicting facts (b): same title and year but different subject
            conflicting: List[str] = []
            if cyear is not None:
                for f in facts_by_title_year.get((title, cyear), []):
                    fsubj = f.get("subject")
                    if isinstance(fsubj, str) and fsubj != subj:
                        fid = f.get("id")
                        if isinstance(fid, str):
                            conflicting.append(fid)
            if corr_match is not None or len(conflicting) > 0:
                exp_status = "disputed"
                exp_conflicting = sorted(set(conflicting))
                if corr_match is not None:
                    exp_correction_note = corr_match.get("correction_note", "")

        expected[cid] = {
            "status": exp_status,
            "matched": sorted(exp_matched),
            "conflicting": sorted(set(exp_conflicting)),
            "correction_note": exp_correction_note,
        }

    return expected


def _parse_counts_from_status_md(text: str) -> Tuple[Optional[int], Dict[str, Optional[int]]]:
    # Extract total and per-status counts
    lower = text.lower()
    status_words = ["verified", "ambiguous", "disputed", "not_found"]
    counts: Dict[str, Optional[int]] = {k: None for k in status_words}
    for status in status_words:
        # find first number after the status word
        m = re.search(rf"\b{re.escape(status)}\b[^0-9]*?(\d+)", lower)
        if m:
            try:
                counts[status] = int(m.group(1))
            except Exception:
                counts[status] = None
        else:
            counts[status] = None

    total = None
    # Try to find a total or processed count
    m_total = re.search(r"\btotal\b[^0-9]*?(\d+)", lower)
    m_processed = re.search(r"\bprocessed\b[^0-9]*?(\d+)", lower)
    if m_total:
        try:
            total = int(m_total.group(1))
        except Exception:
            total = None
    elif m_processed:
        try:
            total = int(m_processed.group(1))
        except Exception:
            total = None
    else:
        # Try "claims: N" as a fallback if labeled
        m_claims = re.search(r"\bclaims\b[^0-9]*?(\d+)", lower)
        if m_claims:
            try:
                total = int(m_claims.group(1))
            except Exception:
                total = None
    return total, counts


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "verification_report_exists_and_parseable": 0.0,
        "verification_report_claims_covered": 0.0,
        "verification_statuses_correct": 0.0,
        "verification_matched_fact_ids_correct": 0.0,
        "verification_conflicting_fact_ids_correct": 0.0,
        "verification_correction_notes_present_when_applicable": 0.0,
        "verification_rationales_nonempty": 0.0,
        "status_update_exists": 0.0,
        "status_update_command_included": 0.0,
        "status_update_counts_by_status_correct": 0.0,
        "status_update_total_correct": 0.0,
        "status_update_summary_present": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_opening_line_present": 0.0,
        "meeting_notes_disputed_entries_complete": 0.0,
        "meeting_notes_not_found_entries_complete": 0.0,
    }

    # Load inputs
    claims_path = workspace / "input" / "claims.jsonl"
    facts_path = workspace / "input" / "facts.json"
    corrections_path = workspace / "input" / "corrections.csv"

    claims = _load_jsonl(claims_path)
    facts = _load_json(facts_path)
    corrections = _load_csv_dicts(corrections_path)

    if not (isinstance(claims, list) and isinstance(facts, list) and isinstance(corrections, list)):
        # Without valid inputs, we cannot compute expected; all checks dependent on expectations will be 0.0
        expected = {}
    else:
        expected = _compute_expected(claims, facts, corrections)

    # Load outputs
    report_path = workspace / "verification" / "verification_report.json"
    report = _load_json(report_path)

    if isinstance(report, list):
        scores["verification_report_exists_and_parseable"] = 1.0
    else:
        report = None

    # Verify report coverage and content
    if report is not None and isinstance(claims, list):
        # Map report by claim_id
        report_by_id: Dict[str, Dict[str, Any]] = {}
        all_have_fields = True
        for item in report:
            if not isinstance(item, dict):
                all_have_fields = False
                break
            cid = item.get("claim_id")
            if not isinstance(cid, str):
                all_have_fields = False
                break
            report_by_id[cid] = item
        # Coverage
        claim_ids = [str(c.get("id")) for c in claims if "id" in c]
        if set(report_by_id.keys()) == set(claim_ids) and all_have_fields:
            scores["verification_report_claims_covered"] = 1.0

        # Status correctness and matched/conflicting/correction_note
        statuses_ok = True
        matched_ok = True
        conflicting_ok = True
        corrections_ok = True
        rationales_ok = True

        for cid in claim_ids:
            exp = expected.get(cid)
            rep = report_by_id.get(cid)
            if exp is None or rep is None:
                statuses_ok = False
                matched_ok = False
                conflicting_ok = False
                corrections_ok = False
                rationales_ok = False
                continue

            rep_status = rep.get("status")
            if rep_status != exp["status"]:
                statuses_ok = False

            # matched_fact_ids
            rep_matched = rep.get("matched_fact_ids")
            if not isinstance(rep_matched, list):
                matched_ok = False
            else:
                rep_matched_set = set([x for x in rep_matched if isinstance(x, str)])
                exp_matched_set = set(exp["matched"])
                # For verified/ambiguous expect exact match; for others expect empty
                if exp["status"] in ("verified", "ambiguous"):
                    if rep_matched_set != exp_matched_set:
                        matched_ok = False
                else:
                    if len(rep_matched_set) != 0:
                        matched_ok = False

            # conflicting_fact_ids
            rep_conflicting = rep.get("conflicting_fact_ids")
            if not isinstance(rep_conflicting, list):
                conflicting_ok = False
            else:
                rep_conflicting_set = set([x for x in rep_conflicting if isinstance(x, str)])
                exp_conflicting_set = set(exp["conflicting"]) if exp["status"] == "disputed" else set()
                if rep_conflicting_set != exp_conflicting_set:
                    conflicting_ok = False

            # correction_note
            rep_corr_note = rep.get("correction_note")
            if not isinstance(rep_corr_note, str):
                corrections_ok = False
            else:
                expected_note = exp["correction_note"] if exp["status"] == "disputed" and exp["correction_note"] else ""
                if rep_corr_note != expected_note:
                    corrections_ok = False

            # rationale non-empty and mentions status
            rationale = rep.get("rationale")
            if not isinstance(rationale, str) or rationale.strip() == "":
                rationales_ok = False
            else:
                # Require rationale to include the status keyword to indicate explanation
                if exp["status"] not in rationale.lower():
                    rationales_ok = False

        if statuses_ok:
            scores["verification_statuses_correct"] = 1.0
        if matched_ok:
            scores["verification_matched_fact_ids_correct"] = 1.0
        if conflicting_ok:
            scores["verification_conflicting_fact_ids_correct"] = 1.0
        if corrections_ok:
            scores["verification_correction_notes_present_when_applicable"] = 1.0
        if rationales_ok:
            scores["verification_rationales_nonempty"] = 1.0

    # Status update checks
    status_md_path = workspace / "docs" / "status_update.md"
    status_md_text = _safe_read_text(status_md_path)
    if isinstance(status_md_text, str):
        scores["status_update_exists"] = 1.0
        # Command included: ensure the exact output path is mentioned
        if "verification/verification_report.json" in status_md_text:
            scores["status_update_command_included"] = 1.0

        # Counts by status and total
        if isinstance(claims, list) and isinstance(facts, list) and isinstance(corrections, list):
            expected_total = len(claims)
            # Compute expected status counts
            expected_counts = {"verified": 0, "ambiguous": 0, "disputed": 0, "not_found": 0}
            for cid, exp in expected.items():
                status = exp["status"]
                if status in expected_counts:
                    expected_counts[status] += 1

            total_found, counts_found = _parse_counts_from_status_md(status_md_text)
            counts_ok = True
            for k in ["verified", "ambiguous", "disputed", "not_found"]:
                if counts_found.get(k) is None or counts_found.get(k) != expected_counts[k]:
                    counts_ok = False
            if counts_ok:
                scores["status_update_counts_by_status_correct"] = 1.0

            total_ok = (total_found == expected_total)
            if total_ok:
                scores["status_update_total_correct"] = 1.0

        # Summary present: any non-empty line that is not command line and not a counts line
        lines = [ln.strip() for ln in status_md_text.splitlines()]
        summary_present = False
        for ln in lines:
            if not ln:
                continue
            lower_ln = ln.lower()
            if "verification/verification_report.json" in ln:
                continue
            if any(word in lower_ln for word in ["verified", "ambiguous", "disputed", "not_found", "total", "processed"]):
                # likely counts lines
                continue
            if ln.startswith("#"):
                continue
            # Consider this a summary line
            summary_present = True
            break
        if summary_present:
            scores["status_update_summary_present"] = 1.0

    # Meeting notes checks
    meeting_md_path = workspace / "docs" / "meeting_notes.md"
    meeting_md_text = _safe_read_text(meeting_md_path)
    if isinstance(meeting_md_text, str):
        scores["meeting_notes_exists"] = 1.0
        # Opening line: first non-empty non-bullet, non-heading line, 1 sentence
        opening_line_ok = False
        for ln in meeting_md_text.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("#") or s.startswith("-") or s.startswith("*"):
                continue
            # One-sentence heuristic: ends with ., !, or ? and contains only one such end
            enders = [c for c in s if c in ".!?"]
            if len(enders) >= 1:
                # Count sentence enders
                count_enders = sum(s.count(ch) for ch in ".!?")
                if count_enders == 1:
                    opening_line_ok = True
            else:
                # allow line without punctuation but short length as one sentence
                if 3 <= len(s.split()) <= 25:
                    opening_line_ok = True
            break
        if opening_line_ok:
            scores["meeting_notes_opening_line_present"] = 1.0

        # Entries for disputed and not_found
        disputed_ok = False
        not_found_ok = False
        if isinstance(claims, list) and isinstance(facts, list) and isinstance(corrections, list):
            # Compute expected again if not present
            exp_map = expected
            # build line list normalized
            lines = meeting_md_text.splitlines()
            # For each claim with disputed or not_found, verify a bullet line contains appropriate info
            all_disputed_ok = True
            all_not_found_ok = True
            for cid, exp in exp_map.items():
                status = exp["status"]
                if status in ("disputed", "not_found"):
                    # Find bullet lines containing cid
                    relevant_lines = [ln for ln in lines if ln.strip().startswith(("-", "*")) and cid in ln]
                    if not relevant_lines:
                        if status == "disputed":
                            all_disputed_ok = False
                        else:
                            all_not_found_ok = False
                        continue
                    # Check content
                    line_ok = False
                    for bl in relevant_lines:
                        bl_lower = bl.lower()
                        has_owner = "fact-check" in bl_lower
                        has_due = "before recording" in bl_lower
                        if status == "disputed":
                            # If correction note exists: require "Replace with:" and the exact note
                            corr_note = exp.get("correction_note", "")
                            if corr_note:
                                line_ok = ("replace with:" in bl_lower) and (corr_note in bl) and has_owner and has_due
                            else:
                                # If no correction note, allow "Research needed"
                                line_ok = ("research needed" in bl_lower) and has_owner and has_due
                        else:  # not_found
                            line_ok = ("research needed" in bl_lower) and has_owner and has_due
                        if line_ok:
                            break
                    if not line_ok:
                        if status == "disputed":
                            all_disputed_ok = False
                        else:
                            all_not_found_ok = False
            if all_disputed_ok:
                scores["meeting_notes_disputed_entries_complete"] = 1.0
            if all_not_found_ok:
                scores["meeting_notes_not_found_entries_complete"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()