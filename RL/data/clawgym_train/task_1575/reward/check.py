import os
import sys
import json
import csv
import re

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Velocity report
        "velocity_report_exists": False,
        "velocity_report_headers": False,
        "velocity_rows_expected_orders_correct": False,
        "velocity_rows_actual_orders_correct": False,
        "velocity_rows_status_correct": False,
        # Priority queue
        "priority_queue_exists": False,
        "priority_queue_headers": False,
        "priority_queue_rows_only_positive_gaps": False,
        "priority_queue_sorted_and_ranked": False,
        "priority_queue_prioritize_repeat": False,
        # Timing recommendations
        "timing_recommendations_exists": False,
        "timing_recommendations_headers": False,
        "timing_recommendations_days_in_window": False,
        "timing_recommendations_start_less_than_end": False,
        "timing_recommendations_rationale_present": False,
        # Compliance report
        "compliance_report_exists": False,
        "compliance_report_headers": False,
        "compliance_report_rows_complete": False,
        "compliance_report_prohibited_detection_correct": False,
        # Risk flags
        "risk_flags_exists": False,
        "risk_flags_headers": False,
        "risk_flags_rows_correct": False,
        # Templates
        "templates_exist_for_underperformers": False,
        "templates_requirements_met": False,
        # Policy notes
        "policy_notes_exists": False,
        "policy_notes_contains_required_phrases": False,
    }

    # Load inputs
    product_csv_path = os.path.join(input_dir, "product_data.csv")
    buyer_segments_path = os.path.join(input_dir, "buyer_segments.json")

    # Parse input data
    product_rows = []
    if os.path.isfile(product_csv_path):
        with open(product_csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                product_rows.append(row)

    buyer_segments = {}
    if os.path.isfile(buyer_segments_path):
        try:
            with open(buyer_segments_path, encoding='utf-8') as f:
                buyer_segments = json.load(f)
        except Exception:
            buyer_segments = {}

    # Helper mappings and functions
    def normalize_category(cat):
        if cat is None:
            return ""
        c = cat.strip()
        c = c.replace(" / ", "/")
        c = re.sub(r"\s+", " ", c)
        return c

    expected_map = {
        "Electronics": 50,
        "Kitchenware": 30,
        "Apparel": 40,
        "Beauty/Personal Care": 25,
        "Toys/Games": 35,
        "Sports/Outdoors": 40,
        "Books": 100,
    }

    # Build helper lookup from input
    asin_to_input = {}
    for r in product_rows:
        asin = r.get("ASIN", "").strip()
        asin_to_input[asin] = r

    # Velocity report checks
    velocity_path = os.path.join(output_dir, "velocity_report.csv")
    if os.path.isfile(velocity_path):
        checks["velocity_report_exists"] = True
        with open(velocity_path, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        if rows:
            header = rows[0]
            expected_header = ["ASIN", "product_name", "category", "monthly_orders", "last_30d_reviews", "expected_orders_per_review", "actual_orders_per_review", "status"]
            if header == expected_header:
                checks["velocity_report_headers"] = True

            # Parse dicts for content validation
            dict_reader = csv.DictReader(open(velocity_path, newline='', encoding='utf-8'))
            vrows = list(dict_reader)

            # Validate expected_orders_per_review and actual_orders_per_review and status
            expected_ok = True
            actual_ok = True
            status_ok = True
            for vr in vrows:
                asin = vr.get("ASIN", "").strip()
                category = normalize_category(vr.get("category", ""))
                # Determine expected from category mapping (normalize keys)
                exp = None
                if category in expected_map:
                    exp = expected_map[category]
                else:
                    # try to normalize further for common variants with spaces around slash
                    cand = category.replace(" / ", "/")
                    if cand in expected_map:
                        exp = expected_map[cand]
                try:
                    reported_expected = float(vr.get("expected_orders_per_review", ""))
                except Exception:
                    expected_ok = False
                    reported_expected = None
                if exp is None or reported_expected != float(exp):
                    expected_ok = False

                # actual computation: monthly_orders / last_30d_reviews, Infinity if zero
                mo_str = vr.get("monthly_orders", "").strip()
                lr_str = vr.get("last_30d_reviews", "").strip()
                try:
                    mo = float(mo_str)
                    # some agents may include commas; attempt cleanup
                except Exception:
                    try:
                        mo = float(mo_str.replace(",", ""))
                    except Exception:
                        actual_ok = False
                        mo = None
                try:
                    lr = float(lr_str)
                except Exception:
                    try:
                        lr = float(lr_str.replace(",", ""))
                    except Exception:
                        actual_ok = False
                        lr = None

                reported_actual = vr.get("actual_orders_per_review", "").strip()
                if lr is not None and mo is not None:
                    if lr == 0:
                        if reported_actual != "Infinity":
                            actual_ok = False
                    else:
                        # parse reported as float
                        try:
                            reported_actual_f = float(reported_actual)
                            expected_actual = mo / lr
                            # tolerance
                            if not (abs(reported_actual_f - expected_actual) <= 1e-6):
                                actual_ok = False
                        except Exception:
                            actual_ok = False

                # status check
                reported_status = vr.get("status", "").strip()
                expected_status = None
                if (lr is not None and mo is not None and exp is not None):
                    if lr == 0:
                        expected_status = "underperforming"
                    else:
                        calc_actual = mo / lr
                        if calc_actual > exp:
                            expected_status = "underperforming"
                        else:
                            expected_status = "on_benchmark_or_better"
                if expected_status is None or reported_status != expected_status:
                    status_ok = False

            checks["velocity_rows_expected_orders_correct"] = expected_ok and checks["velocity_report_headers"]
            checks["velocity_rows_actual_orders_correct"] = actual_ok and checks["velocity_report_headers"]
            checks["velocity_rows_status_correct"] = status_ok and checks["velocity_report_headers"]

    # Priority queue checks
    pq_path = os.path.join(output_dir, "priority_queue.csv")
    if os.path.isfile(pq_path):
        checks["priority_queue_exists"] = True
        with open(pq_path, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        if rows:
            header = rows[0]
            expected_header = ["ASIN", "review_gap", "rank", "prioritize_repeat_buyers"]
            if header == expected_header:
                checks["priority_queue_headers"] = True

            dict_reader = csv.DictReader(open(pq_path, newline='', encoding='utf-8'))
            pq_rows = list(dict_reader)

            # Compute expected review_gap for each ASIN from input and velocity mapping
            expected_gaps = {}
            for asin, r in asin_to_input.items():
                cat = normalize_category(r.get("category", ""))
                exp = expected_map.get(cat, None)
                try:
                    mo = float(str(r.get("monthly_orders", "")).replace(",", ""))
                except Exception:
                    continue
                try:
                    lr = float(str(r.get("last_30d_reviews", "")).replace(",", ""))
                except Exception:
                    continue
                if exp is None:
                    continue
                expected_reviews_at_benchmark = mo / float(exp)
                review_gap = expected_reviews_at_benchmark - lr
                # Only include > 0
                if review_gap > 0:
                    expected_gaps[asin] = round(review_gap + 1e-12, 2)

            # Build actual mapping from pq
            actual_gaps = {}
            actual_asins_order = []
            only_positive = True
            sort_rank_ok = True
            prioritize_ok = True

            # Determine prioritize repeat buyers from buyer_segments.json
            def has_repeat(asin):
                entry = buyer_segments.get(asin)
                if entry is None:
                    return False
                # Accept keys like 'repeat', 'repeat_share', 'repeat_buyers'
                for k, v in (entry.items() if isinstance(entry, dict) else []):
                    if "repeat" in k.lower():
                        try:
                            val = float(v)
                        except Exception:
                            continue
                        if val > 0:
                            return True
                return False

            # Parse rows
            for i, row in enumerate(pq_rows, start=1):
                asin = row.get("ASIN", "").strip()
                actual_asins_order.append(asin)
                # review_gap should be float > 0
                rg_str = row.get("review_gap", "").strip()
                try:
                    rg = float(rg_str)
                except Exception:
                    only_positive = False
                    rg = None
                if rg is None or rg <= 0:
                    only_positive = False
                else:
                    actual_gaps[asin] = round(rg + 1e-12, 2)
                # rank must start 1 and follow order
                try:
                    rank_val = int(row.get("rank", "").strip())
                    if rank_val != i:
                        sort_rank_ok = False
                except Exception:
                    sort_rank_ok = False
                # prioritize_repeat_buyers yes/no based on buyer_segments
                prb = row.get("prioritize_repeat_buyers", "").strip().lower()
                expected_prb = "yes" if has_repeat(asin) else "no"
                if prb != expected_prb:
                    prioritize_ok = False

            # Check that included ASINs = expected set and review_gap values equal (rounded 2 decimals)
            set_match = set(actual_gaps.keys()) == set(expected_gaps.keys())
            values_match = all(actual_gaps.get(a) == expected_gaps.get(a) for a in expected_gaps.keys())
            # Check sorting by review_gap descending equals provided order by ranks
            # Build expected sorting
            sorted_expected = sorted(expected_gaps.items(), key=lambda kv: kv[1], reverse=True)
            expected_order = [asin for asin, _ in sorted_expected]
            order_match = (actual_asins_order == expected_order)

            checks["priority_queue_rows_only_positive_gaps"] = checks["priority_queue_headers"] and only_positive and set_match and values_match
            checks["priority_queue_sorted_and_ranked"] = checks["priority_queue_headers"] and sort_rank_ok and order_match
            checks["priority_queue_prioritize_repeat"] = checks["priority_queue_headers"] and prioritize_ok and set_match

    # Timing recommendations checks
    timing_path = os.path.join(output_dir, "timing_recommendations.csv")
    if os.path.isfile(timing_path):
        checks["timing_recommendations_exists"] = True
        with open(timing_path, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        if rows:
            header = rows[0]
            expected_header = ["ASIN", "category", "avg_delivery_days", "recommended_start_day", "recommended_end_day", "rationale"]
            if header == expected_header:
                checks["timing_recommendations_headers"] = True

            dict_reader = csv.DictReader(open(timing_path, newline='', encoding='utf-8'))
            trows = list(dict_reader)

            # Category windows
            windows = {
                "Electronics": (7, 10),
                "Apparel": (4, 6),
                "Kitchenware": (4, 7),
                "Beauty/Personal Care": (7, 10),
                "Toys/Games": (4, 7),
                "Sports/Outdoors": (4, 7),
                "Books": (4, 7),
            }

            in_window = True
            start_lt_end = True
            rationale_present = True
            for tr in trows:
                cat = normalize_category(tr.get("category", ""))
                win = windows.get(cat)
                try:
                    rs = int(str(tr.get("recommended_start_day", "")).strip())
                    re_ = int(str(tr.get("recommended_end_day", "")).strip())
                except Exception:
                    in_window = False
                    start_lt_end = False
                    continue
                if not (rs < re_):
                    start_lt_end = False
                if win is None or not (win[0] <= rs <= win[1]) or not (win[0] <= re_ <= win[1]):
                    in_window = False
                rationale = (tr.get("rationale", "") or "").strip()
                if rationale == "":
                    rationale_present = False

            checks["timing_recommendations_days_in_window"] = checks["timing_recommendations_headers"] and in_window
            checks["timing_recommendations_start_less_than_end"] = checks["timing_recommendations_headers"] and start_lt_end
            checks["timing_recommendations_rationale_present"] = checks["timing_recommendations_headers"] and rationale_present

    # Compliance report checks
    compliance_path = os.path.join(output_dir, "compliance_report.csv")
    prohibited_terms = [
        "5-star", "5 star", "positive review only", "if you're happy", "discount", "% off",
        "refund", "rebate", "gift card", "free", "incentive", "promotion",
        "update your review", "change your review", "remove your review", "coupon"
    ]
    if os.path.isfile(compliance_path):
        checks["compliance_report_exists"] = True
        with open(compliance_path, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        if rows:
            header = rows[0]
            expected_header = ["ASIN", "status", "issues"]
            if header == expected_header:
                checks["compliance_report_headers"] = True

            dict_reader = csv.DictReader(open(compliance_path, newline='', encoding='utf-8'))
            crows = list(dict_reader)
            # Coverage: ensure each ASIN from input has a row
            input_asins = set(asin_to_input.keys())
            report_asins = set([r.get("ASIN", "").strip() for r in crows])
            checks["compliance_report_rows_complete"] = checks["compliance_report_headers"] and (input_asins.issubset(report_asins))

            # Detection correctness
            det_ok = True
            for asin, row in asin_to_input.items():
                existing = (row.get("existing_message", "") or "")
                existing_lower = existing.lower()
                found = [term for term in prohibited_terms if term.lower() in existing_lower]
                # Find row in compliance report
                matches = [cr for cr in crows if cr.get("ASIN", "").strip() == asin]
                if not matches:
                    det_ok = False
                    continue
                cr = matches[0]
                status = (cr.get("status", "") or "").strip().lower()
                issues = (cr.get("issues", "") or "")
                # Split issues by semicolon and strip
                issue_terms = [s.strip().lower() for s in issues.split(";") if s.strip() != ""]
                if found:
                    if status != "fail":
                        det_ok = False
                    # Ensure all found are reported (at least)
                    for t in found:
                        if t.lower() not in issue_terms:
                            det_ok = False
                else:
                    if status != "pass":
                        det_ok = False
            checks["compliance_report_prohibited_detection_correct"] = checks["compliance_report_headers"] and det_ok

    # Risk flags checks
    risk_path = os.path.join(output_dir, "risk_flags.csv")
    if os.path.isfile(risk_path):
        checks["risk_flags_exists"] = True
        with open(risk_path, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        if rows:
            header = rows[0]
            expected_header = ["ASIN", "risk", "reason"]
            if header == expected_header:
                checks["risk_flags_headers"] = True

            dict_reader = csv.DictReader(open(risk_path, newline='', encoding='utf-8'))
            rrows = list(dict_reader)
            # Compute expected ASINs
            expected_flags = set()
            for asin, r in asin_to_input.items():
                try:
                    mo = float(str(r.get("monthly_orders", "")).replace(",", ""))
                    lr = float(str(r.get("last_30d_reviews", "")).replace(",", ""))
                except Exception:
                    continue
                if mo >= 100 and lr == 0:
                    expected_flags.add(asin)

            # Validate presence and correctness
            present_ok = True
            for asin in expected_flags:
                matches = [rr for rr in rrows if rr.get("ASIN", "").strip() == asin]
                if not matches:
                    present_ok = False
                    break
                rr = matches[0]
                if rr.get("risk", "").strip() != "suppression_suspected":
                    present_ok = False
                    break
                if rr.get("reason", "").strip() != "0 reviews in last 30 days after >=100 orders":
                    present_ok = False
                    break
            # Any rows present for ASINs not meeting condition should not be counted as failure per spec; we only ensure required ones are present and correctly labeled
            checks["risk_flags_rows_correct"] = checks["risk_flags_headers"] and present_ok

    # Templates checks
    # Collect underperforming ASINs from velocity_report
    underperforming_asins = []
    asin_to_product_name = {}
    if os.path.isfile(velocity_path) and checks["velocity_report_headers"]:
        dict_reader = csv.DictReader(open(velocity_path, newline='', encoding='utf-8'))
        for row in dict_reader:
            if (row.get("status", "") or "").strip() == "underperforming":
                asin = (row.get("ASIN", "") or "").strip()
                underperforming_asins.append(asin)
                asin_to_product_name[asin] = (row.get("product_name", "") or "")

    # Evaluate templates existence
    all_exist = True
    reqs_met = True
    prohibited_terms_lower = [t.lower() for t in prohibited_terms]
    for asin in underperforming_asins:
        t1 = os.path.join(output_dir, "templates", f"{asin}_template1.md")
        t2 = os.path.join(output_dir, "templates", f"{asin}_template2.md")
        if not (os.path.isfile(t1) and os.path.isfile(t2)):
            all_exist = False
            reqs_met = False
            continue
        for tpath in [t1, t2]:
            try:
                with open(tpath, encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                reqs_met = False
                continue
            # word count <= 150
            words = [w for w in re.split(r"\s+", content.strip()) if w]
            if len(words) > 150:
                reqs_met = False
            # include product name
            pname = asin_to_product_name.get(asin, "")
            if pname and (pname not in content):
                reqs_met = False
            # contains "honest feedback" or "honest review" case-insensitive
            cl = content.lower()
            if ("honest feedback" not in cl) and ("honest review" not in cl):
                reqs_met = False
            # no prohibited substrings
            for term in prohibited_terms_lower:
                if term in cl:
                    reqs_met = False
                    break
    # If there are no underperformers, treat existence and requirements as vacuously satisfied (nothing to check)
    if underperforming_asins:
        checks["templates_exist_for_underperformers"] = all_exist
        checks["templates_requirements_met"] = reqs_met and all_exist
    else:
        checks["templates_exist_for_underperformers"] = True
        checks["templates_requirements_met"] = True

    # Policy notes checks
    policy_notes_path = os.path.join(output_dir, "policy_notes.txt")
    if os.path.isfile(policy_notes_path):
        checks["policy_notes_exists"] = True
        try:
            with open(policy_notes_path, encoding='utf-8') as f:
                pn = f.read()
        except Exception:
            pn = ""
        # Must contain literal "one request per order"
        cond1 = "one request per order" in pn
        # Mention no incentives
        cond2 = ("no incentive" in pn.lower()) or ("no incentives" in pn.lower()) or ("incentive" in pn.lower())
        # Mention no positive-only language
        lower_pn = pn.lower()
        cond3 = ("positive-only" in lower_pn) or ("positive only" in lower_pn)
        # Mention avoiding opt-outs/returns
        cond4 = (("opt-out" in lower_pn) or ("opt out" in lower_pn)) and (("return" in lower_pn) or ("returns" in lower_pn))
        checks["policy_notes_contains_required_phrases"] = cond1 and cond2 and cond3 and cond4

    # Compute reward
    # No-op baseline: if output dir missing or empty of required artifacts, reward must be exactly 0.0
    required_files_any = any([
        checks["velocity_report_exists"],
        checks["priority_queue_exists"],
        checks["timing_recommendations_exists"],
        checks["compliance_report_exists"],
        checks["risk_flags_exists"],
        checks["policy_notes_exists"],
        # templates are folders/files; rely on above
    ])
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0
    if not required_files_any:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()