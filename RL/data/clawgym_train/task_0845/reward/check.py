import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")
    vault_root = os.path.join(output_dir, "vault")

    # Helper to read text safely
    def read_text(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    # Parse YAML frontmatter at start of file (first non-empty line must be ---)
    def parse_frontmatter(text):
        if text is None:
            return None, None
        lines = text.splitlines()
        i = 0
        # skip leading empty lines
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        if i >= len(lines) or lines[i].strip() != "---":
            return None, text
        i += 1
        fm_lines = []
        while i < len(lines) and lines[i].strip() != "---":
            fm_lines.append(lines[i])
            i += 1
        if i >= len(lines) or lines[i].strip() != "---":
            # no closing fence
            return None, text
        # body starts after closing ---
        body = "\n".join(lines[i+1:]) if i+1 < len(lines) else ""
        # Build a simple key map
        keys = {}
        for ln in fm_lines:
            # match key: value (allow empty value)
            m = re.match(r"^\s*([A-Za-z0-9_\-]+)\s*:\s*(.*)$", ln)
            if m:
                k = m.group(1).strip().lower()
                keys[k] = m.group(2).strip()
        return keys, body

    checks = {
        # Orchestration checks
        "status_has_links_all": False,
        "tasks_has_security_task": False,
        "tasks_has_research_task": False,
        "decisions_contains_keywords": False,
        # Research brief checks
        "brief_exists": False,
        "brief_frontmatter_has_required_keys": False,
        "brief_has_tldr_section": False,
        "brief_has_highlights_section": False,
        "brief_mentions_all_categories": False,
        # Therapy report checks
        "therapy_exists": False,
        "therapy_frontmatter_has_required_keys": False,
        "therapy_has_main_headers": False,
        "therapy_diagnosis_has_canonical_names": False,
        "therapy_has_evidence_item": False,
        # Security dashboard checks
        "security_exists": False,
        "security_frontmatter_has_required_keys": False,
        "security_mentions_counts": False,
        "security_mentions_all_tools": False,
    }

    # 1) Orchestration files
    status_path = os.path.join(vault_root, "_context", "status.md")
    status_text = read_text(status_path)
    if status_text is not None:
        # Require wikilinks to the three deliverables (accept with or without .md, allow any trailing)
        need_links = [
            "[[work/research/paper-brief-common-cold-vitamin-c",
            "[[work/output/therapy/therapy-session-report",
            "[[work/output/security/security-scan-summary",
        ]
        has_all = all(link in status_text for link in need_links)
        checks["status_has_links_all"] = has_all

    tasks_path = os.path.join(vault_root, "_context", "tasks.md")
    tasks_text = read_text(tasks_path)
    if tasks_text is not None:
        lines = tasks_text.splitlines()
        sec_task = any(("- [ ]" in ln) and ("#security" in ln) for ln in lines)
        res_task = any(("- [ ]" in ln) and ("#research" in ln) for ln in lines)
        checks["tasks_has_security_task"] = sec_task
        checks["tasks_has_research_task"] = res_task

    decisions_path = os.path.join(vault_root, "_context", "decisions.md")
    decisions_text = read_text(decisions_path)
    if decisions_text is not None:
        low = decisions_text.lower()
        # Must mention obsidian and both highlight and security
        checks["decisions_contains_keywords"] = ("obsidian" in low and "highlight" in low and "security" in low)

    # 2) Research brief
    brief_path = os.path.join(vault_root, "work", "research", "paper-brief-common-cold-vitamin-c.md")
    brief_text = read_text(brief_path)
    if brief_text is not None:
        checks["brief_exists"] = True
        fm, body = parse_frontmatter(brief_text)
        if fm is not None:
            req_keys = ["title", "type", "status", "created", "updated", "tags"]
            if all(k in fm for k in req_keys):
                checks["brief_frontmatter_has_required_keys"] = True
        # body checks
        body_text = body if body is not None else ""
        if re.search(r"\bTLDR\b", body_text, flags=re.IGNORECASE):
            checks["brief_has_tldr_section"] = True
        if re.search(r"highlights\s+by\s+category", body_text, flags=re.IGNORECASE):
            checks["brief_has_highlights_section"] = True
        cats = ["goal", "motivation", "method", "contribution", "result"]
        low_body = body_text.lower()
        checks["brief_mentions_all_categories"] = all(cat in low_body for cat in cats)

    # 3) Therapy session report
    therapy_path = os.path.join(vault_root, "work", "output", "therapy", "therapy-session-report.md")
    therapy_text = read_text(therapy_path)
    if therapy_text is not None:
        checks["therapy_exists"] = True
        tfm, tbody = parse_frontmatter(therapy_text)
        if tfm is not None:
            req_keys = ["title", "type", "status", "created", "updated", "tags"]
            if all(k in tfm for k in req_keys):
                checks["therapy_frontmatter_has_required_keys"] = True
        # Must contain exact header and subsections
        content_after = tbody if tbody is not None else ""
        has_main = ("## Therapy Session Report" in content_after
                    and "### The Honest Version" in content_after
                    and "### Going Forward" in content_after)
        checks["therapy_has_main_headers"] = has_main

        # Diagnosis section check for canonical names within the Diagnosis section
        diag_has_names = False
        evidence_item = False
        # Extract Diagnosis section
        diag_pattern = re.compile(r"###\s+Diagnosis\b", flags=re.IGNORECASE)
        m = diag_pattern.search(content_after)
        if m:
            start = m.end()
            # Find next "### " header
            nxt = re.search(r"\n###\s+", content_after[start:], flags=re.IGNORECASE)
            end = start + nxt.start() if nxt else len(content_after)
            diag_block = content_after[start:end]
            # Look for canonical names
            if ("Sycophancy" in diag_block) and ("Pressure Hallucination" in diag_block):
                diag_has_names = True
        else:
            diag_block = content_after  # fallback to whole content if not found

        # Evidence line pattern: "- Message N (Role): ..."
        if re.search(r"^\s*-\s*Message\s+\d+\s*\(", content_after, flags=re.MULTILINE):
            evidence_item = True

        checks["therapy_diagnosis_has_canonical_names"] = diag_has_names
        checks["therapy_has_evidence_item"] = evidence_item

    # 4) Security dashboard
    security_path = os.path.join(vault_root, "work", "output", "security", "security-scan-summary.md")
    sec_text = read_text(security_path)
    if sec_text is not None:
        checks["security_exists"] = True
        sfm, sbody = parse_frontmatter(sec_text)
        if sfm is not None:
            req_keys = ["title", "type", "status", "created", "updated", "tags"]
            if all(k in sfm for k in req_keys):
                checks["security_frontmatter_has_required_keys"] = True
        body_text = sbody if sbody is not None else ""
        # Counts labels must appear exactly
        counts_ok = ("Clean:" in body_text and "Review:" in body_text and "Critical:" in body_text)
        checks["security_mentions_counts"] = counts_ok
        # Tools presence (case-insensitive)
        tools = ["sentinel", "signet", "warden", "bastion", "sentry", "vault", "arbiter", "egress", "marshal", "ledger", "triage"]
        low = body_text.lower()
        checks["security_mentions_all_tools"] = all(t in low for t in tools)

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Explicitly model no-op baseline: if output/ is empty or missing, reward should be 0.0
    if not os.path.isdir(os.path.join(workspace_root, "output")):
        reward = 0.0
    # Ensure numeric bounds
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0
    # Print JSON result
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()