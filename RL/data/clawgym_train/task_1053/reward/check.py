import json
import os
import sys
import re
import csv

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_leaderboard_csv": False,
        "has_summary_json": False,
        "csv_header_ok": False,
        "csv_sorted_and_ranked_ok": False,
        "records_only_and_no_suspects": False,
        "statuses_ok": False,
        "topn_with_highlight_ok": False,
        "csv_matches_expected_set": False,
        "summary_fields_ok": False,
        "highlight_consistency_ok": False,
    }

    # Helper regex patterns for extraction
    BPB_PATTERN = re.compile(r"val_bpb[=:\s]*(\d+\.\d+)", re.IGNORECASE)
    SCORE_IN_TITLE = re.compile(r"(\d+\.\d{3,})")
    SINCE_DATE = "2026-03-19"
    TOP_N = 5
    HIGHLIGHT_USER = "dexhunter"

    # Paths
    prs_open_path = os.path.join(input_dir, "prs_open.json")
    prs_closed_path = os.path.join(input_dir, "prs_closed.json")
    csv_path = os.path.join(output_dir, "leaderboard.csv")
    summary_path = os.path.join(output_dir, "summary.json")

    # Compute expected filtered leaderboard
    def safe_get_labels_lower(pr):
        labels = pr.get("labels", [])
        result = []
        if isinstance(labels, list):
            for l in labels:
                if isinstance(l, dict) and "name" in l:
                    name = l.get("name")
                else:
                    name = l
                if isinstance(name, str):
                    result.append(name.lower())
        return result

    def extract_score_from_pr(pr):
        title = pr.get("title", "") or ""
        body = pr.get("body", "") or ""

        m = BPB_PATTERN.search(title)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass

        m = BPB_PATTERN.search(body[:2000])
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass

        # Fallback: decimals with >=3 fractional digits in title; restrict plausible range
        for m in SCORE_IN_TITLE.finditer(title):
            try:
                val = float(m.group(1))
                if 1.0 < val < 2.0:
                    return val
            except ValueError:
                continue

        return None

    def classify_pr(pr):
        title_l = (pr.get("title") or "").lower()
        labels_l = safe_get_labels_lower(pr)
        if "non-record" in title_l or any("non-record" in lab for lab in labels_l):
            return "non-record"
        if "record" in title_l or any("record" in lab for lab in labels_l):
            return "record"
        return "other"

    def is_suspect(pr, score):
        title_l = (pr.get("title") or "").lower()
        if score is not None and score < 1.10:
            return True
        if "val-only" in title_l or "paid prefix" in title_l or "paid-prefix" in title_l:
            return True
        return False

    # Load inputs
    try:
        with open(prs_open_path, "r", encoding="utf-8") as f:
            open_prs = json.load(f)
    except Exception:
        open_prs = []

    try:
        with open(prs_closed_path, "r", encoding="utf-8") as f:
            closed_prs = json.load(f)
    except Exception:
        closed_prs = []

    # Build merged PRs (closed with merged_at)
    merged_prs = []
    for pr in closed_prs:
        try:
            if pr.get("merged_at"):
                merged_prs.append(pr)
        except Exception:
            continue

    # Combine open + merged
    # Ensure unique by PR number, prefer merged version if duplicates
    by_number = {}
    for pr in open_prs:
        if isinstance(pr, dict) and "number" in pr:
            by_number[pr["number"]] = pr
    for pr in merged_prs:
        if isinstance(pr, dict) and "number" in pr:
            by_number[pr["number"]] = pr  # merged overwrites open

    all_prs = list(by_number.values())

    # Filter and prepare entries
    entries = []
    for pr in all_prs:
        try:
            created = (pr.get("created_at") or "")[:10]
            if not created or created < SINCE_DATE:
                continue

            score = extract_score_from_pr(pr)
            if score is None:
                continue

            category = classify_pr(pr)
            if category != "record":
                continue

            suspect = is_suspect(pr, score)
            if suspect:
                continue

            merged = pr.get("merged_at") is not None
            status = "merged" if merged else (pr.get("state", "open") or "open")

            author = None
            if isinstance(pr.get("user"), dict):
                author = pr["user"].get("login")
            if not author:
                author = ""

            entries.append({
                "number": pr.get("number"),
                "title": pr.get("title") or "",
                "score": score,
                "author": author,
                "date": created,
                "category": category,
                "status": status,
                "suspect": False,  # all included entries are non-suspect by construction
            })
        except Exception:
            continue

    # Sort and rank
    entries.sort(key=lambda e: (e["score"] is None, e["score"] if e["score"] is not None else 99.0))
    # Assign rank among scored entries
    for idx, e in enumerate(entries, start=1):
        e["rank"] = idx

    # Expected included set: top N + all dexhunter entries (if any), unique by PR number
    expected_included_map = {}
    for e in entries[:TOP_N]:
        expected_included_map[e["number"]] = e
    for e in entries:
        if isinstance(e.get("author"), str) and e["author"].lower() == HIGHLIGHT_USER.lower():
            expected_included_map[e["number"]] = e

    expected_included = list(expected_included_map.values())
    # Sort expected included by score ascending for display validation
    expected_included.sort(key=lambda e: e["score"])

    # Compute expectations for summary
    best_score = None
    best_pr_number = None
    if entries:
        best_e = min(entries, key=lambda e: e["score"])
        best_score = best_e["score"]
        best_pr_number = int(best_e["number"]) if best_e["number"] is not None else None

    # Dexhunter highlight expectation (choose best ranked one if multiple)
    dex_entries = [e for e in entries if isinstance(e.get("author"), str) and e["author"].lower() == HIGHLIGHT_USER.lower()]
    expected_highlight = None
    if dex_entries:
        dex_best = min(dex_entries, key=lambda e: e["score"])
        expected_highlight = {
            "username": HIGHLIGHT_USER,
            "rank": dex_best["rank"],
            "val_bpb": dex_best["score"],
            "gap_to_best": round(dex_best["score"] - best_score, 5) if best_score is not None else None,
            "pr_number": dex_best["number"],
        }

    # Now validate outputs
    # CSV existence and header
    if os.path.isfile(csv_path):
        checks["has_leaderboard_csv"] = True
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                expected_header = ["rank", "val_bpb", "pr", "status", "author", "date", "title", "suspect", "category"]
                if fieldnames == expected_header:
                    checks["csv_header_ok"] = True
                rows = list(reader)
        except Exception:
            rows = []
    else:
        rows = []

    # Summary existence
    if os.path.isfile(summary_path):
        checks["has_summary_json"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception:
            summary = {}
    else:
        summary = {}

    # If missing required artifacts, force reward 0 later by keeping other checks mostly false
    # Proceed with validations only if we have both csv and summary
    if checks["has_leaderboard_csv"] and checks["has_summary_json"] and checks["csv_header_ok"]:
        # Parse CSV rows into comparable records
        def parse_bool_str(s):
            if isinstance(s, bool):
                return s
            if isinstance(s, str):
                return s.strip().lower() in ("true", "1", "yes")
            return False

        def safe_float(s):
            try:
                return float(s)
            except Exception:
                return None

        parsed_rows = []
        for r in rows:
            try:
                pr_num = None
                try:
                    pr_num = int(str(r.get("pr", "")).strip().lstrip("#"))
                except Exception:
                    pr_num = None
                parsed_rows.append({
                    "rank": int(r["rank"]) if str(r.get("rank", "")).strip().isdigit() else None,
                    "val_bpb": safe_float(r.get("val_bpb")),
                    "pr": pr_num,
                    "status": (r.get("status") or "").strip(),
                    "author": (r.get("author") or "").strip(),
                    "date": (r.get("date") or "").strip(),
                    "title": r.get("title") or "",
                    "suspect": parse_bool_str(r.get("suspect")),
                    "category": (r.get("category") or "").strip(),
                })
            except Exception:
                continue

        # Validate sorting by val_bpb ascending for included subset and ranks matching expected ranks from full list
        sorted_ok = True
        prev_score = None
        for r in parsed_rows:
            if r["val_bpb"] is None:
                sorted_ok = False
                break
            if prev_score is not None and r["val_bpb"] < prev_score - 1e-12:
                sorted_ok = False
                break
            prev_score = r["val_bpb"]
        # Validate ranks match expected ranks for those PRs
        ranks_ok = True
        exp_rank_by_pr = {e["number"]: e["rank"] for e in entries}
        for r in parsed_rows:
            if r["pr"] in exp_rank_by_pr:
                if r["rank"] != exp_rank_by_pr[r["pr"]]:
                    ranks_ok = False
                    break
            else:
                ranks_ok = False
                break
        checks["csv_sorted_and_ranked_ok"] = sorted_ok and ranks_ok

        # Validate records-only and no suspects, and statuses
        recs_only_ok = True
        statuses_ok = True
        for r in parsed_rows:
            # category must be 'record' per rules
            if r["category"].lower() != "record":
                recs_only_ok = False
                break
            # suspect must be false
            if r["suspect"]:
                recs_only_ok = False
                break
            # status validation: merged if merged_at present in source, else open (from expected)
            exp = next((e for e in expected_included if e["number"] == r["pr"]), None)
            if exp is None:
                # Might be highlight from filtered set; try from all entries
                exp = next((e for e in entries if e["number"] == r["pr"]), None)
            if exp is None:
                statuses_ok = False
                break
            if r["status"] != exp["status"]:
                statuses_ok = False
                break
            # date must be created_at date
            if r["date"] != exp["date"]:
                statuses_ok = False
                break
            # author must match
            if r["author"] != exp["author"]:
                statuses_ok = False
                break
        checks["records_only_and_no_suspects"] = recs_only_ok
        checks["statuses_ok"] = statuses_ok

        # Validate topN with highlight inclusion: set equivalence with expected_included
        csv_prs = [r["pr"] for r in parsed_rows if r.get("pr") is not None]
        csv_set = set(csv_prs)
        expected_set = set(e["number"] for e in expected_included)
        checks["csv_matches_expected_set"] = (csv_set == expected_set and len(parsed_rows) == len(expected_included))

        # Specifically verify topN logic and highlight outside topN included when applicable
        # Determine if there exists a dexhunter entry with rank > TOP_N
        dex_outside = [e for e in entries if e["author"].lower() == HIGHLIGHT_USER and e["rank"] > TOP_N]
        topn_ok = True
        # If there is a dexhunter outside topN, ensure at least one such PR appears in CSV
        if dex_outside:
            if not any(e["number"] in csv_set for e in dex_outside):
                topn_ok = False
        # Ensure that all non-dexhunter rows in CSV are within topN ranks
        for r in parsed_rows:
            exp = next((e for e in entries if e["number"] == r["pr"]), None)
            if not exp:
                topn_ok = False
                break
            if exp["author"].lower() != HIGHLIGHT_USER and exp["rank"] > TOP_N:
                topn_ok = False
                break
        checks["topn_with_highlight_ok"] = topn_ok

        # Validate summary fields
        summary_ok = True
        try:
            bs = summary.get("best_score", None)
            bpn = summary.get("best_pr_number", None)
            tr = summary.get("total_rows", None)
            sr = summary.get("scored_rows", None)
            hl = summary.get("highlight", None)

            # Basic types
            if best_score is None or best_pr_number is None:
                # If no entries expected, then CSV should be empty and best fields may be null
                if entries:
                    summary_ok = False
                else:
                    # No entries case: require zero rows and fields may be null/0
                    if len(parsed_rows) != 0:
                        summary_ok = False
            else:
                # Compare best_score and best_pr_number (allow small float tolerance)
                if not isinstance(bs, (int, float)) or abs(float(bs) - float(best_score)) > 1e-9:
                    summary_ok = False
                if int(bpn) != int(best_pr_number):
                    summary_ok = False

            # total_rows equals csv rows count
            if int(tr) != len(parsed_rows):
                summary_ok = False
            # scored_rows equals number of rows with numeric val_bpb (all rows should be scored)
            scored_rows_count = sum(1 for r in parsed_rows if isinstance(r["val_bpb"], float))
            if int(sr) != scored_rows_count:
                summary_ok = False

            # Highlight object
            if not isinstance(hl, dict):
                summary_ok = False
            else:
                if hl.get("username") != HIGHLIGHT_USER:
                    summary_ok = False
                # If expected_highlight exists, validate rank, val_bpb, gap
                if expected_highlight:
                    # Check that highlighted PR is present in CSV set
                    if expected_highlight["pr_number"] not in csv_set:
                        summary_ok = False
                    # Rank and val_bpb
                    if int(hl.get("rank", -1)) != int(expected_highlight["rank"]):
                        summary_ok = False
                    try:
                        hv = float(hl.get("val_bpb"))
                        if abs(hv - expected_highlight["val_bpb"]) > 1e-9:
                            summary_ok = False
                    except Exception:
                        summary_ok = False
                    # Gap rounding to 5 decimals
                    try:
                        gap_val = float(hl.get("gap_to_best"))
                        if round(gap_val, 5) != expected_highlight["gap_to_best"]:
                            summary_ok = False
                    except Exception:
                        summary_ok = False
                else:
                    # If no expected highlight, allow rank to be null/None and val_bpb to be null/None
                    # But require username present
                    pass
        except Exception:
            summary_ok = False
        checks["summary_fields_ok"] = summary_ok

        # Validate highlight consistency between CSV and summary (if highlight exists)
        highlight_consistent = True
        if expected_highlight:
            # Find CSV row for highlighted PR (best one)
            hl_pr = expected_highlight["pr_number"]
            csv_row = next((r for r in parsed_rows if r["pr"] == hl_pr), None)
            if not csv_row:
                highlight_consistent = False
            else:
                # Rank and val_bpb must match
                if csv_row["rank"] != expected_highlight["rank"]:
                    highlight_consistent = False
                if csv_row["val_bpb"] is None or abs(csv_row["val_bpb"] - expected_highlight["val_bpb"]) > 1e-9:
                    highlight_consistent = False
        checks["highlight_consistency_ok"] = highlight_consistent

    # Compute reward: if required artifacts missing or header wrong, reward is 0.0
    required_ok = checks["has_leaderboard_csv"] and checks["has_summary_json"] and checks["csv_header_ok"]
    if not required_ok:
        reward = 0.0
    else:
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total if total > 0 else 0.0
        # Clamp
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Print single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()