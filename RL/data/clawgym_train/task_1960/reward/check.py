import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def lines_after_header(lines, start_idx):
    # returns subsequent lines after start_idx until next header (### or all caps header) or EOF
    content_lines = []
    i = start_idx + 1
    while i < len(lines):
        line = lines[i]
        # Next section if markdown header level 2/3 or uppercase header line or empty line followed by next header
        if line.strip().startswith("## ") or line.strip().startswith("### "):
            break
        # For uppercase headers without markdown hashes, detect by exact known section names externally
        content_lines.append(line)
        i += 1
    return content_lines

def find_section_indices(lines, header_text):
    # returns index of header line equal to header_text, or -1
    for i, line in enumerate(lines):
        if line.strip() == header_text:
            return i
    return -1

def section_block(lines, header_text, next_headers):
    # returns lines in section after header_text until any next_headers is encountered
    start = find_section_indices(lines, header_text)
    if start == -1:
        return start, []
    # find next header index
    end = len(lines)
    for nh in next_headers:
        idx = find_section_indices(lines, nh)
        if idx != -1 and idx > start and idx < end:
            end = idx
    return start, lines[start+1:end]

def has_nonempty_line(lines):
    return any(l.strip() != "" for l in lines)

def get_last_nonempty_line(text):
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # 1) payments/integration_guide.md checks
    payments_path = os.path.join(output_dir, "payments", "integration_guide.md")
    payments_txt = read_text(payments_path)
    payments_low = payments_txt.lower()
    checks["payments_file_exists"] = os.path.isfile(payments_path)

    # Stripe checks
    checks["stripe_paymentintents_present"] = checks["payments_file_exists"] and ("paymentintents.create" in payments_txt)
    checks["stripe_apm_present"] = checks["payments_file_exists"] and ("automatic_payment_methods" in payments_txt)
    checks["stripe_idempotency_present"] = checks["payments_file_exists"] and (("idempotency_key" in payments_low) or ("idempotency" in payments_low))
    stripe_webhook = checks["payments_file_exists"] and ("stripe-signature" in payments_txt) and ("constructEvent" in payments_txt or "constructevent" in payments_low) and ("raw" in payments_low)
    checks["stripe_webhook_verification_present"] = stripe_webhook

    # PayPal checks
    checks["paypal_orders_and_capture_present"] = checks["payments_file_exists"] and ("v2/checkout/orders" in payments_low and "capture" in payments_low)
    checks["paypal_auth_mentioned"] = checks["payments_file_exists"] and (("bearer" in payments_low) or ("oauth2" in payments_low))
    checks["paypal_pitfalls_mentioned"] = checks["payments_file_exists"] and (("expire" in payments_low) or ("webhook" in payments_low) or ("capture" in payments_low))

    # Razorpay checks
    checks["razorpay_hmac_sha256_present"] = checks["payments_file_exists"] and ("createHmac" in payments_txt and "sha256" in payments_low)
    checks["razorpay_pipe_format_present"] = checks["payments_file_exists"] and ("order_id|payment_id" in payments_txt)
    checks["razorpay_paise_mentioned"] = checks["payments_file_exists"] and ("paise" in payments_low)
    # webhook secret distinct from key_secret
    rz_webhook_secret_distinct = False
    if checks["payments_file_exists"]:
        if ("webhook" in payments_low and "secret" in payments_low and "key_secret" in payments_low) and (("separate" in payments_low) or ("distinct" in payments_low) or ("different" in payments_low) or ("webhook_secret" in payments_low)):
            rz_webhook_secret_distinct = True
    checks["razorpay_webhook_secret_distinct"] = rz_webhook_secret_distinct

    # Security best practices mentions
    sec_env = "environment variables" in payments_low
    sec_https = "https" in payments_low  # Accept uppercase/lowercase; we specifically want HTTPS mention
    sec_no_raw = ("never store" in payments_low) or ("no raw card" in payments_low)
    sec_amount_validation = "amount validation" in payments_low
    checks["security_best_practices_mentioned"] = checks["payments_file_exists"] and sec_env and sec_https and sec_no_raw and sec_amount_validation

    # 2) pyx_scan/report.md checks
    pyx_path = os.path.join(output_dir, "pyx_scan", "report.md")
    pyx_txt = read_text(pyx_path)
    pyx_lines = pyx_txt.splitlines()
    pyx_low = pyx_txt.lower()
    checks["pyx_scan_file_exists"] = os.path.isfile(pyx_path)
    # Title line
    title_ok = False
    if checks["pyx_scan_file_exists"]:
        for line in pyx_lines:
            if line.startswith("## Safety Scan: fysoul17/pyx-scan"):
                title_ok = True
                break
    checks["pyx_title_ok"] = title_ok
    # Verdict line
    verdict_ok = False
    if checks["pyx_scan_file_exists"]:
        for line in pyx_lines:
            if line.startswith("Verdict:"):
                val = line[len("Verdict:"):].strip().split()[0] if len(line) > len("Verdict:") else ""
                if val in {"SAFE", "OUTDATED", "CAUTION", "FAILED", "UNSCANNED"}:
                    verdict_ok = True
                break
    checks["pyx_verdict_line_ok"] = verdict_ok
    checks["pyx_trust_risk_ok"] = checks["pyx_scan_file_exists"] and ("Trust Score:" in pyx_txt and "Risk Score:" in pyx_txt)
    checks["pyx_extra_metrics_present"] = checks["pyx_scan_file_exists"] and (("Confidence:" in pyx_txt) or ("Intent:" in pyx_txt) or ("Status:" in pyx_txt))
    # Summary section has at least one non-empty line after header
    summary_ok = False
    if checks["pyx_scan_file_exists"]:
        for idx, line in enumerate(pyx_lines):
            if line.strip() == "### Summary":
                # find next non-empty line
                j = idx + 1
                while j < len(pyx_lines) and pyx_lines[j].strip() == "":
                    j += 1
                if j < len(pyx_lines) and not pyx_lines[j].strip().startswith("###"):
                    if pyx_lines[j].strip() != "":
                        summary_ok = True
                break
    checks["pyx_summary_section_present"] = summary_ok
    # About section: Purpose line and at least one bullet under Capabilities or Permissions Required
    about_purpose_ok = False
    about_bullets_ok = False
    if checks["pyx_scan_file_exists"]:
        # gather About section lines until next ### header
        about_idx = -1
        for i, l in enumerate(pyx_lines):
            if l.strip() == "### About":
                about_idx = i
                break
        if about_idx != -1:
            # collect until next ### or EOF
            j = about_idx + 1
            about_lines = []
            while j < len(pyx_lines):
                if pyx_lines[j].strip().startswith("### "):
                    break
                about_lines.append(pyx_lines[j])
                j += 1
            # Purpose:
            for l in about_lines:
                if l.strip().startswith("Purpose:"):
                    about_purpose_ok = True
                    break
            # Bullets under Capabilities or Permissions Required
            # Find indices of Capabilities: and Permissions Required:
            cap_idx = None
            perm_idx = None
            for k, l in enumerate(about_lines):
                if l.strip().startswith("Capabilities:"):
                    cap_idx = k
                if l.strip().startswith("Permissions Required:"):
                    perm_idx = k
            def bullets_after(start_idx):
                if start_idx is None:
                    return False
                m = start_idx + 1
                seen_bullet = False
                while m < len(about_lines):
                    s = about_lines[m].strip()
                    if s.startswith("Capabilities:") or s.startswith("Permissions Required:") or s.startswith("### "):
                        break
                    if s.startswith("- "):
                        seen_bullet = True
                        break
                    m += 1
                return seen_bullet
            about_bullets_ok = bullets_after(cap_idx) or bullets_after(perm_idx)
    checks["pyx_about_purpose_present"] = about_purpose_ok
    checks["pyx_about_bullets_present"] = about_bullets_ok
    checks["pyx_link_present"] = checks["pyx_scan_file_exists"] and ("scanner.pyxmate.com" in pyx_txt)

    # 3) onlyfans/strategy.md checks
    onlyfans_path = os.path.join(output_dir, "onlyfans", "strategy.md")
    of_txt = read_text(onlyfans_path)
    of_lines = of_txt.splitlines()
    checks["onlyfans_strategy_exists"] = os.path.isfile(onlyfans_path)
    # Required headers list in exact spelling
    required_headers = [
        "RELATIONSHIP ASSESSMENT",
        "SUBSCRIPTION LOGIC",
        "MAIN ISSUES",
        "TIERING PLAN",
        "CONTENT SCARCITY LOGIC",
        "RECOMMENDED NEXT STEP",
    ]
    headers_present = False
    if checks["onlyfans_strategy_exists"]:
        headers_present = all(any(line.strip() == h for line in of_lines) for h in required_headers)
    checks["onlyfans_has_required_headers"] = headers_present
    # Creator Mode and Primary Goal lines
    checks["onlyfans_creator_mode_line"] = checks["onlyfans_strategy_exists"] and any(l.strip().startswith("Creator Mode:") for l in of_lines)
    checks["onlyfans_primary_goal_line"] = checks["onlyfans_strategy_exists"] and any(l.strip().startswith("Primary Goal:") for l in of_lines)
    # Each other section has at least one non-empty line
    sections_nonempty = False
    if checks["onlyfans_strategy_exists"] and headers_present:
        # For each section beyond RELATIONSHIP ASSESSMENT, ensure non-empty content beneath
        success = True
        for idx, h in enumerate(required_headers):
            start_idx = None
            for i, l in enumerate(of_lines):
                if l.strip() == h:
                    start_idx = i
                    break
            if start_idx is None:
                success = False
                break
            # Determine end by next header
            end_idx = len(of_lines)
            if idx < len(required_headers) - 1:
                # find next header line
                nh = required_headers[idx + 1]
                for j in range(start_idx + 1, len(of_lines)):
                    if of_lines[j].strip() == nh:
                        end_idx = j
                        break
            if h == "RELATIONSHIP ASSESSMENT":
                # This is checked separately for Creator Mode and Primary Goal
                continue
            # Collect non-empty lines within
            content = [l for l in of_lines[start_idx+1:end_idx] if l.strip() != ""]
            if len(content) == 0:
                success = False
                break
        sections_nonempty = success
    checks["onlyfans_sections_nonempty"] = sections_nonempty

    # 4) debug/debug_escalation.md checks
    debug_path = os.path.join(output_dir, "debug", "debug_escalation.md")
    dbg_txt = read_text(debug_path)
    dbg_lines = dbg_txt.splitlines()
    checks["debug_escalation_exists"] = os.path.isfile(debug_path)
    expected_first_line = "[Auto-Select: Alibaba L2 | Reason: Stuck in a loop | Next: Jobs/Musk]"
    checks["debug_first_line_tag_ok"] = checks["debug_escalation_exists"] and (len(dbg_lines) > 0 and dbg_lines[0].strip() == expected_first_line)
    checks["debug_has_checklist_header"] = checks["debug_escalation_exists"] and any("7-Item Checklist" in l for l in dbg_lines)
    # checklist lines
    checklist_labels = [
        "Read failure signal",
        "Active search",
        "Read original materials",
        "Validate assumptions",
        "Invert assumptions",
        "Minimal isolation",
        "Change direction",
    ]
    checklist_ok = False
    if checks["debug_escalation_exists"]:
        checklist_lines = [l.strip() for l in dbg_lines if l.strip().startswith("- [x] ")]
        # exactly seven
        if len(checklist_lines) == 7:
            labels = [l[len("- [x] "):] for l in checklist_lines]
            checklist_ok = labels == checklist_labels
        else:
            checklist_ok = False
    checks["debug_exact_seven_checkboxes_in_order"] = checklist_ok

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Ensure exactly 0.0 if no outputs present at all
    if not any([
        checks.get("payments_file_exists", False),
        checks.get("pyx_scan_file_exists", False),
        checks.get("onlyfans_strategy_exists", False),
        checks.get("debug_escalation_exists", False)
    ]):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)

    print(json.dumps(result))

if __name__ == "__main__":
    main()