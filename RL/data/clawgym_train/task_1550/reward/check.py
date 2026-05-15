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
        return ""

def file_exists(path):
    try:
        return os.path.isfile(path)
    except Exception:
        return False

def dir_exists(path):
    try:
        return os.path.isdir(path)
    except Exception:
        return False

def listdir_recursive(path):
    out = []
    for root, dirs, files in os.walk(path):
        for f in files:
            out.append(os.path.join(root, f))
    return out

def sanitize_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        s = val.strip().lower()
        if s in {"true","yes","y","on","1","✔","✓"}:
            return True
        if s in {"false","no","n","off","0","✖","x"}:
            return False
    return None

def yaml_uncomment(lines):
    out = []
    for line in lines:
        # Remove comments not inside quoted values
        if "#" in line:
            idx = line.find("#")
            # Keep if the # is within quotes - simple heuristic: if before # there's an odd number of quotes
            before = line[:idx]
            if before.count('"') % 2 == 0 and before.count("'") % 2 == 0:
                line = before.rstrip()
        out.append(line.rstrip("\n"))
    return out

def parse_simple_yaml_projects(text):
    # Minimal YAML parser for expected structure:
    # Either:
    # projects:
    #   - name: ...
    #     language: ...
    #     ...
    #     author:
    #       name: ...
    #       email: ...
    # Or directly a top-level list:
    # - name: ...
    # ...
    lines = yaml_uncomment(text.splitlines())
    # Trim empty lines
    lines = [ln for ln in lines if ln.strip() != ""]
    # Find start of list
    start_idx = 0
    has_projects_key = False
    for i, ln in enumerate(lines):
        if re.match(r"^\s*projects\s*:\s*$", ln):
            has_projects_key = True
            start_idx = i + 1
            break
    # Find first '- ' item to determine item indent
    item_indent = None
    for i in range(start_idx, len(lines)):
        m = re.match(r"^(\s*)-\s+(.*)$", lines[i])
        if m:
            item_indent = len(m.group(1))
            start_idx = i
            break
        m2 = re.match(r"^(\s*)-\s*$", lines[i])
        if m2:
            item_indent = len(m2.group(1))
            start_idx = i
            break
    if item_indent is None:
        return []
    i = start_idx
    projects = []
    while i < len(lines):
        # Start of an item
        m_item = re.match(r"^(\s*)-\s*(.*)$", lines[i])
        if not m_item or len(m_item.group(1)) != item_indent:
            i += 1
            continue
        proj = {}
        base_indent = item_indent
        rest = m_item.group(2).strip()
        # Parse inline key in the same line after '- '
        if rest:
            # Allow "key: value" inline
            if ":" in rest:
                k, v = rest.split(":", 1)
                key = k.strip()
                val = v.strip()
                proj[key] = coerce_scalar(val)
        i += 1
        # Parse subsequent properties indented more than base_indent
        # Author nested map supported
        while i < len(lines):
            line = lines[i]
            if re.match(rf"^\s{{0,{base_indent}}}-\s", line):
                break  # next item
            if line.strip() == "":
                i += 1
                continue
            # Must be more indented than base
            m_prop = re.match(rf"^(\s*)([^:\s][^:]*)\s*:\s*(.*)$", line)
            if not m_prop:
                i += 1
                continue
            indent = len(m_prop.group(1))
            key = m_prop.group(2).strip()
            val = m_prop.group(3).strip()
            if indent <= base_indent:
                # out of this item
                break
            if key == "author":
                # Parse nested author mapping
                author = {}
                if val:  # inline mapping not expected; but if present, ignore
                    # e.g., author: { name: X, email: Y } not supported
                    pass
                i += 1
                while i < len(lines):
                    sub = lines[i]
                    m_sub = re.match(rf"^(\s*)([^:\s][^:]*)\s*:\s*(.*)$", sub)
                    if not m_sub:
                        break
                    sub_indent = len(m_sub.group(1))
                    if sub_indent <= indent:
                        break
                    akey = m_sub.group(2).strip()
                    aval = m_sub.group(3).strip()
                    author[akey] = coerce_scalar(aval)
                    i += 1
                proj["author"] = author
                continue  # do not i += 1 further
            else:
                proj[key] = coerce_scalar(val)
                i += 1
        projects.append(proj)
    # Normalize field names to expected keys if possible
    normalized = []
    for p in projects:
        np = {}
        for k, v in p.items():
            np[k.strip()] = v
        normalized.append(np)
    return normalized

