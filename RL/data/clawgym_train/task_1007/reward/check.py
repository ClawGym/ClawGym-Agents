import json
import os
import re
import sys
import hashlib

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def sha256_hex(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def parse_value_raw(v):
    if v is None:
        return None
    s = v.strip()
    # Remove quotes if matching
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    sl = s.lower()
    if sl in ("null", "~"):
        return None
    if sl == "true":
        return True
    if sl == "false":
        return False
    # int
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except Exception:
            pass
    return s

def parse_manifest_yaml_simple(text):
    """
    Minimal YAML parser for the expected MANIFEST.yaml structure:
    - Top-level keys: bundle, bundle_version, bundle_date, files
    - files: list of mapping items with keys like path, role, version, hash
    Ignores unknown keys and multi-line scalars except to skip them.
    """
    result = {}
    files = []
    lines = text.splitlines()
    i = 0
    in_multiline = False
    multiline_indent = None

    # Helper to detect if a line is blank or comment
    def is_blank_or_comment(line):
        ls = line.strip()
        return (ls == "" or ls.startswith("#"))

    # Determine indentation
    def indent_of(line):
        return len(line) - len(line.lstrip(" "))

    # Parse top-level and files specially
    # First pass: find 'files:' section and top-level keys
    # We'll handle multiline scalars by skipping until dedent
    while i < len(lines):
        line = lines[i]
        if is_blank_or_comment(line):
            i += 1
            continue

        ind = indent_of(line)
        stripped = line.strip()

        # Handle multiline block closing
        if in_multiline:
            # If current indent <= multiline_indent, close multiline
            if ind <= multiline_indent:
                in_multiline = False
                multiline_indent = None
                # do not increment here; reprocess this line as a new statement
                continue
            else:
                i += 1
                continue

        # Top-level key: value
        m = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", stripped)
        if m and ind == 0:
            key = m.group(1)
            val = m.group(2)
            if val in (">", "|"):
                # start multiline scalar, skip collecting value as we don't need it
                in_multiline = True
                multiline_indent = ind
                # we could store as empty or captured, but not required for checks
                result[key] = ""  # placeholder
                i += 1
                continue
            if key == "files":
                # Enter files list parsing
                files_list_indent = indent_of(line)
                i += 1
                # Parse list items until dedent or EOF
                current_item = None
                current_item_indent = None
                in_item_multiline = False
                item_multiline_indent = None
                while i < len(lines):
                    l2 = lines[i]
                    if is_blank_or_comment(l2):
                        i += 1
                        continue
                    ind2 = indent_of(l2)
                    if ind2 <= files_list_indent:
                        # end of files list
                        break
                    s2 = l2.strip()
                    # Handle multiline fields inside an item
                    if in_item_multiline:
                        if ind2 <= item_multiline_indent:
                            in_item_multiline = False
                            item_multiline_indent = None
                            # reprocess this line
                            continue
                        else:
                            i += 1
                            continue

                    # New item starts with "- "
                    if s2.startswith("- "):
                        # push previous item
                        if current_item is not None:
                            files.append(current_item)
                        current_item = {}
                        current_item_indent = ind2
                        # After "- ", may be "key: value"
                        rest = s2[2:].strip()
                        if rest:
                            mm = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", rest)
                            if mm:
                                k = mm.group(1)
                                v = mm.group(2)
                                if v in (">", "|"):
                                    in_item_multiline = True
                                    item_multiline_indent = ind2
                                    current_item[k] = ""
                                else:
                                    current_item[k] = parse_value_raw(v)
                        i += 1
                        continue
                    # Continuation of current item fields
                    if current_item is not None and ind2 >= current_item_indent:
                        mm2 = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", s2)
                        if mm2:
                            k2 = mm2.group(1)
                            v2 = mm2.group(2)
                            if v2 in (">", "|"):
                                in_item_multiline = True
                                item_multiline_indent = ind2
                                current_item[k2] = ""
                            else:
                                current_item[k2] = parse_value_raw(v2)
                        i += 1
                        continue
                    # If we get here, and not matched, move on
                    i += 1
                # append last item
                if current_item is not None:
                    files.append(current_item)
                result["files"] = files
                continue
            else:
                # simple scalar
                result[key] = parse_value_raw(val)
                i += 1
                continue
        else:
            # Possible start of multiline for nested keys we do not need
            if ":" in stripped:
                parts = stripped.split(":", 1)
                if parts[1].strip() in (">", "|"):
                    in_multiline = True
                    multiline_indent = ind
            i += 1

    return result

def extract_frontmatter(text):
    # Return (frontmatter_text, body_text) or (None, full_text) if missing
    if text is None:
        return None, None
    lines = text.splitlines()
    if not lines:
        return None, None
    i = 0
    # Find start '---'
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i < len(lines) and lines[i].strip() == "---":
        start = i
        i += 1
        while i < len(lines):
            if lines[i].strip() == "---":
                end = i
                fm = "\n".join(lines[start+1:end])
                body = "\n".join(lines[end+1:])
                return fm, body
            i += 1
    return None, text

def parse_skill_frontmatter_simple(frontmatter_text):
    """
    Minimal parser for SKILL.md frontmatter to check:
    - presence of name and description
    - metadata block with fields: version, file_role, previous_version, change_summary, version_date
    """
    if frontmatter_text is None:
        return {}
    lines = frontmatter_text.splitlines()
    result = {"name": None, "description": None, "metadata": {}}
    i = 0

    def indent_of(line):
        return len(line) - len(line.lstrip(" "))

    # First pass: capture top-level name/description and locate metadata
    metadata_start_idx = None
    metadata_indent = None
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s == "" or s.startswith("#"):
            i += 1
            continue
        ind = indent_of(line)
        m = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", s)
        if m and ind == 0:
            key = m.group(1)
            val = m.group(2)
            if key in ("name", "description"):
                result[key] = parse_value_raw(val)
            if key == "metadata":
                metadata_start_idx = i
                metadata_indent = ind
                i += 1
                break
        i += 1

    # Parse metadata mapping keys
    if metadata_start_idx is not None:
        j = metadata_start_idx + 1
        while j < len(lines):
            l2 = lines[j]
            if l2.strip() == "":
                j += 1
                continue
            ind2 = indent_of(l2)
            if ind2 <= metadata_indent:
                break
            s2 = l2.strip()
            mm = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", s2)
            if mm:
                k = mm.group(1)
                v = mm.group(2)
                # Handle multiline scalars '>' or '|': skip the block
                if v in (">", "|"):
                    # skip subsequent indented lines
                    j += 1
                    while j < len(lines):
                        l3 = lines[j]
                        if indent_of(l3) <= ind2:
                            j -= 1  # step back so outer loop processes this line
                            break
                        j += 1
                    result["metadata"][k] = ""  # placeholder
                else:
                    result["metadata"][k] = parse_value_raw(v)
            j += 1

    return result

def is_semver(s):
    if not isinstance(s, str):
        return False
    return re.fullmatch(r"\d+\.\d+\.\d+", s) is not None

def check_paths_relative(file_entries):
    for e in file_entries:
        p = e.get("path")
        if not isinstance(p, str) or p.strip() == "":
            return False
        if p.startswith("/"):
            return False
        low = p.lower()
        if "input/" in low or "output/" in low or low.startswith("input") or low.startswith("output"):
            return False
    return True

def get_manifest_entries_by_path(files_list):
    return { e.get("path"): e for e in files_list if isinstance(e, dict) and e.get("path") }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected output paths
    bundle_dir = os.path.join(output_dir, "bundle")
    manifest_path = os.path.join(bundle_dir, "MANIFEST.yaml")
    changelog_path = os.path.join(bundle_dir, "CHANGELOG.md")
    skill_path = os.path.join(bundle_dir, "SKILL.md")
    evals_path = os.path.join(bundle_dir, "evals.json")
    shapefile_inv_path = os.path.join(bundle_dir, "sources", "shapefile_inventory.json")
    scenarios_path = os.path.join(bundle_dir, "references", "scenarios.md")
    shapefile_note_path = os.path.join(bundle_dir, "references", "shapefile-migration.md")
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")

    checks = {
        # Manifest checks
        "manifest_exists": False,
        "manifest_parsed": False,
        "manifest_has_required_keys": False,
        "manifest_semver_valid": False,
        "manifest_required_entries_present": False,
        "manifest_hash_format_valid": False,
        "manifest_hashes_match": False,
        "manifest_paths_relative": False,
        # Changelog checks
        "changelog_exists": False,
        "changelog_has_heading": False,
        "changelog_has_bootstrap_mentions": False,
        # SKILL.md frontmatter checks
        "skill_exists": False,
        "skill_frontmatter_present": False,
        "skill_has_name_description": False,
        "skill_metadata_fields_valid": False,
        # Scenario doc checks
        "scenarios_exists": False,
        "scenarios_has_sections": False,
        # Shapefile migration note checks
        "shapefile_note_exists": False,
        "shapefile_note_crs_unknown_statement": False,
        # Learning log checks
        "learnings_exists": False,
        "learnings_has_entry": False,
    }

    # Manifest
    if os.path.isfile(manifest_path):
        checks["manifest_exists"] = True
        manifest_text = read_text(manifest_path)
        manifest = None
        if manifest_text is not None:
            try:
                manifest = parse_manifest_yaml_simple(manifest_text)
                # Validate it's a dict and has some keys
                if isinstance(manifest, dict) and len(manifest) > 0:
                    checks["manifest_parsed"] = True
            except Exception:
                manifest = None

        if checks["manifest_parsed"]:
            has_keys = all(k in manifest for k in ("bundle", "bundle_version", "bundle_date", "files"))
            checks["manifest_has_required_keys"] = bool(has_keys and isinstance(manifest.get("files"), list))
            if isinstance(manifest.get("bundle_version"), str) and is_semver(manifest.get("bundle_version")):
                checks["manifest_semver_valid"] = True

            # Files entries presence: SKILL.md, evals.json, sources/shapefile_inventory.json with roles/versions
            files_list = manifest.get("files") or []
            by_path = get_manifest_entries_by_path(files_list)

            required_ok = True
            required_specs = [
                ("SKILL.md", "skill", 1),
                ("evals.json", "evals", 1),
                ("sources/shapefile_inventory.json", "source", None),
            ]
            for path_rel, role_exp, ver_exp in required_specs:
                entry = by_path.get(path_rel)
                if not entry:
                    required_ok = False
                    break
                if entry.get("role") != role_exp:
                    required_ok = False
                    break
                if ver_exp is None:
                    # Accept None or explicit null string
                    v = entry.get("version")
                    if not (v is None or (isinstance(v, str) and v.strip().lower() == "null")):
                        required_ok = False
                        break
                else:
                    v = entry.get("version")
                    if v != ver_exp:
                        required_ok = False
                        break
            checks["manifest_required_entries_present"] = required_ok

            # Hash formats for the three required entries
            hash_fmt_ok = True
            for pth in ("SKILL.md", "evals.json", "sources/shapefile_inventory.json"):
                e = by_path.get(pth)
                if not e or "hash" not in e or not isinstance(e["hash"], str):
                    hash_fmt_ok = False
                    break
                if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", e["hash"]) is None:
                    hash_fmt_ok = False
                    break
            checks["manifest_hash_format_valid"] = hash_fmt_ok

            # Hash values match file contents in output/bundle
            if hash_fmt_ok:
                hashes_match = True
                files_to_check = {
                    "SKILL.md": skill_path,
                    "evals.json": evals_path,
                    "sources/shapefile_inventory.json": shapefile_inv_path,
                }
                for rel, abspath in files_to_check.items():
                    e = by_path.get(rel)
                    if not os.path.isfile(abspath):
                        hashes_match = False
                        break
                    computed = sha256_hex(abspath)
                    if computed is None:
                        hashes_match = False
                        break
                    manifest_hash = e.get("hash", "")
                    if not manifest_hash.lower().startswith("sha256:"):
                        hashes_match = False
                        break
                    if computed.lower() != manifest_hash.split(":", 1)[1].lower():
                        hashes_match = False
                        break
                checks["manifest_hashes_match"] = hashes_match

            # Paths are all relative and not referencing input/ or output/
            if isinstance(files_list, list) and len(files_list) > 0:
                checks["manifest_paths_relative"] = check_paths_relative(files_list)

    # Changelog checks
    if os.path.isfile(changelog_path):
        checks["changelog_exists"] = True
        ct = read_text(changelog_path) or ""
        # Heading check: any line starting with '#'
        if re.search(r"(?m)^\s*#\s+", ct):
            checks["changelog_has_heading"] = True
        # Bootstrap entry mentions 1.0.0 and SKILL.md and evals.json
        if ("1.0.0" in ct) and ("SKILL.md" in ct) and ("evals.json" in ct):
            checks["changelog_has_bootstrap_mentions"] = True

    # SKILL.md frontmatter checks
    if os.path.isfile(skill_path):
        checks["skill_exists"] = True
        skill_text = read_text(skill_path) or ""
        fm_text, body = extract_frontmatter(skill_text)
        if fm_text is not None:
            checks["skill_frontmatter_present"] = True
            parsed = parse_skill_frontmatter_simple(fm_text)
            # name and description present
            if parsed.get("name") not in (None, "") and parsed.get("description") not in (None, ""):
                checks["skill_has_name_description"] = True
            md = parsed.get("metadata") or {}
            # required metadata
            version_ok = (md.get("version") == 1)
            role_ok = (md.get("file_role") == "skill")
            change_summary = md.get("change_summary")
            change_ok = isinstance(change_summary, str) and len(change_summary.strip()) > 0
            vdate = md.get("version_date")
            vdate_ok = isinstance(vdate, str) and len(vdate.strip()) > 0
            prev = md.get("previous_version", "MISSING")
            prev_ok = (prev == "MISSING") or (prev is None)
            if version_ok and role_ok and change_ok and vdate_ok and prev_ok:
                checks["skill_metadata_fields_valid"] = True

    # Scenario doc checks
    if os.path.isfile(scenarios_path):
        checks["scenarios_exists"] = True
        st = read_text(scenarios_path) or ""
        low = st.lower()
        has_title = "## scenario planning:" in low
        # Search section markers
        sec_markers = [
            "driving forces",
            "critical uncertainties",
            "scenario narratives",
            "early warning signposts",
            "strategic implications",
        ]
        has_all = has_title and all(marker in low for marker in sec_markers)
        checks["scenarios_has_sections"] = has_all

    # Shapefile migration note checks
    if os.path.isfile(shapefile_note_path):
        checks["shapefile_note_exists"] = True
        nt = read_text(shapefile_note_path) or ""
        low = nt.lower()
        # Must reference .prj and unknown CRS (e.g., "missing .prj" and "crs is unknown" or ".prj" and "unknown")
        contains_prj = ".prj" in low
        mentions_unknown = ("crs is unknown" in low) or ("crs unknown" in low) or ("unknown crs" in low) or ("unknown" in low and "crs" in low)
        if contains_prj and mentions_unknown:
            checks["shapefile_note_crs_unknown_statement"] = True

    # Learning log checks
    if os.path.isfile(learnings_path):
        checks["learnings_exists"] = True
        lt = read_text(learnings_path) or ""
        # Require an entry with header "## [LRN-" and sections "### Summary" and "### Suggested Action"
        has_id = re.search(r"(?m)^## \[LRN-\d{8}-[A-Za-z0-9]+\]", lt) is not None or re.search(r"(?m)^## \[LRN-\d{8}-\d{3}\]", lt) is not None
        has_summary = "### Summary" in lt
        has_action = "### Suggested Action" in lt
        if has_id and has_summary and has_action:
            checks["learnings_has_entry"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline yields 0.0 if key artifacts missing
    # This is already handled by ratio; if nothing exists passed=0 -> reward 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()