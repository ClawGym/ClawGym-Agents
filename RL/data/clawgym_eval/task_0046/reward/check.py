import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        if reader.fieldnames is None:
            return None
        return rows
    except Exception:
        return None


def _parse_date(s: str):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _find_section_lines(lines: List[str], title_exact: str) -> Optional[List[str]]:
    def norm_heading(line: str) -> str:
        stripped = line.lstrip("#").strip()
        return stripped
    start_idx = None
    for i, line in enumerate(lines):
        if norm_heading(line) == title_exact:
            start_idx = i
            break
    if start_idx is None:
        return None
    content_start = start_idx + 1
    end_idx = len(lines)
    for j in range(content_start, len(lines)):
        if lines[j].lstrip().startswith("#"):
            end_idx = j
            break
    return lines[content_start:end_idx]


def _count_sentences(text: str) -> int:
    parts = re.split(r'[.!?]+', text)
    count = sum(1 for p in parts if p.strip() != "")
    return count


def _contains_emoji(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if 0x1F300 <= code <= 0x1FAFF:
            return True
    return False


def _has_slang(text: str) -> bool:
    slang = [
        "ugh", "asap", "crushed it", "crushed", "dl", "heads up",
        "quick n dirty", "quick'n dirty", "kinda", "gonna", "ish", "tho", "fix asap",
        "hey, ", "lol", "btw", "omg", "nvm", "idk", "heads-up"
    ]
    lt = text.lower()
    return any(s in lt for s in slang)


def _parse_currency_tokens(text: str) -> List[Tuple[str, float, bool]]:
    """
    Return a list of tuples: (raw_token, value_float, has_explicit_sign)
    Recognize formats:
      +$123.45, -$123.45, $+123.45, $-123.45, $123.45
    """
    tokens: List[Tuple[str, float, bool]] = []
    seen_spans = set()
    patterns = [
        re.compile(r'([+-])?\$\s*(\d+\.\d{2})'),   # sign before $
        re.compile(r'\$\s*([+-])?(\d+\.\d{2})'),   # sign after $
    ]
    for pat in patterns:
        for m in pat.finditer(text):
            span = m.span()
            if span in seen_spans:
                continue
            seen_spans.add(span)
            raw = m.group(0)
            if pat.pattern.startswith('('):  # first pattern
                sign = m.group(1) or ""
                amount = m.group(2)
            else:  # second pattern
                sign = m.group(1) or ""
                amount = m.group(2)
            try:
                val = float(amount)
                if sign == "-":
                    val = -val
                elif sign == "+":
                    val = +val
                has_sign = sign in ("+", "-")
                tokens.append((raw, val, has_sign))
            except Exception:
                continue
    return tokens


def _value_matches_in_line(expected: float, line: str, require_sign: bool = False, tol: float = 0.005) -> bool:
    tokens = _parse_currency_tokens(line)
    for raw, val, has_sign in tokens:
        if abs(round(val, 2) - round(expected, 2)) <= tol:
            if require_sign:
                if has_sign:
                    return True
            else:
                return True
    return False


def _line_contains_strategy_and_value(lines: List[str], strategy: str, expected_value: float, require_sign: bool = False) -> bool:
    for ln in lines:
        if strategy in ln and _value_matches_in_line(expected_value, ln, require_sign=require_sign):
            return True
    return False


def _email_opening_paragraph(lines: List[str]) -> str:
    # After subject, until first blank line
    if not lines:
        return ""
    opening_lines = []
    for i in range(1, len(lines)):
        if lines[i].strip() == "":
            break
        opening_lines.append(lines[i])
    return " ".join(opening_lines)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "weekly_summary_exists": 0.0,
        "weekly_summary_totals_section": 0.0,
        "weekly_summary_reported_vs_computed_section": 0.0,
        "weekly_summary_validation_status_section": 0.0,
        "email_exists": 0.0,
        "email_subject_and_overview": 0.0,
        "email_list_entries": 0.0,
        "email_closing": 0.0,
        "rewritten_messages_exists": 0.0,
        "rewritten_messages_structure": 0.0,
    }

    # Inputs
    trades_path = workspace / "input" / "trades.csv"
    reported_path = workspace / "input" / "reported_pnl.csv"
    raw_msgs_path = workspace / "input" / "raw_messages.md"

    # Outputs
    summary_path = workspace / "output" / "weekly_summary.md"
    email_path = workspace / "output" / "compliance_email.txt"
    rewritten_path = workspace / "output" / "rewritten_messages.md"

    # Load inputs safely
    trades_rows = _load_csv_rows(trades_path) or []
    reported_rows = _load_csv_rows(reported_path) or []
    raw_msgs_text = _read_text_safe(raw_msgs_path)

    # Compute week boundaries
    week_start_str = "2024-09-02"
    week_end_str = "2024-09-06"
    week_start = _parse_date(week_start_str)
    week_end = _parse_date(week_end_str)

    # Compute computed nets from trades within week
    computed_by_strategy: Dict[str, float] = {}
    overall_net: Optional[float] = None
    if trades_rows and week_start and week_end:
        try:
            for r in trades_rows:
                d = _parse_date((r.get("date") or "").strip())
                if d is None:
                    computed_by_strategy = {}
                    overall_net = None
                    break
                if not (week_start <= d <= week_end):
                    continue
                strategy = (r.get("strategy") or "").strip()
                try:
                    gross = float((r.get("gross_pnl") or "").strip())
                    fees = float((r.get("fees") or "").strip())
                except Exception:
                    computed_by_strategy = {}
                    overall_net = None
                    break
                net = gross - fees
                computed_by_strategy[strategy] = computed_by_strategy.get(strategy, 0.0) + net
            if computed_by_strategy:
                overall_net = sum(computed_by_strategy.values())
        except Exception:
            computed_by_strategy = {}
            overall_net = None

    # Compute reported per strategy for the specified week
    reported_by_strategy: Dict[str, float] = {}
    if reported_rows and week_start and week_end:
        try:
            for r in reported_rows:
                ws = _parse_date((r.get("week_start") or "").strip())
                we = _parse_date((r.get("week_end") or "").strip())
                if ws == week_start and we == week_end:
                    strategy = (r.get("strategy") or "").strip()
                    try:
                        val = float((r.get("reported_pnl") or "").strip())
                    except Exception:
                        reported_by_strategy = {}
                        break
                    reported_by_strategy[strategy] = val
        except Exception:
            reported_by_strategy = {}

    # Deltas for reported strategies
    deltas_by_strategy: Dict[str, float] = {}
    if reported_by_strategy:
        for s, rep in reported_by_strategy.items():
            comp = computed_by_strategy.get(s, 0.0) if computed_by_strategy else 0.0
            deltas_by_strategy[s] = rep - comp

    mismatches_expected = 0
    if deltas_by_strategy:
        mismatches_expected = sum(1 for v in deltas_by_strategy.values() if abs(v) >= 1.00)

    # Check weekly_summary.md
    if summary_path.exists():
        scores["weekly_summary_exists"] = 1.0
        summary_text = _read_text_safe(summary_path)
        lines = summary_text.splitlines()

        # Totals section check
        totals_section = _find_section_lines(lines, "Totals (computed from trades.csv)")
        totals_ok = False
        if totals_section is not None and computed_by_strategy and overall_net is not None:
            per_ok = True
            for s, val in computed_by_strategy.items():
                if not _line_contains_strategy_and_value(totals_section, s, val, require_sign=False):
                    per_ok = False
                    break
            overall_ok = False
            for ln in totals_section:
                if ("overall" in ln.lower() or "total" in ln.lower()) and _value_matches_in_line(overall_net, ln, require_sign=False):
                    overall_ok = True
                    break
            totals_ok = per_ok and overall_ok
        scores["weekly_summary_totals_section"] = 1.0 if totals_ok else 0.0

        # Reported vs computed section
        rvc_section = _find_section_lines(lines, "Reported vs computed")
        rvc_ok = False
        if rvc_section is not None and reported_by_strategy:
            all_ok = True
            for s, rep in reported_by_strategy.items():
                comp = computed_by_strategy.get(s, 0.0) if computed_by_strategy else 0.0
                delta = rep - comp
                found_line = None
                for ln in rvc_section:
                    if s in ln:
                        # Need three values present: reported, computed, delta (delta must have explicit sign)
                        if _value_matches_in_line(rep, ln, require_sign=False) and _value_matches_in_line(comp, ln, require_sign=False) and _value_matches_in_line(delta, ln, require_sign=True):
                            found_line = ln
                            break
                if not found_line:
                    all_ok = False
                    break
            rvc_ok = all_ok
        scores["weekly_summary_reported_vs_computed_section"] = 1.0 if rvc_ok else 0.0

        # Validation status section
        vs_section = _find_section_lines(lines, "Validation status")
        vs_ok = False
        if vs_section is not None and reported_by_strategy:
            stat_ok = True
            for s, delta in deltas_by_strategy.items():
                status = "Mismatch" if abs(delta) >= 1.00 else "Aligned"
                found = False
                for ln in vs_section:
                    if (s in ln) and (status in ln):
                        found = True
                        break
                if not found:
                    stat_ok = False
                    break
            count_ok = False
            expected_count_str = str(mismatches_expected)
            for ln in vs_section:
                if "mismatch" in ln.lower() and expected_count_str in ln:
                    count_ok = True
                    break
            vs_ok = stat_ok and count_ok
        scores["weekly_summary_validation_status_section"] = 1.0 if vs_ok else 0.0
    else:
        scores["weekly_summary_exists"] = 0.0
        scores["weekly_summary_totals_section"] = 0.0
        scores["weekly_summary_reported_vs_computed_section"] = 0.0
        scores["weekly_summary_validation_status_section"] = 0.0

    # Check compliance_email.txt
    if email_path.exists():
        scores["email_exists"] = 1.0
        email_text = _read_text_safe(email_path)
        email_lines = email_text.splitlines()

        # Subject check
        subject_expected = "Subject: Weekly P&L Validation: 2024-09-02 to 2024-09-06"
        subj_ok = False
        if email_lines:
            subj_ok = (email_lines[0].strip() == subject_expected)

        # Opening paragraph: must include overall net and mismatches count
        open_ok = False
        if subj_ok and overall_net is not None:
            opening = _email_opening_paragraph(email_lines)
            if opening:
                has_overall = _value_matches_in_line(overall_net, opening, require_sign=False)
                has_mismatch_count = ("mismatch" in opening.lower() and str(mismatches_expected) in opening)
                open_ok = has_overall and has_mismatch_count

        scores["email_subject_and_overview"] = 1.0 if (subj_ok and open_ok) else 0.0

        # List entries: lines with strategy, reported, computed, delta and mismatches marked
        list_ok = False
        if reported_by_strategy:
            strategies_ok = True
            for s, rep in reported_by_strategy.items():
                comp = computed_by_strategy.get(s, 0.0) if computed_by_strategy else 0.0
                delta = rep - comp
                found_line = None
                for ln in email_lines:
                    if (s in ln) and _value_matches_in_line(rep, ln, require_sign=False) and _value_matches_in_line(comp, ln, require_sign=False) and _value_matches_in_line(delta, ln, require_sign=True):
                        found_line = ln
                        break
                if not found_line:
                    strategies_ok = False
                    break
                if abs(delta) >= 1.00:
                    if "mismatch" not in found_line.lower():
                        strategies_ok = False
                        break
            list_ok = strategies_ok
        scores["email_list_entries"] = 1.0 if list_ok else 0.0

        # Closing paragraph: propose next steps and professional sign-off
        closing_ok = False
        if email_lines:
            last_idx = 0
            if reported_by_strategy:
                for i, ln in enumerate(email_lines):
                    for s in reported_by_strategy.keys():
                        if s in ln and any(ch.isdigit() for ch in ln) and "$" in ln:
                            last_idx = max(last_idx, i)
            closing_text = " ".join(email_lines[last_idx + 1 :]).strip()
            if closing_text:
                next_steps = any(w in closing_text.lower() for w in ["confirm", "adjust", "adjustment", "update", "reconcile", "correct"])
                sign_off = any(phrase in closing_text for phrase in ["Regards", "Best", "Sincerely", "Thank you", "Thanks"])
                closing_ok = next_steps and sign_off
        scores["email_closing"] = 1.0 if closing_ok else 0.0

    else:
        scores["email_exists"] = 0.0
        scores["email_subject_and_overview"] = 0.0
        scores["email_list_entries"] = 0.0
        scores["email_closing"] = 0.0

    # Check rewritten_messages.md
    if rewritten_path.exists():
        scores["rewritten_messages_exists"] = 1.0
        rewritten_text = _read_text_safe(rewritten_path)
        rewritten_lines = rewritten_text.splitlines()

        ids = ["MSG1", "MSG2", "MSG3"]
        raw_audiences: Dict[str, str] = {}
        if raw_msgs_text:
            raw_lines = raw_msgs_text.splitlines()
            current_id = None
            for ln in raw_lines:
                if ln.strip().startswith("### "):
                    current_id = ln.strip().replace("### ", "").strip()
                elif ln.strip().lower().startswith("audience:") and current_id in ids:
                    raw_audiences[current_id] = ln.split(":", 1)[1].strip()

        structure_ok = True
        order_ok = True
        body_checks_ok = True
        found_ids: List[str] = []
        rewritten_audiences: Dict[str, str] = {}
        bodies: Dict[str, str] = {}
        current_id = None
        current_body_lines: List[str] = []
        for ln in rewritten_lines:
            if ln.strip().startswith("### "):
                if current_id:
                    # Save previous body
                    content = "\n".join(current_body_lines)
                    body_text = content.split("Body:", 1)[-1].strip() if "Body:" in content else content.strip()
                    bodies[current_id] = body_text
                    current_body_lines = []
                current_id = ln.strip().replace("### ", "").strip()
                found_ids.append(current_id)
            elif ln.strip().lower().startswith("audience:") and current_id:
                rewritten_audiences[current_id] = ln.split(":", 1)[1].strip()
            else:
                if current_id:
                    current_body_lines.append(ln)
        if current_id:
            content = "\n".join(current_body_lines)
            body_text = content.split("Body:", 1)[-1].strip() if "Body:" in content else content.strip()
            bodies[current_id] = body_text

        order_ok = (found_ids == ids)
        for mid in ids:
            if mid not in rewritten_audiences or mid not in raw_audiences:
                structure_ok = False
                break
            if rewritten_audiences[mid] != raw_audiences[mid]:
                structure_ok = False
                break

        for mid in ids:
            body = bodies.get(mid, "").strip()
            if not body:
                body_checks_ok = False
                break
            n_sent = _count_sentences(body)
            if n_sent < 2 or n_sent > 3:
                body_checks_ok = False
                break
            if _contains_emoji(body):
                body_checks_ok = False
                break
            if _has_slang(body):
                body_checks_ok = False
                break

        scores["rewritten_messages_structure"] = 1.0 if (order_ok and structure_ok and body_checks_ok) else 0.0
    else:
        scores["rewritten_messages_exists"] = 0.0
        scores["rewritten_messages_structure"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()