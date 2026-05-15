import json
import os
import re
import sys
from typing import Any, Dict, List

def load_json_safe(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_safe(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def extract_items_generic(obj: Any, list_keys: List[str]) -> List[Any]:
    # Accept either a list of dicts or a dict with a known list key.
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in list_keys:
            if k in obj and isinstance(obj[k], list):
                return obj[k]
        # Fallback: values of dict if they look like dict items
        vals = [v for v in obj.values() if isinstance(v, dict)]
        if vals:
            return vals
    return []

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

checks: Dict[str, bool] = {
    # Mindshare
    "mindshare_entities_file_exists": False,
    "mindshare_entities_has_required_fields_for_all": False,
    "mindshare_narratives_file_exists": False,
    "mindshare_narratives_has_required_fields_for_all": False,
    "mindshare_summary_exists": False,
    "mindshare_summary_mentions_entities_and_narratives": False,
    # War room
    "war_room_report_exists": False,
    "war_room_has_all_sections": False,
    "war_room_has_ruling_line": False,
    "war_room_includes_if_x_fails_phrase": False,
    # Signals
    "signals_file_exists": False,
    "signals_entries_have_required_fields_if_nonempty": False,
    "signals_market_summary_exists": False,
    "signals_disclaimer_exists": False,
    "signals_disclaimer_exact_text": False,
    # Marketplace manifest
    "marketplace_manifest_exists": False,
    "marketplace_manifest_fields_valid": False,
    # Strategy memo
    "strategy_memo_exists": False,
    "strategy_memo_word_count_valid": False,
    "strategy_memo_mentions_mindshare_and_signals": False,
    "strategy_memo_mentions_pivot_portfolio": False,
}

# Mindshare entities.json
entities_path = os.path.join(output_dir, "mindshare", "entities.json")
if os.path.isfile(entities_path):
    checks["mindshare_entities_file_exists"] = True
    entities_json = load_json_safe(entities_path)
    items = extract_items_generic(entities_json, ["entities", "results"])
    if isinstance(items, list) and len(items) > 0:
        required_keys = {"current", "high_12m", "low_12m", "avg_12m", "rank_interpretation", "weekly_averages"}
        all_ok = True
        for it in items:
            if not isinstance(it, dict):
                all_ok = False
                break
            if not required_keys.issubset(set(it.keys())):
                all_ok = False
                break
            if not (is_number(it["current"]) and is_number(it["high_12m"]) and is_number(it["low_12m"]) and is_number(it["avg_12m"])):
                all_ok = False
                break
            wa = it["weekly_averages"]
            if not isinstance(wa, list) or len(wa) == 0 or not all(is_number(x) for x in wa):
                all_ok = False
                break
            ri = str(it["rank_interpretation"]).lower()
            if not any(cat in ri for cat in ["dominant", "strong", "moderate", "weak"]):
                all_ok = False
                break
        if all_ok:
            checks["mindshare_entities_has_required_fields_for_all"] = True
    else:
        # If file exists but empty or invalid structure, keep False
        pass

# Mindshare narratives.json
narratives_path = os.path.join(output_dir, "mindshare", "narratives.json")
if os.path.isfile(narratives_path):
    checks["mindshare_narratives_file_exists"] = True
    narratives_json = load_json_safe(narratives_path)
    items = extract_items_generic(narratives_json, ["narratives", "results"])
    if isinstance(items, list) and len(items) > 0:
        allowed = {"surging", "fading", "stable"}
        all_ok = True
        for it in items:
            if not isinstance(it, dict):
                all_ok = False
                break
            if "percent_change" not in it or "movement_classification" not in it:
                all_ok = False
                break
            if not is_number(it["percent_change"]):
                all_ok = False
                break
            mc = str(it["movement_classification"]).lower()
            if mc not in allowed:
                all_ok = False
                break
        if all_ok:
            checks["mindshare_narratives_has_required_fields_for_all"] = True

# Mindshare summary.md
summary_path = os.path.join(output_dir, "mindshare", "summary.md")
if os.path.isfile(summary_path):
    checks["mindshare_summary_exists"] = True
    text = read_text_safe(summary_path).lower()
    mentions_entities = ("entities" in text) or ("entity" in text)
    mentions_narratives = ("narratives" in text) or ("narrative" in text)
    if mentions_entities and mentions_narratives:
        checks["mindshare_summary_mentions_entities_and_narratives"] = True

# War room report
war_room_path = os.path.join(output_dir, "war_room", "report.md")
if os.path.isfile(war_room_path):
    checks["war_room_report_exists"] = True
    report = read_text_safe(war_room_path)
    needed_sections = [
        "I. Participants",
        "II. Per-Agent Findings",
        "III. Process Highlights",
        "IV. Consensus",
        "V. Disputes and Contradictions",
        "VI. Final Plan",
        "VII. Scenario Projections",
        "VIII. Retained Doubts",
        "IX. Ruling",
        "X. Suggested Action Items",
    ]
    has_all_sections = all(sec in report for sec in needed_sections)
    if has_all_sections:
        checks["war_room_has_all_sections"] = True

    # Ruling line starting with "Ruling:" followed by GO|NO-GO|REWORK
    lines = report.splitlines()
    ruling_regex = re.compile(r'^\s*Ruling:\s*(GO|NO-GO|REWORK)\b', re.IGNORECASE)
    has_ruling_line = any(ruling_regex.search(line) for line in lines)
    if has_ruling_line:
        checks["war_room_has_ruling_line"] = True

    # Phrase "If [X] fails"
    if "If [X] fails" in report:
        checks["war_room_includes_if_x_fails_phrase"] = True

# Signals
signals_json_path = os.path.join(output_dir, "signals", "signals.json")
if os.path.isfile(signals_json_path):
    checks["signals_file_exists"] = True
    sig_json = load_json_safe(signals_json_path)
    entries: List[Dict[str, Any]] = []
    if isinstance(sig_json, list):
        entries = sig_json
    elif isinstance(sig_json, dict) and isinstance(sig_json.get("signals"), list):
        entries = sig_json.get("signals", [])
    # If entries are non-empty, validate schema; if empty, pass the check by definition
    ok = True
    if isinstance(entries, list):
        if len(entries) > 0:
            for e in entries:
                if not isinstance(e, dict):
                    ok = False
                    break
                required = ["ticker", "direction", "signal_strength", "avg_confidence", "suggested_action", "top_thesis"]
                if not all(k in e for k in required):
                    ok = False
                    break
                if not (isinstance(e["ticker"], str) and e["ticker"].strip()):
                    ok = False
                    break
                if not (isinstance(e["direction"], str) and e["direction"].strip()):
                    ok = False
                    break
                if not (is_number(e["signal_strength"]) and is_number(e["avg_confidence"])):
                    ok = False
                    break
                if not (isinstance(e["suggested_action"], str) and isinstance(e["top_thesis"], str)):
                    ok = False
                    break
    else:
        ok = False
    if ok:
        checks["signals_entries_have_required_fields_if_nonempty"] = True

signals_market_summary_path = os.path.join(output_dir, "signals", "market_summary.md")
if os.path.isfile(signals_market_summary_path):
    checks["signals_market_summary_exists"] = True

signals_disclaimer_path = os.path.join(output_dir, "signals", "disclaimer.txt")
if os.path.isfile(signals_disclaimer_path):
    checks["signals_disclaimer_exists"] = True
    disclaim = read_text_safe(signals_disclaimer_path).strip()
    if disclaim == "AI-generated, not financial advice":
        checks["signals_disclaimer_exact_text"] = True

# Marketplace manifest
market_manifest_path = os.path.join(output_dir, "marketplace", "skill_manifest.json")
if os.path.isfile(market_manifest_path):
    checks["marketplace_manifest_exists"] = True
    manifest = load_json_safe(market_manifest_path)
    valid = False
    if isinstance(manifest, dict):
        name = manifest.get("name")
        emoji = manifest.get("emoji")
        category = manifest.get("category")
        description = manifest.get("description")
        version = manifest.get("version")
        tags = manifest.get("tags")
        semver_ok = isinstance(version, str) and re.fullmatch(r"\d+\.\d+\.\d+", version) is not None
        category_ok = category in {"tool", "workflow", "integration", "creative", "data", "communication"}
        tags_ok = isinstance(tags, list) and len(tags) >= 1 and all(isinstance(t, str) and t.strip() for t in tags)
        name_ok = isinstance(name, str) and name.strip()
        emoji_ok = isinstance(emoji, str) and emoji.strip()
        description_ok = isinstance(description, str) and description.strip()
        valid = all([semver_ok, category_ok, tags_ok, name_ok, emoji_ok, description_ok])
    if valid:
        checks["marketplace_manifest_fields_valid"] = True

# Strategy memo
memo_path = os.path.join(output_dir, "memo.md")
if os.path.isfile(memo_path):
    checks["strategy_memo_exists"] = True
    memo_text = read_text_safe(memo_path)
    words = re.findall(r"\b\w+\b", memo_text)
    wc = len(words)
    if 800 <= wc <= 1200:
        checks["strategy_memo_word_count_valid"] = True
    lt = memo_text.lower()
    if ("mindshare" in lt) and ("signals" in lt):
        checks["strategy_memo_mentions_mindshare_and_signals"] = True
    if ("pivot" in lt) and ("portfolio" in lt):
        checks["strategy_memo_mentions_pivot_portfolio"] = True

# Compute reward: proportion of passed checks
total_checks = len(checks)
passed_checks = sum(1 for v in checks.values() if v)
reward = 0.0
if total_checks > 0:
    reward = passed_checks / total_checks

# Ensure reward is between 0 and 1
reward = max(0.0, min(1.0, reward))

result = {"reward": reward}
result.update(checks)
print(json.dumps(result))