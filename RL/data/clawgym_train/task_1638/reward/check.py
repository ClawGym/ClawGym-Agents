import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def file_contains(path, substring):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return substring in f.read()
    except Exception:
        return False

def file_read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), True
    except Exception:
        return "", False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    entity_path = os.path.join(output_dir, "entity.json")
    identity_md_path = os.path.join(output_dir, "IDENTITY.md")
    soul_md_path = os.path.join(output_dir, "SOUL.md")
    bio_html_path = os.path.join(output_dir, "bio.html")
    exported_schema_path = os.path.join(output_dir, "exported_schema.json")

    # 1) entity.json checks
    checks["entity_exists"] = os.path.isfile(entity_path)
    entity_json, entity_valid = (None, False)
    if checks["entity_exists"]:
        entity_json, entity_valid = load_json(entity_path)
    checks["entity_json_valid"] = bool(entity_valid)

    checks["entity_protocol_AIEOS"] = False
    checks["entity_nickname_Nova"] = False
    checks["entity_favorite_color_blue"] = False
    checks["entity_logic_08"] = False

    if entity_valid and isinstance(entity_json, dict):
        # standard.protocol == "AIEOS"
        try:
            checks["entity_protocol_AIEOS"] = entity_json.get("standard", {}).get("protocol") == "AIEOS"
        except Exception:
            checks["entity_protocol_AIEOS"] = False
        # identity.names.nickname == "Nova"
        try:
            checks["entity_nickname_Nova"] = entity_json.get("identity", {}).get("names", {}).get("nickname") == "Nova"
        except Exception:
            checks["entity_nickname_Nova"] = False
        # interests.favorites.color == "blue"
        try:
            checks["entity_favorite_color_blue"] = entity_json.get("interests", {}).get("favorites", {}).get("color") == "blue"
        except Exception:
            checks["entity_favorite_color_blue"] = False
        # psychology.neural_matrix.logic == 0.8 (float)
        try:
            logic_val = entity_json.get("psychology", {}).get("neural_matrix", {}).get("logic")
            if isinstance(logic_val, (int, float)) and abs(float(logic_val) - 0.8) < 1e-9:
                checks["entity_logic_08"] = True
        except Exception:
            checks["entity_logic_08"] = False

    # 2) IDENTITY.md checks
    checks["identity_exists"] = os.path.isfile(identity_md_path)
    identity_content, identity_read_ok = file_read(identity_md_path) if checks["identity_exists"] else ("", False)

    # "- **Name:** Nova"
    checks["identity_name_contains"] = False
    if identity_read_ok:
        checks["identity_name_contains"] = "- **Name:** Nova" in identity_content

    # "- **Creature:** Logical digital assistant"
    checks["identity_creature_logical_assistant"] = False
    if identity_read_ok:
        checks["identity_creature_logical_assistant"] = "- **Creature:** Logical digital assistant" in identity_content

    # A line starting with "- **Vibe:" that includes both "logical" and "warm" (case-insensitive)
    checks["identity_vibe_line_has_logical_and_warm"] = False
    if identity_read_ok:
        for line in identity_content.splitlines():
            s = line.strip()
            if s.lower().startswith("- **vibe:".lower()):
                low = s.lower()
                if ("logical" in low) and ("warm" in low):
                    checks["identity_vibe_line_has_logical_and_warm"] = True
                    break

    # "- **Emoji:** 🔵"
    checks["identity_emoji_blue"] = False
    if identity_read_ok:
        checks["identity_emoji_blue"] = "- **Emoji:** 🔵" in identity_content

    # 3) SOUL.md checks
    checks["soul_exists"] = os.path.isfile(soul_md_path)
    soul_content, soul_read_ok = file_read(soul_md_path) if checks["soul_exists"] else ("", False)

    # "Moral Alignment: Lawful Good"
    checks["soul_moral_alignment_lawful_good"] = False
    if soul_read_ok:
        checks["soul_moral_alignment_lawful_good"] = "Moral Alignment: Lawful Good" in soul_content

    # "Neural Matrix" and a line with "- **Logic:**"
    checks["soul_has_neural_matrix_and_logic_line"] = False
    if soul_read_ok:
        has_nm = "Neural Matrix" in soul_content
        has_logic_line = False
        for line in soul_content.splitlines():
            if "- **Logic:**" in line:
                has_logic_line = True
                break
        checks["soul_has_neural_matrix_and_logic_line"] = bool(has_nm and has_logic_line)

    # Boundaries list includes exact sentence
    checks["soul_has_boundaries_sentence"] = False
    if soul_read_ok:
        checks["soul_has_boundaries_sentence"] = "Private things stay private. Period." in soul_content

    # "## Vibe" section that includes either "Reliable" or "generally casual" (case-insensitive for content presence)
    checks["soul_vibe_section_and_reliable_or_generally_casual"] = False
    if soul_read_ok:
        has_vibe_section = "## Vibe" in soul_content
        low = soul_content.lower()
        has_term = ("reliable" in low) or ("generally casual" in low)
        checks["soul_vibe_section_and_reliable_or_generally_casual"] = bool(has_vibe_section and has_term)

    # 4) bio.html checks
    checks["bio_exists"] = os.path.isfile(bio_html_path)
    checks["bio_has_about_nova"] = False
    if checks["bio_exists"]:
        checks["bio_has_about_nova"] = file_contains(bio_html_path, "About Nova")

    # 5) exported_schema.json checks
    checks["exported_exists"] = os.path.isfile(exported_schema_path)
    exported_json, exported_valid = (None, False)
    if checks["exported_exists"]:
        exported_json, exported_valid = load_json(exported_schema_path)
    checks["exported_json_valid"] = bool(exported_valid)

    checks["exported_protocol_AIEOS"] = False
    checks["exported_nickname_Nova"] = False
    checks["exported_style_descriptors_include_warm"] = False

    if exported_valid and isinstance(exported_json, dict):
        try:
            checks["exported_protocol_AIEOS"] = exported_json.get("standard", {}).get("protocol") == "AIEOS"
        except Exception:
            checks["exported_protocol_AIEOS"] = False
        try:
            checks["exported_nickname_Nova"] = exported_json.get("identity", {}).get("names", {}).get("nickname") == "Nova"
        except Exception:
            checks["exported_nickname_Nova"] = False
        try:
            descriptors = exported_json.get("linguistics", {}).get("text_style", {}).get("style_descriptors", [])
            if isinstance(descriptors, list):
                lower_list = [str(x).lower() for x in descriptors]
                checks["exported_style_descriptors_include_warm"] = "warm" in lower_list
        except Exception:
            checks["exported_style_descriptors_include_warm"] = False

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure if no outputs present, reward is 0.0 (this naturally holds)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()