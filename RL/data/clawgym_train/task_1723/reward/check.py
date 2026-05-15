import csv
import json
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            header = reader.fieldnames or []
        return rows, header
    except Exception:
        return None, None


def _is_feb_2025(date_str: str) -> bool:
    return isinstance(date_str, str) and date_str.startswith("2025-02-")


def _to_bool(text: str) -> bool:
    return str(text).strip().upper() in {"TRUE", "1", "YES", "Y", "T"}


def _format_money(v: float) -> str:
    return f"{v:.2f}"


def _compute_expected(workspace: Path) -> Optional[dict]:
    tx_path = workspace / "input" / "transactions.csv"
    pt_path = workspace / "input" / "parenting_time.csv"
    rules_path = workspace / "input" / "split_rules.json"

    tx_rows, tx_header = _safe_load_csv(tx_path)
    pt_rows, _ = _safe_load_csv(pt_path)
    rules = _safe_load_json(rules_path)

    if tx_rows is None or pt_rows is None or rules is None:
        return None

    default_split = rules.get("default_split", {"me": 0.5, "ex": 0.5})
    overrides = rules.get("overrides", {})
    exclude_categories = set(rules.get("exclude_categories", []))

    # Filter eligible transactions for Feb 2025
    eligible = []
    for r in tx_rows:
        date = r.get("date", "")
        category = (r.get("category") or "").strip()
        child_rel = _to_bool(r.get("child_related", "FALSE"))
        payer = (r.get("payer") or "").strip()
        try:
            amount = float(r.get("amount", "0").strip())
        except Exception:
            continue
        if not _is_feb_2025(date):
            continue
        if not child_rel:
            continue
        if category in exclude_categories:
            continue

        split = overrides.get(category, default_split)
        me_frac = float(split.get("me", 0.5))
        ex_frac = float(split.get("ex", 0.5))
        me_share = round(amount * me_frac + 1e-9, 2)
        ex_share = round(amount * ex_frac + 1e-9, 2)

        # Determine reimbursement
        payer_norm = payer.strip().lower()
        owed_by = ""
        owed_to = ""
        owed_amount = 0.0
        if payer_norm == "me":
            if amount > me_share:
                owed_by = "ex"
                owed_to = "me"
                owed_amount = round(amount - me_share + 1e-9, 2)
        elif payer_norm == "ex":
            if amount > ex_share:
                owed_by = "me"
                owed_to = "ex"
                owed_amount = round(amount - ex_share + 1e-9, 2)
        else:
            # Unknown payer label; skip reimbursement line but keep for expense summaries
            owed_by = ""
            owed_to = ""
            owed_amount = 0.0

        eligible.append({
            "date": date,
            "description": r.get("description", "").strip(),
            "category": category,
            "amount": round(amount + 1e-9, 2),
            "payer": payer,
            "me_share": me_share,
            "ex_share": ex_share,
            "owed_by": owed_by,
            "owed_to": owed_to,
            "owed_amount": owed_amount,
        })

    # Reimbursements list (owed_amount > 0), sorted by owed_amount desc, tie-break by date asc
    reimbursements = [e for e in eligible if e["owed_amount"] > 0]
    reimbursements_sorted = sorted(reimbursements, key=lambda x: (-x["owed_amount"], x["date"]))

    # Expense totals by category and overall
    category_totals: Dict[str, float] = {}
    overall_total = 0.0
    for e in eligible:
        cat = e["category"]
        category_totals[cat] = category_totals.get(cat, 0.0) + e["amount"]
        overall_total += e["amount"]
    # Round category totals to 2 decimals for reporting
    category_totals = {k: round(v + 1e-9, 2) for k, v in category_totals.items()}
    overall_total = round(overall_total + 1e-9, 2)

    # Top 3 largest eligible expenses by absolute amount; tie-break date asc
    top3 = sorted(eligible, key=lambda x: (-abs(x["amount"]), x["date"]))[:3]

    # Custody counts for Feb 2025
    me_nights = 0
    ex_nights = 0
    for r in pt_rows or []:
        date = r.get("date", "")
        who = (r.get("overnight_with") or "").strip()
        if not _is_feb_2025(date):
            continue
        if who.lower() == "me":
            me_nights += 1
        elif who.lower() == "ex":
            ex_nights += 1

    # Reimbursement totals summary
    me_to_ex = round(sum(e["owed_amount"] for e in reimbursements if e["owed_by"] == "me") + 1e-9, 2)
    ex_to_me = round(sum(e["owed_amount"] for e in reimbursements if e["owed_by"] == "ex") + 1e-9, 2)
    net = round(ex_to_me - me_to_ex + 1e-9, 2)

    exp = {
        "eligible": eligible,
        "reimbursements_sorted": reimbursements_sorted,
        "category_totals": category_totals,
        "overall_total": overall_total,
        "top3": top3,
        "me_nights": me_nights,
        "ex_nights": ex_nights,
        "me_to_ex": me_to_ex,
        "ex_to_me": ex_to_me,
        "net": net,
    }
    return exp


