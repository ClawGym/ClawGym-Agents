import json
import os
import re
import sys

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f.read().splitlines() if line.strip()]
    except Exception:
        return None

def extract_allowed_domains(obj):
    # Robust extraction of allowed domains from domain_policy.json
    # Supports:
    # - {"allowed_domains": ["general", ...]}
    # - {"domains": [...]}
    # - {"allowed": [...]}
    # - ["general", ...]
    # Fallback to common defaults if no list is found.
    defaults = {"general", "coding", "writing", "research", "ops", "philosophy"}
    if obj is None:
        return defaults
    if isinstance(obj, list):
        if all(isinstance(x, str) for x in obj):
            return set(obj)
        return defaults
    if isinstance(obj, dict):
        for key in ("allowed_domains", "domains", "allowed"):
            val = obj.get(key)
            if isinstance(val, list) and all(isinstance(x, str) for x in val):
                return set(val)
    # Attempt to collect any string-list values in dict
    collected = set()
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                collected.update(v)
    return collected or defaults

def is_base64_str(s):
    if not isinstance(s, str):
        return False
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", s or ""):
        return False
    return True

def word_count(text):
    if not isinstance(text, str):
        return 0
    return len([w for w in re.split(r"\s+", text.strip()) if w])

def safe_get(d, key, default=None):
    try:
        return d.get(key, default)
    except Exception:
        return default

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "att_new_exists": False,
        "att_new_array_min2": False,
        "att_new_schema_ok": False,
        "att_new_domains_allowed": False,
        "att_new_normalization_if_needed": False,  # conditionally weighted
        "rejected_exists_if_reason_invalid": False,  # conditionally weighted
        "trust_report_exists_and_agents_key": False,
        "trust_report_agents_exact_match": False,
        "trust_report_agent_details_fields": False,
        "trust_report_domain_breakdown_ok": False,
        "risk_assessment_ok": False,
        "summary_ok": False,
    }

    # Inputs for conditional checks
    requests_path = os.path.join(input_dir, "requests.json")
    domain_policy_path = os.path.join(input_dir, "domain_policy.json")
    score_targets_path = os.path.join(input_dir, "score_targets.txt")

    requests = read_json(requests_path)
    domain_policy = read_json(domain_policy_path)
    score_targets = read_text_lines(score_targets_path) or []

    allowed_domains = extract_allowed_domains(domain_policy)

    # Determine if any request has invalid domain relative to allowed set
    invalid_request_domains = set()
    if isinstance(requests, list):
        for r in requests:
            try:
                dom = r.get("domain")
                if isinstance(dom, str) and dom not in allowed_domains:
                    invalid_request_domains.add(dom)
            except Exception:
                continue

    # Determine if any request has generic/short reason to conditionally require rejected file
    generics = {"good", "nice", "ok", "fine", "whatever"}
    needs_rejected_due_to_reason = False
    if isinstance(requests, list):
        for r in requests:
            reason = r.get("reason") if isinstance(r, dict) else None
            if isinstance(reason, str):
                if len(reason.strip()) < 10 or reason.strip().lower() in generics:
                    needs_rejected_due_to_reason = True
                    break

    # Load outputs
    att_new_path = os.path.join(output_dir, "attestations_new.json")
    rejected_path = os.path.join(output_dir, "rejected_attestations.json")
    trust_report_path = os.path.join(output_dir, "trust_report.json")
    risk_assessment_path = os.path.join(output_dir, "risk_assessment.md")
    summary_path = os.path.join(output_dir, "summary.md")

    attestations_new = None
    if os.path.isfile(att_new_path):
        checks["att_new_exists"] = True
        attestations_new = read_json(att_new_path)

    # Validate attestations_new
    all_domains_in_allowed = False
    schema_ok = False
    array_min2 = False
    normalization_condition_met = False
    if isinstance(attestations_new, list):
        if len(attestations_new) >= 2:
            array_min2 = True
        # Validate objects
        objects_ok = True
        domains_ok = True
        normalized_hits = set()
        for obj in attestations_new:
            if not isinstance(obj, dict):
                objects_ok = False
                break
            # Required keys
            required_top = ["version", "attestor", "subject", "reason", "context",
                            "task_value", "domain", "stake", "timestamp", "expires_at", "signature"]
            for k in required_top:
                if k not in obj:
                    objects_ok = False
                    break
            if not objects_ok:
                break
            if obj.get("version") != "AAS-3.0":
                objects_ok = False
                break
            # attestor
            attestor = obj.get("attestor")
            if not isinstance(attestor, dict):
                objects_ok = False
                break
            if attestor.get("name") != "ReputationBot":
                objects_ok = False
                break
            email = attestor.get("email")
            if not (isinstance(email, str) and "@" in email and email.strip()):
                objects_ok = False
                break
            pubkey = attestor.get("pubkey")
            if not (isinstance(pubkey, str) and len(pubkey.strip()) > 0):
                objects_ok = False
                break
            # subject
            if not isinstance(obj.get("subject"), str) or not obj.get("subject").strip():
                objects_ok = False
                break
            # reason constraints
            reason = obj.get("reason")
            if not (isinstance(reason, str) and len(reason.strip()) >= 30 and reason.strip().lower() not in generics):
                objects_ok = False
                break
            # context
            if not isinstance(obj.get("context"), dict):
                objects_ok = False
                break
            # task_value
            if obj.get("task_value") not in {"low", "medium", "high", "critical"}:
                objects_ok = False
                break
            # domain
            dom = obj.get("domain")
            if not (isinstance(dom, str) and dom in allowed_domains):
                domains_ok = False
            # stake
            stake = obj.get("stake")
            if not isinstance(stake, dict):
                objects_ok = False
                break
            vouched = stake.get("vouched")
            stake_amt = stake.get("reputation_at_stake")
            if not isinstance(vouched, bool):
                objects_ok = False
                break
            if vouched:
                if not (isinstance(stake_amt, (int, float)) and stake_amt > 0):
                    objects_ok = False
                    break
            else:
                if stake_amt != 0:
                    objects_ok = False
                    break
            # timestamps
            ts = obj.get("timestamp")
            exp = obj.get("expires_at")
            if not (isinstance(ts, str) and ts.endswith("Z")):
                objects_ok = False
                break
            if not (isinstance(exp, str) and exp.endswith("Z")):
                objects_ok = False
                break
            # signature
            sig = obj.get("signature")
            if not (isinstance(sig, str) and is_base64_str(sig) and len(sig) >= 60):
                objects_ok = False
                break

            # normalization: if present, capture context.normalized_from when domain is 'general'
            ctx = obj.get("context", {})
            if isinstance(ctx, dict) and dom == "general" and "normalized_from" in ctx:
                nf = ctx.get("normalized_from")
                if isinstance(nf, str) and nf:
                    normalized_hits.add(nf)

        schema_ok = objects_ok
        all_domains_in_allowed = domains_ok
        if invalid_request_domains:
            # Require at least one normalized_from matching any invalid domain
            normalization_condition_met = any(d in normalized_hits for d in invalid_request_domains)
        else:
            normalization_condition_met = True  # Will be zero-weighted in scoring

    checks["att_new_array_min2"] = checks["att_new_exists"] and array_min2
    checks["att_new_schema_ok"] = checks["att_new_exists"] and schema_ok
    checks["att_new_domains_allowed"] = checks["att_new_exists"] and all_domains_in_allowed
    checks["att_new_normalization_if_needed"] = checks["att_new_exists"] and normalization_condition_met

    # Rejected attestations conditional check
    rejected_data = None
    if os.path.isfile(rejected_path):
        rejected_data = read_json(rejected_path)
    if needs_rejected_due_to_reason:
        if isinstance(rejected_data, list) and len(rejected_data) >= 1:
            # Verify each object includes subject and reasons array (basic)
            valid_items = True
            for it in rejected_data:
                if not isinstance(it, dict):
                    valid_items = False
                    break
                if "subject" not in it:
                    valid_items = False
                    break
                rs = it.get("reasons")
                if not (isinstance(rs, list) and all(isinstance(x, str) for x in rs) and len(rs) >= 1):
                    valid_items = False
                    break
            checks["rejected_exists_if_reason_invalid"] = valid_items
        else:
            checks["rejected_exists_if_reason_invalid"] = False
    else:
        # No invalid reason requests present; mark true but will be zero-weighted
        checks["rejected_exists_if_reason_invalid"] = True

    # Trust report checks
    trust_report = None
    agents_exact = False
    agents_key_ok = False
    details_ok = False
    domains_ok = False
    if os.path.isfile(trust_report_path):
        trust_report = read_json(trust_report_path)
        if isinstance(trust_report, dict) and "agents" in trust_report and isinstance(trust_report["agents"], dict):
            agents_key_ok = True
            agents_dict = trust_report["agents"]
            expected_agents = [a for a in score_targets if isinstance(a, str) and a.strip()]
            expected_set = set(expected_agents)
            present_set = set(agents_dict.keys())
            agents_exact = (present_set == expected_set)
            # Validate each agent entry
            per_details_ok = True
            per_domains_ok = True
            for agent in expected_set:
                entry = agents_dict.get(agent)
                if not isinstance(entry, dict):
                    per_details_ok = False
                    per_domains_ok = False
                    break
                # score
                if not isinstance(entry.get("score"), (int, float)):
                    per_details_ok = False
                # details
                details = entry.get("details")
                if not isinstance(details, dict):
                    per_details_ok = False
                else:
                    for fld in ("valid", "expired", "invalid_signatures", "vouches"):
                        if not isinstance(details.get(fld), int):
                            per_details_ok = False
                    if details.get("window") != "30 days":
                        per_details_ok = False
                # domain_breakdown
                db = entry.get("domain_breakdown")
                if not isinstance(db, dict):
                    per_domains_ok = False
                else:
                    # Each domain value must be an object with numeric 'score' and int 'attestations'
                    for dv in db.values():
                        if not isinstance(dv, dict):
                            per_domains_ok = False
                            break
                        if not isinstance(dv.get("score"), (int, float)):
                            per_domains_ok = False
                            break
                        if not isinstance(dv.get("attestations"), int):
                            per_domains_ok = False
                            break
            details_ok = per_details_ok
            domains_ok = per_domains_ok

    checks["trust_report_exists_and_agents_key"] = agents_key_ok
    checks["trust_report_agents_exact_match"] = agents_exact and agents_key_ok
    checks["trust_report_agent_details_fields"] = details_ok and agents_key_ok and agents_exact
    checks["trust_report_domain_breakdown_ok"] = domains_ok and agents_key_ok and agents_exact

    # risk_assessment.md
    risk_ok = False
    if os.path.isfile(risk_assessment_path):
        try:
            with open(risk_assessment_path, "r", encoding="utf-8") as f:
                txt = f.read()
            wc = word_count(txt)
            lower = txt.lower()
            has_private_key = "private key" in lower
            has_unencrypted = "unencrypted" in lower
            has_collusion = ("collusion" in lower) or ("colluding" in lower)
            has_no_ca = ("no certificate authority" in lower) or ("no ca" in lower) or ("no third-party" in lower)
            has_time = ("system time" in lower) or ("clock" in lower)
            if wc >= 120 and has_private_key and has_unencrypted and has_collusion and has_no_ca and has_time:
                risk_ok = True
        except Exception:
            risk_ok = False
    checks["risk_assessment_ok"] = risk_ok

    # summary.md
    summary_ok = False
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                stxt = f.read()
            if word_count(stxt) >= 100:
                summary_ok = True
        except Exception:
            summary_ok = False
    checks["summary_ok"] = summary_ok

    # Scoring with conditional weighting
    # Base checks always counted
    weighted_checks = []
    def add_check(key, weight=1.0):
        weighted_checks.append((key, weight))

    add_check("att_new_exists")
    add_check("att_new_array_min2")
    add_check("att_new_schema_ok")
    add_check("att_new_domains_allowed")
    # Normalization check only weighted if invalid domains exist in requests
    norm_weight = 1.0 if invalid_request_domains else 0.0
    add_check("att_new_normalization_if_needed", norm_weight)
    # Rejected file presence only weighted if invalid reasons exist
    rej_weight = 1.0 if needs_rejected_due_to_reason else 0.0
    add_check("rejected_exists_if_reason_invalid", rej_weight)
    add_check("trust_report_exists_and_agents_key")
    add_check("trust_report_agents_exact_match")
    add_check("trust_report_agent_details_fields")
    add_check("trust_report_domain_breakdown_ok")
    add_check("risk_assessment_ok")
    add_check("summary_ok")

    total_weight = sum(w for _, w in weighted_checks)
    if total_weight <= 0:
        # Fallback: if nothing is weightable due to missing inputs, set reward to 0
        reward = 0.0
    else:
        passed = 0.0
        for key, w in weighted_checks:
            if w <= 0:
                continue
            if checks.get(key, False):
                passed += w
        reward = passed / total_weight
        # Clamp
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Ensure no-op baseline: if output directory missing or empty important artifacts -> likely 0
    # Already naturally handled by failed checks; no additional override needed.

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()