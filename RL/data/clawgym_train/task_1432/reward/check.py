import json
import os
import re
import sys

def read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def read_bytes(path):
    try:
        with open(path, 'rb') as f:
            return f.read()
    except Exception:
        return None

def sanitize_agent_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = name.lower()
    s = s.replace(" ", "-").replace("_", "-")
    s = re.sub(r'[^a-z0-9\-]', '', s)
    return s

def get_expected_from_worker(input_dir):
    primary_path = os.path.join(input_dir, "worker_result.json")
    reroll_path = os.path.join(input_dir, "worker_result_reroll.json")
    primary = read_json(primary_path)
    if not isinstance(primary, dict):
        return None
    use_reroll = False
    if primary.get("duplicate") is True:
        use_reroll = True
    final_data = read_json(reroll_path) if use_reroll else primary
    if not isinstance(final_data, dict):
        return None
    # Extract fields robustly
    op = final_data.get("operator") or {}
    en_name = op.get("en_name") or final_data.get("en_name")
    cn_name = op.get("cn_name") or final_data.get("cn_name")
    stars = final_data.get("stars")
    try:
        stars_int = int(stars)
    except Exception:
        stars_int = None
    source = "worker_result_reroll" if use_reroll else "worker_result"
    return {
        "en_name": en_name,
        "cn_name": cn_name,
        "stars": stars_int,
        "final_result_source": source
    }

def get_meta_for_en_name(input_dir, en_name):
    meta_path = os.path.join(input_dir, "meta.json")
    meta = read_json(meta_path)
    if not isinstance(meta, dict):
        return None
    # exact key
    if en_name in meta and isinstance(meta[en_name], dict):
        entry = meta[en_name]
    else:
        # try case-insensitive
        key = None
        for k in meta.keys():
            if isinstance(k, str) and isinstance(en_name, str) and k.lower() == en_name.lower():
                key = k
                break
        entry = meta.get(key) if key else None
        if not isinstance(entry, dict):
            return None
    # Support different capitalizations for keys
    cls = entry.get("Class") if "Class" in entry else entry.get("class")
    fac = entry.get("Faction") if "Faction" in entry else entry.get("faction")
    if cls is None or fac is None:
        return None
    return {"Class": cls, "Faction": fac}

def find_headings_in_order(lines, headings):
    """
    Accept lines that may have optional leading '#' heading markers and whitespace.
    Returns indices of each heading if found in order, else None.
    """
    indices = []
    start_idx = 0
    for h in headings:
        found = False
        for i in range(start_idx, len(lines)):
            # Normalize line: strip, remove leading '#' and surrounding whitespace
            raw = lines[i].rstrip("\n")
            norm = raw.strip()
            # Remove any leading markdown heading markers and following spaces
            norm2 = norm
            if norm2.startswith("#"):
                norm2 = norm2.lstrip("#").strip()
            if norm2 == h:
                indices.append(i)
                start_idx = i + 1
                found = True
                break
        if not found:
            return None
    return indices

def section_slice(lines, start_idx, next_idx):
    if start_idx is None:
        return ""
    if next_idx is None or next_idx <= start_idx:
        content_lines = lines[start_idx+1:]
    else:
        content_lines = lines[start_idx+1:next_idx]
    return "\n".join([l.rstrip("\n") for l in content_lines])

def count_unique_exact_quotes_in_text(text, quotes_list):
    present = set()
    for q in quotes_list:
        # Expect exact substring match
        if isinstance(q, str) and q and q in text:
            present.add(q)
    return len(present)

def check_summary(output_dir, expected):
    path = os.path.join(output_dir, "summary.json")
    data = read_json(path)
    if not isinstance(data, dict):
        return False
    # Required keys
    required_keys = ["en_name", "cn_name", "stars", "agent_name", "final_result_source"]
    for k in required_keys:
        if k not in data:
            return False
    # Compare values
    if data["en_name"] != expected["en_name"]:
        return False
    if data["cn_name"] != expected["cn_name"]:
        return False
    try:
        stars_val = int(data["stars"])
    except Exception:
        return False
    if stars_val != expected["stars"]:
        return False
    # agent_name sanitized
    expected_agent = sanitize_agent_name(expected["en_name"] or "")
    if data["agent_name"] != expected_agent:
        return False
    # final_result_source
    if data["final_result_source"] != expected["final_result_source"]:
        return False
    return True

