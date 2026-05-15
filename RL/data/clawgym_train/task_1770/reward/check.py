import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

def list_files_recursive(root, exts=None):
    out = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if exts is None or os.path.splitext(fn)[1].lower() in exts:
                out.append(os.path.join(dirpath, fn))
    return out

def parse_manifest_yaml(path):
    """
    Parse only needed fields from manifest.yaml without requiring PyYAML.
    Returns dict with keys: name, schema_version, type, context_searchable (list).
    """
    result = {"name": None, "schema_version": None, "type": None, "context_searchable": []}
    if not os.path.isfile(path):
        return result
    lines = read_text(path).splitlines()
    # Simple key parsing
    for line in lines:
        m = re.match(r'^\s*name:\s*(.+)\s*$', line)
        if m and result["name"] is None:
            val = m.group(1).strip().strip('"').strip("'")
            result["name"] = val
            continue
        m = re.match(r'^\s*schema_version:\s*(.+)\s*$', line)
        if m and result["schema_version"] is None:
            val = m.group(1).strip().strip('"').strip("'")
            result["schema_version"] = val
            continue
        m = re.match(r'^\s*type:\s*(.+)\s*$', line)
        if m and result["type"] is None:
            val = m.group(1).strip().strip('"').strip("'")
            result["type"] = val
            continue

    # Context.searchable list parsing by indentation
    # Find 'context:' block
    i = 0
    while i < len(lines):
        line = lines[i]
        ctx_match = re.match(r'^(\s*)context:\s*$', line)
        if ctx_match:
            ctx_indent = len(ctx_match.group(1))
            i += 1
            in_searchable = False
            searchable_indent = None
            while i < len(lines):
                l2 = lines[i]
                # break if indentation less or equal to context indent
                indent_l2 = len(re.match(r'^(\s*)', l2).group(1))
                if indent_l2 <= ctx_indent:
                    break
                # detect searchable
                s_match = re.match(r'^(\s*)searchable:\s*$', l2)
                if s_match:
                    in_searchable = True
                    searchable_indent = len(s_match.group(1))
                    i += 1
                    continue
                if in_searchable:
                    # items with '- '
                    item_match = re.match(r'^\s*-\s*(.+?)\s*$', l2)
                    if item_match:
                        item = item_match.group(1).strip().strip('"').strip("'")
                        result["context_searchable"].append(item)
                        i += 1
                        continue
                    # if indentation drops to <= searchable indent and not a list item, end searchable
                    if searchable_indent is not None and indent_l2 <= searchable_indent:
                        in_searchable = False
                        searchable_indent = None
                        # do not increment i here to reprocess current line for other keys
                        continue
                i += 1
            # context block parsed
            break
        i += 1
    return result

def has_required_dirs_and_files(ep_root, dir_name):
    """
    Check that a dir exists under ep_root, has _index.md and at least one other .md file.
    Returns (exists_bool, has_index_bool, has_content_bool)
    """
    path = os.path.join(ep_root, dir_name)
    if not os.path.isdir(path):
        return False, False, False
    md_files = [f for f in os.listdir(path) if f.lower().endswith(".md")]
    has_index = "_index.md" in md_files
    content_files = [f for f in md_files if f != "_index.md"]
    has_content = len(content_files) >= 1
    return True, has_index, has_content

def scan_for_secrets(root):
    """
    Scan all .md and .yaml files under root for secret patterns.
    Return True if no secrets found, False otherwise.
    """
    patterns = [
        re.compile(r'sk-[A-Za-z0-9]{20,}'),
        re.compile(r'ghp_[A-Za-z0-9]{36,}'),
        re.compile(r'xoxb-[A-Za-z0-9\-]+'),
        re.compile(r'(?:api[_-]?key|token|secret|password|bearer)\s*[:=]\s*\S+', re.IGNORECASE),
    ]
    ok = True
    for fpath in list_files_recursive(root, exts={".md", ".yaml"}):
        try:
            txt = read_text(fpath)
        except Exception:
            txt = ""
        for pat in patterns:
            if pat.search(txt):
                ok = False
                break
        if not ok:
            break
    return ok

def check_brand_guidelines(path):
    if not os.path.isfile(path):
        return False
    txt = read_text(path)
    # Word count >= 200
    words = re.findall(r'\b\w+\b', txt)
    if len(words) < 200:
        return False
    needed = ["positioning", "audience personas", "messaging", "visual identity"]
    lower = txt.lower()
    for kw in needed:
        if kw not in lower:
            return False
    return True

