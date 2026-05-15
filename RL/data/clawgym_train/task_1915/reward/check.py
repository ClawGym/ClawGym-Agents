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

def safe_json_load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_excluded_servers_from_yaml(yaml_text):
    excluded = set()
    if not yaml_text:
        return excluded
    known = {"filesystem","fetch","memory","sqlite","postgres","github","puppeteer","brave-search"}
    # Inline lists like: exclude_servers: [puppeteer, brave-search]
    for m in re.findall(r'(?im)^\s*exclude\w*\s*:\s*\[([^\]]+)\]\s*$', yaml_text):
        items = [x.strip().strip('\'"') for x in m.split(",")]
        for it in items:
            lit = it.strip().lower()
            if lit in known:
                excluded.add(lit)
    # Block lists:
    lines = yaml_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'(?im)^\s*exclude\w*\s*:\s*$', line):
            i += 1
            while i < len(lines):
                l = lines[i]
                m = re.match(r'^\s*-\s*([A-Za-z0-9_\-]+)', l)
                if m:
                    name = m.group(1).strip().lower()
                    if name in known:
                        excluded.add(name)
                    i += 1
                    continue
                # Stop block on first non list item
                break
            continue
        i += 1
    return excluded

def find_preferred_db(obj):
    def norm_db(val):
        v = str(val).strip().lower()
        if v in {"postgresql", "postgres"}:
            return "postgres"
        if v in {"sqlite"}:
            return "sqlite"
        return None
    # DFS search for likely keys or values
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if isinstance(v, str):
                if ("database" in kl) or (kl in {"db", "preferred_db", "preferred-database"}):
                    n = norm_db(v)
                    if n:
                        return n
            elif isinstance(v, (dict, list)):
                found = find_preferred_db(v)
                if found:
                    return found
    elif isinstance(obj, list):
        for it in obj:
            found = find_preferred_db(it)
            if found:
                return found
    return None

def validate_selection_sections(md_text, server_names):
    if not md_text:
        return False
    lines = md_text.splitlines()
    # Find sections by "Server: <name>" lines
    indices = []
    for idx, line in enumerate(lines):
        if line.startswith("Server: "):
            # Extract server name
            name = line[len("Server: "):].strip()
            indices.append((idx, name))
    # Build section spans
    sections = []
    for j, (idx, name) in enumerate(indices):
        start = idx
        end = indices[j+1][0] if j+1 < len(indices) else len(lines)
        sections.append((name, start, end))
    # Map name -> section text
    section_map = {}
    for name, s, e in sections:
        section_map[name] = "\n".join(lines[s:e])
    # Each server in config must have a section with Install and URL lines inside that section
    for srv in server_names:
        if srv not in section_map:
            return False
        sec = section_map[srv]
        if ("Install:" not in sec) or ("URL:" not in sec):
            return False
    return True

