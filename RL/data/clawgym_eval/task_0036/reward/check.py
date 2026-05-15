import json
import csv
import sys
import re
from pathlib import Path
from html.parser import HTMLParser


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    try:
        return json.loads(_read_text(path))
    except Exception:
        return None


def _safe_read_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _parse_simple_yaml(path: Path):
    text = _read_text(path)
    if not text:
        return None
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove quotes if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        # Try to parse number
        try:
            if "." in val or "e" in val.lower():
                num = float(val)
            else:
                num = int(val)
            data[key] = num
        except Exception:
            data[key] = val
    return data


def _parse_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s.lower() in {"na", "n/a", "none", ""}:
        return None
    # Remove $ , % and spaces
    s = s.replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(s)
    except Exception:
        return None


class PricingTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.capture = False
        self.current_row = []
        self.rows = []
        self.current_tag = None
        self._table_stack = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "table":
            attrs_dict = dict(attrs)
            if attrs_dict.get("id") == "pricing":
                self.in_table = True
                self._table_stack.append("pricing")
            else:
                self._table_stack.append("other")
        if self.in_table and tag.lower() == "tr":
            self.current_row = []
        if self.in_table and tag.lower() in ("td", "th"):
            self.capture = True
            self.current_tag = tag.lower()

    def handle_endtag(self, tag):
        if self.in_table and tag.lower() in ("td", "th"):
            self.capture = False
            self.current_tag = None
        if self.in_table and tag.lower() == "tr":
            if self.current_row:
                self.rows.append([cell.strip() for cell in self.current_row])
            self.current_row = []
        if tag.lower() == "table":
            if self._table_stack:
                popped = self._table_stack.pop()
                if popped == "pricing":
                    self.in_table = False

    def handle_data(self, data):
        if self.in_table and self.capture and self.current_tag in ("td", "th"):
            text = data.strip()
            if text:
                self.current_row.append(text)


def _parse_vendor_quote_html(path: Path):
    text = _read_text(path)
    if not text:
        return None
    parser = PricingTableParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    items = {}
    # Expect rows: [Item, Amount (USD)]
    for row in parser.rows:
        if len(row) >= 2:
            item = row[0].strip()
            amt_raw = row[1].strip()
            amt = _parse_float(amt_raw)
            if amt is not None:
                items[item] = amt
    # We only need three specific items
    needed_labels = {
        "Sensor unit price",
        "Monthly software subscription per device",
        "One-time installation fee per site",
    }
    if not needed_labels.issubset(set(items.keys())):
        # Try to normalize whitespace/case
        normalized = {re.sub(r"\s+", " ", k).strip().lower(): v for k, v in items.items()}
        out = {}
        for lbl in needed_labels:
            key_norm = re.sub(r"\s+", " ", lbl).strip().lower()
            if key_norm in normalized:
                out[lbl] = normalized[key_norm]
        if not needed_labels.issubset(set(out.keys())):
            return None
        return out
    return {k: items[k] for k in needed_labels}


