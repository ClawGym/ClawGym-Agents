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

def parse_html_title(html):
    m = re.search(r'<title>\s*(.*?)\s*</title>', html, flags=re.I | re.S)
    return m.group(1).strip() if m else None

def extract_styles(html):
    return re.findall(r'<style[^>]*>(.*?)</style>', html, flags=re.I | re.S)

def has_h1(html):
    return re.search(r'<h1\b', html, flags=re.I) is not None

def has_table(html):
    return re.search(r'<table\b', html, flags=re.I) is not None

def has_list(html):
    return re.search(r'<ul\b|<ol\b', html, flags=re.I) is not None

def has_codeblock_with_language_python(html):
    # Look for <pre> followed by <code ... class="...language-python...">
    # Ensure sequence <pre> ... <code ...>
    return re.search(r'<pre[^>]*>\s*<code[^>]*class="[^"]*\blanguage-python\b[^"]*"', html, flags=re.I | re.S) is not None

def anchors_hrefs(html):
    return re.findall(r'<a\s+[^>]*href="([^"]+)"', html, flags=re.I)

def find_line_with_href(html, href):
    for line in html.splitlines():
        if f'href="{href}"' in line:
            return line
    return None

def is_relative_href(href):
    if href.startswith("http://") or href.startswith("https://") or href.startswith("/"):
        return False
    return True

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir not used but defined per convention
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "all_outputs_exist": False,
        "all_titles_match": False,
        "all_styles_match_theme": False,
        "all_have_h1": False,
        "weekly_notes_codeblock_python_class": False,
        "api_guide_has_table": False,
        "changelog_has_list": False,
        "index_exists": False,
        "index_has_overview": False,
        "index_has_all_links_exact": False,
        "index_links_relative_only": False,
        "index_mentions_themes_for_all": False,
        "system_health_exists": False,
        "system_health_valid_fields": False,
    }

    # Load configuration
    config_path = os.path.join(input_dir, "docs_config.json")
    config = load_json(config_path)
    documents = []
    if isinstance(config, dict) and isinstance(config.get("documents"), list):
        documents = config.get("documents", [])

    # Prepare expected docs info
    doc_outputs_abs = []
    doc_titles = {}
    doc_themes = {}
    all_docs_exist = True
    all_titles_match = True
    all_styles_match = True
    all_have_h1_flag = True

    for doc in documents:
        out_rel = doc.get("output")
        title = doc.get("title")
        theme = doc.get("theme")
        if not isinstance(out_rel, str):
            all_docs_exist = False
            all_titles_match = False
            all_styles_match = False
            all_have_h1_flag = False
            continue
        out_abs = os.path.join(workspace_root, out_rel)
        doc_outputs_abs.append(out_abs)
        doc_titles[out_abs] = title
        doc_themes[out_abs] = theme

    # Check each generated document
    for out_abs in doc_outputs_abs:
        html = read_text(out_abs)
        if html is None:
            all_docs_exist = False
            all_titles_match = False
            all_styles_match = False
            all_have_h1_flag = False
            continue

        # Title check
        expected_title = doc_titles.get(out_abs)
        actual_title = parse_html_title(html)
        if not (isinstance(expected_title, str) and actual_title == expected_title):
            all_titles_match = False

        # Style check per theme
        theme = doc_themes.get(out_abs, "")
        styles = extract_styles(html)
        style_text = "\n".join(styles) if styles else ""
        if theme == "light":
            if not ("color: #24292e" in style_text and "background: #fff" in style_text):
                all_styles_match = False
        elif theme == "dark":
            if not ("color: #c9d1d9" in style_text and "background: #0d1117" in style_text):
                all_styles_match = False
        else:
            # Unknown theme fails
            all_styles_match = False

        # h1 presence
        if not has_h1(html):
            all_have_h1_flag = False

    # Set aggregate checks
    if len(doc_outputs_abs) > 0 and all_docs_exist:
        checks["all_outputs_exist"] = True
    if len(doc_outputs_abs) > 0 and all_docs_exist and all_titles_match:
        checks["all_titles_match"] = True
    if len(doc_outputs_abs) > 0 and all_docs_exist and all_styles_match:
        checks["all_styles_match_theme"] = True
    if len(doc_outputs_abs) > 0 and all_docs_exist and all_have_h1_flag:
        checks["all_have_h1"] = True

    # Specific content checks
    # weekly_notes.html code block with language-python
    wn_doc = next((d for d in documents if isinstance(d.get("output"), str) and os.path.basename(d.get("output")) == "weekly_notes.html"), None)
    if wn_doc:
        wn_html = read_text(os.path.join(workspace_root, wn_doc["output"]))
        if wn_html is not None and has_codeblock_with_language_python(wn_html):
            checks["weekly_notes_codeblock_python_class"] = True

    # api_guide.html has table
    api_doc = next((d for d in documents if isinstance(d.get("output"), str) and os.path.basename(d.get("output")) == "api_guide.html"), None)
    if api_doc:
        api_html = read_text(os.path.join(workspace_root, api_doc["output"]))
        if api_html is not None and has_table(api_html):
            checks["api_guide_has_table"] = True

    # changelog.html has list
    cl_doc = next((d for d in documents if isinstance(d.get("output"), str) and os.path.basename(d.get("output")) == "changelog.html"), None)
    if cl_doc:
        cl_html = read_text(os.path.join(workspace_root, cl_doc["output"]))
        if cl_html is not None and has_list(cl_html):
            checks["changelog_has_list"] = True

    # Index checks
    index_path = os.path.join(output_dir, "index.html")
    index_html = read_text(index_path)
    if index_html is not None:
        checks["index_exists"] = True
        # Contains the word "Overview"
        if re.search(r'\bOverview\b', index_html, flags=re.I):
            checks["index_has_overview"] = True
        # Anchor links for each generated HTML file (href exactly matches config output string)
        hrefs = anchors_hrefs(index_html)
        expected_hrefs = [d["output"] for d in documents if isinstance(d.get("output"), str)]
        if all(e in hrefs for e in expected_hrefs) and len(expected_hrefs) > 0:
            checks["index_has_all_links_exact"] = True
        # Only relative links (no http(s) or leading /)
        if len(hrefs) > 0 and all(is_relative_href(h) for h in hrefs):
            checks["index_links_relative_only"] = True
        # Theme mentioned next to each link (string presence on same line as link)
        themes_ok = True
        if len(expected_hrefs) == 0:
            themes_ok = False
        else:
            for d in documents:
                out_rel = d.get("output")
                theme = d.get("theme", "")
                if not isinstance(out_rel, str) or not isinstance(theme, str):
                    themes_ok = False
                    break
                line = find_line_with_href(index_html, out_rel)
                # Require theme word present on the same line (case-insensitive)
                if not line or re.search(r'\b' + re.escape(theme) + r'\b', line, flags=re.I) is None:
                    themes_ok = False
                    break
        if themes_ok:
            checks["index_mentions_themes_for_all"] = True

    # System health JSON
    system_health_path = os.path.join(output_dir, "system_health.json")
    sh = load_json(system_health_path)
    if isinstance(sh, dict):
        checks["system_health_exists"] = True
        status = sh.get("status")
        recommendation = sh.get("recommendation")
        cpu = sh.get("cpu")
        mem = sh.get("memory")
        valid = True
        if status not in {"ok", "warning", "critical"}:
            valid = False
        if recommendation not in {"CONTINUE", "PAUSE"}:
            valid = False
        try:
            cpu_lp = cpu.get("load_percent") if isinstance(cpu, dict) else None
            if not isinstance(cpu_lp, (int, float)):
                valid = False
        except Exception:
            valid = False
        try:
            mem_up = mem.get("used_percent") if isinstance(mem, dict) else None
            if not isinstance(mem_up, (int, float)):
                valid = False
        except Exception:
            valid = False
        if valid:
            checks["system_health_valid_fields"] = True

    # Compute reward: average of passed checks
    check_values = list(checks.values())
    total = len(check_values)
    passed = sum(1 for v in check_values if v)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure baseline: if no output artifacts exist (output dir missing or empty), reward must be 0.0
    # We consider missing all three main expected artifacts as baseline: no generated docs and no index and no system health.
    any_output = False
    # Any expected doc exists?
    for out_abs in doc_outputs_abs:
        if os.path.isfile(out_abs):
            any_output = True
            break
    if not any_output and not os.path.isfile(index_path) and not os.path.isfile(system_health_path):
        reward = 0.0

    print(json.dumps({"reward": round(reward, 6), **checks}))

if __name__ == "__main__":
    main()