import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        out = []
        for ln in lines:
            if ln.strip() == "":
                continue
            out.append(json.loads(ln))
        return out
    except Exception:
        return None


def _load_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            return [row for row in rdr]
    except Exception:
        return None


def _parse_float_amount(val: str) -> Optional[float]:
    try:
        s = val.strip()
        s = s.replace(",", "")
        if s.startswith("$"):
            s = s[1:]
        return float(s)
    except Exception:
        return None


def _parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None


def _extract_preservation_tokens(text: str) -> Tuple[List[str], List[str], List[str]]:
    # Dates in ISO format
    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
    # Quoted titles in single quotes
    quoted = re.findall(r"'[^']+'", text)
    # Numeric tokens including currency (not part of the dates)
    # Capture tokens like $145.00, 129.60, 210, etc.
    all_nums = re.findall(r"\$?\d+(?:\.\d+)?", text)
    # Filter out tokens that are substrings of dates (e.g., 2025, 09, 30)
    nums = []
    for tok in all_nums:
        in_date = False
        for d in dates:
            if tok in d:
                in_date = True
                break
        if not in_date:
            nums.append(tok)
    return nums, dates, quoted


def _within_q3_2025(date_str: str) -> bool:
    d = _parse_date(date_str)
    if d is None:
        return False
    start = datetime(2025, 7, 1)
    end = datetime(2025, 9, 30)
    return start <= d <= end


def _compute_totals_by_source(ledger: List[Dict[str, str]]) -> Dict[str, float]:
    totals: Dict[str, float] = {}
    for row in ledger:
        if not _within_q3_2025(row.get("date", "")):
            continue
        src = row.get("source", "").strip()
        amt = _parse_float_amount(row.get("amount_usd", ""))
        if amt is None:
            continue
        totals[src] = totals.get(src, 0.0) + amt
    # Round to 2 decimal places for comparison
    for k in list(totals.keys()):
        totals[k] = round(totals[k] + 0.0, 2)
    return totals


def _late_pending_items(ledger: List[Dict[str, str]]) -> List[Dict[str, str]]:
    items = []
    for row in ledger:
        if not _within_q3_2025(row.get("date", "")):
            continue
        status = (row.get("status", "") or "").strip().lower()
        if status in {"late", "pending"}:
            items.append(row)
    return items


def _norm_heading(line: str) -> str:
    return line.strip().rstrip(":").lower()


def _extract_sections(text: str) -> Dict[str, List[str]]:
    lines = text.splitlines()
    sections: Dict[str, List[str]] = {}
    headings = ["totals by source", "late or pending items", "notes"]
    current = None
    for line in lines:
        lh = _norm_heading(line)
        if lh in headings:
            current = lh
            if current not in sections:
                sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _first_amount_in_line(line: str) -> Optional[float]:
    m = re.search(r"\$?\d+(?:\.\d+)?", line)
    if not m:
        return None
    return _parse_float_amount(m.group(0))


def _almost_equal(a: float, b: float, tol: float = 0.005) -> bool:
    return abs(a - b) <= tol


