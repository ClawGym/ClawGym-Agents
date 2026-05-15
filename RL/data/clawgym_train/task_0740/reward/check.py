import json
import os
import sys
import re

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    result_path = os.path.join(output_dir, "agent.risk.vendor_assessor.contract.v1.2.0.json")
    checks = {
        "file_exists": False,
        "json_parse_ok": False,
        "schema_id_correct": False,
        "schema_version_correct": False,
        "agent_id_correct": False,
        "agent_version_correct": False,
        "status_correct": False,
        "owner_id_correct": False,
        "owner_kind_correct": False,
        "meta_title_correct": False,
        "meta_lang_correct": False,
        "meta_tags_includes_required": False,
        "meta_description_contains_keywords": False,
        "task_domains_include_required": False,
        "capability_tags_include_required": False,
        "input_envelopes_exact": False,
        "output_envelopes_exact": False,
        "envelope_ids_pattern_ok": False,
        "runtime_binding_correct": False,
        "connectors_include_all_required": False,
        "policy_profile_correct": False,
        "observability_compact_true": False,
        "observability_semantic_true": False,
        "observability_otel_true": False,
        "observability_required_artifacts_includes_required": False,
        "determinism_seed_required_true": False,
        "determinism_replay_supported_true": False,
        "limits_present": False,
        "limits_max_tokens_in_range": False,
        "limits_max_duration_in_range": False,
        "limits_max_tool_calls_in_range": False,
    }

    data = None

    # Determine required connectors from input/connectors.json; fallback to the minimum three if missing or invalid.
    connectors_file = os.path.join(input_dir, "connectors.json")
    required_connectors = {
        "connector.vendor_db.supplier_v1",
        "connector.ticket.jira_v1",
        "connector.security.policymap_v1",
    }
    if os.path.isfile(connectors_file):
        connectors_json, err = load_json_file(connectors_file)
        if err is None:
            try:
                if isinstance(connectors_json, list):
                    # expect list of strings
                    extracted = [c for c in connectors_json if isinstance(c, str)]
                    if extracted:
                        required_connectors = set(extracted)
                elif isinstance(connectors_json, dict):
                    # try common keys
                    for k in ("connectors", "connector_refs", "required_connectors"):
                        if k in connectors_json and isinstance(connectors_json[k], list):
                            extracted = [c for c in connectors_json[k] if isinstance(c, str)]
                            if extracted:
                                required_connectors = set(extracted)
                                break
            except Exception:
                # keep fallback
                pass

    if os.path.isfile(result_path):
        checks["file_exists"] = True
        data, err = load_json_file(result_path)
        if err is None and isinstance(data, dict):
            checks["json_parse_ok"] = True

            # Top-level checks
            if data.get("schema_id") == "ds.mova_agent_contract_core_v1":
                checks["schema_id_correct"] = True
            if data.get("schema_version") == "1.0.0":
                checks["schema_version_correct"] = True
            if data.get("agent_id") == "agent.risk.vendor_assessor":
                checks["agent_id_correct"] = True
            if data.get("agent_version") == "1.2.0":
                checks["agent_version_correct"] = True
            if data.get("status") == "draft":
                checks["status_correct"] = True

            # Owner
            owner = data.get("owner", {})
            if isinstance(owner, dict):
                if owner.get("owner_id") == "risk-ops-team":
                    checks["owner_id_correct"] = True
                if owner.get("owner_kind") == "organization":
                    checks["owner_kind_correct"] = True

            # Meta
            meta = data.get("meta", {})
            if isinstance(meta, dict):
                if meta.get("title") == "Vendor Risk Assessor":
                    checks["meta_title_correct"] = True
                if meta.get("lang") == "en":
                    checks["meta_lang_correct"] = True
                tags = meta.get("tags")
                if isinstance(tags, list):
                    required_tags = {"risk", "vendor", "compliance"}
                    tags_strs = set([str(t) for t in tags])
                    if required_tags.issubset(tags_strs):
                        checks["meta_tags_includes_required"] = True
                desc = meta.get("description")
                if isinstance(desc, str) and len(desc.strip()) > 0:
                    # must contain escalation, PII, GDPR (case-sensitive substrings as specified)
                    if all(substr in desc for substr in ["escalation", "PII", "GDPR"]):
                        checks["meta_description_contains_keywords"] = True

            # Task domains & capabilities
            task_domains = data.get("task_domains", [])
            if isinstance(task_domains, list):
                td_set = set(task_domains)
                if "risk" in td_set and "compliance" in td_set:
                    checks["task_domains_include_required"] = True
            capabilities = data.get("capability_tags", [])
            if isinstance(capabilities, list):
                cap_set = set([str(c) for c in capabilities])
                required_caps = {"analyze", "classify", "validate", "escalate"}
                if required_caps.issubset(cap_set):
                    checks["capability_tags_include_required"] = True

            # Envelopes
            input_envs = data.get("input_envelope_ids", [])
            output_envs = data.get("output_envelope_ids", [])
            expected_input = {"env.risk.assessment_request_v1", "env.risk.vendor_profile_v1"}
            expected_output = {"env.risk.assessment_report_v1", "env.risk.escalation_request_v1"}
            if isinstance(input_envs, list):
                if set(input_envs) == expected_input:
                    checks["input_envelopes_exact"] = True
            if isinstance(output_envs, list):
                if set(output_envs) == expected_output:
                    checks["output_envelopes_exact"] = True
            # Envelope pattern
            env_pattern = re.compile(r"^env\.risk\.[a-z0-9_]+_v1$")
            all_envs = []
            if isinstance(input_envs, list):
                all_envs.extend([e for e in input_envs if isinstance(e, str)])
            if isinstance(output_envs, list):
                all_envs.extend([e for e in output_envs if isinstance(e, str)])
            if all_envs and all(env_pattern.match(e) for e in all_envs):
                checks["envelope_ids_pattern_ok"] = True

            # Runtime & connectors
            if data.get("runtime_binding_ref") == "runtime.cloud.generic_v1":
                checks["runtime_binding_correct"] = True
            connectors = data.get("connector_refs", [])
            if isinstance(connectors, list):
                conn_set = set([str(c) for c in connectors])
                if required_connectors.issubset(conn_set):
                    checks["connectors_include_all_required"] = True

            # Policy
            if data.get("policy_profile_ref") == "policy.risk.vendor_assessment_guardrails_v1":
                checks["policy_profile_correct"] = True

            # Observability
            obs = data.get("observability_profile", {})
            if isinstance(obs, dict):
                if obs.get("compact_required") is True:
                    checks["observability_compact_true"] = True
                if obs.get("semantic_required") is True:
                    checks["observability_semantic_true"] = True
                if obs.get("otel_correlation_required") is True:
                    checks["observability_otel_true"] = True
                artifacts = obs.get("required_artifacts", [])
                if isinstance(artifacts, list):
                    required_artifacts = {"episode", "decision_log", "audit_trail"}
                    art_set = set([str(a) for a in artifacts])
                    if required_artifacts.issubset(art_set):
                        checks["observability_required_artifacts_includes_required"] = True

            # Determinism & limits
            det = data.get("determinism_controls", {})
            if isinstance(det, dict):
                if det.get("seed_required") is True:
                    checks["determinism_seed_required_true"] = True
                if det.get("replay_supported") is True:
                    checks["determinism_replay_supported_true"] = True
            limits = data.get("limits")
            if isinstance(limits, dict):
                checks["limits_present"] = True
                mt = limits.get("max_tokens")
                md = limits.get("max_duration_ms")
                mc = limits.get("max_tool_calls")
                if isinstance(mt, int) and 3000 <= mt <= 8000:
                    checks["limits_max_tokens_in_range"] = True
                if isinstance(md, int) and 90000 <= md <= 180000:
                    checks["limits_max_duration_in_range"] = True
                if isinstance(mc, int) and mc >= 5:
                    checks["limits_max_tool_calls_in_range"] = True

    # Compute reward: if no output file, reward = 0.0
    total_checks = len([k for k in checks.keys()])
    # Do not include file existence and json parse in denominator? The instructions allow any.
    # We include all checks; if file missing, all are False and reward 0.0.
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if checks["file_exists"] and checks["json_parse_ok"]:
        # Use fraction of all checks
        reward = passed / total_checks if total_checks > 0 else 0.0
    else:
        reward = 0.0

    # Ensure reward between 0 and 1
    reward = max(0.0, min(1.0, float(reward)))

    output_obj = {"reward": reward}
    output_obj.update(checks)
    print(json.dumps(output_obj))

if __name__ == "__main__":
    main()