def coerce_scalar(val):
    # Remove optional quotes
    v = val.strip()
    if v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) >= 2:
        v = v[1:-1]
    low = v.lower()
    if low in {"true","false"}:
        return low == "true"
    # numbers not expected besides maybe, ignore
    return v

def extract_markdown_table(text):
    # Returns (headers, rows) where rows is list of list of cells (str)
    lines = [ln.rstrip() for ln in text.splitlines()]
    # Find header row starting with |
    start = -1
    for idx in range(len(lines)):
        if lines[idx].strip().startswith("|") and "|" in lines[idx].strip()[1:]:
            # Next non-empty line should be separator of --- cells
            # But we will accept any next line with '---'
            # Find the next line that contains --- under headers
            if idx + 1 < len(lines):
                if "---" in lines[idx+1]:
                    start = idx
                    break
    if start == -1:
        return None, None
    header_line = lines[start].strip()
    sep_line = lines[start+1].strip() if start + 1 < len(lines) else ""
    # parse header cells
    headers = [c.strip() for c in header_line.strip("|").split("|")]
    # Collect rows until a line not starting with |
    rows = []
    i = start + 2
    while i < len(lines):
        ln = lines[i].strip()
        if not ln.startswith("|"):
            break
        # Skip separator-like rows
        if set(ln.replace("|","").replace(":","").replace("-","").strip()) == set():
            i += 1
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        rows.append(cells)
        i += 1
    return headers, rows

def cell_extract_link_or_text(cell):
    # If markdown link like [text](url) return url, else return stripped text
    m = re.search(r"\[.*?\]\((.*?)\)", cell)
    if m:
        return m.group(1).strip()
    return cell.strip()

def normalize_path_cell(cell):
    val = cell_extract_link_or_text(cell)
    # Remove surrounding quotes/backticks
    val = val.strip().strip("`").strip()
    # Remove leading ./ if present
    if val.startswith("./"):
        val = val[2:]
    return val

def contains_all_sections(readme_text):
    # Require headings: Getting Started, Installation, Running, Testing, Linting
    required = ["Getting Started", "Installation", "Running", "Testing", "Linting"]
    present = set()
    for line in readme_text.splitlines():
        if line.strip().lower().startswith("## "):
            title = line.strip()[3:].strip().lower()
            for req in required:
                if title == req.lower():
                    present.add(req.lower())
    return all(r.lower() in present for r in required)

def readme_lang_commands_ok(readme_text, lang):
    t = readme_text.lower()
    if lang.lower() == "python":
        return ("pip install" in t) and ("pytest" in t)
    if lang.lower() == "go":
        return ("go test" in t) and (("go build" in t) or ("go run" in t))
    if lang.lower() == "rust":
        return ("cargo test" in t)
    return False

def license_matches(content, license_key):
    t = content
    k = license_key.lower()
    if k == "mit":
        return "MIT License" in t
    if k == "apache2":
        return ("Apache License" in t) and ("Version 2.0" in t)
    if k == "gpl3":
        return ("GNU General Public License" in t)
    return False

def license_has_author_and_year(content, author_name, current_year):
    # Must include 4-digit year and author name; year should be current year
    year_match = re.search(r"\b(19|20|21)\d{2}\b", content)
    has_name = author_name in content if author_name else False
    has_current = str(current_year) in content
    return (year_match is not None) and has_name and has_current

def dockerfile_lang_hint_ok(dockerfile_text, lang):
    t = dockerfile_text.lower()
    if lang.lower() == "python":
        return ("python:3" in t)
    if lang.lower() == "go":
        return ("golang:1" in t) or ("scratch" in t)
    if lang.lower() == "rust":
        return ("rust:1" in t) or ("debian:slim" in t) or re.search(r"debian:.*slim", t) is not None
    return False

def project_module_name(name):
    return name.lower().replace("-", "_")

def path_join(*parts):
    return os.path.join(*parts)

def docker_cell_matches(cell, expected_bool):
    val = sanitize_bool(cell_extract_link_or_text(cell))
    if val is None:
        # Try interpret textual like 'yes'/'no'
        s = cell_extract_link_or_text(cell).strip().lower()
        if expected_bool:
            return any(x in s for x in ["true","yes","y","on","1","✔","✓"])
        else:
            return any(x in s for x in ["false","no","n","off","0","✖","x"])
    return val == expected_bool

