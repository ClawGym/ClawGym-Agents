import json
import os
import re
import sys
from collections import Counter, defaultdict

def load_spec(spec_path):
    try:
        with open(spec_path, "r", encoding="utf-8") as f:
            spec = json.load(f)
        if not isinstance(spec, dict):
            return None
        return spec
    except Exception:
        return None

def encode_newlines(s):
    # Normalize to \n then encode as literal \n sequences
    if s is None:
        return ""
    # Replace Windows newlines first just in case
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s.replace("\n", "\\n")

def build_expected(spec):
    vault = spec.get("vault", "")
    notes = spec.get("notes", [])
    creates = []
    moves = []
    properties = []
    appends = []
    bullets = []
    operations = []
    for note in notes:
        name = note.get("name", "")
        initial_content = note.get("initial_content", "")
        move_to_path = note.get("move_to_path", "")
        props = note.get("properties", []) or []
        app_list = note.get("appends", []) or []

        enc_initial = encode_newlines(initial_content)
        creates.append((name, enc_initial))
        moves.append((name, move_to_path))
        bullets.append(f"- create: {name}")
        bullets.append(f"- move: {name} -> {move_to_path}")
        operations.append({"command": "create", "args": {"name": name, "content": enc_initial}})
        operations.append({"command": "move", "args": {"file": name, "to": move_to_path}})

        for p in props:
            pname = p.get("name", "")
            pval = p.get("value", "")
            properties.append((pname, pval, name))
            bullets.append(f"- property:set: {pname}={pval} on {name}")
            operations.append({"command": "property:set", "args": {"name": pname, "value": pval, "file": name}})

        for a in app_list:
            enc_append = encode_newlines(a)
            appends.append((name, enc_append))
            bullets.append(f"- append: '{enc_append}' into {name}")
            operations.append({"command": "append", "args": {"file": name, "content": enc_append}})

    expected_total = len(creates) + len(moves) + len(properties) + len(appends)
    return {
        "vault": vault,
        "creates": creates,
        "moves": moves,
        "properties": properties,
        "appends": appends,
        "bullets": bullets,
        "operations": operations,
        "expected_total": expected_total,
    }

def parse_commands_file(path, vault):
    # Returns parsed data and validation flags
    result = {
        "lines": [],
        "prefix_ok": True,
        "only_allowed_commands": True,
        "parsed_creates": [],
        "parsed_moves": [],
        "parsed_properties": [],
        "parsed_appends": [],
        "all_lines_parsed": True,
        "non_empty": False,
    }
    if not os.path.isfile(path):
        return result

    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    # Split lines, ignore completely empty lines
    lines = [ln for ln in raw.splitlines() if ln.strip() != ""]
    result["non_empty"] = len(lines) > 0
    result["lines"] = lines

    prefix = f'obsidian vault="{vault}"'
    # Patterns for exact param orders
    patterns = {
        "create": re.compile(r'^create\s+name="(?P<name>[^"]+)"\s+content="(?P<content>.*)"$'),
        "move": re.compile(r'^move\s+file="(?P<file>[^"]+)"\s+to="(?P<to>[^"]+)"$'),
        "property:set": re.compile(r'^property:set\s+name="(?P<name>[^"]+)"\s+value="(?P<value>[^"]+)"\s+file="(?P<file>[^"]+)"$'),
        "append": re.compile(r'^append\s+file="(?P<file>[^"]+)"\s+content="(?P<content>.*)"$'),
    }
    allowed_cmds = set(patterns.keys())

    for line in lines:
        if not line.startswith(prefix):
            result["prefix_ok"] = False
            # still try to parse to catch other issues but mark failure
        # Rest of the command after prefix
        rest = line[len(prefix):].lstrip()
        if not rest:
            # No command present
            result["all_lines_parsed"] = False
            continue

        matched = False
        for cmd, pat in patterns.items():
            m = pat.match(rest)
            if m:
                matched = True
                if cmd == "create":
                    result["parsed_creates"].append((m.group("name"), m.group("content")))
                elif cmd == "move":
                    result["parsed_moves"].append((m.group("file"), m.group("to")))
                elif cmd == "property:set":
                    result["parsed_properties"].append((m.group("name"), m.group("value"), m.group("file")))
                elif cmd == "append":
                    result["parsed_appends"].append((m.group("file"), m.group("content")))
                break
        if not matched:
            # Determine if the command token is disallowed
            token = rest.split()[0] if rest.split() else ""
            if token not in allowed_cmds:
                result["only_allowed_commands"] = False
            result["all_lines_parsed"] = False

    return result

def compare_multiset(expected_list, parsed_list):
    # Multiset comparison using tuple items
    return Counter(expected_list) == Counter(parsed_list)

