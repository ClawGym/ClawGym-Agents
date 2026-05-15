import json
import os
import sys
import csv
import re

def read_json(path):
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
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def parse_csv(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = [h for h in reader.fieldnames] if reader.fieldnames else []
            return headers, rows
    except Exception:
        return None, None

def safe_int(v):
    try:
        if isinstance(v, bool):
            return int(v)
        return int(str(v).strip())
    except Exception:
        return None

def collect_numeric_from_json(data):
    # Collect simple numeric values for possible metrics
    nums = []
    if isinstance(data, dict):
        for k, v in data.items():
            nums.extend(collect_numeric_from_json(v))
    elif isinstance(data, list):
        for v in data:
            nums.extend(collect_numeric_from_json(v))
    else:
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            nums.append(data)
        else:
            # sometimes numeric-like string
            if isinstance(data, str):
                try:
                    if data.strip().isdigit():
                        nums.append(int(data.strip()))
                except Exception:
                    pass
    return nums

def extract_company_metrics(profile):
    # Returns set of candidate substrings that indicate numeric traction metrics
    candidates = set()
    if not isinstance(profile, dict):
        return candidates

    # Helper to walk dict and get values by key pattern
    def find_by_key_patterns(d, patterns):
        values = []
        if isinstance(d, dict):
            for k, v in d.items():
                if any(p in k.lower() for p in patterns):
                    values.append(v)
                values.extend(find_by_key_patterns(v, patterns))
        elif isinstance(d, list):
            for item in d:
                values.extend(find_by_key_patterns(item, patterns))
        return values

    # Customer count
    customer_vals = find_by_key_patterns(profile, ["customer", "user", "client"])
    # If value is list, use length
    for val in customer_vals:
        if isinstance(val, list):
            count = len(val)
            if count > 0:
                candidates.add(str(count))
        elif isinstance(val, (int, float)) and val > 0:
            candidates.add(str(int(val)))
        elif isinstance(val, str):
            # try to parse integer
            m = re.search(r"\b(\d{1,6})\b", val)
            if m:
                candidates.add(m.group(1))

    # Growth percent
    growth_vals = find_by_key_patterns(profile, ["growth", "growth_percent", "mom", "yoy"])
    for val in growth_vals:
        if isinstance(val, (int, float)):
            g = int(round(val))
            if g != 0:
                candidates.add(f"{g}%")
        elif isinstance(val, str):
            # If contains %, keep as-is; else extract number and add %
            if "%" in val:
                # normalize spacing, keep as candidate
                # Extract patterns like 18%
                for m in re.findall(r"\b\d{1,3}%\b", val):
                    candidates.add(m)
            else:
                m = re.search(r"\b(\d{1,3})\b", val)
                if m:
                    candidates.add(f"{m.group(1)}%")

    # MRR (Monthly Recurring Revenue)
    mrr_vals = find_by_key_patterns(profile, ["mrr"])
    # Also consider ARR if MRR not found (divide or accept as is). We'll accept ARR as large number too.
    arr_vals = find_by_key_patterns(profile, ["arr"])
    revenue_vals = find_by_key_patterns(profile, ["revenue"])
    def add_mrr_like(v):
        try:
            if isinstance(v, (int, float)):
                amt = int(round(v))
                if amt > 0:
                    # plain integer
                    candidates.add(str(amt))
                    # formatted with commas
                    candidates.add(f"{amt:,}")
                    # shorthand k forms (rounded to nearest k)
                    k = amt / 1000.0
                    if k.is_integer():
                        k_int = int(k)
                        candidates.add(f"{k_int}k")
                        candidates.add(f"${k_int}k")
                    else:
                        # keep 1 decimal place if needed
                        candidates.add(f"{k:.1f}k".rstrip("0").rstrip(".") + "k" if not f"{k:.1f}".endswith(".0") else f"{int(k)}k")
                        # For simplicity, also add $ version without decimals
                        # but stick with lower-case k
            elif isinstance(v, str):
                # Try to parse integers within string
                s = v.replace(",", "")
                m = re.search(r"\b(\d{2,7})\b", s)
                if m:
                    amt = int(m.group(1))
                    if amt > 0:
                        candidates.add(str(amt))
                        candidates.add(f"{amt:,}")
                        k = amt / 1000.0
                        if k.is_integer():
                            k_int = int(k)
                            candidates.add(f"{k_int}k")
                            candidates.add(f"${k_int}k")
        except Exception:
            pass

    for v in mrr_vals:
        add_mrr_like(v)

    # If no MRR found, try revenue values too
    if not any(True for _ in mrr_vals):
        for v in revenue_vals:
            add_mrr_like(v)

    # As fallback include any numeric found in the JSON (but limit to reasonable sizes to avoid years)
    if not candidates:
        all_nums = collect_numeric_from_json(profile)
        for n in all_nums:
            if isinstance(n, (int, float)):
                ni = int(round(n))
                # Filter likely traction numbers: 2-7 digits, exclude common years > 1900 if too high
                if 2 <= len(str(abs(ni))) <= 7 and not (1900 <= ni <= 2100):
                    candidates.add(str(ni))
                    candidates.add(f"{ni:,}")
                    k = ni / 1000.0
                    if k.is_integer():
                        k_int = int(k)
                        candidates.add(f"{k_int}k")
                        candidates.add(f"${k_int}k")

    # Ensure both lowercase/uppercase forms for k variants
    extra = set()
    for c in list(candidates):
        if isinstance(c, str) and c.endswith("k"):
            extra.add(c.upper())
        if isinstance(c, str) and c.endswith("K"):
            extra.add(c.lower())
    candidates |= extra

    return candidates

def extract_event_name(event_details):
    if not isinstance(event_details, dict):
        return None
    preferred_keys = ["event_name", "name", "title", "conference", "event", "eventTitle"]
    for k in preferred_keys:
        if k in event_details and isinstance(event_details[k], str) and event_details[k].strip():
            return event_details[k].strip()
    # Try recursive search
    def find_str(d):
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, str) and v.strip() and any(kw in k.lower() for kw in ["name", "title", "event", "conference"]):
                    return v.strip()
                res = find_str(v)
                if res:
                    return res
        elif isinstance(d, list):
            for item in d:
                res = find_str(item)
                if res:
                    return res
        return None
    return find_str(event_details)

