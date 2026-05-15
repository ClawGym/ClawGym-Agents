import json
import os
import sys
import csv
from datetime import datetime

def safe_load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
    except Exception:
        return []

def parse_csv(path):
    rows = []
    header = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i == 0:
                    header = row
                else:
                    rows.append(row)
        return header, rows
    except Exception:
        return None, []

def to_number(x):
    # Accept int or float from JSON/CSV
    try:
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace(",", "")
        if s == "":
            return None
        return float(s)
    except Exception:
        return None

def approx_equal(a, b, tol=0.05):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def compute_expected(snapshot):
    # snapshot: dict with key "data": list of items
    data = snapshot.get("data", []) if isinstance(snapshot, dict) else []
    # Normalize items: expect keys rank, title, category, search_count
    items = []
    for it in data:
        try:
            rank = int(it.get("rank"))
            title = str(it.get("title", ""))
            category = str(it.get("category", ""))
            sc = to_number(it.get("search_count"))
            sc = sc if sc is not None else 0.0
            items.append({"rank": rank, "title": title, "category": category, "search_count": float(sc)})
        except Exception:
            continue
    # Total
    total_items = len(items)
    # Categories
    categories = {}
    for it in items:
        categories[it["category"]] = categories.get(it["category"], 0) + 1
    # Sort by ascending rank
    items_sorted_by_rank = sorted(items, key=lambda x: (x["rank"], x["title"]))
    top12 = items_sorted_by_rank[:12]
    # Sum search_count across all items
    total_sc = sum([it["search_count"] for it in items]) if items else 0.0
    # Percent share (global sum)
    def pct_share(v, total):
        if total and total > 0:
            return round(v / total * 100.0, 1)
        return 0.0
    # Add computed shares for reference
    top12_with_share = []
    for it in top12:
        top12_with_share.append({**it, "percent_share": pct_share(it["search_count"], total_sc)})
    # Keywords fixed list per spec
    keywords = ["ai", "315", "football", "chicken feet"]
    # Compute hits
    keyword_hits = {k: {"count": 0, "ranks": []} for k in keywords}
    for it in items:
        title_low = it["title"].lower()
        for k in keywords:
            if k.lower() in title_low:
                keyword_hits[k]["ranks"].append(it["rank"])
    for k in keywords:
        # Unique ranks, but count per instruction is "how many titles matched"
        # We consider unique titles (ranks assumed unique)
        ranks = sorted(list(dict.fromkeys(keyword_hits[k]["ranks"])))
        keyword_hits[k]["ranks"] = ranks
        keyword_hits[k]["count"] = len(ranks)
    # Rising items: category == "New"
    rising_ranks = sorted([it["rank"] for it in items if it.get("category") == "New"])
    rising = {"count": len(rising_ranks), "ranks": rising_ranks}
    # Top3 by share (equivalent to top3 by search_count desc)
    top3_items = sorted(items, key=lambda x: (-x["search_count"], x["rank"], x["title"]))[:3]
    top3_titles = [it["title"] for it in top3_items]
    return {
        "total_items": total_items,
        "categories": categories,
        "top12": top12_with_share,
        "keyword_hits": keyword_hits,
        "rising": rising,
        "top3_titles": top3_titles,
        "sum_search_count": total_sc,
        "items_by_rank": {it["rank"]: it for it in items},
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    snapshot_path = os.path.join(input_dir, "baidu_hot_snapshot.json")
    keywords_path = os.path.join(input_dir, "keywords.txt")

    summary_path = os.path.join(output_dir, "summary.json")
    tracked_path = os.path.join(output_dir, "tracked.jsonl")
    report_path = os.path.join(output_dir, "report.html")
    dataset_path = os.path.join(output_dir, "dataset.csv")

    # Initialize checks (all False by default)
    checks = {
        "has_summary_json": False,
        "summary_has_required_keys": False,
        "summary_generated_at_has_T": False,
        "categories_sum_matches_total": False,
        "categories_counts_match_input": False,
        "summary_top12_len_12": False,
        "summary_top12_ascending_rank": False,
        "summary_top12_match_input": False,
        "summary_top12_percent_share_correct": False,
        "summary_top3_by_share_correct": False,
        "summary_keyword_hits_keys_present": False,
        "summary_keyword_hits_correct": False,
        "summary_rising_correct": False,
        "has_tracked_jsonl": False,
        "tracked_lines_valid_json_and_schema": False,
        "tracked_keywords_subset_and_nonempty": False,
        "report_html_exists": False,
        "report_contains_header_and_keywords": False,
        "report_has_table_with_12plus_rows": False,
        "dataset_csv_exists": False,
        "dataset_csv_header_exact": False,
        "dataset_csv_has_12plus_rows": False,
        "dataset_csv_ranks_ascending": False,
        "dataset_csv_first12_match_top12": False,
        "dataset_csv_percent_share_correct": False,
    }

    # Load inputs (for validation reference). Do not award credit for reading inputs alone.
    snapshot = safe_load_json(snapshot_path)
    expected = None
    if snapshot is not None and isinstance(snapshot, dict):
        try:
            expected = compute_expected(snapshot)
        except Exception:
            expected = None

    # 1) summary.json checks
    summary = safe_load_json(summary_path)
    if isinstance(summary, dict):
        checks["has_summary_json"] = True
        required_keys = ["generated_at", "total_items", "categories", "top_12", "keyword_hits", "rising", "top3_by_share"]
        types_ok = (
            isinstance(summary.get("generated_at"), str) and
            isinstance(summary.get("total_items"), (int,)) and
            isinstance(summary.get("categories"), dict) and
            isinstance(summary.get("top_12"), list) and
            isinstance(summary.get("keyword_hits"), dict) and
            isinstance(summary.get("rising"), dict) and
            isinstance(summary.get("top3_by_share"), list) and
            len(summary.get("top3_by_share")) == 3
        )
        if all(k in summary for k in required_keys) and types_ok:
            checks["summary_has_required_keys"] = True
        # generated_at contains 'T'
        if isinstance(summary.get("generated_at"), str) and "T" in summary.get("generated_at"):
            checks["summary_generated_at_has_T"] = True
        # categories sum equals total_items
        if isinstance(summary.get("categories"), dict) and isinstance(summary.get("total_items"), int):
            try:
                cat_sum = sum(int(v) for v in summary["categories"].values())
                if cat_sum == int(summary["total_items"]):
                    checks["categories_sum_matches_total"] = True
            except Exception:
                pass
        # summary.top_12 length and ascending rank
        top12 = summary.get("top_12")
        if isinstance(top12, list) and len(top12) == 12:
            checks["summary_top12_len_12"] = True
            try:
                ranks = [int(item.get("rank")) for item in top12]
                if ranks == sorted(ranks):
                    checks["summary_top12_ascending_rank"] = True
            except Exception:
                pass

        # Validate presence of keyword keys
        kw_req = ["ai", "315", "football", "chicken feet"]
        keyword_hits = summary.get("keyword_hits")
        if isinstance(keyword_hits, dict) and all(k in keyword_hits for k in kw_req):
            # Also check schema for each
            schema_ok = True
            for k in kw_req:
                kv = keyword_hits.get(k, {})
                if not (isinstance(kv, dict) and isinstance(kv.get("count"), int) and isinstance(kv.get("ranks"), list) and all(isinstance(r, int) for r in kv["ranks"])):
                    schema_ok = False
                    break
            if schema_ok:
                checks["summary_keyword_hits_keys_present"] = True

        # If we have expected info from snapshot, perform deeper validations
        if expected is not None:
            # categories_counts_match_input
            # Compare counts exactly (missing categories treated as zero)
            try:
                # Normalize both dicts
                exp_cats = dict(expected["categories"])
                got_cats = dict(summary.get("categories", {}))
                # Remove zero-count categories to avoid mismatch due to extra zeros
                exp_cats_nz = {k: int(v) for k, v in exp_cats.items() if int(v) != 0}
                got_cats_nz = {k: int(v) for k, v in got_cats.items() if int(v) != 0}
                if exp_cats_nz == got_cats_nz:
                    checks["categories_counts_match_input"] = True
            except Exception:
                pass

            # summary_top12_match_input and percent shares
            if isinstance(top12, list) and len(top12) >= 12:
                try:
                    exp_top12 = expected["top12"]
                    # Compare rank order and corresponding fields
                    match_all = True
                    shares_ok = True
                    for i in range(12):
                        got = top12[i]
                        exp = exp_top12[i]
                        # Rank must match expected
                        if int(got.get("rank")) != int(exp["rank"]):
                            match_all = False
                            break
                        # Title, category, search_count should match input for that rank
                        # Note: allow numeric conversion for search_count
                        if str(got.get("title", "")) != exp["title"]:
                            match_all = False
                            break
                        if str(got.get("category", "")) != exp["category"]:
                            match_all = False
                            break
                        sc_got = to_number(got.get("search_count"))
                        if sc_got is None or not approx_equal(sc_got, exp["search_count"], tol=1e-9):
                            match_all = False
                            break
                        # percent_share within tolerance 0.05
                        ps_got = to_number(got.get("percent_share"))
                        if ps_got is None or not approx_equal(ps_got, exp["percent_share"], tol=0.05):
                            shares_ok = False
                    if match_all:
                        checks["summary_top12_match_input"] = True
                    if shares_ok and match_all:
                        checks["summary_top12_percent_share_correct"] = True
                except Exception:
                    pass

            # top3_by_share
            top3_titles = summary.get("top3_by_share")
            if isinstance(top3_titles, list) and len(top3_titles) == 3:
                try:
                    if [str(t) for t in top3_titles] == expected["top3_titles"]:
                        checks["summary_top3_by_share_correct"] = True
                except Exception:
                    pass

            # keyword_hits correctness
            if checks["summary_keyword_hits_keys_present"]:
                try:
                    ok = True
                    for k, exp in expected["keyword_hits"].items():
                        got = summary["keyword_hits"].get(k, {})
                        # Count equals number of titles matched; ranks match as a set (order not enforced)
                        got_ranks = got.get("ranks", [])
                        exp_ranks = exp.get("ranks", [])
                        if int(got.get("count", -1)) != int(exp.get("count", -2)):
                            ok = False
                            break
                        if sorted([int(r) for r in got_ranks]) != sorted([int(r) for r in exp_ranks]):
                            ok = False
                            break
                    if ok:
                        checks["summary_keyword_hits_correct"] = True
                except Exception:
                    pass

            # rising correctness
            rising = summary.get("rising")
            if isinstance(rising, dict):
                try:
                    got_count = int(rising.get("count"))
                    got_ranks = rising.get("ranks", [])
                    if isinstance(got_ranks, list) and all(isinstance(r, int) for r in got_ranks):
                        if got_count == expected["rising"]["count"] and sorted(got_ranks) == expected["rising"]["ranks"]:
                            checks["summary_rising_correct"] = True
                except Exception:
                    pass

    # 2) tracked.jsonl checks
    if os.path.isfile(tracked_path):
        # has_tracked_jsonl: must exist and have at least one non-empty line
        lines = read_lines(tracked_path)
        non_empty = [ln for ln in lines if ln.strip() != ""]
        if len(non_empty) > 0:
            checks["has_tracked_jsonl"] = True
            all_valid = True
            subset_ok = True
            allowed = {"ai", "315", "football", "chicken feet"}
            for ln in non_empty:
                try:
                    obj = json.loads(ln)
                    # schema
                    if not (isinstance(obj, dict) and
                            isinstance(obj.get("rank"), int) and
                            isinstance(obj.get("title"), str) and
                            isinstance(obj.get("category"), str) and
                            isinstance(obj.get("matched_keywords"), list) and
                            len(obj.get("matched_keywords")) >= 1):
                        all_valid = False
                        break
                    # search_count can be int or float
                    sc = obj.get("search_count")
                    if not isinstance(sc, (int, float)):
                        all_valid = False
                        break
                    # matched_keywords subset
                    mks = obj.get("matched_keywords")
                    mks_norm = []
                    for k in mks:
                        if not isinstance(k, str):
                            subset_ok = False
                            break
                        mks_norm.append(k.lower())
                    if not set(mks_norm).issubset(allowed):
                        subset_ok = False
                        break
                    # If title present, ensure each keyword listed is truly matched (case-insensitive substring)
                    title_low = obj.get("title", "").lower()
                    for k in set(mks_norm):
                        if k not in title_low:
                            # For "315", ensure numeric match as substring
                            if k == "315":
                                if "315" not in title_low:
                                    subset_ok = False
                                    break
                            else:
                                subset_ok = False
                                break
                    if not subset_ok:
                        break
                except Exception:
                    all_valid = False
                    break
            if all_valid:
                checks["tracked_lines_valid_json_and_schema"] = True
            if subset_ok and all_valid:
                checks["tracked_keywords_subset_and_nonempty"] = True

    # 3) report.html checks
    if os.path.isfile(report_path):
        checks["report_html_exists"] = True
        content = read_text(report_path)
        low = content.lower()
        # Must contain the string "Baidu Hot Topics Report"
        has_header = "baidu hot topics report" in low
        # Must contain the four keywords as substrings (case-insensitive)
        key_ok = all(k in low for k in ["ai", "315", "football", "chicken feet"])
        if has_header and key_ok:
            checks["report_contains_header_and_keywords"] = True
        # Table with 12 or more <tr rows (including header)
        tr_count = low.count("<tr")
        table_present = "<table" in low and tr_count >= 12
        if table_present:
            checks["report_has_table_with_12plus_rows"] = True

    # 4) dataset.csv checks
    if os.path.isfile(dataset_path):
        checks["dataset_csv_exists"] = True
        header, rows = parse_csv(dataset_path)
        # Header exact
        if header is not None:
            # Strip BOM if present
            if header and header[0].startswith("\ufeff"):
                header[0] = header[0].lstrip("\ufeff")
            if header == ["rank", "title", "category", "search_count", "percent_share"]:
                checks["dataset_csv_header_exact"] = True
        # At least 12 data rows
        if rows and len(rows) >= 12:
            checks["dataset_csv_has_12plus_rows"] = True
            # Ranks ascending across all data rows
            try:
                rank_vals = [int(r[0]) for r in rows if len(r) >= 1]
                if rank_vals == sorted(rank_vals):
                    checks["dataset_csv_ranks_ascending"] = True
            except Exception:
                pass
            # If expected available, verify first 12 match top12
            if expected is not None and checks["dataset_csv_header_exact"]:
                try:
                    exp_top12 = expected["top12"]
                    first12 = rows[:12]
                    all_match = True
                    shares_ok = True
                    for i, row in enumerate(first12):
                        if len(row) < 5:
                            all_match = False
                            break
                        r_rank = int(row[0])
                        r_title = row[1]
                        r_cat = row[2]
                        r_sc = to_number(row[3])
                        r_ps = to_number(row[4])
                        exp = exp_top12[i]
                        if r_rank != exp["rank"] or r_title != exp["title"] or r_cat != exp["category"]:
                            all_match = False
                            break
                        if r_sc is None or not approx_equal(r_sc, exp["search_count"], tol=1e-9):
                            all_match = False
                            break
                        if r_ps is None or not approx_equal(r_ps, exp["percent_share"], tol=0.05):
                            shares_ok = False
                    if all_match:
                        checks["dataset_csv_first12_match_top12"] = True
                    if shares_ok and all_match:
                        checks["dataset_csv_percent_share_correct"] = True
                except Exception:
                    pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if no relevant output files exist, reward must be 0.0
    any_output_present = any(os.path.isfile(p) for p in [summary_path, tracked_path, report_path, dataset_path])
    if not any_output_present:
        reward = 0.0

    # Print single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()