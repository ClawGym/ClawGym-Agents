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

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_jsonl(path):
    objs = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    # empty lines are treated as invalid entries
                    return None
                try:
                    obj = json.loads(s)
                except Exception:
                    return None
                objs.append(obj)
        return objs
    except Exception:
        return None

def is_nonempty_string(x):
    return isinstance(x, str) and len(x.strip()) > 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # 1) loot_drops.jsonl
        "loot_drops_exists": False,
        "loot_drops_valid_jsonl": False,
        "loot_drops_all_fields_valid": False,

        # 2) inventory.md
        "inventory_exists": False,
        "inventory_sections_present": False,

        # 3) loot_drops_humanized.jsonl
        "humanized_exists": False,
        "humanized_valid_jsonl": False,
        "humanized_same_linecount": False,
        "humanized_all_fields_present": False,
        "humanized_flavor_text_changed_all": False,
        "humanized_banned_words_absent": False,

        # 4) gamification_strategy.md
        "strategy_exists": False,
        "strategy_sections_present": False,
        "strategy_timeframe_present": False,

        # 5) model artifacts
        "transcript_exists": False,
        "transcript_valid_structure": False,
        "transcript_interactions_count": False,
        "transcript_entries_valid": False,

        # Optional plan.md (does not affect reward if transcript valid)
        "plan_exists_and_valid": False,
    }

    # Allowed values
    allowed_rarities = {"Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic"}
    allowed_categories = {
        "Sword", "Bow", "Wand", "Hammer", "Dagger",
        "Shield", "Chestplate", "Boots", "Helmet", "Gloves",
        "Ring", "Amulet", "Scroll", "Potion", "Orb"
    }
    banned_ai_words = [
        "pivotal", "landscape", "underscore", "testament", "nestled", "groundbreaking",
        "seamless", "holistic", "synergy", "realm", "multifaceted", "nuanced",
        "delve", "tapestry", "vibrant"
    ]

    # Paths
    loot_drops_path = os.path.join(output_dir, "loot_drops.jsonl")
    inventory_md_path = os.path.join(output_dir, "inventory.md")
    humanized_path = os.path.join(output_dir, "loot_drops_humanized.jsonl")
    strategy_path = os.path.join(output_dir, "gamification_strategy.md")
    transcript_path = os.path.join(output_dir, "model", "transcript.json")
    plan_md_path = os.path.join(output_dir, "model", "plan.md")

    # 1) Validate loot_drops.jsonl
    loot_objs = None
    if os.path.isfile(loot_drops_path):
        checks["loot_drops_exists"] = True
        loot_objs = parse_jsonl(loot_drops_path)
        if loot_objs is not None and isinstance(loot_objs, list) and len(loot_objs) >= 1:
            checks["loot_drops_valid_jsonl"] = True

            # Validate schema/content for each line
            required_keys = {"event_id", "trigger", "rarity", "category", "stats", "special_abilities", "flavor_text", "ascii_box"}
            stats_re = re.compile(r"^\+\d+\s+.+")
            all_valid = True
            for obj in loot_objs:
                # keys present
                if not isinstance(obj, dict):
                    all_valid = False
                    break
                if not required_keys.issubset(set(obj.keys())):
                    all_valid = False
                    break
                # rarity
                rarity = obj.get("rarity", "")
                if not isinstance(rarity, str) or rarity not in allowed_rarities:
                    all_valid = False
                    break
                # category
                category = obj.get("category", "")
                if not isinstance(category, str) or category not in allowed_categories:
                    all_valid = False
                    break
                # stats
                stats = obj.get("stats", [])
                if not isinstance(stats, list) or len(stats) < 2:
                    all_valid = False
                    break
                # each stat matches pattern
                stat_ok = True
                for s in stats:
                    if not isinstance(s, str) or not stats_re.match(s.strip()):
                        stat_ok = False
                        break
                if not stat_ok:
                    all_valid = False
                    break
                # special_abilities: string or array (any content acceptable)
                sa = obj.get("special_abilities", None)
                if not (isinstance(sa, str) or isinstance(sa, list)):
                    all_valid = False
                    break
                # flavor_text non-empty string
                if not is_nonempty_string(obj.get("flavor_text", "")):
                    all_valid = False
                    break
                # ascii_box contains 💎 and "LOOT DROP" and tier label uppercase
                ascii_box = obj.get("ascii_box", "")
                if not isinstance(ascii_box, str):
                    all_valid = False
                    break
                if "💎" not in ascii_box or "LOOT DROP" not in ascii_box:
                    all_valid = False
                    break
                rarity_label = rarity.upper()
                if rarity_label not in ascii_box.upper():
                    all_valid = False
                    break
            if all_valid:
                checks["loot_drops_all_fields_valid"] = True
        else:
            # invalid JSONL
            checks["loot_drops_valid_jsonl"] = False

    # 2) Validate inventory.md
    if os.path.isfile(inventory_md_path):
        checks["inventory_exists"] = True
        inv_text = read_text(inventory_md_path) or ""
        # Must contain literal section titles (case-sensitive)
        needs = ["YOUR INVENTORY", "EQUIPPED", "TOTAL STATS"]
        if all(needle in inv_text for needle in needs):
            checks["inventory_sections_present"] = True

    # 3) Validate loot_drops_humanized.jsonl
    humanized_objs = None
    if os.path.isfile(humanized_path):
        checks["humanized_exists"] = True
        humanized_objs = parse_jsonl(humanized_path)
        if humanized_objs is not None and isinstance(humanized_objs, list) and len(humanized_objs) >= 1:
            checks["humanized_valid_jsonl"] = True

            # only run dependent checks if original loot exists and valid
            if checks["loot_drops_valid_jsonl"]:
                if len(humanized_objs) == len(loot_objs):
                    checks["humanized_same_linecount"] = True

                    # structure & flavor_text difference and banned words
                    required_keys_h = {"event_id", "trigger", "rarity", "category", "stats", "special_abilities", "flavor_text", "ascii_box"}
                    structure_ok = True
                    changed_all = True
                    banned_ok = True

                    for i in range(len(loot_objs)):
                        a = loot_objs[i]
                        b = humanized_objs[i]
                        # must be dict with required keys
                        if not isinstance(b, dict) or not required_keys_h.issubset(set(b.keys())):
                            structure_ok = False
                        # flavor text changed
                        ft_a = a.get("flavor_text", "")
                        ft_b = b.get("flavor_text", "")
                        if not isinstance(ft_b, str):
                            changed_all = False
                            banned_ok = False
                        else:
                            if ft_a == ft_b:
                                changed_all = False
                            # banned words check (case-insensitive substring)
                            low = ft_b.lower()
                            for bad in banned_ai_words:
                                if bad.lower() in low:
                                    banned_ok = False
                                    break
                        if not structure_ok:
                            # continue checking others for completeness but final flags reflect
                            pass

                    if structure_ok:
                        checks["humanized_all_fields_present"] = True
                    if changed_all:
                        checks["humanized_flavor_text_changed_all"] = True
                    if banned_ok:
                        checks["humanized_banned_words_absent"] = True

    # 4) Validate gamification_strategy.md
    if os.path.isfile(strategy_path):
        checks["strategy_exists"] = True
        strategy_text = read_text(strategy_path) or ""
        required_sections = ["Executive Summary", "Risk Assessment", "GTM Strategy", "KPIs", "Decision Framework Matrix"]
        if all(sec in strategy_text for sec in required_sections):
            checks["strategy_sections_present"] = True
        # timeframe mention: either "90 days" or "Next 90 days" (substring, case-sensitive)
        if ("Next 90 days" in strategy_text) or ("90 days" in strategy_text):
            checks["strategy_timeframe_present"] = True

    # 5) Validate model transcript and optional plan
    transcript = None
    if os.path.isfile(transcript_path):
        checks["transcript_exists"] = True
        transcript = read_json(transcript_path)
        if isinstance(transcript, dict):
            base_url = transcript.get("base_url")
            status = transcript.get("status")
            interactions = transcript.get("interactions")
            structure_ok = (
                isinstance(base_url, str) and
                (base_url.startswith("http://") or base_url.startswith("https://")) and
                ("/v1" in base_url) and
                isinstance(status, str) and
                isinstance(interactions, list)
            )
            if structure_ok:
                checks["transcript_valid_structure"] = True
                if len(interactions) >= 10:
                    checks["transcript_interactions_count"] = True

                    # validate each interaction item
                    entries_ok = True
                    for it in interactions:
                        if not isinstance(it, dict):
                            entries_ok = False
                            break
                        prompt = it.get("prompt")
                        response = it.get("response")
                        if not (isinstance(prompt, str) and isinstance(response, dict)):
                            entries_ok = False
                            break
                        item_name = response.get("item_name")
                        category = response.get("category")
                        rarity = response.get("rarity")
                        flavor_text = response.get("flavor_text")
                        if not (isinstance(item_name, str) and is_nonempty_string(item_name)):
                            entries_ok = False
                            break
                        if not (isinstance(category, str) and category in allowed_categories):
                            entries_ok = False
                            break
                        if rarity != "Mythic":
                            entries_ok = False
                            break
                        if not (isinstance(flavor_text, str) and is_nonempty_string(flavor_text)):
                            entries_ok = False
                            break
                    if entries_ok:
                        checks["transcript_entries_valid"] = True

    # Optional plan.md validity (does not affect reward if transcript is valid)
    if os.path.isfile(plan_md_path):
        plan_text = read_text(plan_md_path) or ""
        if (
            "host:" in plan_text and
            "port:" in plan_text and
            "base_url:" in plan_text and
            "/v1/models" in plan_text and
            "/v1/chat/completions" in plan_text
        ):
            checks["plan_exists_and_valid"] = True

    # Scoring: only artifact-dependent, deterministic checks contribute
    scored_keys = [
        "loot_drops_exists",
        "loot_drops_valid_jsonl",
        "loot_drops_all_fields_valid",

        "inventory_exists",
        "inventory_sections_present",

        "humanized_exists",
        "humanized_valid_jsonl",
        "humanized_same_linecount",
        "humanized_all_fields_present",
        "humanized_flavor_text_changed_all",
        "humanized_banned_words_absent",

        "strategy_exists",
        "strategy_sections_present",
        "strategy_timeframe_present",

        "transcript_exists",
        "transcript_valid_structure",
        "transcript_interactions_count",
        "transcript_entries_valid",
    ]

    # Baseline: if output directory missing or empty -> 0.0 (implicitly ensured by checks all False)
    total = len(scored_keys)
    passed = sum(1 for k in scored_keys if checks.get(k, False))
    reward = (passed / total) if total > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()