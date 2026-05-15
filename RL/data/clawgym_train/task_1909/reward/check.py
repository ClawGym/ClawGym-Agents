import json
import os
import sys
import ast

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def ast_walk_functions(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node

def is_agent_tool_decorator(dec):
    # Matches @agent.tool or @agent.tool()
    if isinstance(dec, ast.Attribute):
        return isinstance(dec.value, ast.Name) and dec.value.id == "agent" and dec.attr == "tool"
    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
        return isinstance(dec.func.value, ast.Name) and dec.func.value.id == "agent" and dec.func.attr == "tool"
    return False

def is_agent_tool_plain_decorator(dec):
    # Matches @agent.tool_plain or @agent.tool_plain()
    if isinstance(dec, ast.Attribute):
        return isinstance(dec.value, ast.Name) and dec.value.id == "agent" and dec.attr == "tool_plain"
    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
        return isinstance(dec.func.value, ast.Name) and dec.func.value.id == "agent" and dec.func.attr == "tool_plain"
    return False

def is_db_tools_tool_decorator(dec):
    # Matches @db_tools.tool or @db_tools.tool()
    if isinstance(dec, ast.Attribute):
        return isinstance(dec.value, ast.Name) and dec.value.id == "db_tools" and dec.attr == "tool"
    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
        return isinstance(dec.func.value, ast.Name) and dec.func.value.id == "db_tools" and dec.func.attr == "tool"
    return False

def annotation_contains_name(node, name):
    if node is None:
        return False
    # Recursively search the AST node for a given name
    if isinstance(node, ast.Name):
        return node.id == name
    if isinstance(node, ast.Attribute):
        # Could be something like pydantic_ai.RunContext
        return node.attr == name or annotation_contains_name(node.value, name)
    if isinstance(node, ast.Subscript):
        return annotation_contains_name(node.value, name) or annotation_contains_name(node.slice, name)
    if isinstance(node, ast.Index):  # py<3.9
        return annotation_contains_name(node.value, name)
    if isinstance(node, ast.Tuple):
        return any(annotation_contains_name(elt, name) for elt in node.elts)
    if isinstance(node, ast.List):
        return any(annotation_contains_name(elt, name) for elt in node.elts)
    if isinstance(node, ast.Constant):
        return False
    for child in ast.iter_child_nodes(node):
        if annotation_contains_name(child, name):
            return True
    return False

def has_return_annotation_name(node, names):
    ann = getattr(node, "returns", None)
    if ann is None:
        return False
    for nm in names:
        if annotation_contains_name(ann, nm):
            return True
    return False

def function_returns_literal_dict_or_str(node):
    for sub in ast.walk(node):
        if isinstance(sub, ast.Return):
            val = sub.value
            if isinstance(val, ast.Dict):
                return True
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                return True
    return False

def find_agent_constructor(tree):
    # Find assignment like: agent = Agent(...), capture the Call node and keywords
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            # Left-hand contains name 'agent'
            targets = node.targets
            for t in targets:
                if isinstance(t, ast.Name) and t.id == "agent":
                    # Check value is a call to Agent
                    val = node.value
                    if isinstance(val, ast.Call):
                        # If Agent(...) or something.Agent(...)
                        func = val.func
                        if (isinstance(func, ast.Name) and func.id == "Agent") or (isinstance(func, ast.Attribute) and func.attr == "Agent"):
                            return val
    return None

def get_function_source_segment(source, node):
    try:
        return ast.get_source_segment(source, node)
    except Exception:
        # Fallback using line numbers
        try:
            lines = source.splitlines()
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None)
            if start is not None and end is not None and 1 <= start <= len(lines) and 1 <= end <= len(lines):
                return "\n".join(lines[start-1:end])
        except Exception:
            pass
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_agent_tools_py": False,
        "has_readme": False,
        "agent_constructed_with_prepare_tools": False,
        "has_agent_tool_with_ctx_and_doc": False,
        "has_tool_plain_without_ctx_and_doc": False,
        "has_async_and_sync_tools": False,
        "has_explicit_return_or_literal": False,
        "has_prepare_tools_with_filter": False,
        "has_function_toolset_instantiation": False,
        "has_two_toolset_tools": False,
        "uses_combined_or_toolsets_in_agent": False,
        "readme_mentions_tool_decorators_and_runcontext": False,
        "readme_mentions_docstrings": False,
        "readme_mentions_toolsets": False,
    }

    agent_tools_path = os.path.join(output_dir, "agent_tools.py")
    readme_path = os.path.join(output_dir, "README.md")

    # Existence checks
    if os.path.isfile(agent_tools_path):
        checks["has_agent_tools_py"] = True
    if os.path.isfile(readme_path):
        checks["has_readme"] = True

    source = None
    tree = None
    if checks["has_agent_tools_py"]:
        source = read_file_text(agent_tools_path)
        try:
            tree = ast.parse(source or "")
        except Exception:
            tree = None

    # Analyze agent construction
    if tree is not None:
        agent_call = find_agent_constructor(tree)
        if agent_call is not None:
            # Check for prepare_tools keyword referencing prepare_tools
            for kw in agent_call.keywords:
                if kw.arg == "prepare_tools":
                    # Accept any reference to prepare_tools, e.g., Name('prepare_tools')
                    if isinstance(kw.value, ast.Name) and kw.value.id == "prepare_tools":
                        checks["agent_constructed_with_prepare_tools"] = True
                    else:
                        # Could still be a Name attribute; leniently accept if source mentions "prepare_tools="
                        if source and "prepare_tools=" in source:
                            checks["agent_constructed_with_prepare_tools"] = True
            # Also check if toolsets keyword exists for another check
            for kw in agent_call.keywords:
                if kw.arg == "toolsets":
                    checks["uses_combined_or_toolsets_in_agent"] = True

    # Analyze tools and prepare_tools function
    if tree is not None and source is not None:
        tool_functions = []
        tool_plain_functions = []
        tool_funcs_any = []

        has_async = False
        has_sync = False

        # Identify decorated tool functions
        for fn in ast_walk_functions(tree):
            # Identify decorations
            has_tool_dec = any(is_agent_tool_decorator(d) for d in fn.decorator_list)
            has_tool_plain_dec = any(is_agent_tool_plain_decorator(d) for d in fn.decorator_list)
            has_db_tools_dec = any(is_db_tools_tool_decorator(d) for d in fn.decorator_list)

            if has_tool_dec:
                tool_functions.append(fn)
                tool_funcs_any.append(fn)
            if has_tool_plain_dec:
                tool_plain_functions.append(fn)
                tool_funcs_any.append(fn)

            if isinstance(fn, ast.AsyncFunctionDef) and (has_tool_dec or has_tool_plain_dec):
                has_async = True
            if isinstance(fn, ast.FunctionDef) and (has_tool_dec or has_tool_plain_dec):
                has_sync = True

        # Check @agent.tool function criteria
        ok_tool = False
        for fn in tool_functions:
            # First parameter named ctx
            if fn.args.args:
                first_arg = fn.args.args[0]
                if first_arg.arg == "ctx" and annotation_contains_name(first_arg.annotation, "RunContext"):
                    # Docstring contains "Args:"
                    doc = ast.get_docstring(fn) or ""
                    if "Args:" in doc:
                        ok_tool = True
                        break
        if ok_tool:
            checks["has_agent_tool_with_ctx_and_doc"] = True

        # Check @agent.tool_plain function criteria
        ok_plain = False
        for fn in tool_plain_functions:
            # No param named ctx and no annotation referencing RunContext
            no_ctx_name = all(a.arg != "ctx" for a in fn.args.args)
            no_runcontext_annotation = True
            for a in fn.args.args:
                if annotation_contains_name(a.annotation, "RunContext"):
                    no_runcontext_annotation = False
                    break
            # Docstring contains "Args:"
            doc = ast.get_docstring(fn) or ""
            has_args_doc = "Args:" in doc
            if no_ctx_name and no_runcontext_annotation and has_args_doc:
                ok_plain = True
                break
        if ok_plain:
            checks["has_tool_plain_without_ctx_and_doc"] = True

        # Async and sync among decorated tools
        if has_async and has_sync and (tool_functions or tool_plain_functions):
            checks["has_async_and_sync_tools"] = True

        # Return type explicit or literal among decorated tools
        has_explicit = False
        for fn in tool_funcs_any:
            if has_return_annotation_name(fn, {"dict", "str", "ToolReturn"}):
                has_explicit = True
                break
            if function_returns_literal_dict_or_str(fn):
                has_explicit = True
                break
        if has_explicit:
            checks["has_explicit_return_or_literal"] = True

        # Check prepare_tools function
        prep_ok = False
        for fn in ast_walk_functions(tree):
            if fn.name == "prepare_tools":
                # First param ctx annotated with RunContext
                if fn.args.args and fn.args.args[0].arg == "ctx" and annotation_contains_name(fn.args.args[0].annotation, "RunContext"):
                    # Second param tool_defs exists
                    if len(fn.args.args) >= 2 and fn.args.args[1].arg == "tool_defs":
                        seg = get_function_source_segment(source, fn) or ""
                        if ("admin_" in seg) and ("startswith" in seg) and ("user_role" in seg):
                            prep_ok = True
                            break
        if prep_ok:
            checks["has_prepare_tools_with_filter"] = True

        # Toolsets: FunctionToolset instantiation
        if "FunctionToolset(" in source:
            checks["has_function_toolset_instantiation"] = True

        # At least two functions decorated via @db_tools.tool
        db_tools_count = 0
        for fn in ast_walk_functions(tree):
            if any(is_db_tools_tool_decorator(d) for d in fn.decorator_list):
                db_tools_count += 1
        if db_tools_count >= 2:
            checks["has_two_toolset_tools"] = True

        # CombinedToolset used or Agent constructed with toolsets kw (already partially set)
        if "CombinedToolset(" in source or checks["uses_combined_or_toolsets_in_agent"]:
            checks["uses_combined_or_toolsets_in_agent"] = True

    # README checks
    if checks["has_readme"]:
        readme_text = read_file_text(readme_path) or ""
        if ("@agent.tool" in readme_text) and ("@agent.tool_plain" in readme_text) and ("RunContext" in readme_text):
            checks["readme_mentions_tool_decorators_and_runcontext"] = True
        if ("Google-style docstrings" in readme_text) or ("Args:" in readme_text):
            checks["readme_mentions_docstrings"] = True
        if ("FunctionToolset" in readme_text) and (("CombinedToolset" in readme_text) or ("toolsets" in readme_text)):
            checks["readme_mentions_toolsets"] = True

    # Compute reward: all checks must pass
    all_pass = all(checks.values())
    reward = 1.0 if all_pass else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()