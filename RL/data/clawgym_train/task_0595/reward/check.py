import json
import os
import sys
import re
from typing import Any, Dict, List, Set

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def lines_head(text: str, n: int) -> List[str]:
    return text.splitlines()[:n]

def has_header_line(text: str) -> bool:
    for line in text.splitlines():
        if re.match(r"^\s*#{1,6}\s+\S+", line):
            return True
    return False

def first_header_line(text: str) -> str:
    for line in text.splitlines():
        if re.match(r"^\s*#{1,6}\s+\S+", line):
            return line.strip()
    return ""

def extract_table_names(db_json: Any) -> Set[str]:
    names: Set[str] = set()
    if db_json is None:
        return names
    # Common shapes:
    # 1) {"tables":[{"name":"users",...},{"name":"tasks",...}]}
    if isinstance(db_json, dict):
        if "tables" in db_json:
            tables = db_json.get("tables")
            if isinstance(tables, dict):
                # dictionary mapping
                for k in tables.keys():
                    if isinstance(k, str):
                        names.add(k)
                return names
            if isinstance(tables, list):
                for item in tables:
                    if isinstance(item, dict):
                        n = item.get("name")
                        if isinstance(n, str):
                            names.add(n)
                    elif isinstance(item, str):
                        names.add(item)
        else:
            # Maybe top-level keys are tables
            for k, v in db_json.items():
                # Heuristic: if value looks like schema for a table, record key name
                if isinstance(k, str) and (isinstance(v, dict) or isinstance(v, list)):
                    names.add(k)
    elif isinstance(db_json, list):
        # List of table dicts or names
        for item in db_json:
            if isinstance(item, dict):
                n = item.get("name")
                if isinstance(n, str):
                    names.add(n)
            elif isinstance(item, str):
                names.add(item)
    return names

