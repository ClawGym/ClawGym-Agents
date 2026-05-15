import json
import os
import re
import sys
from datetime import datetime

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_yaml_front_matter(md_text):
    # Expect YAML front matter at the very top between --- lines
    # Return dict-like with minimal parsed keys: date, title, keywords (list)
    result = {"date": None, "title": None, "keywords": []}
    if not md_text:
        return result
    # Match start '---' then content then '---'
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", md_text, flags=re.DOTALL)
    if not m:
        return result
    yaml_str = m.group(1)

    # Parse date
    m_date = re.search(r"(?im)^\s*date\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", yaml_str)
    if m_date:
        result["date"] = m_date.group(1).strip()

    # Parse title
    m_title = re.search(r"(?im)^\s*title\s*:\s*(.+?)\s*$", yaml_str)
    if m_title:
        result["title"] = m_title.group(1).strip().strip('"').strip("'")

    # Parse keywords line in form: keywords: [a, b, c]
    m_keywords = re.search(r"(?im)^\s*keywords\s*:\s*\[(.*?)\]\s*$", yaml_str)
    if m_keywords:
        inner = m_keywords.group(1).strip()
        # Split by commas not inside quotes (simple split sufficient here)
        items = [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
        result["keywords"] = [x for x in items if x]
    else:
        # Attempt multi-line YAML array (minimal support)
        # keywords:
        #   - kw1
        #   - kw2
        m_kw_block = re.search(r"(?ims)^\s*keywords\s*:\s*\n(.*?)\n(?:\S|\Z)", yaml_str)
        if m_kw_block:
            block = m_kw_block.group(1)
            items = re.findall(r"(?im)^\s*-\s*(.+?)\s*$", block)
            result["keywords"] = [x.strip().strip('"').strip("'") for x in items if x.strip()]

    return result

def get_section(text, header):
    # Return content between the header line and the next '## ' header or end
    if not text:
        return None
    # Find header line exactly
    pattern_header = re.compile(r"(?m)^\s*" + re.escape(header) + r"\s*$")
    m = pattern_header.search(text)
    if not m:
        return None
    start = m.end()
    # Find next section header
    m_next = re.search(r"(?m)^\s*##\s+", text[start:])
    if m_next:
        end = start + m_next.start()
    else:
        end = len(text)
    return text[start:end]

def find_subsection_blocks(section_text):
    # Split section into blocks by '### ' headings, return list of tuples (title, content)
    if not section_text:
        return []
    blocks = []
    # Find all '### ' headings positions
    it = list(re.finditer(r"(?m)^\s*###\s+(.+?)\s*$", section_text))
    if not it:
        return []
    for idx, m in enumerate(it):
        title = m.group(1).strip()
        start = m.end()
        if idx + 1 < len(it):
            end = it[idx+1].start()
        else:
            end = len(section_text)
        content = section_text[start:end]
        blocks.append((title, content))
    return blocks

def extract_source_time_line(block_text):
    # Find a line like: Source: X | Time: YYYY-MM-DD
    if not block_text:
        return None, None
    m = re.search(r"(?m)^\s*Source:\s*(.+?)\s*\|\s*Time:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", block_text)
    if not m:
        return None, None
    source = m.group(1).strip()
    date = m.group(2).strip()
    return source, date

def extract_body_after_source(block_text):
    # Body is lines after the first Source/Time line until next heading or end of block
    if not block_text:
        return ""
    # Locate Source line
    m = re.search(r"(?m)^\s*Source:\s*.+?\s*\|\s*Time:\s*[0-9]{4}-[0-9]{2}-[0-9]{2}\s*$", block_text)
    if not m:
        return ""
    start = m.end()
    # Up to end of block (block_text end)
    body = block_text[start:]
    # Remove further headings or separators if any (keep simple)
    # Clean leading/trailing whitespace
    body = body.strip()
    return body

def word_count(text):
    if not text:
        return 0
    # Count words by word-like tokens
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)

def parse_date(dstr):
    try:
        return datetime.strptime(dstr, "%Y-%m-%d").date()
    except Exception:
        return None