def parse_targets_counts(targets_csv_path):
    headers, rows = parse_csv(targets_csv_path)
    if rows is None:
        return None
    # Map columns case-insensitively
    def get_col(row, name):
        for k, v in row.items():
            if k is None:
                continue
            if k.strip().lower() == name:
                return v
        return None
    counts = {1: 0, 2: 0, 3: 0}
    tier_investor_count = 0
    tier1_investor_names = []
    for r in rows:
        tier_val = get_col(r, "tier")
        type_val = get_col(r, "type")
        name_val = get_col(r, "name") or ""
        tier = None
        try:
            tier = int(str(tier_val).strip())
        except Exception:
            continue
        if tier in counts:
            counts[tier] += 1
        if type_val is not None and str(type_val).strip().lower() == "investor" and tier == 1:
            tier_investor_count += 1
            tier1_investor_names.append(name_val)
    return counts, tier_investor_count, tier1_investor_names

def word_count(s):
    if not isinstance(s, str):
        return 1e9
    return len(re.findall(r"\S+", s))

def line_has_exact(lines, target):
    for ln in lines:
        if ln.strip() == target:
            return True
    return False

def parse_jsonl_lines(path):
    lines = read_lines(path)
    if lines is None:
        return None
    out = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
            out.append(obj)
        except Exception:
            return None
    return out

def get_required_columns(header, required):
    if not header:
        return False
    header_map = {h.strip(): idx for idx, h in enumerate(header)}
    return all(col in header_map for col in required)

