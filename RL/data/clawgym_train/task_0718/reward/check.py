import json
import os
import re
import sys

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def extract_new_old_operator(payload):
    # Attempt to robustly extract new agent id, old agent id (to delete), operator, and consent text
    new_id = None
    old_id = None
    operator = None
    consent_text = None

    # Direct keys
    for k in ["new_agent_id", "newAgentId", "create_agent_id", "createAgentId", "agent_id_new"]:
        if isinstance(payload.get(k), str) and payload.get(k).strip():
            new_id = payload.get(k).strip()
            break

    for k in ["delete_agent_id", "deleteAgentId", "to_delete", "agent_id_delete", "retire_agent_id"]:
        if isinstance(payload.get(k), str) and payload.get(k).strip():
            old_id = payload.get(k).strip()
            break

    # Nested dicts
    if new_id is None:
        for k in ["new_agent", "create", "agent_new"]:
            v = payload.get(k)
            if isinstance(v, dict):
                cand = v.get("id") or v.get("agent_id")
                if isinstance(cand, str) and cand.strip():
                    new_id = cand.strip()
                    break

    if old_id is None:
        for k in ["delete_agent", "retire", "remove"]:
            v = payload.get(k)
            if isinstance(v, dict):
                cand = v.get("id") or v.get("agent_id")
                if isinstance(cand, str) and cand.strip():
                    old_id = cand.strip()
                    break

    # Fallback heuristic: if 'agent_id' present and 'delete_agent_id' present, treat 'agent_id' as new
    if new_id is None and isinstance(payload.get("agent_id"), str):
        if payload.get("agent_id").strip():
            # Avoid confusion if it's actually the delete id
            if old_id and payload.get("agent_id").strip() == old_id:
                pass
            else:
                new_id = payload.get("agent_id").strip()

    # Operator
    for k in ["operator", "operator_name", "operatorName", "performed_by"]:
        if isinstance(payload.get(k), str) and payload.get(k).strip():
            operator = payload.get(k).strip()
            break

    # Consent text
    for k in ["consent_text", "consentText", "credential_inheritance_consent", "inherit_consent_text"]:
        if isinstance(payload.get(k), str) and payload.get(k).strip():
            consent_text = payload.get(k).strip()
            break

    return new_id, old_id, operator, consent_text

def iso8601_utc(s):
    if not isinstance(s, str):
        return False
    # Basic strict UTC Z format: YYYY-MM-DDTHH:MM:SSZ
    return re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", s) is not None

def find_agent_ids_in_registry(registry):
    ids = set()
    agents = registry.get("agents")
    if isinstance(agents, list):
        for a in agents:
            if isinstance(a, dict):
                aid = a.get("id")
                if isinstance(aid, str) and aid:
                    ids.add(aid)
    return ids

def has_telegram_binding(agent_obj):
    # Require 'bindings' key to exist per spec
    if not isinstance(agent_obj, dict):
        return False
    if "bindings" not in agent_obj:
        return False
    bindings = agent_obj.get("bindings")
    if not isinstance(bindings, list):
        return False
    for item in bindings:
        if isinstance(item, dict):
            # match.channel == "telegram"
            match = item.get("match")
            if isinstance(match, dict) and match.get("channel") == "telegram":
                return True
            # or direct channel field
            if item.get("channel") == "telegram":
                return True
            # or clearly labeled indication like {"telegram": true}
            if ("telegram" in item) and (item.get("telegram") is True or str(item.get("telegram")).lower() == "true"):
                return True
            # or name/label includes 'telegram'
            for key in ["label", "name", "type"]:
                v = item.get(key)
                if isinstance(v, str) and "telegram" in v:
                    return True
        elif isinstance(item, str):
            if "telegram" in item:
                return True
    return False

