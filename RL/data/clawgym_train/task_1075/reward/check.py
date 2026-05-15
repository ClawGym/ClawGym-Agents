import json
import os
import sys
from datetime import datetime

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    ts = s.strip()
    # Accept trailing 'Z'
    ts = ts.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(ts)
        return True
    except Exception:
        return False

def extract_names_from_brief(brief_text: str):
    """
    Extract product/feature names from brief.md.
    Priority:
    1) Lines starting with 'Product:' or 'Feature:' (case-insensitive)
    2) First non-generic markdown heading (# ...), skipping generic titles
    3) Any capitalized phrase (2+ words) as a last resort
    Returns a list of unique candidate names (non-empty).
    """
    if not brief_text:
        return []

    lines = brief_text.splitlines()
    names = []

    # 1) Lines starting with Product:/Feature:
    import re
    for line in lines:
        m = re.match(r'^\s*(Product|Feature)\s*:\s*(.+)$', line, flags=re.IGNORECASE)
        if m:
            val = m.group(2).strip().strip("#*:- ").strip()
            # Remove inline markdown formatting
            val = re.sub(r'[_*`]+', '', val)
            # Truncate overly long
            if val:
                names.append(val[:120])

    # 2) First non-generic heading
    if not names:
        generic = {"brief", "overview", "background", "constraints", "audience", "product brief", "feature brief"}
        for line in lines:
            mh = re.match(r'^\s*#{1,6}\s+(.+)$', line)
            if mh:
                title = mh.group(1).strip()
                title_clean = re.sub(r'[_*`]+', '', title)
                if title_clean and title_clean.strip().lower() not in generic:
                    names.append(title_clean[:120])
                    break

    # 3) Capitalized phrase fallback (2+ words)
    if not names:
        m = re.search(r'([A-Z][A-Za-z0-9\-\_]+(?:\s+[A-Z][A-Za-z0-9\-\_]+)+)', brief_text)
        if m:
            names.append(m.group(1)[:120])

    # Deduplicate while preserving order and filter trivially short values
    seen = set()
    out = []
    for n in names:
        n2 = n.strip()
        if len(n2) >= 2 and n2.lower() not in seen:
            out.append(n2)
            seen.add(n2.lower())
    return out

def contains_any_substring(text: str, substrings):
    t = text.lower()
    for s in substrings:
        if s and s.lower() in t:
            return True
    return False

