import os
import sys
import json
import csv
from collections import OrderedDict

def get_workspace_root():
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1]
    return "/root/.openclaw/workspace"

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_yaml_keys_rough(yaml_text):
    # Best-effort YAML key extraction without external libraries
    # Extract keys before ":" on non-comment lines; include nested keys.
    keys = set()
    if not yaml_text:
        return keys
    for line in yaml_text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s in ("---", "..."):
            continue
        # Remove leading "- " for list items
        if s.startswith("- "):
            s = s[2:].strip()
        if ":" in s:
            # take token before first colon
            key = s.split(":", 1)[0].strip()
            if key and all(c.isprintable() for c in key):
                # avoid YAML document tags
                keys.add(key)
    return keys

def normalize_heading(line):
    # Strip markdown heading markers and trim spaces
    l = line.strip()
    # Remove leading hashes
    while l.startswith("#"):
        l = l[1:]
    return l.strip().lower()

def has_required_sections(playbook_text, required_sections):
    if not playbook_text:
        return False
    lines = playbook_text.splitlines()
    normalized_lines = [normalize_heading(ln) for ln in lines]
    found = set()
    for sec in required_sections:
        lower_sec = sec.lower()
        # find line exactly matching the section name after normalization
        for nl in normalized_lines:
            if nl == lower_sec:
                found.add(lower_sec)
                break
    return len(found) == len(required_sections)

def references_section_contains_tokens(playbook_text, tokens):
    if not playbook_text:
        return False
    lines = playbook_text.splitlines()
    # Find index of References heading
    ref_idx = None
    for i, ln in enumerate(lines):
        if normalize_heading(ln) == "references":
            ref_idx = i
            break
    if ref_idx is None:
        return False
    # Consider content from references to end
    tail = "\n".join(lines[ref_idx:]).lower()
    ok = True
    for t in tokens:
        if t.lower() not in tail:
            ok = False
            break
    return ok

def count_policy_key_mentions(playbook_text, policy_keys):
    if not playbook_text or not policy_keys:
        return 0
    content_lower = playbook_text.lower()
    count = 0
    seen = set()
    for key in policy_keys:
        k = str(key).strip()
        if not k:
            continue
        # Check case-insensitive substring match
        if k.lower() in content_lower:
            seen.add(k.lower())
    count = len(seen)
    return count

def parse_expected_sources(data_sources_obj):
    names = []
    if data_sources_obj is None:
        return names
    # Data may be list or object with "sources" or similar
    if isinstance(data_sources_obj, list):
        iterable = data_sources_obj
    elif isinstance(data_sources_obj, dict):
        # Try keys in order of likelihood
        for key in ("sources", "data", "items"):
            if key in data_sources_obj and isinstance(data_sources_obj[key], list):
                iterable = data_sources_obj[key]
                break
        else:
            # If object has simple mapping of name->attrs, use keys
            iterable = []
            # If all values are dicts, keys may be source names
            for k, v in data_sources_obj.items():
                if isinstance(v, (dict, list, str, int, float, bool, type(None))):
                    iterable.append({"name": k})
    else:
        iterable = []
    for item in iterable:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            if "source" in item and isinstance(item["source"], str):
                names.append(item["source"])
            elif "name" in item and isinstance(item["name"], str):
                names.append(item["name"])
            elif "id" in item and isinstance(item["id"], str):
                names.append(item["id"])
    # Deduplicate preserving order
    seen = set()
    ordered = []
    for n in names:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered

def read_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = [row for row in reader]
        return rows
    except Exception:
        return None

def csv_header_ok(header):
    if not header:
        return False
    norm = [h.strip().lower() for h in header]
    return norm == ["source", "allowed", "reason"]

def value_is_boolean_like(val):
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in ("true", "false", "yes", "no")

def checklist_item_lines(text):
    lines = []
    if not text:
        return lines
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        # Consider lines starting with -, *, [ ], [x], 1), etc. For simplicity, -, *, or [ ] indicators
        if s.startswith("-") or s.startswith("*") or s.startswith("[ ]") or s.startswith("[x]") or s.startswith("[X]"):
            lines.append(s)
    return lines