def ci_cell_matches(cell, expected_ci):
    s = cell_extract_link_or_text(cell).strip().lower()
    return expected_ci.lower() in s

def build_checks(projects, workspace_root):
    checks = {}
    output_dir = path_join(workspace_root, "output")
    projects_root = path_join(output_dir, "projects")
    portfolio_md_path = path_join(output_dir, "PORTFOLIO.md")
    summary_json_path = path_join(output_dir, "summary.json")
    current_year = datetime.now().year

    # No-op baseline guard: if output/ missing or empty -> reward 0
    output_present = dir_exists(output_dir)
    has_any_output_files = len(listdir_recursive(output_dir)) > 0 if output_present else False
    # We'll compute checks regardless; reward function will set to 0.0 if no-op baseline.

    # Portfolio checks
    checks["portfolio_md_exists"] = file_exists(portfolio_md_path)
    portfolio_headers_ok = False
    portfolio_rows_count_ok = False
    portfolio_rows_values_ok = False
    if checks["portfolio_md_exists"]:
        text = read_text(portfolio_md_path)
        headers, rows = extract_markdown_table(text)
        expected_headers = ["Name","Language","License","Docker","CI","Path"]
        if headers is not None:
            # Normalize headers case-insensitive
            portfolio_headers_ok = [h.lower() for h in headers] == [h.lower() for h in expected_headers]
        if rows is not None:
            # Count check
            # Filter out rows with mismatched number of columns
            valid_rows = [r for r in rows if len(r) >= len(expected_headers)]
            portfolio_rows_count_ok = len(valid_rows) == len(projects)
            # Values check
            all_ok = True
            # Build index by name
            row_by_name = {}
            for r in valid_rows:
                # Map cells to headers
                row_map = {}
                for idx, h in enumerate(headers[:len(expected_headers)]):
                    row_map[h] = r[idx] if idx < len(r) else ""
                nm = row_map.get("Name","").strip()
                row_by_name[nm] = row_map
            for p in projects:
                nm = p.get("name","")
                if nm not in row_by_name:
                    all_ok = False
                    break
                rm = row_by_name[nm]
                # Language
                lang_cell = rm.get("Language","")
                if lang_cell.strip().lower() != str(p.get("language","")).strip().lower():
                    all_ok = False
                    break
                # License
                lic_cell = rm.get("License","")
                if lic_cell.strip().lower() != str(p.get("license","")).strip().lower():
                    all_ok = False
                    break
                # Docker
                if not docker_cell_matches(rm.get("Docker",""), bool(p.get("docker", False))):
                    all_ok = False
                    break
                # CI
                if not ci_cell_matches(rm.get("CI",""), str(p.get("ci",""))):
                    all_ok = False
                    break
                # Path
                path_cell = normalize_path_cell(rm.get("Path",""))
                expected_rel = os.path.join("output","projects", nm)
                # Accept exactly expected_rel
                if path_cell != expected_rel:
                    all_ok = False
                    break
            portfolio_rows_values_ok = all_ok
    checks["portfolio_md_headers_correct"] = portfolio_headers_ok
    checks["portfolio_md_rows_count"] = portfolio_rows_count_ok
    checks["portfolio_md_rows_values_correct"] = portfolio_rows_values_ok

    # summary.json checks
    checks["summary_json_exists"] = file_exists(summary_json_path)
    summary_json_valid = False
    summary_json_count_ok = False
    summary_json_values_ok = False
    summary_arr = None
    if checks["summary_json_exists"]:
        try:
            data = json.loads(read_text(summary_json_path))
            # Accept top-level array or object with "projects"
            if isinstance(data, list):
                summary_arr = data
            elif isinstance(data, dict) and isinstance(data.get("projects"), list):
                summary_arr = data.get("projects")
            else:
                summary_arr = None
            summary_json_valid = summary_arr is not None
        except Exception:
            summary_arr = None
            summary_json_valid = False
        if summary_arr is not None:
            summary_json_count_ok = len(summary_arr) == len(projects)
            # Build index by name
            idx = {item.get("name"): item for item in summary_arr if isinstance(item, dict)}
            all_ok = True
            for p in projects:
                nm = p.get("name")
                it = idx.get(nm)
                if not it:
                    all_ok = False
                    break
                # Required fields
                req_fields = ["name","language","license","docker","has_ci","path","description"]
                if not all(f in it for f in req_fields):
                    all_ok = False
                    break
                if str(it["name"]) != nm:
                    all_ok = False
                    break
                if str(it["language"]).lower() != str(p.get("language")).lower():
                    all_ok = False
                    break
                if str(it["license"]).lower() != str(p.get("license")).lower():
                    all_ok = False
                    break
                docker_bool = it["docker"] if isinstance(it["docker"], bool) else sanitize_bool(str(it["docker"]))
                if docker_bool is None or docker_bool != bool(p.get("docker", False)):
                    all_ok = False
                    break
                has_ci_bool = it["has_ci"] if isinstance(it["has_ci"], bool) else sanitize_bool(str(it["has_ci"]))
                expected_has_ci = bool(p.get("ci"))
                if has_ci_bool is None or has_ci_bool != expected_has_ci:
                    all_ok = False
                    break
                # Path
                expected_rel = os.path.join("output","projects", nm)
                if it["path"] != expected_rel:
                    all_ok = False
                    break
                # Description
                if str(it["description"]) != str(p.get("description","")):
                    all_ok = False
                    break
            summary_json_values_ok = all_ok
    checks["summary_json_valid"] = summary_json_valid
    checks["summary_json_count"] = summary_json_count_ok
    checks["summary_json_values_match"] = summary_json_values_ok

    # Per project checks
    for p in projects:
        name = p.get("name","")
        lang = (p.get("language") or "").lower()
        lic = (p.get("license") or "").lower()
        docker_enabled = bool(p.get("docker", False))
        ci_provider = (p.get("ci") or "")
        author = p.get("author") or {}
        author_name = author.get("name","")

        proj_root = path_join(projects_root, name)
        keyprefix = f"{name}::"

        checks[f"{keyprefix}dir_exists"] = dir_exists(proj_root)

        # README
        readme_path = path_join(proj_root, "README.md")
        has_readme = file_exists(readme_path)
        checks[f"{keyprefix}readme_exists"] = has_readme
        h1_ok = False
        desc_ok = False
        sections_ok = False
        lang_cmds_ok = False
        if has_readme:
            readme = read_text(readme_path)
            lines = readme.splitlines()
            if lines:
                h1_ok = lines[0].strip() == f"# {name}"
            # description presence
            desc = str(p.get("description",""))
            desc_ok = desc in readme if desc else False
            sections_ok = contains_all_sections(readme)
            lang_cmds_ok = readme_lang_commands_ok(readme, lang)
        checks[f"{keyprefix}readme_h1_correct"] = h1_ok
        checks[f"{keyprefix}readme_description_present"] = desc_ok
        checks[f"{keyprefix}readme_sections_present"] = sections_ok
        checks[f"{keyprefix}readme_language_commands"] = lang_cmds_ok

        # LICENSE
        license_path = path_join(proj_root, "LICENSE")
        has_license = file_exists(license_path)
        checks[f"{keyprefix}license_exists"] = has_license
        license_match = False
        license_author_year = False
        if has_license:
            lic_text = read_text(license_path)
            license_match = license_matches(lic_text, lic)
            license_author_year = license_has_author_and_year(lic_text, author_name, current_year)
        checks[f"{keyprefix}license_matches"] = license_match
        checks[f"{keyprefix}license_has_author_year"] = license_author_year

        # .gitignore and .editorconfig
        gitignore_path = path_join(proj_root, ".gitignore")
        editorconfig_path = path_join(proj_root, ".editorconfig")
        has_gitignore = file_exists(gitignore_path)
        checks[f"{keyprefix}gitignore_exists"] = has_gitignore
        has_env = False
        if has_gitignore:
            gi = read_text(gitignore_path)
            has_env = (".env" in gi)
        checks[f"{keyprefix}gitignore_has_env"] = has_env
        checks[f"{keyprefix}editorconfig_exists"] = file_exists(editorconfig_path)

        # CI
        ci_path = path_join(proj_root, ".github", "workflows", "ci.yml")
        checks[f"{keyprefix}ci_exists"] = file_exists(ci_path)

        # Docker
        dockerfile_path = path_join(proj_root, "Dockerfile")
        dockercompose_path = path_join(proj_root, "docker-compose.yml")
        dockerignore_path = path_join(proj_root, ".dockerignore")

        if docker_enabled:
            present = file_exists(dockerfile_path) and file_exists(dockercompose_path) and file_exists(dockerignore_path)
            checks[f"{keyprefix}docker_presence_correct"] = present
            hint_ok = False
            if present:
                hint_ok = dockerfile_lang_hint_ok(read_text(dockerfile_path), lang)
            checks[f"{keyprefix}dockerfile_lang_hint"] = hint_ok
        else:
            absent = (not file_exists(dockerfile_path)) and (not file_exists(dockercompose_path)) and (not file_exists(dockerignore_path))
            checks[f"{keyprefix}docker_presence_correct"] = absent
            # When absent, hint check is trivially True? No, it should not award. Keep False if no Dockerfile.
            checks[f"{keyprefix}dockerfile_lang_hint"] = False

        # Language-specific structures
        if lang == "python":
            modname = project_module_name(name)
            py_checks = {
                "pyproject": file_exists(path_join(proj_root, "pyproject.toml")),
                "requirements": file_exists(path_join(proj_root, "requirements.txt")),
                "requirements_dev": file_exists(path_join(proj_root, "requirements-dev.txt")),
                "setup_cfg": file_exists(path_join(proj_root, "setup.cfg")),
                "src_pkg_init": file_exists(path_join(proj_root, "src", modname, "__init__.py")),
                "src_pkg_main": file_exists(path_join(proj_root, "src", modname, "main.py")),
                "src_pkg_utils": file_exists(path_join(proj_root, "src", modname, "utils.py")),
                "test_main": file_exists(path_join(proj_root, "tests", "test_main.py")),
            }
            checks[f"{keyprefix}python_structure"] = all(py_checks.values())
        elif lang == "go":
            go_checks = {
                "go_mod": file_exists(path_join(proj_root, "go.mod")),
                "cmd_main": file_exists(path_join(proj_root, "cmd", name, "main.go")),
                "internal_app": file_exists(path_join(proj_root, "internal", "app", "app.go")),
                "pkg_utils": file_exists(path_join(proj_root, "pkg", "utils", "utils.go")),
                "makefile": file_exists(path_join(proj_root, "Makefile")),
            }
            checks[f"{keyprefix}go_structure"] = all(go_checks.values())
        elif lang == "rust":
            rust_checks = {
                "cargo_toml": file_exists(path_join(proj_root, "Cargo.toml")),
                "src_main": file_exists(path_join(proj_root, "src", "main.rs")),
                "src_lib": file_exists(path_join(proj_root, "src", "lib.rs")),
                "test_integration": file_exists(path_join(proj_root, "tests", "integration_test.rs")),
            }
            checks[f"{keyprefix}rust_structure"] = all(rust_checks.values())
        else:
            checks[f"{keyprefix}python_structure"] = False
            checks[f"{keyprefix}go_structure"] = False
            checks[f"{keyprefix}rust_structure"] = False

    # Attach baseline indicators to control reward
    checks["_output_present"] = output_present
    checks["_has_any_output_files"] = has_any_output_files
    return checks

