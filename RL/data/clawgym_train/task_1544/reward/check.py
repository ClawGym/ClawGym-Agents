import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def safe_get(d, *keys):
    cur = d
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur

def is_valid_severity(val):
    return isinstance(val, str) and val in ("CRITICAL", "HIGH")

def contains_profiles(obj, required):
    # Search within hooks object for 'minimal', 'standard', 'strict'
    found = set()

    def walk(x):
        nonlocal found
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(k, str) and k in required:
                    found.add(k)
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)
        elif isinstance(x, str):
            if x in required:
                found.add(x)

    walk(obj)
    return all(r in found for r in required)

def extract_languages_from_manifest(manifest):
    langs = set()
    if not isinstance(manifest, dict):
        return []
    # Common patterns: {"languages": ["python","typescript"]} or dict entries with languages
    if "languages" in manifest and isinstance(manifest["languages"], list):
        for v in manifest["languages"]:
            if isinstance(v, str) and v.strip():
                langs.add(v.strip().lower())
    # Also check nested keys
    for k, v in manifest.items():
        if isinstance(v, list) and k.lower().startswith("lang"):
            for item in v:
                if isinstance(item, str) and item.strip():
                    langs.add(item.strip().lower())
    return sorted(langs)

def has_planning_and_research_commands(cmds):
    if not isinstance(cmds, list):
        return False
    has_plan = False
    has_research = False
    for c in cmds:
        name = (c.get("name") if isinstance(c, dict) else None) or ""
        desc = (c.get("description") if isinstance(c, dict) else None) or ""
        text = f"{name} {desc}".lower()
        if "plan" in text:
            has_plan = True
        if "research" in text or "research-first" in text:
            has_research = True
    return has_plan and has_research

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    config_path = os.path.join(output_dir, "harness", "config.json")
    runtime_checks_path = os.path.join(output_dir, "security", "runtime_checks.json")
    entra_audit_path = os.path.join(output_dir, "identity", "entra_audit.json")
    presentation_path = os.path.join(output_dir, "presentation", "overview.html")

    # Input reference files
    project_manifest_path = os.path.join(input_dir, "project_manifest.json")
    role_assignments_path = os.path.join(input_dir, "entra", "role_assignments.json")
    threat_policies_path = os.path.join(input_dir, "threat_policies.yaml")
    branding_path = os.path.join(input_dir, "branding.json")

    checks = {
        # config.json checks
        "config_exists": False,
        "config_valid_json": False,
        "config_has_required_top_keys": False,
        "config_slash_commands_planning_and_research_present": False,
        "config_package_manager_priority_correct": False,
        "config_runtime_security_mode_warn_only": False,
        "config_runtime_security_reference_points_to_runtime_checks": False,
        "config_hooks_profiles_include_minimal_standard_strict": False,
        "config_language_rules_cover_project_languages": False,

        # runtime_checks.json checks
        "runtime_checks_exists": False,
        "runtime_checks_valid_json": False,
        "runtime_checks_length_12": False,
        "runtime_checks_ids_complete_and_exact": False,
        "runtime_checks_severities_valid": False,

        # entra_audit.json checks
        "entra_audit_exists": False,
        "entra_audit_valid_json": False,
        "entra_audit_has_risk_score_valid": False,
        "entra_audit_findings_len_gte_3": False,
        "entra_audit_findings_fields_valid": False,
        "entra_audit_admin_mfa_finding_present": False,

        # presentation checks
        "presentation_exists": False,
        "presentation_has_min_4_slides": False,
        "presentation_css_enforces_viewport_and_no_scroll": False,
        "presentation_has_required_phrases": False,
        "presentation_runtime_security_slide_mentions_12": False,
    }

    # Load inputs for reference
    manifest_json, _ = load_json(project_manifest_path)
    role_assignments_text = read_text(role_assignments_path) or ""
    admin_present_in_input = ("Global Admin" in role_assignments_text) or ("Global Administrator" in role_assignments_text)

    # 1) config.json validation
    if os.path.isfile(config_path):
        checks["config_exists"] = True
        config_json, err = load_json(config_path)
        if isinstance(config_json, dict):
            checks["config_valid_json"] = True

            # required top-level keys
            required_top = ["slash_commands", "hooks", "runtime_security", "package_manager_detection", "language_rules"]
            has_all = all(k in config_json for k in required_top)
            if has_all:
                checks["config_has_required_top_keys"] = True

                # slash commands include planning and research
                slash_cmds = config_json.get("slash_commands")
                if has_planning_and_research_commands(slash_cmds):
                    checks["config_slash_commands_planning_and_research_present"] = True

                # package manager detection priority exact order
                pmd = config_json.get("package_manager_detection", {})
                priority = pmd.get("priority") if isinstance(pmd, dict) else None
                expected_priority = ["env_var", "project_config", "package_json_field", "lock_file", "global_config", "fallback"]
                if isinstance(priority, list) and priority == expected_priority:
                    checks["config_package_manager_priority_correct"] = True

                # runtime_security mode "warn_only"
                rs = config_json.get("runtime_security", {})
                mode = rs.get("mode") if isinstance(rs, dict) else None
                if mode == "warn_only":
                    checks["config_runtime_security_mode_warn_only"] = True

                # runtime checks reference path check
                reference = rs.get("reference") if isinstance(rs, dict) else None
                if isinstance(reference, str):
                    ref_ok = False
                    # Accept exact path under output or a relative path under output
                    # Allowed: "output/security/runtime_checks.json" or "security/runtime_checks.json"
                    if "output/security/runtime_checks.json" in reference or reference.strip() == "security/runtime_checks.json":
                        ref_ok = True
                    # Also allow if the path resolves to the runtime_checks_path
                    else:
                        # Try to resolve relative to workspace root or output dir
                        # Build a path as if relative to output directory
                        candidate1 = os.path.join(output_dir, reference)
                        if os.path.normpath(candidate1) == os.path.normpath(runtime_checks_path):
                            ref_ok = True
                    if ref_ok:
                        checks["config_runtime_security_reference_points_to_runtime_checks"] = True

                # hooks profiles include minimal, standard, strict
                hooks = config_json.get("hooks", {})
                if isinstance(hooks, dict):
                    if contains_profiles(hooks, {"minimal", "standard", "strict"}):
                        checks["config_hooks_profiles_include_minimal_standard_strict"] = True

                # language rules cover project languages
                language_rules = config_json.get("language_rules", {})
                if isinstance(language_rules, dict):
                    languages = extract_languages_from_manifest(manifest_json) if manifest_json else []
                    if languages:
                        cover = True
                        for lang in languages:
                            # Allow exact key or case-insensitive match among keys
                            keys_lower = {k.lower() for k in language_rules.keys()}
                            if lang.lower() not in keys_lower:
                                cover = False
                                break
                        if cover:
                            checks["config_language_rules_cover_project_languages"] = True
                    else:
                        # If no languages listed in manifest, we cannot positively verify coverage
                        # Leave as False
                        pass

    # 2) runtime_checks.json validation
    if os.path.isfile(runtime_checks_path):
        checks["runtime_checks_exists"] = True
        runtime_checks_json, err = load_json(runtime_checks_path)
        if isinstance(runtime_checks_json, list):
            checks["runtime_checks_valid_json"] = True

            # Must be exactly 12
            if len(runtime_checks_json) == 12:
                checks["runtime_checks_length_12"] = True

            # Check ids and severities and descriptions presence
            required_ids = {
                "RT_REVSHELL",
                "RT_CRED_EXFIL",
                "RT_GUARDRAIL_OFF",
                "RT_GATEKEEPER",
                "RT_AMOS",
                "RT_MAL_IP",
                "RT_DNS_EXFIL",
                "RT_B64_SHELL",
                "RT_CURL_BASH",
                "RT_SSH_READ",
                "RT_WALLET",
                "RT_CLOUD_META",
            }
            ids_present = set()
            severities_ok = True
            structure_ok = True
            for item in runtime_checks_json:
                if not isinstance(item, dict):
                    structure_ok = False
                    severities_ok = False
                    break
                if "id" not in item or "severity" not in item or "description" not in item:
                    structure_ok = False
                    severities_ok = False
                    break
                ids_present.add(item.get("id"))
                if not is_valid_severity(item.get("severity")):
                    severities_ok = False
            if structure_ok and ids_present == required_ids:
                checks["runtime_checks_ids_complete_and_exact"] = True
            if structure_ok and severities_ok:
                checks["runtime_checks_severities_valid"] = True

    # 3) entra_audit.json validation
    if os.path.isfile(entra_audit_path):
        checks["entra_audit_exists"] = True
        entra_json, err = load_json(entra_audit_path)
        if isinstance(entra_json, dict):
            checks["entra_audit_valid_json"] = True

            # risk_score validity
            risk_score = entra_json.get("risk_score")
            if isinstance(risk_score, str) and risk_score in {"Critical", "High", "Medium", "Low"}:
                checks["entra_audit_has_risk_score_valid"] = True

            # findings length >= 3
            findings = entra_json.get("findings")
            if isinstance(findings, list) and len(findings) >= 3:
                checks["entra_audit_findings_len_gte_3"] = True

                # Each finding must include principal, finding, risk, mitre
                fields_ok = True
                for f in findings:
                    if not isinstance(f, dict):
                        fields_ok = False
                        break
                    if not all(k in f for k in ["principal", "finding", "risk", "mitre"]):
                        fields_ok = False
                        break
                if fields_ok:
                    checks["entra_audit_findings_fields_valid"] = True

                # If input contains "Global Admin" or "Global Administrator", require at least one finding referencing those and MFA
                admin_finding_ok = False
                if admin_present_in_input:
                    for f in findings:
                        try:
                            text = (str(f.get("principal", "")) + " " + str(f.get("finding", ""))).lower()
                        except Exception:
                            text = ""
                        if ("global admin" in text or "global administrator" in text) and ("mfa" in text):
                            admin_finding_ok = True
                            break
                    if admin_finding_ok:
                        checks["entra_audit_admin_mfa_finding_present"] = True
                else:
                    # Not applicable; set True but exclude from scoring later
                    checks["entra_audit_admin_mfa_finding_present"] = True

    # 4) presentation HTML validation
    if os.path.isfile(presentation_path):
        checks["presentation_exists"] = True
        html = read_text(presentation_path)
        if isinstance(html, str):
            # At least 4 slides
            slide_count = html.count('class="slide"')
            if slide_count >= 4:
                checks["presentation_has_min_4_slides"] = True

            # CSS: .slide height 100vh or 100dvh and overflow hidden
            css_ok = False
            # Look for a CSS rule that includes ".slide" and "height: 100vh" or "height: 100dvh" and "overflow: hidden"
            lower_html = html.lower()
            contains_slide = ".slide" in lower_html
            contains_height = ("height: 100vh".lower() in lower_html) or ("height: 100dvh".lower() in lower_html)
            contains_overflow = "overflow: hidden" in lower_html
            if contains_slide and contains_height and contains_overflow:
                css_ok = True
            if css_ok:
                checks["presentation_css_enforces_viewport_and_no_scroll"] = True

            # Required phrases
            phrases_ok = all(p in html for p in ["Slash Commands", "Lifecycle Hooks", "Language Rules", "Runtime Security", "Identity Audit"])
            if phrases_ok:
                checks["presentation_has_required_phrases"] = True

            # Runtime Security and "12" present
            if ("Runtime Security" in html) and ("12" in html):
                checks["presentation_runtime_security_slide_mentions_12"] = True

    # Compute reward
    # Only include admin_mfa_finding_present in scoring if admin is present in input
    scored_check_names = list(checks.keys())
    if not admin_present_in_input and "entra_audit_admin_mfa_finding_present" in scored_check_names:
        scored_check_names.remove("entra_audit_admin_mfa_finding_present")

    # Enforce no-op baseline: if output dir missing or none of required files exist, reward = 0.0
    required_files = [config_path, runtime_checks_path, entra_audit_path, presentation_path]
    required_exist_any = any(os.path.isfile(p) for p in required_files)
    if not os.path.isdir(output_dir) or not required_exist_any:
        # Ensure all artifact-dependent checks remain False (they already are by default)
        reward_value = 0.0
    else:
        total = len(scored_check_names)
        passed = sum(1 for k in scored_check_names if checks.get(k, False))
        reward_value = (passed / total) if total > 0 else 0.0

    # Clamp reward to [0,1]
    if reward_value < 0:
        reward_value = 0.0
    if reward_value > 1:
        reward_value = 1.0

    # Print final JSON
    result = {"reward": round(reward_value, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()