def check_threat_model_structure(tm):
    # Returns tuple of booleans for structure_ok, methodology_ok, threats_count_ok, stride_coverage_ok, dread_scores_ok
    if not isinstance(tm, dict):
        return (False, False, False, False, False)
    assets = tm.get("assets")
    data_flows = tm.get("data_flows")
    threats = tm.get("threats")
    methodology = tm.get("methodology")
    structure_ok = isinstance(assets, list) and isinstance(data_flows, list) and isinstance(threats, list) and isinstance(methodology, list)
    # methodology contains STRIDE and DREAD (case-insensitive)
    meth_lower = set([str(x).lower() for x in methodology]) if isinstance(methodology, list) else set()
    methodology_ok = "stride" in meth_lower and "dread" in meth_lower
    threats_count_ok = isinstance(threats, list) and len(threats) >= 6
    # STRIDE coverage
    categories_needed = {"spoofing", "tampering", "repudiation", "information disclosure", "denial of service", "elevation of privilege"}
    categories_found = set()
    dread_scores_ok = True
    if isinstance(threats, list):
        for th in threats:
            if not isinstance(th, dict):
                dread_scores_ok = False
                continue
            cat = str(th.get("category", "")).strip().lower()
            if cat:
                categories_found.add(cat)
            # Validate required fields
            if "id" not in th or "description" not in th or "affected_components" not in th or "mitigations" not in th or "dread" not in th:
                dread_scores_ok = False
                continue
            # Validate types
            if not isinstance(th.get("id"), str):
                dread_scores_ok = False
            if not isinstance(th.get("description"), str):
                dread_scores_ok = False
            if not isinstance(th.get("affected_components"), list):
                dread_scores_ok = False
            if not isinstance(th.get("mitigations"), list):
                dread_scores_ok = False
            dread = th.get("dread")
            if not isinstance(dread, dict):
                dread_scores_ok = False
                continue
            # Fields
            fields = ["damage", "reproducibility", "exploitability", "affected_users", "discoverability", "score"]
            for fld in fields:
                if fld not in dread:
                    dread_scores_ok = False
            # Range and int check
            vals = []
            for fld in ["damage", "reproducibility", "exploitability", "affected_users", "discoverability"]:
                v = dread.get(fld)
                if not isinstance(v, int):
                    dread_scores_ok = False
                else:
                    if v < 0 or v > 10:
                        dread_scores_ok = False
                if isinstance(v, int):
                    vals.append(v)
            score = dread.get("score")
            if isinstance(score, int) and len(vals) == 5:
                if score != sum(vals):
                    dread_scores_ok = False
            else:
                dread_scores_ok = False
    stride_coverage_ok = categories_needed.issubset(categories_found)
    return (structure_ok, methodology_ok, threats_count_ok, stride_coverage_ok, dread_scores_ok)

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    playbook_path = os.path.join(output_dir, "playbook.md")
    threat_model_path = os.path.join(output_dir, "threat_model.json")
    sources_matrix_path = os.path.join(output_dir, "sources_matrix.csv")
    checklist_path = os.path.join(output_dir, "checklist.md")

    company_policy_path = os.path.join(input_dir, "company_policy.yaml")
    data_sources_path = os.path.join(input_dir, "data_sources.json")

    checks = OrderedDict()

    # Initialize all checks to False
    checks["playbook_exists"] = False
    checks["playbook_title_ok"] = False
    checks["playbook_sections_ok"] = False
    checks["playbook_policy_mentions_ok"] = False
    checks["playbook_references_ok"] = False

    checks["threat_model_exists"] = False
    checks["threat_model_structure_ok"] = False
    checks["threat_model_methodology_ok"] = False
    checks["threat_model_threats_count_ok"] = False
    checks["threat_model_stride_coverage_ok"] = False
    checks["threat_model_dread_scores_ok"] = False

    checks["sources_matrix_exists"] = False
    checks["sources_matrix_header_ok"] = False
    checks["sources_matrix_covers_sources_ok"] = False
    checks["sources_matrix_boolean_and_reason_ok"] = False

    checks["checklist_exists"] = False
    checks["checklist_min_items_ok"] = False
    checks["checklist_keywords_ok"] = False

    # Playbook checks
    playbook_text = read_text(playbook_path)
    if playbook_text and playbook_text.strip():
        checks["playbook_exists"] = True
        # Title phrase
        if "social scraping implementation playbook" in playbook_text.lower():
            checks["playbook_title_ok"] = True
        # Sections
        required_sections = ["Overview", "Quickstart", "Common Patterns", "Debugging", "Performance", "Security", "Migration", "Cheatsheet", "References"]
        if has_required_sections(playbook_text, required_sections):
            checks["playbook_sections_ok"] = True
        # Policy key mentions: parse YAML keys
        policy_text = read_text(company_policy_path)
        policy_keys = parse_yaml_keys_rough(policy_text or "")
        # If keys are empty, fall back to example keys to avoid false negatives
        if not policy_keys:
            policy_keys = {"respect_robots_txt", "rate_limit_rps", "user_agent", "prohibited_actions", "data_retention_days", "pii_handling"}
        mentions = count_policy_key_mentions(playbook_text, policy_keys)
        if mentions >= 3:
            checks["playbook_policy_mentions_ok"] = True
        # References tokens under References section
        ref_tokens = ["intro", "quickstart", "patterns", "debugging", "performance", "security", "migration", "cheatsheet"]
        if references_section_contains_tokens(playbook_text, ref_tokens):
            checks["playbook_references_ok"] = True

    # Threat model checks
    tm_obj = read_json(threat_model_path)
    if tm_obj is not None:
        checks["threat_model_exists"] = True
        structure_ok, methodology_ok, threats_count_ok, stride_coverage_ok, dread_scores_ok = check_threat_model_structure(tm_obj)
        if structure_ok:
            checks["threat_model_structure_ok"] = True
        if methodology_ok:
            checks["threat_model_methodology_ok"] = True
        if threats_count_ok:
            checks["threat_model_threats_count_ok"] = True
        if stride_coverage_ok:
            checks["threat_model_stride_coverage_ok"] = True
        if dread_scores_ok:
            checks["threat_model_dread_scores_ok"] = True

    # Sources matrix checks
    rows = read_csv_rows(sources_matrix_path)
    if rows is not None and len(rows) >= 1:
        checks["sources_matrix_exists"] = True
        header = rows[0]
        if csv_header_ok(header):
            checks["sources_matrix_header_ok"] = True
            data_rows = rows[1:]
            # Expected sources from input/data_sources.json
            data_sources = read_json(data_sources_path)
            expected_sources = parse_expected_sources(data_sources) if data_sources is not None else []
            # Build set of sources present
            present_sources = set()
            boolean_and_reason_ok = True
            for r in data_rows:
                # ensure row has at least 3 cells
                if len(r) < 3:
                    boolean_and_reason_ok = False
                    continue
                src = r[0].strip()
                allowed_val = r[1].strip()
                reason = r[2].strip()
                if src:
                    present_sources.add(src)
                if not value_is_boolean_like(allowed_val):
                    boolean_and_reason_ok = False
                if reason == "":
                    boolean_and_reason_ok = False
            # Coverage: every expected source must be present
            covers_ok = True
            if expected_sources:
                for s in expected_sources:
                    if s not in present_sources:
                        covers_ok = False
                        break
            # If no expected sources (e.g., cannot parse input), require at least one row to avoid vacuous pass
            else:
                covers_ok = len(present_sources) > 0
            if covers_ok:
                checks["sources_matrix_covers_sources_ok"] = True
            if boolean_and_reason_ok:
                checks["sources_matrix_boolean_and_reason_ok"] = True

    # Checklist checks
    checklist_text = read_text(checklist_path)
    if checklist_text and checklist_text.strip():
        checks["checklist_exists"] = True
        items = checklist_item_lines(checklist_text)
        if len(items) >= 8:
            checks["checklist_min_items_ok"] = True
        content_lower = checklist_text.lower()
        keywords = ["logging", "error handling", "rate limiting", "input validation", "secure storage", "robots.txt", "user-agent", "backoff"]
        if all(k in content_lower for k in keywords):
            checks["checklist_keywords_ok"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
    # Explicitly set to 0.0 if no artifacts produced (no checks passed)
    # Already handled by reward calculation.

    result = OrderedDict()
    result["reward"] = round(reward, 6)
    for k, v in checks.items():
        result[k] = v
    # Print exactly one JSON object on last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()