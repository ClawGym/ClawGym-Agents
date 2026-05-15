import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Ensure headers exist
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s.strip())
    except Exception:
        return None


def _is_iso_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _word_count(text: str) -> int:
    # Count words as sequences of alphanumerics/underscore separated by non-word
    return len(re.findall(r"\b\w+\b", text))


def _compute_budget_metrics(budget_rows: List[Dict[str, str]]) -> Optional[Dict]:
    accounts = []
    try:
        total_2024 = 0
        total_2025 = 0
        for r in budget_rows:
            acc = r.get("Account", "").strip()
            cat = r.get("Category", "").strip()
            fy24 = _parse_int(r.get("FY2024", ""))
            fy25 = _parse_int(r.get("FY2025", ""))
            if acc == "" or cat == "" or fy24 is None or fy25 is None:
                return None
            accounts.append({
                "Account": acc,
                "Category": cat,
                "FY2024": fy24,
                "FY2025": fy25,
            })
            total_2024 += fy24
            total_2025 += fy25
        yoy_pct = round((total_2025 - total_2024) / total_2024 * 100.0, 1) if total_2024 != 0 else 0.0

        # per-account computed values
        per_account = []
        for a in accounts:
            abs_change = a["FY2025"] - a["FY2024"]
            pct_change = round((abs_change / a["FY2024"]) * 100.0, 1) if a["FY2024"] != 0 else 0.0
            share = round((a["FY2025"] / total_2025) * 100.0, 1) if total_2025 != 0 else 0.0
            per_account.append({
                "Account": a["Account"],
                "Category": a["Category"],
                "FY2024": a["FY2024"],
                "FY2025": a["FY2025"],
                "AbsoluteChange": abs_change,
                "PercentChange": pct_change,
                "ShareFY2025": share,
            })

        # Sort by AbsoluteChange desc, ties by Account asc
        per_account_sorted = sorted(per_account, key=lambda x: (-x["AbsoluteChange"], x["Account"]))

        # Top3 by increase (absolute)
        top3 = per_account_sorted[:3]
        top3_list = [(t["Account"], t["AbsoluteChange"]) for t in top3]

        return {
            "total_2024": total_2024,
            "total_2025": total_2025,
            "yoy_pct_1_decimal": yoy_pct,
            "per_account": per_account,
            "per_account_sorted": per_account_sorted,
            "top3": top3_list,
        }
    except Exception:
        return None


def _find_section(text: str, start_marker: str, end_marker: Optional[str]) -> Optional[str]:
    lines = text.splitlines()
    start_idx = None
    end_idx = None
    # find start line containing start_marker (case-insensitive, substring)
    for i, line in enumerate(lines):
        if start_marker.lower() in line.lower():
            start_idx = i
            break
    if start_idx is None:
        return None
    if end_marker:
        for j in range(start_idx + 1, len(lines)):
            if lines[j].strip().lower().startswith(end_marker.lower()):
                end_idx = j
                break
    if end_idx is None:
        end_idx = len(lines)
    # content between start_idx+1 and end_idx (exclusive)
    content_lines = lines[start_idx + 1:end_idx]
    return "\n".join(content_lines).strip()


