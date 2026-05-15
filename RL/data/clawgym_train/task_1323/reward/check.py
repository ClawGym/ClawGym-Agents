import json
import os
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_numeric(s):
    try:
        if s is None:
            return False
        s_str = str(s).strip()
        if s_str == "":
            return False
        float(s_str)
        return True
    except Exception:
        return False

def parse_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def parse_csv_dicts(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return reader.fieldnames, rows
    except Exception:
        return None, None

def last_nonempty_stdout(obj):
    print(json.dumps(obj))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}
    # Initialize overall reward to 0.0 by default (no-op baseline)
    reward_value = 0.0

    # Read input portfolio.json
    portfolio_path = os.path.join(input_dir, "portfolio.json")
    portfolio = read_json(portfolio_path)
    parsed_input = False
    ts_codes = []
    start_date = None
    end_date = None
    if isinstance(portfolio, dict):
        start_date = portfolio.get("start_date")
        end_date = portfolio.get("end_date")
        ts_codes = portfolio.get("ts_codes") if isinstance(portfolio.get("ts_codes"), list) else []
        if isinstance(start_date, str) and isinstance(end_date, str) and len(start_date) == 8 and len(end_date) == 8 and all(isinstance(x, str) for x in ts_codes):
            parsed_input = True
    checks["parsed_input"] = parsed_input

    # If no stocks provided, cannot score positively.
    if not parsed_input or not ts_codes:
        result = {"reward": 0.0}
        result.update(checks)
        return last_nonempty_stdout(result)

    N = len(ts_codes)

    # Weights
    # Daily CSV checks total weight: 0.40 distributed per stock
    w_daily_exist = 0.10 / N
    w_daily_header = 0.05 / N
    w_daily_rows = 0.05 / N
    w_daily_date_range = 0.07 / N
    w_daily_sorted = 0.07 / N
    w_daily_ma20 = 0.03 / N
    w_daily_ma60 = 0.03 / N

    # Metrics checks total: 0.30
    w_metrics_exist = 0.05
    w_metrics_header = 0.05
    w_metrics_rows_cover = 0.05
    w_metrics_td_match = 0.10 / N
    w_metrics_counts_ints = 0.05 / N

    # API calls total: 0.15
    w_api_exist = 0.05
    w_api_per_stock = 0.10 / N

    # Report total: 0.15
    w_report_exist = 0.03
    w_report_title = 0.04
    w_report_methodology = 0.04
    w_report_per_stock = 0.04 / N

    # Prepare data structures
    daily_row_counts = {}
    # Daily files validation
    daily_header_expected = "date,close,ma20,ma60,daily_return"
    for ts in ts_codes:
        key_prefix = ts.replace(".", "_")
        csv_rel = os.path.join("output", "data", f"daily_{ts}.csv")
        csv_abs = os.path.join(output_dir, "data", f"daily_{ts}.csv")

        exist_key = f"daily_exists_{key_prefix}"
        header_key = f"daily_header_ok_{key_prefix}"
        rows_key = f"daily_rows_ge_10_{key_prefix}"
        range_key = f"daily_dates_in_range_{key_prefix}"
        sorted_key = f"daily_sorted_{key_prefix}"
        ma20_key = f"daily_ma20_any_{key_prefix}"
        ma60_key = f"daily_ma60_any_{key_prefix}"

        checks[exist_key] = False
        checks[header_key] = False
        checks[rows_key] = False
        checks[range_key] = False
        checks[sorted_key] = False
        checks[ma20_key] = False
        checks[ma60_key] = False

        if os.path.isfile(csv_abs):
            checks[exist_key] = True
            # Header exact match check
            text = read_text(csv_abs)
            if text is not None:
                lines = text.splitlines()
                if lines:
                    first_line = lines[0].strip()
                    if first_line == daily_header_expected:
                        checks[header_key] = True

            # Parse CSV rows and perform further checks
            rows = parse_csv_rows(csv_abs)
            if rows is not None and len(rows) >= 2:
                data_rows = rows[1:]
                daily_row_counts[ts] = len(data_rows)
                if len(data_rows) >= 10:
                    checks[rows_key] = True

                # Extract columns by index assuming exact header ordering
                dates = []
                ma20_any = False
                ma60_any = False
                all_dates_ok = True
                if len(rows[0]) >= 5:
                    for r in data_rows:
                        if len(r) < 5:
                            all_dates_ok = False
                            break
                        d = r[0].strip()
                        # date format: 8-digit numeric, within [start_date, end_date]
                        if not (len(d) == 8 and d.isdigit()):
                            all_dates_ok = False
                        else:
                            if start_date is not None and d < start_date:
                                all_dates_ok = False
                            if end_date is not None and d > end_date:
                                all_dates_ok = False
                        dates.append(d)
                        # ma20 present somewhere
                        m20 = r[2].strip() if len(r) > 2 else ""
                        m60 = r[3].strip() if len(r) > 3 else ""
                        if is_numeric(m20):
                            ma20_any = True
                        if is_numeric(m60):
                            ma60_any = True
                    if all_dates_ok and dates:
                        checks[range_key] = True
                        # sorted ascending
                        if dates == sorted(dates):
                            checks[sorted_key] = True
                    if ma20_any:
                        checks[ma20_key] = True
                    if ma60_any:
                        checks[ma60_key] = True
            else:
                daily_row_counts[ts] = 0
        else:
            daily_row_counts[ts] = 0

        # Accumulate reward for daily checks per stock
        if checks[exist_key]:
            reward_value += w_daily_exist
        if checks[header_key]:
            reward_value += w_daily_header
        if checks[rows_key]:
            reward_value += w_daily_rows
        if checks[range_key]:
            reward_value += w_daily_date_range
        if checks[sorted_key]:
            reward_value += w_daily_sorted
        if checks[ma20_key]:
            reward_value += w_daily_ma20
        if checks[ma60_key]:
            reward_value += w_daily_ma60

    # Metrics CSV validation
    metrics_path = os.path.join(output_dir, "summary", "metrics.csv")
    checks["metrics_exists"] = os.path.isfile(metrics_path)
    metrics_header_expected = "ts_code,start_date,end_date,trading_days,mean_daily_return,std_daily_return,cumulative_return,max_drawdown_pct,golden_cross_dates_count,death_cross_dates_count"
    checks["metrics_header_ok"] = False
    checks["metrics_rows_cover_all"] = False

    metrics_rows_by_ts = {}
    if checks["metrics_exists"]:
        text = read_text(metrics_path)
        if text is not None:
            lines = text.splitlines()
            if lines:
                if lines[0].strip() == metrics_header_expected:
                    checks["metrics_header_ok"] = True
        # Parse with DictReader
        fieldnames, rows = parse_csv_dicts(metrics_path)
        if rows is not None:
            for r in rows:
                ts = r.get("ts_code")
                if ts:
                    metrics_rows_by_ts[ts] = r
            # Ensure coverage of all ts_codes
            if all(ts in metrics_rows_by_ts for ts in ts_codes) and len(metrics_rows_by_ts) >= len(ts_codes):
                checks["metrics_rows_cover_all"] = True

    if checks["metrics_exists"]:
        reward_value += w_metrics_exist
    if checks["metrics_header_ok"]:
        reward_value += w_metrics_header
    if checks["metrics_rows_cover_all"]:
        reward_value += w_metrics_rows_cover

    # For each stock: trading_days match and counts ints
    for ts in ts_codes:
        key_prefix = ts.replace(".", "_")
        td_match_key = f"metrics_trading_days_match_{key_prefix}"
        counts_ints_key = f"metrics_counts_ints_{key_prefix}"
        checks[td_match_key] = False
        checks[counts_ints_key] = False

        row = metrics_rows_by_ts.get(ts)
        if row:
            # trading_days matches daily rows count
            td = row.get("trading_days")
            try:
                td_int = int(str(td).strip())
                if td_int > 0 and daily_row_counts.get(ts, -1) == td_int:
                    checks[td_match_key] = True
            except Exception:
                checks[td_match_key] = False

            # counts are non-negative integers, and numeric stats parseable
            try:
                g = int(str(row.get("golden_cross_dates_count", "")).strip())
                d = int(str(row.get("death_cross_dates_count", "")).strip())
                if g >= 0 and d >= 0:
                    # Check numeric stats parseable
                    mean_ok = is_numeric(row.get("mean_daily_return", ""))
                    std_ok = is_numeric(row.get("std_daily_return", ""))
                    cum_ok = is_numeric(row.get("cumulative_return", ""))
                    mdd_ok = is_numeric(row.get("max_drawdown_pct", ""))
                    if mean_ok and std_ok and cum_ok and mdd_ok:
                        checks[counts_ints_key] = True
            except Exception:
                checks[counts_ints_key] = False

        if checks[td_match_key]:
            reward_value += w_metrics_td_match
        if checks[counts_ints_key]:
            reward_value += w_metrics_counts_ints

    # API calls jsonl validation
    api_calls_path = os.path.join(output_dir, "cache", "api_calls.jsonl")
    checks["api_calls_exists"] = os.path.isfile(api_calls_path)
    api_lines = []
    if checks["api_calls_exists"]:
        try:
            with open(api_calls_path, "r", encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        obj = json.loads(ln)
                        api_lines.append(obj)
                    except Exception:
                        pass
        except Exception:
            pass

    if checks["api_calls_exists"]:
        reward_value += w_api_exist

    for ts in ts_codes:
        key_prefix = ts.replace(".", "_")
        api_key = f"api_calls_per_stock_{key_prefix}"
        checks[api_key] = False
        if api_lines:
            # At least one line where endpoint is a string and params is an object and params.ts_code == ts
            found = False
            for obj in api_lines:
                endpoint = obj.get("endpoint")
                params = obj.get("params")
                if isinstance(endpoint, str) and isinstance(params, dict):
                    p_ts = params.get("ts_code")
                    if isinstance(p_ts, str) and p_ts == ts:
                        found = True
                        break
            if found:
                checks[api_key] = True
                reward_value += w_api_per_stock

    # Report validation
    report_path = os.path.join(output_dir, "report.md")
    checks["report_exists"] = os.path.isfile(report_path)
    checks["report_title_ok"] = False
    checks["report_methodology_section"] = False

    report_text = None
    report_lines = []
    if checks["report_exists"]:
        report_text = read_text(report_path)
        if report_text is not None:
            report_lines = report_text.splitlines()
            if report_lines:
                first_line = report_lines[0].strip()
                if first_line.startswith("# A-Share Portfolio Technical Summary"):
                    checks["report_title_ok"] = True
            # Check methodology section
            for line in report_lines:
                if line.strip() == "## Methodology & Caveats":
                    checks["report_methodology_section"] = True
                    break

    if checks["report_exists"]:
        reward_value += w_report_exist
    if checks["report_title_ok"]:
        reward_value += w_report_title
    if checks["report_methodology_section"]:
        reward_value += w_report_methodology

    # For each stock: section with at least three bullet points
    for ts in ts_codes:
        key_prefix = ts.replace(".", "_")
        sect_key = f"report_section_{key_prefix}_bullets_ok"
        checks[sect_key] = False
        if report_lines:
            # Find section header "## {ts}"
            bullets = 0
            in_section = False
            for i, line in enumerate(report_lines):
                if line.strip() == f"## {ts}":
                    in_section = True
                    # Count subsequent bullet lines until next section header or EOF
                    for j in range(i + 1, len(report_lines)):
                        l2 = report_lines[j]
                        if l2.strip().startswith("## "):
                            break
                        if l2.strip().startswith("- "):
                            bullets += 1
                    break
            if in_section and bullets >= 3:
                checks[sect_key] = True
                reward_value += w_report_per_stock

    # Ensure reward is within [0,1]
    if reward_value < 0:
        reward_value = 0.0
    if reward_value > 1:
        reward_value = 1.0

    # If no output artifacts exist at all, keep reward at 0.0
    # Define "no artifacts" as missing all four categories: daily any, metrics, api_calls, report
    any_daily = any(checks.get(f"daily_exists_{ts.replace('.', '_')}", False) for ts in ts_codes)
    if not any_daily and not checks.get("metrics_exists") and not checks.get("api_calls_exists") and not checks.get("report_exists"):
        reward_value = 0.0

    result = {"reward": float(reward_value)}
    result.update(checks)
    return last_nonempty_stdout(result)

if __name__ == "__main__":
    main()