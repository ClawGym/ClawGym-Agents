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

def strip_quotes(val: str) -> str:
    v = val.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1].strip()
    return v

def parse_area_ids_from_yaml(yaml_text: str) -> list[str]:
    """
    Minimal YAML parser to extract area ids from a list of items that include 'id:' fields.
    Supports patterns:
      - '- id: value'
      - '-' line starting an item and 'id:' on the next indented lines
    Also supports a top-level key followed by a list of items.
    """
    area_ids = []
    lines = yaml_text.splitlines()
    in_item = False
    current_id = None

    # Try to detect if the YAML is actually JSON and parse it directly
    stripped = yaml_text.strip()
    if stripped.startswith('[') or stripped.startswith('{'):
        try:
            data = json.loads(stripped)
            # Expect a list of dicts with 'id'
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and 'id' in item:
                        val = item['id']
                        if isinstance(val, (str, int, float)):
                            area_ids.append(str(val))
                return area_ids
            # Or a dict with a list under a known key
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict) and 'id' in item:
                                val = item['id']
                                if isinstance(val, (str, int, float)):
                                    area_ids.append(str(val))
                if area_ids:
                    return area_ids
        except Exception:
            pass  # fall back to YAML heuristic parsing

    for raw in lines:
        # Remove inline comments (only if preceded by space or start of line)
        line = raw.rstrip("\n")
        # Split on ' #' or ' # ' or '##', but keep URLs http:// which contain '://'
        # We'll remove comments starting with ' #', '#' if not part of 'http' or 'https'
        # Safer approach: find '#' not preceded by ':' and split there
        comment_pos = -1
        for idx, ch in enumerate(line):
            if ch == '#':
                # If previous non-space char is ':' or part of 'http' scheme, keep
                prev = line[:idx].rstrip()
                if prev.endswith(':') or prev.endswith('http') or prev.endswith('https'):
                    continue
                comment_pos = idx
                break
        if comment_pos != -1:
            line = line[:comment_pos]
        # Strip trailing whitespace
        line = line.rstrip()
        if not line.strip():
            continue

        # Start of a new list item
        if re.match(r'^\s*-\s*(\S.*)?$', line):
            # commit previous item
            if current_id is not None:
                area_ids.append(current_id)
            in_item = True
            current_id = None
            # Handle inline '- id: value'
            m_inline = re.match(r'^\s*-\s*id\s*:\s*(.+?)\s*$', line)
            if m_inline:
                val = strip_quotes(m_inline.group(1))
                if val != "":
                    current_id = val
            continue

        # If inside an item, look for 'id: value'
        if in_item:
            m = re.match(r'^\s*id\s*:\s*(.+?)\s*$', line)
            if m:
                val = strip_quotes(m.group(1))
                if val != "":
                    current_id = val
                    continue

        # Also support top-level maps with '- ' under a key (e.g., areas:)
        # If not in item, still try to catch 'id:' on its own lines (best-effort)
        if not in_item:
            m_top = re.match(r'^\s*-\s*id\s*:\s*(.+?)\s*$', line)
            if m_top:
                val = strip_quotes(m_top.group(1))
                if val != "":
                    area_ids.append(val)
                    continue

    # commit last item
    if current_id is not None:
        area_ids.append(current_id)

    # Deduplicate while preserving order
    seen = set()
    ordered = []
    for aid in area_ids:
        if aid is None:
            continue
        s = str(aid)
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    return ordered

def is_nonempty_ascii(s: str) -> bool:
    if not isinstance(s, str) or len(s.strip()) == 0:
        return False
    try:
        s.encode('ascii')
        return True
    except Exception:
        return False

