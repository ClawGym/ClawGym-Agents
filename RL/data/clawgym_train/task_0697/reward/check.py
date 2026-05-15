import json
import os
import sys
import re

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def list_markdown_files(root_dir):
    md_files = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # ignore node_modules and .git
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git")]
        for fn in filenames:
            if fn.lower().endswith(".md"):
                md_files.append(os.path.join(dirpath, fn))
    return md_files

def parse_markdown_links(content):
    # returns list of dicts: {text, url, line}
    links = []
    # Regex similar to JS: \[([^\]]+)\]\(([^)]+)\)
    link_regex = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    for m in link_regex.finditer(content):
        text = m.group(1)
        url = m.group(2).strip()
        # line number: count newlines before match start
        line = content[:m.start()].count("\n") + 1
        links.append({"text": text, "url": url, "line": line})
    return links

def is_external_or_anchor(url):
    u = url.strip()
    if u.lower().startswith("http://") or u.lower().startswith("https://"):
        return True
    if u.startswith("#"):
        return True
    return False

def normalize_link_url(u):
    # remove leading ./ from url for comparison
    u = u.strip()
    if u.startswith("./"):
        return u[2:]
    return u

def resolve_target_path(file_abs_dir, url):
    # strip anchor part after '#'
    base = url.split("#")[0]
    # resolve relative paths
    return os.path.normpath(os.path.join(file_abs_dir, base))

def scan_broken_links(workspace_root, md_abs_path):
    content = read_file_text(md_abs_path)
    if content is None:
        return []
    links = parse_markdown_links(content)
    broken = []
    file_abs_dir = os.path.dirname(md_abs_path)
    for link in links:
        url = link["url"]
        if is_external_or_anchor(url):
            continue
        target_abs = resolve_target_path(file_abs_dir, url)
        if not os.path.exists(target_abs):
            broken.append({"text": link["text"], "url": url, "line": link["line"]})
    return broken

def ensure_array_of_objects(value):
    return isinstance(value, list) and all(isinstance(x, dict) for x in value)

