import json
import csv
import sys
import re
import math
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from collections import defaultdict, Counter


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _parse_float(s: Any) -> Optional[float]:
    try:
        if isinstance(s, (int, float)):
            return float(s)
        if isinstance(s, str):
            return float(s.strip())
        return None
    except Exception:
        return None


def _month_from_timestamp(ts: str) -> Optional[str]:
    if not isinstance(ts, str) or len(ts) < 7:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-", ts)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}"


def _float_close(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) <= tol


def _sentence_count(text: str) -> int:
    if not text:
        return 0
    stripped = text.strip()
    sentences = re.findall(r'[^.!?]+[.!?]', stripped, flags=re.MULTILINE)
    if not sentences:
        sentences = [line for line in stripped.splitlines() if line.strip()]
    sentences = [s.strip() for s in sentences if s.strip()]
    return len(sentences)


def _transactions_from_inputs(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    input_dir = workspace / "input"
    if not input_dir.exists():
        return None
    files = sorted(input_dir.glob("transactions_*.csv"))
    if not files:
        return None
    all_rows: List[Dict[str, Any]] = []
    for f in files:
        rows = _safe_read_csv_dicts(f)
        if rows is None:
            return None
        for r in rows:
            if not all(k in r for k in ["transaction_id", "user_id", "timestamp", "amount"]):
                return None
            amt = _parse_float(r.get("amount"))
            if amt is None:
                return None
            r["amount"] = amt
        all_rows.extend(rows)
    return all_rows


def _expected_aggregates(rows: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    grouped: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    for r in rows:
        uid = r["user_id"]
        ts = r["timestamp"]
        amt = r["amount"]
        month = _month_from_timestamp(ts)
        if month is None:
            continue
        grouped[(uid, month)].append(amt)
    result: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for (uid, month), amts in grouped.items():
        total = sum(amts)
        mean = total / len(amts) if amts else 0.0
        result[(uid, month)] = {
            "user_id": uid,
            "month": month,
            "total_amount": total,
            "mean_amount": mean,
            "txn_count": len(amts),
        }
    return result


def _expected_anomalies(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    id_counts = Counter([r["transaction_id"] for r in rows])
    dup_ids = {tid for tid, c in id_counts.items() if c > 1}
    duplicates = [
        {
            "transaction_id": r["transaction_id"],
            "user_id": r["user_id"],
            "amount": r["amount"],
            "timestamp": r["timestamp"],
        }
        for r in rows
        if r["transaction_id"] in dup_ids
    ]
    negative = [
        {
            "transaction_id": r["transaction_id"],
            "user_id": r["user_id"],
            "amount": r["amount"],
            "timestamp": r["timestamp"],
        }
        for r in rows
        if r["amount"] < 0
    ]
    high_value = [
        {
            "transaction_id": r["transaction_id"],
            "user_id": r["user_id"],
            "amount": r["amount"],
            "timestamp": r["timestamp"],
        }
        for r in rows
        if r["amount"] >= 3000
    ]
    return {
        "duplicate_transaction_ids": duplicates,
        "negative_amounts": negative,
        "high_value_transactions": high_value,
    }


def _run_python_script(script_path: Path, cwd: Path) -> Tuple[bool, str, str, int]:
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            text=True,
        )
        ok = proc.returncode == 0
        return ok, proc.stdout, proc.stderr, proc.returncode
    except Exception as e:
        return False, "", str(e), -1


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "error_message_captured": 0.0,
        "error_explanation_sentences": 0.0,
        "script_runs_successfully": 0.0,
        "aggregates_schema": 0.0,
        "month_format_correct": 0.0,
        "aggregates_values_correct": 0.0,
        "anomaly_report_schema": 0.0,
        "anomaly_report_values_correct": 0.0,
        "concise_update_sentence_count": 0.0,
        "concise_update_includes_metrics": 0.0,
    }

    rows = _transactions_from_inputs(workspace)
    expected_agg: Dict[Tuple[str, str], Dict[str, Any]] = {}
    expected_anoms: Dict[str, List[Dict[str, Any]]] = {}
    if rows is not None:
        expected_agg = _expected_aggregates(rows)
        expected_anoms = _expected_anomalies(rows)

    ea_path = workspace / "output" / "error_analysis.txt"
    ea_text = _read_text_safe(ea_path)
    if ea_text:
        lower = ea_text.lower()
        has_usecols_error = ("usecols do not match columns" in lower) or ("usecols" in lower and "match" in lower and "column" in lower)
        mentions_missing_cols = ("date" in lower and "amount_usd" in lower)
        if has_usecols_error or mentions_missing_cols:
            scores["error_message_captured"] = 1.0
        lines = [ln.strip() for ln in ea_text.splitlines() if ln.strip()]
        if len(lines) >= 2:
            explanation = "\n".join(lines[1:])
            sc = _sentence_count(explanation)
            if 1 <= sc <= 3:
                scores["error_explanation_sentences"] = 1.0

    script_path = workspace / "scripts" / "aggregate_spend.py"
    if script_path.exists():
        ok, _out, _err, _rc = _run_python_script(script_path, workspace)
        if ok:
            scores["script_runs_successfully"] = 1.0

    agg_path = workspace / "output" / "aggregates.csv"
    agg_rows = _safe_read_csv_dicts(agg_path) if agg_path.exists() else None
    if agg_rows is not None and isinstance(agg_rows, list):
        try:
            with agg_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None
        expected_header = ["user_id", "month", "total_amount", "mean_amount", "txn_count"]
        if header == expected_header:
            scores["aggregates_schema"] = 1.0

        all_months_ok = True
        for r in agg_rows:
            m = r.get("month")
            if not isinstance(m, str) or not re.fullmatch(r"\d{4}-\d{2}", m or ""):
                all_months_ok = False
                break
        if all_months_ok and agg_rows:
            scores["month_format_correct"] = 1.0

        produced: Dict[Tuple[str, str], Dict[str, Any]] = {}
        parse_ok = True
        for r in agg_rows:
            uid = r.get("user_id")
            mon = r.get("month")
            ta = _parse_float(r.get("total_amount"))
            ma = _parse_float(r.get("mean_amount"))
            tc = r.get("txn_count")
            try:
                tc_int = int(float(tc)) if isinstance(tc, str) else int(tc)
            except Exception:
                parse_ok = False
                break
            if uid is None or mon is None or ta is None or ma is None:
                parse_ok = False
                break
            produced[(uid, mon)] = {
                "total_amount": ta,
                "mean_amount": ma,
                "txn_count": tc_int,
            }
        if parse_ok and rows is not None:
            exp_keys = set(expected_agg.keys())
            prod_keys = set(produced.keys())
            if exp_keys == prod_keys and len(exp_keys) == len(agg_rows):
                vals_ok = True
                for key in exp_keys:
                    exp = expected_agg[key]
                    prod = produced[key]
                    if not _float_close(exp["total_amount"], prod["total_amount"]):
                        vals_ok = False
                        break
                    if not _float_close(exp["mean_amount"], prod["mean_amount"]):
                        vals_ok = False
                        break
                    if int(exp["txn_count"]) != int(prod["txn_count"]):
                        vals_ok = False
                        break
                if vals_ok:
                    scores["aggregates_values_correct"] = 1.0

    anom_path = workspace / "output" / "anomaly_report.json"
    anom = _safe_load_json(anom_path) if anom_path.exists() else None
    if isinstance(anom, dict):
        keys = set(anom.keys())
        required_keys = {"duplicate_transaction_ids", "negative_amounts", "high_value_transactions"}
        if required_keys.issubset(keys):
            lists_ok = True
            fields_ok = True
            for k in required_keys:
                val = anom.get(k)
                if not isinstance(val, list):
                    lists_ok = False
                    break
                for rec in val:
                    if not isinstance(rec, dict):
                        fields_ok = False
                        break
                    for fk in ["transaction_id", "user_id", "amount", "timestamp"]:
                        if fk not in rec:
                            fields_ok = False
                            break
                    if not fields_ok:
                        break
                if not fields_ok:
                    break
            if lists_ok and fields_ok:
                scores["anomaly_report_schema"] = 1.0

        if rows is not None and isinstance(anom.get("duplicate_transaction_ids"), list):
            def rec_key(rec: Dict[str, Any]) -> Tuple[str, str, float, str]:
                tid = str(rec.get("transaction_id"))
                uid = str(rec.get("user_id"))
                amt = rec.get("amount")
                amt_f = _parse_float(amt)
                ts = str(rec.get("timestamp"))
                return (tid, uid, amt_f if amt_f is not None else math.nan, ts)

            exp_dup_set = set(rec_key(r) for r in expected_anoms["duplicate_transaction_ids"])
            exp_neg_set = set(rec_key(r) for r in expected_anoms["negative_amounts"])
            exp_hi_set = set(rec_key(r) for r in expected_anoms["high_value_transactions"])

            prod_dup_set = set(rec_key(r) for r in anom.get("duplicate_transaction_ids", []))
            prod_neg_set = set(rec_key(r) for r in anom.get("negative_amounts", []))
            prod_hi_set = set(rec_key(r) for r in anom.get("high_value_transactions", []))

            if exp_dup_set == prod_dup_set and exp_neg_set == prod_neg_set and exp_hi_set == prod_hi_set:
                scores["anomaly_report_values_correct"] = 1.0

    update_path = workspace / "output" / "concise_update.txt"
    upd_text = _read_text_safe(update_path)
    if upd_text:
        sc = _sentence_count(upd_text)
        if 3 <= sc <= 5:
            scores["concise_update_sentence_count"] = 1.0

        if rows is not None and expected_anoms:
            total_transactions = len(rows)
            unique_users_count = len({r["user_id"] for r in rows})
            dup_count = len(expected_anoms["duplicate_transaction_ids"])
            neg_count = len(expected_anoms["negative_amounts"])
            high_count = len(expected_anoms["high_value_transactions"])

            def contains_number(text: str, n: int) -> bool:
                pattern = r"\b" + re.escape(str(n)) + r"\b"
                return re.search(pattern, text) is not None

            if (contains_number(upd_text, total_transactions)
                and contains_number(upd_text, unique_users_count)
                and contains_number(upd_text, dup_count)
                and contains_number(upd_text, neg_count)
                and contains_number(upd_text, high_count)):
                scores["concise_update_includes_metrics"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()