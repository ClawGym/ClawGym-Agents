import ast
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Optional[Path]) -> Tuple[Optional[Any], Optional[str]]:
    if path is None:
        return None, "path is None"
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _parse_python_ast(path: Path) -> Optional[ast.AST]:
    try:
        txt = _read_text(path)
        if txt is None:
            return None
        return ast.parse(txt)
    except Exception:
        return None


def _get_function_defs(module_ast: ast.AST) -> Dict[str, ast.FunctionDef]:
    funcs: Dict[str, ast.FunctionDef] = {}
    for node in ast.walk(module_ast):
        if isinstance(node, ast.FunctionDef):
            funcs[node.name] = node
    return funcs


def _has_import_of_load_json(module_ast: ast.AST) -> bool:
    imported = False
    for node in ast.walk(module_ast):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.names:
                mod = node.module
                for alias in node.names:
                    if alias.name == "load_json" and (mod.endswith("utils.io") or mod.endswith("src.utils.io")):
                        imported = True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("utils.io", "src.utils.io"):
                    imported = True
    return imported


def _uses_load_json_calls(module_ast: ast.AST) -> bool:
    for node in ast.walk(module_ast):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == "load_json":
                return True
            if isinstance(f, ast.Attribute) and f.attr == "load_json":
                return True
    return False


def _run_main_and_capture(workspace: Path) -> Tuple[Optional[str], Optional[str]]:
    # Run as a module to support package-style imports after refactor
    app_module = "src.app.main"
    # Verify presence of main.py to decide feasibility
    main_path = workspace / "src" / "app" / "main.py"
    if not main_path.exists():
        return None, "main.py not found"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", app_module],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8,
        )
        if proc.returncode != 0:
            return None, proc.stderr.strip() or f"Non-zero exit: {proc.returncode}"
        return proc.stdout, None
    except Exception as e:
        return None, str(e)


def _extract_todos_from_file(path: Path) -> List[Tuple[str, int, str, str]]:
    results: List[Tuple[str, int, str, str]] = []
    content = _read_text(path)
    if content is None:
        return results
    lines = content.splitlines()
    tags = ["TODO", "NICE-TO-HAVE"]
    for idx, line in enumerate(lines, start=1):
        for tag in tags:
            pattern = re.compile(rf"(?<!\w){re.escape(tag)}(?:\s*:)?\s*(.*)")
            for match in pattern.finditer(line):
                text = match.group(1).strip()
                results.append((str(path), idx, tag, text))
    return results


