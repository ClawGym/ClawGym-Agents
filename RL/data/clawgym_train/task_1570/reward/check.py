import csv
import json
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _to_float(val):
    try:
        if isinstance(val, (int, float)):
            return float(val)
        if val is None:
            return None
        s = str(val).strip()
        if s == "" or s.lower() in ("na", "nan", "none"):
            return None
        return float(s)
    except Exception:
        return None


def _parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _format_date(d):
    return d.strftime("%Y-%m-%d")


def _week_monday(d):
    # d is date
    return d - timedelta(days=d.weekday())


def _parse_ecb_csv(path: Path):
    # Returns (ok, data_by_date, currencies)
    # data_by_date: {date_str: {currency: rate_float}}
    rows = _read_csv_dicts(path)
    if rows is None or len(rows) == 0:
        return False, {}, set()
    # Expect header to include 'Date', 'USD', 'GBP'
    header = set(rows[0].keys())
    if "Date" not in header or "USD" not in header or "GBP" not in header:
        return False, {}, set()
    data_by_date = {}
    currencies = set([h for h in header if h != "Date"])
    for r in rows:
        ds = r.get("Date", "").strip()
        if not ds:
            continue
        # keep numeric values only
        cur_map = {}
        for cur, v in r.items():
            if cur == "Date":
                continue
            fv = _to_float(v)
            if fv is not None:
                cur_map[cur] = fv
        data_by_date[ds] = cur_map
    return True, data_by_date, currencies


def _get_rate_date_and_value(data_by_date: dict, currency: str, target_date_str: str):
    # Returns tuple (rate_date_str, rate_float) or (None, None) if not found
    target_date = _parse_date(target_date_str)
    if target_date is None:
        return None, None
    # Collect available dates with value for currency
    available_dates = []
    for ds, cmap in data_by_date.items():
        if currency in cmap:
            d = _parse_date(ds)
            if d is not None:
                available_dates.append((d, cmap[currency]))
    if not available_dates:
        return None, None
    available_dates.sort(key=lambda x: x[0])
    # Find the latest date <= target_date
    chosen = None
    for d, rate in available_dates:
        if d <= target_date:
            chosen = (d, rate)
        else:
            break
    if chosen is None:
        # No prior date; cannot convert
        return None, None
    return _format_date(chosen[0]), chosen[1]


def _round2(x):
    return round(x + 1e-12, 2)  # small epsilon to reduce float artifacts


