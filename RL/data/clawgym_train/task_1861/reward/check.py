import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def parse_json_maybe_array_or_jsonl(path):
    # Returns (ok, records_list)
    text = read_text(path)
    if text is None:
        return False, []
    text_stripped = text.strip()
    # Try JSON array first
    try:
        parsed = json.loads(text_stripped)
        if isinstance(parsed, list):
            return True, parsed
        else:
            # Not a list; fall through to JSONL attempt
            pass
    except Exception:
        # Try JSONL
        pass
    # JSONL: one JSON object per non-empty line
    lines = text.splitlines()
    records = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
            records.append(obj)
        except Exception:
            return False, []
    # If there were no non-empty lines, treat as empty list (but still ok parse)
    return True, records

def count_words(s):
    # Count tokens separated by whitespace
    tokens = re.findall(r"\S+", s)
    return len(tokens)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "csv_exists": False,
        "csv_header_ok": False,
        "csv_has_rows": False,
        "json_exists": False,
        "json_parsed": False,
        "json_has_required_fields": False,
        "csv_json_counts_match": False,
        "search_counts_exists": False,
        "search_counts_parsed": False,
        "search_counts_has_required_keys": False,
        "search_counts_values_are_int": False,
        "summary_exists": False,
        "summary_entries_line_matches_csv": False,
        "summary_il_matches_count_matches_search": False,
        "summary_slippage_matches_count_matches_search": False,
        "summary_has_insights_word": False,
        "summary_word_count_ok": False,
        "summary_has_action_items_heading": False,
        "summary_has_3_bullet_lines": False,
        "config_snapshot_exists": False,
        "config_snapshot_has_project_line": False,
    }

    # Paths
    csv_path = os.path.join(output_dir, "amm-export.csv")
    json_path = os.path.join(output_dir, "amm-export.json")
    search_counts_path = os.path.join(output_dir, "search_counts.json")
    summary_path = os.path.join(output_dir, "summary.md")
    cfg_path = os.path.join(output_dir, "config_snapshot.txt")

    # CSV checks
    csv_lines = None
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        csv_lines = read_lines(csv_path)
        if csv_lines is not None and len(csv_lines) >= 1:
            # Header must be exact
            if csv_lines[0] == "timestamp,command,value":
                checks["csv_header_ok"] = True
            # At least one data row (excluding header)
            if len(csv_lines) >= 2:
                checks["csv_has_rows"] = True

    csv_data_rows = 0
    if csv_lines is not None and len(csv_lines) >= 1 and checks["csv_header_ok"]:
        csv_data_rows = max(0, len(csv_lines) - 1)

    # JSON checks
    records = []
    if os.path.isfile(json_path):
        checks["json_exists"] = True
        ok, recs = parse_json_maybe_array_or_jsonl(json_path)
        if ok:
            checks["json_parsed"] = True
            records = recs if isinstance(recs, list) else []
            # Validate fields: each record must contain keys ts, cmd, val
            if records and all(isinstance(r, dict) and ("ts" in r and "cmd" in r and "val" in r) for r in records):
                checks["json_has_required_fields"] = True
            elif records == [] and csv_data_rows == 0:
                # Empty records list is acceptable only if CSV has 0 rows, but CSV must have >=1 per spec, so do nothing
                pass

    if checks["csv_has_rows"] and checks["json_parsed"]:
        if len(records) == csv_data_rows and csv_data_rows >= 1:
            checks["csv_json_counts_match"] = True

    # search_counts.json checks
    search_counts_obj = None
    if os.path.isfile(search_counts_path):
        checks["search_counts_exists"] = True
        try:
            with open(search_counts_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                checks["search_counts_parsed"] = True
                search_counts_obj = data
                # required keys
                required_keys = ["impermanent loss", "slippage"]
                if all(k in data for k in required_keys):
                    checks["search_counts_has_required_keys"] = True
                    # integer values
                    vals_ok = True
                    for k in required_keys:
                        v = data.get(k)
                        if not (isinstance(v, int) and not isinstance(v, bool)):
                            vals_ok = False
                            break
                    if vals_ok:
                        checks["search_counts_values_are_int"] = True
        except Exception:
            pass

    # summary.md checks
    summary_text = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        summary_text = read_text(summary_path)
        if summary_text is None:
            summary_text = ""
        # Entries line
        m_entries = re.search(r"^Entries:\s+(\d+)", summary_text, flags=re.MULTILINE)
        if m_entries and checks["csv_has_rows"]:
            try:
                n_entries = int(m_entries.group(1))
                if n_entries == csv_data_rows:
                    checks["summary_entries_line_matches_csv"] = True
            except Exception:
                pass
        # Impermanent loss matches
        m_il = re.search(r"^Impermanent loss matches:\s+(\d+)", summary_text, flags=re.MULTILINE)
        if m_il and checks["search_counts_values_are_int"] and search_counts_obj is not None:
            try:
                n_il = int(m_il.group(1))
                if n_il == int(search_counts_obj.get("impermanent loss")):
                    checks["summary_il_matches_count_matches_search"] = True
            except Exception:
                pass
        # Slippage matches
        m_sl = re.search(r"^Slippage matches:\s+(\d+)", summary_text, flags=re.MULTILINE)
        if m_sl and checks["search_counts_values_are_int"] and search_counts_obj is not None:
            try:
                n_sl = int(m_sl.group(1))
                if n_sl == int(search_counts_obj.get("slippage")):
                    checks["summary_slippage_matches_count_matches_search"] = True
            except Exception:
                pass
        # Contains word "Insights"
        if re.search(r"\bInsights\b", summary_text, flags=re.IGNORECASE):
            checks["summary_has_insights_word"] = True
        # Word count >= 120
        if count_words(summary_text) >= 120:
            checks["summary_word_count_ok"] = True
        # Action Items section presence
        if re.search(r"Action Items", summary_text, flags=re.IGNORECASE):
            checks["summary_has_action_items_heading"] = True
        # Count bullet lines starting with "- "
        bullet_lines = [ln for ln in summary_text.splitlines() if ln.strip().startswith("- ")]
        if len(bullet_lines) >= 3:
            checks["summary_has_3_bullet_lines"] = True

    # config_snapshot.txt checks
    if os.path.isfile(cfg_path):
        checks["config_snapshot_exists"] = True
        cfg_text = read_text(cfg_path) or ""
        if "project=dex-audit" in cfg_text:
            checks["config_snapshot_has_project_line"] = True

    # Determine reward: all-or-nothing based on strict criteria
    all_pass = all(checks.values())
    reward = 1.0 if all_pass else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()