def get_relative_path(workspace_root, abs_path):
    # return path relative to workspace root using forward slashes
    rel = os.path.relpath(abs_path, workspace_root)
    return rel.replace("\\", "/")

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "report_exists": False,
        "report_json_valid": False,
        "report_paths_relative": False,
        "report_includes_expected_files": False,
        "report_includes_expected_broken": False,
        "report_ignores_external_and_anchors": False,
        "report_valid_flags_consistent": False,
        "fix_plan_exists": False,
        "fix_plan_has_sections": False,
        "fix_plan_has_broken_links_summary": False,
        "fix_plan_lists_expected_broken": False,
        "fix_plan_has_fix_recommendations": False,
        "api_design_exists": False,
        "api_design_has_group_and_middleware": False,
        "api_design_has_endpoints": False,
        "api_design_has_params_and_query": False,
        "api_design_mentions_json_and_status": False,
        "api_design_has_example_json": False,
    }

    # Compute expected files and expected broken links by scanning input/
    md_files_abs = list_markdown_files(input_dir)
    # Map rel path to abs path
    md_files_rel = [get_relative_path(workspace_root, p) for p in md_files_abs]
    # We will focus checks on these known files per task spec
    expected_files_set = set([
        "input/README.md",
        "input/docs/getting-started.md",
        "input/docs/deep/overview.md",
    ])
    # Build map of broken links for each file from input
    broken_map = {}
    for abs_path, rel_path in zip(md_files_abs, md_files_rel):
        broken = scan_broken_links(workspace_root, abs_path)
        broken_map[rel_path] = broken

    # Identify expected broken links targets (normalized) from spec
    expected_broken_targets = {
        "input/README.md": "docs/api-guide.md",  # accept with or without leading ./
        "input/docs/getting-started.md": "deep/missing.md",
    }
    # For each expected file, find the actual broken link item in scanned data
    expected_broken_actual = {}
    for file_rel, target_norm in expected_broken_targets.items():
        items = broken_map.get(file_rel, [])
        found_item = None
        for it in items:
            if normalize_link_url(it["url"]) == target_norm:
                found_item = it
                break
        if found_item:
            expected_broken_actual[file_rel] = found_item
        # else leave missing; we'll still verify against output but will fail appropriately

    # 1) Validate output/report.json
    report_path = os.path.join(output_dir, "report.json")
    report_data = None
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        txt = read_file_text(report_path)
        if txt is not None:
            try:
                data = json.loads(txt)
                if ensure_array_of_objects(data):
                    # validate schema of each element minimally
                    schema_ok = True
                    paths_relative_ok = True
                    ignores_external_anchors_ok = True
                    files_present_ok = True
                    valid_flags_consistent_ok = True
                    includes_expected_broken_ok = True

                    # Build index by file path
                    by_file = {}
                    for item in data:
                        file_field = item.get("file")
                        valid_field = item.get("valid")
                        broken_links_field = item.get("brokenLinks")
                        if not (isinstance(file_field, str) and isinstance(valid_field, bool) and isinstance(broken_links_field, list)):
                            schema_ok = False
                            break
                        # validate brokenLinks items
                        for bi in broken_links_field:
                            if not (isinstance(bi, dict)
                                    and isinstance(bi.get("text"), (str))
                                    and isinstance(bi.get("url"), (str))
                                    and isinstance(bi.get("line"), int)):
                                schema_ok = False
                                break
                        if not schema_ok:
                            break
                        # path relative check
                        if not (file_field.startswith("input/") and not file_field.startswith("/")):
                            paths_relative_ok = False
                        by_file[file_field] = item

                    if schema_ok:
                        checks["report_json_valid"] = True
                        checks["report_paths_relative"] = paths_relative_ok

                        # check includes expected files
                        for ef in expected_files_set:
                            if ef not in by_file:
                                files_present_ok = False
                                break
                        checks["report_includes_expected_files"] = files_present_ok

                        # check ignore external/anchors across all brokenLinks
                        for item in data:
                            for bi in item.get("brokenLinks", []):
                                u = bi.get("url", "")
                                if is_external_or_anchor(u):
                                    ignores_external_anchors_ok = False
                                    break
                            if not ignores_external_anchors_ok:
                                break
                        checks["report_ignores_external_and_anchors"] = ignores_external_anchors_ok

                        # check valid flag consistent with recomputed broken links for expected files only
                        for ef in expected_files_set:
                            if ef in by_file:
                                reported_broken = by_file[ef].get("brokenLinks", [])
                                reported_has_broken = len(reported_broken) > 0
                                recomputed_has_broken = len(broken_map.get(ef, [])) > 0
                                if reported_has_broken != recomputed_has_broken:
                                    valid_flags_consistent_ok = False
                                    break
                                if by_file[ef].get("valid") != (not reported_has_broken):
                                    valid_flags_consistent_ok = False
                                    break
                            else:
                                valid_flags_consistent_ok = False
                                break
                        checks["report_valid_flags_consistent"] = valid_flags_consistent_ok

                        # check includes at least the expected broken links with matching url and line (from recomputation)
                        # Only check if recomputation found the items
                        for file_rel, expected_item in expected_broken_actual.items():
                            if file_rel not in by_file:
                                includes_expected_broken_ok = False
                                break
                            # find in reported brokenLinks
                            rep = by_file[file_rel].get("brokenLinks", [])
                            match_found = False
                            for rb in rep:
                                if isinstance(rb, dict) and rb.get("url") == expected_item["url"] and rb.get("line") == expected_item["line"]:
                                    match_found = True
                                    break
                            if not match_found:
                                includes_expected_broken_ok = False
                                break
                        # If recomputation could not find an expected broken (missing from inputs), this check should fail
                        # because the outputs cannot be verified against inputs
                        if len(expected_broken_actual) != len(expected_broken_targets):
                            includes_expected_broken_ok = False
                        checks["report_includes_expected_broken"] = includes_expected_broken_ok

                    report_data = data
            except Exception:
                # JSON parsing failed
                pass

    # 2) Validate output/fix-plan.md
    fix_plan_path = os.path.join(output_dir, "fix-plan.md")
    fix_txt = None
    if os.path.isfile(fix_plan_path):
        checks["fix_plan_exists"] = True
        fix_txt = read_file_text(fix_plan_path)

    if fix_txt:
        # headings check: Quickstart, Patterns, Debugging, Performance, Security, Migration, Cheatsheet
        def has_heading(name):
            pat = re.compile(rf"^\s{{0,3}}#{1,6}\s*{re.escape(name)}\b", re.IGNORECASE | re.MULTILINE)
            return pat.search(fix_txt) is not None

        sections_ok = all([
            has_heading("Quickstart"),
            has_heading("Patterns"),
            has_heading("Debugging"),
            has_heading("Performance"),
            has_heading("Security"),
            has_heading("Migration"),
            has_heading("Cheatsheet"),
        ])
        checks["fix_plan_has_sections"] = sections_ok

        # Broken Links Summary heading
        bls_ok = has_heading("Broken Links Summary")
        checks["fix_plan_has_broken_links_summary"] = bls_ok

        # Lists each expected broken link with file, link text, target URL, and line
        # Use recomputed expected items; require presence of a line containing file, url, and line number
        list_ok = True
        if len(expected_broken_actual) != len(expected_broken_targets):
            list_ok = False
        else:
            lines = fix_txt.splitlines()
            for file_rel, item in expected_broken_actual.items():
                url = item["url"]
                line_str = str(item["line"])
                text = item["text"]
                found_line = False
                for ln in lines:
                    if (file_rel in ln) and (url in ln) and (line_str in ln):
                        # also require link text mention somewhere in file to be stricter but flexible:
                        # allow it to be on same line or elsewhere
                        if (text in ln) or (text in fix_txt):
                            found_line = True
                            break
                if not found_line:
                    list_ok = False
                    break
        checks["fix_plan_lists_expected_broken"] = list_ok

        # "Fix:" recommendations: at least one per expected broken link
        fix_count = len(re.findall(r"^\s*Fix:\s", fix_txt, flags=re.IGNORECASE | re.MULTILINE))
        checks["fix_plan_has_fix_recommendations"] = fix_count >= len(expected_broken_targets)

    # 3) Validate output/api-design.md
    api_design_path = os.path.join(output_dir, "api-design.md")
    api_txt = None
    if os.path.isfile(api_design_path):
        checks["api_design_exists"] = True
        api_txt = read_file_text(api_design_path)

    if api_txt:
        # group prefix and middleware words
        grp_ok = ("/api/v1" in api_txt) and (re.search(r"\bmiddleware\b", api_txt, re.IGNORECASE) is not None) and (re.search(r"\blogging\b", api_txt, re.IGNORECASE) is not None) and (re.search(r"\bCORS\b", api_txt, re.IGNORECASE) is not None)
        checks["api_design_has_group_and_middleware"] = grp_ok

        # endpoints exact paths
        ep_ok = ("/api/v1/report" in api_txt) and ("/api/v1/docs/:name" in api_txt) and ("/api/v1/echo" in api_txt)
        checks["api_design_has_endpoints"] = ep_ok

        # params and query parsing mention: :name and format with default raw
        params_ok = (":name" in api_txt) and (re.search(r"\bformat\b", api_txt, re.IGNORECASE) is not None) and (re.search(r"\bdefault\b", api_txt, re.IGNORECASE) is not None) and (re.search(r"\braw\b", api_txt, re.IGNORECASE) is not None)
        checks["api_design_has_params_and_query"] = params_ok

        # JSON payload decoding and custom status codes mentioned
        json_status_ok = (re.search(r"\bJSON\b", api_txt, re.IGNORECASE) is not None) and (re.search(r"\bstatus\s+code\b", api_txt, re.IGNORECASE) is not None) and (re.search(r"\bcustom\b", api_txt, re.IGNORECASE) is not None)
        checks["api_design_mentions_json_and_status"] = json_status_ok

        # example JSON response including keys: file, valid, brokenLinks; presence of braces for JSON
        has_json_keys = (re.search(r"\bfile\b", api_txt) is not None) and (re.search(r"\bvalid\b", api_txt) is not None) and (re.search(r"\bbrokenLinks\b", api_txt) is not None)
        has_braces = ("{" in api_txt or "[" in api_txt)
        checks["api_design_has_example_json"] = has_json_keys and has_braces

    # Compute reward as average of True checks, with baseline 0.0 if outputs missing or invalid
    # No-op baseline: if output/ is missing or none of the primary artifacts exist, reward is 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if checks["report_exists"] or checks["fix_plan_exists"] or checks["api_design_exists"]:
        reward = passed / total_checks
    else:
        reward = 0.0

    # Print exactly one JSON object as the last non-empty line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()