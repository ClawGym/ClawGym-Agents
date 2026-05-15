import json
import os
import sys
import re
import csv
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {}

    # Helper: initialize to False for artifact-dependent checks
    def set_check(name: str, value: bool):
        checks[name] = bool(value)

    # Read input jobs
    input_path = os.path.join(input_dir, "job_posts.jsonl")
    jobs: List[Dict[str, Any]] = []
    if os.path.isfile(input_path):
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            jobs.append(obj)
                    except json.JSONDecodeError:
                        # skip malformed lines
                        pass
        except Exception:
            pass

    # Non-scoring informational check
    set_check("input_jobs_loaded", bool(jobs))

    # Prepare per-job checks
    job_ids: List[str] = []
    for job in jobs:
        jid = str(job.get("id"))
        job_ids.append(jid)
        set_check(f"proposal_{jid}_exists", False)
        set_check(f"proposal_{jid}_valid", False)

    # Validation helpers
    def is_number(x: Any) -> bool:
        return (isinstance(x, (int, float)) and not isinstance(x, bool))

    def nearly_equal(a: float, b: float, eps: float = 1e-6) -> bool:
        try:
            return abs(float(a) - float(b)) <= eps
        except Exception:
            return False

    def parse_iso_utc(s: str) -> bool:
        if not isinstance(s, str) or not s:
            return False
        # Accept ISO8601 with 'Z' or +00:00
        st = s
        if st.endswith("Z"):
            st = st[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(st)
            if dt.tzinfo is None:
                return False
            # require UTC
            return dt.tzinfo.utcoffset(dt) == timezone.utc.utcoffset(dt)
        except Exception:
            return False

    REASONS_LABELS = [
        "Budget match:",
        "Requirement clarity:",
        "Skill fit:",
        "Client quality:",
        "Delivery feasibility:",
    ]
    SCORE_PATTERN = re.compile(r"\d+\s*/\s*\d+")

    # Load proposals
    proposals_dir = os.path.join(output_dir, "proposals")
    proposals_map: Dict[str, Dict[str, Any]] = {}

    for job in jobs:
        jid = str(job.get("id"))
        p_path = os.path.join(proposals_dir, f"{jid}.json")
        if os.path.isfile(p_path):
            set_check(f"proposal_{jid}_exists", True)
            try:
                with open(p_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                proposals_map[jid] = data
            except Exception:
                # keep valid as False
                pass

    # Validate proposals content
    for job in jobs:
        jid = str(job.get("id"))
        data = proposals_map.get(jid)
        if not isinstance(data, dict):
            continue

        valid = True

        # score
        score = data.get("score")
        if not (isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 100):
            valid = False

        # decision
        decision = data.get("decision")
        if decision not in ("BID", "MAYBE", "SKIP"):
            valid = False
        else:
            # Check thresholds
            if isinstance(score, int):
                expected_decision = "BID" if score >= 70 else ("MAYBE" if score >= 50 else "SKIP")
                if decision != expected_decision:
                    valid = False

        # summary
        summary = data.get("summary")
        if not (isinstance(summary, str) and summary.strip()):
            valid = False

        # reasons
        reasons = data.get("reasons")
        if not (isinstance(reasons, list) and len(reasons) == 5):
            valid = False
        else:
            # Check each expected label appears exactly once and contains x/y
            labels_found = {lbl: 0 for lbl in REASONS_LABELS}
            for r in reasons:
                if not isinstance(r, str):
                    valid = False
                    break
                matched_label = None
                for lbl in REASONS_LABELS:
                    if r.startswith(lbl):
                        matched_label = lbl
                        break
                if matched_label is None:
                    valid = False
                    break
                labels_found[matched_label] += 1
                # must contain x/y score pattern after the label
                after = r[len(matched_label):]
                if SCORE_PATTERN.search(after) is None:
                    valid = False
                    break
            if valid:
                # ensure each label exactly once
                if any(c != 1 for c in labels_found.values()):
                    valid = False

        # proposal_en length
        proposal_en = data.get("proposal_en")
        if not (isinstance(proposal_en, str) and len(proposal_en) >= 100):
            valid = False

        # followups object
        followups = data.get("followups")
        if not (isinstance(followups, dict) and
                isinstance(followups.get("d1"), str) and followups.get("d1").strip() and
                isinstance(followups.get("d3"), str) and followups.get("d3").strip() and
                isinstance(followups.get("d7"), str) and followups.get("d7").strip()):
            valid = False

        # milestones array of exactly 3 objects with name and amount numbers
        milestones = data.get("milestones")
        if not (isinstance(milestones, list) and len(milestones) == 3):
            valid = False
        else:
            for m in milestones:
                if not (isinstance(m, dict) and isinstance(m.get("name"), str) and m.get("name").strip()
                        and is_number(m.get("amount"))):
                    valid = False
                    break

        # pricing object and alignment with budget
        pricing = data.get("pricing")
        budget = job.get("budget", {})
        budget_mode = budget.get("mode")
        if not isinstance(pricing, dict):
            valid = False
        else:
            if budget_mode == "hourly":
                # required keys
                if pricing.get("type") != "hourly":
                    valid = False
                else:
                    rec = pricing.get("recommended_rate")
                    low = pricing.get("alt_rate_low")
                    high = pricing.get("alt_rate_high")
                    if not (is_number(rec) and is_number(low) and is_number(high)):
                        valid = False
                    else:
                        # compare to input min/max
                        min_rate = budget.get("min_rate")
                        max_rate = budget.get("max_rate")
                        if not (is_number(min_rate) and is_number(max_rate)):
                            valid = False
                        else:
                            if not nearly_equal(low, min_rate) or not nearly_equal(high, max_rate):
                                valid = False
                            # rounded midpoint acceptance: either Python round (banker's) or half-up
                            try:
                                mid = (float(min_rate) + float(max_rate)) / 2.0
                                py_round = int(round(mid))
                                half_up = int((mid + 0.5) // 1) if mid >= 0 else int(-((-mid + 0.5) // 1))
                                # half_up alternative for negatives handled, though rates are non-negative typically
                                rec_val = float(rec)
                                if not (nearly_equal(rec_val, py_round) or nearly_equal(rec_val, half_up)):
                                    valid = False
                            except Exception:
                                valid = False
            elif budget_mode == "fixed":
                if pricing.get("type") != "fixed":
                    valid = False
                else:
                    total = pricing.get("total")
                    amount = budget.get("amount")
                    if not (is_number(total) and is_number(amount) and nearly_equal(total, amount)):
                        valid = False
                    else:
                        # milestones sum equals pricing.total
                        if isinstance(milestones, list) and len(milestones) == 3:
                            sum_amt = sum(float(m.get("amount")) for m in milestones if is_number(m.get("amount")))
                            if not nearly_equal(sum_amt, float(total)):
                                valid = False
                        else:
                            valid = False
            else:
                # unknown budget mode; cannot validate
                valid = False

        if valid:
            set_check(f"proposal_{jid}_valid", True)

    # Aggregate proposal checks
    all_exist = all(checks.get(f"proposal_{str(job.get('id'))}_exists", False) for job in jobs) if jobs else False
    all_valid = all(checks.get(f"proposal_{str(job.get('id'))}_valid", False) for job in jobs) if jobs else False
    set_check("all_proposals_exist", all_exist)
    set_check("all_proposals_valid", all_valid)

    # Validate summary.csv
    summary_csv_path = os.path.join(output_dir, "summary.csv")
    summary_csv_valid = False
    csv_rows_count_correct = False
    if os.path.isfile(summary_csv_path) and jobs:
        try:
            with open(summary_csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                expected_header = ["job_id", "title", "score", "decision", "pricing_type", "price_main_value"]
                if header == expected_header:
                    data_rows = rows[1:]
                    # Count rows must equal job count
                    if len(data_rows) == len(jobs):
                        csv_rows_count_correct = True
                    # Map by job_id
                    csv_map: Dict[str, List[str]] = {}
                    for r in data_rows:
                        if len(r) != 6:
                            csv_map = {}
                            break
                        jid = r[0]
                        csv_map[jid] = r
                    if csv_map and set(csv_map.keys()) == set(str(j.get("id")) for j in jobs):
                        consistency_ok = True
                        # Build job lookup
                        job_lookup = {str(j.get("id")): j for j in jobs}
                        for jid, row in csv_map.items():
                            j = job_lookup[jid]
                            title_in = str(j.get("title", ""))
                            # Title must match input
                            if row[1] != title_in:
                                consistency_ok = False
                                break
                            # Must have proposal JSON
                            pdata = proposals_map.get(jid)
                            if not isinstance(pdata, dict):
                                consistency_ok = False
                                break
                            # Score & decision consistency
                            try:
                                csv_score = int(row[2])
                            except Exception:
                                consistency_ok = False
                                break
                            csv_decision = row[3]
                            if not (csv_decision in ("BID", "MAYBE", "SKIP")):
                                consistency_ok = False
                                break
                            if not (isinstance(pdata.get("score"), int) and pdata.get("decision") in ("BID", "MAYBE", "SKIP")):
                                consistency_ok = False
                                break
                            if csv_score != pdata["score"] or csv_decision != pdata["decision"]:
                                consistency_ok = False
                                break
                            # pricing_type equals input budget.mode
                            budget_mode = j.get("budget", {}).get("mode")
                            if row[4] != budget_mode:
                                consistency_ok = False
                                break
                            # price_main_value from proposal JSON
                            try:
                                price_main_val = float(row[5])
                            except Exception:
                                consistency_ok = False
                                break
                            pricing = pdata.get("pricing", {})
                            if budget_mode == "hourly":
                                rec = pricing.get("recommended_rate")
                                if not is_number(rec) or not nearly_equal(price_main_val, float(rec)):
                                    consistency_ok = False
                                    break
                            elif budget_mode == "fixed":
                                total = pricing.get("total")
                                if not is_number(total) or not nearly_equal(price_main_val, float(total)):
                                    consistency_ok = False
                                    break
                            else:
                                consistency_ok = False
                                break
                        if consistency_ok and csv_rows_count_correct:
                            summary_csv_valid = True
        except Exception:
            summary_csv_valid = False
            csv_rows_count_correct = False
    set_check("summary_csv_valid", summary_csv_valid)
    set_check("csv_rows_count_correct", csv_rows_count_correct)

    # Validate shortlist.json
    shortlist_path = os.path.join(output_dir, "shortlist.json")
    shortlist_valid = False
    if os.path.isfile(shortlist_path) and proposals_map:
        try:
            with open(shortlist_path, "r", encoding="utf-8") as f:
                sl = json.load(f)
            if isinstance(sl, dict) and isinstance(sl.get("top_jobs"), list) and len(sl.get("top_jobs")) == 2 and isinstance(sl.get("generated_at"), str):
                top_jobs = [str(x) for x in sl["top_jobs"]]
                # ensure both exist in proposals set
                if all(jid in proposals_map for jid in top_jobs):
                    # parse ISO8601 UTC
                    if parse_iso_utc(sl["generated_at"]):
                        # Compute actual top 2 by score (desc), then tie by job_id ascending
                        scored_list: List[Tuple[str, int]] = []
                        for jid, pdata in proposals_map.items():
                            sc = pdata.get("score")
                            if isinstance(sc, int) and not isinstance(sc, bool):
                                scored_list.append((jid, sc))
                        if scored_list and len(scored_list) >= 2:
                            scored_list.sort(key=lambda t: (-t[1], t[0]))
                            expected_top = [scored_list[0][0], scored_list[1][0]]
                            if top_jobs == expected_top:
                                shortlist_valid = True
        except Exception:
            shortlist_valid = False
    set_check("shortlist_valid", shortlist_valid)

    # Compute reward
    reward = 0.0
    N = len(jobs)
    if N > 0:
        exists_count = sum(1 for job in jobs if checks.get(f"proposal_{str(job.get('id'))}_exists", False))
        valid_count = sum(1 for job in jobs if checks.get(f"proposal_{str(job.get('id'))}_valid", False))
        reward += 0.4 * (exists_count / N) if N > 0 else 0.0
        reward += 0.3 * (valid_count / N) if N > 0 else 0.0
        if checks.get("summary_csv_valid", False):
            reward += 0.15
        if checks.get("shortlist_valid", False):
            reward += 0.15

    # Baseline: if no outputs, reward = 0.0 (enforced by computation)
    reward = max(0.0, min(1.0, reward))

    # Print final JSON (exactly one object as last non-empty line)
    result_obj = {"reward": reward}
    # Merge checks
    result_obj.update(checks)
    print(json.dumps(result_obj, ensure_ascii=False))

if __name__ == "__main__":
    main()