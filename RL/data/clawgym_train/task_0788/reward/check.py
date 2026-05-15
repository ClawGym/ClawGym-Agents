import json
import os
import re
import sys
from collections import OrderedDict

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\r\n") for line in f.readlines()]
    except Exception:
        return None

def natural_key(s: str):
    # Case-insensitive, numeric-aware split
    s_lower = s.lower()
    parts = re.split(r'(\d+)', s_lower)
    key = []
    for p in parts:
        if p.isdigit():
            try:
                key.append(int(p))
            except Exception:
                key.append(p)
        else:
            key.append(p)
    return key

def is_dir_node(obj):
    if isinstance(obj, dict):
        t = obj.get("type")
        if isinstance(t, str) and t.lower() in ("dir", "directory", "folder"):
            return True
        # Has any child container keys indicating directory
        if any(k in obj for k in ("children", "dirs", "directories", "subdirs", "files")):
            # Presence of "files" alone can still indicate a directory holding files
            return True
    return False

def is_file_node(obj):
    if isinstance(obj, dict):
        t = obj.get("type")
        if isinstance(t, str) and t.lower() == "file":
            return True
        nm = obj.get("name") or obj.get("filename") or obj.get("file")
        if isinstance(nm, str) and nm.endswith(".pdf"):
            return True
    if isinstance(obj, str) and obj.endswith(".pdf"):
        return True
    return False

def get_name(obj):
    if isinstance(obj, dict):
        for k in ("name", "dir", "directory", "folder", "filename", "file"):
            if k in obj and isinstance(obj[k], str):
                return obj[k]
    if isinstance(obj, str):
        return obj
    return None

def extract_children_lists(node):
    # Return (files_list, dirs_list) of child entries from a directory node
    files = []
    dirs = []

    if not isinstance(node, dict):
        return files, dirs

    # Gather from 'files' list if present
    if "files" in node and isinstance(node["files"], list):
        for item in node["files"]:
            if isinstance(item, str):
                files.append(item)
            elif isinstance(item, dict):
                nm = get_name(item)
                if nm is not None:
                    files.append(nm)
    # Gather from possible directory lists
    for key in ("dirs", "directories", "subdirs"):
        if key in node and isinstance(node[key], list):
            for item in node[key]:
                dirs.append(item)

    # Gather from 'children' by classifying each child
    if "children" in node and isinstance(node["children"], list):
        for ch in node["children"]:
            if is_dir_node(ch):
                dirs.append(ch)
            elif is_file_node(ch):
                # Include the file name
                nm = get_name(ch)
                if nm is not None:
                    files.append(nm)
            else:
                # If ambiguous child: try to derive name and include as file if .pdf
                nm = get_name(ch)
                if isinstance(nm, str):
                    if nm.endswith(".pdf"):
                        files.append(nm)
                    else:
                        # Ambiguous non-pdf child assumed to be a dir-like if has nested structure
                        if isinstance(ch, dict) and any(k in ch for k in ("children", "dirs", "directories", "subdirs", "files")):
                            dirs.append(ch)

    return files, dirs

def normalize_input_dir(input_dir_value: str):
    # Normalize to no trailing slash for comparisons, but keep the same slash style
    if input_dir_value.endswith("/"):
        return input_dir_value.rstrip("/")
    return input_dir_value