def recompute_readiness(checklist: dict):
    """
    Returns (expected, ok), where expected is the expected structure with scores/decisions.
    """
    def cat_score(items):
        total_w = 0.0
        earned = 0.0
        blockers = []
        for it in items:
            status = str(it.get("status", "not_started")).strip().lower()
            weight = it.get("weight", 1)
            try:
                w = float(weight)
            except Exception:
                w = 1.0
            sw = 0.0
            if status == "done":
                sw = 1.0
            elif status == "partial":
                sw = 0.5
            elif status == "not_started":
                sw = 0.0
            total_w += w
            earned += sw * w
            if status == "not_started":
                try:
                    if w >= 3:
                        blockers.append(str(it.get("item", "")).strip() or str(it))
                except Exception:
                    pass
        score = int(round(((earned / total_w) * 100))) if total_w > 0 else 0
        return score, blockers

    cats = {}
    blockers_all = []

    for cat in ["product", "marketing", "technical"]:
        items = checklist.get(cat, [])
        if not isinstance(items, list):
            items = []
        score, blockers = cat_score(items)
        cats[cat] = score
        blockers_all.extend(blockers)

    overall = int(round(sum(cats.values()) / 3.0))

    # Launch decision
    if blockers_all:
        decision = f"⛔  NOT READY — {len(blockers_all)} blocker(s) must be resolved before launch."
    elif overall >= 80:
        decision = "✅  LAUNCH READY — all categories are in good shape."
    elif overall >= 60:
        decision = "🟡  CONDITIONAL — address partial items but launch is defensible."
    elif overall >= 40:
        decision = "🚧  CAUTION — significant gaps; soft launch / waitlist recommended."
    else:
        decision = "🔴  NOT READY — major preparation required across multiple areas."

    expected = {
        "overall": {
            "score": overall,
            "launch_decision": decision,
            "blockers": sorted(blockers_all),
        },
        "categories": {
            "product": {"score": cats["product"]},
            "marketing": {"score": cats["marketing"]},
            "technical": {"score": cats["technical"]},
        }
    }
    return expected

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # agent-chat.json checks
        "has_agent_chat_file": False,
        "agent_chat_valid_schema": False,
        "agent_chat_min_counts": False,
        "agent_chat_marketing_question": False,
        "agent_chat_mentions_product_hunt": False,
        "agent_chat_mentions_product_name": False,
        # launch_plan.md checks
        "has_launch_plan": False,
        "launch_plan_orb_labels": False,
        "launch_plan_phase_count": False,
        "launch_plan_launch_day": False,
        "launch_plan_mentions_product_name": False,
        # readiness.json checks
        "has_readiness_json": False,
        "readiness_scores_match": False,
        "readiness_blockers_match": False,
        "readiness_launch_decision_match": False,
        # chat_transcript.txt checks
        "has_transcript": False,
        "transcript_prefixes_present": False,
        "transcript_mentions_product_name": False,
        "transcript_line_count_ok": False,
    }

    # Load inputs
    brief_path = os.path.join(input_dir, "brief.md")
    checklist_path = os.path.join(input_dir, "checklist.json")
    brief_text = read_text(brief_path)
    product_names = extract_names_from_brief(brief_text)
    # If multiple names, allow any
    # Also consider splitting on separators within names to get more chances
    extra_names = []
    for n in product_names:
        parts = [p.strip() for p in n.replace("|", " ").replace("/", " ").split("  ") if p.strip()]
        for p in parts:
            if p.lower() != n.lower() and len(p) >= 2:
                extra_names.append(p)
    product_name_candidates = list(dict.fromkeys(product_names + extra_names))

    # 1) Validate output/agent-chat.json
    chat_path = os.path.join(output_dir, "agent-chat.json")
    chat = load_json(chat_path)
    if isinstance(chat, dict):
        checks["has_agent_chat_file"] = True
        messages = chat.get("messages")
        if isinstance(messages, list) and len(messages) >= 1:
            # schema validation
            valid_schema = True
            count_planner = 0
            count_marketing = 0
            has_question_from_marketing = False
            mentions_product_hunt = False
            mentions_product_name = False

            for m in messages:
                if not isinstance(m, dict):
                    valid_schema = False
                    break
                # Keys
                if "id" not in m or "sender" not in m or "receiver" not in m or "message" not in m or "timestamp" not in m:
                    valid_schema = False
                    break
                # Types/values
                if not isinstance(m["id"], int):
                    valid_schema = False
                    break
                if m["sender"] not in ("planner-bot", "marketing-bot"):
                    valid_schema = False
                    break
                if m["receiver"] not in ("planner-bot", "marketing-bot", "broadcast"):
                    valid_schema = False
                    break
                if not isinstance(m["message"], str) or not m["message"].strip():
                    valid_schema = False
                    break
                if not is_iso8601(m["timestamp"]):
                    valid_schema = False
                    break

                # counts and content checks
                if m["sender"] == "planner-bot":
                    count_planner += 1
                elif m["sender"] == "marketing-bot":
                    count_marketing += 1
                    if "?" in m["message"]:
                        has_question_from_marketing = True

                if "product hunt" in m["message"].lower():
                    mentions_product_hunt = True

                if product_name_candidates:
                    if contains_any_substring(m["message"], product_name_candidates):
                        mentions_product_name = True

            if valid_schema:
                checks["agent_chat_valid_schema"] = True

            if len(messages) >= 5 and count_planner >= 3 and count_marketing >= 2:
                checks["agent_chat_min_counts"] = True

            if has_question_from_marketing:
                checks["agent_chat_marketing_question"] = True

            if mentions_product_hunt:
                checks["agent_chat_mentions_product_hunt"] = True

            # Only mark as True if we actually have a candidate name; if we cannot extract, keep False
            if product_name_candidates and mentions_product_name:
                checks["agent_chat_mentions_product_name"] = True

    # 2) Validate output/launch_plan.md
    launch_plan_path = os.path.join(output_dir, "launch_plan.md")
    lp_text = read_text(launch_plan_path)
    if lp_text:
        checks["has_launch_plan"] = True
        low = lp_text.lower()
        if ("owned" in low) and ("rented" in low) and ("borrowed" in low):
            checks["launch_plan_orb_labels"] = True
        if low.count("phase") >= 3:
            checks["launch_plan_phase_count"] = True
        if "launch day" in low:
            checks["launch_plan_launch_day"] = True
        if product_name_candidates and contains_any_substring(lp_text, product_name_candidates):
            checks["launch_plan_mentions_product_name"] = True

    # 3) Validate output/readiness.json against input/checklist.json
    readiness_out_path = os.path.join(output_dir, "readiness.json")
    readiness_out = load_json(readiness_out_path)
    if isinstance(readiness_out, dict):
        checks["has_readiness_json"] = True
        checklist = load_json(checklist_path) or {}
        expected = recompute_readiness(checklist)

        # Compare category scores
        try:
            out_cats = readiness_out.get("categories", {})
            cat_ok = (
                isinstance(out_cats, dict)
                and out_cats.get("product", {}).get("score") == expected["categories"]["product"]["score"]
                and out_cats.get("marketing", {}).get("score") == expected["categories"]["marketing"]["score"]
                and out_cats.get("technical", {}).get("score") == expected["categories"]["technical"]["score"]
            )
            if cat_ok:
                checks["readiness_scores_match"] = True
        except Exception:
            pass

        # Compare blockers set (order-insensitive)
        try:
            out_blockers = readiness_out.get("overall", {}).get("blockers", [])
            if isinstance(out_blockers, list):
                out_blockers_sorted = sorted([str(x) for x in out_blockers])
                if out_blockers_sorted == expected["overall"]["blockers"]:
                    checks["readiness_blockers_match"] = True
        except Exception:
            pass

        # Compare overall score and decision
        try:
            out_overall_score = readiness_out.get("overall", {}).get("score", None)
            out_decision = readiness_out.get("overall", {}).get("launch_decision", None)
            if out_overall_score == expected["overall"]["score"]:
                if out_decision == expected["overall"]["launch_decision"]:
                    checks["readiness_launch_decision_match"] = True
        except Exception:
            pass

    # 4) Validate output/chat_transcript.txt
    transcript_path = os.path.join(output_dir, "chat_transcript.txt")
    transcript_text = read_text(transcript_path)
    if transcript_text:
        checks["has_transcript"] = True
        lines = [ln for ln in transcript_text.splitlines() if ln.strip() != ""]
        # prefixes present
        has_planner_line = any(ln.startswith("planner-bot:") for ln in lines)
        has_marketing_line = any(ln.startswith("marketing-bot:") for ln in lines)
        # all non-empty lines must start with a sender prefix followed by colon
        all_prefixed = all(ln.startswith("planner-bot:") or ln.startswith("marketing-bot:") for ln in lines) if lines else False
        if has_planner_line and has_marketing_line and all_prefixed:
            checks["transcript_prefixes_present"] = True

        # mentions product name
        if product_name_candidates and contains_any_substring(transcript_text, product_name_candidates):
            checks["transcript_mentions_product_name"] = True

        # line count >= messages length
        chat = load_json(chat_path)
        msg_count = 0
        if isinstance(chat, dict) and isinstance(chat.get("messages"), list):
            msg_count = len(chat["messages"])
        if len(lines) >= msg_count and msg_count > 0:
            checks["transcript_line_count_ok"] = True

    # Compute reward
    check_values = list(checks.values())
    passed = sum(1 for v in check_values if v)
    total = len(check_values)

    # Baseline: if output dir missing or none of required artifacts present, reward must be 0.0
    required_files = [
        os.path.join(output_dir, "agent-chat.json"),
        os.path.join(output_dir, "launch_plan.md"),
        os.path.join(output_dir, "readiness.json"),
        os.path.join(output_dir, "chat_transcript.txt"),
    ]
    any_required_exists = any(os.path.isfile(p) for p in required_files)
    if not os.path.isdir(output_dir) or not any_required_exists:
        reward = 0.0
    else:
        reward = passed / total if total > 0 else 0.0

    # Print result JSON (single line)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()