def validate_install_command(cmd: str) -> bool:
    if not isinstance(cmd, str) or len(cmd.strip()) == 0:
        return False
    if "--yes" not in cmd:
        return False
    # Ensure -y appears as a token or attached to whitespace boundaries
    if not re.search(r'(^|[\s])\-y($|[\s])', cmd):
        return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "skills_report_exists": False,
        "skills_report_json_valid": False,
        "area_coverage_exact": False,
        "all_search_keywords_ascii_nonempty": False,
        "candidates_per_area_count_ok": False,
        "candidates_fields_valid": False,
        "candidates_urls_valid": False,
        "candidates_install_flags_present": False,
        "installation_plan_exists": False,
        "installation_plan_nonempty": False,
        "installation_plan_mentions_all_areas": False,
        "installation_plan_contains_recommended_commands_matching_json": False,
    }

    # Paths
    yaml_path = os.path.join(input_dir, "skill_needs.yaml")
    json_path = os.path.join(output_dir, "skills_report.json")
    md_path = os.path.join(output_dir, "installation_plan.md")

    # Parse area ids from YAML
    area_ids: list[str] = []
    yaml_text = read_text(yaml_path)
    if yaml_text is not None:
        area_ids = parse_area_ids_from_yaml(yaml_text)

    # Load JSON report if exists
    json_data = None
    if os.path.isfile(json_path):
        checks["skills_report_exists"] = True
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)
            if isinstance(json_data, list):
                checks["skills_report_json_valid"] = True
        except Exception:
            checks["skills_report_json_valid"] = False

    report_entries_by_area = {}
    if checks["skills_report_json_valid"]:
        # Build map area_id -> entry (expecting one per area)
        for entry in json_data:
            if isinstance(entry, dict) and isinstance(entry.get("area_id"), str):
                report_entries_by_area.setdefault(entry["area_id"], entry)

        # Check coverage exact: sets equal and lengths equal
        if area_ids:
            set_yaml = set(area_ids)
            set_json = set(report_entries_by_area.keys())
            if set_yaml == set_json and len(json_data) == len(area_ids):
                checks["area_coverage_exact"] = True
        else:
            # If no areas could be parsed, do not award this check
            checks["area_coverage_exact"] = False

        # Validate fields across all entries
        all_keywords_ok = True
        all_candidates_count_ok = True
        all_candidate_fields_ok = True
        all_urls_ok = True
        all_installs_ok = True

        for area_id in area_ids:
            entry = report_entries_by_area.get(area_id)
            if not isinstance(entry, dict):
                all_keywords_ok = False
                all_candidates_count_ok = False
                all_candidate_fields_ok = False
                all_urls_ok = False
                all_installs_ok = False
                continue

            # search_keywords
            if not is_nonempty_ascii(entry.get("search_keywords", "")):
                all_keywords_ok = False

            # candidates
            candidates = entry.get("candidates")
            if not isinstance(candidates, list) or len(candidates) < 2:
                all_candidates_count_ok = False
            else:
                for cand in candidates:
                    if not isinstance(cand, dict):
                        all_candidate_fields_ok = False
                        all_urls_ok = False
                        all_installs_ok = False
                        continue
                    skill_name = cand.get("skill_name")
                    short_desc = cand.get("short_description")
                    url = cand.get("learn_more_url")
                    cmd = cand.get("install_command")
                    if not (isinstance(skill_name, str) and skill_name.strip()):
                        all_candidate_fields_ok = False
                    if not (isinstance(short_desc, str) and short_desc.strip()):
                        all_candidate_fields_ok = False
                    if not (isinstance(url, str) and (url.startswith("http://") or url.startswith("https://"))):
                        all_urls_ok = False
                    if not validate_install_command(cmd if isinstance(cmd, str) else ""):
                        all_installs_ok = False

        checks["all_search_keywords_ascii_nonempty"] = all_keywords_ok and checks["skills_report_json_valid"]
        checks["candidates_per_area_count_ok"] = all_candidates_count_ok and checks["skills_report_json_valid"]
        checks["candidates_fields_valid"] = all_candidate_fields_ok and checks["skills_report_json_valid"]
        checks["candidates_urls_valid"] = all_urls_ok and checks["skills_report_json_valid"]
        checks["candidates_install_flags_present"] = all_installs_ok and checks["skills_report_json_valid"]

    # Load installation_plan.md if exists
    if os.path.isfile(md_path):
        checks["installation_plan_exists"] = True
        md_text = read_text(md_path) or ""
        if md_text and md_text.strip():
            checks["installation_plan_nonempty"] = True
        else:
            checks["installation_plan_nonempty"] = False
    else:
        md_text = ""

    # Validate installation plan content only if JSON is valid and MD exists
    if checks["skills_report_json_valid"] and checks["installation_plan_nonempty"]:
        # Mentions all areas: the file must contain that area_id string
        mentions_all = True
        commands_match = True

        # We will check for each area in the JSON report (which should match input)
        for area_id, entry in report_entries_by_area.items():
            if area_id not in md_text:
                mentions_all = False
            # Check that at least one candidate's install_command appears verbatim in the md content
            found_cmd_for_area = False
            candidates = entry.get("candidates") if isinstance(entry, dict) else None
            if isinstance(candidates, list):
                for cand in candidates:
                    if isinstance(cand, dict):
                        cmd = cand.get("install_command")
                        if isinstance(cmd, str) and cmd and cmd in md_text:
                            found_cmd_for_area = True
                            break
            if not found_cmd_for_area:
                commands_match = False

        checks["installation_plan_mentions_all_areas"] = mentions_all
        checks["installation_plan_contains_recommended_commands_matching_json"] = commands_match

    # Compute reward with gating: both required artifacts must exist and be valid/nonempty
    weights = {
        "skills_report_exists": 0.05,
        "skills_report_json_valid": 0.14,
        "area_coverage_exact": 0.20,
        "all_search_keywords_ascii_nonempty": 0.10,
        "candidates_per_area_count_ok": 0.12,
        "candidates_fields_valid": 0.08,
        "candidates_urls_valid": 0.08,
        "candidates_install_flags_present": 0.08,
        "installation_plan_exists": 0.02,
        "installation_plan_nonempty": 0.03,
        "installation_plan_mentions_all_areas": 0.05,
        "installation_plan_contains_recommended_commands_matching_json": 0.05,
    }

    # Gate: if either main deliverable missing/invalid, overall reward must be exactly 0.0
    main_deliverables_ok = checks["skills_report_json_valid"] and checks["installation_plan_nonempty"]

    reward = 0.0
    if main_deliverables_ok:
        for k, w in weights.items():
            if checks.get(k, False):
                reward += w
        # Ensure numerical bounds
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0
    else:
        reward = 0.0

    # Output single JSON object
    result = {"reward": round(reward, 6)}
    result.update({k: bool(v) for k, v in checks.items()})
    print(json.dumps(result))

if __name__ == "__main__":
    main()