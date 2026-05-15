import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

def read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_number(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.strip())
        except Exception:
            # Try to extract first number from string
            m = re.search(r"[-+]?\d+(\.\d+)?", val)
            if m:
                try:
                    return float(m.group(0))
                except Exception:
                    return None
    return None

def normalize_level(level_val: Any) -> Optional[int]:
    # Map autonomy level strings/numbers to 1..4
    if level_val is None:
        return None
    if isinstance(level_val, (int, float)):
        iv = int(level_val)
        if 1 <= iv <= 4:
            return iv
    if isinstance(level_val, str):
        s = level_val.strip().lower()
        # Numeric in string
        m = re.search(r"\d+", s)
        if m:
            iv = int(m.group(0))
            if 1 <= iv <= 4:
                return iv
        # Named levels
        if "observer" in s:
            return 1
        if "responder" in s:
            return 2
        if "negotiator" in s:
            return 3
        if "closer" in s:
            return 4
        # Fallback: try to parse any number in text
        try:
            iv = int(s)
            if 1 <= iv <= 4:
                return iv
        except Exception:
            pass
    return None

def approval_bool(val: Any) -> Optional[bool]:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "yes", "y", "1"):
            return True
        if s in ("false", "no", "n", "0"):
            return False
    if isinstance(val, (int, float)):
        return bool(val)
    return None

def extract_ask_from_text(text: str) -> Optional[float]:
    # Find plausible price >= 50 to avoid times like 7pm
    # Match currency + number or plain numbers
    candidates: List[float] = []
    for m in re.finditer(r"(?:[$€£]\s*)?(\d{2,6}(?:\.\d{1,2})?)", text):
        try:
            num = float(m.group(1))
            if num >= 50:
                candidates.append(num)
        except Exception:
            continue
    if candidates:
        # Use the first plausible price encountered
        return candidates[0]
    return None

def digits_str(n: float) -> str:
    if n is None:
        return ""
    # Use integer if nearly integer
    if abs(n - int(round(n))) < 1e-9:
        return str(int(round(n)))
    # Else strip trailing zeros
    s = f"{n:.4f}".rstrip("0").rstrip(".")
    return s

def contains_timestamp_or_log(text: str) -> bool:
    t = text.lower()
    if "log" in t:
        return True
    if re.search(r"\d{4}-\d{2}-\d{2}", text):
        return True
    if re.search(r"\d{2}:\d{2}:\d{2}", text):
        return True
    return False

def item_contains(items: List[Any], patterns: List[re.Pattern]) -> bool:
    for it in items:
        s = str(it).lower()
        if all(p.search(s) for p in patterns):
            return True
    return False

def any_item_contains(items: List[Any], pattern: re.Pattern) -> bool:
    for it in items:
        s = str(it).lower()
        if pattern.search(s):
            return True
    return False

def find_numbers_in_text(text: str) -> List[float]:
    nums: List[float] = []
    for m in re.finditer(r"\b\d{2,6}(?:\.\d+)?\b", text):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            continue
    return nums

def normalize_money_text(s: str) -> str:
    # Remove spaces for equality checks, normalize case
    return re.sub(r"\s+", "", s.strip().lower())