def parse_markdown_table_rows(md_text):
    rows = []
    lines = md_text.splitlines()
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        # skip separator lines like |---|
        if re.match(r"^\|\s*-{3,}\s*\|", line.strip()):
            continue
        parts = [p.strip() for p in line.strip().split("|")]
        # Typical: ['', 'UTC Time', 'Action', 'Agent ID', 'Summary', 'Operator', '']
        if len(parts) >= 6:
            header_like = parts[1].lower()
            if "utc time" in header_like and "action" in " ".join(parts[2:]):
                # header row
                continue
            # Data row heuristic: ensure not header markers
            if parts[1] and parts[2] and parts[3]:
                rows.append({
                    "timestamp": parts[1],
                    "action": parts[2],
                    "agent_id": parts[3],
                    "summary": parts[4] if len(parts) > 4 else "",
                    "operator": parts[5] if len(parts) > 5 else ""
                })
    return rows

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # plan.md checks
        "plan_exists": False,
        "plan_contains_new_agent_id": False,
        "plan_contains_old_agent_id": False,
        "plan_contains_explicit_consent_phrase": False,
        "plan_contains_delete_confirmation_literal": False,
        "plan_mentions_archive": False,
        "plan_mentions_delete": False,
        # consent.json checks
        "consent_json_valid": False,
        "consent_agent_id_matches_new": False,
        "consent_inherit_auth_true": False,
        "consent_text_contains_exact_phrase": False,
        # agent-registry.json checks
        "registry_json_valid": False,
        "registry_has_updatedAt": False,
        "registry_has_agents_array": False,
        "registry_has_new_agent": False,
        "registry_excludes_old_agent": False,
        "registry_new_agent_has_telegram_binding": False,
        # AGENT_STATUS.md checks
        "status_md_exists": False,
        "status_md_has_exact_header": False,
        "status_md_contains_new_agent": False,
        "status_md_excludes_old_agent": False,
        # archive_manifest.json checks
        "archive_manifest_json_valid": False,
        "archive_manifest_agent_ok": False,
        "archive_manifest_root_ok": False,
        "archive_manifest_timestamp_is_string": False,
        "archive_manifest_snapshots_exact": False,
        # AGENT_LIFECYCLE_LOG.md checks
        "lifecycle_log_exists": False,
        "lifecycle_log_has_exact_header": False,
        "lifecycle_log_has_create_for_new": False,
        "lifecycle_log_has_approve_pairing_for_new": False,
        "lifecycle_log_has_delete_for_old": False,
        "lifecycle_log_delete_summary_has_safedelete": False,
        "lifecycle_log_operator_present": False,
        "lifecycle_log_timestamps_iso8601": False,
        # status_diffs.json checks
        "diffs_json_valid": False,
        "diffs_added_has_new": False,
        "diffs_removed_has_old": False,
    }

    # Load inputs
    agent_ops_path = os.path.join(input_dir, "agent_ops_request.json")
    initial_registry_path = os.path.join(input_dir, "initial_registry.json")

    agent_ops, _ = read_json(agent_ops_path)
    initial_registry, _ = read_json(initial_registry_path)

    new_agent_id, old_agent_id, operator_name, consent_text_input = (None, None, None, None)
    if isinstance(agent_ops, dict):
        new_agent_id, old_agent_id, operator_name, consent_text_input = extract_new_old_operator(agent_ops)

    # 1) plan.md
    plan_path = os.path.join(output_dir, "plan.md")
    plan_text, plan_err = read_text(plan_path)
    if plan_err is None and isinstance(plan_text, str):
        checks["plan_exists"] = True
        if isinstance(new_agent_id, str) and new_agent_id and new_agent_id in plan_text:
            checks["plan_contains_new_agent_id"] = True
        if isinstance(old_agent_id, str) and old_agent_id and old_agent_id in plan_text:
            checks["plan_contains_old_agent_id"] = True
        # phrase "explicit consent"
        if "explicit consent" in plan_text.lower():
            checks["plan_contains_explicit_consent_phrase"] = True
        # must contain literal "DELETE <old_agent_id>"
        if isinstance(old_agent_id, str) and old_agent_id:
            if f"DELETE {old_agent_id}" in plan_text:
                checks["plan_contains_delete_confirmation_literal"] = True
        # mentions archive and delete
        if re.search(r"\barchive\b", plan_text, flags=re.IGNORECASE):
            checks["plan_mentions_archive"] = True
        if re.search(r"\bdelete\b", plan_text, flags=re.IGNORECASE):
            checks["plan_mentions_delete"] = True

    # 2) consent.json
    consent_path = os.path.join(output_dir, "consent.json")
    consent, consent_err = read_json(consent_path)
    if consent_err is None and isinstance(consent, dict):
        checks["consent_json_valid"] = True
        if isinstance(new_agent_id, str) and isinstance(consent.get("agent_id"), str):
            if consent.get("agent_id") == new_agent_id:
                checks["consent_agent_id_matches_new"] = True
        inherit_auth = consent.get("inherit_auth")
        if inherit_auth is True:
            checks["consent_inherit_auth_true"] = True
        ct = consent.get("consent_text")
        if isinstance(ct, str) and "I explicitly consent" in ct:
            checks["consent_text_contains_exact_phrase"] = True

    # 3) agent-registry.json
    registry_path = os.path.join(output_dir, "agent-registry.json")
    final_registry, reg_err = read_json(registry_path)
    if reg_err is None and isinstance(final_registry, dict):
        checks["registry_json_valid"] = True
        if isinstance(final_registry.get("updatedAt"), str):
            checks["registry_has_updatedAt"] = True
        agents = final_registry.get("agents")
        if isinstance(agents, list):
            checks["registry_has_agents_array"] = True
            # presence of new agent and absence of old agent
            new_obj = None
            found_new = False
            found_old = False
            for obj in agents:
                if isinstance(obj, dict):
                    if obj.get("id") == new_agent_id:
                        found_new = True
                        new_obj = obj
                    if obj.get("id") == old_agent_id:
                        found_old = True
            if found_new:
                checks["registry_has_new_agent"] = True
                # verify telegram binding
                if has_telegram_binding(new_obj):
                    checks["registry_new_agent_has_telegram_binding"] = True
            if not found_old:
                # only mark exclude old if old_agent_id is known
                if isinstance(old_agent_id, str) and old_agent_id:
                    checks["registry_excludes_old_agent"] = True

    # 4) AGENT_STATUS.md
    status_md_path = os.path.join(output_dir, "AGENT_STATUS.md")
    status_md_text, status_md_err = read_text(status_md_path)
    header_exact = "| Agent ID | Name | Identity | Workspace | Model | Heartbeat | Default |"
    if status_md_err is None and isinstance(status_md_text, str):
        checks["status_md_exists"] = True
        has_header = False
        for line in status_md_text.splitlines():
            if line.strip() == header_exact:
                has_header = True
                break
        if has_header:
            checks["status_md_has_exact_header"] = True
        if isinstance(new_agent_id, str) and new_agent_id and new_agent_id in status_md_text:
            checks["status_md_contains_new_agent"] = True
        if isinstance(old_agent_id, str) and old_agent_id and (old_agent_id not in status_md_text):
            checks["status_md_excludes_old_agent"] = True

    # 5) archive_manifest.json
    archive_manifest_path = os.path.join(output_dir, "archive_manifest.json")
    archive_manifest, arch_err = read_json(archive_manifest_path)
    if arch_err is None and isinstance(archive_manifest, dict):
        checks["archive_manifest_json_valid"] = True
        if isinstance(archive_manifest.get("agent_id"), str) and old_agent_id:
            if archive_manifest.get("agent_id") == old_agent_id:
                checks["archive_manifest_agent_ok"] = True
        if archive_manifest.get("archive_root") == "state/archive":
            checks["archive_manifest_root_ok"] = True
        ts = archive_manifest.get("timestamp")
        if isinstance(ts, str) and ts:
            checks["archive_manifest_timestamp_is_string"] = True
        snaps = archive_manifest.get("snapshots")
        required_snaps = {
            "openclaw.agents.list.json",
            "openclaw.status.json",
            "openclaw.gateway.status.json",
        }
        if isinstance(snaps, list):
            snap_set = set()
            ok_types = True
            for s in snaps:
                if not isinstance(s, str):
                    ok_types = False
                    break
                snap_set.add(s)
            if ok_types and snap_set == required_snaps and len(snaps) == 3:
                checks["archive_manifest_snapshots_exact"] = True

    # 6) AGENT_LIFECYCLE_LOG.md
    lifecycle_log_path = os.path.join(output_dir, "AGENT_LIFECYCLE_LOG.md")
    lifecycle_text, lifecycle_err = read_text(lifecycle_log_path)
    if lifecycle_err is None and isinstance(lifecycle_text, str):
        checks["lifecycle_log_exists"] = True
        header_line = "| UTC Time | Action | Agent ID | Summary | Operator |"
        has_header = any(line.strip() == header_line for line in lifecycle_text.splitlines())
        if has_header:
            checks["lifecycle_log_has_exact_header"] = True

        rows = parse_markdown_table_rows(lifecycle_text)
        # Look for specific actions
        create_rows = [r for r in rows if r.get("action") == "create" and r.get("agent_id") == new_agent_id]
        approve_rows = [r for r in rows if r.get("action") == "approve-pairing" and r.get("agent_id") == new_agent_id]
        delete_rows = [r for r in rows if r.get("action") == "delete" and r.get("agent_id") == old_agent_id]

        if create_rows:
            checks["lifecycle_log_has_create_for_new"] = True
        if approve_rows:
            checks["lifecycle_log_has_approve_pairing_for_new"] = True
        if delete_rows:
            checks["lifecycle_log_has_delete_for_old"] = True
            # summary substring on at least one delete row
            if any(("safe-delete; archive=" in (r.get("summary") or "")) for r in delete_rows):
                checks["lifecycle_log_delete_summary_has_safedelete"] = True

        # operator presence
        if isinstance(operator_name, str) and operator_name and operator_name in lifecycle_text:
            checks["lifecycle_log_operator_present"] = True

        # timestamps pattern: ensure all targeted action rows have ISO8601 UTC-like timestamps
        def rows_have_iso(rows_list):
            if not rows_list:
                return False
            for r in rows_list:
                if not iso8601_utc(r.get("timestamp", "")):
                    return False
            return True

        ts_ok = False
        # require that for each of the actions we detected, their rows have ISO timestamps
        parts_to_check = []
        if create_rows:
            parts_to_check.append(rows_have_iso(create_rows))
        if approve_rows:
            parts_to_check.append(rows_have_iso(approve_rows))
        if delete_rows:
            parts_to_check.append(rows_have_iso(delete_rows))
        # If none found, leave False; if any sections exist, require all of them to be True
        if parts_to_check and all(parts_to_check):
            ts_ok = True
        if ts_ok:
            checks["lifecycle_log_timestamps_iso8601"] = True

    # 7) status_diffs.json
    diffs_path = os.path.join(output_dir, "status_diffs.json")
    diffs, diffs_err = read_json(diffs_path)
    if diffs_err is None and isinstance(diffs, dict):
        checks["diffs_json_valid"] = True
        added = diffs.get("added")
        removed = diffs.get("removed")
        if isinstance(added, list) and isinstance(new_agent_id, str):
            if new_agent_id in [x for x in added if isinstance(x, str)]:
                checks["diffs_added_has_new"] = True
        if isinstance(removed, list) and isinstance(old_agent_id, str):
            if old_agent_id in [x for x in removed if isinstance(x, str)]:
                checks["diffs_removed_has_old"] = True

    # Compute reward
    # No-op baseline: if output/ missing or empty, most checks remain False -> reward 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Clamp to [0,1]
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()