def _approx_equal(a, b, tol=1e-2):
    try:
        if a is None or b is None:
            return False
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _compute_expected(workspace: Path):
    input_dir = workspace / "input"
    # Load inputs
    baseline_path = input_dir / "energy_baseline.csv"
    pilot_path = input_dir / "energy_pilot.csv"
    site_meta_path = input_dir / "site_metadata.json"
    vendor_path = input_dir / "vendor_quote.html"
    rate_path = input_dir / "electricity_rate.yaml"

    header_b, rows_b = _safe_read_csv(baseline_path)
    header_p, rows_p = _safe_read_csv(pilot_path)
    site_meta = _safe_load_json(site_meta_path)
    vendor = _parse_vendor_quote_html(vendor_path)
    rate_cfg = _parse_simple_yaml(rate_path)

    if None in (rows_b, rows_p, site_meta, vendor, rate_cfg):
        return None, None

    # Build mappings
    baseline = {}
    pilot = {}
    for r in rows_b:
        site = r.get("site_id")
        date = r.get("date")
        kwh = _parse_float(r.get("kwh"))
        if site and date and kwh is not None:
            baseline.setdefault(site, {})[date] = kwh
    for r in rows_p:
        site = r.get("site_id")
        date = r.get("date")
        kwh = _parse_float(r.get("kwh"))
        if site and date and kwh is not None:
            pilot.setdefault(site, {})[date] = kwh

    # site devices count mapping
    devices_map = {}
    try:
        for item in site_meta:
            sid = item.get("site_id")
            dc = item.get("devices_count")
            if sid is not None:
                devices_map[sid] = int(dc)
    except Exception:
        return None, None

    try:
        month_days = float(rate_cfg.get("month_days"))
        rate_per_kwh = float(rate_cfg.get("rate_per_kwh"))
    except Exception:
        return None, None

    unit_price = vendor.get("Sensor unit price")
    monthly_sub_per_device = vendor.get("Monthly software subscription per device")
    install_fee = vendor.get("One-time installation fee per site")

    if None in (unit_price, monthly_sub_per_device, install_fee):
        return None, None

    # Compute per-site expected
    site_ids = sorted(set(baseline.keys()).union(set(pilot.keys())))
    expected_sites = {}
    for sid in site_ids:
        bdates = set(baseline.get(sid, {}).keys())
        pdates = set(pilot.get(sid, {}).keys())
        mdates = sorted(bdates.intersection(pdates))
        if not mdates:
            # Skip sites without matching dates
            continue
        bvals = [baseline[sid][d] for d in mdates]
        pvals = [pilot[sid][d] for d in mdates]
        if not bvals or not pvals:
            continue
        bavg = sum(bvals) / len(bvals)
        pavg = sum(pvals) / len(pvals)
        red = bavg - pavg
        pct = (red / bavg * 100.0) if bavg != 0 else 0.0
        est_kwh = red * month_days
        est_usd = est_kwh * rate_per_kwh
        devices = devices_map.get(sid, 0)
        upfront = devices * unit_price + install_fee
        monthly_sub = devices * monthly_sub_per_device
        net_benefit = est_usd - monthly_sub
        if net_benefit <= 0:
            payback = "N/A"
        else:
            payback = upfront / net_benefit
        expected_sites[sid] = {
            "site_id": sid,
            "baseline_avg_kwh": bavg,
            "pilot_avg_kwh": pavg,
            "avg_daily_reduction_kwh": red,
            "pct_reduction": pct,
            "est_monthly_savings_kwh": est_kwh,
            "est_monthly_savings_usd": est_usd,
            "devices_count": float(devices),
            "upfront_cost_usd": upfront,
            "monthly_subscription_usd": monthly_sub,
            "net_monthly_benefit_usd": net_benefit,
            "payback_months": payback,
        }

    # Overall expected
    if not expected_sites:
        return None, None

    n = len(expected_sites)
    mean_pct = sum(v["pct_reduction"] for v in expected_sites.values()) / n
    total_est_savings = sum(v["est_monthly_savings_usd"] for v in expected_sites.values())
    total_sub = sum(v["monthly_subscription_usd"] for v in expected_sites.values())
    total_upfront = sum(v["upfront_cost_usd"] for v in expected_sites.values())
    portfolio_net = total_est_savings - total_sub
    if portfolio_net <= 0:
        portfolio_payback = "N/A"
    else:
        portfolio_payback = total_upfront / portfolio_net
    expected_overall = {
        "num_sites": n,
        "mean_pct_reduction": mean_pct,
        "total_est_monthly_savings_usd": total_est_savings,
        "total_monthly_subscription_usd": total_sub,
        "total_upfront_cost_usd": total_upfront,
        "portfolio_net_monthly_benefit_usd": portfolio_net,
        "portfolio_payback_months": portfolio_payback,
    }
    return expected_sites, expected_overall


def _load_savings_summary(path: Path):
    header, rows = _safe_read_csv(path)
    if header is None or rows is None:
        return None, None
    # Build mapping by site_id
    mapping = {}
    for r in rows:
        sid = r.get("site_id")
        if not sid:
            continue
        mapping[sid] = r
    return header, mapping


def _parse_csv_value(val):
    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in {"n/a", "na"}:
        return "N/A"
    f = _parse_float(s)
    if f is None:
        return s
    return f


def _check_savings_structure(workspace: Path, expected_sites: dict):
    path = workspace / "output" / "savings_summary.csv"
    required_header = [
        "site_id",
        "baseline_avg_kwh",
        "pilot_avg_kwh",
        "avg_daily_reduction_kwh",
        "pct_reduction",
        "est_monthly_savings_kwh",
        "est_monthly_savings_usd",
        "devices_count",
        "upfront_cost_usd",
        "monthly_subscription_usd",
        "net_monthly_benefit_usd",
        "payback_months",
    ]
    header, mapping = _load_savings_summary(path)
    if header is None or mapping is None:
        return 0.0
    # Check exact header order
    if header != required_header:
        return 0.0
    if expected_sites is None:
        # Can't verify sites without inputs; but structure ok
        return 1.0 if len(mapping) > 0 else 0.0
    # Verify exact site_ids
    expected_ids = set(expected_sites.keys())
    got_ids = set(mapping.keys())
    if expected_ids != got_ids:
        return 0.0
    return 1.0


