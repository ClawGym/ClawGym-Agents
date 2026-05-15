import json
import os
import sys
import csv
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_csv_dicts(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            for r in reader:
                rows.append(r)
        return header, rows
    except Exception:
        return None, None

def lower_set(iterable):
    return set([str(x).strip().lower() for x in iterable])

def contains_casefold(haystack, needle):
    if haystack is None:
        return False
    return needle.lower() in haystack.lower()

def find_section(content, section_phrase, next_section_phrases):
    # Return substring from first occurrence of section_phrase to next occurrence of any of next_section_phrases
    if content is None:
        return ""
    lc = content.lower()
    start = lc.find(section_phrase.lower())
    if start == -1:
        return ""
    end_candidates = []
    for p in next_section_phrases:
        idx = lc.find(p.lower(), start + 1)
        if idx != -1:
            end_candidates.append(idx)
    end = min(end_candidates) if end_candidates else len(content)
    return content[start:end]

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Initialize all checks to False
checks = {}

# Load inputs
campaigns_csv_path = os.path.join(input_dir, "campaigns.csv")
policies_yaml_path = os.path.join(input_dir, "policies.yaml")
in_header, in_rows = read_csv_dicts(campaigns_csv_path)
policies_text = read_text(policies_yaml_path)

# Determine if "missed balance" appears in policies
policies_has_missed_balance = False
if policies_text is not None:
    policies_has_missed_balance = "missed balance" in policies_text.lower()

# Prepare input campaigns data
input_campaigns_by_name = {}
input_campaign_names = set()
input_payment_models = set()
required_campaign_cols = [
    "campaign_name","product","payment_model","deposit_percent","price",
    "preorder_open","preorder_close","production_start","production_end",
    "est_ship_window_start","est_ship_window_end"
]
inputs_ok = False
if in_header is not None and in_rows is not None:
    # verify required columns exist in input
    if all(col in in_header for col in required_campaign_cols):
        for r in in_rows:
            name = r.get("campaign_name", "")
            if name:
                input_campaigns_by_name[name] = r
                input_campaign_names.add(name)
                pm = r.get("payment_model", "")
                if pm:
                    input_payment_models.add(pm.strip().lower())
        inputs_ok = True

# 1) summary.json checks
summary_path = os.path.join(output_dir, "summary.json")
checks["summary_exists"] = os.path.isfile(summary_path)
summary_data = None
if checks["summary_exists"]:
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            summary_data = json.load(f)
        checks["summary_valid_json"] = isinstance(summary_data, dict)
    except Exception:
        checks["summary_valid_json"] = False
else:
    checks["summary_valid_json"] = False

# Default summary checks
checks["summary_has_keys"] = False
checks["summary_campaigns_len_match"] = False
checks["summary_campaigns_have_fields"] = False
checks["summary_campaign_names_match"] = False
checks["summary_comm_cadence_has_required"] = False
checks["summary_current_gap_mentions_missed_balance_if_required"] = False
checks["summary_next_steps_len_ok"] = False
checks["summary_deposit_and_price_numbers"] = False

if checks["summary_valid_json"]:
    # Required keys
    has_current_gap = isinstance(summary_data.get("current_gap"), str)
    has_campaigns = isinstance(summary_data.get("campaigns"), list)
    has_comm = isinstance(summary_data.get("communication_cadence"), list)
    has_next_steps = isinstance(summary_data.get("next_steps"), list)
    checks["summary_has_keys"] = all([has_current_gap, has_campaigns, has_comm, has_next_steps])

    # campaigns length match
    if inputs_ok and has_campaigns:
        checks["summary_campaigns_len_match"] = (len(summary_data["campaigns"]) == len(input_campaign_names))
    # campaigns have required fields and types for numeric
    required_summary_fields = [
        "campaign_name","product","payment_model","deposit_percent","price",
        "est_ship_window_start","est_ship_window_end"
    ]
    campaigns_have_fields = True
    num_types_ok = True
    names_in_summary = set()
    if has_campaigns:
        for c in summary_data["campaigns"]:
            if not isinstance(c, dict):
                campaigns_have_fields = False
                num_types_ok = False
                break
            if not all(k in c for k in required_summary_fields):
                campaigns_have_fields = False
            # numeric type checks
            dep = c.get("deposit_percent")
            pr = c.get("price")
            if not (isinstance(dep, (int, float)) and isinstance(pr, (int, float))):
                num_types_ok = False
            name = c.get("campaign_name")
            if isinstance(name, str):
                names_in_summary.add(name)
    checks["summary_campaigns_have_fields"] = campaigns_have_fields and has_campaigns
    checks["summary_deposit_and_price_numbers"] = num_types_ok and has_campaigns

    # campaign names match set
    if inputs_ok and has_campaigns:
        checks["summary_campaign_names_match"] = (names_in_summary == input_campaign_names)

    # communication cadence contains required phrases
    required_comm_phrases = [
        "order confirmation", "progress update", "balance due reminder", "delay notice", "ship notification"
    ]
    comm_ok = False
    if has_comm:
        lower_items = [str(x).lower() for x in summary_data["communication_cadence"]]
        comm_ok = all(any(req in item for item in lower_items) for req in required_comm_phrases)
    checks["summary_comm_cadence_has_required"] = comm_ok

    # current_gap mentions "missed balance" if required
    cur_gap_ok = True
    if policies_has_missed_balance:
        cur_gap_ok = isinstance(summary_data.get("current_gap"), str) and ("missed balance" in summary_data.get("current_gap","").lower())
    checks["summary_current_gap_mentions_missed_balance_if_required"] = cur_gap_ok

    # next_steps length >= 3
    checks["summary_next_steps_len_ok"] = has_next_steps and (len(summary_data["next_steps"]) >= 3)

# 2) deposit_flow.csv checks
deposit_flow_path = os.path.join(output_dir, "deposit_flow.csv")
checks["deposit_flow_exists"] = os.path.isfile(deposit_flow_path)
checks["deposit_flow_header_ok"] = False
checks["deposit_flow_covers_payment_models"] = False
checks["deposit_flow_deposit_balance_steps_ok"] = True  # default True when not applicable
checks["deposit_flow_full_upfront_steps_ok"] = True     # default True when not applicable

df_header = None
df_rows = []
if checks["deposit_flow_exists"]:
    try:
        with open(deposit_flow_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            df_header = reader.fieldnames
            if df_header is not None:
                checks["deposit_flow_header_ok"] = (df_header == ["payment_model","Step","When","What happens"])
            for r in reader:
                df_rows.append(r)
    except Exception:
        pass

if df_rows and inputs_ok:
    # Covers payment models present in input
    df_pms = set([str(r.get("payment_model","")).strip().lower() for r in df_rows])
    covers_all = all(pm in df_pms for pm in input_payment_models) if input_payment_models else False
    checks["deposit_flow_covers_payment_models"] = covers_all

    # deposit+balance steps
    if "deposit+balance" in input_payment_models:
        steps = [str(r.get("Step","")).strip().lower() for r in df_rows if str(r.get("payment_model","")).strip().lower() == "deposit+balance"]
        need = {"deposit collected","balance reminder","balance collected","refund window"}
        checks["deposit_flow_deposit_balance_steps_ok"] = all(any(need_step == s for s in steps) for need_step in need)

    # full-upfront steps
    if "full-upfront" in input_payment_models:
        steps_full = [str(r.get("Step","")).strip().lower() for r in df_rows if str(r.get("payment_model","")).strip().lower() == "full-upfront"]
        has_payment_collected = any(s == "payment collected" for s in steps_full)
        has_track_to_ship = any(("track" in s and "ship" in s) for s in steps_full)
        checks["deposit_flow_full_upfront_steps_ok"] = has_payment_collected and has_track_to_ship

# 3) timeline_dashboard.csv checks
timeline_path = os.path.join(output_dir, "timeline_dashboard.csv")
checks["timeline_exists"] = os.path.isfile(timeline_path)
checks["timeline_header_ok"] = False
checks["timeline_rows_count_match"] = False
checks["timeline_values_match_input"] = False

td_header = None
td_rows = []
if checks["timeline_exists"]:
    try:
        with open(timeline_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            td_header = reader.fieldnames
            expected_header = [
                "campaign_name","product","payment_model","deposit_percent","price",
                "preorder_open","preorder_close","production_start","production_end",
                "est_ship_window_start","est_ship_window_end"
            ]
            checks["timeline_header_ok"] = (td_header == expected_header)
            for r in reader:
                td_rows.append(r)
    except Exception:
        pass

if inputs_ok and td_rows:
    checks["timeline_rows_count_match"] = (len(td_rows) == len(input_campaign_names))
    # Ensure exactly one row per campaign and values match
    td_by_name = {}
    for r in td_rows:
        n = r.get("campaign_name","")
        if n:
            td_by_name.setdefault(n, []).append(r)
    names_match = (set(td_by_name.keys()) == input_campaign_names) and all(len(v)==1 for v in td_by_name.values())
    values_match = True
    if names_match:
        for name in input_campaign_names:
            in_row = input_campaigns_by_name.get(name, {})
            out_row = td_by_name[name][0]
            for col in required_campaign_cols:
                if (out_row.get(col, "") != in_row.get(col, "")):
                    values_match = False
                    break
            if not values_match:
                break
    else:
        values_match = False
    checks["timeline_values_match_input"] = values_match

# 4) communication_templates.md checks
templates_path = os.path.join(output_dir, "communication_templates.md")
checks["templates_exists"] = os.path.isfile(templates_path)
checks["templates_has_headings"] = False
checks["templates_has_placeholders"] = False
checks["templates_has_link"] = False
checks["templates_delay_section_placeholders"] = False

templates_text = None
if checks["templates_exists"]:
    templates_text = read_text(templates_path)

if templates_text is not None:
    lc = templates_text.lower()
    required_headings = ["order confirmation","progress update","balance due reminder","delay notice","ship notification"]
    checks["templates_has_headings"] = all(phrase in lc for phrase in required_headings)
    checks["templates_has_placeholders"] = ("[product]" in templates_text) and ("[date]" in templates_text)
    checks["templates_has_link"] = ("[link]" in templates_text)

    # Delay section placeholders [new date] and [reason]
    next_phrases = ["order confirmation","progress update","balance due reminder","ship notification"]
    delay_section = find_section(templates_text, "delay notice", next_phrases)
    ds_lc = delay_section.lower()
    checks["templates_delay_section_placeholders"] = ("[new date]" in ds_lc and "[reason]" in ds_lc)

# 5) exception_rules.md checks
exception_path = os.path.join(output_dir, "exception_rules.md")
checks["exceptions_exists"] = os.path.isfile(exception_path)
checks["exceptions_has_required_phrases"] = False

exc_text = None
if checks["exceptions_exists"]:
    exc_text = read_text(exception_path)

if exc_text is not None:
    lc = exc_text.lower()
    def has_variant(phrase_hyphen, phrase_space):
        return (phrase_hyphen in lc) or (phrase_space in lc)
    has_prod_delay = "production delay" in lc
    has_48h = "48 hours" in lc
    has_unpaid = "unpaid balance" in lc
    has_7day = has_variant("7-day", "7 day")
    has_autocancel = has_variant("auto-cancel", "auto cancel")
    has_buyer_cancel = "buyer cancellation" in lc
    has_over_demand = has_variant("over-demand", "over demand")
    has_refund = "refund" in lc
    checks["exceptions_has_required_phrases"] = all([
        has_prod_delay, has_48h, has_unpaid, has_7day, has_autocancel, has_buyer_cancel, has_over_demand, has_refund
    ])

# 6) metrics_plan.md checks
metrics_path = os.path.join(output_dir, "metrics_plan.md")
checks["metrics_exists"] = os.path.isfile(metrics_path)
checks["metrics_has_required_phrases"] = False

met_text = None
if checks["metrics_exists"]:
    met_text = read_text(metrics_path)

if met_text is not None:
    lc = met_text.lower()
    req_metrics = [
        "pre-order conversion rate",
        "balance collection rate",
        "cancellation rate",
        "average days from pre-order to ship",
        "support tickets per campaign"
    ]
    checks["metrics_has_required_phrases"] = all(req in lc for req in req_metrics)

# Group scoring
def group_score(flags):
    if not flags:
        return 0.0
    total = len(flags)
    passed = sum(1 for f in flags if f)
    return passed / total

# Summary group
summary_flags = [
    checks.get("summary_exists", False),
    checks.get("summary_valid_json", False),
    checks.get("summary_has_keys", False),
    checks.get("summary_campaigns_len_match", False),
    checks.get("summary_campaigns_have_fields", False),
    checks.get("summary_campaign_names_match", False),
    checks.get("summary_comm_cadence_has_required", False),
    checks.get("summary_current_gap_mentions_missed_balance_if_required", False),
    checks.get("summary_next_steps_len_ok", False),
    checks.get("summary_deposit_and_price_numbers", False),
]
summary_score = group_score(summary_flags)

# Deposit flow group: consider conditional checks only if applicable
df_flags = [checks.get("deposit_flow_exists", False), checks.get("deposit_flow_header_ok", False)]
# coverage only meaningful if inputs_ok
if inputs_ok:
    df_flags.append(checks.get("deposit_flow_covers_payment_models", False))
    # deposit+balance applicable?
    if "deposit+balance" in input_payment_models:
        df_flags.append(checks.get("deposit_flow_deposit_balance_steps_ok", False))
    # full-upfront applicable?
    if "full-upfront" in input_payment_models:
        df_flags.append(checks.get("deposit_flow_full_upfront_steps_ok", False))
deposit_flow_score = group_score(df_flags)

# Timeline group
timeline_flags = [
    checks.get("timeline_exists", False),
    checks.get("timeline_header_ok", False),
    checks.get("timeline_rows_count_match", False),
    checks.get("timeline_values_match_input", False),
]
timeline_score = group_score(timeline_flags)

# Templates group
templates_flags = [
    checks.get("templates_exists", False),
    checks.get("templates_has_headings", False),
    checks.get("templates_has_placeholders", False),
    checks.get("templates_has_link", False),
    checks.get("templates_delay_section_placeholders", False),
]
templates_score = group_score(templates_flags)

# Exceptions group
exceptions_flags = [
    checks.get("exceptions_exists", False),
    checks.get("exceptions_has_required_phrases", False),
]
exceptions_score = group_score(exceptions_flags)

# Metrics group
metrics_flags = [
    checks.get("metrics_exists", False),
    checks.get("metrics_has_required_phrases", False),
]
metrics_score = group_score(metrics_flags)

# Final reward: average of six groups
group_scores = [summary_score, deposit_flow_score, timeline_score, templates_score, exceptions_score, metrics_score]
reward_value = sum(group_scores) / 6.0 if group_scores else 0.0

# Ensure baseline zero if no outputs at all
if not os.path.isdir(output_dir) or len([name for name in os.listdir(output_dir)]) == 0:
    reward_value = 0.0

# Clamp between 0 and 1
reward_value = max(0.0, min(1.0, reward_value))

result = {"reward": reward_value}
# Include all checks in output
result.update(checks)

print(json.dumps(result))