def _parse_weekly_summary(path: Path):
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    return rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "ecb_download_exists_and_valid": 0.0,
        "rates_used_complete_and_correct": 0.0,
        "weekly_summary_has_required_columns": 0.0,
        "weekly_summary_values_2021_06_14": 0.0,
        "weekly_summary_values_2021_06_21": 0.0,
        "status_update_length": 0.0,
        "status_update_contains_sections_and_sources": 0.0,
        "status_update_mentions_metrics_and_dates": 0.0,
        "status_update_next_steps_for_missed_campaigns": 0.0,
    }

    # Paths
    ecb_path = workspace / "output" / "downloads" / "eurofxref-hist.csv"
    spend_path = workspace / "input" / "ppc_spend.csv"
    conv_path = workspace / "input" / "ppc_conversions.csv"
    targets_path = workspace / "input" / "targets.json"
    rates_used_path = workspace / "output" / "rates_used.csv"
    weekly_summary_path = workspace / "output" / "weekly_ppc_summary.csv"
    status_md_path = workspace / "output" / "status_update.md"

    # ECB file validation
    ecb_ok = False
    ecb_data = {}
    if ecb_path.exists():
        ok, data_by_date, currencies = _parse_ecb_csv(ecb_path)
        if ok:
            # verify USD & GBP columns and at least rows for 2021-06-14 and 2021-06-21 numeric
            valid_dates = True
            for ds in ["2021-06-14", "2021-06-21"]:
                if ds not in data_by_date:
                    valid_dates = False
                    break
                usd = _to_float(data_by_date.get(ds, {}).get("USD"))
                gbp = _to_float(data_by_date.get(ds, {}).get("GBP"))
                if usd is None or gbp is None:
                    valid_dates = False
                    break
            if valid_dates and "USD" in currencies and "GBP" in currencies:
                ecb_ok = True
                ecb_data = data_by_date
    scores["ecb_download_exists_and_valid"] = 1.0 if ecb_ok else 0.0

    # Prepare expected rates used set from inputs and ECB
    expected_rate_pairs = set()  # (rate_date_str, currency)
    expected_rate_values = {}    # (rate_date_str, currency) -> rate float
    need_checks = True

    spend_rows = _read_csv_dicts(spend_path) if spend_path.exists() else None
    conv_rows = _read_csv_dicts(conv_path) if conv_path.exists() else None

    if not ecb_ok or spend_rows is None or conv_rows is None:
        need_checks = False

    if need_checks:
        # Collect all needed transaction dates and currencies (USD, GBP) from both files
        needed = []
        for r in spend_rows:
            cur = (r.get("currency") or "").strip()
            ds = (r.get("date") or "").strip()
            if cur in ("USD", "GBP") and ds:
                needed.append((ds, cur))
        for r in conv_rows:
            cur = (r.get("currency") or "").strip()
            ds = (r.get("date") or "").strip()
            if cur in ("USD", "GBP") and ds:
                needed.append((ds, cur))
        # Determine expected ECB rate dates and values
        for ds, cur in needed:
            rate_date, rate_val = _get_rate_date_and_value(ecb_data, cur, ds)
            if rate_date is None or rate_val is None:
                need_checks = False
                break
            expected_rate_pairs.add((rate_date, cur))
            expected_rate_values[(rate_date, cur)] = rate_val

    # Validate rates_used.csv
    rates_ok = False
    if rates_used_path.exists() and need_checks:
        rates_rows = _read_csv_dicts(rates_used_path)
        if rates_rows is not None and len(rates_rows) > 0:
            # Check header order and names strictly
            with rates_used_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            expected_header = "date,currency,units_per_eur"
            if header_line == expected_header:
                # Build mapping
                mapping = {}
                currencies_only = set()
                valid_units = True
                for r in rates_rows:
                    d = (r.get("date") or "").strip()
                    c = (r.get("currency") or "").strip()
                    u = _to_float(r.get("units_per_eur"))
                    if d == "" or c == "" or u is None:
                        valid_units = False
                        break
                    mapping[(d, c)] = u
                    currencies_only.add(c)
                # Only USD and GBP allowed
                if valid_units and all(c in ("USD", "GBP") for c in currencies_only):
                    # Ensure all expected pairs are present with matching units
                    all_match = True
                    for key, exp_val in expected_rate_values.items():
                        if key not in mapping:
                            all_match = False
                            break
                        if mapping[key] is None:
                            all_match = False
                            break
                        if abs(mapping[key] - exp_val) > 1e-6:
                            all_match = False
                            break
                    rates_ok = all_match
    scores["rates_used_complete_and_correct"] = 1.0 if rates_ok else 0.0

    # Weekly summary structure
    weekly_structure_ok = False
    weekly_rows = None
    if weekly_summary_path.exists():
        # Read header line exactly and rows
        try:
            with weekly_summary_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            expected_header = "week_start_date,campaign,clicks,cost_eur,conversions,revenue_eur,cpc_eur,cpa_eur,roas"
            if header_line == expected_header:
                weekly_structure_ok = True
                weekly_rows = _parse_weekly_summary(weekly_summary_path)
        except Exception:
            weekly_structure_ok = False
    scores["weekly_summary_has_required_columns"] = 1.0 if weekly_structure_ok else 0.0

    # Compute expected weekly summary from inputs and ECB
    expected_summary = {}  # (week_start_str, campaign) -> dict with metrics
    can_compute_expected = need_checks
    if can_compute_expected:
        # Build rate lookup with fallback for USD/GBP
        # Prepare combined per date-campaign accumulators
        # Sum clicks and cost_eur from spend; conversions and revenue_eur from conversions.
        # Then aggregate by week and campaign.
        per_key = {}  # (date, campaign) -> dict accum
        # Process spend
        for r in spend_rows:
            ds = (r.get("date") or "").strip()
            camp = (r.get("campaign") or "").strip()
            clicks = _to_float(r.get("clicks"))
            cost = _to_float(r.get("cost"))
            cur = (r.get("currency") or "").strip()
            d = _parse_date(ds)
            if ds == "" or camp == "" or clicks is None or cost is None or d is None:
                can_compute_expected = False
                break
            if (ds, camp) not in per_key:
                per_key[(ds, camp)] = {"clicks": 0.0, "cost_eur": 0.0, "conversions": 0.0, "revenue_eur": 0.0}
            if cur == "EUR":
                cost_eur = cost
            elif cur in ("USD", "GBP"):
                rate_date, rate_val = _get_rate_date_and_value(ecb_data, cur, ds)
                if rate_val is None:
                    can_compute_expected = False
                    break
                cost_eur = cost / rate_val
            else:
                # Unexpected currency; cannot compute
                can_compute_expected = False
                break
            per_key[(ds, camp)]["clicks"] += clicks
            per_key[(ds, camp)]["cost_eur"] += cost_eur

        # Process conversions
        if can_compute_expected:
            for r in conv_rows:
                ds = (r.get("date") or "").strip()
                camp = (r.get("campaign") or "").strip()
                convs = _to_float(r.get("conversions"))
                rev = _to_float(r.get("revenue"))
                cur = (r.get("currency") or "").strip()
                d = _parse_date(ds)
                if ds == "" or camp == "" or convs is None or rev is None or d is None:
                    can_compute_expected = False
                    break
                if (ds, camp) not in per_key:
                    per_key[(ds, camp)] = {"clicks": 0.0, "cost_eur": 0.0, "conversions": 0.0, "revenue_eur": 0.0}
                if cur == "EUR":
                    rev_eur = rev
                elif cur in ("USD", "GBP"):
                    rate_date, rate_val = _get_rate_date_and_value(ecb_data, cur, ds)
                    if rate_val is None:
                        can_compute_expected = False
                        break
                    rev_eur = rev / rate_val
                else:
                    can_compute_expected = False
                    break
                per_key[(ds, camp)]["conversions"] += convs
                per_key[(ds, camp)]["revenue_eur"] += rev_eur

        # Aggregate by week and campaign
        if can_compute_expected:
            by_week_campaign = {}
            for (ds, camp), vals in per_key.items():
                d = _parse_date(ds)
                if d is None:
                    can_compute_expected = False
                    break
                week_start = _format_date(_week_monday(d))
                k = (week_start, camp)
                if k not in by_week_campaign:
                    by_week_campaign[k] = {"clicks": 0.0, "cost_eur": 0.0, "conversions": 0.0, "revenue_eur": 0.0}
                agg = by_week_campaign[k]
                agg["clicks"] += vals["clicks"]
                agg["cost_eur"] += vals["cost_eur"]
                agg["conversions"] += vals["conversions"]
                agg["revenue_eur"] += vals["revenue_eur"]
            # Compute derived metrics and rounding
            if can_compute_expected:
                for k, agg in by_week_campaign.items():
                    clicks = agg["clicks"]
                    convs = agg["conversions"]
                    cost_eur = agg["cost_eur"]
                    rev_eur = agg["revenue_eur"]
                    cpc = cost_eur / clicks if clicks else 0.0
                    cpa = cost_eur / convs if convs else 0.0
                    roas = rev_eur / cost_eur if cost_eur else 0.0
                    expected_summary[k] = {
                        "clicks": int(round(clicks)),
                        "cost_eur": _round2(cost_eur),
                        "conversions": int(round(convs)),
                        "revenue_eur": _round2(rev_eur),
                        "cpc_eur": _round2(cpc),
                        "cpa_eur": _round2(cpa),
                        "roas": _round2(roas),
                    }

    # Validate weekly summary values for specific weeks
    def _check_week_values(week_start_str: str) -> bool:
        if not weekly_structure_ok or weekly_rows is None or not can_compute_expected:
            return False
        # Build mapping from file
        file_map = {}
        for r in weekly_rows:
            ws = (r.get("week_start_date") or "").strip()
            camp = (r.get("campaign") or "").strip()
            if ws == "" or camp == "":
                continue
            key = (ws, camp)
            try:
                clicks = int(float(r.get("clicks", "0").strip()))
            except Exception:
                return False
            ce = _to_float(r.get("cost_eur"))
            convs = _to_float(r.get("conversions"))
            rev = _to_float(r.get("revenue_eur"))
            cpc = _to_float(r.get("cpc_eur"))
            cpa = _to_float(r.get("cpa_eur"))
            roas = _to_float(r.get("roas"))
            file_map[key] = {
                "clicks": clicks,
                "cost_eur": ce,
                "conversions": int(round(convs)) if convs is not None else None,
                "revenue_eur": rev,
                "cpc_eur": cpc,
                "cpa_eur": cpa,
                "roas": roas,
            }
        # For the expected keys for this week, ensure presence and values
        ok = True
        for (ws, camp), exp in expected_summary.items():
            if ws != week_start_str:
                continue
            if (ws, camp) not in file_map:
                ok = False
                break
            got = file_map[(ws, camp)]
            # Compare all fields
            if got["clicks"] != exp["clicks"]:
                ok = False
                break
            if got["conversions"] != exp["conversions"]:
                ok = False
                break
            for k in ("cost_eur", "revenue_eur", "cpc_eur", "cpa_eur", "roas"):
                gv = got[k]
                ev = exp[k]
                if gv is None:
                    ok = False
                    break
                if abs(gv - ev) > 0.01:
                    ok = False
                    break
            if not ok:
                break
        return ok

    scores["weekly_summary_values_2021_06_14"] = 1.0 if _check_week_values("2021-06-14") else 0.0
    scores["weekly_summary_values_2021_06_21"] = 1.0 if _check_week_values("2021-06-21") else 0.0

    # Status update checks
    status_text = _read_text(status_md_path) if status_md_path.exists() else None
    if status_text is not None:
        # Word count between 150 and 250
        words = re.findall(r"\b\w+\b", status_text)
        wc_ok = 150 <= len(words) <= 250
        scores["status_update_length"] = 1.0 if wc_ok else 0.0

        # Sections and sources
        contains_data_sources = re.search(r"data sources", status_text, flags=re.IGNORECASE) is not None
        contains_next_steps = re.search(r"next steps", status_text, flags=re.IGNORECASE) is not None
        has_spend = "input/ppc_spend.csv" in status_text
        has_conv = "input/ppc_conversions.csv" in status_text
        has_targets = "input/targets.json" in status_text
        has_ecb = "output/downloads/eurofxref-hist.csv" in status_text
        sections_sources_ok = contains_data_sources and contains_next_steps and has_spend and has_conv and has_targets and has_ecb
        scores["status_update_contains_sections_and_sources"] = 1.0 if sections_sources_ok else 0.0

        # Mentions CPA, ROAS, EUR, and dates
        mentions_metrics_dates = (
            re.search(r"\bcpa\b", status_text, flags=re.IGNORECASE) is not None
            and re.search(r"\broas\b", status_text, flags=re.IGNORECASE) is not None
            and re.search(r"\beur\b", status_text, flags=re.IGNORECASE) is not None
            and "2021-06-14" in status_text
            and "2021-06-21" in status_text
        )
        scores["status_update_mentions_metrics_and_dates"] = 1.0 if mentions_metrics_dates else 0.0

        # Next steps coverage: actionable per campaign that missed any target (based on expected)
        next_steps_ok = False
        if can_compute_expected:
            targets = _load_json(targets_path) if targets_path.exists() else None
            if isinstance(targets, dict) and "targets" in targets and isinstance(targets["targets"], list):
                tgt_map = {}
                for t in targets["targets"]:
                    camp = t.get("campaign")
                    cpa_t = _to_float(t.get("target_cpa_eur"))
                    roas_t = _to_float(t.get("target_roas"))
                    if camp and cpa_t is not None and roas_t is not None:
                        tgt_map[camp] = {"cpa": cpa_t, "roas": roas_t}
                # Determine missed campaigns across the two specified weeks
                missed = set()
                for week in ("2021-06-14", "2021-06-21"):
                    for (ws, camp), vals in expected_summary.items():
                        if ws != week:
                            continue
                        if camp not in tgt_map:
                            continue
                        cpa_t = tgt_map[camp]["cpa"]
                        roas_t = tgt_map[camp]["roas"]
                        # Met if both: CPA <= target AND ROAS >= target
                        cpa_met = vals["cpa_eur"] <= cpa_t
                        roas_met = vals["roas"] >= roas_t
                        if not (cpa_met and roas_met):
                            missed.add(camp)
                # Check that after "Next steps" all missed campaigns are mentioned
                m = re.search(r"next steps", status_text, flags=re.IGNORECASE)
                if m:
                    after_text = status_text[m.start():]
                    all_present = all(camp in after_text for camp in missed) if missed else True
                    next_steps_ok = all_present
        scores["status_update_next_steps_for_missed_campaigns"] = 1.0 if next_steps_ok else 0.0
    else:
        scores["status_update_length"] = 0.0
        scores["status_update_contains_sections_and_sources"] = 0.0
        scores["status_update_mentions_metrics_and_dates"] = 0.0
        scores["status_update_next_steps_for_missed_campaigns"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()