def flatten_strings(obj: Any) -> List[str]:
    # Extract all string values from a nested structure
    out: List[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                # keys can also contain signatures in odd shapes, but mostly values matter
                pass
            out.extend(flatten_strings(v))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(flatten_strings(item))
    return out

def extract_signatures(apis_json: Any) -> List[str]:
    # Collect strings that look like function signatures: contain "(" and ")" and either ":" or "->"
    sigs: List[str] = []
    if apis_json is None:
        return sigs
    for s in flatten_strings(apis_json):
        if not isinstance(s, str):
            continue
        st = s.strip()
        if "(" in st and ")" in st and (":" in st or "->" in st):
            # Avoid extremely short tokens
            if len(st) >= 5:
                sigs.append(st)
    # Deduplicate, preserve order
    seen = set()
    unique = []
    for s in sigs:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique

def description_length_nonws(desc: str) -> int:
    return len(re.sub(r"\s+", "", desc))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # File paths
    agents_path = os.path.join(output_dir, "AGENTS.md")
    llms_path = os.path.join(output_dir, "llms.txt")
    llms_full_path = os.path.join(output_dir, "llms-full.txt")
    auth_md_path = os.path.join(output_dir, "docs", "auth.md")
    db_md_path = os.path.join(output_dir, "docs", "database.md")
    ops_md_path = os.path.join(output_dir, "docs", "operations.md")

    # Inputs
    commands_json_path = os.path.join(input_dir, "commands.json")
    apis_json_path = os.path.join(input_dir, "apis.json")
    db_schema_json_path = os.path.join(input_dir, "db_schema.json")

    checks: Dict[str, bool] = {
        # Existence
        "exists_agents_md": False,
        "exists_llms_txt": False,
        "exists_llms_full_txt": False,
        "exists_auth_md": False,
        "exists_database_md": False,
        "exists_operations_md": False,
        # AGENTS.md checks
        "agents_critical_section_top": False,
        "agents_bullet_no_secrets": False,
        "agents_bullet_use_app_only": False,
        "agents_bullet_do_not_use_pages": False,
        "agents_bullet_no_direct_db_client": False,
        "agents_bullet_external_browsing_allowlist": False,
        "agents_build_cmd_front": False,
        "agents_test_cmd_front": False,
        "agents_lint_cmd_front": False,
        "agents_docs_index_present": False,
        "agents_link_auth": False,
        "agents_link_database": False,
        "agents_link_operations": False,
        "agents_negative_constraint_gssp": False,
        "agents_negative_constraint_no_thirdparty_paste": False,
        "agents_has_api_signature": False,
        "agents_length_ok": False,
        # llms.txt checks
        "llms_auth_line_ok": False,
        "llms_database_line_ok": False,
        "llms_operations_line_ok": False,
        # Reference docs checks
        "auth_has_header": False,
        "auth_prereq_top": False,
        "auth_has_server_and_client": False,
        "db_has_header": False,
        "db_prereq_top": False,
        "db_mentions_table": False,
        "db_mentions_client_components": False,
        "ops_has_header": False,
        "ops_prereq_top": False,
        "ops_has_severity_tokens": False,
        # llms-full concat checks
        "llms_full_contains_auth_header_from_doc": False,
        "llms_full_contains_db_header_from_doc": False,
        "llms_full_contains_ops_header_from_doc": False,
    }

    try:
        # Existence
        if os.path.isfile(agents_path):
            checks["exists_agents_md"] = True
        if os.path.isfile(llms_path):
            checks["exists_llms_txt"] = True
        if os.path.isfile(llms_full_path):
            checks["exists_llms_full_txt"] = True
        if os.path.isfile(auth_md_path):
            checks["exists_auth_md"] = True
        if os.path.isfile(db_md_path):
            checks["exists_database_md"] = True
        if os.path.isfile(ops_md_path):
            checks["exists_operations_md"] = True

        # AGENTS.md validations
        if checks["exists_agents_md"]:
            agents_txt = read_text(agents_path)
            agents_lines = agents_txt.splitlines()
            top30 = "\n".join(lines_head(agents_txt, 30))
            top60 = "\n".join(lines_head(agents_txt, 60))

            # Critical section mention within first 30 lines
            if "CRITICAL" in top30:
                checks["agents_critical_section_top"] = True

            # Bullets (anywhere in the file)
            bullets = {
                "agents_bullet_no_secrets": "NO SECRETS in output",
                "agents_bullet_use_app_only": "Use app/ directory ONLY",
                "agents_bullet_do_not_use_pages": "Do NOT use pages/ directory",
                "agents_bullet_no_direct_db_client": "NO direct database queries in Client Components",
                "agents_bullet_external_browsing_allowlist": "External browsing requires allow-list approval",
            }
            for k, phrase in bullets.items():
                if phrase in agents_txt:
                    checks[k] = True

            # Build/Test/Lint commands in first 60 lines
            commands_json = read_json(commands_json_path)
            if isinstance(commands_json, dict):
                build_cmd = commands_json.get("build")
                test_cmd = commands_json.get("test")
                lint_cmd = commands_json.get("lint")
                if isinstance(build_cmd, str) and build_cmd in top60:
                    checks["agents_build_cmd_front"] = True
                if isinstance(test_cmd, str) and test_cmd in top60:
                    checks["agents_test_cmd_front"] = True
                if isinstance(lint_cmd, str) and lint_cmd in top60:
                    checks["agents_lint_cmd_front"] = True

            # DOCS INDEX phrase
            if "DOCS INDEX" in agents_txt:
                checks["agents_docs_index_present"] = True

            # Paths listed
            if "output/docs/auth.md" in agents_txt:
                checks["agents_link_auth"] = True
            if "output/docs/database.md" in agents_txt:
                checks["agents_link_database"] = True
            if "output/docs/operations.md" in agents_txt:
                checks["agents_link_operations"] = True

            # Negative constraints
            if "Do NOT use getServerSideProps" in agents_txt:
                checks["agents_negative_constraint_gssp"] = True
            if "Do NOT paste full code blocks from third-party docs" in agents_txt:
                checks["agents_negative_constraint_no_thirdparty_paste"] = True

            # API signatures
            apis_json = read_json(apis_json_path)
            sigs = extract_signatures(apis_json)
            if sigs:
                for sig in sigs:
                    if sig in agents_txt:
                        checks["agents_has_api_signature"] = True
                        break

            # Length guard
            if len(agents_txt) <= 17000:
                checks["agents_length_ok"] = True

        # llms.txt checks
        if checks["exists_llms_txt"]:
            llms_txt = read_text(llms_path)
            lines = llms_txt.splitlines()

            def line_ok_for_path(path_rel: str) -> bool:
                # Pattern: - [Title](relative-path): description (>=10 non-whitespace chars)
                pattern = re.compile(r"^\s*-\s*\[(?P<title>[^\]]+)\]\(" + re.escape(path_rel) + r"\)\s*:\s*(?P<desc>.+)$")
                for ln in lines:
                    m = pattern.match(ln)
                    if m:
                        desc = m.group("desc")
                        if description_length_nonws(desc) >= 10:
                            return True
                return False

            if line_ok_for_path("output/docs/auth.md"):
                checks["llms_auth_line_ok"] = True
            if line_ok_for_path("output/docs/database.md"):
                checks["llms_database_line_ok"] = True
            if line_ok_for_path("output/docs/operations.md"):
                checks["llms_operations_line_ok"] = True

        # Reference docs
        # auth.md
        if checks["exists_auth_md"]:
            auth_txt = read_text(auth_md_path)
            if has_header_line(auth_txt):
                checks["auth_has_header"] = True
            if any(line.strip().startswith("Prerequisites:") for line in lines_head(auth_txt, 30)):
                checks["auth_prereq_top"] = True
            lower_auth = auth_txt.lower()
            if ("server" in lower_auth) and ("client" in lower_auth):
                checks["auth_has_server_and_client"] = True

        # database.md
        if checks["exists_database_md"]:
            db_txt = read_text(db_md_path)
            if has_header_line(db_txt):
                checks["db_has_header"] = True
            if any(line.strip().startswith("Prerequisites:") for line in lines_head(db_txt, 30)):
                checks["db_prereq_top"] = True
            # mentions one table
            db_schema_json = read_json(db_schema_json_path)
            table_names = extract_table_names(db_schema_json)
            for name in table_names:
                if name and name in db_txt:
                    checks["db_mentions_table"] = True
                    break
            if "client components" in db_txt.lower():
                checks["db_mentions_client_components"] = True

        # operations.md
        if checks["exists_operations_md"]:
            ops_txt = read_text(ops_md_path)
            if has_header_line(ops_txt):
                checks["ops_has_header"] = True
            if any(line.strip().startswith("Prerequisites:") for line in lines_head(ops_txt, 30)):
                checks["ops_prereq_top"] = True
            if all(tok in ops_txt for tok in ["SEV1", "SEV2", "SEV3", "SEV4"]):
                checks["ops_has_severity_tokens"] = True

        # llms-full concatenation checks
        if checks["exists_llms_full_txt"]:
            full_txt = read_text(llms_full_path)
            # Extract first header from each doc and verify presence in full
            if checks["exists_auth_md"]:
                auth_header = first_header_line(read_text(auth_md_path))
                if auth_header and auth_header in full_txt:
                    checks["llms_full_contains_auth_header_from_doc"] = True
            if checks["exists_database_md"]:
                db_header = first_header_line(read_text(db_md_path))
                if db_header and db_header in full_txt:
                    checks["llms_full_contains_db_header_from_doc"] = True
            if checks["exists_operations_md"]:
                ops_header = first_header_line(read_text(ops_md_path))
                if ops_header and ops_header in full_txt:
                    checks["llms_full_contains_ops_header_from_doc"] = True

        # Compute reward as fraction of passed checks
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = 0.0
        if total > 0:
            reward = passed / total

        # Explicitly ensure no-op baseline results in 0.0
        # If output dir missing or none of the existence checks passed, reward should be 0.0
        if not any([checks["exists_agents_md"], checks["exists_llms_txt"], checks["exists_llms_full_txt"],
                    checks["exists_auth_md"], checks["exists_database_md"], checks["exists_operations_md"]]):
            reward = 0.0

        result = {"reward": reward}
        result.update(checks)
        print(json.dumps(result))
    except Exception:
        # On unexpected error, output zero reward and keep all checks as False
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))

if __name__ == "__main__":
    main()