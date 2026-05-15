import json
import os
import sys
from typing import Any, Dict, List

def load_jsonl(path: str) -> List[Dict[str, Any]]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            items.append(json.loads(s))
    return items

def case_insensitive_contains(haystack: str, needles: List[str]) -> int:
    """Return count of occurrences of any needles in haystack (case-insensitive substring matches)."""
    h = haystack.lower()
    count = 0
    for n in needles:
        if not n:
            continue
        nlow = n.lower()
        # Count non-overlapping occurrences
        idx = 0
        while True:
            idx = h.find(nlow, idx)
            if idx == -1:
                break
            count += 1
            idx += len(nlow) if len(nlow) > 0 else 1
    return count

def mood_intent_from_rules(last_msg: str, rules: Dict[str, Any]) -> Dict[str, Any]:
    # Flexible extraction of mood rules
    mood_rules = rules.get("mood_rules") or rules.get("moods") or {}
    categories = mood_rules.get("categories") or mood_rules.get("mood_categories") or {}
    confidence_cfg = mood_rules.get("confidence") or {}
    base_conf = float(confidence_cfg.get("base", 0.6))
    incr = float(confidence_cfg.get("increment_per_match", 0.1))
    max_conf = float(confidence_cfg.get("max", 0.9))
    neutral_conf = float(confidence_cfg.get("neutral_confidence", 0.5))

    # Emotions mapping can be inside categories or separate
    emotions_map = {}
    for cat_name, cat in categories.items():
        if isinstance(cat, dict):
            em = cat.get("emotions") or cat.get("mood_emotions")
            if isinstance(em, list):
                emotions_map[cat_name] = em

    # Keywords per category
    cat_keywords = {}
    for cat_name, cat in categories.items():
        if isinstance(cat, dict):
            keys = cat.get("any_contains") or cat.get("keywords") or []
            if isinstance(keys, list):
                cat_keywords[cat_name] = keys

    msg = last_msg or ""
    # Compute matches per category
    best_cat = None
    best_count = 0
    for cat_name, keys in cat_keywords.items():
        cnt = case_insensitive_contains(msg, keys)
        if cnt > 0:
            if cnt > best_count:
                best_count = cnt
                best_cat = cat_name
            elif cnt == best_count and best_cat is None:
                best_cat = cat_name

    if best_cat is None:
        mood_name = "neutral"
        confidence = neutral_conf
        emotions = []
    else:
        mood_name = best_cat
        confidence = min(max_conf, base_conf + incr * best_count)
        emotions = emotions_map.get(mood_name, [])

    # Intent rules
    intent_rules = rules.get("intent_rules") or {}
    # Precedence: question → command → casual → default
    # Question: match if any_contains anywhere
    # Command: match if message starts with any of starts_with (case-insensitive)
    # Casual: any_contains anywhere
    # Default: otherwise use default
    msg_strip = msg.lstrip()
    msg_low = msg_strip.lower()
    def contains_any(substrs: List[str]) -> bool:
        if not isinstance(substrs, list):
            return False
        for s in substrs:
            if s and s.lower() in (last_msg or "").lower():
                return True
        return False

    def starts_with_any(prefixes: List[str]) -> bool:
        if not isinstance(prefixes, list):
            return False
        for p in prefixes:
            if not p:
                continue
            if msg_low.startswith(p.lower()):
                return True
        return False

    intent = None
    q = intent_rules.get("question", {})
    if contains_any(q.get("any_contains") or q.get("contains") or []):
        intent = "question"
    else:
        c = intent_rules.get("command", {})
        if starts_with_any(c.get("starts_with") or c.get("prefixes") or []):
            intent = "command"
        else:
            ca = intent_rules.get("casual", {})
            if contains_any(ca.get("any_contains") or ca.get("contains") or []):
                intent = "casual"
            else:
                intent = intent_rules.get("default", "casual")

    return {
        "mood": mood_name,
        "confidence": confidence,
        "emotions": emotions,
        "intent": intent
    }

