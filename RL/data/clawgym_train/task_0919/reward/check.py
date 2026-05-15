import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

def parse_iso8601(ts: str) -> datetime:
    s = ts.strip()
    # Handle Zulu
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        # Fallback: try removing timezone colon if present
        try:
            # e.g., 2023-01-01T12:00:00+00:00 -> 2023-01-01T12:00:00+0000
            m = re.match(r"(.*)([+-]\d{2}):?(\d{2})$", s)
            if m:
                s2 = m.group(1) + m.group(2) + m.group(3)
                dt = datetime.fromisoformat(s2)
            else:
                dt = datetime.fromisoformat(s)
        except Exception:
            # Last resort: parse as naive UTC-like
            try:
                dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            except Exception:
                # Try date only
                try:
                    dt = datetime.strptime(s, "%Y-%m-%d")
                except Exception:
                    raise
    return dt

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_config_product(md_text):
    # Attempt to parse Product 1 fields
    lines = md_text.splitlines()
    name = None
    url = None
    problems = []
    keywords = []
    max_replies = None

    # Find "Product 1" block boundaries
    start_idx = None
    for i, line in enumerate(lines):
        if re.match(r"\s*###\s*Product\s*1", line):
            start_idx = i
            break
    end_idx = len(lines)
    if start_idx is not None:
        for j in range(start_idx + 1, len(lines)):
            if re.match(r"\s*###\s*Product\s*2", lines[j]) or re.match(r"\s*##\s*Target Platforms", lines[j]):
                end_idx = j
                break
    else:
        start_idx = 0

    prod_block = lines[start_idx:end_idx]

    # Parse name and URL and keywords line in block
    for i, line in enumerate(prod_block):
        m = re.match(r"\s*-\s*\*\*Name:\*\*\s*(.+)\s*$", line)
        if m and not name:
            name = m.group(1).strip()
            continue
        m = re.match(r"\s*-\s*\*\*URL:\*\*\s*(\S+)\s*$", line)
        if m and not url:
            url = m.group(1).strip()
            continue
        m = re.match(r"\s*-\s*\*\*Keywords:\*\*\s*(.+)\s*$", line)
        if m and not keywords:
            # comma-separated
            kw_line = m.group(1)
            kws = [k.strip() for k in kw_line.split(",") if k.strip()]
            keywords = kws

        # Problems it solves list
        if re.match(r"\s*-\s*\*\*Problems it solves:\*\*", line):
            # collect subsequent "- " indented lines
            k = i + 1
            while k < len(prod_block):
                l2 = prod_block[k]
                if re.match(r"\s*\-\s", l2) and not re.match(r"\s*-\s*\*\*", l2):
                    # could be another top-level bullet
                    break
                if re.match(r"\s{0,4}-\s+\[?.+?\]?\s*$", l2) or re.match(r"\s{2,}\-\s+.+", l2):
                    # capture content after dash
                    mm = re.match(r"\s*-+\s*(.+)\s*$", l2)
                    if mm:
                        problems.append(mm.group(1).strip("[] ").strip())
                elif re.match(r"\s{2,}\-\s+.+", l2):
                    mm = re.match(r"\s*-+\s*(.+)\s*$", l2)
                    if mm:
                        problems.append(mm.group(1).strip())
                else:
                    # Stop if blank line or not an indented bullet
                    if l2.strip() == "":
                        break
                k += 1

    # Engagement rules: Max replies per day
    for line in lines:
        m = re.match(r"\s*-\s*\*\*Max replies per day:\*\*\s*([0-9]+)", line)
        if m:
            try:
                max_replies = int(m.group(1))
            except Exception:
                pass

    return name, url, problems, keywords, max_replies

def classify_relevance(title, text, problems, keywords):
    content = (title or "") + "\n" + (text or "")
    lc = content.lower()
    hit_problems = []
    hit_keywords = []
    for p in problems:
        p_str = p.strip().lower()
        if p_str and p_str in lc:
            hit_problems.append(p)
    if hit_problems:
        return "high", hit_problems
    for k in keywords:
        k_str = k.strip().lower()
        if k_str and k_str in lc:
            hit_keywords.append(k)
    if hit_keywords:
        return "medium", hit_keywords
    return "low", []

