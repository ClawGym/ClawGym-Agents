import json
import os
import sys

def load_json_array(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        return None
    return None

def contains_in_order(text, tokens):
    start = 0
    for tok in tokens:
        idx = text.find(tok, start)
        if idx == -1:
            return False
        start = idx + len(tok)
    return True

def has_any_chars(text, chars):
    return any(c in text for c in chars)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def file_size(path):
    try:
        return os.path.getsize(path)
    except Exception:
        return -1

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False until positively verified)
    checks = {
        "normalized_correct": False,
        "unsupported_empty": False,
        "progression_valid": False,
        "diagram_G_valid": False,
        "diagram_D_valid": False,
        "diagram_Em_valid": False,
        "diagram_C_valid": False,
    }

    # 1) normalized_chords.json exact array ["G","D","Em","C"]
    norm_path = os.path.join(output_dir, "normalized_chords.json")
    if os.path.isfile(norm_path):
        arr = load_json_array(norm_path)
        if arr == ["G", "D", "Em", "C"]:
            checks["normalized_correct"] = True

    # 2) unsupported.json exists and is empty array
    unsupported_path = os.path.join(output_dir, "unsupported.json")
    if os.path.isfile(unsupported_path):
        arr = load_json_array(unsupported_path)
        if isinstance(arr, list) and len(arr) == 0:
            checks["unsupported_empty"] = True

    # 3) progression.txt exists, contains chord names in order and contains ascii diagram chars
    progression_path = os.path.join(output_dir, "progression.txt")
    if os.path.isfile(progression_path):
        txt = read_text(progression_path)
        if isinstance(txt, str):
            in_order = contains_in_order(txt, ["G", "D", "Em", "C"])
            ascii_ok = has_any_chars(txt, ["╒", "└", "┘", "◯", "✕"])
            if in_order and ascii_ok:
                checks["progression_valid"] = True

    # 4) Individual diagrams: each must exist, be >50 bytes, and contain box-drawing + indicator
    diag_requirements = [
        ("G", os.path.join(output_dir, "diagrams", "G.txt"), "diagram_G_valid"),
        ("D", os.path.join(output_dir, "diagrams", "D.txt"), "diagram_D_valid"),
        ("Em", os.path.join(output_dir, "diagrams", "Em.txt"), "diagram_Em_valid"),
        ("C", os.path.join(output_dir, "diagrams", "C.txt"), "diagram_C_valid"),
    ]
    box_chars = ["╒", "└", "┘"]
    indicator_chars = ["◯", "✕"]

    for chord_name, path, check_key in diag_requirements:
        if os.path.isfile(path):
            size_ok = file_size(path) > 50
            txt = read_text(path)
            if isinstance(txt, str) and size_ok:
                has_box = has_any_chars(txt, box_chars)
                has_indicator = has_any_chars(txt, indicator_chars)
                if has_box and has_indicator:
                    checks[check_key] = True

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure baseline no-output yields 0.0
    if not os.path.isdir(output_dir) or all(not v for v in checks.values()):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()