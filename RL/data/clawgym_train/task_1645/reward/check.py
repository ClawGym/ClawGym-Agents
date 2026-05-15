import json
import os
import re
import sys

def read_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    items.append(json.loads(s))
                except json.JSONDecodeError:
                    return None
        return items
    except FileNotFoundError:
        return None

def parse_scalar(val):
    if val is None:
        return None
    s = val.strip()
    # Strip surrounding quotes if present
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    sl = s.lower()
    if sl == "true":
        return True
    if sl == "false":
        return False
    # int
    try:
        if re.fullmatch(r"-?\d+", s):
            return int(s)
    except Exception:
        pass
    return s

def parse_yaml_loose(text):
    """
    Minimal YAML reader for the expected config structure.
    Supports:
      - top-level scalars (mode, mask_char, show_prefix, show_suffix, log_detections, log_path)
      - top-level lists: allow_channels, allow_patterns
      - patterns: list of dicts with keys name, regex, action, disabled, description
    """
    scalars = {}
    allow_channels = []
    allow_patterns = []
    patterns = []

    lines = text.splitlines()
    i = 0
    current_list = None  # None | 'allow_channels' | 'allow_patterns' | 'patterns'
    current_pattern = None
    in_patterns = False

    def is_top_level_key(line):
        return re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*:", line) is not None

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip("\n")
        # Skip empty or full-line comments
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue

        # Top-level scalar or list start
        m_top = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if m_top and not line.startswith(" "):
            key = m_top.group(1)
            rest = m_top.group(2)
            # If we were in patterns and had a current pattern, push it
            if in_patterns and current_pattern is not None:
                patterns.append(current_pattern)
                current_pattern = None
            # Handle top-level keys
            if rest != "":
                # scalar with value
                scalars[key] = parse_scalar(rest)
                current_list = None
                in_patterns = False
            else:
                # could be a list or nested mapping
                if key in ("allow_channels", "allow_patterns", "patterns"):
                    current_list = key
                    in_patterns = (key == "patterns")
                    # reset pattern on starting a list
                    if not in_patterns:
                        current_pattern = None
                else:
                    current_list = None
                    in_patterns = False
            i += 1
            continue

        # Inside a list
        if current_list in ("allow_channels", "allow_patterns"):
            m_item = re.match(r"^\s*-\s*(.+)$", line)
            if m_item:
                val = parse_scalar(m_item.group(1))
                if current_list == "allow_channels":
                    allow_channels.append(val)
                else:
                    allow_patterns.append(val)
                i += 1
                continue
            # If we encounter a new top-level key, reset list
            if is_top_level_key(line.lstrip()):
                current_list = None
                in_patterns = False
                continue
            # Otherwise skip
            i += 1
            continue

        # Inside patterns list
        if current_list == "patterns":
            # Start of a new pattern item
            m_pat_start = re.match(r"^\s*-\s*(.*)$", line)
            if m_pat_start:
                # push previous
                if current_pattern is not None:
                    patterns.append(current_pattern)
                current_pattern = {}
                rest = m_pat_start.group(1).strip()
                if rest:
                    # support inline "key: val" after '-'
                    m_inline = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$", rest)
                    if m_inline:
                        k = m_inline.group(1)
                        v = parse_scalar(m_inline.group(2))
                        current_pattern[k] = v
                i += 1
                continue
            # Pattern attributes lines
            m_attr = re.match(r"^\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$", line)
            if m_attr and current_pattern is not None:
                k = m_attr.group(1)
                v = parse_scalar(m_attr.group(2))
                current_pattern[k] = v
                i += 1
                continue
            # Possible end of patterns if a top-level key appears
            if is_top_level_key(line.lstrip()):
                if current_pattern is not None:
                    patterns.append(current_pattern)
                    current_pattern = None
                current_list = None
                in_patterns = False
                continue
            i += 1
            continue

        # Default advance
        i += 1

    # Append last pattern item if any
    if in_patterns and current_pattern is not None:
        patterns.append(current_pattern)

    return {
        "scalars": scalars,
        "allow_channels": allow_channels,
        "allow_patterns": allow_patterns,
        "patterns": patterns
    }

def normalize_regex_str(s):
    if s is None:
        return None
    return s.replace("\\\\", "\\")