def _list_files_by_extensions(root: Path, exts: Tuple[str, ...]) -> List[Path]:
    files: List[Path] = []
    if not root.exists():
        return files
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            files.append(p)
    return files


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "utils_io_load_json_defined": 0.0,
        "utils_io_load_json_docstring": 0.0,
        "main_duplicate_reader_removed": 0.0,
        "helpers_duplicate_reader_removed": 0.0,
        "main_uses_utils_load_json": 0.0,
        "settings_json_keys_updated": 0.0,
        "runtime_output_correct": 0.0,
        "runtime_single_line_output": 0.0,
        "meeting_notes_sections": 0.0,
        "meeting_notes_priorities_used": 0.0,
        "refactor_log_valid_structure": 0.0,
        "refactor_log_mappings": 0.0,
        "todos_csv_exists_and_header": 0.0,
        "todos_extracted_coverage": 0.0,
        "todos_tags_valid": 0.0,
        "readme_mentions_record_limit": 0.0,
        "readme_mentions_consolidated_utility": 0.0,
    }

    # 1) utils/io.py checks
    utils_io_path = workspace / "src" / "utils" / "io.py"
    utils_ast = _parse_python_ast(utils_io_path) if utils_io_path.exists() else None
    if utils_ast is not None:
        funcs = _get_function_defs(utils_ast)
        if "load_json" in funcs:
            scores["utils_io_load_json_defined"] = 1.0
            doc = ast.get_docstring(funcs["load_json"])
            if doc and isinstance(doc, str) and doc.strip():
                scores["utils_io_load_json_docstring"] = 1.0

    # 2) main.py and helpers.py refactor checks
    main_path = workspace / "src" / "app" / "main.py"
    helpers_path = workspace / "src" / "app" / "helpers.py"

    # main.py
    main_ast = _parse_python_ast(main_path) if main_path.exists() else None
    if main_ast is not None:
        main_funcs = _get_function_defs(main_ast)
        # Removed duplicate read_json
        if "read_json" not in main_funcs:
            scores["main_duplicate_reader_removed"] = 1.0
        # Uses utils.io.load_json
        if _has_import_of_load_json(main_ast) and _uses_load_json_calls(main_ast):
            scores["main_uses_utils_load_json"] = 1.0

    # helpers.py
    helpers_ast = _parse_python_ast(helpers_path) if helpers_path.exists() else None
    if helpers_ast is not None:
        helpers_funcs = _get_function_defs(helpers_ast)
        if "load_json_file" not in helpers_funcs:
            scores["helpers_duplicate_reader_removed"] = 1.0

    # 3) settings.json check for keys and rename
    settings_path = workspace / "config" / "settings.json"
    settings, _ = _load_json_safe(settings_path if settings_path.exists() else None)
    if settings and isinstance(settings, dict):
        app_cfg = settings.get("app")
        if isinstance(app_cfg, dict):
            has_timeout = "timeout_seconds" in app_cfg
            has_input = "input_path" in app_cfg
            has_record_limit = "record_limit" in app_cfg
            has_old_limit = "limit" in app_cfg
            if has_timeout and has_input and has_record_limit and not has_old_limit:
                scores["settings_json_keys_updated"] = 1.0

    # 4) Runtime output correctness and single-line requirement
    # Compute expected Y, X, Z based on config with updated key "record_limit"
    expected_line: Optional[str] = None
    if settings and isinstance(settings, dict):
        app_cfg = settings.get("app", {})
        if isinstance(app_cfg, dict):
            timeout_val = app_cfg.get("timeout_seconds")
            input_path_val = app_cfg.get("input_path")
            record_limit_val = app_cfg.get("record_limit")
            try:
                input_file_path = (workspace / str(input_path_val)) if isinstance(input_path_val, str) else None
                data, _ = _load_json_safe(input_file_path) if input_file_path else (None, "bad input_path")
                if isinstance(data, list) and isinstance(timeout_val, (int, float)) and isinstance(record_limit_val, (int, float)):
                    Y = len(data)
                    X = min(Y, int(record_limit_val))
                    Z = int(timeout_val)
                    expected_line = f"Processed {X} of {Y} records with timeout={Z}"
            except Exception:
                expected_line = None
    stdout, _ = _run_main_and_capture(workspace)
    if stdout is not None:
        non_empty_lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]
        if expected_line is not None and non_empty_lines:
            # Only evaluate when config is properly wired (expected_line available)
            actual_line = non_empty_lines[0].strip()
            if actual_line == expected_line:
                scores["runtime_output_correct"] = 1.0
            if len(non_empty_lines) == 1:
                scores["runtime_single_line_output"] = 1.0

    # 5) Meeting notes sections and priorities
    notes_path = workspace / "review" / "meeting_notes.md"
    notes_text = _read_text(notes_path)
    if notes_text is not None:
        lines = notes_text.splitlines()

        def has_section(title: str) -> bool:
            t = title.strip().lower()
            for ln in lines:
                ln_stripped = ln.strip()
                if not ln_stripped:
                    continue
                if ln_stripped.lower() == t:
                    return True
                if ln_stripped.startswith("#"):
                    h = ln_stripped.lstrip("#").strip().lower()
                    if h == t:
                        return True
            return False

        has_summary = has_section("Summary")
        has_action = has_section("Action Items")
        has_decisions = has_section("Decisions")
        if has_summary and has_action and has_decisions:
            scores["meeting_notes_sections"] = 1.0

        if any(tag in notes_text for tag in ("[P1]", "[P2]", "[P3]")):
            scores["meeting_notes_priorities_used"] = 1.0

    # 6) Refactor log checks
    refactor_log_path = workspace / "review" / "refactor_log.json"
    refactor_log, _ = _load_json_safe(refactor_log_path if refactor_log_path.exists() else None)
    if isinstance(refactor_log, list):
        valid = True
        for item in refactor_log:
            if not isinstance(item, dict):
                valid = False
                break
            frm = item.get("from")
            to = item.get("to")
            status = item.get("status")
            notes = item.get("notes")
            if not (isinstance(frm, dict) and isinstance(to, dict) and isinstance(status, str) and isinstance(notes, str)):
                valid = False
                break
            if "file" not in frm or "symbol" not in frm or "file" not in to or "symbol" not in to:
                valid = False
                break
            if status not in {"replaced", "removed", "moved"}:
                valid = False
                break
        if valid:
            scores["refactor_log_valid_structure"] = 1.0

        # Check mappings
        def norm(p: str) -> str:
            return p.replace("\\", "/")

        want1 = {
            "from_file": "src/app/main.py",
            "from_symbol": "read_json",
            "to_file": "src/utils/io.py",
            "to_symbol": "load_json",
            "status": "replaced",
        }
        want2 = {
            "from_file": "src/app/helpers.py",
            "from_symbol": "load_json_file",
            "to_file": "src/utils/io.py",
            "to_symbol": "load_json",
            "status": "replaced",
        }
        found1 = False
        found2 = False
        for item in refactor_log:
            try:
                frm = item.get("from", {})
                to = item.get("to", {})
                status = item.get("status", "")
                if (norm(frm.get("file", "")) == want1["from_file"]
                    and frm.get("symbol", "") == want1["from_symbol"]
                    and norm(to.get("file", "")) == want1["to_file"]
                    and to.get("symbol", "") == want1["to_symbol"]
                    and status == want1["status"]):
                    found1 = True
                if (norm(frm.get("file", "")) == want2["from_file"]
                    and frm.get("symbol", "") == want2["from_symbol"]
                    and norm(to.get("file", "")) == want2["to_file"]
                    and to.get("symbol", "") == want2["to_symbol"]
                    and status == want2["status"]):
                    found2 = True
            except Exception:
                continue
        if found1 and found2:
            scores["refactor_log_mappings"] = 1.0
        elif found1 or found2:
            scores["refactor_log_mappings"] = 0.5

    # 7) TODOs extraction CSV
    todos_csv_path = workspace / "review" / "todos_extracted.csv"
    csv_rows: List[Dict[str, str]] = []
    header_ok = False
    tags_valid = True
    if todos_csv_path.exists():
        try:
            with todos_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                header_ok = reader.fieldnames == ["file", "line", "tag", "text"]
                if header_ok:
                    for row in reader:
                        csv_rows.append(row)
                        if row.get("tag") not in ("TODO", "NICE-TO-HAVE"):
                            tags_valid = False
        except Exception:
            header_ok = False
            tags_valid = False
    if header_ok:
        scores["todos_csv_exists_and_header"] = 1.0
    if tags_valid and header_ok:
        scores["todos_tags_valid"] = 1.0

    # Expected TODO/NICE-TO-HAVE extraction from current workspace
    files_to_scan = _list_files_by_extensions(workspace, (".py", ".md"))
    expected_occurrences: List[Tuple[str, int, str, str]] = []
    for f in files_to_scan:
        occs = _extract_todos_from_file(f)
        for (file_path, line_no, tag, text) in occs:
            try:
                rel = str(Path(file_path).resolve().relative_to(workspace.resolve()))
            except Exception:
                rel = str(file_path)
            expected_occurrences.append((rel.replace("\\", "/"), line_no, tag, text))

    if header_ok:
        matched = 0
        used_indices: set = set()
        for exp_idx, (exp_file, exp_line, exp_tag, exp_text) in enumerate(expected_occurrences):
            found = False
            for i, row in enumerate(csv_rows):
                if i in used_indices:
                    continue
                row_file = (row.get("file") or "").replace("\\", "/")
                row_line = row.get("line") or ""
                row_tag = row.get("tag") or ""
                row_text = (row.get("text") or "").strip()
                if row_file.endswith(exp_file) and row_line == str(exp_line) and row_tag == exp_tag and row_text == exp_text:
                    found = True
                    used_indices.add(i)
                    break
            if found:
                matched += 1
        total = len(expected_occurrences)
        if total == 0:
            scores["todos_extracted_coverage"] = 1.0 if len(csv_rows) == 0 else 0.0
        else:
            scores["todos_extracted_coverage"] = matched / total

    # 8) README updates
    readme_path = workspace / "README.md"
    readme_text = _read_text(readme_path)
    if readme_text is not None:
        if "record_limit" in readme_text:
            scores["readme_mentions_record_limit"] = 1.0
        if ("src/utils/io.py" in readme_text) or ("utils/io.py" in readme_text) or ("utils.io" in readme_text) or ("load_json" in readme_text):
            scores["readme_mentions_consolidated_utility"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()