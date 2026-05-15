import json
import os
import sys
import re

def coerce_number(val):
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, bool) or val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        # Remove common formatting like $ and commas
        s = s.replace("$", "").replace(",", "")
        # Handle percentage strings like "20%" -> 0.2 or "20 %"
        if s.endswith("%"):
            num_part = s[:-1].strip()
            try:
                return float(num_part) / 100.0
            except:
                return None
        try:
            return float(s)
        except:
            return None
    return None

def parse_boolish(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "yes", "y", "on"):
            return True
        if s in ("false", "no", "n", "off"):
            return False
    return None

def try_import_yaml():
    try:
        import yaml  # type: ignore
        return yaml
    except Exception:
        return None

def simple_yaml_load(text):
    # Minimal YAML parser for mappings/lists/scalars sufficient for this task
    # Supports:
    # - key: value
    # - key:
    #     nested_key: value
    # - lists: 
    #   - item
    #   - key: value under a list item
    lines = text.splitlines()
    # Remove BOM if present
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0].lstrip("\ufeff")
    root = None
    stack = []  # Each item: (indent_level, container)
    last_key_at_level = {}  # indent -> last key for dict waiting for nested
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        # Strip comments (only if not in quotes; for simplicity, strip after ' # ' or leading '#')
        stripped = line.lstrip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        # Handle YAML document markers
        if stripped in ("---", "..."):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = stripped
        # Determine current container by indent
        while stack and stack[-1][0] > indent:
            stack.pop()
        current_container = stack[-1][1] if stack else None

        def set_in_parent(value):
            nonlocal root, stack, current_container, indent
            if not stack:
                root = value
                stack.append((indent, value))
                return value
            parent_indent, parent = stack[-1]
            if isinstance(parent, list):
                parent.append(value)
                # push if value is container
                return value
            elif isinstance(parent, dict):
                # use last_key_at_level to know where to put
                key = last_key_at_level.get(parent_indent)
                if key is None:
                    # Not expected, but skip
                    return value
                parent[key] = value
                return value
            else:
                # Should not happen
                return value

        # List item
        if content.startswith("- "):
            item_content = content[2:].strip()
            # Ensure current container is a list; if none, create at this indent
            if current_container is None:
                new_list = []
                root = new_list
                stack.append((indent, new_list))
                current_container = new_list
            elif isinstance(current_container, dict):
                # If parent is dict, it means the key at this level expects a list
                # Create list for the last key
                parent_indent, parent = stack[-1]
                # Create list and assign to last key
                key = last_key_at_level.get(parent_indent)
                if key is not None:
                    new_list = []
                    parent[key] = new_list
                    current_container = new_list
                    stack.append((indent, new_list))
                else:
                    # Fallback: create a new list at this level replacing dict (rare)
                    new_list = []
                    root = new_list
                    stack = [(indent, new_list)]
                    current_container = new_list
            # Now current_container is a list (or set above accordingly)
            if isinstance(current_container, list):
                if item_content == "":
                    # Add placeholder and wait for nested content
                    new_item = {}
                    current_container.append(new_item)
                    stack.append((indent + 2, new_item))
                else:
                    # Check if item is "key: value" pair starting a dict
                    if ":" in item_content:
                        # But beware of values with ":"; split only on first colon
                        key_part, val_part = item_content.split(":", 1)
                        key = key_part.strip()
                        val = val_part.strip()
                        new_item = {}
                        if val == "":
                            # key: (nested follows)
                            new_item[key] = {}
                            current_container.append(new_item)
                            # push list item dict, then nested dict
                            stack.append((indent + 2, new_item))
                            last_key_at_level[indent + 2] = key
                            stack.append((indent + 4, new_item[key]))
                        else:
                            # scalar value
                            # Try to parse numbers/bools
                            parsed_bool = parse_boolish(val)
                            if parsed_bool is not None:
                                parsed_val = parsed_bool
                            else:
                                num = coerce_number(val)
                                parsed_val = num if num is not None else (val.strip("\"'"))
                            new_item[key] = parsed_val
                            current_container.append(new_item)
                            stack.append((indent + 2, new_item))
                    else:
                        # scalar list item
                        parsed_bool = parse_boolish(item_content)
                        if parsed_bool is not None:
                            current_container.append(parsed_bool)
                        else:
                            num = coerce_number(item_content)
                            current_container.append(num if num is not None else item_content.strip("\"'"))
            continue

        # Key: value or Key:
        if ":" in content:
            key_part, val_part = content.split(":", 1)
            key = key_part.strip()
            val = val_part.strip()
            # Ensure current container is a dict
            if current_container is None:
                new_dict = {}
                root = new_dict
                stack.append((indent, new_dict))
                current_container = new_dict
            elif isinstance(current_container, list):
                # If parent is a list, last element might be a dict to hold this
                if len(current_container) == 0 or not isinstance(current_container[-1], dict):
                    current_container.append({})
                # For subsequent nested key-values, use last dict
                current_container = current_container[-1]
                # Adjust stack accordingly
                # Remove any prior stack entries at this indent
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                stack.append((indent, current_container))
            if isinstance(current_container, dict):
                if val == "":
                    # key: (nested dict)
                    current_container[key] = {}
                    last_key_at_level[indent] = key
                    # Push nested dict
                    stack.append((indent + 2, current_container[key]))
                else:
                    parsed_bool = parse_boolish(val)
                    if parsed_bool is not None:
                        parsed_val = parsed_bool
                    else:
                        num = coerce_number(val)
                        parsed_val = num if num is not None else val.strip("\"'")
                    current_container[key] = parsed_val
                    last_key_at_level[indent] = key
            continue

        # Fallback: scalar on its own (rare)
        scalar_val = content
        parsed_bool = parse_boolish(scalar_val)
        if parsed_bool is not None:
            sv = parsed_bool
        else:
            num = coerce_number(scalar_val)
            sv = num if num is not None else scalar_val.strip("\"'")
        if current_container is None:
            root = sv
        elif isinstance(current_container, list):
            current_container.append(sv)
        elif isinstance(current_container, dict):
            # Without a key, cannot place reliably; skip
            pass

    return root

