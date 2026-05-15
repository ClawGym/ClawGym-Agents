import json
import os
import sys
import math
from typing import Any, Tuple, Union, List, Dict

# Workspace root handling
workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Utilities

def to_number(val: Any) -> Union[float, None]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if s.endswith("%"):
            s = s[:-1]
        s = s.replace(",", "")
        # remove leading plus sign
        if s.startswith("+"):
            s = s[1:]
        try:
            return float(s)
        except ValueError:
            return None
    return None

def parse_ratio(value: Any) -> Union[float, None]:
    # Accept:
    # - numeric ratio directly (>= 2.0)
    # - string "1:3.0" => 3.0
    # - string "3.0" => interpret as 3.0
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if ":" in s:
            parts = s.split(":")
            # Interpret as A:B where A is baseline (usually 1) and B is the multiple
            try:
                if len(parts) == 2:
                    a = float(parts[0].strip()) if parts[0].strip() else 1.0
                    b = float(parts[1].strip())
                    if a == 0:
                        return None
                    return b / a
                else:
                    # Take last number as ratio relative to first nonzero
                    nums = [float(p.strip()) for p in parts if p.strip() != ""]
                    if len(nums) >= 2 and nums[0] != 0:
                        return nums[-1] / nums[0]
                    return None
            except Exception:
                return None
        else:
            try:
                return float(s)
            except ValueError:
                return None
    return None

# Minimal YAML parser (supports simple mappings and lists)
class YamlParserError(Exception):
    pass

def _strip_comment(line: str) -> str:
    # Remove inline comments starting with # (not inside quotes naive)
    if "#" in line:
        idx = line.find("#")
        if idx == 0:
            return ""
        # crude: if before # there is a quote unmatched, ignore removal; else strip
        before = line[:idx]
        after = line[idx:]
        # naive: always strip comment
        return before.rstrip()
    return line