def compute_expected_plan(library_tree, input_dir_value, exclude_dirs, exclude_hidden, sort, reverse):
    # root_name heuristic to drop root folder from path
    # The input_dir likely ends with the root folder name (e.g., input/library)
    root_basename = os.path.basename(normalize_input_dir(input_dir_value))
    # Determine root node to start walking:
    root_node = library_tree
    if isinstance(library_tree, dict):
        # If this dict is a node with "name" equal to root_basename, keep as is
        nm = get_name(library_tree)
        if nm is None:
            # If has a single key equal to root_basename, extract it
            if len(library_tree.keys()) == 1:
                only_key = next(iter(library_tree.keys()))
                if isinstance(only_key, str) and only_key.lower() == root_basename.lower():
                    root_node = library_tree[only_key]
        else:
            # If name matches base, treat as root dir node
            pass
    elif isinstance(library_tree, list):
        # Treat as children list under root
        root_node = {"name": root_basename, "children": library_tree}

    plan = []

    def walk_dir(node, rel_path_components):
        # node represents a directory-like; rel_path_components is list of path parts under root
        # Determine current dir name
        dir_name = None
        if isinstance(node, dict):
            dir_name = get_name(node)

        # Only apply exclusion if not the very first root node or if rel_path_components not empty
        # We skip excluding the root itself; but if root name matches exclude, we still process its children since input_dir is fixed
        if rel_path_components:
            effective_dir_name = rel_path_components[-1]
        else:
            # If no rel components yet, set from dir_name (if present), but we are not going to include it in path prefix
            effective_dir_name = dir_name

        # Apply directory exclusion rules
        if effective_dir_name:
            if exclude_hidden and effective_dir_name.startswith("."):
                return
            if exclude_dirs and effective_dir_name in exclude_dirs:
                return

        # Collect immediate files and dirs
        files, dirs = extract_children_lists(node)

        # Filter and sort files
        pdf_files = [f for f in files if isinstance(f, str) and f.endswith(".pdf")]
        # Sort according to natural sort
        pdf_files.sort(key=natural_key, reverse=bool(reverse))

        # Append files before subfolders
        for fname in pdf_files:
            # rel_path is input_dir_value + '/' + '/'.join(rel_path_components + [fname])
            # Note: we do not include the top root name in rel_path_components; that is handled by input_dir_value
            path_parts = [input_dir_value] + rel_path_components + [fname]
            # Build relative path string
            rel_path = "/".join(p.strip("/\\") for p in path_parts if isinstance(p, str))
            plan.append(rel_path)

        # Prepare subdirectories: need names to sort
        dir_entries = []
        for d in dirs:
            # derive name
            nm = get_name(d)
            if nm is None and isinstance(d, dict):
                # Try to infer a name if not explicitly provided
                if "path" in d and isinstance(d["path"], str):
                    nm = os.path.basename(d["path"])
            if nm is None:
                # Skip directories without a name
                continue
            # Apply exclusion to subdir before sorting/walking
            if exclude_hidden and nm.startswith("."):
                continue
            if exclude_dirs and nm in exclude_dirs:
                continue
            dir_entries.append((nm, d))

        # Sort directories by natural order of their names
        dir_entries.sort(key=lambda x: natural_key(x[0]), reverse=bool(reverse))

        for nm, d in dir_entries:
            walk_dir(d, rel_path_components + [nm])

    # Initialize traversal
    # If root_node is dict and looks like a directory node, start with its children and skip adding root name to rel path
    if isinstance(root_node, dict) and is_dir_node(root_node):
        # Determine children nodes
        # For walking, we want to start at the content under root, without adding the root directory name to the rel path
        # Gather top-level files and dirs from root_node, but using walk_dir which expects a directory node including its children.
        # To avoid including root name in rel path, we will create a synthetic wrapper node with the same children but no name.
        # However walk_dir uses rel_path_components to determine effective_dir_name; so pass empty list and ensure exclusion doesn't act on root.
        walk_dir(root_node, [])
    elif isinstance(root_node, list):
        # Synthetic directory with children list
        synthetic = {"children": root_node}
        walk_dir(synthetic, [])
    else:
        # Fallback: if the structure is a bare mapping with a single key equal to root_basename
        # try to unwrap; otherwise no files.
        if isinstance(library_tree, dict) and len(library_tree) == 1:
            only_key = next(iter(library_tree.keys()))
            content = library_tree[only_key]
            if isinstance(content, (dict, list)):
                if isinstance(content, dict) and is_dir_node(content):
                    walk_dir(content, [])
                else:
                    synthetic = {"children": content if isinstance(content, list) else []}
                    walk_dir(synthetic, [])

    return plan