def _word_count(s: str) -> int:
    return len(s.split())


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "messages_rewritten_exists_and_structure": 0.0,
        "messages_rewritten_ids_match_and_recipient": 0.0,
        "messages_numbers_dates_titles_preserved": 0.0,
        "messages_brevity": 0.0,
        "messages_calm_tone": 0.0,
        "messages_validation_csv_correct": 0.0,
        "royalty_report_exists_and_sections": 0.0,
        "royalty_totals_by_source_correct": 0.0,
        "royalty_late_or_pending_items_correct": 0.0,
        "royalty_notes_bullets_count_valid": 0.0,
        "email_drafts_exists_and_structure": 0.0,
        "email_a_recipient_subject_and_body": 0.0,
        "email_b_recipient_and_late_pending_mention": 0.0,
        "email_b_totals_by_source_correct": 0.0,
        "email_word_count_limits": 0.0,
    }

    # Load inputs
    raw_messages_path = workspace / "input" / "raw_messages.jsonl"
    ledger_path = workspace / "input" / "royalty_ledger.csv"
    contacts_path = workspace / "input" / "contacts.csv"

    raw_messages = _load_jsonl(raw_messages_path) or []
    ledger = _load_csv_dicts(ledger_path) or []
    contacts = _load_csv_dicts(contacts_path) or []

    input_ids = [m.get("id") for m in raw_messages if isinstance(m, dict)]
    input_map = {m.get("id"): m for m in raw_messages if isinstance(m, dict) and "id" in m}

    # Deliverable 1: messages_rewritten.jsonl
    rewritten_path = workspace / "output" / "messages_rewritten.jsonl"
    rewritten = _load_jsonl(rewritten_path)

    if rewritten is not None and isinstance(rewritten, list):
        # Basic structure: 3 lines, each with id, recipient, rewritten_text
        try:
            all_have_fields = True
            for obj in rewritten:
                if not isinstance(obj, dict):
                    all_have_fields = False
                    break
                if not all(k in obj for k in ("id", "recipient", "rewritten_text")):
                    all_have_fields = False
                    break
                if not isinstance(obj["id"], str) or not isinstance(obj["recipient"], str) or not isinstance(obj["rewritten_text"], str):
                    all_have_fields = False
                    break
            if all_have_fields and len(rewritten) == len(input_ids) == 3:
                scores["messages_rewritten_exists_and_structure"] = 1.0
        except Exception:
            pass

        # IDs and recipient match original messages
        try:
            out_ids = [obj.get("id") for obj in rewritten if isinstance(obj, dict)]
            if set(out_ids) == set(input_ids) and all(
                obj.get("recipient") == (input_map.get(obj.get("id")) or {}).get("recipient")
                for obj in rewritten
            ):
                scores["messages_rewritten_ids_match_and_recipient"] = 1.0
        except Exception:
            pass

        # Preservation constraints and brevity and calm tone
        try:
            preserve_all = True
            brevity_all = True
            calm_all = True
            for obj in rewritten:
                mid = obj.get("id")
                orig = (input_map.get(mid) or {}).get("text", "")
                rew = obj.get("rewritten_text", "")
                o_nums, o_dates, o_quoted = _extract_preservation_tokens(orig)
                # unique tokens; duplicates are not required to be repeated, only presence
                def _all_present(tokens: List[str], text: str) -> bool:
                    for t in tokens:
                        if t not in text:
                            return False
                    return True

                nums_ok = _all_present(list(dict.fromkeys(o_nums)), rew)
                dates_ok = _all_present(list(dict.fromkeys(o_dates)), rew)
                quoted_ok = _all_present(list(dict.fromkeys(o_quoted)), rew)
                if not (nums_ok and dates_ok and quoted_ok):
                    preserve_all = False

                # brevity: rewritten not longer than original
                if not (len(rew) <= len(orig)):
                    brevity_all = False

                # calm tone: no exclamation marks, no ALL CAPS words (>=3 letters)
                if "!" in rew:
                    calm_all = False
                if re.search(r"\b[A-Z]{3,}\b", rew):
                    calm_all = False

            if preserve_all:
                scores["messages_numbers_dates_titles_preserved"] = 1.0
            if brevity_all:
                scores["messages_brevity"] = 1.0
            if calm_all:
                scores["messages_calm_tone"] = 1.0
        except Exception:
            pass
    else:
        # If file missing or malformed, keep zeros but don't crash
        pass

    # Deliverable 4: messages_validation.csv correctness (must match computed preservation)
    validation_path = workspace / "output" / "messages_validation.csv"
    validation_rows = _load_csv_dicts(validation_path)
    try:
        if validation_rows is not None:
            # Expect columns id,numbers_preserved,dates_preserved,quoted_titles_preserved
            expected_fields = ["id", "numbers_preserved", "dates_preserved", "quoted_titles_preserved"]
            header_ok = all(f in validation_rows[0] for f in expected_fields) if validation_rows else False

            # Compute expected outcomes
            expected_map = {}
            for m in raw_messages:
                mid = m.get("id")
                orig = m.get("text", "")
                # Find matching rewritten
                rew_obj = None
                for obj in (rewritten or []):
                    if obj.get("id") == mid:
                        rew_obj = obj
                        break
                if rew_obj is None:
                    expected_map[mid] = {"numbers_preserved": "no", "dates_preserved": "no", "quoted_titles_preserved": "no"}
                    continue
                rew = rew_obj.get("rewritten_text", "")
                o_nums, o_dates, o_quoted = _extract_preservation_tokens(orig)

                def _all_present(tokens: List[str], text: str) -> bool:
                    for t in tokens:
                        if t not in text:
                            return False
                    return True

                expected_map[mid] = {
                    "numbers_preserved": "yes" if _all_present(list(dict.fromkeys(o_nums)), rew) else "no",
                    "dates_preserved": "yes" if _all_present(list(dict.fromkeys(o_dates)), rew) else "no",
                    "quoted_titles_preserved": "yes" if _all_present(list(dict.fromkeys(o_quoted)), rew) else "no",
                }

            rows_ok = True
            if not header_ok:
                rows_ok = False
            else:
                # Must have one row per input message, ids match
                val_ids = [row.get("id") for row in validation_rows]
                if set(val_ids) != set(input_ids) or len(validation_rows) != len(input_ids):
                    rows_ok = False
                else:
                    for row in validation_rows:
                        mid = row.get("id")
                        exp = expected_map.get(mid, {})
                        if not exp:
                            rows_ok = False
                            break
                        if (row.get("numbers_preserved", "").strip().lower() != exp["numbers_preserved"]
                            or row.get("dates_preserved", "").strip().lower() != exp["dates_preserved"]
                            or row.get("quoted_titles_preserved", "").strip().lower() != exp["quoted_titles_preserved"]):
                            rows_ok = False
                            break
            if rows_ok:
                scores["messages_validation_csv_correct"] = 1.0
    except Exception:
        pass

    # Deliverable 2: royalty_status_summary.md
    report_path = workspace / "output" / "royalty_status_summary.md"
    report_text = _read_text(report_path)
    totals_expected = _compute_totals_by_source(ledger)
    late_pending_expected = _late_pending_items(ledger)

    if report_text is not None:
        try:
            sections = _extract_sections(report_text)
            has_all_sections = all(h in sections for h in ["totals by source", "late or pending items", "notes"])
            if has_all_sections:
                scores["royalty_report_exists_and_sections"] = 1.0
        except Exception:
            pass

        # Totals by Source correctness
        try:
            if "totals by source" in sections and totals_expected:
                lines = sections["totals by source"]
                # Build found map
                found: Dict[str, float] = {}
                for line in lines:
                    for src in totals_expected.keys():
                        if src in line:
                            amt = _first_amount_in_line(line)
                            if amt is not None:
                                found[src] = round(amt, 2)
                totals_ok = set(found.keys()) == set(totals_expected.keys()) and all(
                    _almost_equal(found[src], totals_expected[src]) for src in totals_expected
                )
                if totals_ok:
                    scores["royalty_totals_by_source_correct"] = 1.0
        except Exception:
            pass

        # Late or Pending Items correctness
        try:
            if "late or pending items" in sections:
                lines = [ln.strip() for ln in sections["late or pending items"] if ln.strip()]
                bullet_lines = [ln for ln in lines if ln.startswith("-") or ln.startswith("*")]
                # Expect exactly the items flagged in ledger
                def _line_contains_item(ln: str, item: Dict[str, str]) -> bool:
                    src = item.get("source", "")
                    track = item.get("track", "")
                    due = item.get("due_date", "")
                    status = (item.get("status", "") or "").lower()
                    amt = _parse_float_amount(item.get("amount_usd", ""))
                    if src not in ln or track not in ln or due not in ln:
                        return False
                    if status not in ln.lower():
                        return False
                    # amount presence
                    if amt is None:
                        return False
                    # Build allowed amount patterns: $145.00 or 145.00
                    amt_str = f"{amt:.2f}"
                    if (amt_str not in ln) and (f"${amt_str}" not in ln):
                        return False
                    return True

                expected_items = late_pending_expected
                if len(bullet_lines) == len(expected_items) and all(
                    any(_line_contains_item(ln, it) for ln in bullet_lines) for it in expected_items
                ):
                    scores["royalty_late_or_pending_items_correct"] = 1.0
        except Exception:
            pass

        # Notes section bullets 1–3
        try:
            if "notes" in sections:
                lines = [ln.strip() for ln in sections["notes"] if ln.strip()]
                bullet_lines = [ln for ln in lines if ln.startswith("-") or ln.startswith("*")]
                if 1 <= len(bullet_lines) <= 3:
                    scores["royalty_notes_bullets_count_valid"] = 1.0
        except Exception:
            pass

    # Deliverable 3: email_drafts.json
    emails_path = workspace / "output" / "email_drafts.json"
    emails = _load_json(emails_path)
    contacts_by_role = {}
    for row in (contacts or []):
        role = row.get("role", "").strip()
        email = row.get("email", "").strip()
        name = row.get("name", "").strip()
        contacts_by_role[role] = {"email": email, "name": name}

    if isinstance(emails, list):
        try:
            structure_ok = True
            if len(emails) != 2:
                structure_ok = False
            else:
                for e in emails:
                    if not isinstance(e, dict):
                        structure_ok = False
                        break
                    if not all(k in e for k in ("to", "subject", "body")):
                        structure_ok = False
                        break
                    if not isinstance(e["to"], str) or not isinstance(e["subject"], str) or not isinstance(e["body"], str):
                        structure_ok = False
                        break
            if structure_ok:
                scores["email_drafts_exists_and_structure"] = 1.0
        except Exception:
            pass

        # Identify Email A and B by recipients
        try:
            email_a_ok = False
            email_b_ok = False
            email_b_totals_ok = False
            words_ok = True

            royalty_admin_email = None
            accountant_email = None
            for role, info in contacts_by_role.items():
                if role.lower() == "royalty administrator":
                    royalty_admin_email = info.get("email")
                if role.lower() == "accountant":
                    accountant_email = info.get("email")

            # Precompute expected totals and late/pending
            totals = totals_expected
            lp_items = late_pending_expected

            # Evaluate each email
            for e in emails if isinstance(emails, list) else []:
                to = e.get("to", "")
                subject = e.get("subject", "")
                body = e.get("body", "")

                # Word count limit
                if _word_count(body) > 150:
                    words_ok = False

                # Email A: To Royalty Administrator, subject references "August 2025 mechanical for 'Low Ceiling'", body includes $145.00 and 2025-09-30 and status update request
                if royalty_admin_email and to == royalty_admin_email:
                    subj_ref = "August 2025 mechanical for 'Low Ceiling'"
                    has_subj_ref = subj_ref in subject
                    has_amt = "$145.00" in body
                    has_due = "2025-09-30" in body
                    asks_status = ("status" in body.lower() and "update" in body.lower())
                    if has_subj_ref and has_amt and has_due and asks_status:
                        email_a_ok = True

                # Email B: To Accountant, include Q3 totals by source and a one-line mention of any late or pending items
                if accountant_email and to == accountant_email:
                    # Check totals present: each source name and amount
                    totals_present = True
                    for src, amt in totals.items():
                        src_present = src in body
                        amt_str = f"{amt:.2f}"
                        amt_present = (amt_str in body) or (f"${amt_str}" in body)
                        if not (src_present and amt_present):
                            totals_present = False
                            break
                    email_b_totals_ok = email_b_totals_ok or totals_present
                    # One-line mention of any late or pending items
                    lines = [ln.strip() for ln in body.splitlines()]
                    has_lp_line = any(("late" in ln.lower() or "pending" in ln.lower()) for ln in lines)
                    if totals_present and has_lp_line:
                        email_b_ok = True

            if email_a_ok:
                scores["email_a_recipient_subject_and_body"] = 1.0
            if email_b_ok:
                scores["email_b_recipient_and_late_pending_mention"] = 1.0
            if email_b_totals_ok:
                scores["email_b_totals_by_source_correct"] = 1.0
            if words_ok:
                scores["email_word_count_limits"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()