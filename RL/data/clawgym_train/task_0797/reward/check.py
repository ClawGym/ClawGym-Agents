import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def first_non_empty_line(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    return line.rstrip("\n")
        return None
    except Exception:
        return None

def dir_has_files(path):
    if not os.path.isdir(path):
        return False
    for root, dirs, files in os.walk(path):
        if files:
            return True
    return False

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

checks = {
    "summary_ok": False,
    "allocation_ok": False,
    "performance_ok": False,
    "risk_ok": False,
    "sectors_ok": False,
    "rebalance_ok": False,
    "dca_aapl_ok": False,
    "dca_eth_ok": False,
    "dividends_ok": False,
    "compare_nvda_googl_ok": False,
    "export_csv_ok": False,
    "export_json_ok": False,
    "rationale_ok": False,
}

# 1) summary.txt
summary_path = os.path.join(output_dir, "summary.txt")
summary_text = read_text(summary_path)
if summary_text is not None:
    has_heading = "Portfolio Summary" in summary_text
    has_total_value = "Total Value:" in summary_text
    has_pl = "P/L:" in summary_text
    if has_heading and has_total_value and has_pl:
        checks["summary_ok"] = True

# 2) allocation.txt
allocation_path = os.path.join(output_dir, "allocation.txt")
allocation_text = read_text(allocation_path)
if allocation_text is not None:
    has_heading = "Asset Allocation" in allocation_text
    has_aapl = "AAPL" in allocation_text
    has_btc = "BTC" in allocation_text
    if has_heading and has_aapl and has_btc:
        checks["allocation_ok"] = True

# 3) performance.txt
performance_path = os.path.join(output_dir, "performance.txt")
performance_text = read_text(performance_path)
if performance_text is not None:
    has_heading = "Performance Analysis" in performance_text
    has_any_ticker = ("AAPL" in performance_text) or ("NVDA" in performance_text)
    if has_heading and has_any_ticker:
        checks["performance_ok"] = True

# 4) risk.txt
risk_path = os.path.join(output_dir, "risk.txt")
risk_text = read_text(risk_path)
if risk_text is not None:
    has_heading = "Risk Assessment" in risk_text
    has_diversification = "Diversification:" in risk_text
    if has_heading and has_diversification:
        checks["risk_ok"] = True

# 5) sectors.txt
sectors_path = os.path.join(output_dir, "sectors.txt")
sectors_text = read_text(sectors_path)
if sectors_text is not None:
    has_heading = "Sector Breakdown" in sectors_text
    has_tech = "Technology" in sectors_text
    has_crypto = "Crypto" in sectors_text
    if has_heading and has_tech and has_crypto:
        checks["sectors_ok"] = True

# 6) rebalance.txt
rebalance_path = os.path.join(output_dir, "rebalance.txt")
rebalance_text = read_text(rebalance_path)
if rebalance_text is not None:
    has_heading = "Rebalance Suggestions" in rebalance_text
    has_aapl = "AAPL" in rebalance_text
    has_googl = "GOOGL" in rebalance_text
    has_btc = "BTC" in rebalance_text
    if has_heading and has_aapl and has_googl and has_btc:
        checks["rebalance_ok"] = True

# 7) dca_AAPL.txt
dca_aapl_path = os.path.join(output_dir, "dca_AAPL.txt")
dca_aapl_text = read_text(dca_aapl_path)
if dca_aapl_text is not None:
    has_title = "DCA Calculator: AAPL" in dca_aapl_text
    has_total = "Total invested after 12 months" in dca_aapl_text
    if has_title and has_total:
        checks["dca_aapl_ok"] = True

# 8) dca_ETH.txt
dca_eth_path = os.path.join(output_dir, "dca_ETH.txt")
dca_eth_text = read_text(dca_eth_path)
if dca_eth_text is not None:
    has_title = "DCA Calculator: ETH" in dca_eth_text
    has_total = "Total invested after 12 months" in dca_eth_text
    if has_title and has_total:
        checks["dca_eth_ok"] = True

# 9) dividends.txt
dividends_path = os.path.join(output_dir, "dividends.txt")
dividends_text = read_text(dividends_path)
if dividends_text is not None:
    count_yield = dividends_text.count("Dividend Yield:")
    has_breakdown = ("Annual:" in dividends_text) or ("Quarterly:" in dividends_text)
    if count_yield >= 2 and has_breakdown:
        checks["dividends_ok"] = True

# 10) compare_NVDA_GOOGL.txt
compare_path = os.path.join(output_dir, "compare_NVDA_GOOGL.txt")
compare_text = read_text(compare_path)
if compare_text is not None:
    has_nvda = "NVDA" in compare_text
    has_googl = "GOOGL" in compare_text
    has_shares = "Shares" in compare_text
    if has_nvda and has_googl and has_shares:
        checks["compare_nvda_googl_ok"] = True

# 11) portfolio_export.csv
export_csv_path = os.path.join(output_dir, "portfolio_export.csv")
header_line = first_non_empty_line(export_csv_path)
if header_line is not None and header_line.strip() == "ticker,shares,buy_price,current_price,date":
    checks["export_csv_ok"] = True

# 12) portfolio_export.json
export_json_path = os.path.join(output_dir, "portfolio_export.json")
export_json_text = read_text(export_json_path)
valid_json = False
has_ticker_substring = False
if export_json_text is not None:
    try:
        parsed = json.loads(export_json_text)
        valid_json = True
    except Exception:
        valid_json = False
    has_ticker_substring = '"ticker"' in export_json_text
if valid_json and has_ticker_substring:
    checks["export_json_ok"] = True

# 13) rebalance_rationale.md
rationale_path = os.path.join(output_dir, "rebalance_rationale.md")
rationale_text = read_text(rationale_path)
if rationale_text is not None:
    words = [w for w in rationale_text.split() if w.strip()]
    word_count = len(words)
    lower = rationale_text.lower()
    has_keywords = ("rebalance" in lower) and ("risk" in lower)
    tickers = ["AAPL", "GOOGL", "NVDA", "BTC", "ETH", "JNJ", "XOM"]
    ticker_count = sum(1 for t in tickers if t in rationale_text)
    if word_count >= 150 and has_keywords and ticker_count >= 3:
        checks["rationale_ok"] = True

# Compute reward
total_checks = len(checks)
passed_checks = sum(1 for v in checks.values() if v)

# No-op baseline: if output directory is missing or has no files, reward must be 0.0
if not dir_has_files(output_dir):
    reward = 0.0
else:
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

result = {"reward": reward}
result.update(checks)
print(json.dumps(result))