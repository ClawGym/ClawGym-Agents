import json
import os
import re
import sys
import ast

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_true_value(v):
    if isinstance(v, bool):
        return v is True
    if isinstance(v, str):
        return v.strip().lower() in {"true", "yes", "1"}
    return False

def count_frequently_changing_integrations(obj):
    count = 0
    if isinstance(obj, dict):
        if "changes_frequently" in obj and is_true_value(obj["changes_frequently"]):
            count += 1
        for v in obj.values():
            count += count_frequently_changing_integrations(v)
    elif isinstance(obj, list):
        for item in obj:
            count += count_frequently_changing_integrations(item)
    return count

def find_section(content, section_name):
    # Return section text between a header matching section_name and the next header
    lines = content.splitlines()
    headers = []
    header_re = re.compile(r'^\s{0,3}#{1,6}\s*(.+?)\s*$')
    for idx, line in enumerate(lines):
        m = header_re.match(line)
        if m:
            headers.append((idx, m.group(1).strip().lower()))
    # find target header
    target_idx = None
    for i, (line_no, title) in enumerate(headers):
        if title == section_name.lower():
            target_idx = i
            break
    if target_idx is None:
        # try contains (e.g., "Architecture Decision")
        for i, (line_no, title) in enumerate(headers):
            if section_name.lower() in title:
                target_idx = i
                break
    if target_idx is None:
        return None
    start_line = headers[target_idx][0] + 1
    end_line = len(lines)
    if target_idx + 1 < len(headers):
        end_line = headers[target_idx + 1][0]
    return "\n".join(lines[start_line:end_line]).strip()

def has_header(content, name):
    # Case-insensitive heading match for the given section name
    pattern = re.compile(r'^\s{0,3}#{1,6}\s*' + re.escape(name) + r'\b', re.IGNORECASE | re.MULTILINE)
    return bool(pattern.search(content))

