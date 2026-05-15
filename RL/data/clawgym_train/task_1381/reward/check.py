import json
import os
import re
import sys
import hashlib
from datetime import datetime

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def load_agents(input_dir):
    agents_path = os.path.join(input_dir, "agents.json")
    if not os.path.isfile(agents_path):
        return None, "agents.json missing"
    try:
        with open(agents_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("agents"), list):
            agents = [str(x) for x in data.get("agents")]
            return agents, None
        elif isinstance(data, list):
            agents = [str(x) for x in data]
            return agents, None
        else:
            return None, "agents.json format invalid"
    except Exception as e:
        return None, f"agents.json parse error: {e}"

def compute_stats(agent_name, date_str):
    seed = f"{agent_name}-{date_str}"
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    energy = (h % 60) + 40
    appetite = ((h // 100) % 70) + 30
    bravery = ((h // 10000) % 80) + 20
    intelligence = ((h // 1000000) % 50) + 50
    affection = ((h // 100000000) % 90) + 10
    return {
        "energy": energy,
        "appetite": appetite,
        "bravery": bravery,
        "intelligence": intelligence,
        "affection": affection,
    }

def classify_level(value):
    # thresholds: low = 0–39, medium = 40–69, high = 70–100
    if value <= 39:
        return "low"
    elif value <= 69:
        return "medium"
    else:
        return "high"

def parse_soul_stats(content):
    # Return dict of parsed stats if exactly one line per label with integers, else None
    labels = ["Energy", "Compute Appetite", "Bravery", "Intelligence", "Affection"]
    pattern_map = {
        "Energy": re.compile(r"^\s*Energy:\s*(\d+)\s*$"),
        "Compute Appetite": re.compile(r"^\s*Compute Appetite:\s*(\d+)\s*$"),
        "Bravery": re.compile(r"^\s*Bravery:\s*(\d+)\s*$"),
        "Intelligence": re.compile(r"^\s*Intelligence:\s*(\d+)\s*$"),
        "Affection": re.compile(r"^\s*Affection:\s*(\d+)\s*$"),
    }
    counts = {k: 0 for k in labels}
    values = {}
    for line in content.splitlines():
        for label, pat in pattern_map.items():
            m = pat.match(line)
            if m:
                counts[label] += 1
                try:
                    values[label] = int(m.group(1))
                except:
                    return None
    # Ensure exactly one match for each label
    if any(counts[k] != 1 for k in labels):
        return None
    return values

def header_has_name_and_timestamp(agent_name, content):
    # Look for any line containing the agent name and a timestamp YYYY-MM-DD HH:MM:SS
    ts_re = re.compile(r"\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\b")
    for line in content.splitlines():
        if agent_name in line and ts_re.search(line):
            return True
    return False

def has_5d_stats_header(content):
    # Check for presence of "5D Stats" phrase (case-insensitive)
    return re.search(r"\b5D Stats\b", content, flags=re.IGNORECASE) is not None

def check_index_json(output_dir, agents, today_str, expected_stats_map):
    index_path = os.path.join(output_dir, "souls", "index.json")
    if not os.path.isfile(index_path):
        return False
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return False
        # Must be exactly one object per agent with no extras
        if len(data) != len(agents):
            return False
        # Build map by agent name
        found_agents = set()
        for obj in data:
            if not isinstance(obj, dict):
                return False
            required_keys = {"agent", "date", "energy", "appetite", "bravery", "intelligence", "affection"}
            if not required_keys.issubset(set(obj.keys())):
                return False
            agent = obj["agent"]
            if agent in found_agents:
                return False
            found_agents.add(agent)
            if agent not in expected_stats_map:
                return False
            if obj["date"] != today_str:
                return False
            stats = expected_stats_map[agent]
            try:
                if int(obj["energy"]) != stats["energy"]:
                    return False
                if int(obj["appetite"]) != stats["appetite"]:
                    return False
                if int(obj["bravery"]) != stats["bravery"]:
                    return False
                if int(obj["intelligence"]) != stats["intelligence"]:
                    return False
                if int(obj["affection"]) != stats["affection"]:
                    return False
            except Exception:
                return False
        if set(agents) != found_agents:
            return False
        return True
    except Exception:
        return False

def check_calibration_md(output_dir):
    path = os.path.join(output_dir, "taste", "calibration.md")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # Find a line starting with "Level:" and value is exactly one of allowed
        allowed = {"Uncalibrated", "Learning", "Calibrating", "Calibrated"}
        for line in content.splitlines():
            m = re.match(r"^\s*Level:\s*(\w+)\s*$", line)
            if m:
                return m.group(1) in allowed
        return False
    except Exception:
        return False

def check_corrections_template(output_dir):
    path = os.path.join(output_dir, "taste", "corrections", "writing.md")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        labels = [
            "Date:",
            "Domain:",
            "My judgment:",
            "Human's correction:",
            "Why (their explanation):",
            "Pattern extracted:",
            "Confidence update:",
        ]
        ok = True
        for label in labels:
            count = content.count(label)
            if count != 1:
                ok = False
                break
        return ok
    except Exception:
        return False

def check_report(output_dir, agents, expected_stats_map):
    path = os.path.join(output_dir, "report.md")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # Split into blocks by blank lines
        blocks = re.split(r"\n\s*\n", content)
        covered = {}
        for agent in agents:
            covered[agent] = False
        for agent in agents:
            expected = expected_stats_map[agent]
            appetite_class = classify_level(expected["appetite"])
            bravery_class = classify_level(expected["bravery"])
            found_block = None
            for block in blocks:
                if agent in block:
                    found_block = block
                    break
            if not found_block:
                return False
            # Check classifications within the block
            # Appetite
            app_match = re.search(r"(Compute Appetite|Appetite)\s*[:\-]?\s*(low|medium|high)", found_block, flags=re.IGNORECASE)
            brav_match = re.search(r"Bravery\s*[:\-]?\s*(low|medium|high)", found_block, flags=re.IGNORECASE)
            if not app_match or not brav_match:
                return False
            app_val = app_match.group(2).lower()
            brav_val = brav_match.group(1).lower()
            if app_val != appetite_class or brav_val != bravery_class:
                return False
            # At least one sentence of guidance: presence of a period, exclamation, or question mark
            if not re.search(r"[\.!\?]", found_block):
                return False
            covered[agent] = True
        # Ensure every agent covered
        if not all(covered.values()):
            return False
        return True
    except Exception:
        return False

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "souls_all_present": False,
        "souls_header_has_name_and_timestamp": False,
        "souls_contains_5d_stats_header": False,
        "souls_5d_labels_once_and_ints": False,
        "souls_stats_match_algorithm": False,
        "index_json_valid_and_consistent": False,
        "taste_calibration_level_valid": False,
        "taste_corrections_template_valid": False,
        "report_per_agent_classification_and_guidance": False,
    }

    # Load agents
    agents, agents_err = load_agents(input_dir)
    if not agents:
        # Cannot proceed with further checks without agents; all remain False
        reward = 0.0
        print(json.dumps({"reward": reward, **checks}))
        return

    # Today's date string
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Prepare expected stats map
    expected_stats_map = {agent: compute_stats(agent, today_str) for agent in agents}

    # Check SOUL.md files presence and content
    souls_present_for_all = True
    header_ok_for_all = True
    has_stats_header_for_all = True
    labels_once_for_all = True
    stats_match_for_all = True

    for agent in agents:
        soul_path = os.path.join(output_dir, "souls", agent, "SOUL.md")
        if not os.path.isfile(soul_path):
            souls_present_for_all = False
            header_ok_for_all = False
            has_stats_header_for_all = False
            labels_once_for_all = False
            stats_match_for_all = False
            continue
        try:
            with open(soul_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            souls_present_for_all = False
            header_ok_for_all = False
            has_stats_header_for_all = False
            labels_once_for_all = False
            stats_match_for_all = False
            continue

        # Header check (name + timestamp)
        if not header_has_name_and_timestamp(agent, content):
            header_ok_for_all = False

        # "5D Stats" header presence
        if not has_5d_stats_header(content):
            has_stats_header_for_all = False

        # Parse stats lines
        parsed = parse_soul_stats(content)
        if parsed is None:
            labels_once_for_all = False
            stats_match_for_all = False
        else:
            # Compare with expected stats
            exp = expected_stats_map[agent]
            # Map labels to keys
            label_to_key = {
                "Energy": "energy",
                "Compute Appetite": "appetite",
                "Bravery": "bravery",
                "Intelligence": "intelligence",
                "Affection": "affection",
            }
            for label, key in label_to_key.items():
                val = parsed.get(label)
                if val is None:
                    stats_match_for_all = False
                    break
                if key == "energy" and val != exp["energy"]:
                    stats_match_for_all = False
                elif key == "appetite" and val != exp["appetite"]:
                    stats_match_for_all = False
                elif key == "bravery" and val != exp["bravery"]:
                    stats_match_for_all = False
                elif key == "intelligence" and val != exp["intelligence"]:
                    stats_match_for_all = False
                elif key == "affection" and val != exp["affection"]:
                    stats_match_for_all = False
                # Also ensure ranges per spec
                if key == "energy" and not (40 <= val <= 99):
                    stats_match_for_all = False
                if key == "appetite" and not (30 <= val <= 99):
                    stats_match_for_all = False
                if key == "bravery" and not (20 <= val <= 99):
                    stats_match_for_all = False
                if key == "intelligence" and not (50 <= val <= 99):
                    stats_match_for_all = False
                if key == "affection" and not (10 <= val <= 99):
                    stats_match_for_all = False

    checks["souls_all_present"] = souls_present_for_all
    checks["souls_header_has_name_and_timestamp"] = header_ok_for_all and souls_present_for_all
    checks["souls_contains_5d_stats_header"] = has_stats_header_for_all and souls_present_for_all
    checks["souls_5d_labels_once_and_ints"] = labels_once_for_all and souls_present_for_all
    checks["souls_stats_match_algorithm"] = stats_match_for_all and souls_present_for_all

    # Check index.json
    checks["index_json_valid_and_consistent"] = check_index_json(output_dir, agents, today_str, expected_stats_map)

    # Taste calibration and corrections template
    checks["taste_calibration_level_valid"] = check_calibration_md(output_dir)
    checks["taste_corrections_template_valid"] = check_corrections_template(output_dir)

    # Report check
    checks["report_per_agent_classification_and_guidance"] = check_report(output_dir, agents, expected_stats_map)

    # Compute reward as average of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    print(json.dumps({"reward": round(reward, 6), **checks}))

if __name__ == "__main__":
    main()