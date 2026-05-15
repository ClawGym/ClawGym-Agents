import csv
import json
import os
import re
import sys
from typing import Dict, List, Tuple, Any

def parse_float(value: str) -> float:
    # Allow $ and commas, trim spaces
    s = str(value).strip().replace("$", "").replace(",", "")
    return float(s)

def is_int_in_range(value: str, lo: int, hi: int) -> Tuple[bool, int]:
    try:
        iv = int(str(value).strip())
    except Exception:
        return False, 0
    return (lo <= iv <= hi), iv

def read_csv_with_header(path: str) -> Tuple[bool, List[Dict[str, str]], List[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            # Peek header line
            first_line = f.readline()
            if first_line == "":
                return False, [], []
            header = [h.strip() for h in first_line.rstrip("\n").split(",")]
            # Rewind and read with csv for rows
            f.seek(0)
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            return True, rows, header
    except Exception:
        return False, [], []

def priority_from_score(score: int) -> str:
    if 20 <= score <= 25:
        return "Critical"
    if 15 <= score <= 19:
        return "High"
    if 8 <= score <= 14:
        return "Medium"
    if 1 <= score <= 7:
        return "Low"
    return ""

def count_priorities(rows: List[Dict[str, str]]) -> Dict[str, int]:
    counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for r in rows:
        p = r.get("Priority", "").strip()
        if p in counts:
            counts[p] += 1
    return counts

def safe_load_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return True, data
    except Exception:
        return False, None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {}

    # Initialize all checks to False
    check_names = [
        # CSV checks
        "csv_exists",
        "csv_non_empty",
        "csv_header_exact",
        "csv_min_rows",
        "csv_categories_valid",
        "csv_each_category_at_least_two",
        "csv_likelihood_impact_int_range",
        "csv_score_correct_all",
        "csv_priority_correct_all",
        "csv_deadline_iso_all",
        "csv_cost_positive_all",
        "csv_residual_li_int_range",
        "csv_residual_score_correct_all",
        "csv_residual_improved_80pct",
        # Heatmap checks
        "heatmap_exists",
        "heatmap_has_labels_once_each",
        "heatmap_totals_line_present",
        "heatmap_totals_match_csv",
        # Summary checks
        "summary_exists",
        "summary_valid_json",
        "summary_required_keys_present",
        "summary_total_risks_matches_csv",
        "summary_by_category_matches_csv",
        "summary_highest_score_matches_csv",
        "summary_budget_total_matches_csv_sum",
        "summary_within_budget_logic_correct",
    ]
    for name in check_names:
        checks[name] = False

    # Paths
    csv_path = os.path.join(output_dir, "risk_register.csv")
    heatmap_path = os.path.join(output_dir, "risk_heatmap.md")
    summary_path = os.path.join(output_dir, "summary.json")

    # CSV validations
    expected_header = [
        "Risk #",
        "Risk description",
        "Category",
        "Likelihood",
        "Impact",
        "Score",
        "Priority",
        "Mitigation strategy",
        "Owner",
        "Deadline",
        "Cost",
        "Residual Likelihood",
        "Residual Impact",
        "Residual Score",
    ]
    csv_loaded = False
    rows: List[Dict[str, str]] = []
    header: List[str] = []

    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        # Non-empty check
        try:
            if os.path.getsize(csv_path) > 0:
                checks["csv_non_empty"] = True
        except Exception:
            pass

        ok_read, parsed_rows, parsed_header = read_csv_with_header(csv_path)
        if ok_read:
            rows = parsed_rows
            header = parsed_header

            if header == expected_header:
                checks["csv_header_exact"] = True

            if len(rows) >= 12 and checks["csv_header_exact"]:
                checks["csv_min_rows"] = True

            # Only proceed with deeper checks if header is exact and we have rows
            if checks["csv_header_exact"] and len(rows) > 0:
                csv_loaded = True

                # Categories validation
                allowed_categories = {"operational", "financial", "technical", "regulatory", "reputational", "strategic"}
                categories_ok = True
                category_counts: Dict[str, int] = {k: 0 for k in allowed_categories}
                for r in rows:
                    cat = r.get("Category", "").strip()
                    if cat not in allowed_categories:
                        categories_ok = False
                        break
                    category_counts[cat] += 1
                if categories_ok:
                    checks["csv_categories_valid"] = True
                    if all(category_counts[k] >= 2 for k in allowed_categories):
                        checks["csv_each_category_at_least_two"] = True

                # Likelihood/Impact int range and score correctness, priority correctness
                li_ok = True
                score_ok = True
                priority_ok = True
                deadline_ok = True
                cost_ok = True
                resid_li_ok = True
                resid_score_ok = True
                residual_better_count = 0

                iso_date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")

                for r in rows:
                    lik_valid, lik = is_int_in_range(r.get("Likelihood", ""), 1, 5)
                    imp_valid, imp = is_int_in_range(r.get("Impact", ""), 1, 5)
                    if not (lik_valid and imp_valid):
                        li_ok = False

                    # Score check
                    try:
                        score_val = int(str(r.get("Score", "")).strip())
                    except Exception:
                        score_ok = False
                        score_val = -1
                    if lik_valid and imp_valid:
                        if score_val != (lik * imp):
                            score_ok = False
                    else:
                        score_ok = False

                    # Priority check
                    expected_p = priority_from_score(score_val)
                    if expected_p == "" or r.get("Priority", "").strip() != expected_p:
                        priority_ok = False

                    # Deadline ISO YYYY-MM-DD
                    deadline_val = r.get("Deadline", "").strip()
                    if not iso_date_re.match(deadline_val):
                        deadline_ok = False

                    # Cost positive number
                    try:
                        cval = parse_float(r.get("Cost", ""))
                        if not (cval > 0):
                            cost_ok = False
                    except Exception:
                        cost_ok = False

                    # Residual LI int range and residual score correctness
                    rlik_valid, rlik = is_int_in_range(r.get("Residual Likelihood", ""), 1, 5)
                    rimp_valid, rimp = is_int_in_range(r.get("Residual Impact", ""), 1, 5)
                    if not (rlik_valid and rimp_valid):
                        resid_li_ok = False
                    try:
                        rscore_val = int(str(r.get("Residual Score", "")).strip())
                    except Exception:
                        resid_score_ok = False
                        rscore_val = -1
                    if rlik_valid and rimp_valid:
                        if rscore_val != (rlik * rimp):
                            resid_score_ok = False
                    else:
                        resid_score_ok = False

                    # Residual improvement
                    if rscore_val <= score_val and rscore_val >= 0 and score_val >= 0:
                        residual_better_count += 1

                if li_ok:
                    checks["csv_likelihood_impact_int_range"] = True
                if score_ok:
                    checks["csv_score_correct_all"] = True
                if priority_ok:
                    checks["csv_priority_correct_all"] = True
                if deadline_ok:
                    checks["csv_deadline_iso_all"] = True
                if cost_ok:
                    checks["csv_cost_positive_all"] = True
                if resid_li_ok:
                    checks["csv_residual_li_int_range"] = True
                if resid_score_ok:
                    checks["csv_residual_score_correct_all"] = True

                if len(rows) > 0:
                    fraction = residual_better_count / len(rows)
                    if fraction >= 0.8:
                        checks["csv_residual_improved_80pct"] = True

    # Heatmap validations
    if os.path.isfile(heatmap_path):
        checks["heatmap_exists"] = True
        text = safe_load_text(heatmap_path)
        if text:
            # Labels exactly once
            labels = ["🔴 Critical", "🟠 High", "🟡 Medium", "🟢 Low"]
            counts = [text.count(label) for label in labels]
            if all(c == 1 for c in counts):
                checks["heatmap_has_labels_once_each"] = True

            # Totals line present exactly once
            totals_pattern = re.compile(r"^Totals: Critical=(\d+), High=(\d+), Medium=(\d+), Low=(\d+)\s*$", re.MULTILINE)
            matches = totals_pattern.findall(text)
            if len(matches) == 1:
                checks["heatmap_totals_line_present"] = True
                if csv_loaded:
                    X, Y, Z, W = map(int, matches[0])
                    csv_priority_counts = count_priorities(rows)
                    if (
                        X == csv_priority_counts["Critical"]
                        and Y == csv_priority_counts["High"]
                        and Z == csv_priority_counts["Medium"]
                        and W == csv_priority_counts["Low"]
                    ):
                        checks["heatmap_totals_match_csv"] = True

    # Summary validations
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        ok_json, data = load_json(summary_path)
        if ok_json and isinstance(data, dict):
            checks["summary_valid_json"] = True

            required_keys_present = (
                "total_risks" in data
                and "by_category" in data
                and "highest_score" in data
                and "budget_cap" in data
                and "budget_total_mitigation_cost" in data
                and "within_budget" in data
            )
            # by_category exact keys check
            by_cat_ok = False
            if required_keys_present and isinstance(data.get("by_category"), dict):
                by_cat = data["by_category"]
                expected_cats = {"operational", "financial", "technical", "regulatory", "reputational", "strategic"}
                if set(by_cat.keys()) == expected_cats:
                    by_cat_ok = True

            # types basic expectations
            if required_keys_present and by_cat_ok:
                checks["summary_required_keys_present"] = True

            if csv_loaded and checks["summary_required_keys_present"]:
                # total risks match
                try:
                    total_risks_val = int(data["total_risks"])
                    if total_risks_val == len(rows):
                        checks["summary_total_risks_matches_csv"] = True
                except Exception:
                    pass

                # by_category counts match CSV
                try:
                    by_cat = data["by_category"]
                    # Build CSV counts
                    allowed_categories = ["operational", "financial", "technical", "regulatory", "reputational", "strategic"]
                    csv_cat_counts: Dict[str, int] = {k: 0 for k in allowed_categories}
                    for r in rows:
                        cat = r.get("Category", "").strip()
                        if cat in csv_cat_counts:
                            csv_cat_counts[cat] += 1
                    if all(int(by_cat[k]) == csv_cat_counts[k] for k in allowed_categories):
                        checks["summary_by_category_matches_csv"] = True
                except Exception:
                    pass

                # highest_score matches CSV
                try:
                    hs = data["highest_score"]
                    if isinstance(hs, dict) and "risk_number" in hs and "score" in hs:
                        # compute max score from CSV
                        max_score = None
                        risk_numbers_with_max: List[str] = []
                        for r in rows:
                            try:
                                sc = int(str(r["Score"]).strip())
                            except Exception:
                                continue
                            rn = str(r.get("Risk #", "")).strip()
                            if max_score is None or sc > max_score:
                                max_score = sc
                                risk_numbers_with_max = [rn]
                            elif sc == max_score:
                                risk_numbers_with_max.append(rn)
                        if max_score is not None:
                            hs_score = int(hs["score"])
                            hs_rn = str(hs["risk_number"])
                            if hs_score == max_score and hs_rn in risk_numbers_with_max:
                                checks["summary_highest_score_matches_csv"] = True
                except Exception:
                    pass

                # budget total matches sum of CSV costs (±0.01)
                try:
                    budget_total = float(data["budget_total_mitigation_cost"])
                    sum_costs = 0.0
                    for r in rows:
                        sum_costs += parse_float(r.get("Cost", "0"))
                    if abs(budget_total - sum_costs) <= 0.01:
                        checks["summary_budget_total_matches_csv_sum"] = True
                except Exception:
                    pass

                # within_budget logic is correct
                try:
                    budget_cap = float(data["budget_cap"])
                    budget_total = float(data["budget_total_mitigation_cost"])
                    within = bool(data["within_budget"])
                    if within == (budget_total <= budget_cap):
                        checks["summary_within_budget_logic_correct"] = True
                except Exception:
                    pass

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or all three required files missing, reward must be 0.0
    if not os.path.isdir(output_dir) or not (os.path.isfile(csv_path) or os.path.isfile(heatmap_path) or os.path.isfile(summary_path)):
        reward = 0.0

    # Print final JSON (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()