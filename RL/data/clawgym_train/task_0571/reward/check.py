import json
import os
import re
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def iter_nonempty_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip() != "":
                    yield line.rstrip("\n")
    except Exception:
        return
        yield from ()

def parse_csv_rows(path):
    # Returns (headers, rows_as_list)
    try:
        with open(path, "r", encoding="utf-8") as f:
            rdr = csv.reader(f)
            rows = list(rdr)
        if not rows:
            return [], []
        headers = rows[0]
        data = rows[1:]
        # filter out completely empty rows
        data = [r for r in data if any(cell.strip() for cell in r)]
        return headers, data
    except Exception:
        return [], []

def parse_jsonl_lines(path):
    parsed = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    parsed.append(obj)
                except Exception:
                    # Mark with a sentinel to indicate parse failure for this line
                    parsed.append(None)
        return parsed
    except Exception:
        return []

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks to False
    checks = {
        # CSV checks
        "csv_exists": False,
        "csv_header_ok": False,
        "csv_min_rows": False,
        "csv_has_boiler3": False,
        "csv_has_conveyor1": False,
        # JSONL checks
        "jsonl_exists": False,
        "jsonl_min_lines": False,
        "jsonl_schema_ok": False,
        "jsonl_has_add_cmd": False,
        "jsonl_has_target_asset": False,
        # Report checks
        "report_exists": False,
        "report_mentions_compliance": False,
        "report_total_entries_line": False,
        "report_mentions_boiler3": False,
        "report_mentions_conveyor1": False,
        "report_has_how_to_reproduce": False,
        "report_has_search_word": False,
        "report_has_export_word": False,
        "report_has_remove_word": False,
    }

    # Paths
    csv_path = os.path.join(output_dir, "tagout-export.csv")
    jsonl_path = os.path.join(output_dir, "tagout-export.jsonl")
    report_path = os.path.join(output_dir, "compliance_summary.md")

    # CSV checks
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        # header check: first non-empty line equals exactly required header
        first_nonempty = None
        for line in iter_nonempty_lines(csv_path):
            first_nonempty = line.strip()
            break
        if first_nonempty == "timestamp,command,value":
            checks["csv_header_ok"] = True

        headers, rows = parse_csv_rows(csv_path)
        # Count at least 5 data rows (non-empty)
        if len(rows) >= 5:
            checks["csv_min_rows"] = True

        # Check substrings in value column (header expected index 2)
        # If header is correct, we trust index 2; else we still try index 2 if present.
        val_idx = 2 if len(headers) >= 3 else 2
        has_b = False
        has_c = False
        for r in rows:
            if len(r) > val_idx:
                val = r[val_idx]
                if "Boiler-3" in val:
                    has_b = True
                if "Conveyor-1" in val:
                    has_c = True
            if has_b and has_c:
                break
        if has_b:
            checks["csv_has_boiler3"] = True
        if has_c:
            checks["csv_has_conveyor1"] = True

    # JSONL checks
    if os.path.isfile(jsonl_path):
        checks["jsonl_exists"] = True
        content_lines = []
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        content_lines.append(line.rstrip("\n"))
        except Exception:
            content_lines = []
        if len(content_lines) >= 5:
            checks["jsonl_min_lines"] = True

        parsed = parse_jsonl_lines(jsonl_path)
        # Ensure all non-empty lines parse and have keys ts, cmd, val
        if parsed and all(isinstance(obj, dict) and all(k in obj for k in ("ts", "cmd", "val")) for obj in parsed if obj is not None):
            checks["jsonl_schema_ok"] = True

        # At least one line with cmd == "add"
        if any(isinstance(obj, dict) and obj.get("cmd") == "add" for obj in parsed if obj is not None):
            checks["jsonl_has_add_cmd"] = True

        # At least one line's val contains Boiler-3 or Conveyor-1
        if any(isinstance(obj, dict) and isinstance(obj.get("val"), str) and ("Boiler-3" in obj.get("val") or "Conveyor-1" in obj.get("val")) for obj in parsed if obj is not None):
            checks["jsonl_has_target_asset"] = True

    # Report checks
    if os.path.isfile(report_path):
        text = read_text(report_path)
        if text is not None and len(text.strip()) > 0:
            checks["report_exists"] = True
            # compliance mention
            if re.search(r"\bcompliance\b", text, flags=re.IGNORECASE):
                checks["report_mentions_compliance"] = True
            # Total entries line: phrase "Total entries" followed by a number on the same line
            for line in text.splitlines():
                if re.search(r"Total entries\s*:?\s*\d+", line, flags=re.IGNORECASE):
                    checks["report_total_entries_line"] = True
                    break
            # Mention assets
            if "Boiler-3" in text:
                checks["report_mentions_boiler3"] = True
            if "Conveyor-1" in text:
                checks["report_mentions_conveyor1"] = True
            # "How to reproduce" section mention
            if re.search(r"How to reproduce", text, flags=re.IGNORECASE):
                checks["report_has_how_to_reproduce"] = True
            # Presence of command words
            if re.search(r"\bsearch\b", text, flags=re.IGNORECASE):
                checks["report_has_search_word"] = True
            if re.search(r"\bexport\b", text, flags=re.IGNORECASE):
                checks["report_has_export_word"] = True
            if re.search(r"\bremove(d)?\b", text, flags=re.IGNORECASE):
                checks["report_has_remove_word"] = True

    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()