def load_yaml_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return None, "read_error"
    yaml_mod = try_import_yaml()
    if yaml_mod:
        try:
            data = yaml_mod.safe_load(text)
            return data, None
        except Exception:
            # Fall through to simple loader
            pass
    try:
        data = simple_yaml_load(text)
        return data, None
    except Exception:
        return None, "parse_error"

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, "json_error"

def deep_get(d, keys, default=None):
    cur = d
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur

def find_number_in_dict(d, key_path_variants):
    for path in key_path_variants:
        val = deep_get(d, path, None)
        n = coerce_number(val)
        if n is not None:
            return n
    return None

def get_gross_sf_from(d):
    # Usually at scope.gross_sf
    return find_number_in_dict(d, [["scope", "gross_sf"], ["project", "gross_sf"], ["gross_sf"]])

def get_location_factor_from(d):
    return find_number_in_dict(d, [["project", "location", "location_factor"], ["location_factor"], ["project", "location_factor"]])

def get_escalation_rate_from(d):
    return find_number_in_dict(d, [["estimate", "escalation_rate"], ["escalation_rate"]])

def numeric_dict_values(d):
    if not isinstance(d, dict):
        return False
    ok = True
    for v in d.values():
        if coerce_number(v) is None:
            ok = False
            break
    return ok

def get_cross_checks(obj):
    if obj is None:
        return None, 0
    if isinstance(obj, dict):
        return obj, len(obj)
    if isinstance(obj, list):
        return obj, len(obj)
    return None, 0

def extract_trades_from_json(obj):
    # Return list of trade objects
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        # common wrapper
        if "trades" in obj and isinstance(obj["trades"], list):
            return obj["trades"]
        # if dict keyed by division
        trades = []
        for v in obj.values():
            if isinstance(v, dict) and ("csi_division" in v or "quotes" in v):
                trades.append(v)
        if trades:
            return trades
    return []

