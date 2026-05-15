import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def find_mailbox_file(workspace_root):
    inbox_dir = os.path.join(workspace_root, "output", ".agent-mailbox", "inbox")
    if not os.path.isdir(inbox_dir):
        return None, None
    candidates = []
    for name in os.listdir(inbox_dir):
        full = os.path.join(inbox_dir, name)
        if os.path.isfile(full):
            rel = os.path.relpath(full, workspace_root)
            candidates.append((rel, full))
    # match pattern on relpath
    pat = re.compile(r"^output/\.agent-mailbox/inbox/\d{14}--[A-Za-z0-9._-]+--(info|warn|critical)--[A-Za-z0-9._-]+\.md$")
    for rel, full in candidates:
        if pat.match(rel):
            return rel, full
    return None, None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # guide.md presence and content checks
        "has_guide": False,
        "guide_contains_amsterdam": False,
        "guide_contains_30_percent_ruling": False,
        "guide_contains_hsm_or_phrase": False,
        "guide_contains_eur_5688": False,
        "guide_contains_eur_99": False,
        "guide_contains_neighborhood_term": False,
        "guide_has_security_addendum_section": False,
        "security_addendum_mentions_jwt": False,
        "security_addendum_mentions_oauth_or_pkce": False,
        "security_addendum_mentions_mfa_or_webauthn": False,
        "security_addendum_mentions_cookie_csrf_samesite": False,
        # brief.md checks
        "has_brief": False,
        "brief_has_target_prompt": False,
        "brief_has_mandatory_topics": False,
        "brief_has_questions_to_answer": False,
        "brief_has_key_entities": False,
        "brief_has_unique_value_angle": False,
        "brief_has_content_structure": False,
        # publishing checklist checks
        "has_publishing_checklist": False,
        "checklist_has_title_line": False,
        "checklist_has_meta_description": False,
        "checklist_has_schema_and_type": False,
        "checklist_has_timeline_2_4_weeks": False,
        # mailbox checks
        "has_mailbox_file": False,
        "mailbox_headers_present": False,
        "mailbox_priority_warn": False,
        "mailbox_from_content": False,
        "mailbox_body_mentions_required_terms": False,
    }

    # 1) guide.md checks
    guide_path = os.path.join(output_dir, "guide.md")
    guide_text = read_text(guide_path)
    if guide_text is not None:
        checks["has_guide"] = True
        gl = guide_text.lower()

        if "amsterdam" in gl:
            checks["guide_contains_amsterdam"] = True
        if "30% ruling" in gl:
            checks["guide_contains_30_percent_ruling"] = True
        if ("highly skilled migrant" in gl) or (re.search(r"\bhsm\b", gl) is not None):
            checks["guide_contains_hsm_or_phrase"] = True
        if "eur 5,688" in gl:
            checks["guide_contains_eur_5688"] = True
        if "eur 99" in gl:
            checks["guide_contains_eur_99"] = True

        neighborhood_terms = [
            "neighborhood", "de pijp", "oud-zuid", "oud-west", "noord", "oost", "zuidoost", "amstelveen"
        ]
        if any(term in gl for term in neighborhood_terms):
            checks["guide_contains_neighborhood_term"] = True

        # Security Addendum section extraction
        # Find "security addendum" substring and treat until end as section text
        sec_idx = gl.find("security addendum")
        if sec_idx != -1:
            checks["guide_has_security_addendum_section"] = True
            sec_text = guide_text[sec_idx:]  # original case for mixed-case checks
            sec_lower = sec_text.lower()
            if "jwt" in sec_lower:
                checks["security_addendum_mentions_jwt"] = True
            if ("oauth 2.0" in sec_lower) or ("pkce" in sec_lower):
                checks["security_addendum_mentions_oauth_or_pkce"] = True
            if ("mfa" in sec_lower) or ("webauthn" in sec_lower):
                checks["security_addendum_mentions_mfa_or_webauthn"] = True
            if ("httponly" in sec_lower) or ("samesite" in sec_lower) or ("csrf" in sec_lower):
                checks["security_addendum_mentions_cookie_csrf_samesite"] = True

    # 2) brief.md checks
    brief_path = os.path.join(output_dir, "brief.md")
    brief_text = read_text(brief_path)
    if brief_text is not None:
        checks["has_brief"] = True
        bl = brief_text.lower()
        if "target prompt" in bl:
            checks["brief_has_target_prompt"] = True
        if ("mandatory topics to cover" in bl) or ("mandatory topics" in bl):
            checks["brief_has_mandatory_topics"] = True
        if "questions to answer" in bl:
            checks["brief_has_questions_to_answer"] = True
        if ("key entities to include" in bl) or ("key entities" in bl):
            checks["brief_has_key_entities"] = True
        if "unique value angle" in bl:
            checks["brief_has_unique_value_angle"] = True
        if "content structure" in bl:
            checks["brief_has_content_structure"] = True

    # 3) publishing_checklist.md checks
    checklist_path = os.path.join(output_dir, "publishing_checklist.md")
    checklist_text = read_text(checklist_path)
    if checklist_text is not None:
        checks["has_publishing_checklist"] = True
        cl = checklist_text.lower()
        cls = lines(checklist_path) or []
        # Title line at start of a line
        for ln in cls:
            if ln.strip().lower().startswith("title:"):
                checks["checklist_has_title_line"] = True
                break
        # Meta description line
        if "meta description" in cl:
            checks["checklist_has_meta_description"] = True
        # schema mention and at least one of FAQ/HowTo/Article
        has_schema_word = ("schema" in cl)
        has_type = (re.search(r"\bfaq\b", cl) is not None) or (re.search(r"\bhowto\b", cl) is not None) or (re.search(r"\barticle\b", cl) is not None)
        if has_schema_word and has_type:
            checks["checklist_has_schema_and_type"] = True
        # timeline "2–4 weeks" or "2-4 weeks"
        if ("2–4 weeks" in checklist_text) or ("2-4 weeks" in checklist_text):
            checks["checklist_has_timeline_2_4_weeks"] = True

    # 4) mailbox file checks
    rel_mail, mail_full = find_mailbox_file(workspace_root)
    if rel_mail and mail_full:
        checks["has_mailbox_file"] = True
        mail_lines = lines(mail_full) or []
        # Expect first 5 lines as headers in specified order, then a blank line
        expected_order = ["Title:", "From:", "Created-At:", "Priority:", "Tags:"]
        headers_ok = False
        if len(mail_lines) >= 6:
            order_ok = True
            for i, prefix in enumerate(expected_order):
                if not mail_lines[i].startswith(prefix):
                    order_ok = False
                    break
            if order_ok and mail_lines[5].strip() == "":
                headers_ok = True
        checks["mailbox_headers_present"] = headers_ok

        # Priority warn and From content (check header lines if present; otherwise scan)
        priority_warn = False
        from_content = False
        # Search lines regardless of order to be robust, but prefer header locations
        for ln in mail_lines[:10]:
            if ln.lower().startswith("priority:"):
                if ln.split(":", 1)[1].strip().lower() == "warn":
                    priority_warn = True
            if ln.lower().startswith("from:"):
                if ln.split(":", 1)[1].strip().lower() == "content":
                    from_content = True
        checks["mailbox_priority_warn"] = priority_warn
        checks["mailbox_from_content"] = from_content

        # Body mentions Amsterdam and one of [30% ruling, HSM, Highly Skilled Migrant, tax]
        body_text = ""
        if "" in mail_lines:
            try:
                blank_idx = mail_lines.index("")
                body_text = "\n".join(mail_lines[blank_idx+1:])
            except ValueError:
                body_text = "\n".join(mail_lines)
        else:
            body_text = "\n".join(mail_lines)
        bl = body_text.lower()
        body_has_city = "amsterdam" in bl
        body_has_term = ("30% ruling" in bl) or (re.search(r"\bhsm\b", bl) is not None) or ("highly skilled migrant" in bl) or ("tax" in bl)
        checks["mailbox_body_mentions_required_terms"] = (body_has_city and body_has_term)

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    # No-op baseline: if output/ is missing or empty, ensure reward is 0.0
    # If none of the artifacts exist, passed should be 0 already due to default False.
    # Keep computed reward otherwise.

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()