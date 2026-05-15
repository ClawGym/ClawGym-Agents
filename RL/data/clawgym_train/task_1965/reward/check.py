import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def normalize_header_cells(line):
    # Split a markdown table header line into trimmed cells, dropping empties
    if "|" not in line:
        return []
    parts = [p.strip() for p in line.strip().split("|")]
    # remove leading/trailing empty elements caused by leading/trailing pipes
    cells = [p for p in parts if p != ""]
    return cells

def contains_header_with_exact_columns(text, required_columns):
    if text is None:
        return False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = normalize_header_cells(line)
        if cells == required_columns:
            return True
    return False

def find_line_starting_with(text, prefix):
    if text is None:
        return False
    for raw_line in text.splitlines():
        if raw_line.strip().startswith(prefix):
            return True
    return False

def has_heading_with_word(text, word):
    if text is None:
        return False
    for raw_line in text.splitlines():
        s = raw_line.strip()
        if s.startswith("#") and re.search(rf"\b{re.escape(word)}\b", s, flags=re.IGNORECASE):
            return True
    return False

def triage_title_near_top(text, max_nonempty_lines=10):
    if text is None:
        return False
    nonempty = [ln for ln in text.splitlines() if ln.strip() != ""]
    top = nonempty[:max_nonempty_lines]
    joined = "\n".join(top)
    return re.search(r"\bTRIAGE REPORT\b", joined, flags=re.IGNORECASE) is not None

def guide_checks(content):
    res = {
        "guide_exists": False,
        "guide_seed_25word": False,
        "guide_hardware_wallet": False,
        "guide_air_gapped": False,
        "guide_backup_321": False,
        "guide_verify_address": False,
    }
    if content is None:
        return res
    res["guide_exists"] = True
    low = content.lower()
    # seed phrase and 25 word
    if "seed phrase" in low and ("25-word" in low or "25 word" in low):
        res["guide_seed_25word"] = True
    # hardware wallet
    if "hardware wallet" in low:
        res["guide_hardware_wallet"] = True
    # air-gapped (accept hyphen or space)
    if "air-gapped" in low or "air gapped" in low:
        res["guide_air_gapped"] = True
    # 3-2-1 or 3 copies
    if "3-2-1" in low or "3 copies" in low:
        res["guide_backup_321"] = True
    # verify and address must both appear
    if "verify" in low and "address" in low:
        res["guide_verify_address"] = True
    return res

def reviews_checks(content):
    res = {
        "reviews_exists": False,
        "reviews_has_pain_header": False,
        "reviews_has_pain_table_header": False,
        "reviews_has_selection_spec_list": False,
        "reviews_has_must_have": False,
        "reviews_has_avoid_list": False,
        "reviews_has_validation_plan": False,
        "reviews_mentions_rijoy": False,
    }
    if content is None:
        return res
    res["reviews_exists"] = True
    low = content.lower()
    if "pain summary table" in low:
        res["reviews_has_pain_header"] = True
    required_columns = [
        "Pain Label",
        "Typical Review Quote",
        "Type",
        "Root-Cause Hypothesis",
        "Selection / Improvement Action",
        "Validation Method",
        "Priority Score",
    ]
    if contains_header_with_exact_columns(content, required_columns):
        res["reviews_has_pain_table_header"] = True
    if re.search(r"\bSelection Spec List\b", content, flags=re.IGNORECASE):
        res["reviews_has_selection_spec_list"] = True
    if re.search(r"\bMust-have\b", content, flags=re.IGNORECASE):
        res["reviews_has_must_have"] = True
    if re.search(r"\bAvoid list\b", content, flags=re.IGNORECASE):
        res["reviews_has_avoid_list"] = True
    if re.search(r"\bValidation Plan\b", content, flags=re.IGNORECASE):
        res["reviews_has_validation_plan"] = True
    if re.search(r"\bRijoy\b", content, flags=re.IGNORECASE):
        res["reviews_mentions_rijoy"] = True
    return res