def compute_reward(checks):
    # No-op baseline: if output missing or no files, reward is 0.0
    if not checks.get("_output_present") or not checks.get("_has_any_output_files"):
        return 0.0
    # Exclude internal baseline keys from scoring
    score_keys = [k for k in checks.keys() if not k.startswith("_")]
    if not score_keys:
        return 0.0
    passed = sum(1 for k in score_keys if checks[k])
    total = len(score_keys)
    if total == 0:
        return 0.0
    return round(passed / total, 6)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    projects_yaml_path = os.path.join(input_dir, "projects.yaml")
    text = read_text(projects_yaml_path)
    projects = parse_simple_yaml_projects(text)

    # Basic normalization: ensure keys are lowercased for some fields
    norm_projects = []
    for p in projects:
        np = dict(p)
        if "language" in np and isinstance(np["language"], str):
            np["language"] = np["language"].strip().lower()
        if "license" in np and isinstance(np["license"], str):
            np["license"] = np["license"].strip().lower()
        if "ci" in np and isinstance(np["ci"], str):
            np["ci"] = np["ci"].strip().lower()
        if "docker" in np and isinstance(np["docker"], str):
            np["docker"] = sanitize_bool(np["docker"])
        norm_projects.append(np)

    checks = build_checks(norm_projects, workspace_root)
    reward = compute_reward(checks)

    # Remove internal keys before output
    checks.pop("_output_present", None)
    checks.pop("_has_any_output_files", None)

    result = {"reward": reward}
    # Merge checks
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()