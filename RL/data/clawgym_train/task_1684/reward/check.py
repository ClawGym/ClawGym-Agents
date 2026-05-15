import json
import csv
import sys
import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        txt = _read_text_safe(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _load_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _nonempty_line_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip() != "")


def _compute_function_spans(source: str) -> List[Tuple[int, int, ast.FunctionDef]]:
    try:
        tree = ast.parse(source)
    except Exception:
        return []
    lines = source.splitlines()
    n_lines = len(lines)
    funcs: List[Tuple[int, int, ast.FunctionDef]] = []
    func_nodes: List[ast.FunctionDef] = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    func_nodes.sort(key=lambda n: getattr(n, "lineno", 0))
    top_defs: List[int] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ln = getattr(node, "lineno", None)
            if isinstance(ln, int):
                top_defs.append(ln)
    top_defs = sorted(top_defs)

    for fn in func_nodes:
        start = getattr(fn, "lineno", None)
        end = getattr(fn, "end_lineno", None)
        if start is None:
            continue
        if end is None:
            if start in top_defs:
                next_markers = [ln for ln in top_defs if ln > start]
                end = (next_markers[0] - 1) if next_markers else n_lines
            else:
                end = n_lines
        funcs.append((int(start), int(end), fn))
    return funcs


def _count_function_lengths_nonempty(source: str) -> Tuple[int, float]:
    spans = _compute_function_spans(source)
    if not spans:
        return 0, 0.0
    lines = source.splitlines()
    lengths: List[int] = []
    for start, end, _node in spans:
        slice_lines = lines[start - 1:end]
        nonempty = sum(1 for ln in slice_lines if ln.strip() != "")
        lengths.append(nonempty)
    avg = (sum(lengths) / len(lengths)) if lengths else 0.0
    return len(lengths), float(avg)


def _compute_expected_metrics(src_dir: Path) -> Optional[Dict[str, Any]]:
    if not src_dir.exists() or not src_dir.is_dir():
        return None
    files_metrics: Dict[str, Dict[str, float]] = {}
    total_nonempty = 0
    total_functions = 0
    all_func_lengths: List[float] = []

    for py in sorted(src_dir.rglob("*.py")):
        rel = py.relative_to(src_dir.parent).as_posix() if src_dir.parent in py.parents else py.as_posix()
        text = _read_text_safe(py)
        if text is None:
            return None
        nonempty = _nonempty_line_count(text)
        fn_count, avg_len = _count_function_lengths_nonempty(text)
        spans = _compute_function_spans(text)
        func_lengths = []
        for start, end, _ in spans:
            slice_lines = text.splitlines()[start - 1:end]
            func_lengths.append(sum(1 for ln in slice_lines if ln.strip() != ""))
        files_metrics[rel] = {
            "total_nonempty_lines": float(nonempty),
            "function_count": float(fn_count),
            "average_function_length_lines": float(avg_len),
        }
        total_nonempty += nonempty
        total_functions += fn_count
        all_func_lengths.extend(func_lengths)
    repo_avg = float(sum(all_func_lengths) / len(all_func_lengths)) if all_func_lengths else 0.0
    expected = {
        "files": files_metrics,
        "repository_totals": {
            "total_nonempty_lines": float(total_nonempty),
            "total_functions": float(total_functions),
            "average_function_length_lines": float(repo_avg),
        },
    }
    return expected


def _almost_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(float(a) - float(b)) <= tol