def check_config(config_path):
    checks = {
        "config_exists": False,
        "config_settings_ok": False,
        "config_allowlists_ok": False,
        "config_patterns_ok": False
    }
    if not os.path.isfile(config_path):
        return checks
    checks["config_exists"] = True
    try:
        text = open(config_path, "r", encoding="utf-8").read()
    except Exception:
        return checks

    parsed = parse_yaml_loose(text)
    scalars = parsed["scalars"]
    allow_channels = parsed["allow_channels"]
    allow_patterns = parsed["allow_patterns"]
    patterns = parsed["patterns"]

    # Settings checks
    settings_ok = True
    settings_ok &= (scalars.get("mode") == "mask")
    settings_ok &= (scalars.get("mask_char") == "▓")
    settings_ok &= (scalars.get("show_prefix") == 2)
    settings_ok &= (scalars.get("show_suffix") == 0)
    settings_ok &= (scalars.get("log_detections") is True)
    settings_ok &= (scalars.get("log_path") == "output/detections.jsonl")
    checks["config_settings_ok"] = bool(settings_ok)

    # Allow lists
    allow_ok = True
    allow_ok &= ("internal-dev" in allow_channels)
    # Allow pattern for ^TEST:
    has_test_allow = any(isinstance(p, str) and re.search(r"^\^?TEST:", p) for p in allow_patterns)
    allow_ok &= has_test_allow
    checks["config_allowlists_ok"] = bool(allow_ok)

    # Patterns overrides and custom
    def find_pattern(name):
        for p in patterns:
            if isinstance(p, dict) and p.get("name") == name:
                return p
        return None

    p_priv_ip = find_pattern("private_ip_range")
    p_env = find_pattern("env_file_line")
    p_acme = find_pattern("acme_deploy_token")

    patt_ok = True
    patt_ok &= (p_priv_ip is not None and p_priv_ip.get("action") == "block")
    patt_ok &= (p_env is not None and (p_env.get("disabled") is True))
    if p_acme is not None:
        # regex comparison normalized
        req = r"\bACME-[A-Z0-9]{32}\b"
        got = p_acme.get("regex")
        got_norm = normalize_regex_str(got) if isinstance(got, str) else None
        patt_ok &= (p_acme.get("action") == "block" and (got_norm == req or got == req))
    else:
        patt_ok = False
    checks["config_patterns_ok"] = bool(patt_ok)

    return checks