def sources_registry_checks(content):
    res = {
        "sources_registry_exists": False,
        "sources_registry_header_ok": False,
    }
    if content is None:
        return res
    res["sources_registry_exists"] = True
    required_columns = [
        "source_id",
        "title",
        "issuer",
        "date",
        "topic",
        "tier",
        "url",
        "status",
        "notes",
    ]
    if contains_header_with_exact_columns(content, required_columns):
        res["sources_registry_header_ok"] = True
    return res

def claim_tracker_checks(content):
    res = {
        "claim_tracker_exists": False,
        "claim_tracker_header_ok": False,
    }
    if content is None:
        return res
    res["claim_tracker_exists"] = True
    required_columns = [
        "claim_id",
        "claim",
        "class",
        "source_ids",
        "date_range",
        "confidence",
        "status",
        "notes",
    ]
    if contains_header_with_exact_columns(content, required_columns):
        res["claim_tracker_header_ok"] = True
    return res

def report_checks(content):
    res = {
        "report_exists": False,
        "report_has_cutoff_date": False,
        "report_has_limits_heading": False,
    }
    if content is None:
        return res
    res["report_exists"] = True
    # Line starting with "Report cutoff:" and containing a date pattern YYYY-MM-DD
    if re.search(r"(?m)^\s*Report cutoff:\s*.*\d{4}-\d{2}-\d{2}.*$", content):
        res["report_has_cutoff_date"] = True
    if has_heading_with_word(content, "Limits"):
        res["report_has_limits_heading"] = True
    return res

def triage_checks(content):
    res = {
        "triage_exists": False,
        "triage_has_title_near_top": False,
        "triage_has_symptom_line": False,
        "triage_has_evidence_line": False,
        "triage_has_cause_line": False,
        "triage_has_fixplan_line": False,
        "triage_has_verification_line": False,
        "triage_has_rollback_line": False,
    }
    if content is None:
        return res
    res["triage_exists"] = True
    if triage_title_near_top(content):
        res["triage_has_title_near_top"] = True
    if find_line_starting_with(content, "- Symptom:"):
        res["triage_has_symptom_line"] = True
    # Evidence line: begin with "- Evidence"
    if find_line_starting_with(content, "- Evidence"):
        res["triage_has_evidence_line"] = True
    if find_line_starting_with(content, "- Most likely cause:"):
        res["triage_has_cause_line"] = True
    if find_line_starting_with(content, "- Fix plan"):
        res["triage_has_fixplan_line"] = True
    if find_line_starting_with(content, "- Verification:"):
        res["triage_has_verification_line"] = True
    if find_line_starting_with(content, "- Rollback:"):
        res["triage_has_rollback_line"] = True
    return res

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir is not used but computed per requirements
    reward_dir = os.path.join(workspace_root, "reward")

    # Load contents
    guide_path = os.path.join(output_dir, "guides", "monero_wallet_security.md")
    reviews_path = os.path.join(output_dir, "reviews", "pain_analysis.md")
    sources_registry_path = os.path.join(output_dir, "monero_security_research", "sources", "source_registry.md")
    claim_tracker_path = os.path.join(output_dir, "monero_security_research", "claims", "claim_tracker.md")
    report_path = os.path.join(output_dir, "monero_security_research", "deliverables", "report.md")
    triage_path = os.path.join(output_dir, "triage", "TRIAGE_REPORT.md")

    guide_content = read_text(guide_path)
    reviews_content = read_text(reviews_path)
    sources_content = read_text(sources_registry_path)
    claims_content = read_text(claim_tracker_path)
    report_content = read_text(report_path)
    triage_content = read_text(triage_path)

    checks = {}
    # Initialize all to False; then update
    gchk = guide_checks(guide_content)
    rchk = reviews_checks(reviews_content)
    srchk = sources_registry_checks(sources_content)
    cchk = claim_tracker_checks(claims_content)
    rpchk = report_checks(report_content)
    tchk = triage_checks(triage_content)

    checks.update(gchk)
    checks.update(rchk)
    checks.update(srchk)
    checks.update(cchk)
    checks.update(rpchk)
    checks.update(tchk)

    # Compute reward as fraction of passed checks, but ensure 0.0 if no artifact-dependent check passes
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if passed > 0 else 0.0

    # Print JSON with "reward" first, then checks
    out = {"reward": round(reward, 6)}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()