def approx_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False)
    checks: Dict[str, bool] = {}
    users_expected_order = ["u_alex", "u_bria", "u_cara"]
    # Global artifact checks
    checks["contexts_exists"] = False
    checks["contexts_three_lines"] = False
    checks["contexts_parse_ok"] = False
    checks["contexts_order_ok"] = False
    checks["summary_exists"] = False
    checks["summary_lines_ok"] = False
    checks["summary_content_ok"] = False

    # Per-user checks init
    for uid in users_expected_order:
        checks[f"{uid}_profile_name_ok"] = False
        checks[f"{uid}_comm_style_ok"] = False
        checks[f"{uid}_interests_ok"] = False
        checks[f"{uid}_prefs_ok"] = False
        checks[f"{uid}_mood_ok"] = False
        checks[f"{uid}_intent_ok"] = False
        checks[f"{uid}_personality_ok"] = False
        checks[f"{uid}_suggestions_ok"] = False
        checks[f"{uid}_memories_required_ok"] = False

    # Load inputs
    users_path = os.path.join(input_dir, "users.jsonl")
    rules_path = os.path.join(input_dir, "detection_rules.json")
    users_data = {}
    try:
        users_list = load_jsonl(users_path)
        for u in users_list:
            if isinstance(u, dict) and "user_id" in u:
                users_data[u["user_id"]] = u
    except Exception:
        users_list = []

    try:
        with open(rules_path, "r", encoding="utf-8") as rf:
            rules = json.load(rf)
    except Exception:
        rules = {}

    # Expected communication styles map
    comm_map = {"u_alex": "concise", "u_bria": "detailed", "u_cara": "friendly"}

    # Expected interests and preferences substrings
    interests_require = {
        "u_alex": ["sci-fi", "hiking"],
        "u_bria": ["long-form", "coffee"],  # "long-form" should cover "long-form writing"
        "u_cara": ["gardening", "mystery novels"],
    }
    prefs_require = {
        "u_alex": ["concise"],
        "u_bria": ["detailed steps"],
        "u_cara": ["friendly tone"],
    }

    # Load output contexts
    contexts_path = os.path.join(output_dir, "contexts.jsonl")
    contexts_lines: List[str] = []
    contexts: List[Dict[str, Any]] = []
    if os.path.isfile(contexts_path):
        checks["contexts_exists"] = True
        try:
            with open(contexts_path, "r", encoding="utf-8") as f:
                contexts_lines = f.read().splitlines()
            # Must be exactly 3 non-empty lines
            nonempty = [ln for ln in contexts_lines if ln.strip() != ""]
            if len(nonempty) == 3 and len(contexts_lines) == 3:
                checks["contexts_three_lines"] = True
            # Parse each line
            ok_parse = True
            contexts = []
            for ln in contexts_lines:
                s = ln.strip()
                if not s:
                    ok_parse = False
                    break
                try:
                    obj = json.loads(s)
                    contexts.append(obj)
                except Exception:
                    ok_parse = False
                    break
            if ok_parse:
                checks["contexts_parse_ok"] = True
            # Check order
            if ok_parse and len(contexts) == 3:
                uid_order = [c.get("user_id") for c in contexts]
                if uid_order == users_expected_order:
                    checks["contexts_order_ok"] = True
        except Exception:
            pass

    # Per-user validations
    # Build quick map for contexts
    contexts_by_uid: Dict[str, Dict[str, Any]] = {}
    if checks["contexts_parse_ok"]:
        for c in contexts:
            if isinstance(c, dict) and "user_id" in c:
                contexts_by_uid[c["user_id"]] = c

    # Compute expected mood/intent using rules applied to last message
    expected_mood_intent: Dict[str, Dict[str, Any]] = {}
    for uid in users_expected_order:
        u = users_data.get(uid, {})
        msgs = u.get("messages") or []
        last_msg_text = ""
        if isinstance(msgs, list) and len(msgs) > 0 and isinstance(msgs[-1], dict):
            last_msg_text = msgs[-1].get("text", "")
        expected_mood_intent[uid] = mood_intent_from_rules(last_msg_text, rules)

    allowed_memory_types = {"preference", "interest", "fact"}
    required_indices = {
        "u_alex": [0, 1, 2],
        "u_bria": [0, 1],
        "u_cara": [0, 1, 2],
    }

    for uid in users_expected_order:
        ctx = contexts_by_uid.get(uid)
        if not isinstance(ctx, dict):
            continue  # leave checks as False

        # user_profile name
        up = ctx.get("user_profile", {})
        name_ok = False
        if isinstance(up, dict):
            expected_name = users_data.get(uid, {}).get("name")
            if expected_name is not None and up.get("name") == expected_name:
                name_ok = True
        checks[f"{uid}_profile_name_ok"] = name_ok

        # communication style
        comm_ok = isinstance(up, dict) and up.get("communication_style") == comm_map.get(uid)
        checks[f"{uid}_comm_style_ok"] = comm_ok

        # interests
        interests_ok = False
        interests = up.get("interests") if isinstance(up, dict) else None
        if isinstance(interests, list):
            required = interests_require.get(uid, [])
            found_all = True
            for req in required:
                present = any(isinstance(x, str) and (req.lower() in x.lower()) for x in interests)
                if not present:
                    found_all = False
                    break
            interests_ok = found_all
        checks[f"{uid}_interests_ok"] = interests_ok

        # preferences
        prefs_ok = False
        prefs = up.get("preferences") if isinstance(up, dict) else None
        if isinstance(prefs, list):
            reqs = prefs_require.get(uid, [])
            found_all = True
            for req in reqs:
                present = any(isinstance(x, str) and (req.lower() in x.lower()) for x in prefs)
                if not present:
                    found_all = False
                    break
            prefs_ok = found_all
        checks[f"{uid}_prefs_ok"] = prefs_ok

        # mood
        mood_obj = ctx.get("mood", {})
        mood_expected = expected_mood_intent.get(uid, {})
        mood_ok = False
        if isinstance(mood_obj, dict):
            m_name = mood_obj.get("mood")
            m_conf = mood_obj.get("confidence")
            m_em = mood_obj.get("emotions")
            e_name = mood_expected.get("mood")
            e_conf = mood_expected.get("confidence")
            e_em = mood_expected.get("emotions") if isinstance(mood_expected.get("emotions"), list) else []
            # If rules do not define emotions for neutral, default to []
            if e_name == "neutral" and not e_em:
                e_em = []
            # Compare
            if m_name == e_name and approx_equal(m_conf, e_conf) and isinstance(m_em, list) and m_em == e_em:
                mood_ok = True
        checks[f"{uid}_mood_ok"] = mood_ok

        # intent
        intent_ok = ctx.get("intent") == mood_expected.get("intent")
        checks[f"{uid}_intent_ok"] = intent_ok

        # personality substring
        personality_ok = False
        pers = ctx.get("personality")
        if isinstance(pers, str) and "humor, empathy, curiosity, creativity, helpfulness, honesty" in pers:
            personality_ok = True
        checks[f"{uid}_personality_ok"] = personality_ok

        # suggested_responses
        sugg_ok = False
        sugg = ctx.get("suggested_responses")
        if isinstance(sugg, list) and len(sugg) == 3 and all(isinstance(x, str) for x in sugg):
            uname = users_data.get(uid, {}).get("name", "")
            has_name = any(uname and (uname.lower() in s.lower()) for s in sugg)
            # At least one suggestion mentions one of the user's interests (required phrases)
            interest_phrases = interests_require.get(uid, [])
            has_interest = any(
                any(phr.lower() in s.lower() for phr in interest_phrases) for s in sugg
            )
            if has_name and has_interest:
                sugg_ok = True
        checks[f"{uid}_suggestions_ok"] = sugg_ok

        # memories
        mem_ok = False
        mems = ctx.get("memories")
        if isinstance(mems, list):
            req_idx = required_indices.get(uid, [])
            u = users_data.get(uid, {})
            msgs = u.get("messages") or []
            all_present = True
            for ridx in req_idx:
                # Verify bounds
                if not (isinstance(msgs, list) and 0 <= ridx < len(msgs) and isinstance(msgs[ridx], dict)):
                    all_present = False
                    break
                target_text = msgs[ridx].get("text")
                target_ts = msgs[ridx].get("timestamp")
                found = False
                for m in mems:
                    if not isinstance(m, dict):
                        continue
                    if m.get("source_message_index") != ridx:
                        continue
                    if m.get("content") != target_text:
                        continue
                    if m.get("timestamp") != target_ts:
                        continue
                    if m.get("memory_type") not in allowed_memory_types:
                        continue
                    found = True
                    break
                if not found:
                    all_present = False
                    break
            mem_ok = all_present
        checks[f"{uid}_memories_required_ok"] = mem_ok

    # Summary checks
    summary_path = os.path.join(output_dir, "summary.md")
    summary_lines: List[str] = []
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                raw = f.read()
            # Preserve lines as splitlines (does not include trailing newline)
            summary_lines = raw.splitlines()
            if len(summary_lines) == 4:
                checks["summary_lines_ok"] = True

            # Validate content if contexts parsed
            if checks["contexts_parse_ok"] and len(summary_lines) == 4:
                # Compute memory counts from contexts
                mem_counts = {}
                for uid in users_expected_order:
                    ctx = contexts_by_uid.get(uid, {})
                    mem_counts[uid] = len(ctx.get("memories", [])) if isinstance(ctx.get("memories"), list) else 0

                line1 = "Context Summary"
                line2 = f"u_alex: intent={expected_mood_intent.get('u_alex', {}).get('intent')}, mood={expected_mood_intent.get('u_alex', {}).get('mood')}, memories={mem_counts.get('u_alex', 0)}"
                line3 = f"u_bria: intent={expected_mood_intent.get('u_bria', {}).get('intent')}, mood={expected_mood_intent.get('u_bria', {}).get('mood')}, memories={mem_counts.get('u_bria', 0)}"
                line4 = f"u_cara: intent={expected_mood_intent.get('u_cara', {}).get('intent')}, mood={expected_mood_intent.get('u_cara', {}).get('mood')}, memories={mem_counts.get('u_cara', 0)}"
                if (
                    summary_lines[0] == line1
                    and summary_lines[1] == line2
                    and summary_lines[2] == line3
                    and summary_lines[3] == line4
                ):
                    checks["summary_content_ok"] = True
        except Exception:
            pass

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # Enforce no-op baseline: if required artifacts missing, reward must be 0.0
    if not checks["contexts_exists"] or not checks["summary_exists"]:
        reward = 0.0

    # Print final JSON
    final_obj = {"reward": reward}
    final_obj.update(checks)
    print(json.dumps(final_obj))

if __name__ == "__main__":
    main()