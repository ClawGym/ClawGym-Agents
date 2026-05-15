import json
import os
import sys
import re
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_csv_dicts(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception:
        pass
    return rows

def normalize_kind(val):
    if isinstance(val, str):
        return val.strip().lower()
    return ""

def has_header(lines, title_options):
    # title_options: list of strings to check as header lines
    if not isinstance(title_options, (list, tuple)):
        title_options = [title_options]
    pattern_opts = [re.compile(r'^\s*#+\s*' + re.escape(opt) + r'\b', re.IGNORECASE) for opt in title_options]
    for line in lines:
        for p in pattern_opts:
            if p.search(line):
                return True
    return False

def percentage_pattern_present(text):
    return re.search(r'\b\d{1,3}(\.\d+)?\s?%(\b|)', text) is not None

def line_starts_with_h1(lines):
    if not lines:
        return False
    return re.match(r'^\s*#\s+\S+', lines[0]) is not None

def count_watchlist_tickers_mentions(text, watchlist_tickers):
    count = 0
    seen = set()
    for tk in watchlist_tickers:
        if not tk:
            continue
        # Match as a whole token; allow digits and letters
        if re.search(r'\b' + re.escape(tk) + r'\b', text):
            if tk not in seen:
                seen.add(tk)
                count += 1
    return count

def find_section_index(text, section_title):
    # returns index in text where section starts, or -1
    m = re.search(r'^\s*#+\s*' + re.escape(section_title) + r'\b.*$', text, flags=re.IGNORECASE | re.MULTILINE)
    if not m:
        return -1
    return m.start()

def sanitize_float(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    s = s.replace('%', '')
    try:
        return float(s)
    except Exception:
        return None

def has_no_absolute_paths(lines):
    # No lines starting with '/' (absolute Unix paths)
    for ln in lines:
        if ln.lstrip().startswith("/"):
            return False
    return True

def tool_servers_have_names_and_tools(servers):
    if not isinstance(servers, list):
        return False
    for s in servers:
        name_ok = isinstance(s.get("name"), str) and s.get("name").strip() != ""
        tools_ok = isinstance(s.get("tools"), list) and len(s.get("tools")) > 0
        if not (name_ok and tools_ok):
            return False
    return True

def route_rules_nonempty(rr):
    if not isinstance(rr, dict):
        return False
    if len(rr) < 1:
        return False
    # Check at least one mapping has a non-empty fallback
    for k, v in rr.items():
        if v is None:
            continue
        if isinstance(v, (list, dict, str)):
            if isinstance(v, str):
                if v.strip() != "":
                    return True
            elif isinstance(v, list):
                if len(v) > 0:
                    return True
            elif isinstance(v, dict):
                if len(v) > 0:
                    return True
        else:
            # any truthy value is acceptable
            if v:
                return True
    return False

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Initialize checks
checks = {
    # briefing.md checks
    "briefing_exists": False,
    "briefing_nonempty": False,
    "briefing_h1_title": False,
    "briefing_has_market_overview": False,
    "briefing_has_sector_rankings": False,
    "briefing_has_stock_deep_dives": False,
    "briefing_has_disclosures_section": False,
    "briefing_has_alerts_plan": False,
    "briefing_has_fork_judgment_section": False,
    "briefing_mentions_three_watchlist_tickers": False,
    "briefing_has_percentage_pattern": False,
    "fork_keywords_present": False,

    # tool_config.json checks
    "tool_config_valid_json": False,
    "tool_config_servers_ge2": False,
    "tool_config_has_http_server": False,
    "tool_config_has_stdio_server": False,
    "tool_config_servers_named_with_tools": False,
    "tool_config_has_route_rules": False,

    # pipeline.py checks
    "pipeline_exists": False,
    "pipeline_has_random_state": False,
    "pipeline_has_data_paths_input": False,
    "pipeline_has_load_data_function": False,
    "pipeline_mentions_sklearn_pipeline": False,
    "pipeline_has_main_block": False,
    "pipeline_no_absolute_paths": False,

    # alerts.json checks
    "alerts_is_list": False,
    "alerts_match_down_3": False,
}

# Paths
brief_path = os.path.join(output_dir, "briefing.md")
tool_path = os.path.join(output_dir, "tool_config.json")
pipe_path = os.path.join(output_dir, "pipeline.py")
alerts_path = os.path.join(output_dir, "alerts.json")

watchlist_path = os.path.join(input_dir, "watchlist.csv")
prices_path = os.path.join(input_dir, "korea_prices.csv")

# Check briefing.md
if os.path.isfile(brief_path):
    checks["briefing_exists"] = True
    briefing_text = read_text(brief_path)
    if briefing_text.strip():
        checks["briefing_nonempty"] = True
    lines = briefing_text.splitlines()

    if line_starts_with_h1(lines):
        checks["briefing_h1_title"] = True

    if has_header(lines, ["Market Overview"]):
        checks["briefing_has_market_overview"] = True
    if has_header(lines, ["Sector Rankings"]):
        checks["briefing_has_sector_rankings"] = True
    if has_header(lines, ["Stock Deep Dives"]):
        checks["briefing_has_stock_deep_dives"] = True
    if has_header(lines, ["DART Disclosures", "Disclosures"]):
        checks["briefing_has_disclosures_section"] = True
    if has_header(lines, ["Alerts Plan"]):
        checks["briefing_has_alerts_plan"] = True
    if has_header(lines, ["Fork Judgment"]):
        checks["briefing_has_fork_judgment_section"] = True

    if percentage_pattern_present(briefing_text):
        checks["briefing_has_percentage_pattern"] = True

    # Watchlist tickers mention check
    watchlist_rows = load_csv_dicts(watchlist_path)
    watchlist_tickers = []
    for r in watchlist_rows:
        tk = (r.get("ticker") or "").strip()
        if tk:
            watchlist_tickers.append(tk)
    if watchlist_tickers:
        mentioned = count_watchlist_tickers_mentions(briefing_text, watchlist_tickers)
        if mentioned >= 3:
            checks["briefing_mentions_three_watchlist_tickers"] = True

    # Fork keywords within Fork Judgment section
    fork_index = find_section_index(briefing_text, "Fork Judgment")
    fork_text = briefing_text[fork_index:] if fork_index >= 0 else briefing_text
    kw_ok = (
        re.search(r'\bTruth signal\b', fork_text, re.IGNORECASE) is not None
        and re.search(r'\bDistortion signal\b', fork_text, re.IGNORECASE) is not None
        and re.search(r'\bBifurcation decision\b', fork_text, re.IGNORECASE) is not None
        and re.search(r'\bReceipts\b', fork_text, re.IGNORECASE) is not None
    )
    if kw_ok:
        checks["fork_keywords_present"] = True

# Check tool_config.json
tool_obj = None
if os.path.isfile(tool_path):
    tool_obj = load_json(tool_path)
    if isinstance(tool_obj, dict):
        checks["tool_config_valid_json"] = True
        servers = tool_obj.get("servers")
        if isinstance(servers, list) and len(servers) >= 2:
            checks["tool_config_servers_ge2"] = True
            # kind checks
            kinds = [normalize_kind(s.get("kind")) for s in servers if isinstance(s, dict)]
            if any(k == "http" for k in kinds):
                checks["tool_config_has_http_server"] = True
            if any(k == "stdio" for k in kinds):
                checks["tool_config_has_stdio_server"] = True
            if tool_servers_have_names_and_tools(servers):
                checks["tool_config_servers_named_with_tools"] = True
        rr = tool_obj.get("route_rules")
        if route_rules_nonempty(rr):
            checks["tool_config_has_route_rules"] = True

# Check pipeline.py
if os.path.isfile(pipe_path):
    checks["pipeline_exists"] = True
    pipe_text = read_text(pipe_path)
    pipe_lines = pipe_text.splitlines()

    if re.search(r'RANDOM_STATE\s*=\s*\d+', pipe_text):
        checks["pipeline_has_random_state"] = True

    data_paths_defined = re.search(r'DATA_PATHS\s*=\s*\{', pipe_text) is not None
    mentions_input_paths = 'input/' in pipe_text
    if data_paths_defined and mentions_input_paths:
        checks["pipeline_has_data_paths_input"] = True

    if re.search(r'^\s*def\s+load_data\s*\(', pipe_text, re.MULTILINE):
        checks["pipeline_has_load_data_function"] = True

    if "sklearn.pipeline.Pipeline" in pipe_text:
        checks["pipeline_mentions_sklearn_pipeline"] = True

    if re.search(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]\s*:', pipe_text):
        checks["pipeline_has_main_block"] = True

    if has_no_absolute_paths(pipe_lines):
        checks["pipeline_no_absolute_paths"] = True

# Check alerts.json
alerts_list = None
if os.path.isfile(alerts_path):
    obj = load_json(alerts_path)
    if isinstance(obj, list):
        alerts_list = obj
        checks["alerts_is_list"] = True

    # Compute expected down_3 tickers based on inputs
    expected_down = set()
    watchlist_rows = load_csv_dicts(watchlist_path)
    prices_rows = load_csv_dicts(prices_path)
    wl_tickers = set()
    for r in watchlist_rows:
        tk = (r.get("ticker") or "").strip()
        if tk:
            wl_tickers.add(tk)
    price_changes = {}
    for r in prices_rows:
        tk = (r.get("ticker") or "").strip()
        ch = sanitize_float(r.get("change"))
        if tk and ch is not None:
            price_changes[tk] = ch
    for tk in wl_tickers:
        ch = price_changes.get(tk)
        if ch is not None and ch <= -3.0:
            expected_down.add(tk)

    # Validate alerts content
    alerts_ok = False
    if alerts_list is not None:
        if len(expected_down) == 0:
            # Must be empty list
            alerts_ok = (len(alerts_list) == 0)
        else:
            # For each expected ticker, there must be at least one alert object with event == "down_3"
            found = set()
            for itm in alerts_list:
                if not isinstance(itm, dict):
                    continue
                tk = (itm.get("ticker") or "").strip()
                ev = itm.get("event")
                if tk in expected_down and ev == "down_3":
                    found.add(tk)
            alerts_ok = (expected_down.issubset(found))
    if alerts_ok:
        checks["alerts_match_down_3"] = True

# Compute reward as average of passed checks
passed = sum(1 for v in checks.values() if v)
total = len(checks)
reward = (passed / total) if total > 0 else 0.0
# No-op baseline: if no outputs exist at all, ensure reward 0.0
outputs_exist = any(os.path.isfile(p) for p in [brief_path, tool_path, pipe_path, alerts_path])
if not outputs_exist:
    reward = 0.0

result = {"reward": reward}
result.update(checks)
print(json.dumps(result))