def _check_savings_values(workspace: Path, expected_sites: dict, tol=1e-2):
    if expected_sites is None:
        return 0.0
    path = workspace / "output" / "savings_summary.csv"
    header, mapping = _load_savings_summary(path)
    if header is None or mapping is None:
        return 0.0
    # For each site and numeric fields compare
    fields_numeric = [
        "baseline_avg_kwh",
        "pilot_avg_kwh",
        "avg_daily_reduction_kwh",
        "pct_reduction",
        "est_monthly_savings_kwh",
        "est_monthly_savings_usd",
        "devices_count",
        "upfront_cost_usd",
        "monthly_subscription_usd",
        "net_monthly_benefit_usd",
    ]
    per_site_scores = []
    for sid, exp in expected_sites.items():
        row = mapping.get(sid)
        if row is None:
            per_site_scores.append(0.0)
            continue
        ok = True
        for f in fields_numeric:
            got_val = _parse_csv_value(row.get(f))
            exp_val = exp.get(f)
            if not _approx_equal(got_val, exp_val, tol=tol):
                ok = False
                break
        # payback
        exp_pb = exp.get("payback_months")
        got_pb_raw = row.get("payback_months")
        if isinstance(exp_pb, str) and exp_pb == "N/A":
            if got_pb_raw is None or str(got_pb_raw).strip().upper() != "N/A":
                ok = False
        else:
            got_pb = _parse_float(got_pb_raw)
            if not _approx_equal(got_pb, exp_pb, tol=tol):
                ok = False
        per_site_scores.append(1.0 if ok else 0.0)
    if not per_site_scores:
        return 0.0
    return sum(per_site_scores) / len(per_site_scores)


def _check_overall_structure(workspace: Path):
    path = workspace / "output" / "overall_stats.json"
    data = _safe_load_json(path)
    if not isinstance(data, dict):
        return 0.0
    required_keys = [
        "num_sites",
        "mean_pct_reduction",
        "total_est_monthly_savings_usd",
        "total_monthly_subscription_usd",
        "total_upfront_cost_usd",
        "portfolio_net_monthly_benefit_usd",
        "portfolio_payback_months",
    ]
    for k in required_keys:
        if k not in data:
            return 0.0
    return 1.0


def _check_overall_values(workspace: Path, expected_overall: dict, tol=1e-2):
    if expected_overall is None:
        return 0.0
    path = workspace / "output" / "overall_stats.json"
    data = _safe_load_json(path)
    if not isinstance(data, dict):
        return 0.0
    ok = True
    # Numeric fields
    numeric_fields = [
        "num_sites",
        "mean_pct_reduction",
        "total_est_monthly_savings_usd",
        "total_monthly_subscription_usd",
        "total_upfront_cost_usd",
        "portfolio_net_monthly_benefit_usd",
    ]
    for f in numeric_fields:
        got = _parse_float(data.get(f))
        exp = expected_overall.get(f)
        if not _approx_equal(got, exp, tol=tol):
            ok = False
            break
    # portfolio_payback_months
    if ok:
        exp_pb = expected_overall.get("portfolio_payback_months")
        got_pb = data.get("portfolio_payback_months")
        if isinstance(exp_pb, str) and exp_pb == "N/A":
            if not isinstance(got_pb, str) or got_pb.upper() != "N/A":
                ok = False
        else:
            if not _approx_equal(_parse_float(got_pb), exp_pb, tol=tol):
                ok = False
    return 1.0 if ok else 0.0


def _check_overall_consistency(workspace: Path, tol=1e-2):
    # Compare overall_stats.json with aggregates from savings_summary.csv (student-produced)
    summary_path = workspace / "output" / "savings_summary.csv"
    overall_path = workspace / "output" / "overall_stats.json"
    header, mapping = _load_savings_summary(summary_path)
    data = _safe_load_json(overall_path)
    if header is None or mapping is None or not isinstance(data, dict):
        return 0.0
    # Aggregate
    try:
        num_sites = len(mapping)
        mean_pct = sum(_parse_float(r.get("pct_reduction")) for r in mapping.values()) / num_sites if num_sites > 0 else 0.0
        total_savings = sum(_parse_float(r.get("est_monthly_savings_usd")) for r in mapping.values())
        total_sub = sum(_parse_float(r.get("monthly_subscription_usd")) for r in mapping.values())
        total_upfront = sum(_parse_float(r.get("upfront_cost_usd")) for r in mapping.values())
        portfolio_net = total_savings - total_sub
        if portfolio_net <= 0:
            portfolio_payback = "N/A"
        else:
            portfolio_payback = total_upfront / portfolio_net
    except Exception:
        return 0.0
    ok = True
    if not _approx_equal(_parse_float(data.get("num_sites")), num_sites, tol=tol):
        ok = False
    if not _approx_equal(_parse_float(data.get("mean_pct_reduction")), mean_pct, tol=tol):
        ok = False
    if not _approx_equal(_parse_float(data.get("total_est_monthly_savings_usd")), total_savings, tol=tol):
        ok = False
    if not _approx_equal(_parse_float(data.get("total_monthly_subscription_usd")), total_sub, tol=tol):
        ok = False
    if not _approx_equal(_parse_float(data.get("total_upfront_cost_usd")), total_upfront, tol=tol):
        ok = False
    if not _approx_equal(_parse_float(data.get("portfolio_net_monthly_benefit_usd")), portfolio_net, tol=tol):
        ok = False
    exp_pb = portfolio_payback
    got_pb = data.get("portfolio_payback_months")
    if isinstance(exp_pb, str) and exp_pb == "N/A":
        if not isinstance(got_pb, str) or got_pb.upper() != "N/A":
            ok = False
    else:
        if not _approx_equal(_parse_float(got_pb), exp_pb, tol=tol):
            ok = False
    return 1.0 if ok else 0.0