def parse_yaml_simple(text: str) -> Any:
    lines = []
    for raw in text.splitlines():
        # Keep indentation; strip trailing whitespace
        line = raw.rstrip("\n").rstrip("\r")
        # ignore pure comment lines
        stripped = line.lstrip()
        if not stripped:
            continue
        no_comment = _strip_comment(line)
        if not no_comment.strip():
            continue
        lines.append(no_comment)

    idx = 0
    n = len(lines)

    def indent_level(s: str) -> int:
        count = 0
        for ch in s:
            if ch == " ":
                count += 1
            else:
                break
        return count

    def parse_value_scalar(s: str) -> Any:
        ss = s.strip()
        if ss == "" or ss.lower() == "null" or ss.lower() == "none":
            return None
        if ss.lower() == "true":
            return True
        if ss.lower() == "false":
            return False
        # Quoted string
        if (ss.startswith('"') and ss.endswith('"')) or (ss.startswith("'") and ss.endswith("'")):
            return ss[1:-1]
        # Try number
        num = to_number(ss)
        if num is not None and (str(num) == ss.replace("+","") or ss.endswith("%") or ss.replace(",", "").replace("+","").replace("%","").replace(".","",1).isdigit()):
            return num if not ss.endswith("%") else f"{ss}"
        # Fallback string
        return ss

    def parse_block(current_indent: int) -> Any:
        nonlocal idx
        # Determine if the next block is a list or a mapping
        collection_type = None  # "list" or "dict"
        start_idx = idx

        # Peek first non-empty at current indent
        while idx < n:
            line = lines[idx]
            ind = indent_level(line)
            if ind < current_indent:
                break
            if ind > current_indent:
                # nested under previous key
                break
            content = line[ind:]
            if content.startswith("- "):
                collection_type = "list"
                break
            else:
                collection_type = "dict"
                break

        if collection_type == "list":
            arr: List[Any] = []
            while idx < n:
                line = lines[idx]
                ind = indent_level(line)
                if ind < current_indent:
                    break
                if ind > current_indent:
                    # Nested unexpected; let nested parser handle
                    # Should not happen as list items start with '- ' at current indent
                    # We'll parse nested with previous item if any
                    if len(arr) == 0:
                        # invalid structure
                        break
                    # Parse nested into last item if it's a dict
                    nested = parse_block(ind)
                    # If last item is a dict, merge
                    if isinstance(arr[-1], dict) and isinstance(nested, dict):
                        arr[-1].update(nested)
                    idx += 0
                    continue
                content = line[ind:]
                if not content.startswith("- "):
                    break
                # Process list item
                item_content = content[2:].strip()
                idx += 1
                if item_content == "":
                    # Item with nested block
                    # Next lines should have greater indent
                    if idx < n and indent_level(lines[idx]) > ind:
                        item = parse_block(ind + 2)
                        arr.append(item)
                    else:
                        arr.append(None)
                else:
                    # Could be "key: value" inline dict, or scalar
                    if ":" in item_content:
                        key, val = item_content.split(":", 1)
                        key = key.strip()
                        val = val.strip()
                        if val == "":
                            # nested dict follows
                            if idx < n and indent_level(lines[idx]) > ind:
                                nested = parse_block(ind + 2)
                                if isinstance(nested, dict):
                                    item = {key: nested}
                                else:
                                    item = {key: nested}
                                arr.append(item)
                            else:
                                arr.append({key: None})
                        else:
                            item = {key: parse_value_scalar(val)}
                            # Also consider nested continuation
                            if idx < n and indent_level(lines[idx]) > ind:
                                nested = parse_block(ind + 2)
                                if isinstance(nested, dict):
                                    item[key] = nested
                            arr.append(item)
                    else:
                        # scalar list item
                        arr.append(parse_value_scalar(item_content))
                        # consume any nested but unusual block (attach as dict with "_")
                        if idx < n and indent_level(lines[idx]) > ind:
                            _ = parse_block(ind + 2)  # parse and discard
            return arr

        # default mapping
        d: Dict[str, Any] = {}
        while idx < n:
            line = lines[idx]
            ind = indent_level(line)
            if ind < current_indent:
                break
            if ind > current_indent:
                # This is nested under previous key; parse nested and attach
                # But this branch is handled after consuming key line
                break
            content = line[ind:]
            if ":" not in content:
                break
            key, val = content.split(":", 1)
            key = key.strip()
            val = val.strip()
            idx += 1
            if val == "":
                # Nested block or empty/null
                if idx < n and indent_level(lines[idx]) > ind:
                    nested = parse_block(ind + 2)
                    d[key] = nested
                else:
                    d[key] = None
            else:
                # Inline value
                d[key] = parse_value_scalar(val)
                # If next is indented more, parse nested and if current value is a dict, merge; else overwrite
                if idx < n and indent_level(lines[idx]) > ind:
                    nested = parse_block(ind + 2)
                    if isinstance(d[key], dict) and isinstance(nested, dict):
                        d[key].update(nested)
                    else:
                        # If value is scalar and nested follows, create a subkey with same key? YAML would not do this,
                        # but we assign nested to key as value
                        d[key] = nested
        return d

    result = parse_block(0)
    return result