def floor_hours(delta: timedelta) -> int:
    secs = int(delta.total_seconds())
    # floor division
    hrs = secs // 3600
    # ensure non-negative
    if hrs < 0:
        return 0
    return hrs

def extract_required_fields(obj):
    req = {"url", "platform", "product", "relevance", "recency_hours", "reply", "reason"}
    return set(obj.keys()) == req

def check_reply_structure(reply_text, product_name, product_url):
    # Must have lines starting with Acknowledge: and Help:, and a section "Options:" followed by at least two "- " bullets
    lines = reply_text.splitlines()
    has_ack = any(l.startswith("Acknowledge:") for l in lines)
    has_help = any(l.startswith("Help:") for l in lines)
    # find Options: line
    opts_idx = None
    for i, l in enumerate(lines):
        if l.strip() == "Options:":
            opts_idx = i
            break
    bullets = []
    if opts_idx is not None:
        for j in range(opts_idx + 1, len(lines)):
            l = lines[j]
            if l.strip().startswith("- "):
                bullets.append(l.strip())
            elif l.strip() == "":
                # allow blank lines between bullets
                continue
            else:
                # stop at non-bullet content
                break
    has_two_bullets = len(bullets) >= 2
    # one bullet must contain product name and URL
    product_bullet = any((product_name in b) and (product_url in b) for b in bullets)
    # at least one bullet that does not mention product
    non_product_bullet = any((product_name not in b) and (product_url not in b) for b in bullets)

    return has_ack and has_help and (opts_idx is not None) and has_two_bullets and product_bullet and non_product_bullet

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "leads_exists": False,
        "leads_json_valid": False,
        "leads_expected_urls_match": False,
        "leads_recency_correct": False,
        "leads_relevance_correct": False,
        "reply_structure_all_valid": False,
        "reasons_reference_matches": False,
        "product_name_and_url_in_replies": False,
        "within_engagement_limit": False,
        "scout_log_exists": False,
        "scout_log_includes_prior": False,
        "scout_log_threads_found_correct": False,
        "scout_log_table_header_present": False,
        "scout_log_rows_saved_for_each_url": False,
        "scout_log_notes_recency_mentions": False,
    }

    # Prepare expected from inputs
    try:
        config_path = os.path.join(input_dir, "scout-config.md")
        config_text = read_text(config_path)
    except Exception:
        config_text = ""

    # Defaults per task spec if parsing fails
    default_name = "InboxZero Pro"
    default_url = "https://inboxzero.pro"
    default_problems = ["email triage", "inbox overload", "auto-categorize emails"]
    default_keywords = ["email triage", "inbox zero", "inbox overload", "email filters"]
    name, url, problems, keywords, max_replies = parse_config_product(config_text)
    product_name = name or default_name
    product_url = url or default_url
    problems = problems if problems else default_problems
    keywords = keywords if keywords else default_keywords
    if max_replies is None:
        max_replies = 5

    # Read prior log to filter duplicates
    try:
        prior_log_path = os.path.join(input_dir, "scout-log.md")
        prior_log_text = read_text(prior_log_path)
    except Exception:
        prior_log_text = ""

    # Read search results and now timestamp
    try:
        search_path = os.path.join(input_dir, "search_results.json")
        candidates = read_json(search_path)
        if not isinstance(candidates, list):
            candidates = []
    except Exception:
        candidates = []

    try:
        now_txt = read_text(os.path.join(input_dir, "now.txt"))
        now_dt = parse_iso8601(now_txt)
    except Exception:
        # If now.txt missing or malformed, pick an arbitrary fixed time (won't award credit unless outputs match)
        now_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=None)

    # Build expected accepted leads
    expected = []  # list of dicts with url, platform, relevance, recency_hours, matches(list)
    for cand in candidates:
        url_c = cand.get("url", "")
        platform = cand.get("platform", "")
        title = cand.get("title", "")
        text = cand.get("text", "")
        created_at = cand.get("created_at", "")
        has_good_answer = cand.get("has_good_answer", False)

        if not isinstance(url_c, str) or url_c.strip() == "":
            continue
        # Skip if already in prior log
        if prior_log_text and url_c in prior_log_text:
            continue
        if has_good_answer:
            continue

        try:
            created_dt = parse_iso8601(created_at)
            # If timezone awareness differs, coerce naive to naive
            if (now_dt.tzinfo is None) != (created_dt.tzinfo is None):
                # make both naive by dropping tz
                now_dt_cmp = now_dt.replace(tzinfo=None) if now_dt.tzinfo else now_dt
                created_dt_cmp = created_dt.replace(tzinfo=None) if created_dt.tzinfo else created_dt
            else:
                now_dt_cmp = now_dt
                created_dt_cmp = created_dt
            recency = floor_hours(now_dt_cmp - created_dt_cmp)
        except Exception:
            # If malformed, skip
            continue

        # Skip older than 7 days (> 168 hours)
        if recency > 168:
            continue

        relevance, matches = classify_relevance(title, text, problems, keywords)
        if relevance in ("high", "medium"):
            expected.append({
                "url": url_c,
                "platform": platform,
                "relevance": relevance,
                "recency_hours": recency,
                "matches": matches
            })

    # Respect engagement cap (truncate to max_replies in deterministic order: keep as is)
    if len(expected) > max_replies:
        expected = expected[:max_replies]

    expected_urls = [e["url"] for e in expected]
    expected_by_url = {e["url"]: e for e in expected}

    # Leads.json checks
    leads_path = os.path.join(output_dir, "leads.json")
    leads = None
    if os.path.isfile(leads_path):
        checks["leads_exists"] = True
        try:
            with open(leads_path, "r", encoding="utf-8") as f:
                leads = json.load(f)
            if isinstance(leads, list):
                checks["leads_json_valid"] = True
        except Exception:
            leads = None

    if checks["leads_json_valid"] and leads is not None:
        # Check fields and compute various validations
        # Must match expected count and URLs exactly (order-insensitive)
        actual_urls = []
        fields_ok = True
        product_ok = True
        recency_ok = True
        relevance_ok = True
        reply_structure_ok = True
        reason_ok = True
        product_mention_ok = True
        # Also engagement limit
        engagement_ok = len(leads) <= max_replies

        for item in leads:
            if not isinstance(item, dict):
                fields_ok = False
                break
            if not extract_required_fields(item):
                fields_ok = False
                break
            url_i = item.get("url", "")
            actual_urls.append(url_i)
            # product must equal parsed name
            if item.get("product") != product_name:
                product_ok = False
            # platform allowed and matches expected if in expected set
            # We'll check platform match within expected_urls check below
            # recency hours check if URL in expected
            if url_i in expected_by_url:
                exp = expected_by_url[url_i]
                if item.get("recency_hours") != exp["recency_hours"]:
                    recency_ok = False
                if item.get("relevance") != exp["relevance"]:
                    relevance_ok = False
                # reply structure
                reply_txt = item.get("reply", "")
                if not isinstance(reply_txt, str):
                    reply_structure_ok = False
                else:
                    if not check_reply_structure(reply_txt, product_name, product_url):
                        reply_structure_ok = False
                # reason string should reference matched term
                reason_txt = item.get("reason", "")
                if not isinstance(reason_txt, str) or reason_txt.strip() == "":
                    reason_ok = False
                else:
                    # require at least one matched term to appear in reason (case-insensitive)
                    matched_terms = exp["matches"]
                    if matched_terms:
                        lc_reason = reason_txt.lower()
                        if not any(mt.lower() in lc_reason for mt in matched_terms):
                            reason_ok = False
                # product name and URL presence in reply (already checked in structure, but double-check across full reply)
                rep = item.get("reply", "")
                if not ((product_name in rep) and (product_url in rep)):
                    product_mention_ok = False
            else:
                # URL not expected; fail comparisons later
                pass

        # URLs must match expected set exactly
        checks["leads_expected_urls_match"] = set(actual_urls) == set(expected_urls) and len(leads) == len(expected_urls)
        checks["leads_recency_correct"] = recency_ok and checks["leads_expected_urls_match"]
        checks["leads_relevance_correct"] = relevance_ok and checks["leads_expected_urls_match"]
        checks["reply_structure_all_valid"] = reply_structure_ok and checks["leads_expected_urls_match"]
        checks["reasons_reference_matches"] = reason_ok and checks["leads_expected_urls_match"]
        checks["product_name_and_url_in_replies"] = product_mention_ok and checks["leads_expected_urls_match"]
        checks["within_engagement_limit"] = engagement_ok and checks["leads_expected_urls_match"] and len(leads) == len(expected_urls) and len(leads) <= max_replies
    else:
        # If leads missing or invalid, dependent checks remain False
        pass

    # scout-log.md checks
    log_out_path = os.path.join(output_dir, "scout-log.md")
    if os.path.isfile(log_out_path):
        checks["scout_log_exists"] = True
        try:
            out_log_text = read_text(log_out_path)
        except Exception:
            out_log_text = ""
    else:
        out_log_text = ""

    if checks["scout_log_exists"]:
        # Includes prior content at the beginning
        try:
            prior = read_text(os.path.join(input_dir, "scout-log.md"))
        except Exception:
            prior = ""
        # Normalize line endings
        out_norm = out_log_text.replace("\r\n", "\n")
        prior_norm = prior.replace("\r\n", "\n")
        # Allow extra trailing newlines in the prior content
        if out_norm.startswith(prior_norm):
            checks["scout_log_includes_prior"] = True
        else:
            # Also consider if a single trailing newline difference
            if out_norm.startswith(prior_norm.rstrip("\n")):
                checks["scout_log_includes_prior"] = True

        # Threads found: N must appear with N = len(leads)
        leads_count = 0
        if checks["leads_json_valid"] and isinstance(leads, list):
            leads_count = len(leads)
        m = re.search(r"Threads found:\s*([0-9]+)", out_norm)
        if m:
            try:
                found_n = int(m.group(1))
                if found_n == leads_count:
                    checks["scout_log_threads_found_correct"] = True
            except Exception:
                pass

        # Table header present
        header = "| Thread | Platform | Relevance | Action | Product | Notes |"
        if header in out_norm:
            checks["scout_log_table_header_present"] = True

        # For each URL in leads, find a line containing it and ensure 'saved' appears on same line
        rows_ok = True
        notes_ok = True
        if checks["leads_json_valid"] and isinstance(leads, list):
            for item in leads:
                url_i = item.get("url", "")
                platform_i = item.get("platform", "")
                relevance_i = item.get("relevance", "")
                # find line with URL
                lines = out_norm.splitlines()
                line_found = None
                for ln in lines:
                    if url_i in ln:
                        line_found = ln
                        break
                if not line_found:
                    rows_ok = False
                    notes_ok = False
                    continue
                # Saved on same line
                if "saved" not in line_found:
                    rows_ok = False
                # Platform and relevance and product should also be visible on that line (best effort)
                if platform_i and platform_i not in line_found:
                    rows_ok = False
                if relevance_i and relevance_i not in line_found:
                    rows_ok = False
                if product_name not in line_found:
                    rows_ok = False
                # Notes should mention "within {recency_hours}h"
                rec = item.get("recency_hours")
                if isinstance(rec, int):
                    if f"within {rec}h" not in line_found:
                        notes_ok = False
                else:
                    notes_ok = False
        else:
            rows_ok = False
            notes_ok = False
        checks["scout_log_rows_saved_for_each_url"] = rows_ok and checks["leads_expected_urls_match"]
        checks["scout_log_notes_recency_mentions"] = notes_ok and checks["leads_expected_urls_match"]

    # Compute reward
    # No-op baseline: if outputs missing or invalid, reward = 0.0
    essential_ok = checks["leads_exists"] and checks["leads_json_valid"] and checks["scout_log_exists"]
    if not essential_ok:
        reward = 0.0
    else:
        # Weight all checks equally
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Ensure reward between 0 and 1
        reward = passed / total if total else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    # Print exactly one JSON object on the last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()