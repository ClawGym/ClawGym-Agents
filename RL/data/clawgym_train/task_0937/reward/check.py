import os
import sys
import json
import ast
from typing import Dict, List, Optional, Tuple

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_ast(path: str) -> Optional[ast.AST]:
    try:
        src = read_text(path)
        if src is None:
            return None
        return ast.parse(src)
    except Exception:
        return None

def get_docstring_from_node(node) -> Optional[str]:
    # Use ast.get_docstring to normalize consistently
    return ast.get_docstring(node)

def extract_section(doc: str, header: str) -> str:
    # Extract the block starting at "header:" until the next section header line like "Xxx:"
    lines = doc.splitlines()
    out: List[str] = []
    in_section = False
    for i, line in enumerate(lines):
        if not in_section:
            if line.strip().startswith(header + ":"):
                in_section = True
                # include following lines only (typically content lines)
                continue
        else:
            stripped = line.strip()
            if stripped.endswith(":") and stripped[:1].isalpha() and stripped.split(":")[0].istitle():
                break
            out.append(line)
    return "\n".join(out).strip()

def section_present(doc: str, header: str) -> bool:
    return f"{header}:" in doc

def args_section_has_params(doc: str, params: List[str]) -> bool:
    if not section_present(doc, "Args"):
        return False
    section = extract_section(doc, "Args")
    sec_lower = section.lower()
    for p in params:
        if p in ("self", "cls"):
            continue
        if p.lower() not in sec_lower:
            return False
    return True

def raises_section_mentions(doc: str, exc_name: str) -> bool:
    if not section_present(doc, "Raises"):
        return False
    section = extract_section(doc, "Raises")
    return exc_name in section

def collect_functions_and_methods(module: ast.AST) -> Tuple[Dict[str, ast.FunctionDef], Dict[str, Dict[str, ast.FunctionDef]]]:
    # returns (module_functions, class_methods)
    mod_funcs: Dict[str, ast.FunctionDef] = {}
    class_methods: Dict[str, Dict[str, ast.FunctionDef]] = {}
    for node in module.body:  # type: ignore
        if isinstance(node, ast.FunctionDef):
            mod_funcs[node.name] = node
        elif isinstance(node, ast.ClassDef):
            methods: Dict[str, ast.FunctionDef] = {}
            for b in node.body:
                if isinstance(b, ast.FunctionDef):
                    methods[b.name] = b
            class_methods[node.name] = methods
    return mod_funcs, class_methods

def get_node_docstring_raw(node: ast.AST) -> Optional[str]:
    # Return the docstring literal value if present (first statement Expr with Constant string)
    if hasattr(node, "body") and isinstance(node.body, list) and node.body:
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):  # type: ignore
            return first.value.value  # type: ignore
    return None

def get_all_docstrings_map(module: ast.AST) -> Dict[str, Optional[str]]:
    # Map path keys to docstrings (normalized with ast.get_docstring)
    res: Dict[str, Optional[str]] = {}
    # module-level docstring
    res["__module__"] = ast.get_docstring(module)
    for node in module.body:  # type: ignore
        if isinstance(node, ast.FunctionDef):
            res[f"func::{node.name}"] = ast.get_docstring(node)
        elif isinstance(node, ast.ClassDef):
            res[f"class::{node.name}"] = ast.get_docstring(node)
            for b in node.body:
                if isinstance(b, ast.FunctionDef):
                    res[f"method::{node.name}.{b.name}"] = ast.get_docstring(b)
    return res

def compare_bodies_ignoring_docstrings(func_in: ast.FunctionDef, func_out: ast.FunctionDef) -> bool:
    def strip_doc(f: ast.FunctionDef) -> List[ast.AST]:
        body = f.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):  # type: ignore
            return body[1:]
        return body
    in_body = strip_doc(func_in)
    out_body = strip_doc(func_out)
    # Compare dumps of each statement sequence
    if len(in_body) != len(out_body):
        return False
    for a, b in zip(in_body, out_body):
        if ast.dump(a, include_attributes=False) != ast.dump(b, include_attributes=False):
            return False
    return True

def module_has_no_logic_change_heuristic(input_mod: ast.AST, output_mod: ast.AST) -> bool:
    # Heuristic: compare functions and methods bodies ignoring docstrings
    in_funcs, in_methods = collect_functions_and_methods(input_mod)
    out_funcs, out_methods = collect_functions_and_methods(output_mod)
    # Compare functions present in input
    for name, f_in in in_funcs.items():
        f_out = out_funcs.get(name)
        if f_out is None:
            return False
        if not compare_bodies_ignoring_docstrings(f_in, f_out):
            return False
    # Compare methods
    for cls, methods in in_methods.items():
        out_cls_methods = out_methods.get(cls)
        if out_cls_methods is None:
            return False
        for mname, minfo in methods.items():
            mout = out_cls_methods.get(mname)
            if mout is None:
                return False
            if not compare_bodies_ignoring_docstrings(minfo, mout):
                return False
    return True

