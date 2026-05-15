import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def try_yaml_load(path):
    # Attempt to load YAML with PyYAML if available; return (data, True) on success else (None, False)
    try:
        import yaml  # type: ignore
    except Exception:
        return None, False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data, isinstance(data, dict)
    except Exception:
        return None, False

def extract_scene_names_from_text(yaml_text):
    # Fallback parser: find scene names from list items
    names = re.findall(r'^\s*-\s*name:\s*["\']?([^"\']+)["\']?', yaml_text, flags=re.MULTILINE)
    return [n.strip() for n in names]

def extract_scene_block(yaml_text, scene_name):
    # Find the block of the scene with the given name from the text
    pattern = re.compile(r'^\s*-\s*name:\s*["\']?(' + re.escape(scene_name) + r')["\']?', re.MULTILINE | re.IGNORECASE)
    matches = list(pattern.finditer(yaml_text))
    if not matches:
        return None
    start = matches[0].start()
    # Find next scene start
    next_pattern = re.compile(r'^\s*-\s*name:\s*', re.MULTILINE)
    next_match = next_pattern.search(yaml_text, matches[0].end())
    end = next_match.start() if next_match else len(yaml_text)
    return yaml_text[start:end]

def good_morning_has_light_brightness_leq_40(yaml_text):
    block = extract_scene_block(yaml_text, "Good Morning")
    if not block:
        return False
    # Within block, locate entities and parse entity sections
    # Approach: find lines that look like entity declarations and their sub-blocks
    lines = block.splitlines()
    # Find "entities:" line index
    ent_index = None
    for idx, line in enumerate(lines):
        if re.match(r'^\s*entities\s*:\s*$', line):
            ent_index = idx
            break
    if ent_index is None:
        return False
    # Parse subsequent lines for entity blocks
    # An entity line looks like "      light.xxx:" (key with colon on its own)
    # Track current entity and its attribute lines
    current_entity = None
    current_entity_indent = None
    entity_blocks = {}  # entity_id -> list of attribute lines
    for i in range(ent_index + 1, len(lines)):
        line = lines[i]
        # Entity declaration
        m_ent = re.match(r'^(\s+)([A-Za-z0-9_.]+)\s*:\s*$', line)
        if m_ent:
            current_entity_indent = len(m_ent.group(1))
            current_entity = m_ent.group(2)
            entity_blocks[current_entity] = []
            continue
        # Attribute under current entity
        if current_entity is not None:
            # Attribute lines must be further indented than current_entity_indent
            m_attr = re.match(r'^(\s+)([A-Za-z0-9_]+)\s*:\s*(.+)?\s*$', line)
            if m_attr and len(m_attr.group(1)) > (current_entity_indent or 0):
                entity_blocks[current_entity].append(line)
            else:
                # Dedented line means entity block likely ended
                # But continue scanning; current_entity may be reset when next entity found
                pass
    # Inspect light.* entities for brightness_pct <= 40
    for ent_id, attrs in entity_blocks.items():
        if ent_id.startswith("light."):
            for attr_line in attrs:
                m_b = re.match(r'^\s+[A-Za-z0-9_]+\s*:\s*(.+)\s*$', attr_line)
                if not m_b:
                    continue
                if re.search(r'brightness_pct\s*:\s*([0-9]+)', attr_line):
                    m_val = re.search(r'brightness_pct\s*:\s*([0-9]+)', attr_line)
                    try:
                        val = int(m_val.group(1)) if m_val else None
                    except Exception:
                        val = None
                    if val is not None and val <= 40:
                        return True
    return False

