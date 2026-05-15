import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x

def round3(x: float) -> float:
    # Small epsilon to reduce floating artifacts before rounding
    return round(x + 1e-12, 3)

def count_overlapping_case_insensitive(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    pattern = re.compile(r"(?=(" + re.escape(needle) + r"))", flags=re.IGNORECASE)
    return len(pattern.findall(haystack))

def yaml_unquote(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s

def load_yaml_simple(path: str) -> Dict[str, Any]:
    """
    Very small YAML subset loader for top-level scalars and lists.
    Supports:
      key: value
      key: [a, b, "c d"]
      key:
        - item1
        - "item 2"
    Ignores comments (#...) and blank lines. No nesting beyond one level.
    """
    result: Dict[str, Any] = {}
    if not os.path.isfile(path):
        return result
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return result

    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        # Strip comments not inside quotes (best-effort: split on # first occurrence)
        line = raw.strip()
        if not line or line.startswith("#"):
            i += 1
            continue

        # Match key: value or key:
        m = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key = m.group(1)
        valpart = m.group(2).strip()

        # Inline list
        if valpart.startswith("["):
            # Read until we find a closing ']'
            buffer = valpart
            while not buffer.endswith("]") and i + 1 < n:
                i += 1
                buffer += " " + lines[i].strip()
            # Now parse between [ and ]
            inside = buffer[1:-1].strip()
            items: List[str] = []
            if inside:
                # Split by commas not inside quotes (simple split, quotes will be handled by yaml_unquote)
                parts = [p.strip() for p in inside.split(",")]
                for p in parts:
                    if p:
                        items.append(yaml_unquote(p))
            result[key] = items
            i += 1
            continue

        # Block list or empty value
        if valpart == "" or valpart == "|":
            # Try to read a block list
            j = i + 1
            items: List[str] = []
            consumed = False
            while j < n:
                s = lines[j].strip()
                if not s:
                    j += 1
                    continue
                if s.startswith("- "):
                    items.append(yaml_unquote(s[2:].strip()))
                    consumed = True
                    j += 1
                    continue
                # Stop if next top-level key
                if re.match(r"^[A-Za-z0-9_\-]+\s*:\s*", s):
                    break
                # Non-list content; stop
                break
            if consumed:
                result[key] = items
                i = j
                continue
            else:
                # No list found, set empty string
                result[key] = ""
                i += 1
                continue

        # Scalar
        scalar = yaml_unquote(valpart)
        # Try to cast to float if numeric
        try:
            if scalar.lower() in ("true", "false"):
                val = scalar.lower() == "true"
            else:
                # Attempt numeric
                if re.match(r"^[+-]?(\d+(\.\d*)?|\.\d+)$", scalar):
                    val = float(scalar)
                else:
                    val = scalar
            result[key] = val
        except Exception:
            result[key] = scalar
        i += 1

    return result

def read_jsonl_messages(path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    users: List[Dict[str, Any]] = []
    bots: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            obj = json.loads(s)
            role = obj.get("role")
            text = obj.get("text", "")
            if role == "user":
                users.append({"text": text})
            elif role == "bot":
                bots.append({"text": text})
    return users, bots

def jaccard_tokens(a: str, b: str) -> float:
    a_tokens = set(t for t in re.sub("[^a-z]", " ", a.lower()).split() if t)
    b_tokens = set(t for t in re.sub("[^a-z]", " ", b.lower()).split() if t)
    union = a_tokens | b_tokens
    if not union:
        return 0.0
    inter = a_tokens & b_tokens
    return len(inter) / len(union)

def compute_expected(users: List[Dict[str, Any]], bots: List[Dict[str, Any]], rules: Dict[str, Any]) -> Dict[str, Any]:
    # Defaults
    E_base = float(rules.get("E_base", 20.0))
    E_w_len = float(rules.get("E_w_len", 0.6))
    E_w_q = float(rules.get("E_w_q", 0.4))
    P_weight = float(rules.get("P_weight", 0.2))
    H_weight = float(rules.get("H_weight", 0.1))

    hedges_list = rules.get("hedges", ["maybe", "not sure", "kind of", "sort of", "i guess", "probably"])
    positives_list = rules.get("positives", ["thank", "appreciate", "helpful", "great"])
    commitments_list = rules.get("commitments", ["let's do it", "sign us up", "i want to buy", "go ahead", "yes"])
    objections_list = rules.get("objections", ["but", "however", "expensive", "too much"])
    urgency_list = rules.get("urgency", ["today", "now", "asap"])

    # Ensure lists are lists of strings
    def to_str_list(x: Any) -> List[str]:
        if isinstance(x, list):
            return [str(i) for i in x]
        if isinstance(x, str) and x.strip():
            return [x]
        return []

    hedges_list = to_str_list(hedges_list)
    positives_list = to_str_list(positives_list)
    commitments_list = to_str_list(commitments_list)
    objections_list = to_str_list(objections_list)
    urgency_list = to_str_list(urgency_list)

    # Engagement
    n_users = len(users)
    if n_users > 0:
        word_counts = [len((u.get("text") or "").split()) for u in users]
        avg_words = sum(word_counts) / n_users
    else:
        avg_words = 0.0
    q_total = sum((u.get("text") or "").count("?") for u in users)
    question_density = q_total / max(1, n_users)
    engagement_raw = (avg_words / E_base) * E_w_len + question_density * E_w_q
    engagement = clamp(engagement_raw, 0.0, 1.0)

    # Trust
    hedges_count = 0
    positives_count = 0
    for u in users:
        txt = u.get("text") or ""
        for token in hedges_list:
            hedges_count += count_overlapping_case_insensitive(txt, token)
        for token in positives_list:
            positives_count += count_overlapping_case_insensitive(txt, token)
    trust_raw = 0.5 + P_weight * positives_count - H_weight * hedges_count
    trust = clamp(trust_raw, 0.0, 1.0)

    # Decision presence flags
    def any_present(tokens: List[str]) -> bool:
        for u in users:
            txt = (u.get("text") or "").lower()
            for t in tokens:
                if t and t.lower() in txt:
                    return True
        return False

    commit_present = 1 if any_present(commitments_list) else 0
    objection_present = 1 if any_present(objections_list) else 0
    urgency_present = 1 if any_present(urgency_list) else 0

    decision_raw = 0.2 + 0.5 * commit_present - 0.1 * objection_present + 0.2 * urgency_present
    decision = clamp(decision_raw, 0.0, 1.0)

    # Style match
    if users and bots:
        last_user = users[-1].get("text") or ""
        last_bot = bots[-1].get("text") or ""
        base_jaccard = jaccard_tokens(last_bot, last_user)
        bot_excl = last_bot.count("!")
        user_excl = last_user.count("!")
        if (bot_excl > 0 and user_excl > 0) or (bot_excl == 0 and user_excl == 0):
            style_match_raw = min(1.0, base_jaccard + 0.1)
        else:
            style_match_raw = base_jaccard
        style_match = clamp(style_match_raw, 0.0, 1.0)
    else:
        style_match = 0.0

    # Composite and resonance level
    composite_raw = 0.25 * engagement + 0.30 * trust + 0.30 * decision + 0.15 * style_match
    composite = clamp(composite_raw, 0.0, 1.0)
    if composite >= 0.8:
        resonance_level = "PEAK_RESONANCE"
    elif composite >= 0.6:
        resonance_level = "HIGH_RESONANCE"
    elif composite >= 0.4:
        resonance_level = "BUILDING"
    elif composite >= 0.2:
        resonance_level = "WEAK"
    else:
        resonance_level = "NO_RESONANCE"

    # Recommendation mapping
    if decision >= 0.7 and trust >= 0.5:
        rec_style = "AMPLIFY"
        rec_timing = "NOW"
        rec_urgency = "HIGH"
        rec_action = "User is ready to close. Present the offer now with a clear next step."
    elif engagement < 0.4:
        rec_style = "MIRROR"
        rec_timing = "BUILD_MORE"
        rec_urgency = "LOW"
        rec_action = "Engagement is weak. Ask one focused question to re-engage."
    elif trust < 0.4:
        rec_style = "SOFTEN"
        rec_timing = "NEXT_TURN"
        rec_urgency = "MEDIUM"
        rec_action = "Trust is low. Lead with empathy and address the latest concern directly."
    else:
        rec_style = "MIRROR"
        rec_timing = "NEXT_TURN"
        rec_urgency = "MEDIUM"
        rec_action = "Momentum is building. Ask a focused question and offer concise value."

    # Yield prediction
    conversion_prob_raw = 0.5 * decision + 0.3 * trust + 0.2 * engagement
    if objection_present == 1:
        conversion_prob_raw -= 0.1
    conversion_probability = clamp(conversion_prob_raw, 0.0, 1.0)

    if decision >= 0.75:
        estimated_value = "high"
    elif decision >= 0.5:
        estimated_value = "medium"
    else:
        estimated_value = "low"

    if decision >= 0.7:
        optimal_turns_remaining = 0
    elif decision >= 0.5:
        optimal_turns_remaining = 1
    else:
        optimal_turns_remaining = 2

    should_close = (decision >= 0.65 and trust >= 0.5)
    yield_action = "Close now" if should_close else "Build more."

    expected = {
        "frequencies": {
            "engagement": round3(engagement),
            "trust": round3(trust),
            "decision": round3(decision),
            "style_match": round3(style_match),
        },
        "composite_score": round3(composite),
        "resonance_level": resonance_level,
        "recommendation": {
            "style": rec_style,
            "timing": rec_timing,
            "urgency": rec_urgency,
            "action": rec_action,
        },
        "yield": {
            "conversion_probability": round3(conversion_probability),
            "estimated_value": estimated_value,
            "optimal_turns_remaining": int(optimal_turns_remaining),
            "should_close": bool(should_close),
            "action": yield_action,
        },
    }
    return expected

def validate_schema(report: Dict[str, Any]) -> bool:
    # Exact top-level keys
    top_expected = {"frequencies", "composite_score", "resonance_level", "recommendation", "yield"}
    if set(report.keys()) != top_expected:
        return False

    # Frequencies
    freqs = report.get("frequencies")
    if not isinstance(freqs, dict):
        return False
    if set(freqs.keys()) != {"engagement", "trust", "decision", "style_match"}:
        return False

    # Recommendation
    rec = report.get("recommendation")
    if not isinstance(rec, dict):
        return False
    if set(rec.keys()) != {"style", "timing", "urgency", "action"}:
        return False

    # Yield
    yld = report.get("yield")
    if not isinstance(yld, dict):
        return False
    if set(yld.keys()) != {"conversion_probability", "estimated_value", "optimal_turns_remaining", "should_close", "action"}:
        return False

    # Types: basic checks
    try:
        float(report["composite_score"])
        for k in ["engagement", "trust", "decision", "style_match"]:
            float(freqs[k])
        if not isinstance(report["resonance_level"], str):
            return False
        for k in ["style", "timing", "urgency", "action"]:
            if not isinstance(rec[k], str):
                return False
        float(yld["conversion_probability"])
        if not isinstance(yld["estimated_value"], str):
            return False
        if not isinstance(yld["optimal_turns_remaining"], int):
            return False
        if not isinstance(yld["should_close"], bool):
            return False
        if not isinstance(yld["action"], str):
            return False
    except Exception:
        return False

    return True

def close_enough(a: float, b: float, tol: float = 1e-3) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    output_path = os.path.join(output_dir, "resonance_report.json")
    transcript_path = os.path.join(input_dir, "transcript.jsonl")
    rules_path = os.path.join(input_dir, "rules.yaml")

    checks: Dict[str, bool] = {
        "output_exists": False,
        "schema_valid": False,
        "frequencies_match": False,
        "composite_match": False,
        "level_match": False,
        "recommendation_match": False,
        "yield_match": False,
    }

    # No-op baseline: if file missing, reward remains 0.0
    if not os.path.isfile(output_path):
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    checks["output_exists"] = True

    # Load produced report
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception:
        # Cannot parse JSON
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    # Validate schema strictly
    if validate_schema(report):
        checks["schema_valid"] = True

    # Compute expected only if we can read inputs
    try:
        users, bots = read_jsonl_messages(transcript_path)
        rules = load_yaml_simple(rules_path)
        expected = compute_expected(users, bots, rules)
    except Exception:
        # If inputs cannot be read/parsed, we cannot award matches
        result = {"reward": 1.0 * sum(1 for v in checks.values() if v) / len(checks)}
        result.update(checks)
        print(json.dumps(result))
        return

    # Compare frequencies
    try:
        ef = expected["frequencies"]
        rf = report["frequencies"]
        freq_ok = all(
            close_enough(rf[k], ef[k]) for k in ["engagement", "trust", "decision", "style_match"]
        )
        checks["frequencies_match"] = freq_ok
    except Exception:
        pass

    # Composite
    try:
        checks["composite_match"] = close_enough(report["composite_score"], expected["composite_score"])
    except Exception:
        pass

    # Resonance level
    try:
        checks["level_match"] = (report["resonance_level"] == expected["resonance_level"])
    except Exception:
        pass

    # Recommendation
    try:
        rr = report["recommendation"]
        er = expected["recommendation"]
        rec_ok = (
            rr.get("style") == er.get("style")
            and rr.get("timing") == er.get("timing")
            and rr.get("urgency") == er.get("urgency")
            and rr.get("action") == er.get("action")
        )
        checks["recommendation_match"] = rec_ok
    except Exception:
        pass

    # Yield
    try:
        ry = report["yield"]
        ey = expected["yield"]
        y_ok = (
            close_enough(ry.get("conversion_probability"), ey.get("conversion_probability"))
            and ry.get("estimated_value") == ey.get("estimated_value")
            and isinstance(ry.get("optimal_turns_remaining"), int)
            and ry.get("optimal_turns_remaining") == ey.get("optimal_turns_remaining")
            and isinstance(ry.get("should_close"), bool)
            and ry.get("should_close") == ey.get("should_close")
            and ry.get("action") == ey.get("action")
        )
        checks["yield_match"] = y_ok
    except Exception:
        pass

    # Compute reward as ratio of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()