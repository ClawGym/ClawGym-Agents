import sys
import json
import csv
import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any


PLACEHOLDERS = {"{PROVIDER_NAME}", "{TOTAL_DUE}", "{CLAIM_TABLE}", "{RESPONSE_DEADLINE}"}
ISSUE_ORDER = [
    ("Missing documentation", lambda r: (r.get("missing_docs", "").strip().lower() == "yes")),
    ("Denied", lambda r: (r.get("status", "").strip() == "Denied")),
    ("Pending", lambda r: (r.get("status", "").strip() == "Pending")),
    ("Underpayment", lambda r: _to_decimal(r.get("paid_amount")) is not None and _to_decimal(r.get("allowed_amount")) is not None and _to_decimal(r.get("paid_amount")) < _to_decimal(r.get("allowed_amount"))),
]


def _read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _to_decimal(val: Any) -> Optional[Decimal]:
    try:
        if val is None:
            return None
        s = str(val).strip()
        if s == "":
            return None
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _money_two_dec(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _format_money_two_dec(d: Decimal) -> str:
    return f"{_money_two_dec(d):.2f}"


def _format_money_with_dollar(d: Decimal) -> str:
    return f"${_money_two_dec(d):.2f}"


def _compute_issues(row: Dict[str, str]) -> List[str]:
    issues = []
    for label, predicate in ISSUE_ORDER:
        try:
            if predicate(row):
                issues.append(label)
        except Exception:
            continue
    return issues


def _compute_actionable(claims: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    actionable = []
    for r in claims:
        missing_docs_flag = r.get("missing_docs", "").strip().lower() == "yes"
        status = r.get("status", "").strip()
        paid = _to_decimal(r.get("paid_amount"))
        allowed = _to_decimal(r.get("allowed_amount"))
        underpayment = (paid is not None and allowed is not None and paid < allowed)

        needs_action = missing_docs_flag or status in {"Denied", "Pending"} or underpayment
        if not needs_action:
            continue

        issues = _compute_issues(r)
        reimb = None
        if paid is not None and allowed is not None:
            diff = allowed - paid
            if diff < Decimal("0"):
                diff = Decimal("0")
            reimb = _money_two_dec(diff)

        actionable.append({
            "provider_id": r.get("provider_id", "").strip(),
            "claim_id": r.get("claim_id", "").strip(),
            "patient_id": r.get("patient_id", "").strip(),
            "service_date": r.get("service_date", "").strip(),
            "issues": "; ".join(issues),
            "reimbursement_due": reimb,  # Decimal or None
        })
    return actionable


def _join_provider_names(actionable: List[Dict[str, Any]], providers: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
    joined = []
    for r in actionable:
        pid = r["provider_id"]
        prov = providers.get(pid)
        provider_name = prov.get("provider_name") if prov else None
        rr = dict(r)
        rr["provider_name"] = provider_name if provider_name is not None else ""
        joined.append(rr)
    return joined


def _sort_claims_by_provider_and_claim(claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(claims, key=lambda x: (x.get("provider_id", ""), x.get("claim_id", "")))


def _count_body_words_excluding_placeholders(text: str) -> int:
    if not text:
        return 0
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    body_lines = []
    subject_seen = False
    for ln in lines:
        if not subject_seen:
            if ln.strip() == "":
                continue
            if ln.lstrip().startswith("Subject:"):
                subject_seen = True
                continue
            else:
                subject_seen = True
                body_lines.append(ln)
                continue
        else:
            body_lines.append(ln)
    body_text = "\n".join(body_lines)
    for ph in PLACEHOLDERS:
        body_text = body_text.replace(ph, "")
    words = re.findall(r"\b\w[\w'-]*\b", body_text)
    return len(words)


def _extract_claim_table_lines(message_text: str) -> List[str]:
    lines = [ln.strip() for ln in message_text.splitlines()]
    table_lines = []
    for ln in lines:
        if " | " in ln:
            parts = ln.split(" | ")
            if len(parts) == 5:
                last = parts[-1].strip()
                if re.fullmatch(r"\$\d+(?:\.\d{2})", last) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[2].strip()):
                    table_lines.append(ln)
    return table_lines


def _parse_claim_table_line(line: str) -> Optional[Dict[str, str]]:
    parts = [p.strip() for p in line.split(" | ")]
    if len(parts) != 5:
        return None
    claim_id, patient_id, service_date, issues, amount_str = parts
    if not re.fullmatch(r"\$\d+(?:\.\d{2})", amount_str):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", service_date):
        return None
    return {
        "claim_id": claim_id,
        "patient_id": patient_id,
        "service_date": service_date,
        "issues": issues,
        "amount_str": amount_str,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "claim_actions_file_structure": 0.0,
        "claim_actions_inclusion_and_sorting": 0.0,
        "claim_actions_field_values": 0.0,
        "polished_template_placeholders_and_subject": 0.0,
        "polished_template_body_length": 0.0,
        "polished_template_closing": 0.0,
        "messages_files_presence": 0.0,
        "messages_placeholders_and_deadline": 0.0,
        "messages_claim_tables_correctness": 0.0,
        "messages_total_due_consistency": 0.0,
        "messages_provider_name_inserted": 0.0,
    }

    # Load inputs
    claims_path = workspace / "input" / "claims.csv"
    providers_path = workspace / "input" / "providers.csv"
    notif_template_path = workspace / "input" / "notification_template.txt"

    claims_rows, claims_fields = _read_csv(claims_path)
    providers_rows, providers_fields = _read_csv(providers_path)
    _ = _read_text(notif_template_path)  # not directly graded

    # 2) Validate output/notification_template_polished.txt (independent of inputs)
    polished_path = workspace / "output" / "notification_template_polished.txt"
    polished_text = _read_text(polished_path)
    if polished_text is not None:
        lines = [ln for ln in polished_text.splitlines()]
        first_nonempty = None
        for ln in lines:
            if ln.strip() != "":
                first_nonempty = ln
                break
        subject_ok = first_nonempty is not None and first_nonempty.lstrip().startswith("Subject:")
        placeholders_ok = all(ph in polished_text for ph in PLACEHOLDERS)
        if subject_ok and placeholders_ok:
            scores["polished_template_placeholders_and_subject"] = 1.0

        word_count = _count_body_words_excluding_placeholders(polished_text)
        if word_count <= 120:
            scores["polished_template_body_length"] = 1.0

        closing_tokens = ["Regards", "Sincerely", "Thank you", "Thanks", "Best", "Kind regards", "Respectfully"]
        nonempty_lines = [ln.strip() for ln in lines if ln.strip() != ""]
        tail = nonempty_lines[-5:] if nonempty_lines else []
        closing_found = any(any(tok.lower() in ln.lower() for tok in closing_tokens) for ln in tail)
        if closing_found:
            scores["polished_template_closing"] = 1.0

    # Only proceed with claims/providers dependent checks if inputs parsed
    if claims_rows is not None and providers_rows is not None:
        providers_by_id = {r.get("provider_id", "").strip(): r for r in providers_rows}
        actionable = _compute_actionable(claims_rows)
        actionable_joined = _join_provider_names(actionable, providers_by_id)
        expected_sorted = _sort_claims_by_provider_and_claim(actionable_joined)

        expected_claim_actions_rows: List[Dict[str, str]] = []
        for r in expected_sorted:
            reimb = r["reimbursement_due"]
            reimb_str = _format_money_two_dec(reimb) if isinstance(reimb, Decimal) else ""
            expected_claim_actions_rows.append({
                "provider_id": r["provider_id"],
                "provider_name": r.get("provider_name", ""),
                "claim_id": r["claim_id"],
                "patient_id": r["patient_id"],
                "service_date": r["service_date"],
                "issues": r["issues"],
                "reimbursement_due": reimb_str,
            })

        # 1) Validate output/claim_actions.csv
        out_claims_path = workspace / "output" / "claim_actions.csv"
        out_rows, out_fields = _read_csv(out_claims_path)
        expected_columns = ["provider_id", "provider_name", "claim_id", "patient_id", "service_date", "issues", "reimbursement_due"]
        if out_rows is not None and out_fields is not None and out_fields == expected_columns:
            scores["claim_actions_file_structure"] = 1.0

        if out_rows is not None and out_fields is not None:
            observed_keys = [(r.get("provider_id", ""), r.get("claim_id", "")) for r in out_rows]
            is_sorted = observed_keys == sorted(observed_keys)
            expected_keys = [(r["provider_id"], r["claim_id"]) for r in expected_claim_actions_rows]
            only_expected = set(observed_keys) == set(expected_keys) and len(out_rows) == len(expected_claim_actions_rows)
            if is_sorted and only_expected:
                scores["claim_actions_inclusion_and_sorting"] = 1.0

            all_values_ok = True
            expected_by_key = {(r["provider_id"], r["claim_id"]): r for r in expected_claim_actions_rows}
            for r in out_rows:
                key = (r.get("provider_id", ""), r.get("claim_id", ""))
                exp = expected_by_key.get(key)
                if exp is None:
                    all_values_ok = False
                    break
                if (r.get("provider_name", "") != exp["provider_name"] or
                    r.get("patient_id", "") != exp["patient_id"] or
                    r.get("service_date", "") != exp["service_date"] or
                    (r.get("issues", "") or "") != exp["issues"]):
                    all_values_ok = False
                    break
                rd = r.get("reimbursement_due", "")
                if not re.fullmatch(r"\d+(?:\.\d{2})", rd or ""):
                    all_values_ok = False
                    break
                if rd != exp["reimbursement_due"]:
                    all_values_ok = False
                    break
            if all_values_ok and len(out_rows) == len(expected_claim_actions_rows):
                scores["claim_actions_field_values"] = 1.0

        # 3) Validate per-provider messages
        expected_by_provider: Dict[str, Dict[str, Any]] = {}
        for r in expected_claim_actions_rows:
            pid = r["provider_id"]
            prov = providers_by_id.get(pid, {})
            provider_name = prov.get("provider_name", "")
            reimburse = _to_decimal(r["reimbursement_due"]) or Decimal("0.00")
            line = f'{r["claim_id"]} | {r["patient_id"]} | {r["service_date"]} | {r["issues"]} | ${_format_money_two_dec(reimburse)}'
            if pid not in expected_by_provider:
                expected_by_provider[pid] = {"provider_name": provider_name, "lines": [], "total": Decimal("0.00")}
            expected_by_provider[pid]["lines"].append((r["claim_id"], line, reimburse))
            expected_by_provider[pid]["total"] = expected_by_provider[pid]["total"] + reimburse
        for pid, data in expected_by_provider.items():
            data["lines"] = [line for _, line, _ in sorted(data["lines"], key=lambda t: t[0])]
            data["total"] = _money_two_dec(data["total"])

        expected_providers_with_msgs = set(expected_by_provider.keys())
        messages_dir = workspace / "output" / "messages"
        observed_provider_files = set()
        if messages_dir.exists() and messages_dir.is_dir():
            for p in messages_dir.iterdir():
                if p.is_file() and p.name.endswith("_notice.txt"):
                    prov_id = p.name[:-len("_notice.txt")]
                    observed_provider_files.add(prov_id)

        if observed_provider_files == expected_providers_with_msgs and len(observed_provider_files) == len(expected_providers_with_msgs):
            scores["messages_files_presence"] = 1.0

        placeholders_and_deadlines_ok = True
        claim_tables_ok = True
        totals_ok = True
        provider_name_ok = True

        for pid in expected_providers_with_msgs:
            msg_path = messages_dir / f"{pid}_notice.txt"
            msg_text = _read_text(msg_path)
            if msg_text is None:
                placeholders_and_deadlines_ok = False
                claim_tables_ok = False
                totals_ok = False
                provider_name_ok = False
                continue

            if any(ph in msg_text for ph in PLACEHOLDERS):
                placeholders_and_deadlines_ok = False

            if "10 business days from notice date" not in msg_text:
                placeholders_and_deadlines_ok = False

            exp_provider_name = expected_by_provider[pid]["provider_name"]
            if exp_provider_name and exp_provider_name not in msg_text:
                provider_name_ok = False

            table_lines = _extract_claim_table_lines(msg_text)
            expected_lines = expected_by_provider[pid]["lines"]
            if table_lines != expected_lines:
                claim_tables_ok = False

            parsed_lines = [_parse_claim_table_line(ln) for ln in table_lines]
            if any(pl is None for pl in parsed_lines):
                claim_tables_ok = False
                totals_ok = False
            else:
                sum_amount = Decimal("0.00")
                for pl in parsed_lines:
                    amt = _to_decimal(pl["amount_str"].replace("$", ""))
                    if amt is None:
                        totals_ok = False
                        break
                    sum_amount += amt
                sum_amount = _money_two_dec(sum_amount)
                exp_total = _money_two_dec(expected_by_provider[pid]["total"])
                if sum_amount != exp_total:
                    totals_ok = False
                total_str = _format_money_with_dollar(exp_total)
                msg_text_wo_table = "\n".join([ln for ln in msg_text.splitlines() if ln.strip() not in set(table_lines)])
                if total_str not in msg_text_wo_table:
                    totals_ok = False

        scores["messages_placeholders_and_deadline"] = 1.0 if placeholders_and_deadlines_ok else 0.0
        scores["messages_claim_tables_correctness"] = 1.0 if claim_tables_ok else 0.0
        scores["messages_total_due_consistency"] = 1.0 if totals_ok else 0.0
        scores["messages_provider_name_inserted"] = 1.0 if provider_name_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()