def count_hashtags(text):
    if not text:
        return 0
    # Count tokens starting with '#'
    tokens = re.findall(r'(^|\s)#\S+', text)
    # tokens includes leading-group captures; count occurrences of '#'
    # Better: split by whitespace and count startswith '#'
    count = 0
    for tok in re.split(r'\s+', text):
        if tok.startswith("#") and len(tok) > 1:
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Read inputs (reference only)
    req_yaml_path = os.path.join(input_dir, "requirements.yaml")
    team_json_path = os.path.join(input_dir, "team_prefs.json")
    req_text = read_text(req_yaml_path)
    team_json = safe_json_load(team_json_path)

    excluded_servers = set()
    if req_text:
        excluded_servers = parse_excluded_servers_from_yaml(req_text)

    preferred_db = None
    if team_json is not None:
        preferred_db = find_preferred_db(team_json)
    # Fallback mapping if team specified under different casing/value directly
    if not preferred_db and req_text:
        # Try to find preferred database in yaml via simple regex
        m = re.search(r'(?im)^\s*preferred[_\- ]?database\s*:\s*("?)([A-Za-z0-9_\-]+)\1\s*$', req_text)
        if m:
            val = m.group(2).strip().lower()
            if val in {"sqlite", "postgres", "postgresql"}:
                preferred_db = "postgres" if val in {"postgres", "postgresql"} else "sqlite"

    # Paths to outputs
    mcp_json_path = os.path.join(output_dir, "config", "mcp.json")
    selection_md_path = os.path.join(output_dir, "docs", "selection.md")
    checklist_json_path = os.path.join(output_dir, "security", "checklist.json")
    hardening_md_path = os.path.join(output_dir, "security", "hardening.md")
    announcement_md_path = os.path.join(output_dir, "communications", "announcement.md")

    checks = {
        "has_mcp_config": False,
        "mcp_json_valid": False,
        "mcp_has_required_servers": False,
        "mcp_no_excluded_servers": False,
        "mcp_entries_structured": False,
        "selection_md_exists": False,
        "selection_has_sections_for_all_servers": False,
        "security_checklist_valid": False,
        "hardening_md_keywords": False,
        "announcement_md_structure": False,
    }

    mcp_data = None
    if os.path.isfile(mcp_json_path):
        checks["has_mcp_config"] = True
        mcp_data = safe_json_load(mcp_json_path)
        if isinstance(mcp_data, dict) and isinstance(mcp_data.get("mcpServers"), dict):
            checks["mcp_json_valid"] = True

    # Validate required servers and entries
    server_keys = []
    if checks["mcp_json_valid"]:
        mcp_servers = mcp_data["mcpServers"]
        server_keys = list(mcp_servers.keys())

        # Required servers: filesystem, fetch, memory, and preferred database (if specified)
        required = {"filesystem", "fetch", "memory"}
        if preferred_db in {"sqlite", "postgres"}:
            required.add(preferred_db)
        # All required must be present
        if required.issubset(set(server_keys)):
            checks["mcp_has_required_servers"] = True

        # No excluded servers present
        if not excluded_servers:
            # If no explicit excluded servers from inputs, consider this check as pass by default
            checks["mcp_no_excluded_servers"] = True
        else:
            absent = all(ex not in mcp_servers for ex in excluded_servers)
            if absent:
                checks["mcp_no_excluded_servers"] = True

        # Validate each entry has correct "command" and "args"
        all_structured = True
        for name, entry in mcp_servers.items():
            if not isinstance(entry, dict):
                all_structured = False
                break
            cmd = entry.get("command")
            args = entry.get("args")
            expected_args = ["-y", f"@modelcontextprotocol/server-{name}"]
            if cmd != "npx":
                all_structured = False
                break
            if not isinstance(args, list) or args != expected_args:
                all_structured = False
                break
        if all_structured:
            checks["mcp_entries_structured"] = True

    # Validate docs/selection.md
    if os.path.isfile(selection_md_path):
        checks["selection_md_exists"] = True
        sel_text = read_text(selection_md_path) or ""
        # For each server in the config, ensure a section present with Install and URL lines
        if server_keys:
            if validate_selection_sections(sel_text, server_keys):
                checks["selection_has_sections_for_all_servers"] = True
        else:
            # If no config, cannot validate sections for servers
            checks["selection_has_sections_for_all_servers"] = False

    # Validate security/checklist.json
    if os.path.isfile(checklist_json_path):
        data = safe_json_load(checklist_json_path)
        if isinstance(data, dict):
            tel = data.get("telemetry_opt_out")
            wrap_action = data.get("wrap_action")
            risk_notes = data.get("risk_notes")
            if isinstance(tel, bool) and isinstance(wrap_action, str) and wrap_action in {"dry-run", "active", "undo"} and isinstance(risk_notes, list) and len(risk_notes) >= 3:
                checks["security_checklist_valid"] = True

    # Validate security/hardening.md keywords
    if os.path.isfile(hardening_md_path):
        txt = read_text(hardening_md_path) or ""
        low = txt.lower()
        required_kw = ["wrap", "scan", "undo", "policy", "threat"]
        if all(kw in low for kw in required_kw):
            checks["hardening_md_keywords"] = True

    # Validate communications/announcement.md
    if os.path.isfile(announcement_md_path):
        txt = read_text(announcement_md_path) or ""
        lines = txt.splitlines()
        has_hook = any(l.lstrip().startswith("Hook:") for l in lines)
        has_cta = any(l.lstrip().startswith("CTA:") for l in lines)
        hashtag_count = count_hashtags(txt)
        if has_hook and has_cta and hashtag_count >= 3:
            checks["announcement_md_structure"] = True

    # Compute reward: proportion of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or empty, force reward = 0.0
    # Consider "empty" if none of the core artifacts exist
    core_paths = [mcp_json_path, selection_md_path, checklist_json_path, hardening_md_path, announcement_md_path]
    if not any(os.path.isfile(p) for p in core_paths):
        reward = 0.0

    # Print single JSON object
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()