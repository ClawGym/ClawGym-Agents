import json
import os
import re
import sys
from datetime import datetime

def read_search_terms(path):
    terms = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if t:
                    terms.append(t)
    except OSError:
        pass
    return terms

def read_agents_yaml(path):
    # Minimal YAML list reader (supports JSON-like [..] or dash-prefixed lines)
    agents = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return []
        # Try JSON-style first
        if content.startswith("[") and content.endswith("]"):
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    agents = [str(x) for x in data]
                    return agents
            except json.JSONDecodeError:
                pass
        # Fallback: parse dash list
        lines = content.splitlines()
        for ln in lines:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("-"):
                val = s[1:].strip()
                # Strip optional quotes
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                if val:
                    agents.append(val)
    except OSError:
        pass
    return agents

def read_config(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        days = int(data.get("days"))
        max_results = int(data.get("max_results"))
        return days, max_results
    except Exception:
        return None, None

def is_iso8601_z_or_offset(s):
    if not isinstance(s, str):
        return False
    if "T" not in s:
        return False
    try:
        dt = s.replace("Z", "+00:00")
        datetime.fromisoformat(dt)
    except Exception:
        return False
    if s.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", s):
        return True
    return False

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def find_header_index(lines, header_word):
    # Match lines like "Summary", "## Summary", etc.
    pattern = re.compile(r"^\s*(?:#{1,6}\s*)?" + re.escape(header_word) + r"\b", re.IGNORECASE)
    for idx, ln in enumerate(lines):
        if pattern.search(ln):
            return idx
    return -1

def has_title_line(lines, phrase):
    pat = re.compile(r"^\s*#\s*.*" + re.escape(phrase) + r".*$", re.IGNORECASE)
    for ln in lines:
        if pat.search(ln):
            return True
    return False

def contains_any_keyword(text, keywords):
    tl = text.lower()
    for kw in keywords:
        if kw.strip() and kw.strip().lower() in tl:
            return True
    return False

def brief_no_raw_json_dump(lines):
    # No more than 3 consecutive lines starting with '{' or '"type"'
    consec = 0
    max_consec = 0
    for ln in lines:
        s = ln.lstrip()
        if s.startswith("{") or s.startswith('"type"') or s.startswith("'type'"):
            consec += 1
        else:
            if consec > max_consec:
                max_consec = consec
            consec = 0
    if consec > max_consec:
        max_consec = consec
    return max_consec <= 3

def sources_items_format_ok(lines_after_sources):
    # If there are non-empty lines, each should look like an identifier or path:
    # contains a slash OR a hyphen OR an alphanumeric token length >= 8
    token_re = re.compile(r"[A-Za-z0-9]{8,}")
    for ln in lines_after_sources:
        s = ln.strip()
        if not s:
            continue
        if ("/" in s) or ("-" in s) or token_re.search(s):
            continue
        else:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    metadata_path = os.path.join(output_dir, "search_metadata.json")
    brief_path = os.path.join(output_dir, "brief.md")
    plan_path = os.path.join(output_dir, "implementation_plan.md")

    # Inputs
    search_terms_path = os.path.join(input_dir, "search_terms.txt")
    agents_yaml_path = os.path.join(input_dir, "agents.yaml")
    config_json_path = os.path.join(input_dir, "config.json")

    expected_terms = read_search_terms(search_terms_path)
    expected_agents = read_agents_yaml(agents_yaml_path)
    expected_days, expected_max_results = read_config(config_json_path)

    checks = {
        # metadata checks
        "metadata_file_exists": False,
        "metadata_valid_json": False,
        "metadata_required_keys": False,
        "metadata_query_terms_match": False,
        "metadata_agents_match": False,
        "metadata_days_match": False,
        "metadata_max_results_match": False,
        "metadata_status_valid": False,
        "metadata_created_at_valid": False,
        # brief checks
        "brief_exists": False,
        "brief_title_contains_session_recall_brief": False,
        "brief_sections_in_order": False,
        "brief_contains_keyword": False,
        "brief_length_ok": False,
        "brief_no_raw_dump": False,
        "brief_sources_items_format_ok": False,
        # plan checks
        "plan_exists": False,
        "plan_has_title_implementation_plan": False,
        "plan_has_goal_arch_tech": False,
        "plan_has_tdd_phrases": False,
        "plan_mentions_session_history": False,
    }

    # --- search_metadata.json checks ---
    metadata = None
    if os.path.isfile(metadata_path):
        checks["metadata_file_exists"] = True
        metadata = load_json(metadata_path)
        if isinstance(metadata, dict):
            checks["metadata_valid_json"] = True
            # required keys
            req_keys = {"query_terms", "agents", "days", "max_results", "status", "created_at"}
            if req_keys.issubset(set(metadata.keys())):
                checks["metadata_required_keys"] = True

                # query_terms match expected
                q = metadata.get("query_terms")
                if isinstance(q, list) and all(isinstance(x, str) for x in q):
                    if expected_terms and q == expected_terms:
                        checks["metadata_query_terms_match"] = True
                    elif not expected_terms and q == []:
                        # If no terms provided, expect empty array
                        checks["metadata_query_terms_match"] = True

                # agents set match (order-insensitive)
                a = metadata.get("agents")
                if isinstance(a, list) and all(isinstance(x, str) for x in a):
                    if set(a) == set(expected_agents):
                        checks["metadata_agents_match"] = True

                # days match
                d = metadata.get("days")
                if isinstance(d, int) and expected_days is not None and d == expected_days:
                    checks["metadata_days_match"] = True

                # max_results match
                m = metadata.get("max_results")
                if isinstance(m, int) and expected_max_results is not None and m == expected_max_results:
                    checks["metadata_max_results_match"] = True

                # status valid
                status = metadata.get("status")
                if isinstance(status, str) and status in ("matches_found", "no_matches"):
                    checks["metadata_status_valid"] = True

                # created_at ISO8601 with Z or offset
                created_at = metadata.get("created_at")
                if is_iso8601_z_or_offset(created_at):
                    checks["metadata_created_at_valid"] = True

    # --- brief.md checks ---
    brief_content = ""
    brief_lines = []
    if os.path.isfile(brief_path):
        checks["brief_exists"] = True
        try:
            with open(brief_path, "r", encoding="utf-8") as f:
                brief_content = f.read()
            brief_lines = brief_content.splitlines()
        except OSError:
            brief_lines = []
            brief_content = ""

        # Title contains "Session Recall Brief"
        if any(re.search(r"\bSession\s+Recall\s+Brief\b", ln, re.IGNORECASE) for ln in brief_lines):
            checks["brief_title_contains_session_recall_brief"] = True

        # Sections in order: Summary, Decisions, Risks, Next Steps, Sources
        targets = ["Summary", "Decisions", "Risks", "Next Steps", "Sources"]
        idxs = []
        ok = True
        for t in targets:
            idx = find_header_index(brief_lines, t)
            if idx == -1:
                ok = False
                break
            idxs.append(idx)
        if ok and all(earlier <= later for earlier, later in zip(idxs, idxs[1:])):
            checks["brief_sections_in_order"] = True

        # Contains at least one keyword from search_terms.txt (case-insensitive)
        if brief_content and expected_terms:
            if contains_any_keyword(brief_content, expected_terms):
                checks["brief_contains_keyword"] = True
        elif brief_content and not expected_terms:
            # If no terms provided, relax this check to True (cannot verify against empty)
            checks["brief_contains_keyword"] = True

        # Length <= 20000 chars
        if isinstance(brief_content, str) and len(brief_content) <= 20000:
            checks["brief_length_ok"] = True

        # No raw transcript dump heuristic
        if brief_lines:
            if brief_no_raw_json_dump(brief_lines):
                checks["brief_no_raw_dump"] = True

        # Sources items format OK (if present lines after Sources)
        sources_idx = find_header_index(brief_lines, "Sources")
        if sources_idx != -1:
            after = brief_lines[sources_idx + 1 :] if sources_idx + 1 < len(brief_lines) else []
            if sources_items_format_ok(after):
                checks["brief_sources_items_format_ok"] = True

    # --- implementation_plan.md checks ---
    plan_content = ""
    plan_lines = []
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_content = f.read()
            plan_lines = plan_content.splitlines()
        except OSError:
            plan_content = ""
            plan_lines = []

        # Title line includes "Implementation Plan"
        if has_title_line(plan_lines, "Implementation Plan"):
            checks["plan_has_title_implementation_plan"] = True

        # Contains Goal:, Architecture:, Tech Stack:
        labels = ["Goal:", "Architecture:", "Tech Stack:"]
        if all(re.search(re.escape(lbl), plan_content, re.IGNORECASE) for lbl in labels):
            checks["plan_has_goal_arch_tech"] = True

        # TDD phrases: "Write the failing test", "Run", "Implement", "Commit"
        tdd_phrases = ["Write the failing test", "Run", "Implement", "Commit"]
        if all(re.search(rf"\b{re.escape(p)}\b", plan_content, re.IGNORECASE) for p in tdd_phrases):
            checks["plan_has_tdd_phrases"] = True

        # Mentions based on session history
        if re.search(r"based on session history|from prior sessions", plan_content, re.IGNORECASE):
            checks["plan_mentions_session_history"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Explicitly enforce no-op baseline: if no required outputs exist, reward 0.0
    required_any = checks["metadata_file_exists"] or checks["brief_exists"] or checks["plan_exists"]
    reward = 0.0
    if required_any and total_checks > 0:
        reward = passed / total_checks
        # Clamp to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()