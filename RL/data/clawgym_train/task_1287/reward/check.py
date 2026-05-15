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

def split_entries(content, entry_type):
    # entry_type: 'LRN', 'ERR', 'FEAT'
    if content is None:
        return []
    pattern = rf"^## \[{entry_type}-\d{{8}}-[A-Za-z0-9]{{3}}\].*?(?=^## \[{entry_type}-\d{{8}}-[A-Za-z0-9]{{3}}\]|$)"
    return re.findall(pattern, content, flags=re.MULTILINE | re.DOTALL)

def line_has_build_deps(line):
    s = line.strip().lower()
    return ("build" in s) and ("depend" in s)

def extract_candidate_pattern_keys(cand_text):
    keys = set()
    if not cand_text:
        return keys
    try:
        data = json.loads(cand_text)
        # Candidates can be a list or wrapped in an object under a key like "candidates"
        candidates = []
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            # try common keys
            for k in ["candidates", "items", "patterns"]:
                if isinstance(data.get(k), list):
                    candidates = data.get(k)
                    break
        for item in candidates:
            if isinstance(item, dict):
                pk = item.get("pattern_key") or item.get("patternKey") or item.get("pattern-key")
                if isinstance(pk, str) and pk.strip():
                    keys.add(pk.strip())
    except Exception:
        # If JSON fails to parse, return empty set
        pass
    return keys

def entry_contains_all(entry_text, substrings, case_insensitive=True):
    text = entry_text if entry_text is not None else ""
    if case_insensitive:
        text = text.lower()
        subs = [s.lower() for s in substrings]
    else:
        subs = substrings
    return all(s in text for s in subs)

