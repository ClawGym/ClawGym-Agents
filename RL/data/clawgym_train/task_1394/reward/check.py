import json
import os
import re
import sys

def safe_read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def safe_read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_int(value):
    try:
        return isinstance(value, int)
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dictionary with all False by default
    checks = {}

    # Input references
    docs_index_path = os.path.join(input_dir, "docs_site_index.json")
    version_path = os.path.join(input_dir, "openclaw_version.txt")
    input_docs_dir = os.path.join(input_dir, "docs")

    docs_index = safe_read_json(docs_index_path) or {}
    base_url = docs_index.get("base_url")
    index_pages = docs_index.get("pages") if isinstance(docs_index.get("pages"), list) else []
    index_pages_set = set([p for p in index_pages if isinstance(p, str)])
    index_pages_basenames = set([os.path.basename(p) for p in index_pages_set])

    version_text = safe_read_text(version_path)
    version_exact = version_text.strip() if isinstance(version_text, str) else None

    # Output paths
    memory_path = os.path.join(output_dir, "MEMORY.md")
    agents_path = os.path.join(output_dir, "AGENTS.md")
    fetch_plan_path = os.path.join(output_dir, "fetch_plan.json")
    compat_path = os.path.join(output_dir, "compatibility_check.md")
    model_advice_path = os.path.join(output_dir, "model_advice.md")

    # 1) Required files exist
    has_memory = os.path.isfile(memory_path)
    has_agents = os.path.isfile(agents_path)
    has_fetch_plan = os.path.isfile(fetch_plan_path)
    has_compat = os.path.isfile(compat_path)
    has_model_advice = os.path.isfile(model_advice_path)

    checks["has_MEMORY_md"] = has_memory
    checks["has_AGENTS_md"] = has_agents
    checks["has_fetch_plan_json"] = has_fetch_plan
    checks["has_compatibility_check_md"] = has_compat
    checks["has_model_advice_md"] = has_model_advice

    # 2) fetch_plan.json structure & content
    checks["fetch_json_valid"] = False
    checks["fetch_keys_present"] = False
    checks["fetch_base_url_match"] = False
    checks["fetch_total_pages_match"] = False
    checks["fetch_permission_requested_true"] = False
    checks["fetch_token_budget_positive"] = False
    checks["fetch_recursion_depth_positive"] = False
    checks["fetch_pages_paths_valid"] = False
    checks["fetch_pages_tokens_int"] = False

    fetch_obj = None
    if has_fetch_plan:
        fetch_obj = safe_read_json(fetch_plan_path)
        if isinstance(fetch_obj, dict):
            checks["fetch_json_valid"] = True

            required_keys = [
                "base_url",
                "total_pages",
                "recursion_depth",
                "permission_requested",
                "token_budget_estimate_tokens",
                "pages",
            ]
            if all(k in fetch_obj for k in required_keys):
                checks["fetch_keys_present"] = True

                # base_url match
                if isinstance(fetch_obj.get("base_url"), str) and isinstance(base_url, str):
                    if fetch_obj.get("base_url") == base_url:
                        checks["fetch_base_url_match"] = True

                # total_pages match
                if isinstance(fetch_obj.get("total_pages"), int) and isinstance(index_pages, list):
                    if fetch_obj.get("total_pages") == len(index_pages):
                        checks["fetch_total_pages_match"] = True

                # permission_requested true
                if fetch_obj.get("permission_requested") is True:
                    checks["fetch_permission_requested_true"] = True

                # token_budget_estimate_tokens > 0
                tbet = fetch_obj.get("token_budget_estimate_tokens")
                if isinstance(tbet, int) and tbet > 0:
                    checks["fetch_token_budget_positive"] = True

                # recursion_depth positive int
                rd = fetch_obj.get("recursion_depth")
                if isinstance(rd, int) and rd > 0:
                    checks["fetch_recursion_depth_positive"] = True

                # pages array validation
                pages = fetch_obj.get("pages")
                pages_paths_valid = True
                pages_tokens_ok = True
                if isinstance(pages, list) and len(pages) == len(index_pages):
                    for item in pages:
                        if not isinstance(item, dict):
                            pages_paths_valid = False
                            pages_tokens_ok = False
                            break
                        pth = item.get("path")
                        tok = item.get("tokens_estimate")
                        # tokens_estimate int (can be 0 or positive; spec only requires int)
                        if not isinstance(tok, int):
                            pages_tokens_ok = False
                        # path must correspond to a filename present in index and to a file in input/docs
                        if not isinstance(pth, str):
                            pages_paths_valid = False
                        else:
                            # Check membership by either exact path or basename
                            in_index = (pth in index_pages_set) or (os.path.basename(pth) in index_pages_basenames)
                            # Check file exists under input/docs using basename
                            exists_under_docs = os.path.isfile(os.path.join(input_docs_dir, os.path.basename(pth)))
                            if not (in_index and exists_under_docs):
                                pages_paths_valid = False
                    if pages_paths_valid:
                        checks["fetch_pages_paths_valid"] = True
                    if pages_tokens_ok:
                        checks["fetch_pages_tokens_int"] = True
                else:
                    # Structure mismatch
                    pass

    # 3) MEMORY.md content checks
    checks["memory_includes_base_url"] = False
    checks["memory_includes_agent_contact_card_phrase"] = False
    checks["memory_keywords_coverage"] = False
    checks["memory_has_learned_from_line"] = False
    checks["memory_min_length"] = False

    memory_text = safe_read_text(memory_path) if has_memory else None
    if isinstance(memory_text, str):
        text_lower = memory_text.lower()
        if isinstance(base_url, str) and base_url in memory_text:
            checks["memory_includes_base_url"] = True

        if "agent contact card" in memory_text:
            checks["memory_includes_agent_contact_card_phrase"] = True

        keywords = ["channels", "webhook", "multi-agent", "privacy tiers", "discovery", "routing"]
        count_keywords = 0
        for kw in keywords:
            if kw.lower() in text_lower:
                count_keywords += 1
        if count_keywords >= 3:
            checks["memory_keywords_coverage"] = True

        # Learned from: <base_url> line
        learned_ok = False
        if isinstance(base_url, str):
            for line in memory_text.splitlines():
                if line.strip().startswith("Learned from:"):
                    rest = line.strip()[len("Learned from:"):].strip()
                    if rest == base_url:
                        learned_ok = True
                        break
        checks["memory_has_learned_from_line"] = learned_ok

        if len(memory_text) >= 400:
            checks["memory_min_length"] = True

    # 4) AGENTS.md content checks
    checks["agents_includes_privacy_sentence"] = False
    checks["agents_terms_coverage"] = False
    checks["agents_has_checklist_reference"] = False
    checks["agents_includes_base_url"] = False
    checks["agents_min_length"] = False

    agents_text = safe_read_text(agents_path) if has_agents else None
    if isinstance(agents_text, str):
        if "Do not log sensitive environment variables or API keys." in agents_text:
            checks["agents_includes_privacy_sentence"] = True

        terms = ["create", "parse", "frontmatter", "channels", "webhook", "routing"]
        tcount = 0
        lower_agents = agents_text.lower()
        for term in terms:
            if term.lower() in lower_agents:
                tcount += 1
        if tcount >= 2:
            checks["agents_terms_coverage"] = True

        if ("checklist" in lower_agents) or ("preflight" in lower_agents):
            checks["agents_has_checklist_reference"] = True

        if isinstance(base_url, str) and base_url in agents_text:
            checks["agents_includes_base_url"] = True

        if len(agents_text) >= 400:
            checks["agents_min_length"] = True

    # 5) compatibility_check.md content
    checks["compat_includes_version_string"] = False
    checks["compat_has_compatible_word"] = False

    compat_text = safe_read_text(compat_path) if has_compat else None
    if isinstance(compat_text, str):
        if isinstance(version_exact, str) and len(version_exact) > 0 and version_exact in compat_text:
            checks["compat_includes_version_string"] = True
        if re.search(r"\bcompatible\b", compat_text, flags=re.IGNORECASE) or re.search(r"\bincompatible\b", compat_text, flags=re.IGNORECASE):
            checks["compat_has_compatible_word"] = True

    # 6) model_advice.md content
    checks["model_advice_mentions_local"] = False
    checks["model_advice_mentions_cloud"] = False
    checks["model_advice_mentions_model_word"] = False

    model_text = safe_read_text(model_advice_path) if has_model_advice else None
    if isinstance(model_text, str):
        lt = model_text.lower()
        if "local" in lt:
            checks["model_advice_mentions_local"] = True
        if "cloud" in lt:
            checks["model_advice_mentions_cloud"] = True
        if "model" in lt:
            checks["model_advice_mentions_model_word"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure reward is within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Print a single JSON object as last non-empty line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()