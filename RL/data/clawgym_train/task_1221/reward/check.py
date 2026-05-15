import json
import os
import re
import sys

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n\r") for line in f.readlines()]
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # sales_rank.txt checks
        "sales_rank_exists": False,
        "sales_rank_header_dashed": False,
        "sales_rank_rank1_is_1005": False,
        "sales_rank_stable_tie_34950": False,
        # sales_top3.txt checks
        "sales_top3_exists": False,
        "sales_top3_has_header": False,
        "sales_top3_has_exact_three_data_rows": False,
        "sales_top3_order_correct": False,
        # subscribers_dedup.txt checks
        "subscribers_dedup_exists": False,
        "subscribers_dedup_exact_lines": False,
        # subscribers_freq.txt checks
        "subscribers_freq_exists": False,
        "subscribers_freq_has_header": False,
        "subscribers_freq_three_counts_present": False,
        # events_sorted.json checks
        "events_sorted_exists": False,
        "events_sorted_valid_and_ordered": False,
        # README.md checks
        "readme_exists": False,
        "readme_line_count_ok": False,
    }

    # Paths
    sales_rank_path = os.path.join(output_dir, "sales_rank.txt")
    sales_top3_path = os.path.join(output_dir, "sales_top3.txt")
    subscribers_dedup_path = os.path.join(output_dir, "subscribers_dedup.txt")
    subscribers_freq_path = os.path.join(output_dir, "subscribers_freq.txt")
    events_sorted_path = os.path.join(output_dir, "events_sorted.json")
    readme_path = os.path.join(output_dir, "README.md")

    # 1) sales_rank.txt
    if os.path.isfile(sales_rank_path):
        checks["sales_rank_exists"] = True
        lines = read_lines(sales_rank_path) or []
        # Find header "RANK" and immediate dashed separator "----"
        header_idx = None
        for idx, line in enumerate(lines):
            if line.strip().startswith("RANK"):
                header_idx = idx
                break
        if header_idx is not None and header_idx + 1 < len(lines):
            if lines[header_idx + 1].strip().startswith("----"):
                checks["sales_rank_header_dashed"] = True
                dashed_idx = header_idx + 1
            else:
                dashed_idx = None
        else:
            dashed_idx = None

        # Check first ranked data line content
        if checks["sales_rank_header_dashed"]:
            # First data line after dashed: look for a line that looks like "<rank>  <csv>"
            first_data_line = None
            rank_entry_pattern = re.compile(r"^\s*\d+\s{1,}.*")
            for i in range(dashed_idx + 1, len(lines)):
                if rank_entry_pattern.match(lines[i]):
                    first_data_line = lines[i]
                    break
            if first_data_line and "1005,Widget D,3,799.00" in first_data_line:
                checks["sales_rank_rank1_is_1005"] = True

        # Stable tie check: 1002 before 1006 for equal revenue
        if lines:
            idx_1002 = next((i for i, l in enumerate(lines) if "1002,Widget B,5,349.50" in l), None)
            idx_1006 = next((i for i, l in enumerate(lines) if "1006,Widget E,7,349.50" in l), None)
            if idx_1002 is not None and idx_1006 is not None and idx_1002 < idx_1006:
                checks["sales_rank_stable_tie_34950"] = True

    # 2) sales_top3.txt
    if os.path.isfile(sales_top3_path):
        checks["sales_top3_exists"] = True
        lines = read_lines(sales_top3_path) or []
        # Header presence (original CSV header)
        expected_header = "order_id,product,units_sold,revenue"
        if any((ln.strip() == expected_header) for ln in lines):
            checks["sales_top3_has_header"] = True

        # Data rows detection: CSV-like lines starting with digits then comma
        data_rows = [ln.strip() for ln in lines if re.match(r"^\s*\d+,\s*.+", ln)]
        if len(data_rows) == 3:
            checks["sales_top3_has_exact_three_data_rows"] = True
            expected_rows = [
                "1005,Widget D,3,799.00",
                "1002,Widget B,5,349.50",
                "1006,Widget E,7,349.50",
            ]
            if data_rows == expected_rows:
                checks["sales_top3_order_correct"] = True

    # 3) subscribers_dedup.txt
    if os.path.isfile(subscribers_dedup_path):
        checks["subscribers_dedup_exists"] = True
        lines = read_lines(subscribers_dedup_path)
        if lines is not None:
            expected_list = [
                "alice@example.com",
                "bob@example.com",
                "carol@example.com",
                "dave@example.com",
                "ALICE@example.com",
                "eve@sample.org",
                "frank@test.com",
            ]
            if lines == expected_list:
                checks["subscribers_dedup_exact_lines"] = True

    # 4) subscribers_freq.txt
    if os.path.isfile(subscribers_freq_path):
        checks["subscribers_freq_exists"] = True
        lines = read_lines(subscribers_freq_path) or []

        # Header check: a line with both COUNT and VALUE words
        header_found = any(("count" in ln.lower() and "value" in ln.lower()) for ln in lines)
        if header_found:
            checks["subscribers_freq_has_header"] = True

        # Parse frequency lines: format like "<count> <value>"
        freq_map = {}
        for ln in lines:
            # Skip header-like or dashed separator lines
            if ("count" in ln.lower() and "value" in ln.lower()):
                continue
            if set(ln.strip()) <= set("- ") and ln.strip():
                continue
            m = re.match(r"^\s*(\d+)\s+(.+?)\s*$", ln)
            if m:
                cnt = int(m.group(1))
                val = m.group(2)
                freq_map[val] = cnt
        need_counts = {
            "alice@example.com": 2,
            "carol@example.com": 2,
            "eve@sample.org": 2,
        }
        all_present = True
        for k, v in need_counts.items():
            if freq_map.get(k) != v:
                all_present = False
                break
        if all_present:
            checks["subscribers_freq_three_counts_present"] = True

    # 5) events_sorted.json
    if os.path.isfile(events_sorted_path):
        checks["events_sorted_exists"] = True
        data = load_json(events_sorted_path)
        if isinstance(data, list) and len(data) == 4:
            expected_pairs = [
                ("view", "2025-01-01T12:00:00Z"),
                ("add_to_cart", "2025-01-02T09:58:00Z"),
                ("view", "2025-01-02T10:00:00Z"),
                ("purchase", "2025-01-02T10:05:00Z"),
            ]
            try:
                pairs = [(item.get("event"), item.get("timestamp")) for item in data]
                if pairs == expected_pairs:
                    checks["events_sorted_valid_and_ordered"] = True
            except Exception:
                pass

    # 6) README.md
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        lines = read_lines(readme_path) or []
        non_empty = [ln for ln in lines if ln.strip() != ""]
        if 8 <= len(non_empty) <= 200:
            checks["readme_line_count_ok"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()