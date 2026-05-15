import os
import sys
import json
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_csv_rows(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            sample = f.read(2048)
            f.seek(0)
            # Try DictReader first
            try:
                sniffer = csv.Sniffer()
                dialect = sniffer.sniff(sample)
            except Exception:
                dialect = csv.excel
            reader = csv.DictReader(f, dialect=dialect)
            if reader.fieldnames:
                for row in reader:
                    # normalize keys lowercased
                    norm = { (k.lower() if isinstance(k,str) else k): v for k,v in row.items() }
                    rows.append(norm)
                return rows
            else:
                rows = []
        # Fallback: simple reader without headers
        with open(path, "r", encoding="utf-8") as f2:
            reader2 = csv.reader(f2)
            for r in reader2:
                if len(r) >= 3:
                    rows.append({"method": r[0], "path": r[1], "handler": r[2]})
        return rows
    except Exception:
        return rows

def flatten_strings(obj):
    found = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            found.extend(flatten_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(flatten_strings(v))
    return found

def parse_component_dependencies(dep):
    pairs = []
    if isinstance(dep, list):
        for item in dep:
            if isinstance(item, dict):
                frm = item.get("from") or item.get("source") or item.get("src") or item.get("a")
                to = item.get("to") or item.get("target") or item.get("dst") or item.get("b")
                if frm and to:
                    pairs.append((str(frm), str(to)))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                pairs.append((str(item[0]), str(item[1])))
            elif isinstance(item, str) and "->" in item:
                parts = item.split("->", 1)
                pairs.append((parts[0].strip(), parts[1].strip()))
    return pairs

def load_patterns_lines(path):
    content = read_text(path)
    lines = []
    for line in content.splitlines():
        s = line.strip()
        if s:
            lines.append(s)
    return lines

def ensure_all_substrings(container_text, substrings):
    for s in substrings:
        if s not in container_text:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    arch_path = os.path.join(output_dir, ".claude", "codemaps", "architecture.md")
    api_ep_path = os.path.join(output_dir, ".claude", "codemaps", "api-endpoints.md")
    comps_path = os.path.join(output_dir, ".claude", "codemaps", "components.md")
    data_flow_path = os.path.join(output_dir, ".claude", "codemaps", "data-flow.md")
    claude_md_path = os.path.join(output_dir, "CLAUDE.md")
    plan_path = os.path.join(output_dir, "plan.md")

    codebase_json_path = os.path.join(input_dir, "codebase.json")
    api_csv_path = os.path.join(input_dir, "api_endpoints.csv")
    patterns_txt_path = os.path.join(input_dir, "patterns.txt")
    commands_json_path = os.path.join(input_dir, "commands.json")

    checks = {
        "has_architecture_md": False,
        "has_api_endpoints_md": False,
        "has_components_md": False,
        "has_data_flow_md": False,
        "has_CLAUDE_md": False,
        "has_plan_md": False,

        "arch_entry_points_complete": False,
        "arch_core_modules_complete": False,
        "arch_key_files_complete": False,
        "arch_common_patterns_section": False,
        "arch_common_patterns_included": False,

        "api_endpoints_listed_all": False,
        "api_contains_API_and_Billing_words": False,

        "components_dependencies_complete": False,

        "data_flow_includes_notes": False,
        "data_flow_includes_required_terms": False,

        "claude_has_quick_start_and_refs": False,
        "claude_has_commands_section_and_required_cmds": False,
        "claude_has_session_strategy_and_clear": False,
        "claude_has_subagent_strategy": False,
        "claude_has_context_budget_rule": False,

        "plan_has_phases_and_auth_path": False
    }

    # Existence checks
    arch_exists = os.path.isfile(arch_path)
    api_ep_exists = os.path.isfile(api_ep_path)
    comps_exists = os.path.isfile(comps_path)
    data_flow_exists = os.path.isfile(data_flow_path)
    claude_exists = os.path.isfile(claude_md_path)
    plan_exists = os.path.isfile(plan_path)

    checks["has_architecture_md"] = arch_exists
    checks["has_api_endpoints_md"] = api_ep_exists
    checks["has_components_md"] = comps_exists
    checks["has_data_flow_md"] = data_flow_exists
    checks["has_CLAUDE_md"] = claude_exists
    checks["has_plan_md"] = plan_exists

    # Load inputs
    codebase = read_json(codebase_json_path) or {}
    entry_points = codebase.get("entryPoints", []) or []
    modules = codebase.get("modules", []) or []
    key_files = codebase.get("keyFiles", []) or []
    comp_deps_raw = codebase.get("componentDependencies", []) or []
    comp_deps = parse_component_dependencies(comp_deps_raw)
    data_flow_notes = codebase.get("dataFlowNotes", []) or []

    patterns_lines = load_patterns_lines(patterns_txt_path)
    commands_json = read_json(commands_json_path)
    commands_strings = flatten_strings(commands_json) if commands_json is not None else []

    # Architecture.md validations
    if arch_exists:
        arch_text = read_text(arch_path)

        # Entry Points present and listed
        if "Entry Points" in arch_text and all(str(ep) in arch_text for ep in entry_points):
            checks["arch_entry_points_complete"] = True

        # Core Modules section contains each module's name AND path
        core_modules_ok = "Core Modules" in arch_text
        if core_modules_ok:
            for m in modules:
                name = str(m.get("name", ""))
                path = str(m.get("path", ""))
                if not name or not path:
                    core_modules_ok = False
                    break
                if name not in arch_text or path not in arch_text:
                    core_modules_ok = False
                    break
        checks["arch_core_modules_complete"] = core_modules_ok

        # Key Files section items present
        key_files_ok = ("Key Files" in arch_text) or ("Key Files (Read These First)" in arch_text)
        if key_files_ok:
            for kf in key_files:
                if str(kf) not in arch_text:
                    key_files_ok = False
                    break
        checks["arch_key_files_complete"] = key_files_ok

        # Common Patterns section and inclusion
        checks["arch_common_patterns_section"] = ("Common Patterns" in arch_text)
        if patterns_lines:
            checks["arch_common_patterns_included"] = all((line in arch_text) for line in patterns_lines)
        else:
            # If no patterns provided, treat as not passed (avoid vacuous pass)
            checks["arch_common_patterns_included"] = False

    # api-endpoints.md validations
    if api_ep_exists:
        api_text = read_text(api_ep_path)

        # Parse CSV and ensure each Method, Path, Handler appears
        rows = read_csv_rows(api_csv_path)
        all_rows_ok = True
        if rows:
            for r in rows:
                # Normalize keys
                method = (r.get("Method") or r.get("method") or r.get("METHOD") or "").strip()
                path = (r.get("Path") or r.get("path") or r.get("PATH") or "").strip()
                handler = (r.get("Handler") or r.get("handler") or r.get("HANDLER") or "").strip()
                if not method and not path and not handler:
                    all_rows_ok = False
                    break
                if method and method not in api_text:
                    all_rows_ok = False
                    break
                if path and path not in api_text:
                    all_rows_ok = False
                    break
                if handler and handler not in api_text:
                    all_rows_ok = False
                    break
        else:
            all_rows_ok = False
        checks["api_endpoints_listed_all"] = all_rows_ok

        # Must include "API" and "Billing"
        checks["api_contains_API_and_Billing_words"] = ("API" in api_text and "Billing" in api_text)

    # components.md validations
    if comps_exists:
        comps_text = read_text(comps_path)
        if comp_deps:
            ok = True
            for frm, to in comp_deps:
                line = f"{frm} depends on {to}"
                if line not in comps_text:
                    ok = False
                    break
            checks["components_dependencies_complete"] = ok
        else:
            # If no dependencies provided, do not pass (avoid vacuous pass)
            checks["components_dependencies_complete"] = False

    # data-flow.md validations
    if data_flow_exists:
        df_text = read_text(data_flow_path)
        notes_ok = True if data_flow_notes else False
        if data_flow_notes:
            for note in data_flow_notes:
                if str(note) not in df_text:
                    notes_ok = False
                    break
        checks["data_flow_includes_notes"] = notes_ok
        checks["data_flow_includes_required_terms"] = ("HTTP Request" in df_text and "Stripe billing webhook" in df_text)

    # CLAUDE.md validations
    if claude_exists:
        ctext = read_text(claude_md_path)

        # Quick Start and references
        quick_ok = ("Codebase Quick Start" in ctext and
                    "@.claude/codemaps/architecture.md" in ctext and
                    "@.claude/codemaps/api-endpoints.md" in ctext)
        checks["claude_has_quick_start_and_refs"] = quick_ok

        # Commands section and required cmds if present
        commands_section = ("Commands" in ctext)
        require_dev = any("pnpm dev" in s for s in commands_strings)
        require_test = any("pnpm test" in s for s in commands_strings)
        cmds_ok = commands_section
        if require_dev and "pnpm dev" not in ctext:
            cmds_ok = False
        if require_test and "pnpm test" not in ctext:
            cmds_ok = False
        checks["claude_has_commands_section_and_required_cmds"] = cmds_ok

        # Session Strategy and /clear
        checks["claude_has_session_strategy_and_clear"] = ("Session Strategy: One Goal Per Session" in ctext and "/clear" in ctext)

        # Subagent Strategy
        checks["claude_has_subagent_strategy"] = ("Subagent Strategy" in ctext)

        # Context Budget Rule of Thumb
        checks["claude_has_context_budget_rule"] = ("Context Budget Rule of Thumb" in ctext)

    # plan.md validations
    if plan_exists:
        ptext = read_text(plan_path)
        phases_ok = all(h in ptext for h in ["Explore", "Plan", "Implement", "Commit"])
        auth_ok = "src/middleware/authV1.ts" in ptext
        checks["plan_has_phases_and_auth_path"] = (phases_ok and auth_ok)

    # Compute reward as fraction passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Enforce baseline: if no required outputs found, reward must be 0.0 (will be by fraction)
    reward = passed / total if total > 0 else 0.0
    # Clip to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()