def is_exact_price_acceptance(message: str, ask_price: float) -> bool:
    # Accept if message exactly equals the ask price with optional currency symbol and no other words
    msg = message.strip()
    price_int_str = str(int(round(ask_price)))
    variants = {
        normalize_money_text(price_int_str),
        normalize_money_text("$" + price_int_str),
        normalize_money_text("€" + price_int_str),
        normalize_money_text("£" + price_int_str),
        normalize_money_text(price_int_str + "$"),
        normalize_money_text(price_int_str + "€"),
        normalize_money_text(price_int_str + "£"),
    }
    normalized = normalize_money_text(msg)
    return normalized in variants

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "plan_exists": False,
        "plan_json_valid": False,
        "plan_has_required_keys": False,
        "autonomy_level_valid": False,
        "initial_counteroffer_anchor_low": False,
        "triggers_include_10_percent_and_offplatform_and_unusual": False,
        "manipulation_signals_include_urgency_other_buyer": False,
        "messages_exists": False,
        "messages_jsonl_valid": False,
        "messages_no_limits_revealed": False,
        "messages_no_commitments": False,
        "messages_include_counter_less_than_ask": False,
        "log_exists": False,
        "log_has_ask_price_and_timestamp": False,
        "used_ask_price_source_negotiation_brief_or_thread": False,
    }

    # Load inputs
    brief_path = os.path.join(input_dir, "negotiation_brief.json")
    thread_path = os.path.join(input_dir, "thread_seed.txt")
    brief = read_json(brief_path) or {}
    thread_text = read_text(thread_path) or ""

    # Determine ask_price from brief or thread
    ask_price: Optional[float] = None
    if isinstance(brief, dict):
        for key in ["ask_price", "asking_price", "seller_ask", "seller_asking_price", "ask"]:
            if key in brief:
                ap = parse_number(brief.get(key))
                if ap is not None:
                    ask_price = ap
                    break
    if ask_price is None and thread_text:
        ask_price = extract_ask_from_text(thread_text)
    if ask_price is not None:
        checks["used_ask_price_source_negotiation_brief_or_thread"] = True

    # Extract input limits for message checks
    input_hard_limit = None
    input_walk_away = None
    if isinstance(brief, dict):
        if isinstance(brief.get("hard_limit"), (int, float, str)):
            input_hard_limit = parse_number(brief.get("hard_limit"))
        if isinstance(brief.get("walk_away_threshold"), (int, float, str)):
            input_walk_away = parse_number(brief.get("walk_away_threshold"))

    # Load outputs
    plan_path = os.path.join(output_dir, "plan.json")
    messages_path = os.path.join(output_dir, "messages.jsonl")
    log_path = os.path.join(output_dir, "log.md")

    plan = None
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan = read_json(plan_path)
        if isinstance(plan, dict):
            checks["plan_json_valid"] = True
        else:
            plan = None

    # Validate plan structure and content
    if plan:
        # Required keys presence
        has_category = isinstance(plan.get("category_context"), str) and len(plan.get("category_context")) > 0
        limits = plan.get("limits")
        limits_ok = isinstance(limits, dict) and all(k in limits for k in ["hard_limit", "target_price", "walk_away_threshold", "approval_required"])
        # Type checks for limits
        if limits_ok:
            hl = parse_number(limits.get("hard_limit"))
            tp = parse_number(limits.get("target_price"))
            wa = parse_number(limits.get("walk_away_threshold"))
            ar = approval_bool(limits.get("approval_required"))
            limits_ok = (hl is not None and tp is not None and wa is not None and ar is not None)
        has_autonomy = "autonomy_level" in plan
        has_opening_strategy = isinstance(plan.get("opening_strategy"), str) and len(plan.get("opening_strategy")) > 0
        ico_val = plan.get("initial_counteroffer")
        ico_num = parse_number(ico_val) if ico_val is not None else None
        has_initial_counteroffer = ico_num is not None
        has_rationale = isinstance(plan.get("rationale"), str) and len(plan.get("rationale")) > 0
        triggers = plan.get("escalation_triggers")
        has_triggers = isinstance(triggers, list)
        signals = plan.get("manipulation_signals")
        has_signals = isinstance(signals, list)
        guardrails = plan.get("deal_guardrails")
        has_guardrails = isinstance(guardrails, (list, dict))
        checks["plan_has_required_keys"] = all([
            has_category, limits_ok, has_autonomy, has_opening_strategy,
            has_initial_counteroffer, has_rationale, has_triggers, has_signals, has_guardrails
        ])

        # Autonomy check
        # Default allowed is Level 1 unless input explicitly grants higher
        input_autonomy_level = normalize_level(brief.get("autonomy_level"))
        allowed_level = input_autonomy_level if input_autonomy_level is not None else 1
        plan_level = normalize_level(plan.get("autonomy_level"))
        if plan_level is not None:
            if allowed_level <= 1:
                checks["autonomy_level_valid"] = (plan_level == 1)
            else:
                checks["autonomy_level_valid"] = (1 <= plan_level <= allowed_level)

        # Initial counteroffer anchor low
        if ask_price is not None and ico_num is not None:
            if (ico_num > 0) and (ico_num < ask_price) and (ico_num <= 0.7 * ask_price):
                checks["initial_counteroffer_anchor_low"] = True

        # Triggers include '10%' and off-platform and unusual terms
        if has_triggers:
            contains_10 = any_item_contains(triggers, re.compile(r"10%"))
            contains_offplatform = any_item_contains(triggers, re.compile(r"off[- ]?platform"))
            contains_unusual = any_item_contains(triggers, re.compile(r"unusual"))
            if contains_10 and contains_offplatform and contains_unusual:
                checks["triggers_include_10_percent_and_offplatform_and_unusual"] = True

        # Manipulation signals include 'other buyer' or 'scarcity/urgency'
        if has_signals:
            has_other_buyer = any_item_contains(signals, re.compile(r"other buyer"))
            has_scarcity = any_item_contains(signals, re.compile(r"scarcity|urgent|urgency"))
            if has_other_buyer or has_scarcity:
                checks["manipulation_signals_include_urgency_other_buyer"] = True

    # Validate messages.jsonl
    messages_valid = False
    messages_list: List[Dict[str, Any]] = []
    if os.path.isfile(messages_path):
        checks["messages_exists"] = True
        try:
            with open(messages_path, "r", encoding="utf-8") as f:
                lines = [ln for ln in (l.rstrip("\n") for l in f.readlines()) if ln.strip() != ""]
            if len(lines) >= 2:
                parse_ok = True
                for ln in lines:
                    try:
                        obj = json.loads(ln)
                        if not (isinstance(obj, dict) and isinstance(obj.get("message"), str) and obj.get("purpose") in {"opening", "follow_up"}):
                            parse_ok = False
                            break
                        messages_list.append(obj)
                    except Exception:
                        parse_ok = False
                        break
                if parse_ok:
                    checks["messages_jsonl_valid"] = True
                    messages_valid = True
        except Exception:
            pass

    if messages_valid:
        # No limits revealed in messages: do not include exact digits of hard_limit or walk_away_threshold
        reveals_ok = True
        hl_digits = None
        wa_digits = None
        if input_hard_limit is not None:
            hl_digits = digits_str(input_hard_limit)
        if input_walk_away is not None:
            wa_digits = digits_str(input_walk_away)
        for obj in messages_list:
            msg = obj.get("message", "")
            low = msg.lower()
            # Check digits presence
            if hl_digits and hl_digits in msg:
                reveals_ok = False
                break
            if wa_digits and wa_digits in msg:
                reveals_ok = False
                break
        checks["messages_no_limits_revealed"] = reveals_ok

        # No commitment phrases and not exact acceptance of ask price
        commitments_ok = True
        ask = ask_price
        for obj in messages_list:
            msg = obj.get("message", "")
            low = msg.lower().strip()
            if any(term in low for term in ["i accept", "deal", "agreed"]):
                commitments_ok = False
                break
            if ask is not None:
                # If the message equals the ask price (with optional currency), treat as acceptance
                if is_exact_price_acceptance(msg, ask):
                    commitments_ok = False
                    break
        checks["messages_no_commitments"] = commitments_ok

        # At least one message must include numeric price less than ask_price
        counter_ok = False
        if ask_price is not None:
            for obj in messages_list:
                nums = find_numbers_in_text(obj.get("message", ""))
                if any(n < ask_price for n in nums):
                    counter_ok = True
                    break
        checks["messages_include_counter_less_than_ask"] = counter_ok

    # Validate log.md
    if os.path.isfile(log_path):
        checks["log_exists"] = True
        content = read_text(log_path) or ""
        has_ask = False
        if ask_price is not None:
            ask_digits = digits_str(ask_price)
            if ask_digits and ask_digits in content:
                has_ask = True
        has_time_or_log = contains_timestamp_or_log(content)
        if has_ask and has_time_or_log:
            checks["log_has_ask_price_and_timestamp"] = True

    # Final reward: full if all checks True, else 0
    all_pass = all(checks.values())
    result = {"reward": 1.0 if all_pass else 0.0}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()