def check_sanitized(input_path, sanitized_path):
    checks = {
        "sanitized_exists": False,
        "sanitized_valid_schema": False,
        "sanitized_count_matches_input": False,
        "preserves_order_and_original": False,
        "has_blocked_detection": False,
        "has_masked_message": False,
        "has_internal_dev_unchanged": False,
        "has_test_prefix_unchanged": False,
    }
    input_items = read_jsonl(input_path)
    sanitized_items = read_jsonl(sanitized_path)
    if sanitized_items is None:
        return checks
    checks["sanitized_exists"] = True

    # Validate schema line-by-line
    valid_schema = True
    exact_keys = {"channel", "original", "message", "blocked", "detections", "warnings"}
    for obj in sanitized_items:
        if not isinstance(obj, dict):
            valid_schema = False
            break
        if set(obj.keys()) != exact_keys:
            valid_schema = False
            break
        if not isinstance(obj.get("channel"), str):
            valid_schema = False
            break
        if not isinstance(obj.get("original"), str):
            valid_schema = False
            break
        if not isinstance(obj.get("message"), str):
            valid_schema = False
            break
        if not isinstance(obj.get("blocked"), bool):
            valid_schema = False
            break
        if not isinstance(obj.get("detections"), list) or not all(isinstance(x, str) for x in obj.get("detections")):
            valid_schema = False
            break
        if not isinstance(obj.get("warnings"), list) or not all(isinstance(x, str) for x in obj.get("warnings")):
            valid_schema = False
            break
    checks["sanitized_valid_schema"] = bool(valid_schema)

    # Count matches input
    if isinstance(input_items, list):
        checks["sanitized_count_matches_input"] = (len(sanitized_items) == len(input_items))
        # Preserve order and original channel/text
        preserves = True
        for in_obj, out_obj in zip(input_items, sanitized_items):
            if not isinstance(in_obj, dict):
                preserves = False
                break
            if in_obj.get("channel") != out_obj.get("channel"):
                preserves = False
                break
            if in_obj.get("text") != out_obj.get("original"):
                preserves = False
                break
        checks["preserves_order_and_original"] = bool(preserves)

    # Blocked detection present
    blocked_names_required = {"openai_key", "aws_access_key", "jwt_token", "private_ip_range", "acme_deploy_token"}
    has_blocked = False
    for obj in sanitized_items:
        if obj.get("blocked") is True:
            dets = set(obj.get("detections") or [])
            if dets & blocked_names_required:
                has_blocked = True
                break
    checks["has_blocked_detection"] = has_blocked

    # Masked message (non-blocked, contains mask, with two original chars prefix before mask)
    mask_char = "▓"
    mask_patterns_allowed = {"password_assignment", "bearer_token", "database_url", "generic_api_key"}
    masked_ok = False
    two_prefix_mask_re = re.compile(r"(^|[^▓])[^▓][^▓]▓+")
    for obj in sanitized_items:
        if obj.get("blocked") is False and mask_char in obj.get("message", ""):
            if two_prefix_mask_re.search(obj.get("message", "")):
                dets = set(obj.get("detections") or [])
                if dets & mask_patterns_allowed:
                    masked_ok = True
                    break
    checks["has_masked_message"] = masked_ok

    # internal-dev unchanged
    internal_ok = False
    for obj in sanitized_items:
        if obj.get("channel") == "internal-dev":
            if obj.get("blocked") is False and obj.get("message") == obj.get("original") and len(obj.get("detections") or []) == 0:
                internal_ok = True
                break
    checks["has_internal_dev_unchanged"] = internal_ok

    # TEST: unchanged
    test_ok = False
    for obj in sanitized_items:
        orig = obj.get("original", "")
        if isinstance(orig, str) and orig.startswith("TEST:"):
            if obj.get("message") == orig and len(obj.get("detections") or []) == 0:
                test_ok = True
                break
    checks["has_test_prefix_unchanged"] = test_ok

    return checks

def check_detections_log(path):
    checks = {
        "detections_log_exists_and_blocked_true": False
    }
    if not os.path.isfile(path):
        return checks
    try:
        found_blocked_true = False
        nonempty = False
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                nonempty = True
                try:
                    obj = json.loads(s)
                    if isinstance(obj, dict) and obj.get("blocked") is True:
                        found_blocked_true = True
                except json.JSONDecodeError:
                    continue
        checks["detections_log_exists_and_blocked_true"] = bool(nonempty and found_blocked_true)
    except Exception:
        pass
    return checks

def check_notes(path):
    checks = {
        "notes_exists_and_mentions": False,
        "notes_word_count_ok": False
    }
    if not os.path.isfile(path):
        return checks
    try:
        text = open(path, "r", encoding="utf-8").read()
    except Exception:
        return checks
    # word count
    words = re.findall(r"\b\w+\b", text)
    checks["notes_word_count_ok"] = (len(words) >= 140)
    # mentions at least three of: "allow", "mask_char", "private ip", "env", "acme", "log"
    lower = text.lower()
    topics = [
        "allow",
        "mask_char",
        "private ip",
        "env",
        "acme",
        "log",
    ]
    found = [t for t in topics if t in lower]
    checks["notes_exists_and_mentions"] = (len(set(found)) >= 3)
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    input_messages = os.path.join(input_dir, "messages.jsonl")
    cfg_path = os.path.join(output_dir, "config.yaml")
    sanitized_path = os.path.join(output_dir, "sanitized_messages.jsonl")
    detections_log_path = os.path.join(output_dir, "detections.jsonl")
    notes_path = os.path.join(output_dir, "notes.md")

    checks = {}
    # Config checks
    checks.update(check_config(cfg_path))
    # Sanitized checks
    checks.update(check_sanitized(input_messages, sanitized_path))
    # Detections log checks
    checks.update(check_detections_log(detections_log_path))
    # Notes checks
    checks.update(check_notes(notes_path))

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Enforce no-op baseline: if key deliverables are missing, reward should be 0
    key_files = [
        os.path.isfile(cfg_path),
        os.path.isfile(sanitized_path),
        os.path.isfile(detections_log_path),
        os.path.isfile(notes_path),
    ]
    if not all(key_files):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()