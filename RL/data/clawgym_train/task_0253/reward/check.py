import sys
import json
import csv
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Tuple


def _read_csv_dicts(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            headers = reader.fieldnames or []
        return rows, headers
    except Exception:
        return [], []


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_simple_yaml_kv(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return data
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in s:
            continue
        key, val = s.split(":", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            val = val[1:-1]
        data[key] = val
    return data


def _to_decimal(s: str) -> Decimal:
    try:
        return Decimal(s.strip())
    except Exception:
        try:
            return Decimal(str(float(s)))
        except Exception:
            raise


def _isclose(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(a - b) <= tol
    except Exception:
        return False


def _parse_bool(s: str) -> Any:
    if isinstance(s, bool):
        return s
    val = str(s).strip().lower()
    if val in ("true", "1", "yes", "y"):
        return True
    if val in ("false", "0", "no", "n"):
        return False
    return None


def _compute_expected(workspace: Path) -> Dict[str, Any]:
    inputs = {
        "csv": workspace / "input" / "dividend_transactions_2024.csv",
        "claims": workspace / "input" / "news_claims_2024.json",
        "yaml": workspace / "input" / "recipient.yaml",
    }
    rows, _ = _read_csv_dicts(inputs["csv"])
    claims = _load_json(inputs["claims"])
    recipient = _load_simple_yaml_kv(inputs["yaml"])

    result: Dict[str, Any] = {
        "ok": False,
        "anomalies": [],
        "inconsistent_rows": [],
        "anomaly_symbols_ordered": [],
        "has_any_inconsistent": False,
        "recipient": recipient,
    }

    if not rows or not isinstance(claims, list):
        return result

    per_symbol = {}
    inconsistent_rows: List[Dict[str, Any]] = []
    for r in rows:
        payment_date = r.get("payment_date", "")
        if not payment_date.startswith("2024-"):
            continue
        sym = (r.get("symbol") or "").strip()
        if not sym:
            continue
        try:
            per_share = _to_decimal(r.get("per_share_dividend_usd", "0"))
            shares = _to_decimal(str(r.get("shares_paid", "0")))
            total_amount = _to_decimal(r.get("total_amount_usd", "0"))
        except (InvalidOperation, Exception):
            continue

        expected_total = per_share * shares
        delta = total_amount - expected_total
        if abs(delta) > Decimal("0.01"):
            inconsistent_rows.append({
                "payment_date": payment_date,
                "symbol": sym,
                "per_share_dividend_usd": float(per_share),
                "shares_paid": float(shares),
                "total_amount_usd": float(total_amount),
                "expected_total_usd": float(expected_total),
                "delta_usd": float(delta),
            })

        if sym not in per_symbol:
            per_symbol[sym] = {
                "realized_per_share_sum": Decimal("0"),
                "total_paid_usd": Decimal("0"),
                "num_payouts": 0,
            }
        per_symbol[sym]["realized_per_share_sum"] += per_share
        per_symbol[sym]["total_paid_usd"] += total_amount
        per_symbol[sym]["num_payouts"] += 1

    claims_map: Dict[str, Decimal] = {}
    for c in claims:
        try:
            sym = (c.get("symbol") or "").strip()
            val = c.get("claimed_dividend_per_share_usd_2024_total")
            if sym and val is not None:
                claims_map[sym] = _to_decimal(str(val))
        except Exception:
            continue

    symbols = sorted(set(per_symbol.keys()).intersection(set(claims_map.keys())))
    records = []
    has_inconsistent_by_symbol = {ir["symbol"]: True for ir in inconsistent_rows}
    for sym in symbols:
        realized = per_symbol[sym]["realized_per_share_sum"]
        claimed = claims_map[sym]
        abs_diff = abs(realized - claimed)
        if claimed == Decimal("0"):
            pct_diff = Decimal("0") if abs_diff == Decimal("0") else Decimal("Infinity")
        else:
            pct_diff = abs_diff / claimed
        rec = {
            "symbol": sym,
            "realized_per_share_2024": float(realized),
            "claimed_per_share_2024": float(claimed),
            "abs_diff_per_share": float(abs_diff),
            "pct_diff": float(pct_diff) if pct_diff != Decimal("Infinity") else float("inf"),
            "total_paid_usd": float(per_symbol[sym]["total_paid_usd"]),
            "num_payouts": per_symbol[sym]["num_payouts"],
            "has_inconsistent_payments": bool(has_inconsistent_by_symbol.get(sym, False)),
        }
        records.append(rec)

    anomalies = [r for r in records if (r["pct_diff"] >= 0.15 and r["pct_diff"] != float("inf")) or (r["pct_diff"] == float("inf"))]
    anomalies.sort(key=lambda x: (-x["pct_diff"], -x["abs_diff_per_share"], x["symbol"]))
    for idx, r in enumerate(anomalies, start=1):
        r["rank"] = idx

    result["ok"] = True
    result["anomalies"] = anomalies
    result["anomaly_symbols_ordered"] = [r["symbol"] for r in anomalies]
    result["inconsistent_rows"] = inconsistent_rows
    result["has_any_inconsistent"] = len(inconsistent_rows) > 0
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "consistency_warnings_file_correct": 0.0,
        "anomalies_csv_correct": 0.0,
        "anomalies_json_correct": 0.0,
        "anomalies_csv_json_consistent": 0.0,
        "email_address_and_signature_present": 0.0,
        "email_methodology_summary_present": 0.0,
        "email_anomalies_bullets_present_and_ordered": 0.0,
        "email_references_output_paths": 0.0,
    }

    expected = _compute_expected(workspace)

    out_anom_csv = workspace / "output" / "anomalies.csv"
    out_anom_json = workspace / "output" / "anomalies.json"
    out_warnings_csv = workspace / "output" / "consistency_warnings.csv"
    out_email = workspace / "output" / "draft_email_to_broker.txt"

    try:
        exp_inconsistent = expected["inconsistent_rows"] if expected.get("ok") else []
        rows, headers = _read_csv_dicts(out_warnings_csv)
        expected_header = [
            "payment_date",
            "symbol",
            "per_share_dividend_usd",
            "shares_paid",
            "total_amount_usd",
            "expected_total_usd",
            "delta_usd",
        ]
        if headers == expected_header and expected.get("ok"):
            def key_row(r):
                return (r.get("payment_date", ""), r.get("symbol", ""))

            out_map = {}
            for r in rows:
                k = key_row(r)
                try:
                    out_map[k] = {
                        "payment_date": r.get("payment_date", ""),
                        "symbol": r.get("symbol", ""),
                        "per_share_dividend_usd": float(r.get("per_share_dividend_usd", "nan")),
                        "shares_paid": float(r.get("shares_paid", "nan")),
                        "total_amount_usd": float(r.get("total_amount_usd", "nan")),
                        "expected_total_usd": float(r.get("expected_total_usd", "nan")),
                        "delta_usd": float(r.get("delta_usd", "nan")),
                    }
                except Exception:
                    out_map[k] = None

            exp_map = {}
            for r in exp_inconsistent:
                k = (r["payment_date"], r["symbol"])
                exp_map[k] = r

            if set(out_map.keys()) == set(exp_map.keys()) and None not in out_map.values():
                all_match = True
                for k in out_map:
                    o = out_map[k]
                    e = exp_map[k]
                    if o["payment_date"] != e["payment_date"] or o["symbol"] != e["symbol"]:
                        all_match = False
                        break
                    if not (_isclose(o["per_share_dividend_usd"], e["per_share_dividend_usd"])
                            and _isclose(o["shares_paid"], e["shares_paid"])
                            and _isclose(o["total_amount_usd"], e["total_amount_usd"])
                            and _isclose(o["expected_total_usd"], e["expected_total_usd"])):
                        all_match = False
                        break
                    if not _isclose(abs(o["delta_usd"]), abs(e["delta_usd"])):
                        all_match = False
                        break
                if all_match:
                    scores["consistency_warnings_file_correct"] = 1.0
    except Exception:
        scores["consistency_warnings_file_correct"] = 0.0

    try:
        exp_anom = expected["anomalies"] if expected.get("ok") else []
        rows, headers = _read_csv_dicts(out_anom_csv)
        expected_header = [
            "symbol",
            "realized_per_share_2024",
            "claimed_per_share_2024",
            "abs_diff_per_share",
            "pct_diff",
            "total_paid_usd",
            "num_payouts",
            "has_inconsistent_payments",
            "rank",
        ]
        if headers == expected_header and expected.get("ok"):
            if len(rows) == len(exp_anom):
                all_match = True
                for i, r in enumerate(rows):
                    e = exp_anom[i]
                    try:
                        sym = r.get("symbol", "")
                        if sym != e["symbol"]:
                            all_match = False
                            break
                        if not (_isclose(float(r.get("realized_per_share_2024", "nan")), e["realized_per_share_2024"])
                                and _isclose(float(r.get("claimed_per_share_2024", "nan")), e["claimed_per_share_2024"])
                                and _isclose(float(r.get("abs_diff_per_share", "nan")), e["abs_diff_per_share"])
                                and _isclose(float(r.get("pct_diff", "nan")), e["pct_diff"])
                                and _isclose(float(r.get("total_paid_usd", "nan")), e["total_paid_usd"])):
                            all_match = False
                            break
                        try:
                            num_payouts = int(float(r.get("num_payouts", "nan")))
                        except Exception:
                            all_match = False
                            break
                        if num_payouts != e["num_payouts"]:
                            all_match = False
                            break
                        hicp = _parse_bool(r.get("has_inconsistent_payments", ""))
                        if hicp is None or bool(hicp) != bool(e["has_inconsistent_payments"]):
                            all_match = False
                            break
                        try:
                            rank_val = int(float(r.get("rank", "nan")))
                        except Exception:
                            all_match = False
                            break
                        if rank_val != e["rank"]:
                            all_match = False
                            break
                    except Exception:
                        all_match = False
                        break
                if all_match:
                    scores["anomalies_csv_correct"] = 1.0
    except Exception:
        scores["anomalies_csv_correct"] = 0.0

    try:
        exp_anom = expected["anomalies"] if expected.get("ok") else []
        data = _load_json(out_anom_json)
        if isinstance(data, list) and expected.get("ok"):
            if len(data) == len(exp_anom):
                all_match = True
                for i, obj in enumerate(data):
                    e = exp_anom[i]
                    if not isinstance(obj, dict):
                        all_match = False
                        break
                    try:
                        if obj.get("symbol", "") != e["symbol"]:
                            all_match = False
                            break
                        if not (_isclose(float(obj.get("realized_per_share_2024")), e["realized_per_share_2024"])
                                and _isclose(float(obj.get("claimed_per_share_2024")), e["claimed_per_share_2024"])
                                and _isclose(float(obj.get("abs_diff_per_share")), e["abs_diff_per_share"])
                                and _isclose(float(obj.get("pct_diff")), e["pct_diff"])
                                and _isclose(float(obj.get("total_paid_usd")), e["total_paid_usd"])):
                            all_match = False
                            break
                        if int(obj.get("num_payouts")) != e["num_payouts"]:
                            all_match = False
                            break
                        if bool(obj.get("has_inconsistent_payments")) != bool(e["has_inconsistent_payments"]):
                            all_match = False
                            break
                        if int(obj.get("rank")) != e["rank"]:
                            all_match = False
                            break
                    except Exception:
                        all_match = False
                        break
                if all_match:
                    scores["anomalies_json_correct"] = 1.0
    except Exception:
        scores["anomalies_json_correct"] = 0.0

    try:
        rows_csv, headers_csv = _read_csv_dicts(out_anom_csv)
        data_json = _load_json(out_anom_json)
        if isinstance(data_json, list) and headers_csv and rows_csv:
            if len(rows_csv) == len(data_json):
                consistent = True
                for i in range(len(rows_csv)):
                    rc = rows_csv[i]
                    rj = data_json[i] if isinstance(data_json[i], dict) else {}
                    if rc.get("symbol", "") != rj.get("symbol", ""):
                        consistent = False
                        break
                    try:
                        fields = [
                            "realized_per_share_2024",
                            "claimed_per_share_2024",
                            "abs_diff_per_share",
                            "pct_diff",
                            "total_paid_usd",
                        ]
                        for f in fields:
                            if not _isclose(float(rc.get(f, "nan")), float(rj.get(f))):
                                consistent = False
                                break
                        if not consistent:
                            break
                        if int(float(rc.get("num_payouts", "nan"))) != int(rj.get("num_payouts")):
                            consistent = False
                            break
                        hicp_csv = _parse_bool(rc.get("has_inconsistent_payments", ""))
                        if hicp_csv is None or bool(hicp_csv) != bool(rj.get("has_inconsistent_payments")):
                            consistent = False
                            break
                        if int(float(rc.get("rank", "nan"))) != int(rj.get("rank")):
                            consistent = False
                            break
                    except Exception:
                        consistent = False
                        break
                if consistent:
                    scores["anomalies_csv_json_consistent"] = 1.0
    except Exception:
        scores["anomalies_csv_json_consistent"] = 0.0

    try:
        email_text = out_email.read_text(encoding="utf-8")
    except Exception:
        email_text = None

    recipient = expected.get("recipient", {}) if expected else {}
    to_name = recipient.get("to_name", "")
    to_email = recipient.get("to_email", "")
    user_name = recipient.get("user_name", "")

    if email_text is not None and to_name and to_email and user_name:
        addr_ok = (to_name in email_text) and (to_email in email_text) and (user_name in email_text)
        scores["email_address_and_signature_present"] = 1.0 if addr_ok else 0.0

        has_15 = "15%" in email_text
        has_2024 = "2024" in email_text
        has_realized = "realized" in email_text.lower()
        has_claimed = "claimed" in email_text.lower()
        has_pershare = ("per-share" in email_text.lower()) or ("per share" in email_text.lower())
        meth_ok = has_15 and has_2024 and has_realized and has_claimed and has_pershare
        scores["email_methodology_summary_present"] = 1.0 if meth_ok else 0.0

        bullets = []
        for line in email_text.splitlines():
            ls = line.lstrip()
            if ls.startswith("-") or ls.startswith("*"):
                bullets.append(ls)
        expected_symbols = expected.get("anomaly_symbols_ordered", []) if expected.get("ok") else []
        bullets_for_anom = []
        for b in bullets:
            for sym in expected_symbols:
                if sym in b:
                    bullets_for_anom.append((sym, b))
                    break
        order_ok = [sym for sym, _ in bullets_for_anom] == expected_symbols if expected_symbols else False
        percent_ok = all("%" in b for _, b in bullets_for_anom) if bullets_for_anom else False
        words_ok = all(("claimed" in b.lower() and "realized" in b.lower()) for _, b in bullets_for_anom) if bullets_for_anom else False
        bullets_ok = order_ok and percent_ok and words_ok and len(bullets_for_anom) <= 5 and len(bullets_for_anom) == len(expected_symbols)
        scores["email_anomalies_bullets_present_and_ordered"] = 1.0 if bullets_ok else 0.0

        paths_ok = all(p in email_text for p in [
            "output/anomalies.csv",
            "output/anomalies.json",
            "output/consistency_warnings.csv",
        ])
        inconsistency_note_ok = True
        if expected.get("has_any_inconsistent"):
            inconsistency_note_ok = ("inconsistent" in email_text.lower())
        scores["email_references_output_paths"] = 1.0 if (paths_ok and inconsistency_note_ok) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()