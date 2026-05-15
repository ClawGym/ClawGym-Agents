import json
import os
import sys
import re
import hashlib

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)

def compute_sha256_hex(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks to False
    checks = {
        "has_scan_json": False,
        "scan_json_valid": False,
        "scan_has_required_keys": False,
        "scan_classification_dangerous": False,
        "scan_severity_counts_keys": False,
        "scan_findings_cover_required": False,
        "scan_recommendation_present": False,
        "has_summary_md": False,
        "summary_has_overall_classification": False,
        "summary_mentions_checks": False,
        "summary_has_recommendations_section": False,
        "has_attestation_json": False,
        "attestation_json_valid": False,
        "attestation_required_keys_valid": False,
        "attestation_classification_matches_scan": False,
        "attestation_sha_matches_scan": False,
    }

    # Paths
    scan_path = os.path.join(output_dir, "scan.json")
    summary_path = os.path.join(output_dir, "summary.md")
    attestation_path = os.path.join(output_dir, "attestation.json")

    # 1) scan.json validations
    scan_data = None
    if os.path.isfile(scan_path):
        checks["has_scan_json"] = True
        scan_data, err = load_json(scan_path)
        if scan_data is not None and isinstance(scan_data, dict):
            checks["scan_json_valid"] = True

            # Required top-level keys
            required_keys = ["findings", "severity_counts", "classification", "recommendation"]
            if all(k in scan_data for k in required_keys):
                checks["scan_has_required_keys"] = True

                # classification must be exactly DANGEROUS
                if isinstance(scan_data.get("classification"), str) and scan_data["classification"] == "DANGEROUS":
                    checks["scan_classification_dangerous"] = True

                # recommendation must be a non-empty string
                rec = scan_data.get("recommendation")
                if isinstance(rec, str) and rec.strip() != "":
                    checks["scan_recommendation_present"] = True

                # severity_counts must include INFO, LOW, MEDIUM, HIGH, CRITICAL as integer values
                sev = scan_data.get("severity_counts")
                if isinstance(sev, dict):
                    required_sev = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
                    if all(k in sev and is_int(sev[k]) for k in required_sev):
                        checks["scan_severity_counts_keys"] = True

                # findings coverage
                findings = scan_data.get("findings")
                if isinstance(findings, list):
                    # Map checks to entries
                    found_checks = {}
                    for item in findings:
                        if not isinstance(item, dict):
                            continue
                        chk = item.get("check")
                        if isinstance(chk, str) and chk:
                            # Keep the first occurrence
                            if chk not in found_checks:
                                found_checks[chk] = item

                    required_all = [
                        "BEHAVIOR_EXFILTRATION",
                        "PAYLOAD_B64_MALICIOUS",
                        "DEP_KNOWN_MALICIOUS",
                        "DEP_INSTALL_SCRIPT",
                        "STRUCT_UNSAFE_INSTRUCTION",
                    ]
                    either_one = ["STRUCT_HIDDEN_FILE", "STRUCT_BINARY"]

                    def valid_finding(obj):
                        # Must include path, description, and line_num (int)
                        if not isinstance(obj, dict):
                            return False
                        path = obj.get("path")
                        desc = obj.get("description")
                        ln = obj.get("line_num", None)
                        if not (isinstance(path, str) and path.startswith("input/skill_to_audit/")):
                            return False
                        if not (isinstance(desc, str) and desc.strip() != ""):
                            return False
                        if ln is None or not is_int(ln):
                            return False
                        return True

                    has_required = True
                    for chk_name in required_all:
                        item = found_checks.get(chk_name)
                        if item is None or not valid_finding(item):
                            has_required = False
                            break

                    has_either = False
                    for chk_name in either_one:
                        item = found_checks.get(chk_name)
                        if item is not None and valid_finding(item):
                            has_either = True
                            break

                    if has_required and has_either:
                        checks["scan_findings_cover_required"] = True

    # 2) summary.md validations
    if os.path.isfile(summary_path):
        checks["has_summary_md"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_content = f.read()
        except Exception:
            summary_content = ""

        # Must contain the exact phrase on one line
        if any(line.strip() == "Overall Classification: DANGEROUS" for line in summary_content.splitlines()):
            checks["summary_has_overall_classification"] = True

        # Must mention by name at least three of these checks
        check_names = [
            "PAYLOAD_B64_MALICIOUS",
            "BEHAVIOR_EXFILTRATION",
            "DEP_KNOWN_MALICIOUS",
            "DEP_INSTALL_SCRIPT",
            "STRUCT_UNSAFE_INSTRUCTION",
            "STRUCT_HIDDEN_FILE",
            "STRUCT_BINARY",
        ]
        mentions = set()
        for name in check_names:
            if name in summary_content:
                mentions.add(name)
        if len(mentions) >= 3:
            checks["summary_mentions_checks"] = True

        # Must include a section with the word "Recommendations" or "Remediation" and at least two bullet items
        has_section_word = ("Recommendations" in summary_content) or ("Remediation" in summary_content)
        bullet_count = 0
        for line in summary_content.splitlines():
            s = line.lstrip()
            if s.startswith("- ") or s.startswith("* "):
                bullet_count += 1
        if has_section_word and bullet_count >= 2:
            checks["summary_has_recommendations_section"] = True

    # 3) attestation.json validations
    att_data = None
    if os.path.isfile(attestation_path):
        checks["has_attestation_json"] = True
        att_data, err = load_json(attestation_path)
        if isinstance(att_data, dict):
            checks["attestation_json_valid"] = True
            # Required keys and constraints
            agent_id = att_data.get("agent_id")
            public_key = att_data.get("public_key")
            att_class = att_data.get("classification")
            scan_sha = att_data.get("scan_sha256")
            signature = att_data.get("signature")
            signed_at = att_data.get("signed_at")

            hex32_re = re.compile(r"^[0-9a-f]{32}$")
            hex64_re = re.compile(r"^[0-9a-f]{64}$")
            b64_like_re = re.compile(r"^[A-Za-z0-9+/=]{20,}$")

            keys_ok = True
            if not (isinstance(agent_id, str) and hex32_re.match(agent_id)):
                keys_ok = False
            if not (isinstance(public_key, str) and public_key.strip() != ""):
                keys_ok = False
            if not (isinstance(att_class, str) and att_class == "DANGEROUS"):
                keys_ok = False
            if not (isinstance(scan_sha, str) and hex64_re.match(scan_sha)):
                keys_ok = False
            if not (isinstance(signature, str) and b64_like_re.match(signature)):
                keys_ok = False
            if not (isinstance(signed_at, str) and signed_at.strip() != ""):
                keys_ok = False
            if keys_ok:
                checks["attestation_required_keys_valid"] = True

            # Match classification to scan.json classification
            if checks["scan_json_valid"]:
                scan_class = None
                try:
                    scan_class = scan_data.get("classification")
                except Exception:
                    scan_class = None
                if scan_class == att_class == "DANGEROUS":
                    checks["attestation_classification_matches_scan"] = True

            # SHA256 must match actual scan.json
            actual_sha = compute_sha256_hex(scan_path) if checks["has_scan_json"] else None
            if isinstance(scan_sha, str) and actual_sha is not None and scan_sha == actual_sha:
                checks["attestation_sha_matches_scan"] = True

    # Compute reward
    # If output directory is missing or contains none of the required artifacts, reward = 0.0
    any_artifact = any(os.path.isfile(p) for p in [scan_path, summary_path, attestation_path])
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    if not any_artifact:
        reward = 0.0
    else:
        # Fractional reward based on the proportion of checks passed
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Clamp reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()