def check_emergency_card(path):
    if not os.path.isfile(path):
        return False
    lines = read_text(path).splitlines()
    fields = [
        "Name:",
        "Blood Type:",
        "Allergies:",
        "Medical Conditions:",
        "Current Medications:",
        "Emergency Contact Name:",
        "Emergency Contact Phone:",
    ]
    found = {f: False for f in fields}
    for line in lines:
        for f in fields:
            # exact field start
            if line.strip().startswith(f):
                # value after colon non-empty (non-whitespace)
                after = line.split(f, 1)[1]
                if after is not None and after.strip() != "":
                    found[f] = True
    return all(found.values())

def check_git_checklist(path):
    if not os.path.isfile(path):
        return False
    txt = read_text(path)
    required = ["git status", "git pull", "git branch", "git commit -m", "git push", "git log --oneline"]
    return all(r in txt for r in required)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    ep_root = os.path.join(output_dir, "expertpack")

    checks = {
        "expertpack_exists": False,
        "manifest_valid": False,
        "context_searchable_includes_dirs": False,
        "overview_has_lead_and_converted": False,
        "dir_mind_has_index_and_content": False,
        "dir_facts_has_index_and_content": False,
        "dir_summaries_has_index_and_content": False,
        "dir_operational_has_index_and_content": False,
        "dir_relationships_has_index_and_content": False,
        "primary_user_present": False,
        "no_secrets_in_md_yaml": False,
        "brand_guidelines_valid": False,
        "emergency_card_complete": False,
        "git_checklist_has_commands": False,
    }

    # Check existence of expertpack
    if os.path.isdir(ep_root):
        checks["expertpack_exists"] = True

        # manifest.yaml validation
        manifest_path = os.path.join(ep_root, "manifest.yaml")
        manifest = parse_manifest_yaml(manifest_path)
        if (
            manifest.get("schema_version") == "2.3"
            and manifest.get("name") == "Acme Agent Knowledge Pack"
            and manifest.get("type") == "person"
        ):
            checks["manifest_valid"] = True

        # context.searchable includes all existing EP dirs among set
        existing_dirs = []
        for d in ["mind", "facts", "summaries", "operational", "relationships"]:
            d_path = os.path.join(ep_root, d)
            if os.path.isdir(d_path):
                existing_dirs.append(f"{d}/")
        searchable = manifest.get("context_searchable") or []
        if all(item in searchable for item in existing_dirs) and len(existing_dirs) > 0:
            checks["context_searchable_includes_dirs"] = True

        # overview.md content
        overview_path = os.path.join(ep_root, "overview.md")
        if os.path.isfile(overview_path):
            ov_txt = read_text(overview_path)
            if ("lead summary" in ov_txt.lower()) and ("converted:" in ov_txt):
                checks["overview_has_lead_and_converted"] = True

        # directories checks
        for d, key in [
            ("mind", "dir_mind_has_index_and_content"),
            ("facts", "dir_facts_has_index_and_content"),
            ("summaries", "dir_summaries_has_index_and_content"),
            ("operational", "dir_operational_has_index_and_content"),
            ("relationships", "dir_relationships_has_index_and_content"),
        ]:
            exists, has_index, has_content = has_required_dirs_and_files(ep_root, d)
            checks[key] = exists and has_index and has_content

        # primary user file
        pu_path = os.path.join(ep_root, "relationships", "primary-user.md")
        if os.path.isfile(pu_path):
            txt = read_text(pu_path).strip()
            if txt:
                checks["primary_user_present"] = True

        # secrets scan across output md/yaml
        checks["no_secrets_in_md_yaml"] = scan_for_secrets(output_dir)

    # Brand guidelines
    brand_guidelines_path = os.path.join(output_dir, "brand_guidelines.md")
    checks["brand_guidelines_valid"] = check_brand_guidelines(brand_guidelines_path)

    # Emergency card
    emergency_path = os.path.join(output_dir, "emergency_card.md")
    checks["emergency_card_complete"] = check_emergency_card(emergency_path)

    # Git checklist
    git_checklist_path = os.path.join(output_dir, "publish_git_checklist.md")
    checks["git_checklist_has_commands"] = check_git_checklist(git_checklist_path)

    # Compute reward: proportion of passed checks; but if no output or zero files, reward = 0.0
    # Explicit no-op baseline
    output_exists = os.path.isdir(output_dir)
    any_output_files = False
    if output_exists:
        for _, _, files in os.walk(output_dir):
            if files:
                any_output_files = True
                break

    if not output_exists or not any_output_files:
        reward = 0.0
    else:
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total if total > 0 else 0.0

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()