def _find_line_with_all_tokens(text: str, tokens: List[str]) -> Optional[int]:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        lc = line.lower()
        ok = True
        for t in tokens:
            if t.lower() not in lc:
                ok = False
                break
        if ok:
            return idx
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "reimbursements_csv_exists_and_schema": 0.0,
        "reimbursements_csv_content_correct": 0.0,
        "monthly_report_exists": 0.0,
        "monthly_report_sections_present": 0.0,
        "monthly_report_custody_summary_correct": 0.0,
        "monthly_report_expense_summary_correct": 0.0,
        "monthly_report_top3_correct_and_ranked": 0.0,
        "monthly_report_reimbursement_summary_correct": 0.0,
        "email_to_ex_exists": 0.0,
        "email_to_ex_has_subject": 0.0,
        "email_to_ex_custody_summary_present": 0.0,
        "email_to_ex_reimbursement_totals_and_net_correct": 0.0,
        "email_to_ex_references_csv_attachment": 0.0,
        "email_to_mediator_exists": 0.0,
        "email_to_mediator_has_subject": 0.0,
        "email_to_mediator_custody_summary_present": 0.0,
        "email_to_mediator_category_totals_present": 0.0,
        "email_to_mediator_net_reimbursement_present": 0.0,
    }

    expected = _compute_expected(workspace)
    # If expected is None (missing inputs), we cannot compute; all checks remain 0.0
    # Proceed with checks that depend on expected only if available.
    # Paths
    reimbursements_path = workspace / "output" / "reimbursements_2025-02.csv"
    report_path = workspace / "output" / "monthly_report_2025-02.md"
    email_ex_path = workspace / "output" / "email_to_ex_2025-02.txt"
    email_mediator_path = workspace / "output" / "email_to_mediator_2025-02.txt"

    # Check reimbursements CSV: existence and schema
    rows, header = _safe_load_csv(reimbursements_path)
    required_header = ["date", "description", "category", "amount", "payer", "me_share", "ex_share", "owed_by", "owed_to", "owed_amount"]
    if rows is not None and header == required_header:
        scores["reimbursements_csv_exists_and_schema"] = 1.0

    # Check reimbursements CSV content correctness (requires expected)
    if rows is not None and header == required_header and expected is not None:
        # Build expected rows (as strings for comparison) in sorted order
        exp_rows = []
        for e in expected["reimbursements_sorted"]:
            exp_rows.append({
                "date": e["date"],
                "description": e["description"],
                "category": e["category"],
                "amount": _format_money(e["amount"]),
                "payer": e["payer"],
                "me_share": _format_money(e["me_share"]),
                "ex_share": _format_money(e["ex_share"]),
                "owed_by": e["owed_by"],
                "owed_to": e["owed_to"],
                "owed_amount": _format_money(e["owed_amount"]),
            })
        # Convert actual rows to normalized strings
        def _norm_row(r: Dict[str, str]) -> Dict[str, str]:
            return {
                "date": (r.get("date") or "").strip(),
                "description": (r.get("description") or "").strip(),
                "category": (r.get("category") or "").strip(),
                "amount": _format_money(float((r.get("amount") or "0").strip())),
                "payer": (r.get("payer") or "").strip(),
                "me_share": _format_money(float((r.get("me_share") or "0").strip())),
                "ex_share": _format_money(float((r.get("ex_share") or "0").strip())),
                "owed_by": (r.get("owed_by") or "").strip(),
                "owed_to": (r.get("owed_to") or "").strip(),
                "owed_amount": _format_money(float((r.get("owed_amount") or "0").strip())),
            }

        actual_norm = []
        try:
            for r in rows:
                actual_norm.append(_norm_row(r))
        except Exception:
            actual_norm = []

        if len(actual_norm) == len(exp_rows) == len(expected["reimbursements_sorted"]) and all(
            a == b for a, b in zip(actual_norm, exp_rows)
        ):
            scores["reimbursements_csv_content_correct"] = 1.0
        else:
            scores["reimbursements_csv_content_correct"] = 0.0

    # Monthly report checks
    report_text = _read_text(report_path)
    if report_text is not None:
        scores["monthly_report_exists"] = 1.0
        lower = report_text.lower()
        has_header_month = "february 2025" in lower
        has_custody = "custody" in lower
        has_expense = "expense summary" in lower
        has_top3 = "top 3" in lower or "top three" in lower
        has_reimb = "reimbursement summary" in lower or "reimbursements" in lower
        if has_header_month and has_custody and has_expense and has_top3 and has_reimb:
            scores["monthly_report_sections_present"] = 1.0

        if expected is not None:
            # Custody summary correctness: look for 'overnight' and two '14'
            cust_ok = ("overnight" in lower) and (lower.count("14") >= 2) and has_custody
            if expected["me_nights"] == 14 and expected["ex_nights"] == 14 and cust_ok:
                scores["monthly_report_custody_summary_correct"] = 1.0

            # Expense summary by category and overall
            # For each category, there should be a line containing the category and its total formatted
            lines = report_text.splitlines()
            cat_matches = 0
            total_cats = len(expected["category_totals"])
            for cat, tot in expected["category_totals"].items():
                amt = _format_money(tot)
                found = False
                for line in lines:
                    if cat.lower() in line.lower() and amt in line:
                        found = True
                        break
                if found:
                    cat_matches += 1
            # overall total presence
            overall_str = _format_money(expected["overall_total"])
            overall_found = overall_str in report_text
            if total_cats > 0:
                scores["monthly_report_expense_summary_correct"] = (cat_matches / total_cats) * (1.0 if overall_found else 0.0)

            # Top 3 expenses present and in ranked order
            top3_items = expected["top3"]
            # Build tokens per item: date, description, category, amount
            indices: List[int] = []
            for item in top3_items:
                tokens = [item["date"], item["description"], item["category"], _format_money(item["amount"])]
                idx = _find_line_with_all_tokens(report_text, tokens)
                if idx is None:
                    indices = []
                    break
                indices.append(idx)
            if indices and indices == sorted(indices):
                scores["monthly_report_top3_correct_and_ranked"] = 1.0

            # Reimbursement summary totals present
            need1 = _format_money(expected["me_to_ex"])
            need2 = _format_money(expected["ex_to_me"])
            need3 = _format_money(expected["net"])
            if need1 in report_text and need2 in report_text and need3 in report_text and has_reimb:
                scores["monthly_report_reimbursement_summary_correct"] = 1.0

    # Email to ex checks
    email_ex_text = _read_text(email_ex_path)
    if email_ex_text is not None:
        scores["email_to_ex_exists"] = 1.0
        lines = [ln.strip() for ln in email_ex_text.splitlines() if ln.strip() != ""]
        has_subject = any(ln.lower().startswith("subject:") for ln in lines)
        scores["email_to_ex_has_subject"] = 1.0 if has_subject else 0.0
        lower = email_ex_text.lower()
        # Custody summary presence
        custody_ok = ("overnight" in lower) and (lower.count("14") >= 2) and ("february 2025" in lower)
        scores["email_to_ex_custody_summary_present"] = 1.0 if custody_ok else 0.0
        # Reimbursement totals and net
        if expected is not None:
            need1 = _format_money(expected["me_to_ex"])
            need2 = _format_money(expected["ex_to_me"])
            need3 = _format_money(expected["net"])
            reimb_ok = (need1 in email_ex_text) and (need2 in email_ex_text) and (need3 in email_ex_text)
            scores["email_to_ex_reimbursement_totals_and_net_correct"] = 1.0 if reimb_ok else 0.0
        # Reference to CSV attachment
        ref_ok = ("reimbursements_2025-02.csv".lower() in lower) or (("attached" in lower) and ("reimburse" in lower))
        scores["email_to_ex_references_csv_attachment"] = 1.0 if ref_ok else 0.0

    # Email to mediator checks
    email_med_text = _read_text(email_mediator_path)
    if email_med_text is not None:
        scores["email_to_mediator_exists"] = 1.0
        lines = [ln.strip() for ln in email_med_text.splitlines() if ln.strip() != ""]
        has_subject = any(ln.lower().startswith("subject:") for ln in lines)
        scores["email_to_mediator_has_subject"] = 1.0 if has_subject else 0.0
        lower = email_med_text.lower()
        custody_ok = ("overnight" in lower) and (lower.count("14") >= 2) and ("february 2025" in lower)
        scores["email_to_mediator_custody_summary_present"] = 1.0 if custody_ok else 0.0
        if expected is not None:
            # Category totals presence (fractional score)
            cat_matches = 0
            total_cats = len(expected["category_totals"])
            for cat, tot in expected["category_totals"].items():
                amt = _format_money(tot)
                found = False
                for ln in lines:
                    if cat.lower() in ln.lower() and amt in ln:
                        found = True
                        break
                if found:
                    cat_matches += 1
            scores["email_to_mediator_category_totals_present"] = (cat_matches / total_cats) if total_cats > 0 else 0.0

            # Net reimbursement presence with context
            need_net = _format_money(expected["net"])
            net_ok = (need_net in email_med_text) and (("net" in lower) or ("balance" in lower) or ("position" in lower))
            scores["email_to_mediator_net_reimbursement_present"] = 1.0 if net_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()