def load_yaml_file(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        # Try simple parser
        data = parse_yaml_simple(text)
        return True, data
    except Exception:
        return False, None

def load_json_file(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return True, data
    except Exception:
        return False, None

def approx_equal(a: float, b: float, tol: float) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol

def percent_str_to_float(s: Any) -> Union[float, None]:
    if isinstance(s, (int, float)):
        return float(s)
    if isinstance(s, str):
        v = to_number(s)
        return v
    return None

def get_nested(d: dict, path: List[str]) -> Any:
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur

# Checks initialization
checks: Dict[str, bool] = {
    # thesis.yaml
    "thesis_exists": False,
    "thesis_yaml_valid": False,
    "thesis_required_fields": False,
    "thesis_probabilities_sum": False,
    "thesis_ev_correct": False,
    "thesis_ev_vs_current_correct": False,
    "thesis_conviction_valid": False,
    # position_size.json
    "position_exists": False,
    "position_json_valid": False,
    "position_required_fields": False,
    "position_risk_per_share_correct": False,
    "position_risk_amount_consistent": False,
    "position_weight_calc_correct": False,
    "position_risk_limit_flag_correct": False,
    "position_weight_limit_flag_correct": False,
    # trade_journal.json
    "journal_exists": False,
    "journal_json_valid": False,
    "journal_required_fields": False,
    "journal_ratio_good": False,
    "journal_stop_matches_size": False,
    # risk_report.json
    "risk_exists": False,
    "risk_json_valid": False,
    "risk_required_fields": False,
    "risk_post_heat_leq_15": False,
    "risk_heat_consistent_with_position_flag": False,
    "risk_correlated_ok_logic": False,
    "risk_note_mitigation_if_needed": False,
}

# Paths
thesis_path = os.path.join(output_dir, "thesis.yaml")
position_path = os.path.join(output_dir, "position_size.json")
journal_path = os.path.join(output_dir, "trade_journal.json")
risk_path = os.path.join(output_dir, "risk_report.json")

# 1) thesis.yaml checks
thesis_data = None
if os.path.isfile(thesis_path):
    checks["thesis_exists"] = True
    ok, data = load_yaml_file(thesis_path)
    if ok and isinstance(data, dict):
        checks["thesis_yaml_valid"] = True
        thesis_data = data
        t = data.get("thesis") if isinstance(data.get("thesis"), dict) else None
        # required fields
        required_present = True
        def has(path: List[str]) -> bool:
            v = get_nested(data, ["thesis"] + path)
            return v is not None
        required_present = all([
            has(["ticker"]),
            has(["asset_class"]),
            has(["edge", "type"]),
            has(["edge", "description"]),
            has(["thesis_statement"]),
            has(["timeframe"]),
            has(["scenarios", "bull", "probability"]),
            has(["scenarios", "base", "probability"]),
            has(["scenarios", "bear", "probability"]),
            has(["scenarios", "bull", "target_price"]),
            has(["scenarios", "base", "target_price"]),
            has(["scenarios", "bear", "target_price"]),
            has(["current_price"]),
            has(["expected_value"]),
            has(["ev_vs_current"]),
            has(["invalidation", "price_stop"]),
            has(["invalidation", "thesis_stop"]),
            has(["invalidation", "time_stop"]),
            has(["conviction"]),
            has(["conviction_factors"]),
        ])
        if required_present:
            checks["thesis_required_fields"] = True
            # probabilities sum
            pb = to_number(get_nested(data, ["thesis","scenarios","bull","probability"]))
            pm = to_number(get_nested(data, ["thesis","scenarios","base","probability"]))
            pr = to_number(get_nested(data, ["thesis","scenarios","bear","probability"]))
            if pb is not None and pm is not None and pr is not None:
                if abs((pb + pm + pr) - 100.0) <= 0.1:
                    checks["thesis_probabilities_sum"] = True
            # EV math
            tb = to_number(get_nested(data, ["thesis","scenarios","bull","target_price"]))
            tm = to_number(get_nested(data, ["thesis","scenarios","base","target_price"]))
            tr = to_number(get_nested(data, ["thesis","scenarios","bear","target_price"]))
            ev = to_number(get_nested(data, ["thesis","expected_value"]))
            cp = to_number(get_nested(data, ["thesis","current_price"]))
            if None not in (pb, pm, pr, tb, tm, tr, ev):
                ev_calc = (pb*tb + pm*tm + pr*tr) / 100.0
                if abs(ev_calc - ev) <= 1.0:
                    checks["thesis_ev_correct"] = True
            # EV vs current
            ev_vs = get_nested(data, ["thesis","ev_vs_current"])
            if ev is not None and cp is not None and cp != 0:
                ev_pct = (ev - cp) / cp * 100.0
                ev_vs_num = percent_str_to_float(ev_vs)
                if ev_vs_num is not None:
                    if abs(ev_pct - ev_vs_num) <= 0.5:
                        checks["thesis_ev_vs_current_correct"] = True
            # conviction range and factors length
            conv = to_number(get_nested(data, ["thesis","conviction"]))
            factors = get_nested(data, ["thesis","conviction_factors"])
            if conv is not None and 1.0 <= conv <= 5.0 and isinstance(factors, list) and len(factors) >= 2:
                checks["thesis_conviction_valid"] = True

# 2) position_size.json checks
position_data = None
if os.path.isfile(position_path):
    checks["position_exists"] = True
    ok, pdata = load_json_file(position_path)
    if ok and isinstance(pdata, dict):
        checks["position_json_valid"] = True
        position_data = pdata
        # required fields
        req_keys = [
            "account_equity", "risk_per_trade_percent", "entry_price", "stop_loss_price",
            "risk_per_share", "position_size_units", "position_value", "risk_amount",
            "portfolio_weight_percent", "within_risk_limit", "within_position_weight_limit",
            "within_portfolio_heat_limit"
        ]
        if all(k in pdata for k in req_keys):
            checks["position_required_fields"] = True
            account_equity = to_number(pdata.get("account_equity"))
            risk_pct = to_number(pdata.get("risk_per_trade_percent"))
            entry = to_number(pdata.get("entry_price"))
            stop = to_number(pdata.get("stop_loss_price"))
            rps = to_number(pdata.get("risk_per_share"))
            size_units = to_number(pdata.get("position_size_units"))
            pos_value = to_number(pdata.get("position_value"))
            risk_amount = to_number(pdata.get("risk_amount"))
            pw_pct = to_number(pdata.get("portfolio_weight_percent"))
            within_risk = bool(pdata.get("within_risk_limit"))
            within_weight = bool(pdata.get("within_position_weight_limit"))

            # risk per share
            if None not in (entry, stop, rps):
                if approx_equal(rps, entry - stop, 0.01):
                    checks["position_risk_per_share_correct"] = True

            # risk amount consistency
            if None not in (size_units, rps, risk_amount):
                if approx_equal(risk_amount, size_units * rps, 1.0):
                    checks["position_risk_amount_consistent"] = True

            # position weight percent correctness
            if None not in (pos_value, account_equity, pw_pct) and account_equity not in (0, None):
                calc_pw = (pos_value / account_equity) * 100.0
                if approx_equal(calc_pw, pw_pct, 0.1):
                    checks["position_weight_calc_correct"] = True

            # within_risk_limit correct
            if None not in (risk_amount, account_equity, risk_pct):
                limit = account_equity * (risk_pct / 100.0)
                is_within = risk_amount <= (limit + 1e-6)
                if is_within == within_risk:
                    checks["position_risk_limit_flag_correct"] = True

            # within_position_weight_limit correct (≤10% with $1 tolerance)
            if None not in (pos_value, account_equity):
                weight_limit_value = account_equity * 0.10 + 1.0
                is_within_w = pos_value <= weight_limit_value
                if is_within_w == within_weight:
                    checks["position_weight_limit_flag_correct"] = True

# 3) trade_journal.json checks
journal_data = None
if os.path.isfile(journal_path):
    checks["journal_exists"] = True
    ok, jdata = load_json_file(journal_path)
    if ok and isinstance(jdata, dict):
        checks["journal_json_valid"] = True
        journal_data = jdata
        # required fields
        required = [
            "ticker", "direction", "entry_price", "stop_loss",
            "target_1", "target_2", "thesis", "edge_type",
            "conviction", "entry_type"
        ]
        present = all(k in jdata for k in required)
        # ensure ticker is AAPL
        if present and str(jdata.get("ticker")).upper() == "AAPL":
            # risk_reward check either string risk_reward or numeric risk_reward_ratio
            rr_val = None
            if "risk_reward" in jdata:
                rr_val = parse_ratio(jdata.get("risk_reward"))
            elif "risk_reward_ratio" in jdata:
                rr_val = parse_ratio(jdata.get("risk_reward_ratio"))
            if rr_val is not None and rr_val >= 2.0:
                checks["journal_ratio_good"] = True
            # mark required fields true if all present
            checks["journal_required_fields"] = True
            # stop_loss matches position stop
            if position_data is not None:
                j_stop = to_number(jdata.get("stop_loss"))
                p_stop = to_number(position_data.get("stop_loss_price"))
                if None not in (j_stop, p_stop) and approx_equal(j_stop, p_stop, 0.01):
                    checks["journal_stop_matches_size"] = True

# 4) risk_report.json checks
risk_data = None
if os.path.isfile(risk_path):
    checks["risk_exists"] = True
    ok, rdata = load_json_file(risk_path)
    if ok and isinstance(rdata, dict):
        checks["risk_json_valid"] = True
        risk_data = rdata
        # required keys
        req = [
            "regime",
            "pre_trade_portfolio_heat_percent",
            "post_trade_portfolio_heat_percent",
            "max_single_position_breach",
            "correlated_exposure_ok",
            "correlated_exposure_combined_weight",
            "note",
        ]
        if all(k in rdata for k in req):
            checks["risk_required_fields"] = True
            post_heat = to_number(rdata.get("post_trade_portfolio_heat_percent"))
            pre_heat = to_number(rdata.get("pre_trade_portfolio_heat_percent"))
            if post_heat is not None and post_heat <= 15.0 + 1e-9:
                checks["risk_post_heat_leq_15"] = True
            # consistency with position within_portfolio_heat_limit
            if position_data is not None:
                pos_flag = bool(position_data.get("within_portfolio_heat_limit"))
                if post_heat is not None:
                    expect_flag = post_heat <= 15.0 + 1e-9
                    if pos_flag == expect_flag:
                        checks["risk_heat_consistent_with_position_flag"] = True
            # correlated exposure logic
            combo_w = to_number(rdata.get("correlated_exposure_combined_weight"))
            coro_ok = bool(rdata.get("correlated_exposure_ok"))
            if combo_w is not None:
                if coro_ok:
                    if combo_w <= 20.0 + 1e-9:
                        checks["risk_correlated_ok_logic"] = True
                else:
                    # allow >20.0
                    if combo_w > 20.0 - 1e-9:
                        checks["risk_correlated_ok_logic"] = True
                        # note mentions mitigation
                        note = str(rdata.get("note", "") or "").lower()
                        mitigation_terms = ["mitigat", "hedg", "reduce", "rebalance", "diversif", "decreas", "lower position", "trim"]
                        if any(term in note for term in mitigation_terms):
                            checks["risk_note_mitigation_if_needed"] = True
                    else:
                        # If marked not ok but weight <=20, still require mitigation note
                        note = str(rdata.get("note", "") or "").lower()
                        mitigation_terms = ["mitigat", "hedg", "reduce", "rebalance", "diversif", "decreas", "lower position", "trim"]
                        if any(term in note for term in mitigation_terms):
                            checks["risk_note_mitigation_if_needed"] = True

# Compute reward as fraction of checks passed
total = len(checks)
passed = sum(1 for v in checks.values() if v)
reward = 0.0
if total > 0:
    reward = passed / total

# Ensure no-op baseline yields 0.0
# (If all output files missing, passed will be 0)
if not any([checks["thesis_exists"], checks["position_exists"], checks["journal_exists"], checks["risk_exists"]]):
    reward = 0.0

# Print single JSON line
result = {"reward": reward}
result.update(checks)
print(json.dumps(result))