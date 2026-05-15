import json
import sys
import csv
from pathlib import Path
import importlib.util
from typing import Dict, Any, List, Optional, Tuple, Set


def _read_csv_dicts(p: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with p.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _load_json(p: Path) -> Optional[Any]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _strip_yaml_comment(line: str) -> str:
    idx = line.find("#")
    if idx != -1:
        return line[:idx].rstrip("\n")
    return line.rstrip("\n")


def _parse_category_rules_yaml(p: Path) -> Optional[Tuple[Set[str], Set[str]]]:
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = text.splitlines()
    science_merchants: Set[str] = set()
    science_categories: Set[str] = set()

    inside_groups = False
    inside_science = False
    current_list: Optional[str] = None

    for raw in lines:
        line = _strip_yaml_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0 and stripped == "groups:":
            inside_groups = True
            inside_science = False
            current_list = None
            continue

        if not inside_groups:
            continue

        if indent == 2 and stripped.endswith(":"):
            grp_name = stripped[:-1].strip()
            inside_science = (grp_name == "science")
            current_list = None
            continue

        if inside_science:
            if indent == 4 and stripped.startswith("merchants:"):
                if stripped.endswith("[]"):
                    current_list = None
                else:
                    current_list = "merchants"
                continue
            if indent == 4 and stripped.startswith("categories:"):
                if stripped.endswith("[]"):
                    current_list = None
                else:
                    current_list = "categories"
                continue
            if indent >= 6 and stripped.startswith("- ") and current_list in {"merchants", "categories"}:
                val = stripped[2:].strip()
                if val:
                    if current_list == "merchants":
                        science_merchants.add(val)
                    else:
                        science_categories.add(val)
                continue
            if indent == 4 and ":" in stripped:
                current_list = None

    return science_merchants, science_categories


def _load_rewards_config(p: Path) -> Optional[Dict[str, Any]]:
    try:
        spec = importlib.util.spec_from_file_location("rewards_config", str(p))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        cfg = {
            "SURCHARGE_RATE": getattr(module, "SURCHARGE_RATE", None),
            "CASHBACK_RATES": getattr(module, "CASHBACK_RATES", None),
            "APPLY_CASHBACK_TO_SCIENCE_ONLY": getattr(module, "APPLY_CASHBACK_TO_SCIENCE_ONLY", None),
        }
        if not isinstance(cfg["SURCHARGE_RATE"], (int, float)):
            return None
        if not isinstance(cfg["CASHBACK_RATES"], dict):
            return None
        if not isinstance(cfg["APPLY_CASHBACK_TO_SCIENCE_ONLY"], bool):
            return None
        for k, v in cfg["CASHBACK_RATES"].items():
            if not isinstance(k, str) or not isinstance(v, (int, float)):
                return None
        return cfg
    except Exception:
        return None


def _isclose(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _safe_float(s: Any) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    tx_path = workspace / "input" / "transactions.csv"
    yaml_path = workspace / "input" / "category_rules.yaml"
    pycfg_path = workspace / "input" / "rewards_config.py"

    tx_rows = _read_csv_dicts(tx_path)
    if tx_rows is None:
        return None

    parsed_yaml = _parse_category_rules_yaml(yaml_path)
    if parsed_yaml is None:
        return None
    science_merchants, science_categories = parsed_yaml

    cfg = _load_rewards_config(pycfg_path)
    if cfg is None:
        return None

    surcharge_rate = float(cfg["SURCHARGE_RATE"])
    cashback_rates: Dict[str, float] = {k: float(v) for k, v in cfg["CASHBACK_RATES"].items()}
    apply_science_only: bool = bool(cfg["APPLY_CASHBACK_TO_SCIENCE_ONLY"])

    months: Dict[str, Dict[str, float]] = {}
    overall = {
        "total_transactions": 0,
        "gross_expense": 0.0,
        "net_expense": 0.0,
        "net_science_expense": 0.0,
        "income": 0.0,
    }
    classified_counts = {"science": 0, "other": 0}
    seen_merchants: Set[str] = set()
    science_merchant_net: Dict[str, float] = {}

    def classify(merchant: str, category: str) -> str:
        if merchant in science_merchants or category in science_categories:
            return "science"
        return "other"

    for row in tx_rows:
        date = row.get("date", "")
        merchant = row.get("merchant", "")
        category = row.get("category", "")
        amount_s = row.get("amount", "")
        amount = _safe_float(amount_s)
        if date is None or merchant is None or category is None or amount is None:
            return None
        month = date[:7]
        if len(month) != 7 or month[4] != "-":
            return None
        if month not in months:
            months[month] = {
                "gross_expense": 0.0,
                "net_expense": 0.0,
                "income": 0.0,
                "net_science_expense": 0.0,
            }
        overall["total_transactions"] += 1
        seen_merchants.add(merchant)
        cls = classify(merchant, category)
        if cls not in ("science", "other"):
            return None
        classified_counts[cls] += 1

        if amount < 0:
            gross = abs(amount)
            months[month]["gross_expense"] += gross
            overall["gross_expense"] += gross

            adj = gross
            if category == "International":
                adj *= (1.0 + surcharge_rate)
            rate = cashback_rates.get(merchant)
            if rate is not None:
                if (apply_science_only and cls == "science") or (not apply_science_only):
                    adj *= (1.0 - rate)
            months[month]["net_expense"] += adj
            overall["net_expense"] += adj

            if cls == "science":
                months[month]["net_science_expense"] += adj
                overall["net_science_expense"] += adj
                science_merchant_net[merchant] = science_merchant_net.get(merchant, 0.0) + adj
        else:
            months[month]["income"] += amount
            overall["income"] += amount

    monthly_summary = []
    for m, agg in months.items():
        net_expense = agg["net_expense"]
        net_science = agg["net_science_expense"]
        science_share = (net_science / net_expense) if net_expense != 0 else 0.0
        monthly_summary.append({
            "month": m,
            "gross_expense": agg["gross_expense"],
            "net_expense": agg["net_expense"],
            "income": agg["income"],
            "net_science_expense": agg["net_science_expense"],
            "science_share": science_share,
        })

    top_science = sorted(
        [{"merchant": k, "net_expense": v} for k, v in science_merchant_net.items()],
        key=lambda x: (-x["net_expense"], x["merchant"])
    )[:3]

    config_snapshot = {
        "surcharge_rate": surcharge_rate,
        "apply_cashback_to_science_only": apply_science_only,
        "cashback_merchants": list(cashback_rates.keys()),
    }

    missing_cashback_merchants = sorted([m for m in cashback_rates.keys() if m not in seen_merchants])

    expected = {
        "monthly_summary": monthly_summary,
        "overall": {
            "total_transactions": overall["total_transactions"],
            "gross_expense": overall["gross_expense"],
            "net_expense": overall["net_expense"],
            "net_science_expense": overall["net_science_expense"],
        },
        "top_science_merchants_by_net_expense": top_science,
        "classified_counts": classified_counts,
        "config_snapshot": config_snapshot,
        "missing_cashback_merchants_in_data": missing_cashback_merchants,
        "months_set": set(months.keys()),
    }
    return expected


def _load_monthly_csv(p: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _read_csv_dicts(p)
    if rows is None:
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
    except Exception:
        return None
    header_cols = header_line.split(",") if header_line else []
    expected_cols = ["month", "gross_expense", "net_expense", "income", "net_science_expense", "science_share"]
    if header_cols != expected_cols:
        return None
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            out.append({
                "month": r["month"],
                "gross_expense": float(r["gross_expense"]),
                "net_expense": float(r["net_expense"]),
                "income": float(r["income"]),
                "net_science_expense": float(r["net_science_expense"]),
                "science_share": float(r["science_share"]),
            })
        except Exception:
            return None
    return out


def _index_by_month(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {r["month"]: r for r in rows}


def _compare_monthly_csv(expected: List[Dict[str, Any]], actual: List[Dict[str, Any]], tol: float = 1e-6) -> bool:
    if len(expected) != len(actual):
        return False
    exp_idx = _index_by_month(expected)
    act_idx = _index_by_month(actual)
    if set(exp_idx.keys()) != set(act_idx.keys()):
        return False
    for m, e in exp_idx.items():
        a = act_idx[m]
        if not (_isclose(e["gross_expense"], a["gross_expense"], tol) and
                _isclose(e["net_expense"], a["net_expense"], tol) and
                _isclose(e["income"], a["income"], tol) and
                _isclose(e["net_science_expense"], a["net_science_expense"], tol)):
            return False
        expected_share = (e["net_science_expense"] / e["net_expense"]) if e["net_expense"] != 0 else 0.0
        if not _isclose(expected_share, a["science_share"], tol):
            return False
    return True


def _compare_json_report(expected: Dict[str, Any], actual: Dict[str, Any], tol: float = 1e-6) -> Dict[str, bool]:
    results = {
        "structure_ok": False,
        "overall_ok": False,
        "monthly_ok": False,
        "top_science_merchants_ok": False,
        "classified_counts_ok": False,
        "config_snapshot_ok": False,
        "missing_cashback_merchants_ok": False,
    }
    required_keys = {
        "overall",
        "monthly",
        "top_science_merchants_by_net_expense",
        "classified_counts",
        "config_snapshot",
        "missing_cashback_merchants_in_data",
    }
    if not isinstance(actual, dict):
        return results
    if not required_keys.issubset(set(actual.keys())):
        return results
    if not isinstance(actual.get("monthly"), list):
        return results
    if not isinstance(actual.get("top_science_merchants_by_net_expense"), list):
        return results
    if not isinstance(actual.get("overall"), dict):
        return results
    if not isinstance(actual.get("classified_counts"), dict):
        return results
    if not isinstance(actual.get("config_snapshot"), dict):
        return results
    if not isinstance(actual.get("missing_cashback_merchants_in_data"), list):
        return results
    results["structure_ok"] = True

    exp_overall = expected["overall"]
    act_overall = actual["overall"]
    try:
        overall_ok = (
            int(act_overall.get("total_transactions")) == int(exp_overall["total_transactions"]) and
            _isclose(float(act_overall.get("gross_expense")), float(exp_overall["gross_expense"]), tol) and
            _isclose(float(act_overall.get("net_expense")), float(exp_overall["net_expense"]), tol) and
            _isclose(float(act_overall.get("net_science_expense")), float(exp_overall["net_science_expense"]), tol)
        )
    except Exception:
        overall_ok = False
    results["overall_ok"] = overall_ok

    try:
        act_months = {m["month"]: m for m in actual["monthly"]}
        exp_months = {m["month"]: m for m in expected["monthly_summary"]}
        monthly_ok = set(act_months.keys()) == set(exp_months.keys())
        if monthly_ok:
            for k, e in exp_months.items():
                a = act_months[k]
                monthly_ok = monthly_ok and _isclose(float(a["net_expense"]), float(e["net_expense"]), tol)
                monthly_ok = monthly_ok and _isclose(float(a["net_science_expense"]), float(e["net_science_expense"]), tol)
                expected_share = (e["net_science_expense"] / e["net_expense"]) if e["net_expense"] != 0 else 0.0
                monthly_ok = monthly_ok and _isclose(float(a["science_share"]), expected_share, tol)
    except Exception:
        monthly_ok = False
    results["monthly_ok"] = monthly_ok

    try:
        exp_top = expected["top_science_merchants_by_net_expense"]
        act_top = actual["top_science_merchants_by_net_expense"]
        top_ok = isinstance(act_top, list) and len(act_top) == len(exp_top)
        if top_ok:
            for e, a in zip(exp_top, act_top):
                if a.get("merchant") != e.get("merchant"):
                    top_ok = False
                    break
                if not _isclose(float(a.get("net_expense")), float(e.get("net_expense")), tol):
                    top_ok = False
                    break
    except Exception:
        top_ok = False
    results["top_science_merchants_ok"] = top_ok

    try:
        exp_counts = expected["classified_counts"]
        act_counts = actual["classified_counts"]
        counts_ok = (
            int(act_counts.get("science")) == int(exp_counts["science"]) and
            int(act_counts.get("other")) == int(exp_counts["other"])
        )
    except Exception:
        counts_ok = False
    results["classified_counts_ok"] = counts_ok

    try:
        exp_cfg = expected["config_snapshot"]
        act_cfg = actual["config_snapshot"]
        cfg_ok = (
            _isclose(float(act_cfg.get("surcharge_rate")), float(exp_cfg["surcharge_rate"]), tol) and
            bool(act_cfg.get("apply_cashback_to_science_only")) == bool(exp_cfg["apply_cashback_to_science_only"])
        )
        act_cash_merchants = act_cfg.get("cashback_merchants")
        if isinstance(act_cash_merchants, list):
            cfg_ok = cfg_ok and set(act_cash_merchants) == set(exp_cfg["cashback_merchants"])
        else:
            cfg_ok = False
    except Exception:
        cfg_ok = False
    results["config_snapshot_ok"] = cfg_ok

    try:
        exp_missing = set(expected["missing_cashback_merchants_in_data"])
        act_missing = set(actual["missing_cashback_merchants_in_data"])
        missing_ok = exp_missing == act_missing
    except Exception:
        missing_ok = False
    results["missing_cashback_merchants_ok"] = missing_ok

    return results


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "monthly_csv_structure": 0.0,
        "monthly_csv_values": 0.0,
        "science_report_structure": 0.0,
        "science_report_overall_and_monthly_values": 0.0,
        "science_report_top_merchants": 0.0,
        "science_report_classified_counts": 0.0,
        "science_report_config_snapshot": 0.0,
        "science_report_missing_cashback_merchants": 0.0,
    }

    expected = _compute_expected(workspace)
    output_csv_path = workspace / "output" / "monthly_summary.csv"
    output_json_path = workspace / "output" / "science_spend_report.json"

    monthly_rows = _load_monthly_csv(output_csv_path)
    report_json = _load_json(output_json_path)

    if expected is None:
        return scores

    if monthly_rows is not None:
        months_set_actual = {r["month"] for r in monthly_rows}
        if months_set_actual == expected["months_set"]:
            scores["monthly_csv_structure"] = 1.0

    if monthly_rows is not None and scores["monthly_csv_structure"] == 1.0:
        if _compare_monthly_csv(expected["monthly_summary"], monthly_rows, tol=1e-6):
            scores["monthly_csv_values"] = 1.0

    comp_results = {
        "structure_ok": False,
        "overall_ok": False,
        "monthly_ok": False,
        "top_science_merchants_ok": False,
        "classified_counts_ok": False,
        "config_snapshot_ok": False,
        "missing_cashback_merchants_ok": False,
    }
    if report_json is not None:
        comp_results = _compare_json_report(expected, report_json, tol=1e-6)
        if comp_results["structure_ok"]:
            scores["science_report_structure"] = 1.0

    if report_json is not None and scores["science_report_structure"] == 1.0:
        if comp_results["overall_ok"] and comp_results["monthly_ok"]:
            scores["science_report_overall_and_monthly_values"] = 1.0
        if comp_results["top_science_merchants_ok"]:
            scores["science_report_top_merchants"] = 1.0
        if comp_results["classified_counts_ok"]:
            scores["science_report_classified_counts"] = 1.0
        if comp_results["config_snapshot_ok"]:
            scores["science_report_config_snapshot"] = 1.0
        if comp_results["missing_cashback_merchants_ok"]:
            scores["science_report_missing_cashback_merchants"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()