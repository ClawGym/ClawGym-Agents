import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import importlib.util


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_committee_tags_yaml(path: Path) -> Optional[Dict[str, str]]:
    # Minimal YAML parser for the provided structure
    # Expects:
    # committees:
    #   KEY: VALUE
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None
    committees: Dict[str, str] = {}
    in_committees = False
    for raw in lines:
        line = raw.split("#", 1)[0].rstrip("\n")
        if not line.strip():
            continue
        if not in_committees:
            if line.strip() == "committees:":
                in_committees = True
            continue
        else:
            # Expect two-space indented "KEY: VALUE"
            if not line.startswith("  "):
                # End of committees block
                break
            stripped = line.strip()
            if ":" not in stripped:
                continue
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = v.strip()
            # remove possible quotes
            if v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) >= 2:
                v = v[1:-1]
            committees[k] = v
    return committees if committees else {}


def _import_rates_module(path: Path):
    try:
        spec = importlib.util.spec_from_file_location("rates_config_module", str(path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        # Validate presence of expected function/consts
        if not hasattr(module, "expected_fee"):
            return None
        return module
    except Exception:
        return None


def _to_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _to_int(x: Any) -> Optional[int]:
    try:
        # Some CSV fields might be float strings but should be ints for counts
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return None
        return int(round(f))
    except Exception:
        return None


def _parse_bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    s = str(x).strip().lower()
    return s in {"true", "t", "1", "yes", "y"}


def _round2(x: float) -> float:
    return float(f"{round(x + 0.0000001, 2):.2f}")


def _compare_num(expected: float, actual: Any, tol: float = 0.01) -> bool:
    try:
        a = float(actual)
        return abs(a - expected) <= tol
    except Exception:
        return False


def _median(values: List[float]) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    arr = sorted(values)
    mid = n // 2
    if n % 2 == 1:
        return _round2(arr[mid])
    else:
        return _round2((arr[mid - 1] + arr[mid]) / 2.0)


def _month_from_date(d: str) -> Optional[str]:
    if not isinstance(d, str):
        return None
    d = d.strip()
    if len(d) >= 7:
        return d[:7]
    return None


def _compute_expected(workspace: Path) -> Dict[str, Any]:
    """
    Returns a dict with keys:
      ok, rows, committees_map, rates_module, expected structures:
        overall, by_platform, by_ideology, months_map, by_county_map,
        anomalies_list, unmapped_committees_map
    """
    result: Dict[str, Any] = {
        "ok": False,
        "rows": [],
        "committees_map": None,
        "rates_module": None,
        "overall": None,
        "by_platform": None,
        "by_ideology": None,
        "months_map": None,
        "by_county_map": None,
        "anomalies_list": None,
        "unmapped_committees_map": None,
    }
    tx_path = workspace / "input" / "transactions.csv"
    tx_rows = _read_csv_dicts(tx_path)
    if tx_rows is None:
        return result

    committees_map = _load_committee_tags_yaml(workspace / "config" / "committee_tags.yaml")
    rates_module = _import_rates_module(workspace / "config" / "rates.py")
    result["committees_map"] = committees_map
    result["rates_module"] = rates_module

    # Filter rows
    filtered: List[Dict[str, Any]] = []
    for r in tx_rows:
        if r.get("donor_state") != "IN":
            continue
        if r.get("status") != "Completed":
            continue
        amt = _to_float(r.get("amount"))
        fee = _to_float(r.get("payment_processor_fee"))
        if amt is None or fee is None:
            continue
        is_refund = _parse_bool(r.get("is_refund"))
        # Enforce refund negativity per requirement
        if is_refund and amt > 0:
            amt = -amt
        # Keep other signs as-is
        entry = {
            "transaction_id": r.get("transaction_id"),
            "date": r.get("date"),
            "month": _month_from_date(r.get("date", "")),
            "donor_id": r.get("donor_id"),
            "donor_county": r.get("donor_county"),
            "amount": amt,
            "source": r.get("source"),
            "recipient_committee_id": r.get("recipient_committee_id"),
            "recipient_committee_name": r.get("recipient_committee_name"),
            "is_refund": is_refund,
            "fee": fee,
        }
        filtered.append(entry)

    result["rows"] = filtered

    # Overall
    gross = _round2(sum(x["amount"] for x in filtered))
    fees = _round2(sum(x["fee"] for x in filtered))
    net = _round2(gross - fees)
    txns = len(filtered)
    unique_donors = len({x["donor_id"] for x in filtered})
    overall = {
        "gross": gross,
        "fees": fees,
        "net": net,
        "txns": txns,
        "unique_donors": unique_donors,
    }
    result["overall"] = overall

    # By platform
    platforms = ["ActBlue", "WinRed"]
    by_platform: Dict[str, Dict[str, Any]] = {}
    for p in platforms:
        sub = [x for x in filtered if x.get("source") == p]
        g = _round2(sum(x["amount"] for x in sub))
        f = _round2(sum(x["fee"] for x in sub))
        n = _round2(g - f)
        c = len(sub)
        by_platform[p] = {
            "gross": g,
            "fees": f,
            "net": n,
            "txns": c,
        }
    result["by_platform"] = by_platform

    # By ideology
    ideologies = ["progressive", "conservative", "nonpartisan", "unmapped"]
    by_ideology: Dict[str, Dict[str, Any]] = {k: {"amounts": [], "fees": 0.0, "txns": 0} for k in ideologies}
    for x in filtered:
        cid = x.get("recipient_committee_id")
        bucket = "unmapped"
        if isinstance(committees_map, dict) and cid in committees_map:
            bucket = committees_map[cid]
            if bucket not in ["progressive", "conservative", "nonpartisan"]:
                # If invalid label, treat as unmapped
                bucket = "unmapped"
        d = by_ideology[bucket]
        d["amounts"].append(x["amount"])
        d["fees"] = d["fees"] + x["fee"]
        d["txns"] = d["txns"] + 1

    out_by_ideology: Dict[str, Dict[str, Any]] = {}
    for key in ideologies:
        d = by_ideology[key]
        g = _round2(sum(d["amounts"]))
        f = _round2(d["fees"])
        n = _round2(g - f)
        c = int(d["txns"])
        avg = _round2(sum(d["amounts"]) / c) if c > 0 else 0.0
        med = _median(d["amounts"])
        out_by_ideology[key] = {
            "gross": g,
            "fees": f,
            "net": n,
            "txns": c,
            "average_donation": avg,
            "median_donation": med,
        }
    result["by_ideology"] = out_by_ideology

    # Months
    months_map: Dict[str, Dict[str, Any]] = {}
    for x in filtered:
        m = x.get("month")
        if not m:
            continue
        if m not in months_map:
            months_map[m] = {"gross": 0.0, "fees": 0.0, "txns": 0}
        months_map[m]["gross"] += x["amount"]
        months_map[m]["fees"] += x["fee"]
        months_map[m]["txns"] += 1
    for m in list(months_map.keys()):
        months_map[m]["gross"] = _round2(months_map[m]["gross"])
        months_map[m]["fees"] = _round2(months_map[m]["fees"])
        months_map[m]["net"] = _round2(months_map[m]["gross"] - months_map[m]["fees"])
    result["months_map"] = months_map

    # By county
    by_county_map: Dict[str, Dict[str, Any]] = {}
    for x in filtered:
        cty = x.get("donor_county") or ""
        if cty not in by_county_map:
            by_county_map[cty] = {"donors": set(), "txns": 0, "gross": 0.0, "fees": 0.0}
        d = by_county_map[cty]
        d["donors"].add(x.get("donor_id"))
        d["txns"] += 1
        d["gross"] += x["amount"]
        d["fees"] += x["fee"]
    # finalize rounding
    for cty in list(by_county_map.keys()):
        d = by_county_map[cty]
        d["unique_donors"] = len(d["donors"])
        d["txn_count"] = d["txns"]
        d["gross_amount"] = _round2(d["gross"])
        d["total_fees"] = _round2(d["fees"])
        d["net_amount"] = _round2(d["gross_amount"] - d["total_fees"])
        # cleanup
        for k in ["donors", "txns", "gross", "fees"]:
            d.pop(k, None)
    result["by_county_map"] = by_county_map

    # Fee anomalies
    anomalies_list: Optional[List[Dict[str, Any]]] = None
    if rates_module is not None:
        anomalies: List[Dict[str, Any]] = []
        for x in filtered:
            try:
                exp_fee = float(rates_module.expected_fee(float(x["amount"]), str(x["source"])))
            except Exception:
                # If formula fails, skip anomaly computation
                anomalies = []
                anomalies_list = None
                break
            deviation = exp_fee - x["fee"]
            if abs(deviation) > 0.02:
                anomalies.append({
                    "transaction_id": x["transaction_id"],
                    "source": x["source"],
                    "amount": _round2(x["amount"]),
                    "expected_fee": _round2(exp_fee),
                    "recorded_fee": _round2(x["fee"]),
                    "deviation": _round2(deviation),
                })
        if anomalies_list is None:
            anomalies_list = anomalies
    result["anomalies_list"] = anomalies_list

    # Unmapped committees
    unmapped_committees_map: Optional[Dict[Tuple[str, str], Dict[str, Any]]] = None
    if isinstance(committees_map, dict):
        umap: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for x in filtered:
            cid = x.get("recipient_committee_id")
            cname = x.get("recipient_committee_name")
            if cid not in committees_map:
                key = (cid, cname)
                if key not in umap:
                    umap[key] = {"txn_count": 0, "gross_amount": 0.0}
                umap[key]["txn_count"] += 1
                umap[key]["gross_amount"] += x["amount"]
        # round gross
        for k in list(umap.keys()):
            umap[k]["gross_amount"] = _round2(umap[k]["gross_amount"])
        unmapped_committees_map = umap
    result["unmapped_committees_map"] = unmapped_committees_map

    result["ok"] = True
    return result


def _check_summary_json(workspace: Path, expected: Dict[str, Any]) -> Tuple[float, float, float, float, float]:
    """
    Returns tuple of scores for:
      (summary_json_present_and_structure,
       summary_overall_correct,
       summary_by_ideology_correct,
       summary_by_platform_correct,
       summary_months_correct)
    """
    path = workspace / "output" / "summary.json"
    data = _load_json(path)
    if not isinstance(data, dict):
        return (0.0, 0.0, 0.0, 0.0, 0.0)

    # Structure check
    keys_required = {"overall", "by_ideology", "by_platform", "months"}
    has_notes_ok = True
    if "notes" in data and not isinstance(data["notes"], str):
        has_notes_ok = False
    structure_ok = keys_required.issubset(set(data.keys())) and has_notes_ok
    str_score = 1.0 if structure_ok else 0.0

    overall_score = 0.0
    ideology_score = 0.0
    platform_score = 0.0
    months_score = 0.0

    # Overall check
    exp_overall = expected.get("overall")
    if structure_ok and isinstance(data.get("overall"), dict) and isinstance(exp_overall, dict):
        ov = data["overall"]
        ok = True
        for k in ["gross", "fees", "net"]:
            ok = ok and _compare_num(exp_overall[k], ov.get(k), tol=0.01)
        # txns and unique_donors numeric ints (allow floats that equal int)
        ok = ok and (_to_int(ov.get("txns")) == exp_overall["txns"])
        ok = ok and (_to_int(ov.get("unique_donors")) == exp_overall["unique_donors"])
        overall_score = 1.0 if ok else 0.0

    # By ideology check
    exp_by_ideology = expected.get("by_ideology")
    if structure_ok and isinstance(data.get("by_ideology"), dict) and isinstance(exp_by_ideology, dict):
        bi = data["by_ideology"]
        required_keys = {"progressive", "conservative", "nonpartisan", "unmapped"}
        # Require exactly these keys
        bi_keys = set(bi.keys())
        if bi_keys == required_keys:
            ok = True
            for cat in ["progressive", "conservative", "nonpartisan", "unmapped"]:
                val = bi.get(cat)
                exp_val = exp_by_ideology.get(cat)
                if not isinstance(val, dict) or not isinstance(exp_val, dict):
                    ok = False
                    break
                # Compare metrics
                ok = ok and _compare_num(exp_val["gross"], val.get("gross"), tol=0.01)
                ok = ok and _compare_num(exp_val["fees"], val.get("fees"), tol=0.01)
                ok = ok and _compare_num(exp_val["net"], val.get("net"), tol=0.01)
                ok = ok and (_to_int(val.get("txns")) == exp_val["txns"])
                ok = ok and _compare_num(exp_val["average_donation"], val.get("average_donation"), tol=0.01)
                ok = ok and _compare_num(exp_val["median_donation"], val.get("median_donation"), tol=0.01)
            ideology_score = 1.0 if ok else 0.0
        else:
            ideology_score = 0.0

    # By platform check
    exp_by_platform = expected.get("by_platform")
    if structure_ok and isinstance(data.get("by_platform"), dict) and isinstance(exp_by_platform, dict):
        bp = data["by_platform"]
        required_keys = {"ActBlue", "WinRed"}
        bp_keys = set(bp.keys())
        if bp_keys == required_keys:
            ok = True
            for plat in ["ActBlue", "WinRed"]:
                val = bp.get(plat)
                exp_val = exp_by_platform.get(plat)
                if not isinstance(val, dict) or not isinstance(exp_val, dict):
                    ok = False
                    break
                ok = ok and _compare_num(exp_val["gross"], val.get("gross"), tol=0.01)
                ok = ok and _compare_num(exp_val["fees"], val.get("fees"), tol=0.01)
                ok = ok and _compare_num(exp_val["net"], val.get("net"), tol=0.01)
                ok = ok and (_to_int(val.get("txns")) == exp_val["txns"])
            platform_score = 1.0 if ok else 0.0
        else:
            platform_score = 0.0

    # Months check
    exp_months_map = expected.get("months_map")
    months_val = data.get("months")
    if structure_ok and isinstance(exp_months_map, dict) and isinstance(months_val, list):
        got_map: Dict[str, Dict[str, Any]] = {}
        ok_struct = True
        for item in months_val:
            if not isinstance(item, dict) or "month" not in item:
                ok_struct = False
                break
            got_map[item["month"]] = item
        if ok_struct:
            # Require same set of months
            if set(got_map.keys()) == set(exp_months_map.keys()):
                ok = True
                for m, exp in exp_months_map.items():
                    got = got_map.get(m, {})
                    ok = ok and _compare_num(exp["gross"], got.get("gross"), tol=0.01)
                    ok = ok and _compare_num(exp["fees"], got.get("fees"), tol=0.01)
                    ok = ok and _compare_num(exp["net"], got.get("net"), tol=0.01)
                    ok = ok and (_to_int(got.get("txns")) == exp["txns"])
                months_score = 1.0 if ok else 0.0
            else:
                months_score = 0.0
        else:
            months_score = 0.0

    return (str_score, overall_score, ideology_score, platform_score, months_score)


def _check_by_county_csv(workspace: Path, expected: Dict[str, Any]) -> float:
    path = workspace / "output" / "by_county.csv"
    rows = _read_csv_dicts(path)
    if rows is None:
        return 0.0
    # Header check: exact expected order
    expected_header = ["county", "unique_donors", "txn_count", "gross_amount", "total_fees", "net_amount"]
    try:
        with path.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
        header = header_line.split(",")
        if header != expected_header:
            return 0.0
    except Exception:
        return 0.0

    exp_map = expected.get("by_county_map")
    if not isinstance(exp_map, dict):
        return 0.0

    got_map: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        county = r.get("county")
        if county is None:
            return 0.0
        got_map[county] = r

    if set(got_map.keys()) != set(exp_map.keys()):
        return 0.0

    for county, exp in exp_map.items():
        got = got_map.get(county, {})
        if _to_int(got.get("unique_donors")) != exp["unique_donors"]:
            return 0.0
        if _to_int(got.get("txn_count")) != exp["txn_count"]:
            return 0.0
        if not _compare_num(exp["gross_amount"], got.get("gross_amount"), tol=0.01):
            return 0.0
        if not _compare_num(exp["total_fees"], got.get("total_fees"), tol=0.01):
            return 0.0
        if not _compare_num(exp["net_amount"], got.get("net_amount"), tol=0.01):
            return 0.0
    return 1.0


def _check_fee_anomalies_csv(workspace: Path, expected: Dict[str, Any]) -> float:
    path = workspace / "output" / "fee_anomalies.csv"
    rows = _read_csv_dicts(path)
    if rows is None:
        return 0.0
    # Header check exact
    expected_header = ["transaction_id", "source", "amount", "expected_fee", "recorded_fee", "deviation"]
    try:
        with path.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
        header = header_line.split(",")
        if header != expected_header:
            return 0.0
    except Exception:
        return 0.0

    exp_list = expected.get("anomalies_list")
    if not isinstance(exp_list, list):
        return 0.0

    exp_map = {x["transaction_id"]: x for x in exp_list}
    got_map = {r.get("transaction_id"): r for r in rows if r.get("transaction_id") is not None}

    if set(exp_map.keys()) != set(got_map.keys()):
        return 0.0

    for tid, exp in exp_map.items():
        got = got_map[tid]
        if got.get("source") != exp["source"]:
            return 0.0
        if not _compare_num(exp["amount"], got.get("amount"), tol=0.01):
            return 0.0
        if not _compare_num(exp["expected_fee"], got.get("expected_fee"), tol=0.01):
            return 0.0
        if not _compare_num(exp["recorded_fee"], got.get("recorded_fee"), tol=0.01):
            return 0.0
        if not _compare_num(exp["deviation"], got.get("deviation"), tol=0.01):
            return 0.0
    return 1.0


def _check_unmapped_committees_csv(workspace: Path, expected: Dict[str, Any]) -> float:
    path = workspace / "output" / "unmapped_committees.csv"
    rows = _read_csv_dicts(path)
    if rows is None:
        return 0.0
    # Header check exact
    expected_header = ["recipient_committee_id", "recipient_committee_name", "txn_count", "gross_amount"]
    try:
        with path.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
        header = header_line.split(",")
        if header != expected_header:
            return 0.0
    except Exception:
        return 0.0

    exp_map = expected.get("unmapped_committees_map")
    if not isinstance(exp_map, dict):
        return 0.0

    got_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in rows:
        cid = r.get("recipient_committee_id")
        cname = r.get("recipient_committee_name")
        if cid is None or cname is None:
            return 0.0
        got_map[(cid, cname)] = r

    if set(got_map.keys()) != set(exp_map.keys()):
        return 0.0

    for key, exp in exp_map.items():
        got = got_map.get(key, {})
        if _to_int(got.get("txn_count")) != exp["txn_count"]:
            return 0.0
        if not _compare_num(exp["gross_amount"], got.get("gross_amount"), tol=0.01):
            return 0.0
    return 1.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_json_present_and_structure": 0.0,
        "summary_overall_correct": 0.0,
        "summary_by_ideology_correct": 0.0,
        "summary_by_platform_correct": 0.0,
        "summary_months_correct": 0.0,
        "by_county_csv_correct": 0.0,
        "fee_anomalies_csv_correct": 0.0,
        "unmapped_committees_csv_correct": 0.0,
    }

    expected = _compute_expected(workspace)
    # If transactions couldn't be read, all checks remain 0.0
    if not expected.get("ok", False):
        return scores

    # summary checks
    a, b, c, d, e = _check_summary_json(workspace, expected)
    scores["summary_json_present_and_structure"] = a
    scores["summary_overall_correct"] = b
    scores["summary_by_ideology_correct"] = c
    scores["summary_by_platform_correct"] = d
    scores["summary_months_correct"] = e

    # by_county
    scores["by_county_csv_correct"] = _check_by_county_csv(workspace, expected)

    # fee anomalies depends on rates and anomalies_list being computed
    if expected.get("anomalies_list") is not None:
        scores["fee_anomalies_csv_correct"] = _check_fee_anomalies_csv(workspace, expected)
    else:
        scores["fee_anomalies_csv_correct"] = 0.0

    # unmapped committees depends on committees map
    if expected.get("unmapped_committees_map") is not None:
        scores["unmapped_committees_csv_correct"] = _check_unmapped_committees_csv(workspace, expected)
    else:
        scores["unmapped_committees_csv_correct"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()