def last_non_empty_line(s):
    if s is None:
        return ""
    lines = [ln for ln in s.splitlines() if ln.strip() != ""]
    return lines[-1] if lines else ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dict
    checks = {
        "md_exists": False,
        "selection_exists": False,
        "rejections_exists": False,
        "yaml_date_title_keywords_ok": False,
        "headers_ok": False,
        "parent_cases_block_ok": False,
        "practice_frontline_block_ok": False,
        "policy_signals_block_ok": False,
        "quick_news_three_items_ok": False,
        "selection_schema_ok": False,
        "selection_titles_unique": False,
        "selection_dates_within_window": False,
        "selection_scores_threshold_and_no_promos": False,
        "rejections_reasons_valid": False,
        "rejections_has_blacklist": False,
        "rejections_has_stale": False,
    }

    # Paths
    md_path = os.path.join(output_dir, "AI_Education_Daily", "AI_Education_Daily_2026-04-02.md")
    selection_path = os.path.join(output_dir, "selection.json")
    rejections_path = os.path.join(output_dir, "rejections.json")

    # Check existence
    if os.path.isfile(md_path):
        checks["md_exists"] = True
    if os.path.isfile(selection_path):
        checks["selection_exists"] = True
    if os.path.isfile(rejections_path):
        checks["rejections_exists"] = True

    # Early exit reward 0.0 if any required artifact missing
    all_required_exist = checks["md_exists"] and checks["selection_exists"] and checks["rejections_exists"]

    md_text = read_text(md_path) if checks["md_exists"] else None

    # YAML front matter checks
    if checks["md_exists"] and md_text:
        yaml_info = parse_yaml_front_matter(md_text)
        date_ok = (yaml_info.get("date") == "2026-04-02")
        title_val = yaml_info.get("title") or ""
        title_ok = ("AI Education Daily - 2026-04-02" in title_val)
        keywords = yaml_info.get("keywords") or []
        keywords_ok = isinstance(keywords, list) and len(keywords) >= 3
        if date_ok and title_ok and keywords_ok:
            checks["yaml_date_title_keywords_ok"] = True

        # Headers presence
        required_headers = [
            "## 🏷️ Today’s Keywords",
            "## 💡 Actionable Suggestions",
            "## 👨‍👩‍👧 Parent Cases",
            "## 🔬 Practice Frontline",
            "## 📢 Policy Signals",
            "## ⚡ Quick News",
            "## ✨ Quote",
        ]
        headers_ok = all(h in md_text for h in required_headers)
        if headers_ok:
            checks["headers_ok"] = True

        # Parent Cases block: at least one item with ###, source/time line, 100–220 word body
        pc_section = get_section(md_text, "## 👨‍👩‍👧 Parent Cases")
        pc_ok = False
        if pc_section:
            blocks = find_subsection_blocks(pc_section)
            for title, content in blocks:
                src, dt = extract_source_time_line(content)
                body = extract_body_after_source(content)
                wc = word_count(body)
                if src and dt and 100 <= wc <= 220:
                    pc_ok = True
                    break
        checks["parent_cases_block_ok"] = pc_ok

        # Practice Frontline: must include both "### School Case" and "### Home Exploration" each with source/time and 100–220 words
        pf_section = get_section(md_text, "## 🔬 Practice Frontline")
        pf_ok = False
        if pf_section:
            blocks = {title.strip(): content for title, content in find_subsection_blocks(pf_section)}
            need_titles = ["School Case", "Home Exploration"]
            found_all = True
            for nt in need_titles:
                if nt not in blocks:
                    found_all = False
                    break
                src, dt = extract_source_time_line(blocks[nt])
                body = extract_body_after_source(blocks[nt])
                wc = word_count(body)
                if not (src and dt and 100 <= wc <= 220):
                    found_all = False
                    break
            pf_ok = found_all
        checks["practice_frontline_block_ok"] = pf_ok

        # Policy Signals: at least one item with ###, source/time line, 100–220 words
        pol_section = get_section(md_text, "## 📢 Policy Signals")
        pol_ok = False
        if pol_section:
            blocks = find_subsection_blocks(pol_section)
            for title, content in blocks:
                src, dt = extract_source_time_line(content)
                body = extract_body_after_source(content)
                wc = word_count(body)
                if src and dt and 100 <= wc <= 220:
                    pol_ok = True
                    break
        checks["policy_signals_block_ok"] = pol_ok

        # Quick News: exactly three single-line items labeled Parent Community, Product Updates, Research Frontiers
        qn_section = get_section(md_text, "## ⚡ Quick News")
        qn_ok = False
        if qn_section is not None:
            # Extract non-empty lines in this section
            lines = [ln.strip() for ln in qn_section.strip().splitlines() if ln.strip() != ""]
            # We expect exactly three lines
            labels = ["Parent Community", "Product Updates", "Research Frontiers"]
            if len(lines) == 3:
                found_labels = {lab: False for lab in labels}
                # Each line must contain one distinct label
                for ln in lines:
                    matched = [lab for lab in labels if lab in ln]
                    if len(matched) == 1 and not found_labels[matched[0]]:
                        found_labels[matched[0]] = True
                    else:
                        # Either no label or duplicate labels in lines
                        found_labels["Parent Community"] = False  # force failure
                        break
                qn_ok = all(found_labels.values())
        checks["quick_news_three_items_ok"] = qn_ok

    # selection.json checks
    selection_data = None
    if checks["selection_exists"]:
        try:
            with open(selection_path, "r", encoding="utf-8") as f:
                selection_data = json.load(f)
        except Exception:
            selection_data = None

    selection_schema_ok = False
    selection_titles_unique = False
    selection_dates_ok = False
    selection_scores_and_promos_ok = False

    report_date = parse_date("2026-04-02")

    if isinstance(selection_data, list):
        all_schema = True
        titles = []
        dates_ok = True
        scores_ok = True
        promos_ok = True
        categories_valid = {"parent", "practice", "policy", "other"}
        for item in selection_data:
            # Basic fields present and types
            try:
                title = item["title"]
                source = item["source"]
                source_category = item["source_category"]
                typ = item["type"]
                date_str = item["date"]
                score = item["score"]
                breakdown = item["breakdown"]
                rec = breakdown["recency"]
                prac = breakdown["practicality"]
                auth = breakdown["authority"]
                aud = breakdown["audience"]
                category = item["category"]
            except Exception:
                all_schema = False
                break

            # Types check
            if not (isinstance(title, str) and isinstance(source, str) and isinstance(source_category, str) and isinstance(typ, str) and isinstance(date_str, str)):
                all_schema = False
                break
            if typ not in ("wechat", "web"):
                all_schema = False
                break
            if category not in categories_valid:
                all_schema = False
                break
            # Numeric checks
            for num in [score, rec, prac, auth, aud]:
                if not isinstance(num, (int, float)):
                    all_schema = False
                    break
            if not all_schema:
                break
            # Score threshold
            if score < 4.5:
                scores_ok = False
            # Date window checks
            d = parse_date(date_str)
            if d is None or report_date is None:
                dates_ok = False
            else:
                delta = (report_date - d).days
                if delta < 0 or delta > 7:
                    dates_ok = False
            # Promotional terms check in title
            low_title = title.lower()
            for bad in ["buy", "coupon", "deal", "discount"]:
                if bad in low_title:
                    promos_ok = False
                    break
            titles.append(title)

        selection_schema_ok = all_schema
        # Titles unique
        if all_schema:
            selection_titles_unique = len(titles) == len(set(titles))
        selection_dates_ok = dates_ok
        selection_scores_and_promos_ok = scores_ok and promos_ok

    checks["selection_schema_ok"] = selection_schema_ok
    checks["selection_titles_unique"] = selection_titles_unique
    checks["selection_dates_within_window"] = selection_dates_ok
    checks["selection_scores_threshold_and_no_promos"] = selection_scores_and_promos_ok

    # rejections.json checks
    rej_data = None
    if checks["rejections_exists"]:
        try:
            with open(rejections_path, "r", encoding="utf-8") as f:
                rej_data = json.load(f)
        except Exception:
            rej_data = None

    reasons_valid = False
    has_blacklist = False
    has_stale = False
    if isinstance(rej_data, list):
        allowed = {"blacklist", "stale", "below_threshold", "duplicate"}
        valid_all = True
        for it in rej_data:
            # Each must have title, source, reason
            if not isinstance(it, dict):
                valid_all = False
                break
            if "title" not in it or "source" not in it or "reason" not in it:
                valid_all = False
                break
            if not isinstance(it["title"], str) or not isinstance(it["source"], str) or not isinstance(it["reason"], str):
                valid_all = False
                break
            if it["reason"] not in allowed:
                valid_all = False
                break
            if it["reason"] == "blacklist":
                has_blacklist = True
            if it["reason"] == "stale":
                has_stale = True
        reasons_valid = valid_all

    checks["rejections_reasons_valid"] = reasons_valid
    checks["rejections_has_blacklist"] = has_blacklist
    checks["rejections_has_stale"] = has_stale

    # Compute reward
    if not all_required_exist:
        reward = 0.0
    else:
        # Count only checks that are meaningful after existence
        # We include all booleans in checks (they all depend on outputs)
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total if total > 0 else 0.0
        # Clamp to [0,1]
        reward = max(0.0, min(1.0, reward))

    # Print single JSON line
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()