def parse_port_classes(py_content):
    result = {
        "class_names": set(),
        "class_has_abstractmethod": {},
        "class_inherits_abc": {},
    }
    try:
        tree = ast.parse(py_content)
    except Exception:
        return result
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            name = node.name
            if name.endswith("Port"):
                result["class_names"].add(name)
                # Check base classes for ABC
                inherits_abc = False
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "ABC":
                        inherits_abc = True
                    elif isinstance(base, ast.Attribute) and base.attr == "ABC":
                        inherits_abc = True
                result["class_inherits_abc"][name] = inherits_abc
                # Check for @abstractmethod on at least one method
                has_abs = False
                for b in node.body:
                    if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for dec in b.decorator_list:
                            if isinstance(dec, ast.Name) and dec.id == "abstractmethod":
                                has_abs = True
                            elif isinstance(dec, ast.Attribute) and dec.attr == "abstractmethod":
                                has_abs = True
                result["class_has_abstractmethod"][name] = has_abs
    return result

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        # ADR checks
        "adr_exists": False,
        "adr_has_context_section": False,
        "adr_has_options_section": False,
        "adr_has_decision_section": False,
        "adr_has_consequences_section": False,
        "adr_mentions_pattern": False,
        "adr_hexagonal_choice_correct_if_required": False,

        # directory.json checks
        "directory_exists": False,
        "directory_valid_json": False,
        "directory_has_required_keys": False,
        "directory_ports_has_inbound_outbound_arrays": False,

        # ports.py checks
        "ports_py_exists": False,
        "ports_py_has_import_abc": False,
        "ports_py_has_three_port_classes": False,
        "ports_py_each_port_has_abstractmethod": False,
        "ports_py_inbound_names_match_directory": False,
        "ports_py_outbound_names_match_directory": False,

        # diagram checks
        "diagram_exists": False,
        "diagram_has_keywords": False,

        # test plan checks
        "test_plan_exists": False,
        "test_plan_mentions_mock_and_adapter": False,

        # readme checks
        "readme_exists": False,
        "readme_has_dependency_rule": False,
        "readme_mentions_ports_and_adapters": False,
    }

    # Paths
    adr_path = os.path.join(output_dir, "architecture", "adr", "001-architecture-decision.md")
    directory_json_path = os.path.join(output_dir, "architecture", "directory.json")
    ports_py_path = os.path.join(output_dir, "architecture", "ports.py")
    diagram_path = os.path.join(output_dir, "architecture", "diagram.txt")
    test_plan_path = os.path.join(output_dir, "architecture", "test_plan.md")
    readme_path = os.path.join(output_dir, "architecture", "readme.md")

    # Input for integrations rule
    integrations_json_path = os.path.join(input_dir, "integrations.json")

    # Evaluate ADR
    adr_content = read_text(adr_path)
    if adr_content is not None:
        checks["adr_exists"] = True
        # section headers presence
        if has_header(adr_content, "Context"):
            checks["adr_has_context_section"] = True
        if has_header(adr_content, "Options Considered"):
            checks["adr_has_options_section"] = True
        if has_header(adr_content, "Decision"):
            checks["adr_has_decision_section"] = True
        if has_header(adr_content, "Consequences"):
            checks["adr_has_consequences_section"] = True

        # mentions one of the patterns
        lower = adr_content.lower()
        if ("hexagonal" in lower) or ("clean architecture" in lower) or ("domain-driven design" in lower) or re.search(r'\bddd\b', lower):
            checks["adr_mentions_pattern"] = True

        # Hexagonal correctness if 3+ frequently changing integrations
        integrations = load_json(integrations_json_path)
        freq_count = count_frequently_changing_integrations(integrations) if integrations is not None else 0
        if freq_count >= 3:
            # require Decision section to include "Hexagonal"
            decision_section = find_section(adr_content, "Decision")
            if decision_section is None:
                # fallback to any mention in whole ADR if Decision not parsed
                checks["adr_hexagonal_choice_correct_if_required"] = "hexagonal" in lower
            else:
                checks["adr_hexagonal_choice_correct_if_required"] = ("hexagonal" in decision_section.lower())
        else:
            # Not required; passing this check if ADR exists (neutral-to-pass to avoid penalizing)
            # But to keep it strictly tied to output, we set True only if ADR exists
            checks["adr_hexagonal_choice_correct_if_required"] = checks["adr_exists"]

    # Evaluate directory.json
    dir_json = load_json(directory_json_path)
    if dir_json is not None:
        checks["directory_exists"] = True
        checks["directory_valid_json"] = True
        # required top-level keys
        required_keys = {"domain", "ports", "adapters", "infrastructure"}
        if all(k in dir_json for k in required_keys):
            checks["directory_has_required_keys"] = True
            ports_obj = dir_json.get("ports", {})
            if isinstance(ports_obj, dict):
                inbound = ports_obj.get("inbound", None)
                outbound = ports_obj.get("outbound", None)
                if isinstance(inbound, list) and isinstance(outbound, list):
                    checks["directory_ports_has_inbound_outbound_arrays"] = True
        # If JSON parsed but missing required keys, still considered exists/valid_json

    # Evaluate ports.py
    ports_content = read_text(ports_py_path)
    class_info = None
    if ports_content is not None:
        checks["ports_py_exists"] = True
        if "from abc import ABC, abstractmethod" in ports_content.replace("  ", " "):
            checks["ports_py_has_import_abc"] = True
        # Parse class definitions
        class_info = parse_port_classes(ports_content)
        class_names = class_info["class_names"]
        if len(class_names) >= 3:
            checks["ports_py_has_three_port_classes"] = True
            # Ensure each class has at least one @abstractmethod
            if all(class_info["class_has_abstractmethod"].get(cn, False) for cn in class_names):
                checks["ports_py_each_port_has_abstractmethod"] = True

        # Cross-check with directory.json inbound/outbound names
        if dir_json is not None and isinstance(dir_json.get("ports", {}), dict):
            inbound_list = dir_json["ports"].get("inbound", [])
            outbound_list = dir_json["ports"].get("outbound", [])
            if isinstance(inbound_list, list) and isinstance(outbound_list, list):
                inbound_matches = [name for name in inbound_list if isinstance(name, str) and name in class_names]
                outbound_matches = [name for name in outbound_list if isinstance(name, str) and name in class_names]
                # require at least one inbound class defined
                if len(inbound_matches) >= 1:
                    checks["ports_py_inbound_names_match_directory"] = True
                # require at least two outbound classes defined
                if len(outbound_matches) >= 2:
                    checks["ports_py_outbound_names_match_directory"] = True

    # Evaluate diagram
    diagram_content = read_text(diagram_path)
    if diagram_content is not None:
        checks["diagram_exists"] = True
        low = diagram_content.lower()
        if ("ports" in low) and ("adapters" in low):
            checks["diagram_has_keywords"] = True

    # Evaluate test plan
    test_plan_content = read_text(test_plan_path)
    if test_plan_content is not None:
        checks["test_plan_exists"] = True
        low = test_plan_content.lower()
        if ("mock" in low) and ("adapter" in low):
            checks["test_plan_mentions_mock_and_adapter"] = True

    # Evaluate readme
    readme_content = read_text(readme_path)
    if readme_content is not None:
        checks["readme_exists"] = True
        if "Dependency Rule" in readme_content:
            checks["readme_has_dependency_rule"] = True
        low = readme_content.lower()
        if ("ports" in low) and ("adapters" in low):
            checks["readme_mentions_ports_and_adapters"] = True

    # Compute reward: fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
        # Clamp to [0,1]
        reward = max(0.0, min(1.0, reward))

    # Print single JSON line
    output = {"reward": reward}
    output.update(checks)
    print(json.dumps(output))

if __name__ == "__main__":
    main()