def validate_plan(plan_path, expected_bullets):
    res = {
        "exists": False,
        "heading_ok": False,
        "bullets_exact_match": False,
        "no_extra_nonempty_lines": False,
    }
    if not os.path.isfile(plan_path):
        return res
    res["exists"] = True
    with open(plan_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    if not lines:
        return res
    # First line must be exactly "Execution Plan"
    res["heading_ok"] = lines[0] == "Execution Plan"
    # Collect bullet lines (start with "- ")
    bullets = [ln for ln in lines[1:] if ln.strip().startswith("- ")]
    # Check exact set and count
    res["bullets_exact_match"] = Counter(bullets) == Counter(expected_bullets)
    # Ensure there are no other non-empty lines besides heading and bullets
    others = [ln for ln in lines[1:] if ln.strip() != "" and not ln.strip().startswith("- ")]
    res["no_extra_nonempty_lines"] = len(others) == 0
    return res

def validate_manifest(manifest_path, expected):
    res = {
        "exists": False,
        "valid_json": False,
        "vault_match": False,
        "operations_count_match": False,
        "operations_match": False,
        "only_allowed_commands": False,
    }
    if not os.path.isfile(manifest_path):
        return res
    res["exists"] = True
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        res["valid_json"] = isinstance(data, dict)
        if not res["valid_json"]:
            return res
    except Exception:
        return res

    vault = data.get("vault")
    ops = data.get("operations")
    res["vault_match"] = (vault == expected["vault"])
    if not isinstance(ops, list):
        return res

    res["operations_count_match"] = (len(ops) == expected["expected_total"])

    allowed = {"create", "move", "property:set", "append"}
    res["only_allowed_commands"] = all(isinstance(op, dict) and op.get("command") in allowed for op in ops)

    observed = []
    for op in ops:
        cmd = op.get("command")
        args = op.get("args", {})
        if not isinstance(args, dict):
            continue
        if cmd == "create":
            name = args.get("name")
            content = args.get("content")
            observed.append(("create", name, content))
        elif cmd == "move":
            file_ = args.get("file")
            to = args.get("to")
            observed.append(("move", file_, to))
        elif cmd == "property:set":
            name = args.get("name")
            value = args.get("value")
            file_ = args.get("file")
            observed.append(("property:set", name, value, file_))
        elif cmd == "append":
            file_ = args.get("file")
            content = args.get("content")
            observed.append(("append", file_, content))
        else:
            # Disallowed commands handled by only_allowed_commands
            pass

    expected_ops = []
    for c_name, c_content in expected["creates"]:
        expected_ops.append(("create", c_name, c_content))
    for m_file, m_to in expected["moves"]:
        expected_ops.append(("move", m_file, m_to))
    for p_name, p_val, p_file in expected["properties"]:
        expected_ops.append(("property:set", p_name, p_val, p_file))
    for a_file, a_content in expected["appends"]:
        expected_ops.append(("append", a_file, a_content))

    res["operations_match"] = Counter(expected_ops) == Counter(observed)

    return res

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    spec_path = os.path.join(input_dir, "spec.json")
    commands_path = os.path.join(output_dir, "obsidian_commands.txt")
    plan_path = os.path.join(output_dir, "plan.md")
    manifest_path = os.path.join(output_dir, "manifest.json")

    checks = {
        "commands_file_exists": False,
        "commands_non_empty": False,
        "commands_prefix_ok": False,
        "commands_only_allowed": False,
        "commands_exact_count": False,
        "commands_create_match": False,
        "commands_move_match": False,
        "commands_property_match": False,
        "commands_append_match": False,
        "plan_exists": False,
        "plan_heading_ok": False,
        "plan_bullets_exact_match": False,
        "plan_no_extra_nonempty": False,
        "manifest_exists": False,
        "manifest_json_valid": False,
        "manifest_vault_match": False,
        "manifest_operations_count_match": False,
        "manifest_only_allowed": False,
        "manifest_operations_match": False,
    }

    spec = load_spec(spec_path)
    if not spec:
        # Without a valid spec, we cannot validate outputs; keep all checks false.
        reward = 0.0
        print(json.dumps({"reward": reward, **checks}))
        return

    expected = build_expected(spec)

    # Validate commands file
    if os.path.isfile(commands_path):
        checks["commands_file_exists"] = True
        parsed = parse_commands_file(commands_path, expected["vault"])
        checks["commands_non_empty"] = parsed["non_empty"]
        checks["commands_prefix_ok"] = parsed["prefix_ok"]
        checks["commands_only_allowed"] = parsed["only_allowed_commands"]
        # Compare counts
        if parsed["non_empty"]:
            total_lines = len(parsed["lines"])
            checks["commands_exact_count"] = (total_lines == expected["expected_total"])
            # Compare each action type as multisets
            checks["commands_create_match"] = compare_multiset(
                expected["creates"], parsed["parsed_creates"]
            )
            checks["commands_move_match"] = compare_multiset(
                expected["moves"], parsed["parsed_moves"]
            )
            checks["commands_property_match"] = compare_multiset(
                expected["properties"], parsed["parsed_properties"]
            )
            checks["commands_append_match"] = compare_multiset(
                expected["appends"], parsed["parsed_appends"]
            )

    # Validate plan
    plan_res = validate_plan(plan_path, expected["bullets"])
    checks["plan_exists"] = plan_res["exists"]
    checks["plan_heading_ok"] = plan_res["heading_ok"]
    checks["plan_bullets_exact_match"] = plan_res["bullets_exact_match"]
    checks["plan_no_extra_nonempty"] = plan_res["no_extra_nonempty_lines"]

    # Validate manifest
    man_res = validate_manifest(manifest_path, expected)
    checks["manifest_exists"] = man_res["exists"]
    checks["manifest_json_valid"] = man_res["valid_json"]
    checks["manifest_vault_match"] = man_res["vault_match"]
    checks["manifest_operations_count_match"] = man_res["operations_count_match"]
    checks["manifest_only_allowed"] = man_res["only_allowed_commands"]
    checks["manifest_operations_match"] = man_res["operations_match"]

    # Compute reward as fraction of passed checks, but enforce 0.0 if outputs missing/empty baseline
    # No-op baseline: if no commands, plan, and manifest, reward must be 0.0
    outputs_present = checks["commands_file_exists"] or checks["plan_exists"] or checks["manifest_exists"]
    passed = sum(1 for v in checks.values() if v is True)
    total = len(checks)
    reward = (passed / total) if outputs_present else 0.0

    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()