def get_recurrence_count(entry_text):
    if not entry_text:
        return None
    m = re.search(r"Recurrence-Count:\s*(\d+)", entry_text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def has_lrn_header(content):
    if not content:
        return False
    return re.search(r"^## \[LRN-\d{8}-[A-Za-z0-9]{3}\]", content, flags=re.MULTILINE) is not None

def has_err_header(content):
    if not content:
        return False
    return re.search(r"^## \[ERR-\d{8}-[A-Za-z0-9]{3}\]", content, flags=re.MULTILINE) is not None

def has_feat_header(content):
    if not content:
        return False
    return re.search(r"^## \[FEAT-\d{8}-[A-Za-z0-9]{3}\]", content, flags=re.MULTILINE) is not None

def check_pnpm_learning(entries):
    # Must find an LRN entry with:
    # - Pattern-Key: build.package_manager.pnpm
    # - Status: promoted
    # - Source: conversation
    # - Recurrence-Count >= 3
    target_found = False
    for e in entries:
        el = e.lower()
        has_pattern = "pattern-key:" in el and "build.package_manager.pnpm" in el
        has_status_promoted = "status:" in el and "promoted" in el
        has_source_conv = "source:" in el and "conversation" in el
        if has_pattern and has_status_promoted and has_source_conv:
            rc = get_recurrence_count(e)
            if rc is not None and rc >= 3:
                target_found = True
                break
    return target_found

def check_simplify_candidate(entries, candidate_keys):
    # Need at least one entry with:
    # - Source: simplify-and-harden
    # - Pattern-Key: one of candidate_keys
    # - Recurrence-Count >= 1
    if not candidate_keys:
        # Without candidates, cannot verify presence; return False
        return False
    for e in entries:
        el = e.lower()
        if "source:" in el and "simplify-and-harden" in el and "pattern-key:" in el:
            # Find pattern key value
            # We'll search each candidate key case-insensitively in the entry
            for key in candidate_keys:
                if key and key.lower() in el:
                    rc = get_recurrence_count(e)
                    if rc is not None and rc >= 1:
                        return True
    return False

def check_errors_pytest_modulenotfound(entries):
    # At least one ERR entry containing both 'pytest' and 'ModuleNotFoundError'
    for e in entries:
        el = e.lower()
        if "pytest" in el and "modulenotfounderror" in el:
            return True
    return False

def check_features_thread_reply(entries):
    # At least one FEAT entry with 'thread' and 'repl' substring within same entry
    for e in entries:
        el = e.lower()
        if "thread" in el and "repl" in el:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        "has_learnings_file": False,
        "has_errors_file": False,
        "has_feature_requests_file": False,
        "has_claude_file": False,
        "has_agents_file": False,
        "learnings_has_lrn_header": False,
        "learnings_has_pnpm_learning": False,
        "learnings_has_simplify_candidate": False,
        "errors_has_err_header": False,
        "errors_has_pytest_modulenotfound": False,
        "features_has_feat_header": False,
        "features_has_thread_reply": False,
        "claude_has_build_deps_section": False,
        "claude_mentions_pnpm_install": False,
        "agents_has_threading_rule": False,
    }

    # Paths
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    feat_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")
    claude_path = os.path.join(output_dir, "CLAUDE.md")
    agents_path = os.path.join(output_dir, "AGENTS.md")

    # Read outputs if present
    learnings_text = read_text(learnings_path)
    errors_text = read_text(errors_path)
    feat_text = read_text(feat_path)
    claude_text = read_text(claude_path)
    agents_text = read_text(agents_path)

    # File existence checks
    if learnings_text is not None:
        checks["has_learnings_file"] = True
    if errors_text is not None:
        checks["has_errors_file"] = True
    if feat_text is not None:
        checks["has_feature_requests_file"] = True
    if claude_text is not None:
        checks["has_claude_file"] = True
    if agents_text is not None:
        checks["has_agents_file"] = True

    # LEARNINGS.md content checks
    if checks["has_learnings_file"]:
        checks["learnings_has_lrn_header"] = has_lrn_header(learnings_text)
        lrn_entries = split_entries(learnings_text, "LRN")

        # pnpm learning check
        checks["learnings_has_pnpm_learning"] = check_pnpm_learning(lrn_entries)

        # simplify_and_harden candidate check - need input file to get pattern keys
        candidates_path = os.path.join(input_dir, "simplify_and_harden_candidates.json")
        candidates_text = read_text(candidates_path)
        candidate_keys = extract_candidate_pattern_keys(candidates_text)
        checks["learnings_has_simplify_candidate"] = check_simplify_candidate(lrn_entries, candidate_keys)

    # ERRORS.md content checks
    if checks["has_errors_file"]:
        checks["errors_has_err_header"] = has_err_header(errors_text)
        err_entries = split_entries(errors_text, "ERR")
        checks["errors_has_pytest_modulenotfound"] = check_errors_pytest_modulenotfound(err_entries)

    # FEATURE_REQUESTS.md content checks
    if checks["has_feature_requests_file"]:
        checks["features_has_feat_header"] = has_feat_header(feat_text)
        feat_entries = split_entries(feat_text, "FEAT")
        checks["features_has_thread_reply"] = check_features_thread_reply(feat_entries)

    # CLAUDE.md content checks
    if checks["has_claude_file"]:
        lines = (claude_text or "").splitlines()
        for ln in lines:
            if line_has_build_deps(ln):
                checks["claude_has_build_deps_section"] = True
                break
        text_l = (claude_text or "").lower()
        if "pnpm" in text_l and "pnpm install" in text_l:
            checks["claude_mentions_pnpm_install"] = True

    # AGENTS.md content checks
    if checks["has_agents_file"]:
        # Look for a line with both 'thread' and 'repl' substrings
        for ln in (agents_text or "").splitlines():
            s = ln.strip().lower()
            if "thread" in s and "repl" in s:
                checks["agents_has_threading_rule"] = True
                break

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if no outputs (none of the five files exist), reward should be 0.0
    any_outputs = checks["has_learnings_file"] or checks["has_errors_file"] or checks["has_feature_requests_file"] or checks["has_claude_file"] or checks["has_agents_file"]
    reward = (passed / total_checks) if any_outputs else 0.0

    # Print result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()