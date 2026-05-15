import json
import os
import re
import sys
from typing import Any, Dict, List

def get_workspace_root(argv: List[str]) -> str:
    if len(argv) > 1 and argv[1]:
        return argv[1]
    return "/root/.openclaw/workspace"

def load_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        return text, json.loads(text)
    except Exception:
        return None, None

def is_non_empty_string(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""

def check_threat_assessment(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    required_keys = ["hands", "stance", "face", "voice", "context", "threat_level"]
    for k in required_keys:
        if k not in obj:
            return False
    # Non-empty strings
    for k in ["hands", "stance", "face", "voice", "context"]:
        if not is_non_empty_string(obj.get(k)):
            return False
    # threat_level
    tl = obj.get("threat_level")
    if tl not in {"LOW", "MEDIUM", "HIGH"}:
        return False
    return True

def check_body_positioning(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    req_keys = ["angle", "reactionary_gap_ft", "hands", "feet", "exit_strategy"]
    for k in req_keys:
        if k not in obj:
            return False
    # angle contains "45"
    angle = obj.get("angle", "")
    if not (isinstance(angle, str) and "45" in angle):
        return False
    # reactionary_gap_ft number >= 6
    rg = obj.get("reactionary_gap_ft")
    if not isinstance(rg, (int, float)):
        return False
    if rg < 6:
        return False
    # hands contains "open" and "palms"
    hands = obj.get("hands", "")
    if not (isinstance(hands, str) and ("open" in hands.lower()) and ("palms" in hands.lower())):
        return False
    # feet contains "balls"
    feet = obj.get("feet", "")
    if not (isinstance(feet, str) and ("balls" in feet.lower())):
        return False
    # exit_strategy non-empty string
    exit_strategy = obj.get("exit_strategy")
    if not is_non_empty_string(exit_strategy):
        return False
    return True

def check_voice_and_tone(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    req = ["volume_start", "pace", "pitch", "tone"]
    for k in req:
        if k not in obj:
            return False
    vol = obj.get("volume_start", "")
    if not isinstance(vol, str):
        return False
    # must mention matching at ~70% (accept 70%, ~70, 70 %)
    vol_l = vol.lower()
    has_70 = bool(re.search(r"(~?\s*70\s*%)|(~\s*70)|(70\s*%)", vol_l))
    if not has_70 and "70" not in vol_l:
        return False
    pace = obj.get("pace", "")
    if not (isinstance(pace, str) and ("half" in pace.lower())):
        return False
    pitch = obj.get("pitch", "")
    if not (isinstance(pitch, str) and ("low" in pitch.lower())):
        return False
    tone = obj.get("tone", "")
    tone_l = tone.lower() if isinstance(tone, str) else ""
    if not ("respectful" in tone_l or "non-confrontational" in tone_l):
        return False
    return True

def exactly_two_options(text: str) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    # Count ' or ' as a separate word
    ors = re.findall(r"\bor\b", text, flags=re.IGNORECASE)
    if len(ors) != 1:
        return False
    parts = re.split(r"\bor\b", text, flags=re.IGNORECASE, maxsplit=1)
    if len(parts) != 2:
        return False
    left = parts[0].strip()
    right = parts[1].strip()
    # Ensure both sides have some alphabetic content to be considered concrete
    has_left = bool(re.search(r"[A-Za-z]", left))
    has_right = bool(re.search(r"[A-Za-z]", right))
    return has_left and has_right

def check_verbal_techniques(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    req = ["acknowledgment", "open_questions", "paraphrase", "limited_choices", "boundary_statement"]
    for k in req:
        if k not in obj:
            return False
    if not is_non_empty_string(obj.get("acknowledgment")):
        return False
    oq = obj.get("open_questions")
    if not (isinstance(oq, list) and len(oq) >= 2 and all(is_non_empty_string(x) for x in oq)):
        return False
    if not is_non_empty_string(obj.get("paraphrase")):
        return False
    lc = obj.get("limited_choices")
    if not (isinstance(lc, str) and exactly_two_options(lc)):
        return False
    if not is_non_empty_string(obj.get("boundary_statement")):
        return False
    return True

ALLOWED_PRE_ATTACK = {
    "target glance",
    "thousand-yard stare",
    "blading",
    "sudden silence",
    "fists clenching",
    "shoulders rise",
    "removing glasses/hat/jacket",
    "closing distance despite step-backs",
}

def check_pre_attack_list(items: Any) -> bool:
    if not isinstance(items, list):
        return False
    if len(items) < 3:
        return False
    # All items must be from allowed set
    for it in items:
        if not isinstance(it, str):
            return False
        if it not in ALLOWED_PRE_ATTACK:
            return False
    return True

def check_protocol(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    if "name" not in obj or "steps" not in obj:
        return False
    if not is_non_empty_string(obj.get("name")):
        return False
    steps = obj.get("steps")
    if not (isinstance(steps, list) and len(steps) >= 3 and all(is_non_empty_string(s) for s in steps)):
        return False
    return True

def check_disengage_criteria(items: Any) -> bool:
    if not isinstance(items, list):
        return False
    if len(items) < 2:
        return False
    if not all(is_non_empty_string(x) for x in items):
        return False
    return True

def contains_prohibited_phrases(text: str) -> bool:
    # Case-insensitive search for exact prohibited phrases as substrings
    prohibited = [
        "calm down",
        "you need to relax",
        "that's not a big deal",
        "there's nothing i can do",
        "you're being unreasonable",
        "it's policy",
    ]
    tl = text.lower()
    return any(p in tl for p in prohibited)

def safe_get(d: Dict[str, Any], *keys: str, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        if k not in cur:
            return default
        cur = cur[k]
    return cur

def scenario_specific_angry(scen: Dict[str, Any]) -> bool:
    # Name includes "retail" or "food service"
    protocol = scen.get("scenario_protocol", {})
    name = protocol.get("name", "")
    if not isinstance(name, str):
        return False
    name_l = name.lower()
    if not ("retail" in name_l or "food service" in name_l):
        return False
    # Steps mention "counter" and "manager"
    steps = protocol.get("steps", [])
    if not isinstance(steps, list):
        return False
    has_counter = any(isinstance(s, str) and ("counter" in s.lower()) for s in steps)
    has_manager = any(isinstance(s, str) and ("manager" in s.lower()) for s in steps)
    return has_counter and has_manager

def scenario_specific_family(scen: Dict[str, Any]) -> bool:
    # Name includes "family"
    protocol = scen.get("scenario_protocol", {})
    name = protocol.get("name", "")
    if not (isinstance(name, str) and "family" in name.lower()):
        return False
    # "You might be right" present within verbal_techniques fields
    vt = scen.get("verbal_techniques", {})
    vt_texts = []
    if isinstance(vt, dict):
        for v in vt.values():
            if isinstance(v, str):
                vt_texts.append(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        vt_texts.append(item)
    vt_join = " ".join(vt_texts)
    if "You might be right" not in vt_join:
        return False
    # At least one protocol step includes environment change: outside, air, or balcony
    steps = protocol.get("steps", [])
    if not isinstance(steps, list):
        return False
    env_words = ("outside", "air", "balcony")
    has_env = any(isinstance(s, str) and any(w in s.lower() for w in env_words) for s in steps)
    return has_env

def main():
    workspace_root = get_workspace_root(sys.argv)
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "has_output_file": False,
        "valid_json": False,
        "top_level_types_ok": False,
        "plan_version_ok": False,
        "scenarios_present": False,
        "angry_threat_assessment_ok": False,
        "angry_body_positioning_ok": False,
        "angry_voice_and_tone_ok": False,
        "angry_verbal_techniques_ok": False,
        "angry_pre_attack_ok": False,
        "angry_protocol_ok": False,
        "angry_disengage_ok": False,
        "angry_prohibited_flag_false": False,
        "angry_specific_requirements_ok": False,
        "family_threat_assessment_ok": False,
        "family_body_positioning_ok": False,
        "family_voice_and_tone_ok": False,
        "family_verbal_techniques_ok": False,
        "family_pre_attack_ok": False,
        "family_protocol_ok": False,
        "family_disengage_ok": False,
        "family_prohibited_flag_false": False,
        "family_specific_requirements_ok": False,
        "prohibited_phrases_absent": False,
        "global_rules_present": False,
    }

    plan_path = os.path.join(output_dir, "plan.json")
    if os.path.isfile(plan_path):
        checks["has_output_file"] = True
        raw_text, data = load_json_file(plan_path)
        if isinstance(data, dict) and isinstance(raw_text, str):
            checks["valid_json"] = True
            # top-level types
            plan_version = data.get("plan_version")
            scenarios = data.get("scenarios")
            global_safety_rules = data.get("global_safety_rules")
            if isinstance(plan_version, str) and isinstance(scenarios, dict) and isinstance(global_safety_rules, list):
                checks["top_level_types_ok"] = True
            # plan_version
            if plan_version == "1.0":
                checks["plan_version_ok"] = True
            # scenarios present
            if isinstance(scenarios, dict) and "angry_retail_customer" in scenarios and "family_escalation" in scenarios:
                checks["scenarios_present"] = True

            # prohibited phrases
            if raw_text is not None and not contains_prohibited_phrases(raw_text):
                checks["prohibited_phrases_absent"] = True

            # global rules exact inclusion
            required_global_rules = [
                "Your personal safety is the top priority",
                "Never block someone's exit path",
                "Keep hands visible; do not touch an agitated person unless they are in immediate danger",
                "Do not attempt to physically restrain someone unless trained",
            ]
            if isinstance(global_safety_rules, list):
                # Ensure exact presence
                present = all(rule in global_safety_rules for rule in required_global_rules)
                if present:
                    checks["global_rules_present"] = True

            # Validate each scenario
            if isinstance(scenarios, dict):
                angry = scenarios.get("angry_retail_customer", {})
                family = scenarios.get("family_escalation", {})

                # Angry Retail Customer
                if isinstance(angry, dict):
                    if check_threat_assessment(angry.get("threat_assessment")):
                        checks["angry_threat_assessment_ok"] = True
                    if check_body_positioning(angry.get("body_positioning")):
                        checks["angry_body_positioning_ok"] = True
                    if check_voice_and_tone(angry.get("voice_and_tone")):
                        checks["angry_voice_and_tone_ok"] = True
                    if check_verbal_techniques(angry.get("verbal_techniques")):
                        checks["angry_verbal_techniques_ok"] = True
                    if check_pre_attack_list(angry.get("pre_attack_indicators_to_watch")):
                        checks["angry_pre_attack_ok"] = True
                    if check_protocol(angry.get("scenario_protocol")):
                        checks["angry_protocol_ok"] = True
                    dc = angry.get("disengage_criteria")
                    if check_disengage_criteria(dc):
                        checks["angry_disengage_ok"] = True
                    # Prohibited flag
                    pf = angry.get("prohibited_phrases_used")
                    if pf is False:
                        checks["angry_prohibited_flag_false"] = True
                    # Scenario-specific
                    if scenario_specific_angry(angry):
                        checks["angry_specific_requirements_ok"] = True

                # Family Escalation
                if isinstance(family, dict):
                    if check_threat_assessment(family.get("threat_assessment")):
                        checks["family_threat_assessment_ok"] = True
                    if check_body_positioning(family.get("body_positioning")):
                        checks["family_body_positioning_ok"] = True
                    if check_voice_and_tone(family.get("voice_and_tone")):
                        checks["family_voice_and_tone_ok"] = True
                    if check_verbal_techniques(family.get("verbal_techniques")):
                        checks["family_verbal_techniques_ok"] = True
                    if check_pre_attack_list(family.get("pre_attack_indicators_to_watch")):
                        checks["family_pre_attack_ok"] = True
                    if check_protocol(family.get("scenario_protocol")):
                        checks["family_protocol_ok"] = True
                    dc2 = family.get("disengage_criteria")
                    if check_disengage_criteria(dc2):
                        checks["family_disengage_ok"] = True
                    pf2 = family.get("prohibited_phrases_used")
                    if pf2 is False:
                        checks["family_prohibited_flag_false"] = True
                    if scenario_specific_family(family):
                        checks["family_specific_requirements_ok"] = True

    # Determine overall reward: all checks that represent core requirements must pass
    required_keys = [
        "has_output_file",
        "valid_json",
        "top_level_types_ok",
        "plan_version_ok",
        "scenarios_present",
        "prohibited_phrases_absent",
        "global_rules_present",
        "angry_threat_assessment_ok",
        "angry_body_positioning_ok",
        "angry_voice_and_tone_ok",
        "angry_verbal_techniques_ok",
        "angry_pre_attack_ok",
        "angry_protocol_ok",
        "angry_disengage_ok",
        "angry_prohibited_flag_false",
        "angry_specific_requirements_ok",
        "family_threat_assessment_ok",
        "family_body_positioning_ok",
        "family_voice_and_tone_ok",
        "family_verbal_techniques_ok",
        "family_pre_attack_ok",
        "family_protocol_ok",
        "family_disengage_ok",
        "family_prohibited_flag_false",
        "family_specific_requirements_ok",
    ]
    all_pass = all(checks.get(k, False) for k in required_keys)
    reward = 1.0 if all_pass else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()