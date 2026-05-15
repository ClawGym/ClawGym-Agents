import json
import os
import sys
import re
import csv
from datetime import datetime

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def file_exists_nonempty(path):
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except Exception:
        return False

def parse_float(s):
    try:
        # Remove thousands separators like "1,234.56"
        s_clean = s.replace(",", "")
        return float(s_clean)
    except Exception:
        return None

def parse_date_generic(s):
    # Try robust ISO parsing, then common fallbacks. Returns (parsed_dt, ok)
    if not isinstance(s, str):
        return None, False
    s = s.strip()
    if not s:
        return None, False
    try:
        # handle Z suffix
        if s.endswith("Z"):
            s_iso = s[:-1] + "+00:00"
        else:
            s_iso = s
        dt = datetime.fromisoformat(s_iso)
        return dt, True
    except Exception:
        pass
    patterns = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
    ]
    for fmt in patterns:
        try:
            dt = datetime.strptime(s, fmt)
            return dt, True
        except Exception:
            continue
    return None, False

def extract_year_month(date_str):
    if not isinstance(date_str, str):
        return None
    s = date_str.strip()
    # Prefer simple slice if ISO-like
    if len(s) >= 7 and re.match(r"^\d{4}[-/]\d{2}", s):
        # Normalize separator to '-'
        ym = s[:7].replace("/", "-")
        return ym
    # Attempt parse then format
    dt, ok = parse_date_generic(s)
    if ok:
        return f"{dt.year:04d}-{dt.month:02d}"
    # Fallback: try to find YYYY and MM in string
    m = re.search(r"(\d{4})[-/](\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None

def read_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def check_aggregate(input_orders_path, aggregate_path):
    # Initialize flags
    exists = file_exists_nonempty(aggregate_path)
    if not exists:
        return False
    rows = read_csv_rows(aggregate_path)
    if not rows or len(rows) < 1:
        return False
    header = rows[0]
    if header != ["region", "month", "total_amount"]:
        return False
    data_rows = rows[1:]
    # Validate sorting
    seen = []
    for r in data_rows:
        if len(r) != 3:
            return False
        region = r[0]
        month = r[1]
        # basic sanity for month format
        if not re.match(r"^\d{4}-\d{2}$", month):
            return False
        seen.append((region, month))
    if seen != sorted(seen, key=lambda x: (x[0], x[1])):
        return False

    # Compute expected aggregation from input/orders.csv
    src_rows = read_csv_rows(input_orders_path)
    if not src_rows or len(src_rows) < 2:
        # If input seems empty, then output should also be empty data rows
        expected_groups = {}
    else:
        src_header = [h.strip().lower() for h in src_rows[0]]
        try:
            region_idx = src_header.index("region")
            date_idx = src_header.index("date")
            amount_idx = src_header.index("amount")
        except ValueError:
            return False
        expected_groups = {}
        for r in src_rows[1:]:
            if len(r) <= max(region_idx, date_idx, amount_idx):
                continue
            region = r[region_idx].strip()
            ym = extract_year_month(r[date_idx])
            amt = parse_float(r[amount_idx])
            if region and ym and amt is not None:
                key = (region, ym)
                expected_groups[key] = expected_groups.get(key, 0.0) + amt

    # Build mapping from output for comparison
    out_map = {}
    for r in data_rows:
        region = r[0]
        month = r[1]
        amt = parse_float(r[2])
        if amt is None:
            return False
        out_map[(region, month)] = out_map.get((region, month), 0.0) + amt

    # Counts must match
    if len(out_map) != len(expected_groups):
        return False
    # Verify each expected group within tolerance
    for k, v in expected_groups.items():
        if k not in out_map:
            return False
        if abs(out_map[k] - v) > 0.01:
            return False
    return True

def check_changelog(commits_path, changelog_path):
    # Load commits
    if not file_exists_nonempty(changelog_path):
        return False
    commits = []
    try:
        with open(commits_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                commits.append(obj)
    except Exception:
        return False
    types_order = ["feat", "fix", "chore"]
    # Group and sort commits by type and date desc
    def get_sort_key(obj):
        ds = obj.get("date", "")
        dt, ok = parse_date_generic(ds)
        if ok:
            return dt
        # Fallback: lexicographic
        return ds
    grouped = {t: [] for t in types_order}
    for c in commits:
        t = str(c.get("type", "")).lower()
        if t in grouped:
            grouped[t].append(c)
    for t in types_order:
        # Sort descending by date
        grouped[t].sort(key=get_sort_key, reverse=True)
    # Parse changelog content
    content = read_text(changelog_path)
    if content is None:
        return False
    lines = [ln.rstrip("\n") for ln in content.splitlines()]
    # Extract level-2 headings
    headings = []
    # Map type -> list of bullet lines
    bullets = {t: [] for t in types_order}
    current_type = None
    for ln in lines:
        if ln.startswith("## "):
            h = ln.strip()
            headings.append(h)
            hname = h[3:].strip()
            if hname in types_order:
                current_type = hname
            else:
                # Extra section not allowed
                return False
            continue
        if ln.startswith("- "):
            if current_type is None:
                # Bullet outside a recognized section
                return False
            bullets[current_type].append(ln.strip())
        else:
            # other lines allowed (blank or text)
            continue
    # Check headings order exactly feat, fix, chore (ignore any other level like '#')
    if headings != ["## feat", "## fix", "## chore"]:
        return False
    # Build expected bullets per type
    expected_bullets = {t: [] for t in types_order}
    for t in types_order:
        for c in grouped[t]:
            scope = str(c.get("scope", "")).strip()
            desc = str(c.get("description", "")).strip()
            expected_bullets[t].append(f"- {scope}: {desc}")
    # Compare bullets exactly and order
    for t in types_order:
        if bullets[t] != expected_bullets[t]:
            return False
    return True

def count_changelog(commits_path):
    counts = {"feat": 0, "fix": 0, "chore": 0}
    try:
        with open(commits_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                t = str(obj.get("type", "")).lower()
                if t in counts:
                    counts[t] += 1
    except Exception:
        pass
    return counts

def count_csv_data_rows(csv_path):
    rows = read_csv_rows(csv_path)
    if not rows:
        return None
    # exclude header
    return max(0, len(rows) - 1)

def check_summary(summary_path, expected_orders_rows, expected_changelog_counts, expected_files_ok):
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    # Validate fields
    if not isinstance(data, dict):
        return False
    if "orders_rows" not in data or "changelog_counts" not in data or "files_ok" not in data:
        return False
    if not isinstance(data["orders_rows"], int):
        return False
    if not isinstance(data["changelog_counts"], dict):
        return False
    cc = data["changelog_counts"]
    for k in ["feat", "fix", "chore"]:
        if k not in cc or not isinstance(cc[k], int):
            return False
    if not isinstance(data["files_ok"], bool):
        return False
    # Compare values
    if expected_orders_rows is None:
        return False
    if data["orders_rows"] != expected_orders_rows:
        return False
    for k in ["feat", "fix", "chore"]:
        if cc[k] != expected_changelog_counts.get(k, 0):
            return False
    if data["files_ok"] != expected_files_ok:
        return False
    return True

def load_task_array(queue_path):
    try:
        with open(queue_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    # Accept either a top-level list or an object with "tasks"
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("tasks"), list):
            return data.get("tasks")
    return None

def check_task_queue(queue_path):
    tasks = load_task_array(queue_path)
    if tasks is None:
        return False
    required_paths = [
        "output/aggregates/orders_by_region_month.csv",
        "output/docs/CHANGELOG.md",
        "output/validation/summary.json",
    ]
    found = {p: False for p in required_paths}
    for t in tasks:
        if not isinstance(t, dict):
            continue
        deliverable = t.get("deliverable_path") or t.get("deliverablePath") or t.get("deliverable")
        status = t.get("status")
        tid = t.get("id")
        if isinstance(deliverable, str) and deliverable in found:
            # status == done and id matches T-\d{2,}
            if status == "done" and isinstance(tid, str) and re.match(r"^T-\d{2,}$", tid):
                found[deliverable] = True
    return all(found.values())

def check_queue_status(status_path):
    if not file_exists_nonempty(status_path):
        return False
    txt = read_text(status_path)
    if txt is None:
        return False
    # Find a line containing the required counts
    required_snippets = ["Task Queue", "3 total", "0 pending", "0 running", "3 done", "0 blocked"]
    for line in txt.splitlines():
        line_stripped = line.strip()
        if all(snip in line_stripped for snip in required_snippets):
            return True
    return False

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    orders_in = os.path.join(input_dir, "orders.csv")
    commits_in = os.path.join(input_dir, "commits.jsonl")
    agg_out = os.path.join(output_dir, "aggregates", "orders_by_region_month.csv")
    changelog_out = os.path.join(output_dir, "docs", "CHANGELOG.md")
    summary_out = os.path.join(output_dir, "validation", "summary.json")
    queue_out = os.path.join(output_dir, "task-queue.json")
    qstatus_out = os.path.join(output_dir, "queue-status.txt")

    # Perform checks
    agg_ok = False
    changelog_ok = False
    summary_ok = False
    queue_ok = False
    qstatus_ok = False

    # Check aggregate CSV
    if file_exists_nonempty(agg_out) and os.path.isfile(orders_in):
        agg_ok = check_aggregate(orders_in, agg_out)

    # Check changelog md
    if os.path.isfile(commits_in) and file_exists_nonempty(changelog_out):
        changelog_ok = check_changelog(commits_in, changelog_out)

    # Compute expected for summary
    expected_files_ok = file_exists_nonempty(agg_out) and file_exists_nonempty(changelog_out)
    expected_orders_rows = count_csv_data_rows(agg_out) if file_exists_nonempty(agg_out) else None
    expected_changelog_counts = count_changelog(commits_in) if os.path.isfile(commits_in) else {"feat": 0, "fix": 0, "chore": 0}

    # Check summary json
    if os.path.isfile(summary_out):
        summary_ok = check_summary(summary_out, expected_orders_rows, expected_changelog_counts, expected_files_ok)

    # Check task queue
    if os.path.isfile(queue_out):
        queue_ok = check_task_queue(queue_out)

    # Check queue-status.txt
    qstatus_ok = check_queue_status(qstatus_out)

    checks = {
        "agg_csv_ok": agg_ok,
        "changelog_md_ok": changelog_ok,
        "summary_json_ok": summary_ok,
        "task_queue_ok": queue_ok,
        "queue_status_ok": qstatus_ok,
    }
    total = sum(1 for v in checks.values() if v)
    reward = total / 5.0 if total > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()