def _get_function_def_by_name(source: str, name: str) -> Optional[ast.FunctionDef]:
    try:
        tree = ast.parse(source)
    except Exception:
        return None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _exec_module_from_path(path: Path) -> Optional[Dict[str, Any]]:
    try:
        import runpy
        return runpy.run_path(str(path))
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "signal_module_exists": 0.0,
        "moving_average_signature": 0.0,
        "moving_average_behavior_valid": 0.0,
        "sensors_refactor_exists": 0.0,
        "sensors_imports_updated": 0.0,
        "sensors_functions_preserved": 0.0,
        "code_metrics_json_exists": 0.0,
        "code_metrics_files_correct": 0.0,
        "code_metrics_repository_totals_correct": 0.0,
        "api_changes_csv_exists": 0.0,
        "api_changes_required_rows_present": 0.0,
        "api_changes_file_updated_flags": 0.0,
        "review_notes_exists": 0.0,
        "review_notes_bullet_count": 0.0,
    }

    src_dir = workspace / "src"
    refactored_signal = workspace / "refactored" / "signal.py"
    refactored_sensors = workspace / "refactored" / "sensors.py"
    out_metrics = workspace / "out" / "code_metrics.json"
    out_api_changes = workspace / "out" / "api_changes.csv"
    out_review_notes = workspace / "out" / "review_notes.md"

    # 1) refactored/signal.py
    if refactored_signal.exists() and refactored_signal.is_file():
        scores["signal_module_exists"] = 1.0
        sig_src = _read_text_safe(refactored_signal) or ""
        fn = _get_function_def_by_name(sig_src, "moving_average")
        signature_ok = False
        if fn is not None:
            args = fn.args.args
            if len(args) == 2 and args[0].arg == "values" and args[1].arg == "window":
                params_annotated = (args[0].annotation is not None) and (args[1].annotation is not None)
                doc = ast.get_docstring(fn)
                has_doc = isinstance(doc, str) and len(doc.strip()) > 0
                if params_annotated and has_doc:
                    signature_ok = True
        scores["moving_average_signature"] = 1.0 if signature_ok else 0.0

        env = _exec_module_from_path(refactored_signal)
        behavior_ok = False
        if env is not None and "moving_average" in env and callable(env["moving_average"]):
            ma = env["moving_average"]
            try:
                vals = [1.0, 2.0, 3.0, 4.0]
                out = ma(vals, 2)
                expected = [(vals[i] + vals[i + 1]) / 2.0 for i in range(len(vals) - 1)]
                if isinstance(out, list) and len(out) == 3 and all(_almost_equal(o, e) for o, e in zip(out, expected)):
                    out2 = ma(vals, 1)
                    if isinstance(out2, list) and len(out2) == len(vals) and all(_almost_equal(x, float(y)) for x, y in zip(out2, vals)):
                        err1 = False
                        err2 = False
                        try:
                            ma(vals, 0)
                        except Exception as e:
                            err1 = isinstance(e, ValueError)
                        try:
                            ma(vals, 10)
                        except Exception as e:
                            err2 = isinstance(e, ValueError)
                        if err1 and err2:
                            behavior_ok = True
            except Exception:
                behavior_ok = False
        scores["moving_average_behavior_valid"] = 1.0 if behavior_ok else 0.0

    # 2) refactored/sensors.py
    if refactored_sensors.exists() and refactored_sensors.is_file():
        scores["sensors_refactor_exists"] = 1.0
        ssrc = _read_text_safe(refactored_sensors) or ""
        import_updated = ("from refactored.signal import moving_average" in ssrc)
        old_imports_absent = ("from smoothing import boxcar_smooth" not in ssrc) and ("from filters import moving_average_filter" not in ssrc)
        moving_calls = ssrc.count("moving_average(")
        if import_updated and old_imports_absent and moving_calls >= 2:
            scores["sensors_imports_updated"] = 1.0
        else:
            scores["sensors_imports_updated"] = 0.0
        try:
            tree = ast.parse(ssrc)
            fn_names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
            preserved = ("read_encoder_samples" in fn_names and "demo_apply" in fn_names)
        except Exception:
            preserved = False
        scores["sensors_functions_preserved"] = 1.0 if preserved else 0.0

    # 3) out/code_metrics.json
    if out_metrics.exists() and out_metrics.is_file():
        scores["code_metrics_json_exists"] = 1.0
        data = _load_json_safe(out_metrics)
        if isinstance(data, dict) and "files" in data and "repository_totals" in data and isinstance(data["files"], (dict,)):
            expected = _compute_expected_metrics(src_dir)
            if expected is not None:
                per_file_ok = True
                for py in sorted(src_dir.rglob("*.py")):
                    rel = py.relative_to(src_dir.parent).as_posix() if src_dir.parent in py.parents else py.as_posix()
                    if rel not in data["files"]:
                        per_file_ok = False
                        break
                    m_actual = data["files"][rel]
                    m_expect = expected["files"][rel]
                    for key in ("total_nonempty_lines", "function_count", "average_function_length_lines"):
                        if key not in m_actual:
                            per_file_ok = False
                            break
                        try:
                            v_actual = float(m_actual[key])
                            v_expect = float(m_expect[key])
                        except Exception:
                            per_file_ok = False
                            break
                        if not _almost_equal(v_actual, v_expect):
                            per_file_ok = False
                            break
                    if not per_file_ok:
                        break
                scores["code_metrics_files_correct"] = 1.0 if per_file_ok else 0.0

                repo_ok = False
                repo = data.get("repository_totals", {})
                try:
                    tnl = float(repo.get("total_nonempty_lines", "nan"))
                    tf = float(repo.get("total_functions", "nan"))
                    af = float(repo.get("average_function_length_lines", "nan"))
                    e_tnl = float(expected["repository_totals"]["total_nonempty_lines"])
                    e_tf = float(expected["repository_totals"]["total_functions"])
                    e_af = float(expected["repository_totals"]["average_function_length_lines"])
                    if _almost_equal(tnl, e_tnl) and _almost_equal(tf, e_tf) and _almost_equal(af, e_af):
                        repo_ok = True
                except Exception:
                    repo_ok = False
                scores["code_metrics_repository_totals_correct"] = 1.0 if repo_ok else 0.0
            else:
                scores["code_metrics_files_correct"] = 0.0
                scores["code_metrics_repository_totals_correct"] = 0.0
        else:
            scores["code_metrics_files_correct"] = 0.0
            scores["code_metrics_repository_totals_correct"] = 0.0

    # 4) out/api_changes.csv
    if out_api_changes.exists() and out_api_changes.is_file():
        scores["api_changes_csv_exists"] = 1.0
        rows = _load_csv_safe(out_api_changes)
        required_ok = False
        flags_ok = False
        if isinstance(rows, list):
            try:
                with out_api_changes.open("r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    header = next(reader, [])
            except Exception:
                header = []
            header_lower = [h.strip().lower() for h in header]
            if header_lower == ["old_fqn", "new_fqn", "file_updated"]:
                need = {
                    ("smoothing.boxcar_smooth", "refactored.signal.moving_average"),
                    ("filters.moving_average_filter", "refactored.signal.moving_average"),
                }
                found = set()
                flags_all_yes = True
                for r in rows:
                    old = (r.get("old_fqn") or "").strip()
                    new = (r.get("new_fqn") or "").strip()
                    fu = (r.get("file_updated") or "").strip().lower()
                    if (old, new) in need:
                        found.add((old, new))
                        expect_yes = scores["sensors_imports_updated"] >= 1.0
                        if expect_yes and fu != "yes":
                            flags_all_yes = False
                        if not expect_yes and fu != "no":
                            flags_all_yes = False
                required_ok = (found == need)
                if required_ok:
                    flags_ok = flags_all_yes
        scores["api_changes_required_rows_present"] = 1.0 if required_ok else 0.0
        scores["api_changes_file_updated_flags"] = 1.0 if flags_ok else 0.0

    # 5) out/review_notes.md
    if out_review_notes.exists() and out_review_notes.is_file():
        scores["review_notes_exists"] = 1.0
        txt = _read_text_safe(out_review_notes) or ""
        lines = [ln for ln in txt.splitlines()]
        bullet_lines = [ln for ln in lines if ln.lstrip().startswith("- ") or ln.lstrip().startswith("* ")]
        count = len(bullet_lines)
        if 4 <= count <= 8:
            scores["review_notes_bullet_count"] = 1.0
        else:
            scores["review_notes_bullet_count"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()