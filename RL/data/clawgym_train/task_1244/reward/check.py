import json
import os
import sys
import re

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

def is_nonempty_file(path):
    return os.path.isfile(path) and os.path.getsize(path) > 0

def parse_jsonl_lines(lines):
    objs = []
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            continue
        try:
            obj = json.loads(line_stripped)
        except Exception:
            return None
        objs.append(obj)
    return objs

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # 1) margin_report.md
        "margin_report_exists": False,
        "margin_report_nonempty": False,
        "margin_report_has_revenue_label": False,
        "margin_report_has_gross_margin_label": False,
        "margin_report_has_operating_margin_label": False,
        "margin_report_has_net_margin_label": False,
        "margin_report_has_qoq_trend_label": False,
        "margin_report_has_benchmark_label": False,
        "margin_report_has_top3_findings_label": False,
        "margin_report_has_recommendations_label": False,
        "margin_report_has_90day_priority_label": False,
        "margin_report_mentions_pricing_power": False,
        "margin_report_has_pricing_power_score": False,
        "margin_report_mentions_base": False,
        "margin_report_mentions_bull": False,
        "margin_report_mentions_bear": False,

        # 2) segment_flags.json
        "segment_flags_exists": False,
        "segment_flags_valid_json": False,
        "segment_flags_exact_keys": False,
        "segment_flags_all_lists": False,
        "segment_flags_any_nonempty": False,
        "segment_flags_gross_schema_ok": False,
        "segment_flags_discounts_schema_ok": False,
        "segment_flags_cac_ltv_schema_ok": False,
        "segment_flags_support_schema_ok": False,

        # 3) scenarios.csv
        "scenarios_exists": False,
        "scenarios_header_ok": False,
        "scenarios_min_rows": False,
        "scenarios_values_valid": False,

        # 4) task_graph.jsonl
        "task_graph_exists": False,
        "task_graph_min_lines": False,
        "task_graph_all_lines_json": False,
        "task_graph_fields_ok": False,
        "task_graph_types_valid": False,
        "task_graph_priorities_valid": False,
        "task_graph_statuses_valid": False,
        "task_graph_deps_is_array": False,
        "task_graph_has_epic": False,
        "task_graph_two_tasks_depend_on_epic": False,
        "task_graph_ids_unique": False,

        # 5) qa_review.txt
        "qa_review_exists": False,
        "qa_review_nonempty": False,
        "qa_review_has_pre_ship_header": False,
        "qa_review_enumerates_1_to_7": False,
        "qa_review_mentions_margin_report": False,
        "qa_review_has_block_fix_note": False,

        # 6) ops logs
        "ops_jsonl_exists": False,
        "ops_jsonl_min_lines": False,
        "ops_jsonl_all_lines_json": False,
        "ops_jsonl_has_export_cmd": False,
        "ops_jsonl_has_stats_cmd": False,

        "ops_csv_exists": False,
        "ops_csv_header_ok": False,
        "ops_csv_min_lines": False,
        "ops_csv_has_export_cmd": False,
        "ops_csv_has_stats_cmd": False,
    }

    # 1) margin_report.md checks
    mr_path = os.path.join(output_dir, "margin_report.md")
    if os.path.isfile(mr_path):
        checks["margin_report_exists"] = True
    if is_nonempty_file(mr_path):
        checks["margin_report_nonempty"] = True
        mr = read_text(mr_path)
        if mr is None:
            mr = ""
        mr_lower = mr.lower()

        # Labels
        if "revenue:" in mr_lower:
            checks["margin_report_has_revenue_label"] = True
        if "gross margin:" in mr_lower:
            checks["margin_report_has_gross_margin_label"] = True
        if "operating margin:" in mr_lower:
            checks["margin_report_has_operating_margin_label"] = True
        if "net margin:" in mr_lower:
            checks["margin_report_has_net_margin_label"] = True
        if "qoq trend:" in mr_lower:
            checks["margin_report_has_qoq_trend_label"] = True
        if "vs industry benchmark:" in mr_lower:
            checks["margin_report_has_benchmark_label"] = True
        if "top 3 findings:" in mr_lower:
            checks["margin_report_has_top3_findings_label"] = True
        if "recommendations:" in mr_lower:
            checks["margin_report_has_recommendations_label"] = True
        if "90-day priority:" in mr_lower:
            checks["margin_report_has_90day_priority_label"] = True

        # Pricing power phrase and score
        if "pricing power" in mr_lower:
            checks["margin_report_mentions_pricing_power"] = True
        # Find a numeric score 1-25 adjacent to "pricing power"
        # Search for numbers near the phrase
        pp_score_ok = False
        # Regex to capture "pricing power" followed by non-digits then a number
        pattern = re.compile(r'pricing power[^0-9\-]*([0-9]{1,2})', re.IGNORECASE)
        for m in pattern.finditer(mr):
            try:
                val = int(m.group(1))
                if 1 <= val <= 25:
                    pp_score_ok = True
                    break
            except Exception:
                continue
        checks["margin_report_has_pricing_power_score"] = pp_score_ok

        # Scenario mentions
        if re.search(r'\bbase\b', mr, re.IGNORECASE):
            checks["margin_report_mentions_base"] = True
        if re.search(r'\bbull\b', mr, re.IGNORECASE):
            checks["margin_report_mentions_bull"] = True
        if re.search(r'\bbear\b', mr, re.IGNORECASE):
            checks["margin_report_mentions_bear"] = True

    # 2) segment_flags.json checks
    sf_path = os.path.join(output_dir, "segment_flags.json")
    sf_obj = None
    if os.path.isfile(sf_path):
        checks["segment_flags_exists"] = True
        try:
            with open(sf_path, "r", encoding="utf-8") as f:
                sf_obj = json.load(f)
            checks["segment_flags_valid_json"] = True
        except Exception:
            sf_obj = None

    if sf_obj is not None and isinstance(sf_obj, dict):
        expected_keys = {"gross_margin_declines", "discounts_over_30", "cac_vs_ltv_risks", "support_costs_rising"}
        keys_ok = set(sf_obj.keys()) == expected_keys
        checks["segment_flags_exact_keys"] = keys_ok

        all_lists = True
        any_nonempty = False
        if keys_ok:
            for k in expected_keys:
                v = sf_obj.get(k)
                if not isinstance(v, list):
                    all_lists = False
                else:
                    if len(v) > 0:
                        any_nonempty = True
        else:
            all_lists = False
        checks["segment_flags_all_lists"] = all_lists
        checks["segment_flags_any_nonempty"] = any_nonempty

        # Schema checks only if file/keys are ok
        if keys_ok and all_lists:
            # gross_margin_declines schema
            g_ok = False
            g_list = sf_obj.get("gross_margin_declines", [])
            if len(g_list) == 0:
                g_ok = True  # empty is acceptable
            else:
                items_ok = True
                for it in g_list:
                    if not isinstance(it, dict):
                        items_ok = False
                        break
                    for req in ("segment", "from_q", "to_q", "qoq_decline_pct"):
                        if req not in it:
                            items_ok = False
                            break
                    if items_ok:
                        # qoq_decline_pct should be number
                        if not isinstance(it.get("qoq_decline_pct"), (int, float)):
                            items_ok = False
                            break
                    if not items_ok:
                        break
                g_ok = items_ok
            checks["segment_flags_gross_schema_ok"] = g_ok

            # discounts_over_30 schema
            d_ok = False
            d_list = sf_obj.get("discounts_over_30", [])
            if len(d_list) == 0:
                d_ok = True
            else:
                items_ok = True
                for it in d_list:
                    if not isinstance(it, dict):
                        items_ok = False
                        break
                    for req in ("quarter", "tier", "channel", "discount_rate"):
                        if req not in it:
                            items_ok = False
                            break
                    if items_ok:
                        if not isinstance(it.get("discount_rate"), (int, float)):
                            items_ok = False
                            break
                    if not items_ok:
                        break
                d_ok = items_ok
            checks["segment_flags_discounts_schema_ok"] = d_ok

            # cac_vs_ltv_risks schema
            c_ok = False
            c_list = sf_obj.get("cac_vs_ltv_risks", [])
            if len(c_list) == 0:
                c_ok = True
            else:
                items_ok = True
                for it in c_list:
                    if not isinstance(it, dict):
                        items_ok = False
                        break
                    for req in ("quarter", "tier", "cac", "ltv", "risk"):
                        if req not in it:
                            items_ok = False
                            break
                    if items_ok:
                        if not isinstance(it.get("cac"), (int, float)) or not isinstance(it.get("ltv"), (int, float)):
                            items_ok = False
                            break
                        # risk should be boolean true/false; at least ensure bool type
                        if not isinstance(it.get("risk"), bool):
                            items_ok = False
                            break
                    if not items_ok:
                        break
                c_ok = items_ok
            checks["segment_flags_cac_ltv_schema_ok"] = c_ok

            # support_costs_rising schema
            s_ok = False
            s_list = sf_obj.get("support_costs_rising", [])
            if len(s_list) == 0:
                s_ok = True
            else:
                items_ok = True
                for it in s_list:
                    if not isinstance(it, dict):
                        items_ok = False
                        break
                    for req in ("from_q", "to_q", "tier", "delta"):
                        if req not in it:
                            items_ok = False
                            break
                    if items_ok:
                        if not isinstance(it.get("delta"), (int, float)):
                            items_ok = False
                            break
                    if not items_ok:
                        break
                s_ok = items_ok
            checks["segment_flags_support_schema_ok"] = s_ok

    # 3) scenarios.csv checks
    scen_path = os.path.join(output_dir, "scenarios.csv")
    header_expected = "quarter,scenario,revenue,gross_margin_pct,operating_margin_pct,net_margin_pct,cash_runway_months,breakeven_quarter"
    scen_lines = read_lines(scen_path) if os.path.isfile(scen_path) else None
    if scen_lines is not None:
        checks["scenarios_exists"] = True
        if len(scen_lines) >= 1:
            header_line = scen_lines[0].strip()
            if header_line == header_expected:
                checks["scenarios_header_ok"] = True
            # Count data rows (non-empty lines after header)
            data_rows = [ln for ln in scen_lines[1:] if ln.strip() != ""]
            if len(data_rows) >= 9:
                checks["scenarios_min_rows"] = True
            # Scenario value validity
            scen_ok = True
            allowed = {"Base", "Bull", "Bear"}
            for ln in data_rows:
                parts = ln.split(",")
                if len(parts) < 2:
                    scen_ok = False
                    break
                scenario_val = parts[1].strip()
                if scenario_val not in allowed:
                    scen_ok = False
                    break
            if data_rows and scen_ok:
                checks["scenarios_values_valid"] = True

    # 4) task_graph.jsonl checks
    tg_path = os.path.join(output_dir, "task_graph.jsonl")
    tg_lines = read_lines(tg_path) if os.path.isfile(tg_path) else None
    tg_objs = None
    if tg_lines is not None:
        checks["task_graph_exists"] = True
        nonempty_lines = [ln for ln in tg_lines if ln.strip() != ""]
        if len(nonempty_lines) >= 5:
            checks["task_graph_min_lines"] = True
        tg_objs = parse_jsonl_lines(nonempty_lines)
        if tg_objs is not None:
            checks["task_graph_all_lines_json"] = True
            # Validate per-line fields and values
            fields_ok = True
            types_valid = True
            priorities_valid = True
            statuses_valid = True
            deps_is_array = True
            ids = []
            epic_ids = []
            for obj in tg_objs:
                # required fields
                required = ("id", "title", "type", "priority", "status", "deps", "assignee")
                if not all(k in obj for k in required):
                    fields_ok = False
                else:
                    # type
                    if obj["type"] not in ("epic", "task"):
                        types_valid = False
                    if obj["type"] == "epic":
                        epic_ids.append(obj.get("id"))
                    # priority integer 0-3
                    if not isinstance(obj["priority"], int) or not (0 <= obj["priority"] <= 3):
                        priorities_valid = False
                    # status in allowed set
                    if obj["status"] not in ("open", "in_progress", "blocked", "closed"):
                        statuses_valid = False
                    # deps array
                    if not isinstance(obj["deps"], list):
                        deps_is_array = False
                if "id" in obj:
                    ids.append(obj["id"])
            # set checks
            checks["task_graph_fields_ok"] = fields_ok
            checks["task_graph_types_valid"] = types_valid
            checks["task_graph_priorities_valid"] = priorities_valid
            checks["task_graph_statuses_valid"] = statuses_valid
            checks["task_graph_deps_is_array"] = deps_is_array
            # epic presence
            if len(epic_ids) >= 1:
                checks["task_graph_has_epic"] = True
            # ids unique
            if ids and len(set(ids)) == len(ids):
                checks["task_graph_ids_unique"] = True
            # at least two task entries depend on an epic id
            two_tasks_depend = False
            if epic_ids:
                target_epic = epic_ids[0]
                count = 0
                for obj in tg_objs:
                    if obj.get("type") == "task" and isinstance(obj.get("deps"), list) and target_epic in obj.get("deps"):
                        count += 1
                if count >= 2:
                    two_tasks_depend = True
            checks["task_graph_two_tasks_depend_on_epic"] = two_tasks_depend

    # 5) qa_review.txt checks
    qa_path = os.path.join(output_dir, "qa_review.txt")
    qa_text = read_text(qa_path) if os.path.isfile(qa_path) else None
    if os.path.isfile(qa_path):
        checks["qa_review_exists"] = True
    if qa_text is not None and len(qa_text) > 0:
        checks["qa_review_nonempty"] = True
        if re.search(r'pre-ship checklist', qa_text, re.IGNORECASE):
            checks["qa_review_has_pre_ship_header"] = True
        # Enumerates 1 through 7 as list items (e.g., "1." or "1)")
        enum_ok = True
        for n in range(1, 8):
            if not re.search(r'(^|\n)\s*' + re.escape(str(n)) + r'[\.\)]', qa_text):
                enum_ok = False
                break
        checks["qa_review_enumerates_1_to_7"] = enum_ok
        if "output/margin_report.md" in qa_text:
            checks["qa_review_mentions_margin_report"] = True
        # Includes BLOCK, FIX, NOTE (case-insensitive ok)
        has_block = re.search(r'\bBLOCK\b', qa_text, re.IGNORECASE) is not None
        has_fix = re.search(r'\bFIX\b', qa_text, re.IGNORECASE) is not None
        has_note = re.search(r'\bNOTE\b', qa_text, re.IGNORECASE) is not None
        checks["qa_review_has_block_fix_note"] = has_block and has_fix and has_note

    # 6) ops logs
    # JSONL
    ops_jsonl_path = os.path.join(output_dir, "ops_log.jsonl")
    ops_jsonl_lines = read_lines(ops_jsonl_path) if os.path.isfile(ops_jsonl_path) else None
    if ops_jsonl_lines is not None:
        checks["ops_jsonl_exists"] = True
        nonempty_ops = [ln for ln in ops_jsonl_lines if ln.strip() != ""]
        if len(nonempty_ops) >= 5:
            checks["ops_jsonl_min_lines"] = True
        objs = parse_jsonl_lines(nonempty_ops) if nonempty_ops else []
        if objs is not None and len(objs) == len(nonempty_ops):
            checks["ops_jsonl_all_lines_json"] = True
            has_export = any(o.get("cmd") == "export" for o in objs if isinstance(o, dict))
            has_stats = any(o.get("cmd") == "stats" for o in objs if isinstance(o, dict))
            checks["ops_jsonl_has_export_cmd"] = has_export
            checks["ops_jsonl_has_stats_cmd"] = has_stats

    # CSV
    ops_csv_path = os.path.join(output_dir, "ops_log.csv")
    ops_csv_lines = read_lines(ops_csv_path) if os.path.isfile(ops_csv_path) else None
    if ops_csv_lines is not None and len(ops_csv_lines) >= 1:
        checks["ops_csv_exists"] = True
        header = ops_csv_lines[0].strip()
        if header == "timestamp,command,value":
            checks["ops_csv_header_ok"] = True
        data = [ln for ln in ops_csv_lines[1:] if ln.strip() != ""]
        if len(data) >= 5:
            checks["ops_csv_min_lines"] = True
        # Second column contains at least one export and one stats
        has_export_csv = False
        has_stats_csv = False
        for ln in data:
            parts = ln.split(",")
            if len(parts) >= 2:
                cmd = parts[1].strip()
                if cmd == "export":
                    has_export_csv = True
                if cmd == "stats":
                    has_stats_csv = True
        checks["ops_csv_has_export_cmd"] = has_export_csv
        checks["ops_csv_has_stats_cmd"] = has_stats_csv

    # Compute reward as average of True booleans
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
        # Clamp to [0,1]
        if reward < 0.0:
            reward = 0.0
        if reward > 1.0:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()