def _csv_fieldnames(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            row = next(reader, None)
            if row is None:
                return None
            return row
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        # Memo checks
        "memo_exists": 0.0,
        "memo_no_placeholders": 0.0,
        "memo_totals_values_correct": 0.0,
        "memo_yoy_pct_correct": 0.0,
        "memo_top3_list_correct": 0.0,
        "memo_exec_summary_within_150_words": 0.0,
        "memo_sections_preserved": 0.0,
        # Summary CSV checks
        "summary_exists": 0.0,
        "summary_columns_order": 0.0,
        "summary_row_count": 0.0,
        "summary_values_correct": 0.0,
        "summary_sorting_correct": 0.0,
        # CFO email checks
        "cfo_email_exists": 0.0,
        "cfo_subject_prefix": 0.0,
        "cfo_body_within_120_words": 0.0,
        "cfo_includes_fy2025_total_once": 0.0,
        "cfo_requests_brief_within_two_weeks": 0.0,
        "cfo_no_commitment_language": 0.0,
        # Advocacy email checks
        "advocacy_email_exists": 0.0,
        "advocacy_subject_exact": 0.0,
        "advocacy_body_within_100_words": 0.0,
        "advocacy_polite_acknowledgment": 0.0,
        "advocacy_no_commitment_language": 0.0,
        "advocacy_no_dollar_amounts": 0.0,
        # Reminders checks
        "reminders_csv_exists": 0.0,
        "reminders_csv_structure": 0.0,
        "reminders_rows_correct": 0.0,
        "reminders_messages_correct": 0.0,
        "reminders_summary_exists": 0.0,
        "reminders_summary_counts_correct": 0.0,
    }

    # Load input data
    budget_csv = workspace / "input" / "data" / "defense_budget.csv"
    hearings_csv = workspace / "input" / "schedule" / "hearings.csv"
    budget_rows = _read_csv_dicts(budget_csv) or []
    budget_metrics = _compute_budget_metrics(budget_rows) if budget_rows else None

    # Paths for outputs
    memo_out = workspace / "output" / "memos" / "Defense_Budget_Memo_Rev.md"
    summary_out = workspace / "output" / "data" / "defense_summary.csv"
    cfo_email_out = workspace / "output" / "emails" / "DoD_CFO_followup.txt"
    advocacy_email_out = workspace / "output" / "emails" / "Advocacy_group_reply.txt"
    reminders_out = workspace / "output" / "reminders" / "reminders.csv"
    reminders_summary_out = workspace / "output" / "reminders" / "summary.txt"

    # Memo checks
    memo_text = _read_text(memo_out)
    if memo_text is not None:
        scores["memo_exists"] = 1.0
        # Placeholders replaced
        if all(ph not in memo_text for ph in [
            "{{TOTAL_FY2025_MILLIONS}}",
            "{{TOTAL_FY2024_MILLIONS}}",
            "{{YOY_PCT_1_DECIMAL}}",
            "{{TOP3_BY_INCREASE}}",
            "{{", "}}"
        ]):
            scores["memo_no_placeholders"] = 1.0

        # Sections preserved (check presence of key section headings)
        required_sections = ["Executive Summary", "Background", "Preliminary Observations", "Follow-up Actions", "Appendix"]
        if all(any(sec.lower() in line.lower() for line in memo_text.splitlines()) for sec in required_sections):
            scores["memo_sections_preserved"] = 1.0

        if budget_metrics:
            # Totals values correctness: presence of computed totals with "million"
            t2024 = budget_metrics["total_2024"]
            t2025 = budget_metrics["total_2025"]
            if (f"{t2024} million" in memo_text) and (f"{t2025} million" in memo_text):
                scores["memo_totals_values_correct"] = 1.0

            # YOY percent correctness: one decimal like '2.9%'
            yoy = budget_metrics["yoy_pct_1_decimal"]
            if f"{yoy}%" in memo_text:
                scores["memo_yoy_pct_correct"] = 1.0

            # Top3 list correctness: ensure the three accounts with deltas appear in order with (+delta), optional "million"
            top3 = budget_metrics["top3"]  # list of tuples (Account, delta)
            # Build regex patterns in order
            patterns = []
            for acc, delta in top3:
                # accept thousands optional comma separation and optional ' million' inside parentheses
                delta_str_plain = str(delta)
                delta_str_commas = f"{delta:,}"
                pattern = re.compile(
                    re.escape(acc) + r"\s*\(\+\s*(?:" + re.escape(delta_str_plain) + r"|" + re.escape(delta_str_commas) + r")\s*(?:million)?\s*\)",
                    flags=re.IGNORECASE
                )
                patterns.append(pattern)

            # Verify ordered occurrence
            pos = 0
            ok = True
            for pat in patterns:
                m = pat.search(memo_text, pos)
                if not m:
                    ok = False
                    break
                pos = m.end()
            if ok:
                scores["memo_top3_list_correct"] = 1.0

        # Executive Summary <= 150 words
        exec_section = _find_section(memo_text, "Executive Summary", "Background")
        if exec_section is not None:
            wc = _word_count(exec_section)
            if wc <= 150:
                scores["memo_exec_summary_within_150_words"] = 1.0

    # Summary CSV checks
    if summary_out.exists():
        scores["summary_exists"] = 1.0
        # columns order
        fieldnames = _csv_fieldnames(summary_out)
        expected_cols = ["Account", "Category", "FY2024", "FY2025", "AbsoluteChange", "PercentChange", "ShareFY2025"]
        if fieldnames == expected_cols:
            scores["summary_columns_order"] = 1.0
        # parse rows
        summary_rows = _read_csv_dicts(summary_out) or []
        if budget_metrics:
            expected_accounts = {r["Account"] for r in budget_metrics["per_account"]}
            if len(summary_rows) == len(expected_accounts) == len(budget_metrics["per_account"]):
                scores["summary_row_count"] = 1.0
            # Check values and sorting
            values_ok = True
            sorting_ok = True
            # Build expected mapping
            exp_map = {r["Account"]: r for r in budget_metrics["per_account"]}
            # Verify each row
            seen_accounts = []
            for r in summary_rows:
                acc = r.get("Account", "").strip()
                seen_accounts.append(acc)
                if acc not in exp_map:
                    values_ok = False
                    break
                exp = exp_map[acc]
                # Category
                if r.get("Category", "").strip() != exp["Category"]:
                    values_ok = False
                    break
                # Numeric checks
                fy24 = _parse_int(r.get("FY2024", ""))
                fy25 = _parse_int(r.get("FY2025", ""))
                abs_ch = _parse_int(r.get("AbsoluteChange", ""))
                try:
                    pct_ch = float(str(r.get("PercentChange", "")).strip())
                    share = float(str(r.get("ShareFY2025", "")).strip())
                except Exception:
                    values_ok = False
                    break
                if fy24 != exp["FY2024"] or fy25 != exp["FY2025"] or abs_ch != exp["AbsoluteChange"]:
                    values_ok = False
                    break
                # PercentChange and ShareFY2025 equality to one decimal
                if round(pct_ch, 1) != exp["PercentChange"] or round(share, 1) != exp["ShareFY2025"]:
                    values_ok = False
                    break
            if values_ok:
                scores["summary_values_correct"] = 1.0

            # Sorting check by AbsoluteChange desc, ties Account asc
            # Build expected order
            expected_sorted_accounts = [r["Account"] for r in budget_metrics["per_account_sorted"]]
            # Compare seen order exactly
            if seen_accounts == expected_sorted_accounts and len(seen_accounts) == len(expected_sorted_accounts):
                sorting_ok = True
            else:
                sorting_ok = False
            if sorting_ok:
                scores["summary_sorting_correct"] = 1.0

    # CFO email checks
    cfo_text = _read_text(cfo_email_out)
    if cfo_text is not None:
        scores["cfo_email_exists"] = 1.0
        lines = cfo_text.splitlines()
        subj_line = lines[0].strip() if lines else ""
        # Subject starts with exactly phrase
        subj_prefix = "Follow-up: FY2025 Defense Budget Brief"
        if subj_line.lower().startswith("subject:"):
            content = subj_line[len("subject:"):].strip()
            if content.startswith(subj_prefix):
                scores["cfo_subject_prefix"] = 1.0
        # Body within 120 words
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        if _word_count(body) <= 120:
            scores["cfo_body_within_120_words"] = 1.0
        # Includes FY2025 total as "$<number> million" exactly once
        if budget_metrics:
            t2025 = budget_metrics["total_2025"]
            pattern_total = rf"\${t2025}\s+million\b"
            matches = re.findall(pattern_total, body)
            if len(matches) == 1:
                scores["cfo_includes_fy2025_total_once"] = 1.0
        # Requests a short briefing within the next two weeks
        # Check for "brief" and "two week" phrases
        if re.search(r"\bbrief\w*\b", body, flags=re.IGNORECASE) and re.search(r"\b(two\s+weeks?|2\s+weeks?)\b", body, flags=re.IGNORECASE):
            scores["cfo_requests_brief_within_two_weeks"] = 1.0
        # No commitments: check absence of "commit" or "promise"
        if not re.search(r"\bcommit\w*\b", body, flags=re.IGNORECASE) and not re.search(r"\bpromis\w*\b", body, flags=re.IGNORECASE):
            scores["cfo_no_commitment_language"] = 1.0

    # Advocacy email checks
    adv_text = _read_text(advocacy_email_out)
    if adv_text is not None:
        scores["advocacy_email_exists"] = 1.0
        lines = adv_text.splitlines()
        subj_line = lines[0].strip() if lines else ""
        # Subject exact
        if subj_line.strip() == "Subject: Re: Budget Priorities Inquiry":
            scores["advocacy_subject_exact"] = 1.0
        # Body within 100 words
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        if _word_count(body) <= 100:
            scores["advocacy_body_within_100_words"] = 1.0
        # Polite acknowledgment (look for thanks/thank/appreciate)
        if re.search(r"\bthank(s| you)?\b", body, flags=re.IGNORECASE) or re.search(r"\bappreciate\b", body, flags=re.IGNORECASE):
            scores["advocacy_polite_acknowledgment"] = 1.0
        # No commitments: absence of commit/promise/will/support/champion
        if (not re.search(r"\bcommit\w*\b", body, flags=re.IGNORECASE)
            and not re.search(r"\bpromis\w*\b", body, flags=re.IGNORECASE)
            and not re.search(r"\bchampion\w*\b", body, flags=re.IGNORECASE)
            and not re.search(r"\bsupport\w*\b", body, flags=re.IGNORECASE)):
            scores["advocacy_no_commitment_language"] = 1.0
        # Avoid specific dollar amounts: no "$" and no "million" and no "%"
        if "$" not in body and not re.search(r"\bmillion(s)?\b", body, flags=re.IGNORECASE) and "%" not in body:
            scores["advocacy_no_dollar_amounts"] = 1.0

    # Reminders checks
    reminders_text_rows = _read_csv_dicts(reminders_out) if reminders_out.exists() else None
    if reminders_out.exists():
        scores["reminders_csv_exists"] = 1.0
        # Structure: columns in exact order
        expected_cols_rem = ["HearingDate", "Topic", "ReminderType", "DueDate", "Message"]
        actual_cols_rem = _csv_fieldnames(reminders_out)
        if actual_cols_rem == expected_cols_rem:
            scores["reminders_csv_structure"] = 1.0

    # Compute expected reminders from input schedule
    hearings_rows = _read_csv_dicts(hearings_csv) or []
    expected_reminders: List[Tuple[str, str, str, str]] = []
    if hearings_rows:
        for r in hearings_rows:
            topic = r.get("topic", "").strip() or r.get("Topic", "").strip()
            hearing_date = r.get("hearing_date", "").strip() or r.get("HearingDate", "").strip()
            w_days = r.get("witness_deadline_days", "").strip() or r.get("witness_deadline_days".upper(), "").strip()
            q_days = r.get("qfr_deadline_days", "").strip() or r.get("qfr_deadline_days".upper(), "").strip()
            if not topic or not hearing_date or not _is_iso_date(hearing_date):
                continue
            try:
                w_days_i = int(w_days)
                q_days_i = int(q_days)
            except Exception:
                continue
            hd = datetime.strptime(hearing_date, "%Y-%m-%d").date()
            # WitnessLetter
            wl_due = (hd - timedelta(days=w_days_i)).isoformat()
            # QFRSubmission
            qfr_due = (hd + timedelta(days=q_days_i)).isoformat()
            # StaffMemoReview
            smr_due = (hd - timedelta(days=3)).isoformat()
            expected_reminders.append((hearing_date, topic, "WitnessLetter", wl_due))
            expected_reminders.append((hearing_date, topic, "QFRSubmission", qfr_due))
            expected_reminders.append((hearing_date, topic, "StaffMemoReview", smr_due))

    # Validate reminders rows and messages
    if reminders_text_rows is not None and expected_reminders:
        # Build actual set of (HearingDate, Topic, ReminderType, DueDate)
        actual_quads = []
        messages_ok = True
        for r in reminders_text_rows:
            h = (r.get("HearingDate", "") or "").strip()
            t = (r.get("Topic", "") or "").strip()
            rt = (r.get("ReminderType", "") or "").strip()
            dd = (r.get("DueDate", "") or "").strip()
            msg = (r.get("Message", "") or "").strip()
            actual_quads.append((h, t, rt, dd))
            # Message should include Topic and ReminderType
            if t not in msg or rt not in msg:
                messages_ok = False
            # Dates ISO
            if not _is_iso_date(h) or not _is_iso_date(dd):
                messages_ok = False
            # ReminderType valid
            if rt not in {"WitnessLetter", "QFRSubmission", "StaffMemoReview"}:
                messages_ok = False

        # Compare counts and exact expected set
        if len(actual_quads) == len(expected_reminders) and Counter(actual_quads) == Counter(expected_reminders):
            scores["reminders_rows_correct"] = 1.0
        if messages_ok:
            scores["reminders_messages_correct"] = 1.0

    # Reminders summary.txt checks
    rem_summary_text = _read_text(reminders_summary_out)
    if rem_summary_text is not None:
        scores["reminders_summary_exists"] = 1.0
        # Compute expected counts by DueDate month from expected reminders
        month_counts = defaultdict(int)
        for _, _, _, due in expected_reminders:
            if _is_iso_date(due):
                month = due[:7]  # YYYY-MM
                month_counts[month] += 1
        expected_lines = [f"{m}: {month_counts[m]}" for m in sorted(month_counts.keys())]
        actual_lines = [ln.strip() for ln in rem_summary_text.splitlines() if ln.strip() != ""]
        if expected_lines == actual_lines:
            scores["reminders_summary_counts_correct"] = 1.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()