def validate_notes(path):
    txt = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read()
    except Exception:
        return False
    if not txt:
        return False
    # Word count (split on whitespace)
    words = re.findall(r"\S+", txt)
    if len(words) < 120:
        return False
    content_lower = txt.lower()
    # Required mentions
    # bookmarks/hierarchical
    has_bookmark = ("bookmark" in content_lower)
    has_hierarchical = ("hierarchical" in content_lower)
    # exclusion rules (both named dirs and hidden directories)
    has_exclude = ("exclude" in content_lower)
    has_hidden = ("hidden" in content_lower)
    # natural sorting
    has_natural = ("natural" in content_lower and "sort" in content_lower)
    # verification / dry-run plan
    has_verify = any(k in content_lower for k in ["verify", "verification", "dry-run", "preview", "validate", "check order"])
    return all([has_bookmark, has_hierarchical, has_exclude, has_hidden, has_natural, has_verify])

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir_abs = os.path.join(workspace_root, "input")
    output_dir_abs = os.path.join(workspace_root, "output")
    reward_dir_abs = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = OrderedDict()
    checks["plan_exact_match"] = False
    checks["config_reflects_requirements"] = False
    checks["notes_satisfy_criteria"] = False

    # Paths
    req_path = os.path.join(input_dir_abs, "merge_requirements.json")
    tree_path = os.path.join(input_dir_abs, "library_tree.json")
    plan_path = os.path.join(output_dir_abs, "merge_plan.txt")
    config_path = os.path.join(output_dir_abs, "merge_config.json")
    notes_path = os.path.join(output_dir_abs, "notes.md")

    # Read inputs
    req = read_json(req_path)
    tree = read_json(tree_path)

    expected_plan = None
    expected_config = None

    if isinstance(req, dict) and req:
        # Prepare expected configuration
        # Keys expected: input_dir, output_pdf, sort, reverse, exclude_dirs, exclude_hidden, bookmarks
        expected_config = {}
        for k in ["input_dir", "output_pdf", "sort", "reverse", "exclude_dirs", "exclude_hidden", "bookmarks"]:
            if k in req:
                expected_config[k] = req[k]
        # For plan computation, extract controls
        input_dir_value = req.get("input_dir", "input/library")
        sort_value = req.get("sort", "natural")
        reverse_value = bool(req.get("reverse", False))
        exclude_dirs = req.get("exclude_dirs", [])
        if not isinstance(exclude_dirs, list):
            exclude_dirs = []
        exclude_hidden = bool(req.get("exclude_hidden", True))
        # Compute expected plan if tree is available
        if tree is not None:
            expected_plan = compute_expected_plan(
                library_tree=tree,
                input_dir_value=normalize_input_dir(input_dir_value),
                exclude_dirs=exclude_dirs,
                exclude_hidden=exclude_hidden,
                sort=sort_value,
                reverse=reverse_value
            )

    # Validate plan
    if expected_plan is not None and os.path.isfile(plan_path):
        plan_lines = read_text_lines(plan_path)
        if plan_lines is not None:
            # Filter out empty lines for comparison
            plan_lines_no_blank = [ln.strip() for ln in plan_lines if ln.strip() != ""]
            # Validate each line format: must start with input_dir and end with .pdf
            valid_format = True
            expected_input_prefix = None
            if expected_config and "input_dir" in expected_config:
                expected_input_prefix = normalize_input_dir(expected_config["input_dir"]) + "/"
            else:
                expected_input_prefix = "input/library/"
            for ln in plan_lines_no_blank:
                if not ln.startswith(expected_input_prefix):
                    valid_format = False
                    break
                if not ln.endswith(".pdf"):
                    valid_format = False
                    break
            # Compare exactly with expected list (order and content)
            if valid_format and plan_lines_no_blank == expected_plan:
                checks["plan_exact_match"] = True

    # Validate config
    if expected_config is not None and os.path.isfile(config_path):
        out_cfg = read_json(config_path)
        if isinstance(out_cfg, dict):
            # Check presence and equality for each required key
            cfg_ok = True
            for k, v in expected_config.items():
                if k not in out_cfg:
                    cfg_ok = False
                    break
                if k == "exclude_dirs":
                    exp_set = set(v) if isinstance(v, list) else set()
                    got_val = out_cfg.get(k, [])
                    got_set = set(got_val) if isinstance(got_val, list) else set()
                    if exp_set != got_set:
                        cfg_ok = False
                        break
                else:
                    if out_cfg.get(k) != v:
                        cfg_ok = False
                        break
            if cfg_ok:
                checks["config_reflects_requirements"] = True

    # Validate notes
    if os.path.isfile(notes_path):
        if validate_notes(notes_path):
            checks["notes_satisfy_criteria"] = True

    # Compute reward: average over 3 checks; no-op baseline 0 if outputs missing/don't match
    total_checks = 3
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if passed > 0 else 0.0

    result = OrderedDict()
    result["reward"] = reward
    for k, v in checks.items():
        result[k] = v
    print(json.dumps(result))

if __name__ == "__main__":
    main()