def compute_lead_score(entry):
    # entry is dict from lead_signals.jsonl
    def get_bool(key):
        v = entry.get(key, False)
        return bool(v)
    def get_int(key):
        try:
            return int(entry.get(key, 0))
        except Exception:
            try:
                return int(float(entry.get(key, 0)))
            except Exception:
                return 0
    reasons = []
    hot = get_bool("asked_pricing") or get_bool("requested_demo") or get_bool("expressed_intent")
    if hot:
        if get_bool("asked_pricing"): reasons.append("asked_pricing")
        if get_bool("requested_demo"): reasons.append("requested_demo")
        if get_bool("expressed_intent"): reasons.append("expressed_intent")
        return "HOT", " + ".join(reasons) if reasons else "intent signal"
    warm = get_bool("icp_fit") and get_int("spoke_minutes") >= 10
    if warm:
        reasons = []
        if get_bool("icp_fit"): reasons.append("icp_fit")
        reasons.append(f"spoke_minutes={get_int('spoke_minutes')}")
        return "WARM", " + ".join(reasons)
    return "COLD", "no high-intent signals"

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Load inputs
    company_profile = read_json(os.path.join(input_dir, "company_profile.json"))
    event_details = read_json(os.path.join(input_dir, "event_details.json"))
    targets_csv_path = os.path.join(input_dir, "targets.csv")
    lead_signals_path = os.path.join(input_dir, "lead_signals.jsonl")
    budget_json = read_json(os.path.join(input_dir, "budget.json"))

    # Precompute
    event_name = extract_event_name(event_details) if event_details else None
    tier_counts_info = parse_targets_counts(targets_csv_path) if os.path.isfile(targets_csv_path) else None
    metrics_candidates = extract_company_metrics(company_profile) if company_profile else set()

    # 1) meeting_strategy.md
    ms_path = os.path.join(output_dir, "meeting_strategy.md")
    ms_exists = os.path.isfile(ms_path)
    checks["meeting_strategy_exists"] = bool(ms_exists)
    checks["meeting_strategy_has_week1"] = False
    checks["meeting_strategy_has_week2"] = False
    checks["meeting_strategy_has_week3"] = False
    checks["meeting_strategy_has_max_meetings_phrase"] = False
    checks["meeting_strategy_has_tier_summary_line"] = False
    checks["meeting_strategy_tier_counts_match"] = False

    if ms_exists:
        ms_text = read_text(ms_path) or ""
        ms_lines = ms_text.splitlines()
        checks["meeting_strategy_has_week1"] = "Week 1" in ms_text
        checks["meeting_strategy_has_week2"] = "Week 2" in ms_text
        checks["meeting_strategy_has_week3"] = "Week 3" in ms_text
        checks["meeting_strategy_has_max_meetings_phrase"] = "Max 4-6 quality meetings per day" in ms_text

        # Find Tier Summary line
        tier_line = None
        for ln in ms_lines:
            if re.match(r"^Tier Summary: Tier 1=\d+, Tier 2=\d+, Tier 3=\d+$", ln.strip()):
                tier_line = ln.strip()
                break
        checks["meeting_strategy_has_tier_summary_line"] = tier_line is not None

        if tier_line and tier_counts_info is not None:
            m = re.match(r"^Tier Summary: Tier 1=(\d+), Tier 2=(\d+), Tier 3=(\d+)$", tier_line)
            if m:
                x, y, z = int(m.group(1)), int(m.group(2)), int(m.group(3))
                counts, _, _ = tier_counts_info
                checks["meeting_strategy_tier_counts_match"] = (x == counts.get(1, 0) and y == counts.get(2, 0) and z == counts.get(3, 0))

    # 2) pre_event_outreach.jsonl
    outreach_path = os.path.join(output_dir, "pre_event_outreach.jsonl")
    outreach_exists = os.path.isfile(outreach_path)
    checks["outreach_exists"] = bool(outreach_exists)
    checks["outreach_count_matches"] = False
    checks["outreach_all_lines_valid_json"] = False
    checks["outreach_subject_contains_event_all"] = False
    checks["outreach_body_word_limit_all"] = False
    checks["outreach_body_has_calendar_link_all"] = False
    checks["outreach_body_has_traction_all"] = False

    if outreach_exists and tier_counts_info is not None:
        _, expected_n, _names = tier_counts_info
        # Load JSONL
        try:
            with open(outreach_path, "r", encoding="utf-8") as f:
                raw_lines = [ln for ln in f.read().splitlines() if ln.strip() != ""]
        except Exception:
            raw_lines = None

        if raw_lines is not None:
            checks["outreach_count_matches"] = (len(raw_lines) == expected_n)

            # Validate each line
            all_json = True
            all_subject_has_event = True
            all_body_word_limit = True
            all_body_calendar = True
            all_body_traction = True

            if expected_n == 0:
                # If no Tier 1 investors, expect an empty file (0 lines)
                all_json = True
                all_subject_has_event = True
                all_body_word_limit = True
                all_body_calendar = True
                all_body_traction = True
            else:
                event_name_valid = isinstance(event_name, str) and len(event_name) > 0
                for ln in raw_lines:
                    try:
                        obj = json.loads(ln)
                    except Exception:
                        all_json = False
                        break
                    # keys exist and are strings
                    required_keys = ["name", "email", "subject", "body"]
                    if not all(k in obj and isinstance(obj[k], str) for k in required_keys):
                        all_json = False
                        break
                    subj = obj["subject"]
                    body = obj["body"]
                    # subject contains event name
                    if not (event_name_valid and (event_name in subj)):
                        all_subject_has_event = False
                    # body <= 200 words
                    if word_count(body) > 200:
                        all_body_word_limit = False
                    # body contains literal [calendar link]
                    if "[calendar link]" not in body:
                        all_body_calendar = False
                    # body includes at least one numeric traction metric from company_profile.json
                    if metrics_candidates:
                        present = False
                        for cand in metrics_candidates:
                            if isinstance(cand, str) and cand.lower() in body.lower():
                                present = True
                                break
                        if not present:
                            all_body_traction = False
                    else:
                        # If no metrics available from input, cannot pass
                        all_body_traction = False

            checks["outreach_all_lines_valid_json"] = all_json
            checks["outreach_subject_contains_event_all"] = all_subject_has_event
            checks["outreach_body_word_limit_all"] = all_body_word_limit
            checks["outreach_body_has_calendar_link_all"] = all_body_calendar
            checks["outreach_body_has_traction_all"] = all_body_traction

    # 3) pitches.md
    pitches_path = os.path.join(output_dir, "pitches.md")
    pitches_exists = os.path.isfile(pitches_path)
    checks["pitches_exists"] = bool(pitches_exists)
    checks["pitches_has_60_header"] = False
    checks["pitches_has_required_labels"] = False
    checks["pitches_traction_line_has_digit"] = False
    checks["pitches_has_3min"] = False
    checks["pitches_has_10min"] = False

    if pitches_exists:
        ptxt = read_text(pitches_path) or ""
        plines = ptxt.splitlines()
        checks["pitches_has_60_header"] = ("60-Second Pitch" in ptxt)
        # Labels lines starting with exact labels
        labels = {"Hook:", "Problem:", "Solution:", "Traction:", "Ask:"}
        found_labels = set()
        for ln in plines:
            for lab in labels:
                if ln.strip().startswith(lab):
                    found_labels.add(lab)
        checks["pitches_has_required_labels"] = (found_labels == labels)
        # Traction line or immediate following line contains at least one digit
        traction_ok = False
        for idx, ln in enumerate(plines):
            if ln.strip().startswith("Traction:"):
                if re.search(r"\d", ln):
                    traction_ok = True
                    break
                if idx + 1 < len(plines) and re.search(r"\d", plines[idx + 1]):
                    traction_ok = True
                    break
        checks["pitches_traction_line_has_digit"] = traction_ok
        checks["pitches_has_3min"] = ("3-Minute Pitch" in ptxt)
        checks["pitches_has_10min"] = ("10-Minute Pitch" in ptxt)

    # 4) followup_rules.md
    followup_path = os.path.join(output_dir, "followup_rules.md")
    followup_exists = os.path.isfile(followup_path)
    checks["followup_rules_exists"] = bool(followup_exists)
    checks["followup_rules_hot_line"] = False
    checks["followup_rules_warm_line"] = False
    checks["followup_rules_cold_line"] = False
    if followup_exists:
        flines = read_lines(followup_path) or []
        checks["followup_rules_hot_line"] = line_has_exact(flines, "HOT: within 0-24 hours")
        checks["followup_rules_warm_line"] = line_has_exact(flines, "WARM: within 24-48 hours")
        checks["followup_rules_cold_line"] = line_has_exact(flines, "COLD: within 48-72 hours")

    # 5) lead_scoring.csv
    lead_csv_path = os.path.join(output_dir, "lead_scoring.csv")
    lead_csv_exists = os.path.isfile(lead_csv_path)
    checks["lead_scoring_exists"] = bool(lead_csv_exists)
    checks["lead_scoring_has_header"] = False
    checks["lead_scoring_row_count_matches"] = False
    checks["lead_scoring_scores_match"] = False
    checks["lead_scoring_rationale_nonempty"] = False

    if lead_csv_exists and os.path.isfile(lead_signals_path):
        header, rows = parse_csv(lead_csv_path)
        lead_lines = read_lines(lead_signals_path) or []
        # filter jsonl non-empty valid json lines
        input_entries = []
        for ln in lead_lines:
            if not ln.strip():
                continue
            try:
                input_entries.append(json.loads(ln))
            except Exception:
                # invalid input jsonl - then the dependent checks cannot pass
                input_entries = None
                break

        if header and rows is not None:
            checks["lead_scoring_has_header"] = get_required_columns(header, ["name", "org", "type", "score", "rationale"])
            if input_entries is not None:
                checks["lead_scoring_row_count_matches"] = (len(rows) == len(input_entries))

                # Build mapping by name to row (assume 1:1)
                by_name = {}
                all_rationale_nonempty = True
                for r in rows:
                    nm = r.get("name", "")
                    by_name[nm] = r
                    # check rationale
                    rationale = r.get("rationale", "")
                    if not isinstance(rationale, str) or len(rationale.strip()) == 0:
                        all_rationale_nonempty = False
                checks["lead_scoring_rationale_nonempty"] = all_rationale_nonempty

                all_scores_match = True
                if input_entries is not None:
                    for e in input_entries:
                        nm = e.get("name", "")
                        expected_score, _reason = compute_lead_score(e)
                        row = by_name.get(nm)
                        if row is None:
                            all_scores_match = False
                            break
                        score_val = (row.get("score") or "").strip().upper()
                        if score_val != expected_score:
                            all_scores_match = False
                            break
                checks["lead_scoring_scores_match"] = all_scores_match

    # 6) roi.json
    roi_path = os.path.join(output_dir, "roi.json")
    roi_exists = os.path.isfile(roi_path)
    checks["roi_exists"] = bool(roi_exists)
    checks["roi_has_numeric"] = False
    checks["roi_value_matches"] = False
    if roi_exists and isinstance(budget_json, dict):
        roi_out = read_json(roi_path)
        rev = budget_json.get("revenue_from_event_leads_usd")
        cost = budget_json.get("total_cost_usd")
        try:
            rev_val = float(rev)
            cost_val = float(cost)
            if cost_val != 0:
                expected_roi = ((rev_val - cost_val) / cost_val) * 100.0
            else:
                expected_roi = 0.0
        except Exception:
            expected_roi = None

        if isinstance(roi_out, dict) and "roi_percent" in roi_out:
            try:
                roi_num = float(roi_out["roi_percent"])
                checks["roi_has_numeric"] = True
                if expected_roi is not None:
                    checks["roi_value_matches"] = (abs(roi_num - expected_roi) <= 0.5)
            except Exception:
                checks["roi_has_numeric"] = False

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline: if no outputs at all, reward 0.0
    if not os.path.isdir(output_dir) or len([name for name in os.listdir(output_dir)]) == 0:
        reward = 0.0

    # Bound reward
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()