def check_identity(output_dir, expected, meta):
    path = os.path.join(output_dir, "IDENTITY.md")
    content = read_text(path)
    if content is None:
        return False
    lines = [l.strip() for l in content.splitlines() if l.strip() != ""]
    # Find fields anywhere in file
    en_val = cn_val = cls_val = fac_val = None
    for l in lines:
        m = re.match(r'^\-+\s*Name\s*\(EN\)\s*:\s*(.+)$', l)
        if m:
            en_val = m.group(1).strip()
            continue
        m = re.match(r'^\-+\s*Name\s*\(CN\)\s*:\s*(.+)$', l)
        if m:
            cn_val = m.group(1).strip()
            continue
        m = re.match(r'^\-+\s*Class\s*:\s*(.+)$', l)
        if m:
            cls_val = m.group(1).strip()
            continue
        m = re.match(r'^\-+\s*Faction\s*:\s*(.+)$', l)
        if m:
            fac_val = m.group(1).strip()
            continue
    if en_val is None or cn_val is None or cls_val is None or fac_val is None:
        return False
    if en_val != expected["en_name"]:
        return False
    if cn_val != expected["cn_name"]:
        return False
    if cls_val != meta["Class"]:
        return False
    if fac_val != meta["Faction"]:
        return False
    return True

def check_soul(output_dir, input_dir, expected):
    path = os.path.join(output_dir, "SOUL.md")
    content = read_text(path)
    if content is None:
        return {
            "soul_headings_ok": False,
            "soul_names_and_star_ok": False,
            "soul_reference_quotes_ok": False
        }
    lines = content.splitlines()
    headings = [
        "Core Identity",
        "Voice and Mannerisms",
        "Relationships",
        "Themes",
        "How to Embody",
        "Reference: Original Voice Lines"
    ]
    idxs = find_headings_in_order(lines, headings)
    headings_ok = idxs is not None
    names_star_ok = False
    quotes_ok = False
    if headings_ok:
        # Names and star rating presence
        text_lower = content
        en_name = expected["en_name"] or ""
        cn_name = expected["cn_name"] or ""
        star_str = f"{expected['stars']}★" if isinstance(expected["stars"], int) else None
        has_en = en_name in content if en_name else False
        has_cn = cn_name in content if cn_name else False
        has_star = star_str in content if star_str else False
        names_star_ok = bool(has_en and has_cn and has_star)
        # Reference quotes
        dialogue_path = os.path.join(input_dir, "dialogue.json")
        dialogue = read_json(dialogue_path)
        if isinstance(dialogue, list):
            # Extract the "Reference" section content
            ref_start = idxs[-1]  # index of reference heading
            # find next heading after ref_start (none expected)
            next_idx = None
            # compute where next heading occurs (should be none; but safe)
            for i in range(ref_start + 1, len(lines)):
                raw = lines[i].strip()
                if raw.startswith("#"):
                    # Normalize possible heading text
                    norm2 = raw.lstrip("#").strip()
                    if norm2 in headings:
                        next_idx = i
                        break
                elif raw in headings:
                    next_idx = i
                    break
            ref_text = section_slice(lines, ref_start, next_idx)
            count = count_unique_exact_quotes_in_text(ref_text, dialogue)
            quotes_ok = count >= 3
    return {
        "soul_headings_ok": bool(headings_ok),
        "soul_names_and_star_ok": bool(names_star_ok),
        "soul_reference_quotes_ok": bool(quotes_ok)
    }

def check_greeting(output_dir, input_dir):
    path = os.path.join(output_dir, "greeting.txt")
    b = read_bytes(path)
    if b is None:
        return False
    # Must not contain newline characters
    if b'\n' in b or b'\r' in b:
        return False
    try:
        s = b.decode('utf-8')
    except Exception:
        return False
    dialogue = read_json(os.path.join(input_dir, "dialogue.json"))
    if not isinstance(dialogue, list):
        return False
    for q in dialogue:
        if isinstance(q, str) and s == q:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # Initialize checks
    checks = {
        "selected_final_input": False,  # diagnostic; not used for positive reward
        "summary_ok": False,
        "identity_ok": False,
        "soul_headings_ok": False,
        "soul_names_and_star_ok": False,
        "soul_reference_quotes_ok": False,
        "greeting_ok": False
    }
    expected = get_expected_from_worker(input_dir)
    if expected is not None and expected.get("en_name") and expected.get("cn_name") and expected.get("stars") is not None:
        checks["selected_final_input"] = True
        # summary.json
        if check_summary(output_dir, expected):
            checks["summary_ok"] = True
        # identity.md
        meta = get_meta_for_en_name(input_dir, expected["en_name"])
        if meta is not None and check_identity(output_dir, expected, meta):
            checks["identity_ok"] = True
        # soul.md
        soul_checks = check_soul(output_dir, input_dir, expected)
        checks.update(soul_checks)
        # greeting
        if check_greeting(output_dir, input_dir):
            checks["greeting_ok"] = True
    # Compute reward as average of output-dependent checks
    scored_keys = [
        "summary_ok",
        "identity_ok",
        "soul_headings_ok",
        "soul_names_and_star_ok",
        "soul_reference_quotes_ok",
        "greeting_ok"
    ]
    total = len(scored_keys)
    passed = sum(1 for k in scored_keys if checks[k])
    reward = (passed / total) if total > 0 else 0.0
    # Ensure baseline: if output is empty/missing, keep reward 0.0 (our logic already yields 0.0)
    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object as the last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()