def _check_email(workspace: Path):
    # Validate placeholders replaced and values present with two decimals based on overall_stats.json
    email_path = workspace / "output" / "stakeholder_email.txt"
    overall_path = workspace / "output" / "overall_stats.json"
    text = _read_text(email_path)
    data = _safe_load_json(overall_path)
    if not text or not isinstance(data, dict):
        return 0.0, 0.0
    # Check placeholders removed
    placeholders_ok = ("{{MEAN_PCT_REDUCTION}}" not in text) and ("{{PORTFOLIO_PAYBACK_MONTHS}}" not in text)
    # Check that the two figures are present rounded to two decimals
    mean_pct = _parse_float(data.get("mean_pct_reduction"))
    if mean_pct is None:
        return 0.0, 0.0
    mean_str = f"{mean_pct:.2f}"
    ppb = data.get("portfolio_payback_months")
    if isinstance(ppb, str) and ppb.upper() == "N/A":
        payback_ok = "N/A" in text
    else:
        ppb_val = _parse_float(ppb)
        if ppb_val is None:
            return 0.0, 0.0
        payback_str = f"{ppb_val:.2f}"
        payback_ok = payback_str in text
    values_ok = (mean_str in text) and payback_ok
    placeholders_and_values = 1.0 if (placeholders_ok and values_ok) else 0.0

    # Check length <= 150 words and contains focus keywords
    # Count words by whitespace
    words = re.findall(r"\b\w+\b", text)
    length_ok = len(words) <= 150
    # Focus on key results and payback
    has_reduction = re.search(r"\breduction\b", text, flags=re.IGNORECASE) is not None
    has_payback = re.search(r"\bpayback\b", text, flags=re.IGNORECASE) is not None
    # Neutral tone basic check: avoid slang like 'kinda'
    no_slang = re.search(r"\bkinda\b", text, flags=re.IGNORECASE) is None
    length_and_focus = 1.0 if (length_ok and has_reduction and has_payback and no_slang) else 0.0

    return placeholders_and_values, length_and_focus


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "savings_summary_structure": 0.0,
        "savings_summary_values": 0.0,
        "overall_stats_structure": 0.0,
        "overall_stats_values": 0.0,
        "overall_stats_consistent_with_summary": 0.0,
        "stakeholder_email_placeholders_and_values": 0.0,
        "stakeholder_email_length_and_focus": 0.0,
    }

    expected_sites, expected_overall = _compute_expected(workspace)
    # savings summary checks
    try:
        scores["savings_summary_structure"] = _check_savings_structure(workspace, expected_sites)
    except Exception:
        scores["savings_summary_structure"] = 0.0
    try:
        scores["savings_summary_values"] = _check_savings_values(workspace, expected_sites, tol=1e-2)
    except Exception:
        scores["savings_summary_values"] = 0.0

    # overall stats checks
    try:
        scores["overall_stats_structure"] = _check_overall_structure(workspace)
    except Exception:
        scores["overall_stats_structure"] = 0.0
    try:
        scores["overall_stats_values"] = _check_overall_values(workspace, expected_overall, tol=1e-2)
    except Exception:
        scores["overall_stats_values"] = 0.0
    try:
        scores["overall_stats_consistent_with_summary"] = _check_overall_consistency(workspace, tol=1e-2)
    except Exception:
        scores["overall_stats_consistent_with_summary"] = 0.0

    # email checks
    try:
        e1, e2 = _check_email(workspace)
        scores["stakeholder_email_placeholders_and_values"] = e1
        scores["stakeholder_email_length_and_focus"] = e2
    except Exception:
        scores["stakeholder_email_placeholders_and_values"] = 0.0
        scores["stakeholder_email_length_and_focus"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()