def parse_savings_pct(val):
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if s.endswith("%"):
            try:
                return float(s[:-1].strip()) / 100.0
            except:
                return None
        try:
            return float(s)
        except:
            return None
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "estimate_exists": False,
        "estimate_valid_yaml": False,
        "estimate_has_required_keys": False,
        "estimate_type_definitive": False,
        "estimate_has_division_totals": False,
        "estimate_division_keys_present": False,
        "estimate_division_values_numeric": False,
        "cross_checks_present": False,
        "estimate_has_markup_fields": False,
        "estimate_general_conditions_ratio_ok": False,
        "estimate_escalation_rate_matches_input": False,
        "estimate_location_factor_matches_input": False,
        "estimate_months_to_midpoint_positive": False,
        "estimate_cost_per_sf_consistent": False,

        "sub_eval_exists": False,
        "sub_eval_valid_json": False,
        "sub_eval_has_div_03_23_26": False,
        "sub_eval_quotes_count_and_fields": False,
        "sub_eval_chosen_vendor_valid": False,

        "ve_exists": False,
        "ve_valid_yaml": False,
        "ve_has_two_items": False,
        "ve_items_fields_and_math_ok": False,

        "bid_summary_exists": False,
        "bid_summary_has_required_sections": False,
    }

    # Load input reference
    brief_path = os.path.join(input_dir, "project_brief.yaml")
    brief_data = None
    if os.path.isfile(brief_path):
        brief_data, _ = load_yaml_file(brief_path)

    # Expected input values
    input_location_factor = None
    input_escalation_rate = None
    if isinstance(brief_data, dict):
        input_location_factor = get_location_factor_from(brief_data)
        input_escalation_rate = get_escalation_rate_from(brief_data)

    # 1) estimate.yaml
    est_path = os.path.join(output_dir, "estimate.yaml")
    est_data = None
    if os.path.isfile(est_path):
        checks["estimate_exists"] = True
        est_data, est_err = load_yaml_file(est_path)
        if est_err is None and isinstance(est_data, (dict, list)):
            checks["estimate_valid_yaml"] = True
            # Required keys and structure
            if isinstance(est_data, dict):
                has_project = "project" in est_data
                has_scope = "scope" in est_data and isinstance(est_data.get("scope"), dict) and coerce_number(est_data["scope"].get("gross_sf")) not in (None, 0)
                has_schedule = "schedule" in est_data
                has_estimate_block = "estimate" in est_data and isinstance(est_data.get("estimate"), dict)
                has_div_totals = "division_totals" in est_data and isinstance(est_data.get("division_totals"), dict)
                has_markup_calc = "markup_calculation" in est_data and isinstance(est_data.get("markup_calculation"), dict)
                checks["estimate_has_required_keys"] = all([has_project, has_scope, has_schedule, has_estimate_block, has_div_totals, has_markup_calc])

                # estimate.type is definitive and estimate block contains base_date, escalation_rate, location_factor
                est_block = est_data.get("estimate", {}) if isinstance(est_data, dict) else {}
                est_type = est_block.get("type")
                if isinstance(est_type, str) and est_type.strip().lower() == "definitive":
                    # Also verify presence of required fields
                    if "base_date" in est_block and "escalation_rate" in est_block and "location_factor" in est_block:
                        checks["estimate_type_definitive"] = True

                # division_totals presence and numeric
                div_totals = est_data.get("division_totals", {})
                if isinstance(div_totals, dict):
                    checks["estimate_has_division_totals"] = True
                    required_divs = ["01","03","05","07","08","09","21","22","23","26","31","32","33"]
                    # Presence
                    present_all = all(k in div_totals for k in required_divs)
                    checks["estimate_division_keys_present"] = present_all
                    # Numeric
                    numeric_all = True
                    for k in required_divs:
                        v = div_totals.get(k, None)
                        n = coerce_number(v)
                        if n is None:
                            numeric_all = False
                            break
                    checks["estimate_division_values_numeric"] = numeric_all

                # cross_checks at least 2
                cross_obj = est_data.get("cross_checks")
                _, cross_len = get_cross_checks(cross_obj)
                if cross_len >= 2:
                    checks["cross_checks_present"] = True

                # markup_calculation fields
                mc = est_data.get("markup_calculation", {})
                mc_ok = False
                gc_ratio_ok = False
                escal_rate_match = False
                loc_factor_match = False
                months_positive = False
                cpsf_ok = False
                if isinstance(mc, dict):
                    direct_costs = coerce_number(mc.get("direct_costs"))
                    gc = mc.get("general_conditions", {})
                    oh = mc.get("overhead", {})
                    profit = mc.get("profit", {})
                    contingency = mc.get("contingency", {})
                    bond = mc.get("bond", {})
                    escalation = mc.get("escalation", {})
                    total_estimate = coerce_number(mc.get("total_estimate"))
                    cost_per_sf = coerce_number(mc.get("cost_per_sf"))
                    # Check presence of required numeric fields
                    required_nested = all([
                        isinstance(gc, dict) and coerce_number(gc.get("percentage")) is not None and coerce_number(gc.get("amount")) is not None,
                        isinstance(oh, dict) and coerce_number(oh.get("percentage")) is not None and coerce_number(oh.get("amount")) is not None,
                        isinstance(profit, dict) and coerce_number(profit.get("percentage")) is not None and coerce_number(profit.get("amount")) is not None,
                        isinstance(contingency, dict) and coerce_number(contingency.get("design_contingency")) is not None and coerce_number(contingency.get("construction_contingency")) is not None and coerce_number(contingency.get("amount")) is not None,
                        isinstance(bond, dict) and coerce_number(bond.get("percentage")) is not None and coerce_number(bond.get("amount")) is not None,
                        isinstance(escalation, dict) and coerce_number(escalation.get("rate")) is not None and coerce_number(escalation.get("months_to_midpoint")) is not None and coerce_number(escalation.get("amount")) is not None,
                        direct_costs is not None,
                        total_estimate is not None,
                        cost_per_sf is not None
                    ])
                    mc_ok = required_nested
                    # General conditions ratio check if data present
                    if direct_costs is not None and isinstance(gc, dict):
                        gc_amount = coerce_number(gc.get("amount"))
                        if gc_amount is not None and direct_costs > 0:
                            ratio = gc_amount / direct_costs
                            if 0.08 - 1e-6 <= ratio <= 0.15 + 1e-6:
                                gc_ratio_ok = True
                    # Escalation rate equals input escalation_rate
                    if isinstance(escalation, dict):
                        esc_rate = coerce_number(escalation.get("rate"))
                        if input_escalation_rate is not None and esc_rate is not None:
                            # Compare with small tolerance
                            if abs(esc_rate - float(input_escalation_rate)) <= 1e-6:
                                escal_rate_match = True
                    # Location factor in estimate block equals input
                    if input_location_factor is not None:
                        out_loc = coerce_number(est_block.get("location_factor"))
                        if out_loc is not None:
                            if abs(out_loc - float(input_location_factor)) <= 1e-6:
                                loc_factor_match = True
                    # Months to midpoint positive
                    if isinstance(escalation, dict):
                        months = coerce_number(escalation.get("months_to_midpoint"))
                        if months is not None and months > 0:
                            months_positive = True
                    # cost_per_sf within 1% of total_estimate / gross_sf
                    gross_sf_est = get_gross_sf_from(est_data)
                    if gross_sf_est is not None and gross_sf_est > 0 and total_estimate is not None and cost_per_sf is not None:
                        expected = total_estimate / gross_sf_est
                        if expected == 0:
                            cpsf_ok = abs(cost_per_sf) < 1e-6
                        else:
                            if abs(cost_per_sf - expected) / abs(expected) <= 0.01 + 1e-12:
                                cpsf_ok = True

                checks["estimate_has_markup_fields"] = mc_ok
                checks["estimate_general_conditions_ratio_ok"] = gc_ratio_ok
                checks["estimate_escalation_rate_matches_input"] = escal_rate_match
                checks["estimate_location_factor_matches_input"] = loc_factor_match
                checks["estimate_months_to_midpoint_positive"] = months_positive
                checks["estimate_cost_per_sf_consistent"] = cpsf_ok

    # 2) sub_eval.json
    sub_path = os.path.join(output_dir, "sub_eval.json")
    sub_data = None
    if os.path.isfile(sub_path):
        checks["sub_eval_exists"] = True
        sub_data, sub_err = load_json_file(sub_path)
        if sub_err is None:
            checks["sub_eval_valid_json"] = True
            trades = extract_trades_from_json(sub_data)
            # Find trades with csi_division "03","23","26"
            div_map = {"03": None, "23": None, "26": None}
            for t in trades:
                if not isinstance(t, dict):
                    continue
                div = t.get("csi_division")
                if isinstance(div, (int, float)):
                    div = f"{int(div):02d}"
                elif isinstance(div, str):
                    div = div.strip()
                if div in div_map and div_map[div] is None:
                    div_map[div] = t
            has_all = all(div_map[d] is not None for d in ["03", "23", "26"])
            checks["sub_eval_has_div_03_23_26"] = has_all

            quotes_ok_all = True
            chosen_ok_all = True
            if has_all:
                for d in ["03", "23", "26"]:
                    t = div_map[d]
                    quotes = t.get("quotes")
                    if not isinstance(quotes, list) or len(quotes) < 3:
                        quotes_ok_all = False
                        break
                    # Check each quote has vendor, price numeric, weighted_total numeric
                    vendors = set()
                    for q in quotes:
                        if not isinstance(q, dict):
                            quotes_ok_all = False
                            break
                        vendor = q.get("vendor")
                        price = coerce_number(q.get("price"))
                        wt = coerce_number(q.get("weighted_total"))
                        if not isinstance(vendor, str) or vendor.strip() == "":
                            quotes_ok_all = False
                            break
                        vendors.add(vendor)
                        if price is None or wt is None:
                            quotes_ok_all = False
                            break
                    if not quotes_ok_all:
                        break
                    chosen = t.get("chosen_vendor")
                    if not isinstance(chosen, str) or chosen not in vendors:
                        chosen_ok_all = False
                        break
            else:
                quotes_ok_all = False
                chosen_ok_all = False
            checks["sub_eval_quotes_count_and_fields"] = quotes_ok_all
            checks["sub_eval_chosen_vendor_valid"] = chosen_ok_all

    # 3) ve.yaml
    ve_path = os.path.join(output_dir, "ve.yaml")
    ve_data = None
    if os.path.isfile(ve_path):
        checks["ve_exists"] = True
        ve_data, ve_err = load_yaml_file(ve_path)
        if ve_err is None:
            checks["ve_valid_yaml"] = True
            # Determine list of items
            items = None
            if isinstance(ve_data, list):
                items = ve_data
            elif isinstance(ve_data, dict):
                for k in ["ve_items", "items", "proposals"]:
                    if k in ve_data and isinstance(ve_data[k], list):
                        items = ve_data[k]
                        break
                if items is None:
                    # If dict looks like a single item (has original/proposed), wrap
                    if "original" in ve_data and "proposed" in ve_data:
                        items = [ve_data]
            if isinstance(items, list) and len(items) >= 2:
                checks["ve_has_two_items"] = True
                all_ok = True
                for it in items:
                    if not isinstance(it, dict):
                        all_ok = False
                        break
                    # Must have division and risk
                    if "division" not in it or "risk" not in it:
                        all_ok = False
                        break
                    orig = it.get("original", {})
                    prop = it.get("proposed", {})
                    savings = it.get("savings")
                    savings_pct = it.get("savings_pct")
                    net_savings = it.get("net_savings")
                    if not isinstance(orig, dict) or not isinstance(prop, dict):
                        all_ok = False
                        break
                    oc = coerce_number(orig.get("cost"))
                    pc = coerce_number(prop.get("cost"))
                    sv = coerce_number(savings)
                    sp = parse_savings_pct(savings_pct)
                    ns = coerce_number(net_savings)
                    if oc is None or pc is None or sv is None or ns is None or sp is None:
                        all_ok = False
                        break
                    # Check relationships
                    if abs((oc - pc) - sv) > max(1e-2, 1e-6 * max(abs(oc), abs(pc), 1.0)):
                        all_ok = False
                        break
                    # savings_pct equals savings/original.cost within 0.01 absolute
                    expected_pct = 0.0 if oc == 0 else sv / oc
                    if abs(expected_pct - sp) > 0.01 + 1e-12:
                        all_ok = False
                        break
                    if ns < -1e-6:
                        all_ok = False
                        break
                checks["ve_items_fields_and_math_ok"] = all_ok

    # 4) bid_summary.md
    bid_path = os.path.join(output_dir, "bid_summary.md")
    if os.path.isfile(bid_path):
        checks["bid_summary_exists"] = True
        try:
            with open(bid_path, "r", encoding="utf-8") as f:
                content = f.read()
            lc = content.lower()
            required_phrases = ["bid summary", "assumptions", "exclusions", "allowances", "addenda"]
            if all(p in lc for p in required_phrases):
                checks["bid_summary_has_required_sections"] = True
        except Exception:
            pass

    # Calculate reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if no required artifacts present, reward must be 0.0
    # If all four deliverables missing or invalid, ensure reward is 0.0
    essential_outputs = [
        checks["estimate_exists"] and checks["estimate_valid_yaml"],
        checks["sub_eval_exists"] and checks["sub_eval_valid_json"],
        checks["ve_exists"] and checks["ve_valid_yaml"],
        checks["bid_summary_exists"],
    ]
    if not any(essential_outputs):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()