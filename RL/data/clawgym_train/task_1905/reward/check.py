import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

def is_relative_path(p):
    if not isinstance(p, str) or not p:
        return False
    return not (p.startswith("/") or p.startswith("~"))

def find_agent(agents_list, agent_id):
    if not isinstance(agents_list, list):
        return None
    for a in agents_list:
        if isinstance(a, dict) and a.get("id") == agent_id:
            return a
    return None

def find_binding(bindings_list, agent_id, channel, account_id):
    if not isinstance(bindings_list, list):
        return None
    for b in bindings_list:
        if not isinstance(b, dict):
            continue
        if b.get("agentId") != agent_id:
            continue
        m = b.get("match", {})
        if isinstance(m, dict) and m.get("channel") == channel and m.get("accountId") == account_id:
            return b
    return None

def last_non_empty_line(text):
    if text is None:
        return None
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return None

def parse_jsonl_first_valid(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    items.append(obj)
                except:
                    continue
    except:
        return []
    return items

def count_risk_keywords(text):
    if not isinstance(text, str):
        return 0
    kws = {"json", "delete", "backup", "secret", "credentials", "corruption", "jq", "atomic", "overwrite"}
    text_lower = text.lower()
    present = set()
    for k in kws:
        if k in text_lower:
            present.add(k)
    return len(present)

def compute_reward(checks_dict):
    total = len(checks_dict)
    if total == 0:
        return 0.0
    passed = sum(1 for v in checks_dict.values() if v is True)
    if passed == 0:
        return 0.0
    # Normalize to [0,1]
    return round(passed / total, 6)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize all checks to False
    checks = {
        # Config JSON checks
        "openclaw_json_exists": False,
        "openclaw_json_valid": False,
        "has_brand_helper_agent": False,
        "brand_helper_workspace_rel": False,
        "brand_helper_agentDir_rel": False,
        "brand_helper_model_updated": False,
        "has_sales_support_agent": False,
        "sales_support_workspace_rel": False,
        "sales_support_agentDir_rel": False,
        "sales_support_default_model": False,
        "accounts_brand_helper_ok": False,
        "accounts_sales_support_ok": False,
        "bindings_brand_helper": False,
        "bindings_sales_support": False,
        "deprecated_bot_removed_based_on_input": False,

        # feishu_list.txt checks
        "feishu_list_ok": False,
        "feishu_list_total_ok": False,
        "feishu_list_excludes_main": False,

        # brand_helper_info.txt checks
        "brand_helper_info_ok": False,

        # config_risks.md checks
        "config_risks_ok": False,

        # GEP assets checks
        "gep_prompt_ok": False,
        "gep_selector_ok": False,
        "gep_events_ok": False,

        # Branding doc checks
        "branding_doc_ok": False,

        # Humanized essay checks
        "brand_story_exists_diff": False,
        "brand_story_no_markdown_artifacts": False,
        "brand_story_no_dollar_math": False,
        "brand_story_no_chat_signoff": False,
    }

    # Reference input config (for conditional deprecated_bot check)
    input_openclaw_path = os.path.join(input_dir, "openclaw.json")
    input_config = read_json(input_openclaw_path)
    input_has_deprecated = False
    if isinstance(input_config, dict):
        agents_list_in = (input_config.get("agents") or {}).get("list") or []
        channels_in = (input_config.get("channels") or {}).get("feishu") or {}
        accounts_in = channels_in.get("accounts") or {}
        bindings_in = input_config.get("bindings") or []
        if find_agent(agents_list_in, "deprecated_bot") is not None:
            input_has_deprecated = True
        if isinstance(accounts_in, dict) and "deprecated_bot" in accounts_in:
            input_has_deprecated = True or input_has_deprecated
        if find_binding(bindings_in, "deprecated_bot", "feishu", "deprecated_bot") is not None:
            input_has_deprecated = True or input_has_deprecated

    DEFAULT_MODEL = "bailian-coding-plan/glm-5"
    known_genes = {
        "gene_gep_repair_from_errors",
        "gene_gep_optimize_prompt_and_assets",
        "gene_gep_innovate_from_opportunity",
    }

    # 1) Validate output/openclaw.json
    out_config_path = os.path.join(output_dir, "openclaw.json")
    if os.path.isfile(out_config_path) and os.path.getsize(out_config_path) > 0:
        checks["openclaw_json_exists"] = True
        out_config = read_json(out_config_path)
        if isinstance(out_config, dict):
            checks["openclaw_json_valid"] = True

            # Agents lookups
            agents_list = (out_config.get("agents") or {}).get("list") or []
            brand_helper = find_agent(agents_list, "brand_helper")
            sales_support = find_agent(agents_list, "sales_support")

            if isinstance(brand_helper, dict):
                checks["has_brand_helper_agent"] = True
                # Workspace and agentDir relative and exact values
                if is_relative_path(brand_helper.get("workspace")) and brand_helper.get("workspace") == "workspace/brand_helper":
                    checks["brand_helper_workspace_rel"] = True
                if is_relative_path(brand_helper.get("agentDir")) and brand_helper.get("agentDir") == "agents/brand_helper/agent":
                    checks["brand_helper_agentDir_rel"] = True
                if brand_helper.get("model") == "kimi-k2.5":
                    checks["brand_helper_model_updated"] = True

            if isinstance(sales_support, dict):
                checks["has_sales_support_agent"] = True
                if is_relative_path(sales_support.get("workspace")) and sales_support.get("workspace") == "workspace/sales_support":
                    checks["sales_support_workspace_rel"] = True
                if is_relative_path(sales_support.get("agentDir")) and sales_support.get("agentDir") == "agents/sales_support/agent":
                    checks["sales_support_agentDir_rel"] = True
                if sales_support.get("model") == DEFAULT_MODEL:
                    checks["sales_support_default_model"] = True

            # Accounts checks
            channels = (out_config.get("channels") or {})
            feishu = (channels.get("feishu") or {})
            accounts = feishu.get("accounts") or {}

            def account_ok(acc, expected_app_id, expected_app_secret):
                if not isinstance(acc, dict):
                    return False
                if acc.get("appId") != expected_app_id:
                    return False
                if acc.get("appSecret") != expected_app_secret:
                    return False
                if acc.get("groupPolicy") != "open":
                    return False
                if acc.get("dmPolicy") != "open":
                    return False
                allow_from = acc.get("allowFrom")
                if not (isinstance(allow_from, list) and allow_from == ["*"]):
                    return False
                if acc.get("connectionMode") != "websocket":
                    return False
                return True

            if account_ok(accounts.get("brand_helper"), "cli_brand_123", "sec_brand_abc"):
                checks["accounts_brand_helper_ok"] = True
            if account_ok(accounts.get("sales_support"), "cli_sales_456", "sec_sales_def"):
                checks["accounts_sales_support_ok"] = True

            # Bindings checks
            bindings = out_config.get("bindings") or []
            if find_binding(bindings, "brand_helper", "feishu", "brand_helper") is not None:
                checks["bindings_brand_helper"] = True
            if find_binding(bindings, "sales_support", "feishu", "sales_support") is not None:
                checks["bindings_sales_support"] = True

            # Deprecated bot removal (conditional)
            dep_removed = True
            if input_has_deprecated:
                # Must ensure it is absent in output
                dep_agent = find_agent(agents_list, "deprecated_bot")
                dep_account_present = isinstance(accounts, dict) and ("deprecated_bot" in accounts)
                dep_binding = find_binding(bindings, "deprecated_bot", "feishu", "deprecated_bot")
                dep_removed = (dep_agent is None) and (not dep_account_present) and (dep_binding is None)
            if dep_removed:
                checks["deprecated_bot_removed_based_on_input"] = True

    # 2) Validate feishu_list.txt
    list_path = os.path.join(output_dir, "feishu_list.txt")
    list_text = read_text(list_path)
    list_lines = []
    if isinstance(list_text, str) and list_text.strip():
        # Split lines and filter non-empty
        list_lines = [ln.rstrip("\n") for ln in list_text.splitlines() if ln.strip()]
        # Check presence of required lines
        has_brand_line = any(re.fullmatch(r"brand_helper\s+-\s+Model:\s+kimi-k2\.5", ln.strip()) for ln in list_lines)
        has_sales_line = any(re.fullmatch(r"sales_support\s+-\s+Model:\s+" + re.escape(DEFAULT_MODEL), ln.strip()) for ln in list_lines)
        if has_brand_line and has_sales_line:
            checks["feishu_list_ok"] = True
        # Check excludes main
        if not any(re.match(r"main\s+-\s+Model:", ln.strip()) for ln in list_lines):
            checks["feishu_list_excludes_main"] = True
        # Check total count on final line
        # Count all lines that match "<botId> - Model: <model>"
        count_listed = sum(1 for ln in list_lines if re.match(r"^.+\s+-\s+Model:\s+.+$", ln.strip()))
        total_line = list_lines[-1].strip() if list_lines else ""
        m = re.match(r"^Total:\s+(\d+)\s+bot\(s\)$", total_line)
        if m:
            try:
                total_n = int(m.group(1))
                if total_n == count_listed:
                    checks["feishu_list_total_ok"] = True
            except:
                pass

    # 3) Validate brand_helper_info.txt
    info_path = os.path.join(output_dir, "brand_helper_info.txt")
    info_text = read_text(info_path)
    if isinstance(info_text, str) and info_text.strip():
        ok = True
        if "Bot: brand_helper" not in info_text:
            ok = False
        # Agent Config section
        if ("Agent Config:" not in info_text or
            "Model: kimi-k2.5" not in info_text or
            "Workspace: workspace/brand_helper" not in info_text or
            "Agent Dir: agents/brand_helper/agent" not in info_text):
            ok = False
        # Feishu Account section
        if ("Feishu Account:" not in info_text or
            "App ID: cli_brand_123" not in info_text or
            "Group Policy: open" not in info_text or
            "DM Policy: open" not in info_text or
            "Connection: websocket" not in info_text):
            ok = False
        if ok:
            checks["brand_helper_info_ok"] = True

    # 4) Validate config_risks.md
    risks_path = os.path.join(output_dir, "config_risks.md")
    risks_text = read_text(risks_path)
    if isinstance(risks_text, str) and risks_text.strip():
        if count_risk_keywords(risks_text) >= 3:
            checks["config_risks_ok"] = True

    # 5) GEP files
    gep_dir = os.path.join(output_dir, "gep")
    prompt_path = os.path.join(gep_dir, "prompt.txt")
    selector_path = os.path.join(gep_dir, "selector_decision.json")
    events_path = os.path.join(gep_dir, "events.jsonl")

    prompt_text = read_text(prompt_path)
    if isinstance(prompt_text, str) and prompt_text.strip():
        has_gep_ref = ("GEP" in prompt_text) or ("Genome Evolution Protocol" in prompt_text) or ("GEP Protocol" in prompt_text)
        has_known_gene = any(g in prompt_text for g in known_genes)
        if has_gep_ref and has_known_gene:
            checks["gep_prompt_ok"] = True

    selector_json = read_json(selector_path)
    if isinstance(selector_json, dict):
        sg = selector_json.get("selected_gene")
        rationale = selector_json.get("rationale")
        signals = selector_json.get("signals")
        if isinstance(sg, str) and sg in known_genes and isinstance(rationale, str) and rationale.strip() and isinstance(signals, list):
            checks["gep_selector_ok"] = True

    events = parse_jsonl_first_valid(events_path)
    if isinstance(events, list) and len(events) >= 1:
        ok_event = False
        for e in events:
            if not isinstance(e, dict):
                continue
            eid = e.get("id")
            intent = e.get("intent")
            outcome = e.get("outcome")
            status = outcome.get("status") if isinstance(outcome, dict) else None
            if isinstance(eid, str) and eid.strip() and isinstance(intent, str) and intent.strip() and isinstance(status, str) and status.strip():
                ok_event = True
                break
        if ok_event:
            checks["gep_events_ok"] = True

    # 6) Branding doc
    branding_path = os.path.join(output_dir, "branding.md")
    branding_text = read_text(branding_path)
    if isinstance(branding_text, str) and branding_text.strip():
        text_lower = branding_text.lower()
        has_sections = ("summary" in text_lower) and ("action items" in text_lower) and ("next steps" in text_lower)
        has_warn = "⚠️" in branding_text
        mentions_platforms = ("amazon" in text_lower) and ("shopify" in text_lower)
        visual_terms = (("color" in text_lower) or ("colors" in text_lower)) and ("typography" in text_lower)
        if has_sections and has_warn and mentions_platforms and visual_terms:
            checks["branding_doc_ok"] = True

    # 7) Humanized essay
    brand_story_path = os.path.join(output_dir, "brand_story.txt")
    brand_story_text = read_text(brand_story_path)
    input_draft_path = os.path.join(input_dir, "draft.md")
    input_draft_text = read_text(input_draft_path)

    if isinstance(brand_story_text, str) and brand_story_text.strip():
        if isinstance(input_draft_text, str):
            if brand_story_text.strip() != input_draft_text.strip():
                checks["brand_story_exists_diff"] = True
        else:
            # If input draft missing or unreadable, still require non-empty output and treat as different
            checks["brand_story_exists_diff"] = True

        # No markdown artifacts in lines
        no_md_artifacts = True
        for ln in brand_story_text.splitlines():
            s = ln.lstrip()
            if s.startswith("#") or s.startswith("-") or s.startswith("*") or s.startswith("```"):
                no_md_artifacts = False
                break
        if no_md_artifacts:
            checks["brand_story_no_markdown_artifacts"] = True

        # No $$ LaTeX
        if "$$" not in brand_story_text:
            checks["brand_story_no_dollar_math"] = True

        # No chat signoffs
        bs_lower = brand_story_text.lower()
        if ("hope this helps" not in bs_lower) and ("let me know if you have any questions" not in bs_lower):
            checks["brand_story_no_chat_signoff"] = True

    reward = compute_reward(checks)

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()