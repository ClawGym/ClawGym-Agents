import json
import os
import sys
import csv
import math
import re

def load_json(path):
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

def load_csv_rows(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
    except Exception:
        return None
    return rows

def is_int_between(v, lo, hi):
    return isinstance(v, int) and lo <= v <= hi

def approx_equal(a, b, tol=0.01):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def sentence_count(text):
    # Count sentence-ending punctuation . ! ?
    if not isinstance(text, str):
        return 0
    # Normalize spaces
    t = text.strip()
    # Use regex to split sentences conservatively
    parts = re.split(r'(?<=[.!?])\s+', t)
    # Filter out empty tokens
    parts = [p for p in parts if p.strip()]
    return len(parts)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_report_json": False,
        "has_summary_md": False,
        "has_tier1_csv": False,
        "brand_fields_ok": False,
        "brand_summary_sentence_count_ok": False,
        "prompts_nonempty": False,
        "categories_exactly_7": False,
        "category_counts_ok": False,
        "scores_valid": False,
        "priority_formula_ok": False,
        "tiers_ok": False,
        "coverage_tier1_present_valid": False,
        "coverage_non_tier1_null_or_missing": False,
        "gap_analysis_matches_tier1_none": False,
        "recommendations_ok": False,
        "summary_headings_ok": False,
        "csv_matches_tier1": False
    }

    report_path = os.path.join(output_dir, "aeo_report.json")
    summary_path = os.path.join(output_dir, "aeo_summary.md")
    csv_path = os.path.join(output_dir, "tier1_coverage.csv")

    report = None
    if os.path.isfile(report_path):
        checks["has_report_json"] = True
        report = load_json(report_path)

    if os.path.isfile(summary_path):
        checks["has_summary_md"] = True

    if os.path.isfile(csv_path):
        checks["has_tier1_csv"] = True

    # Early parse validations
    if report and isinstance(report, dict):
        # Brand fields
        brand = report.get("brand")
        if isinstance(brand, dict):
            name = brand.get("name")
            domain = brand.get("domain")
            summary = brand.get("summary")
            if isinstance(name, str) and name.strip() and isinstance(domain, str) and domain.strip():
                checks["brand_fields_ok"] = True
            # Sentence count 2-3
            sc = sentence_count(summary) if isinstance(summary, str) else 0
            if 2 <= sc <= 3:
                checks["brand_summary_sentence_count_ok"] = True

        # Prompts array
        prompts = report.get("prompts")
        if isinstance(prompts, list) and len(prompts) > 0:
            checks["prompts_nonempty"] = True

            required_categories = {
                "Problem-aware",
                "Solution-aware",
                "Comparison",
                "Best-of",
                "How-to",
                "Evaluation",
                "Industry",
            }
            categories_in_data = set()
            for p in prompts:
                if isinstance(p, dict):
                    cat = p.get("category")
                    if isinstance(cat, str):
                        categories_in_data.add(cat)

            if categories_in_data == required_categories:
                checks["categories_exactly_7"] = True

            # Count per category 5-15
            counts_ok = True
            for cat in required_categories:
                count_cat = sum(1 for p in prompts if isinstance(p, dict) and p.get("category") == cat)
                if not (5 <= count_cat <= 15):
                    counts_ok = False
                    break
            checks["category_counts_ok"] = counts_ok

            # Scores, priority, tiers and coverage
            scores_ok = True
            priority_ok = True
            tiers_ok = True
            tier1_coverage_ok = True
            non_tier1_coverage_ok = True

            tier1_prompts = []
            tier1_none_prompts = set()

            for p in prompts:
                if not isinstance(p, dict):
                    scores_ok = False
                    priority_ok = False
                    tiers_ok = False
                    tier1_coverage_ok = False
                    non_tier1_coverage_ok = False
                    continue

                scores = p.get("scores")
                if not isinstance(scores, dict):
                    scores_ok = False
                    continue
                rel = scores.get("relevance")
                vol = scores.get("volume")
                win = scores.get("winability")
                intent = scores.get("intent")
                if not (is_int_between(rel, 1, 5) and is_int_between(vol, 1, 5) and is_int_between(win, 1, 5) and is_int_between(intent, 1, 5)):
                    scores_ok = False

                # Priority
                pr = p.get("priority")
                if not isinstance(pr, (int, float)):
                    priority_ok = False
                else:
                    expected = (rel * 2 + vol + win + intent) / 5 if all(isinstance(x, int) for x in [rel, vol, win, intent]) else None
                    if expected is None or not approx_equal(pr, expected, tol=0.01):
                        priority_ok = False

                # Tiers
                tier = p.get("tier")
                if isinstance(pr, (int, float)):
                    expected_tier = None
                    if pr >= 3.5:
                        expected_tier = "Tier 1"
                    elif 2.5 <= pr <= 3.4:
                        expected_tier = "Tier 2"
                    else:
                        expected_tier = "Tier 3"
                    if tier != expected_tier:
                        tiers_ok = False
                else:
                    tiers_ok = False

                # Coverage rules
                coverage = p.get("coverage") if "coverage" in p else None
                if p.get("tier") == "Tier 1":
                    # Must be present and one of allowed
                    if not (isinstance(coverage, str) and coverage in {"Strong", "Partial", "None"}):
                        tier1_coverage_ok = False
                    else:
                        tier1_prompts.append(p)
                        if coverage == "None":
                            prom_text = p.get("prompt")
                            if isinstance(prom_text, str):
                                tier1_none_prompts.add(prom_text)
                else:
                    # For non-Tier1, coverage should be omitted or null
                    if coverage is not None and coverage != "":
                        # If coverage present as non-null, this violates "omit or null"
                        non_tier1_coverage_ok = False

            checks["scores_valid"] = scores_ok
            checks["priority_formula_ok"] = priority_ok
            checks["tiers_ok"] = tiers_ok
            checks["coverage_tier1_present_valid"] = tier1_coverage_ok
            checks["coverage_non_tier1_null_or_missing"] = non_tier1_coverage_ok

            # Gap analysis
            gap = report.get("content_gap_analysis")
            gap_ok = False
            if isinstance(gap, list):
                # Extract referenced prompt strings from gap list
                referenced = set()
                all_valid_items = True
                for item in gap:
                    if isinstance(item, str):
                        referenced.add(item)
                    elif isinstance(item, dict):
                        # Prefer a key named 'prompt'; fallback to 'target_prompt_or_cluster'
                        if "prompt" in item and isinstance(item["prompt"], str):
                            referenced.add(item["prompt"])
                        elif "target_prompt_or_cluster" in item and isinstance(item["target_prompt_or_cluster"], str):
                            # Only count this if it exactly matches a Tier1 None prompt text
                            referenced.add(item["target_prompt_or_cluster"])
                        else:
                            all_valid_items = False
                    else:
                        all_valid_items = False
                # Check that referenced equals the set of Tier1 None prompts
                if all_valid_items and referenced == tier1_none_prompts:
                    gap_ok = True
            checks["gap_analysis_matches_tier1_none"] = gap_ok

            # Recommendations
            recs = report.get("recommendations")
            recs_ok = False
            if isinstance(recs, list) and len(recs) >= 5:
                all_rec_fields = True
                for r in recs:
                    if not isinstance(r, dict):
                        all_rec_fields = False
                        break
                    title = r.get("title")
                    target = r.get("target_prompt_or_cluster")
                    rationale = r.get("rationale")
                    if not (isinstance(title, str) and title.strip() and isinstance(target, str) and target.strip() and isinstance(rationale, str) and rationale.strip()):
                        all_rec_fields = False
                        break
                if all_rec_fields:
                    recs_ok = True
            checks["recommendations_ok"] = recs_ok

        # Summary headings
        if checks["has_summary_md"]:
            txt = read_text(summary_path)
            headings_ok = all(h in txt for h in ["## Brand Summary", "## Priority Prompts", "## Content Gap Analysis", "## Recommended Next Steps"])
            checks["summary_headings_ok"] = headings_ok

        # CSV matches Tier 1
        if checks["has_tier1_csv"] and isinstance(report, dict) and isinstance(report.get("prompts"), list):
            rows = load_csv_rows(csv_path)
            if rows is not None:
                # Build dict for Tier 1 by prompt text for exact matching
                tier1 = [p for p in report["prompts"] if isinstance(p, dict) and p.get("tier") == "Tier 1"]
                # Build mapping from prompt text to (category, priority, coverage)
                tier1_map = {}
                valid_tier1 = True
                for p in tier1:
                    pt = p.get("prompt")
                    cat = p.get("category")
                    pr = p.get("priority")
                    cov = p.get("coverage") if "coverage" in p else None
                    if not (isinstance(pt, str) and isinstance(cat, str) and isinstance(pr, (int, float)) and isinstance(cov, str)):
                        valid_tier1 = False
                        break
                    tier1_map[pt] = (cat, float(pr), cov)
                if valid_tier1:
                    # CSV header must include exactly the columns prompt,category,priority,coverage in any case-sensitive order?
                    # Requirement specifies columns with these names; enforce presence and use those keys.
                    header_ok = True
                    # DictReader ensures headers are keys in rows; check first row's keys
                    if len(rows) > 0:
                        keys = rows[0].keys()
                        required_cols = ["prompt", "category", "priority", "coverage"]
                        header_ok = all(col in keys for col in required_cols)
                    # Now match content: CSV must include only Tier 1 prompts, count must match
                    content_ok = True
                    if header_ok:
                        if len(rows) != len(tier1_map):
                            content_ok = False
                        else:
                            seen_prompts = set()
                            for r in rows:
                                pt = r.get("prompt", "")
                                cat = r.get("category", "")
                                pr_str = r.get("priority", "")
                                cov = r.get("coverage", "")
                                if pt not in tier1_map:
                                    content_ok = False
                                    break
                                exp_cat, exp_pr, exp_cov = tier1_map[pt]
                                # Compare category
                                if cat != exp_cat:
                                    content_ok = False
                                    break
                                # Compare coverage
                                if cov != exp_cov:
                                    content_ok = False
                                    break
                                # Compare priority within tolerance
                                try:
                                    pr_val = float(pr_str)
                                except Exception:
                                    content_ok = False
                                    break
                                if not approx_equal(pr_val, exp_pr, tol=0.01):
                                    content_ok = False
                                    break
                                seen_prompts.add(pt)
                            if content_ok and seen_prompts != set(tier1_map.keys()):
                                content_ok = False
                    checks["csv_matches_tier1"] = header_ok and content_ok

    # Compute reward as proportion of passed checks, but enforce baseline: if any of the three primary outputs missing -> reward 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    if not (checks["has_report_json"] and checks["has_summary_md"] and checks["has_tier1_csv"]):
        reward = 0.0

    # Clamp reward to [0,1]
    reward = max(0.0, min(1.0, float(reward)))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()