def last_non_empty_line(s: str) -> str:
    for line in reversed(s.splitlines()):
        if line.strip():
            return line
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks: Dict[str, bool] = {
        # File presence
        "files_exist_utils": False,
        "files_exist_models": False,
        "files_exist_legacy": False,
        # math_ops docstrings and sections
        "math_add_doc": False,
        "math_add_args_ok": False,
        "math_add_returns_ok": False,
        "math_divide_doc": False,
        "math_divide_args_ok": False,
        "math_divide_returns_ok": False,
        "math_divide_raises_valueerror": False,
        "math_moving_average_doc": False,
        "math_moving_average_args_ok": False,
        "math_moving_average_returns_ok": False,
        "math_moving_average_raises_valueerror": False,
        # user models checks
        "user_is_adult_doc_preserved": False,
        "user_params_documented_name_age": False,
        # legacy unchanged
        "legacy_file_unchanged": False,
        # report checks
        "report_exists": False,
        "report_has_int_fields": False,
        "report_changed_files_has_math": False,
        "report_changed_files_has_user": False,
        "report_changed_files_excludes_legacy": False,
        "report_docstrings_added_ge_4": False,
        # audit checks
        "audit_exists": False,
        "audit_mentions_google_style": False,
        "audit_confirms_no_mods_existing": False,
        # heuristic (non-scored)
        "heuristic_google_style_headers_present": False,
        "heuristic_no_logic_change_utils": False,
        "heuristic_no_logic_change_models": False,
    }

    # Early no-op baseline: if output missing or empty, reward must be 0.0
    no_outputs = (not os.path.isdir(output_dir)) or all(
        not files for _, _, files in os.walk(output_dir)
    )

    # Paths
    out_utils = os.path.join(output_dir, "src", "utils", "math_ops.py")
    out_models = os.path.join(output_dir, "src", "models", "user.py")
    out_legacy = os.path.join(output_dir, "src", "legacy", "old_module.py")

    in_utils = os.path.join(input_dir, "src", "utils", "math_ops.py")
    in_models = os.path.join(input_dir, "src", "models", "user.py")
    in_legacy = os.path.join(input_dir, "src", "legacy", "old_module.py")

    # File existence
    if os.path.isfile(out_utils):
        checks["files_exist_utils"] = True
    if os.path.isfile(out_models):
        checks["files_exist_models"] = True
    if os.path.isfile(out_legacy):
        checks["files_exist_legacy"] = True

    # math_ops checks
    if checks["files_exist_utils"]:
        mod_out = parse_ast(out_utils)
        mod_in = parse_ast(in_utils) if os.path.isfile(in_utils) else None
        if mod_out is not None:
            funcs_out, _ = collect_functions_and_methods(mod_out)
            # Expected functions
            for fname in ["add", "divide", "moving_average"]:
                fnode = funcs_out.get(fname)
                if fnode is None:
                    continue
                doc = get_docstring_from_node(fnode)
                if fname == "add":
                    if doc:
                        checks["math_add_doc"] = True
                        # Args
                        params = [a.arg for a in fnode.args.args]
                        checks["math_add_args_ok"] = args_section_has_params(doc, params)
                        # Returns
                        checks["math_add_returns_ok"] = section_present(doc, "Returns")
                elif fname == "divide":
                    if doc:
                        checks["math_divide_doc"] = True
                        params = [a.arg for a in fnode.args.args]
                        checks["math_divide_args_ok"] = args_section_has_params(doc, params)
                        checks["math_divide_returns_ok"] = section_present(doc, "Returns")
                        checks["math_divide_raises_valueerror"] = raises_section_mentions(doc, "ValueError")
                elif fname == "moving_average":
                    if doc:
                        checks["math_moving_average_doc"] = True
                        params = [a.arg for a in fnode.args.args]
                        checks["math_moving_average_args_ok"] = args_section_has_params(doc, params)
                        checks["math_moving_average_returns_ok"] = section_present(doc, "Returns")
                        checks["math_moving_average_raises_valueerror"] = raises_section_mentions(doc, "ValueError")

            # Heuristic: no logic change for math_ops
            if mod_in is not None:
                checks["heuristic_no_logic_change_utils"] = module_has_no_logic_change_heuristic(mod_in, mod_out)

            # Heuristic: google style headers present in at least these docstrings
            headers_ok = True
            for fname in ["add", "divide", "moving_average"]:
                fnode = funcs_out.get(fname)
                if fnode is None:
                    headers_ok = False
                    break
                doc = get_docstring_from_node(fnode)
                if not doc:
                    headers_ok = False
                    break
                if not section_present(doc, "Args") or not section_present(doc, "Returns"):
                    headers_ok = False
                    break
            checks["heuristic_google_style_headers_present"] = headers_ok

    # models/user.py checks
    if checks["files_exist_models"]:
        out_mod = parse_ast(out_models)
        in_mod = parse_ast(in_models) if os.path.isfile(in_models) else None
        if out_mod is not None and in_mod is not None:
            _, out_methods_map = collect_functions_and_methods(out_mod)
            _, in_methods_map = collect_functions_and_methods(in_mod)
            # is_adult doc preserved
            # Find class User -> method is_adult
            out_is_adult = None
            in_is_adult = None
            if "User" in out_methods_map and "User" in in_methods_map:
                out_is_adult_node = out_methods_map["User"].get("is_adult")
                in_is_adult_node = in_methods_map["User"].get("is_adult")
                if out_is_adult_node and in_is_adult_node:
                    out_is_adult = get_docstring_from_node(out_is_adult_node)
                    in_is_adult = get_docstring_from_node(in_is_adult_node)
                    if (out_is_adult is not None) and (in_is_adult is not None) and (out_is_adult == in_is_adult):
                        checks["user_is_adult_doc_preserved"] = True
            # User class or __init__ docs with Args: name and age
            user_class_node = None
            for node in out_mod.body:  # type: ignore
                if isinstance(node, ast.ClassDef) and node.name == "User":
                    user_class_node = node
                    break
            documented = False
            if user_class_node is not None:
                cls_doc = get_docstring_from_node(user_class_node)
                if cls_doc and args_section_has_params(cls_doc, ["name", "age"]):
                    documented = True
                else:
                    # check __init__
                    init_node = None
                    for b in user_class_node.body:
                        if isinstance(b, ast.FunctionDef) and b.name == "__init__":
                            init_node = b
                            break
                    if init_node is not None:
                        init_doc = get_docstring_from_node(init_node)
                        if init_doc and args_section_has_params(init_doc, ["name", "age"]):
                            documented = True
            checks["user_params_documented_name_age"] = documented

            # Heuristic: no logic change in models
            checks["heuristic_no_logic_change_models"] = module_has_no_logic_change_heuristic(in_mod, out_mod)

    # legacy/old_module.py unchanged
    if checks["files_exist_legacy"]:
        out_text = read_text(out_legacy) or ""
        in_text = read_text(in_legacy) or ""
        if out_text == in_text and out_text != "":
            checks["legacy_file_unchanged"] = True

    # report.json checks
    report_path = os.path.join(output_dir, "report.json")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            ints_ok = all(
                isinstance(report.get(k), int)
                for k in ["files_processed", "docstrings_added", "functions_seen", "classes_seen", "methods_seen"]
            ) and isinstance(report.get("changed_files"), list)
            checks["report_has_int_fields"] = bool(ints_ok)
            if isinstance(report.get("changed_files"), list):
                cf = report.get("changed_files", [])
                # Ensure elements are strings
                cf = [c for c in cf if isinstance(c, str)]
                # Required inclusions/exclusions
                checks["report_changed_files_has_math"] = "src/utils/math_ops.py" in cf
                checks["report_changed_files_has_user"] = "src/models/user.py" in cf
                checks["report_changed_files_excludes_legacy"] = "src/legacy/old_module.py" not in cf
            if isinstance(report.get("docstrings_added"), int):
                checks["report_docstrings_added_ge_4"] = report.get("docstrings_added", 0) >= 4
        except Exception:
            pass

    # AUDIT.md checks
    audit_path = os.path.join(output_dir, "AUDIT.md")
    if os.path.isfile(audit_path):
        checks["audit_exists"] = True
        txt = read_text(audit_path) or ""
        if "Google Style docstrings" in txt:
            checks["audit_mentions_google_style"] = True
        lower = txt.lower()
        phrases = [
            "did not modify existing docstrings",
            "didn't modify existing docstrings",
            "did not change existing docstrings",
            "no changes to existing docstrings",
        ]
        if any(p in lower for p in phrases):
            checks["audit_confirms_no_mods_existing"] = True

    # Determine reward: only deterministic checks contribute
    scored_keys = [
        "files_exist_utils",
        "files_exist_models",
        "files_exist_legacy",
        "math_add_doc",
        "math_add_args_ok",
        "math_add_returns_ok",
        "math_divide_doc",
        "math_divide_args_ok",
        "math_divide_returns_ok",
        "math_divide_raises_valueerror",
        "math_moving_average_doc",
        "math_moving_average_args_ok",
        "math_moving_average_returns_ok",
        "math_moving_average_raises_valueerror",
        "user_is_adult_doc_preserved",
        "user_params_documented_name_age",
        "legacy_file_unchanged",
        "report_exists",
        "report_has_int_fields",
        "report_changed_files_has_math",
        "report_changed_files_has_user",
        "report_changed_files_excludes_legacy",
        "report_docstrings_added_ge_4",
        "audit_exists",
        "audit_mentions_google_style",
        "audit_confirms_no_mods_existing",
    ]

    if no_outputs:
        reward = 0.0
    else:
        total = len(scored_keys)
        passed = sum(1 for k in scored_keys if checks.get(k, False))
        reward = passed / total if total > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()