import json
import os
import sys
import re

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    items.append(obj)
                except Exception:
                    return None
        return items
    except Exception:
        return None

def is_nonempty_string(v):
    return isinstance(v, str) and v.strip() != ""

def validate_subdomain_code(code, domain_ranges):
    if not isinstance(code, str) or len(code) < 2:
        return False
    m = re.fullmatch(r"([A-I|Z])(\d+)", code)
    if not m:
        return False
    letter = m.group(1)
    num = int(m.group(2))
    if letter not in domain_ranges:
        return False
    return num in domain_ranges[letter]

def get_tools_list(tools_json):
    if not isinstance(tools_json, list):
        return None
    tools = []
    for t in tools_json:
        if not isinstance(t, dict):
            return None
        name = t.get("name")
        desc = t.get("description", "")
        if not is_nonempty_string(name):
            return None
        tools.append({"name": name, "description": desc if isinstance(desc, str) else ""})
    return tools

def compute_used_counts(routing_obj):
    counts = {}
    for tid, decision in routing_obj.items():
        chosen = decision.get("chosen_skills", [])
        if isinstance(chosen, list):
            for tool in chosen:
                if isinstance(tool, str):
                    counts[tool] = counts.get(tool, 0) + 1
    return counts

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "classified_skills_exists": False,
        "routing_matrix_exists": False,
        "usage_report_exists": False,
        "classified_count_matches_tools": False,
        "classified_fields_valid": False,
        "classified_risk_heuristics_valid": False,
        "routing_keys_match_tasks": False,
        "routing_fields_valid": False,
        "routing_max_two_tools": False,
        "read_only_tasks_low_risk": False,
        "web_article_notes_two_tools_correct": False,
        "portal_form_task_includes_browser_tool": False,
        "aws_iam_task_single_and_includes": False,
        "usage_report_counts_correct": False,
    }

    # Paths
    tools_path = os.path.join(input_dir, "tools.json")
    tasks_path = os.path.join(input_dir, "tasks.jsonl")
    classified_path = os.path.join(output_dir, "classified_skills.json")
    routing_path = os.path.join(output_dir, "routing_matrix.json")
    usage_path = os.path.join(output_dir, "usage_report.json")

    # Load inputs
    tools_json = load_json(tools_path)
    tasks_jsonl = load_jsonl(tasks_path)

    # Early exit if inputs missing (but per requirements, positive reward must depend on output only)
    # However, to validate outputs, we need inputs; if inputs missing, no checks can pass.
    if tools_json is None or tasks_jsonl is None:
        print(json.dumps({"reward": 0.0, **checks}))
        return

    tools_list = get_tools_list(tools_json)
    if tools_list is None:
        print(json.dumps({"reward": 0.0, **checks}))
        return
    tool_names = [t["name"] for t in tools_list]
    tool_desc_map = {t["name"]: t.get("description", "") for t in tools_list}

    task_ids = []
    task_texts = {}
    for item in tasks_jsonl:
        if isinstance(item, dict) and "id" in item and "task" in item and isinstance(item["id"], str) and isinstance(item["task"], str):
            task_ids.append(item["id"])
            task_texts[item["id"]] = item["task"]
    # Outputs existence
    if os.path.isfile(classified_path):
        checks["classified_skills_exists"] = True
    if os.path.isfile(routing_path):
        checks["routing_matrix_exists"] = True
    if os.path.isfile(usage_path):
        checks["usage_report_exists"] = True

    # If any of the core files missing, still continue to set others? We'll proceed but those dependent checks will fail.

    # Domain/subdomain ranges
    domain_ranges = {
        "A": set(range(1, 7)),
        "B": set(range(1, 7)),
        "C": set(range(1, 8)),
        "D": set(range(1, 7)),
        "E": set(range(1, 8)),
        "F": set(range(1, 6)),
        "G": set(range(1, 5)),
        "H": set(range(1, 5)),
        "I": set(range(1, 4)),
        "Z": set(range(1, 5)),
    }
    allowed_primary_letters = set(domain_ranges.keys())
    risk_levels = {"R0", "R1", "R2", "R3", "R4"}
    allowed_tags = {
        "read-only",
        "search",
        "retrieve",
        "write-local",
        "write-remote",
        "message-send",
        "browser-act",
        "device-control",
        "finance",
        "credential",
        "automation",
        "agent-orchestration",
        "knowledge-base",
        "calendar",
        "notes",
        "crm",
        "cloud-infra",
        "security",
        "content-publish",
        "monitoring",
        "setup-install",
    }
    allowed_dims = {"local_system", "data_egress", "external_action", "physical_world", "auth_permission", "financial_asset"}

    classified = None
    classified_map = {}
    if checks["classified_skills_exists"]:
        classified = load_json(classified_path)
        if isinstance(classified, list):
            # Count match check
            names_in_classified = []
            for e in classified:
                if isinstance(e, dict):
                    name = e.get("name")
                    if isinstance(name, str):
                        names_in_classified.append(name)
            if set(names_in_classified) == set(tool_names) and len(names_in_classified) == len(tool_names):
                checks["classified_count_matches_tools"] = True

            # Build map
            for e in classified:
                if isinstance(e, dict) and "name" in e and isinstance(e["name"], str):
                    classified_map[e["name"]] = e

            # Validate fields
            fields_ok = True
            for tool in tool_names:
                entry = classified_map.get(tool)
                if not isinstance(entry, dict):
                    fields_ok = False
                    break
                # primary_domain
                pd = entry.get("primary_domain")
                if not (isinstance(pd, str) and pd in allowed_primary_letters):
                    fields_ok = False
                    break
                # subdomain
                sd = entry.get("subdomain")
                if not validate_subdomain_code(sd, domain_ranges):
                    fields_ok = False
                    break
                # risk_level
                rl = entry.get("risk_level")
                if not (isinstance(rl, str) and rl in risk_levels):
                    fields_ok = False
                    break
                # capability_tags
                ct = entry.get("capability_tags")
                if not (isinstance(ct, list) and 1 <= len(ct) <= 5 and all(isinstance(x, str) and x in allowed_tags for x in ct)):
                    fields_ok = False
                    break
                # threat_dimensions
                td = entry.get("threat_dimensions")
                if not (isinstance(td, list) and all(isinstance(x, str) and x in allowed_dims for x in td)):
                    fields_ok = False
                    break
                # rationale
                rat = entry.get("rationale")
                if not is_nonempty_string(rat):
                    fields_ok = False
                    break
            if fields_ok:
                checks["classified_fields_valid"] = True

            # Risk heuristics
            heur_ok = True
            for t in tools_list:
                name = t["name"]
                desc = (t.get("description") or "").lower()
                entry = classified_map.get(name)
                if not isinstance(entry, dict):
                    heur_ok = False
                    break
                rl = entry.get("risk_level")
                if rl not in risk_levels:
                    heur_ok = False
                    break
                # Heuristic keywords
                high_risk_kw = ["send", "email", "post", "submit", "login", "permissions", "credentials", "iam", "role", "policy", "update crm", "upload"]
                low_risk_kw = ["read-only", "reads", "read only"]
                high_trigger = any(k in desc for k in high_risk_kw)
                low_trigger = any(k in desc for k in low_risk_kw)
                if high_trigger:
                    # Must be R2 or higher
                    if rl not in {"R2", "R3", "R4"}:
                        heur_ok = False
                        break
                if low_trigger:
                    # Must be R0 or R1
                    if rl not in {"R0", "R1"}:
                        heur_ok = False
                        break
            if heur_ok:
                checks["classified_risk_heuristics_valid"] = True

    # Routing matrix
    routing_obj = None
    if checks["routing_matrix_exists"]:
        routing_obj = load_json(routing_path)
        if isinstance(routing_obj, dict):
            # keys match tasks
            keys = set(routing_obj.keys())
            if keys == set(task_ids) and len(keys) == len(task_ids):
                checks["routing_keys_match_tasks"] = True

            # value fields
            fields_ok = True
            max_two_ok = True
            if checks["classified_fields_valid"]:
                # to validate chosen tools exist in tools.json
                for tid in task_ids:
                    v = routing_obj.get(tid)
                    if not isinstance(v, dict):
                        fields_ok = False
                        break
                    if not is_nonempty_string(v.get("intent", "")):
                        fields_ok = False
                        break
                    pd = v.get("primary_domain")
                    if not (isinstance(pd, str) and pd in allowed_primary_letters):
                        fields_ok = False
                        break
                    sd = v.get("subdomain")
                    if not validate_subdomain_code(sd, domain_ranges):
                        fields_ok = False
                        break
                    chosen = v.get("chosen_skills")
                    if not (isinstance(chosen, list) and 1 <= len(chosen) <= 2 and all(isinstance(x, str) for x in chosen)):
                        fields_ok = False
                        break
                    # names exist
                    if not all(x in tool_names for x in chosen):
                        fields_ok = False
                        break
                    # risk_level
                    rv = v.get("risk_level")
                    if not (isinstance(rv, str) and rv in risk_levels):
                        fields_ok = False
                        break
                    candidates = v.get("candidates")
                    if not (isinstance(candidates, list) and all(isinstance(x, str) for x in candidates)):
                        fields_ok = False
                        break
                    if not is_nonempty_string(v.get("why_choice", "")):
                        fields_ok = False
                        break
                    if not is_nonempty_string(v.get("why_not_loaded", "")):
                        fields_ok = False
                        break
                    # max two tools enforced already by chosen length check
                    if len(chosen) > 2:
                        max_two_ok = False
                if fields_ok:
                    checks["routing_fields_valid"] = True
                if max_two_ok and fields_ok:
                    checks["routing_max_two_tools"] = True

            # Special deterministic checks only if we have classified info
            if checks["routing_fields_valid"] and checks["classified_fields_valid"]:
                # Read-only tasks risk low
                low_ok = True
                for tid, text in task_texts.items():
                    text_l = text.lower()
                    if ("read-only" in text_l) or ("read only" in text_l) or ("without changing anything" in text_l):
                        decision = routing_obj.get(tid, {})
                        chosen = decision.get("chosen_skills", [])
                        for tool in chosen:
                            entry = classified_map.get(tool, {})
                            rl = entry.get("risk_level")
                            if rl not in {"R0", "R1"}:
                                low_ok = False
                                break
                        if not low_ok:
                            break
                if low_ok:
                    checks["read_only_tasks_low_risk"] = True

                # Identify helper sets for tools
                # Sets based on tools descriptions and classifications
                web_fetcher_candidates = set()
                notes_tool_candidates = set()
                browser_form_candidates = set()
                iam_tool_candidates = set()

                for name in tool_names:
                    desc = (tool_desc_map.get(name) or "").lower()
                    entry = classified_map.get(name, {})
                    caps = set(entry.get("capability_tags", [])) if isinstance(entry.get("capability_tags", []), list) else set()
                    risk = entry.get("risk_level")

                    # Web fetcher: description mentions web/http/url/website/browser/scrape AND capabilities suggest retrieve/search, prefer read-only risk
                    if any(k in desc for k in ["web", "website", "web page", "http", "url", "scrape", "read web", "fetch"]):
                        if ("retrieve" in caps or "search" in caps) and risk in {"R0", "R1"}:
                            web_fetcher_candidates.add(name)
                    # Notes tool: name/desc includes notes, or capability tag notes or write-local
                    if ("note" in name.lower() or "notes" in desc or "notebook" in desc) or ("notes" in caps or "write-local" in caps):
                        notes_tool_candidates.add(name)
                    # Browser form automation
                    if (("form" in desc and any(x in desc for x in ["submit", "upload", "attachment"])) or ("portal" in desc and any(x in desc for x in ["submit", "upload"])) or ("browser" in desc and "automation" in desc)):
                        browser_form_candidates.add(name)
                    if ("browser-act" in caps and ("automation" in caps or "write-remote" in caps)):
                        browser_form_candidates.add(name)
                    # IAM tool
                    if ("aws" in desc and "iam" in desc) or (" iam " in f" {desc} ") or ("iam" in name.lower()):
                        iam_tool_candidates.add(name)
                    elif "aws" in desc and any(k in desc for k in ["role", "roles", "policy", "policies"]):
                        iam_tool_candidates.add(name)

                # Web article summarize into notes task: detect
                web_article_task_ids = []
                for tid, text in task_texts.items():
                    l = text.lower()
                    if (("article" in l or "web article" in l) and ("summar" in l) and ("note" in l) and any(k in l for k in ["web", "website", "online", "url", "link"])):
                        web_article_task_ids.append(tid)
                web_notes_ok = True
                if len(web_article_task_ids) >= 1:
                    # For each such task, validate exactly two tools: one from web_fetcher_candidates and one from notes_tool_candidates
                    for tid in web_article_task_ids:
                        decision = routing_obj.get(tid, {})
                        chosen = decision.get("chosen_skills", [])
                        if not (isinstance(chosen, list) and len(chosen) == 2):
                            web_notes_ok = False
                            break
                        has_web = any(ch in web_fetcher_candidates for ch in chosen)
                        has_notes = any(ch in notes_tool_candidates for ch in chosen)
                        if not (has_web and has_notes):
                            web_notes_ok = False
                            break
                else:
                    # If no such task found, keep False to avoid vacuous pass
                    web_notes_ok = False
                if web_notes_ok:
                    checks["web_article_notes_two_tools_correct"] = True

                # Portal form submission task
                portal_tasks = []
                for tid, text in task_texts.items():
                    l = text.lower()
                    if ("portal" in l and "form" in l and "submit" in l):
                        portal_tasks.append(tid)
                portal_ok = True
                if len(portal_tasks) >= 1:
                    for tid in portal_tasks:
                        decision = routing_obj.get(tid, {})
                        chosen = decision.get("chosen_skills", [])
                        if not chosen:
                            portal_ok = False
                            break
                        if not any(ch in browser_form_candidates for ch in chosen):
                            portal_ok = False
                            break
                else:
                    portal_ok = False
                if portal_ok:
                    checks["portal_form_task_includes_browser_tool"] = True

                # AWS IAM roles task
                iam_tasks = []
                for tid, text in task_texts.items():
                    l = text.lower()
                    if ("aws" in l and (("iam" in l) or (" role" in l) or ("roles" in l) or ("policy" in l) or ("policies" in l))):
                        iam_tasks.append(tid)
                iam_ok = True
                if len(iam_tasks) >= 1 and len(iam_tool_candidates) >= 1:
                    # pick first candidate
                    for tid in iam_tasks:
                        decision = routing_obj.get(tid, {})
                        chosen = decision.get("chosen_skills", [])
                        if not (isinstance(chosen, list) and len(chosen) == 1):
                            iam_ok = False
                            break
                        if not any(ch in iam_tool_candidates for ch in chosen):
                            iam_ok = False
                            break
                else:
                    iam_ok = False
                if iam_ok:
                    checks["aws_iam_task_single_and_includes"] = True

    # Usage report correctness
    if checks["usage_report_exists"] and isinstance(routing_obj, dict) and checks["routing_fields_valid"]:
        usage_obj = load_json(usage_path)
        if isinstance(usage_obj, dict):
            types_ok = all(isinstance(k, str) and isinstance(v, int) for k, v in usage_obj.items())
            # No unknown tools
            no_unknown = all(k in [*tool_names] for k in usage_obj.keys())
            used_counts = compute_used_counts(routing_obj)
            # All used tools must be present and match
            used_match = True
            for k, v in used_counts.items():
                if usage_obj.get(k) != v:
                    used_match = False
                    break
            if types_ok and no_unknown and used_match:
                checks["usage_report_counts_correct"] = True

    # Compute reward: fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if output is empty or missing artifacts, ensure reward is 0.0
    # If none of the primary existence checks are true, set reward 0.0
    if not (checks["classified_skills_exists"] or checks["routing_matrix_exists"] or checks["usage_report_exists"]):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()