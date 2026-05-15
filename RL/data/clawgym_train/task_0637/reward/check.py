import os
import sys
import json
import hashlib
import re

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def file_size(path):
    return os.path.getsize(path)

def load_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Required inputs and outputs
    required_inputs = [
        "input/contract.txt",
        "input/ledger.csv",
        "input/transfers.json",
        "input/policy.md",
        "input/model_outputs.jsonl",
        "input/env.txt",
    ]
    required_outputs = [
        "output/audit_report.md",
        "output/evidence_log.jsonl",
        "output/proof_of_audit.json",
    ]

    checks = {
        "has_audit_report": False,
        "has_evidence_log": False,
        "has_proof_of_audit": False,
        "report_headings_order": False,
        "report_mentions_all_domains": False,
        "report_contains_proof_root": False,
        "evidence_log_valid": False,
        "proof_of_audit_valid": False,
        "secrets_redacted": False,
        "report_has_redaction_marker": False,
    }

    # Verify output files exist
    report_path = os.path.join(output_dir, "audit_report.md")
    evidence_log_path = os.path.join(output_dir, "evidence_log.jsonl")
    proof_path = os.path.join(output_dir, "proof_of_audit.json")

    if os.path.isfile(report_path):
        checks["has_audit_report"] = True
    if os.path.isfile(evidence_log_path):
        checks["has_evidence_log"] = True
    if os.path.isfile(proof_path):
        checks["has_proof_of_audit"] = True

    # Report structure and content checks
    if checks["has_audit_report"]:
        try:
            report_text = load_text(report_path)
            # Headings order: top-level headings (# ...)
            required_headings = [
                "Executive Summary",
                "Discrepancy Findings",
                "Technical Assessment",
                "Financial Reconciliation",
                "Legal & Compliance Review",
                "Ethical Risk Scan",
                "Recommendations",
                "Standards Mapping",
            ]
            headings = []
            for line in report_text.splitlines():
                if line.startswith("# "):
                    headings.append(line[2:].strip())

            if headings == required_headings:
                checks["report_headings_order"] = True

            # Mentions all four domains at least once
            lower = report_text.lower()
            domain_ok = all(
                re.search(r"\b" + w + r"\b", lower) is not None
                for w in ["financial", "legal", "technical", "ethical"]
            )
            if domain_ok:
                checks["report_mentions_all_domains"] = True

            # Contains "Proof-of-Audit Root:" followed by 64 lowercase hex
            if re.search(r"Proof-of-Audit Root:\s*[0-9a-f]{64}", report_text) is not None:
                checks["report_contains_proof_root"] = True

            # Contains at least one [REDACTED:*] marker
            if "[REDACTED:" in report_text:
                checks["report_has_redaction_marker"] = True
        except Exception:
            pass

    # Evidence log validation
    # Compute expected digests and sizes for required inputs
    expected_info = {}
    all_inputs_exist = True
    for rel in required_inputs:
        abs_path = os.path.join(workspace_root, rel)
        if not os.path.isfile(abs_path):
            all_inputs_exist = False
            break
        try:
            expected_info[rel] = {
                "sha256": sha256_file(abs_path),
                "size_bytes": file_size(abs_path),
            }
        except Exception:
            all_inputs_exist = False
            break

    if checks["has_evidence_log"] and all_inputs_exist:
        try:
            lines = []
            with open(evidence_log_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip("\r\n")
                    if line.strip() == "":
                        continue
                    lines.append(line)
            # Must be exactly one line per required input file
            if len(lines) == len(required_inputs):
                seen_paths = set()
                valid = True
                for line in lines:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        valid = False
                        break
                    path = obj.get("path")
                    sha = obj.get("sha256")
                    size = obj.get("size_bytes")
                    if (
                        not isinstance(path, str)
                        or path not in expected_info
                        or path in seen_paths
                    ):
                        valid = False
                        break
                    seen_paths.add(path)
                    exp = expected_info[path]
                    if sha != exp["sha256"] or size != exp["size_bytes"]:
                        valid = False
                        break
                if valid and seen_paths == set(required_inputs):
                    checks["evidence_log_valid"] = True
        except Exception:
            pass

    # Proof of audit validation
    if checks["has_proof_of_audit"] and all_inputs_exist:
        try:
            with open(proof_path, "r", encoding="utf-8", errors="replace") as f:
                proof = json.load(f)
            algo_ok = proof.get("algorithm") == "SHA256"
            files_list = proof.get("files")
            per_file = proof.get("per_file_digests")
            audit_root = proof.get("audit_root")
            signature = proof.get("signature")

            files_ok = files_list == required_inputs
            per_file_ok = isinstance(per_file, dict) and set(per_file.keys()) == set(required_inputs)

            digests_ok = True
            if per_file_ok:
                for rel in required_inputs:
                    if per_file.get(rel) != expected_info[rel]["sha256"]:
                        digests_ok = False
                        break

            # Compute audit root: SHA256 of concatenated digests in order (ASCII)
            root_ok = False
            sig_ok = False
            if files_ok and digests_ok:
                concat = "".join([per_file[rel] for rel in required_inputs])
                concat_bytes = concat.encode("ascii")
                computed_root = hashlib.sha256(concat_bytes).hexdigest()
                root_ok = (audit_root == computed_root)
                sig_ok = (signature == f"POA-{computed_root}")

            if algo_ok and files_ok and per_file_ok and digests_ok and root_ok and sig_ok:
                checks["proof_of_audit_valid"] = True
        except Exception:
            pass

    # Secret redaction check: ensure no exact lines from env.txt appear verbatim in any outputs
    # Applies only if outputs exist and env.txt exists
    env_path = os.path.join(workspace_root, "input", "env.txt")
    if os.path.isfile(env_path) and checks["has_audit_report"] and checks["has_evidence_log"] and checks["has_proof_of_audit"]:
        try:
            outputs_text = ""
            try:
                outputs_text += load_text(report_path)
            except Exception:
                pass
            try:
                outputs_text += "\n" + load_text(evidence_log_path)
            except Exception:
                pass
            try:
                outputs_text += "\n" + load_text(proof_path)
            except Exception:
                pass

            leaked = False
            with open(env_path, "r", encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    line = raw_line.rstrip("\r\n")
                    if line == "":
                        continue
                    if line in outputs_text:
                        leaked = True
                        break
            checks["secrets_redacted"] = (not leaked)
        except Exception:
            # On error, keep False
            pass

    # Compute reward: fraction of passed checks
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = (passed / total) if total > 0 else 0.0

    # Baseline: if output dir missing or empty, ensure reward 0.0
    if not os.path.isdir(output_dir) or len(os.listdir(output_dir)) == 0:
        reward = 0.0

    # Print final JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()