def find_services_in_structure(obj):
    services = []
    def _recurse(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "service":
                    try:
                        services.append(str(v))
                    except Exception:
                        pass
                _recurse(v)
        elif isinstance(x, list):
            for item in x:
                _recurse(item)
        else:
            pass
    _recurse(obj)
    return services

def has_alias_with_phrase_in_yaml(data, phrase):
    # data expected dict with key 'automation' -> list of dicts
    automations = data.get("automation") if isinstance(data, dict) else None
    if not isinstance(automations, list):
        return False
    p = phrase.lower()
    for a in automations:
        if isinstance(a, dict):
            alias = a.get("alias")
            if isinstance(alias, str) and p in alias.lower():
                return True
    return False

def has_alias_with_phrase_in_text(text, phrase):
    # Search for alias lines containing the phrase
    pattern = re.compile(r'^\s*alias\s*:\s*(.*' + re.escape(phrase) + r'.*)$', re.IGNORECASE | re.MULTILINE)
    return pattern.search(text) is not None

def has_service_in_yaml(data, service_predicate):
    automations = data.get("automation") if isinstance(data, dict) else None
    if not isinstance(automations, list):
        return False
    for a in automations:
        if isinstance(a, dict):
            services = find_services_in_structure(a)
            for s in services:
                if service_predicate(s):
                    return True
    return False

def has_service_in_text(text, regex_pattern):
    return re.search(regex_pattern, text, flags=re.IGNORECASE) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # Scenes
        "scenes_exists": False,
        "scenes_yaml_valid": False,
        "scenes_has_good_morning": False,
        "scenes_has_focus_mode": False,
        "scenes_has_movie_time": False,
        "scenes_has_bedtime": False,
        "scenes_good_morning_light_brightness_leq_40": False,
        # Automations
        "automations_exists": False,
        "automations_yaml_valid": False,
        "automations_has_morning_brief_alias": False,
        "automations_has_medication_alias": False,
        "automations_has_arrival_alias": False,
        "automations_has_inactivity_alias": False,
        "automations_has_scene_turn_on_service": False,
        "automations_has_notify_service": False,
        # Voice commands
        "voice_commands_exists": False,
        "voice_has_goodnight": False,
        "voice_has_im_working": False,
        "voice_has_movie_time": False,
        "voice_has_help": False,
        "voice_mentions_undo": False,
        # Fallbacks
        "fallbacks_exists": False,
        "fallbacks_mentions_offline": False,
        "fallbacks_mentions_manual": False,
        "fallbacks_has_code_4821": False,
        "fallbacks_mentions_alert_and_reconnects": False,
        # Friction audit script
        "friction_script_exists": False,
        "friction_script_has_function": False,
        "friction_script_references_input_path": False,
        "friction_script_references_output_path": False,
        # README
        "readme_exists": False,
        "readme_has_required_emojis": False,
    }

    # Paths
    scenes_path = os.path.join(output_dir, "scenes.yaml")
    automations_path = os.path.join(output_dir, "automations.yaml")
    voice_md_path = os.path.join(output_dir, "voice_commands.md")
    fallbacks_md_path = os.path.join(output_dir, "fallbacks.md")
    friction_py_path = os.path.join(output_dir, "friction_audit.py")
    readme_md_path = os.path.join(output_dir, "README.md")

    # Scenes checks
    if os.path.isfile(scenes_path):
        checks["scenes_exists"] = True
        scenes_text = read_text(scenes_path) or ""
        # Try YAML load
        data, yaml_ok = try_yaml_load(scenes_path)
        if yaml_ok and isinstance(data, dict) and isinstance(data.get("scene"), list):
            checks["scenes_yaml_valid"] = True
            # Names
            names = []
            for item in data.get("scene", []):
                if isinstance(item, dict):
                    nm = item.get("name")
                    if isinstance(nm, str):
                        names.append(nm.strip())
            checks["scenes_has_good_morning"] = any(n == "Good Morning" for n in names)
            checks["scenes_has_focus_mode"] = any(n == "Focus Mode" for n in names)
            checks["scenes_has_movie_time"] = any(n == "Movie Time" for n in names)
            checks["scenes_has_bedtime"] = any(n == "Bedtime" for n in names)
            # Good Morning brightness check
            for item in data.get("scene", []):
                if isinstance(item, dict) and item.get("name") == "Good Morning":
                    entities = item.get("entities", {})
                    if isinstance(entities, dict):
                        for ent_id, ent_cfg in entities.items():
                            if isinstance(ent_id, str) and ent_id.startswith("light.") and isinstance(ent_cfg, dict):
                                bpct = ent_cfg.get("brightness_pct")
                                try:
                                    if bpct is not None and int(bpct) <= 40:
                                        checks["scenes_good_morning_light_brightness_leq_40"] = True
                                except Exception:
                                    pass
            # If not satisfied via YAML parse, fall back to text parser
            if not checks["scenes_good_morning_light_brightness_leq_40"]:
                if good_morning_has_light_brightness_leq_40(scenes_text):
                    checks["scenes_good_morning_light_brightness_leq_40"] = True
        else:
            # Fallback validation by text
            # Must have top-level key 'scene'
            if re.search(r'^\s*scene\s*:\s*$', scenes_text, flags=re.MULTILINE):
                # At least looks like a YAML list of scenes
                # Confirm presence of names
                names = extract_scene_names_from_text(scenes_text)
                if names:
                    checks["scenes_yaml_valid"] = True  # Consider parseable by fallback heuristic
                checks["scenes_has_good_morning"] = any(n.strip() == "Good Morning" for n in names)
                checks["scenes_has_focus_mode"] = any(n.strip() == "Focus Mode" for n in names)
                checks["scenes_has_movie_time"] = any(n.strip() == "Movie Time" for n in names)
                checks["scenes_has_bedtime"] = any(n.strip() == "Bedtime" for n in names)
                if good_morning_has_light_brightness_leq_40(scenes_text):
                    checks["scenes_good_morning_light_brightness_leq_40"] = True

    # Automations checks
    if os.path.isfile(automations_path):
        checks["automations_exists"] = True
        automations_text = read_text(automations_path) or ""
        data, yaml_ok = try_yaml_load(automations_path)
        if yaml_ok and isinstance(data, dict) and isinstance(data.get("automation"), list):
            checks["automations_yaml_valid"] = True
            # Aliases
            checks["automations_has_morning_brief_alias"] = has_alias_with_phrase_in_yaml(data, "Morning Brief")
            checks["automations_has_medication_alias"] = has_alias_with_phrase_in_yaml(data, "Medication")
            checks["automations_has_arrival_alias"] = has_alias_with_phrase_in_yaml(data, "Arrival")
            checks["automations_has_inactivity_alias"] = has_alias_with_phrase_in_yaml(data, "Inactivity")
            # Services
            checks["automations_has_scene_turn_on_service"] = has_service_in_yaml(
                data, lambda s: isinstance(s, str) and s.strip().lower() == "scene.turn_on"
            )
            checks["automations_has_notify_service"] = has_service_in_yaml(
                data, lambda s: isinstance(s, str) and (s.strip().lower() == "notify" or s.strip().lower().startswith("notify."))
            )
        else:
            # Fallback text-based checks
            if re.search(r'^\s*automation\s*:\s*$', automations_text, flags=re.MULTILINE) and re.search(r'^\s*-\s*alias\s*:\s*', automations_text, flags=re.MULTILINE):
                checks["automations_yaml_valid"] = True
            checks["automations_has_morning_brief_alias"] = has_alias_with_phrase_in_text(automations_text, "Morning Brief")
            checks["automations_has_medication_alias"] = has_alias_with_phrase_in_text(automations_text, "Medication")
            checks["automations_has_arrival_alias"] = has_alias_with_phrase_in_text(automations_text, "Arrival")
            checks["automations_has_inactivity_alias"] = has_alias_with_phrase_in_text(automations_text, "Inactivity")
            # Services via regex
            if has_service_in_text(automations_text, r'^\s*service\s*:\s*scene\.turn_on\s*$',):
                checks["automations_has_scene_turn_on_service"] = True
            if has_service_in_text(automations_text, r'^\s*service\s*:\s*notify(\.[A-Za-z0-9_]+)?\s*$'):
                checks["automations_has_notify_service"] = True

    # Voice commands
    if os.path.isfile(voice_md_path):
        checks["voice_commands_exists"] = True
        voice_text = read_text(voice_md_path) or ""
        # Case-sensitive per requirements for literal phrases
        checks["voice_has_goodnight"] = ("Goodnight" in voice_text)
        checks["voice_has_im_working"] = ("I'm working" in voice_text)
        checks["voice_has_movie_time"] = ("Movie time" in voice_text)
        checks["voice_has_help"] = ("Help" in voice_text)
        # undo pattern (case-insensitive acceptable)
        checks["voice_mentions_undo"] = ("undo" in voice_text.lower())

    # Fallbacks
    if os.path.isfile(fallbacks_md_path):
        checks["fallbacks_exists"] = True
        fallbacks_text = read_text(fallbacks_md_path) or ""
        lt = fallbacks_text.lower()
        checks["fallbacks_mentions_offline"] = ("offline" in lt)
        checks["fallbacks_mentions_manual"] = ("manual" in lt)
        checks["fallbacks_has_code_4821"] = ("4821" in fallbacks_text)
        checks["fallbacks_mentions_alert_and_reconnects"] = ("alert" in lt and "reconnects" in lt)

    # Friction audit script
    if os.path.isfile(friction_py_path):
        checks["friction_script_exists"] = True
        script_text = read_text(friction_py_path) or ""
        checks["friction_script_has_function"] = (re.search(r'^\s*def\s+analyze_conversation\s*\(', script_text, flags=re.MULTILINE) is not None)
        checks["friction_script_references_input_path"] = ("input/conversation_logs.jsonl" in script_text)
        checks["friction_script_references_output_path"] = ("output/friction_report.json" in script_text)

    # README
    if os.path.isfile(readme_md_path):
        checks["readme_exists"] = True
        readme_text = read_text(readme_md_path) or ""
        required_emojis = ["☀️", "📅", "💊", "🔋"]
        checks["readme_has_required_emojis"] = all(e in readme_text for e in required_emojis)

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0
    # No-op baseline: if no outputs exist, reward must be 0.0
    output_exists = any(os.path.isfile(os.path.join(output_dir, p)) for p in [
        "scenes.yaml", "automations.yaml", "voice_commands.md", "fallbacks.md", "friction_audit.py", "README.md"
    ])
    if not output_exists:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()