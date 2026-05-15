import json
import sys
import subprocess
import ast
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from datetime import datetime


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            return path.read_text(errors="ignore")
        except Exception:
            return None


def read_bytes_safe(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    try:
        return json.loads(data)
    except Exception:
        return None


def parse_simple_yaml_config(path: Path) -> Optional[Dict[str, str]]:
    """
    Minimal parser for simple key: value YAML used in this task.
    Handles lines of the form: key: value
    Ignores comments and blank lines.
    Does not handle nested structures or lists.
    """
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None
    result: Dict[str, str] = {}
    for raw in content:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
            val = val[1:-1]
        result[key] = val
    required_keys = {"domain", "path", "raw_html_path", "text_path", "metadata_path"}
    # If any required key missing, return None to signal invalid config
    if not required_keys.issubset(result.keys()):
        return None
    return result


def count_words(text: str) -> int:
    return len([w for w in text.split() if w.strip() != ""])


def has_function_with_docstring(py_path: Path) -> bool:
    """
    Parse a Python file and return True if at least one top-level function
    has a docstring.
    """
    try:
        source = py_path.read_text(encoding="utf-8", errors="ignore")
        module = ast.parse(source)
    except Exception:
        return False
    for node in module.body:
        if isinstance(node, ast.FunctionDef):
            if ast.get_docstring(node):
                return True
    return False


def run_subprocess(args: list, cwd: Path, timeout: int = 20) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", e.stderr or ""
    except Exception as e:
        return 1, "", str(e)


def parse_iso8601(dt_str: str) -> bool:
    """
    Validate ISO 8601 timestamp. Accepts 'Z' suffix as UTC.
    """
    if not isinstance(dt_str, str) or not dt_str:
        return False
    s = dt_str
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        _ = datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def extract_section_lines(content: str, header: str) -> Tuple[int, int, list]:
    """
    Find a section by a case-insensitive header line containing the header string.
    Return (start_idx, end_idx_exclusive, lines_of_section).
    The end is the next section header of the other known headings or EOF.
    """
    lines = content.splitlines()
    start = -1
    for i, ln in enumerate(lines):
        if header.lower() in ln.lower():
            start = i + 1
            break
    if start == -1:
        return -1, -1, []
    end = len(lines)
    other_headers = ["Refactoring changes", "How to run", "Clinic relevance"]
    others = [h for h in other_headers if h.lower() != header.lower()]
    for j in range(start, len(lines)):
        for h in others:
            if h.lower() in lines[j].lower():
                end = j
                break
        if end != len(lines):
            break
    section_lines = lines[start:end]
    return start, end, section_lines


def default_expected_paths() -> Dict[str, str]:
    return {
        "raw_html_path": "data/raw/page.html",
        "text_path": "data/processed/page.txt",
        "metadata_path": "data/processed/metadata.json",
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "app_dir_exists": 0.0,
        "app_net_module_exists": 0.0,
        "app_extract_module_exists": 0.0,
        "net_module_has_function_docstring": 0.0,
        "extract_module_has_function_docstring": 0.0,
        "run_pipeline_script_exists": 0.0,
        "run_pipeline_reads_config": 0.0,
        "run_pipeline_imports_app_modules": 0.0,
        "validate_script_exists": 0.0,
        "artifacts_exist_raw_html": 0.0,
        "artifacts_exist_text": 0.0,
        "artifacts_exist_metadata": 0.0,
        "html_non_empty_contains_html_tag": 0.0,
        "text_non_empty_min_50_words": 0.0,
        "metadata_contains_required_keys": 0.0,
        "metadata_values_consistent": 0.0,
        "validate_script_runs_success": 0.0,
        "validation_summary_contains_pass": 0.0,
        "status_report_sections_present": 0.0,
        "status_report_refactoring_bullets_3_to_7": 0.0,
        "status_report_how_to_run_mentions_commands": 0.0,
        "metadata_url_uses_who_domain_and_configured_path": 0.0,
    }

    app_dir = workspace / "app"
    net_py = app_dir / "net.py"
    extract_py = app_dir / "extract.py"
    run_pipeline_py = workspace / "scripts" / "run_pipeline.py"
    validate_py = workspace / "scripts" / "validate.py"
    config_yaml = workspace / "input" / "config.yaml"
    status_report = workspace / "reports" / "refactor_status.md"
    validation_summary = workspace / "reports" / "validation_summary.txt"

    # App modules existence and docstrings
    if app_dir.exists() and app_dir.is_dir():
        scores["app_dir_exists"] = 1.0
    if net_py.exists() and net_py.is_file():
        scores["app_net_module_exists"] = 1.0
        if has_function_with_docstring(net_py):
            scores["net_module_has_function_docstring"] = 1.0
    if extract_py.exists() and extract_py.is_file():
        scores["app_extract_module_exists"] = 1.0
        if has_function_with_docstring(extract_py):
            scores["extract_module_has_function_docstring"] = 1.0

    # run_pipeline checks
    if run_pipeline_py.exists() and run_pipeline_py.is_file():
        scores["run_pipeline_script_exists"] = 1.0
        run_pipeline_text = read_text_safe(run_pipeline_py) or ""
        # Check that config is referenced
        if "config.yaml" in run_pipeline_text or "input/config.yaml" in run_pipeline_text:
            scores["run_pipeline_reads_config"] = 1.0
        # Check app module use
        if ("app.net" in run_pipeline_text or "from app import net" in run_pipeline_text) and (
            "app.extract" in run_pipeline_text or "from app import extract" in run_pipeline_text
        ):
            scores["run_pipeline_imports_app_modules"] = 1.0

    # validate script existence
    if validate_py.exists() and validate_py.is_file():
        scores["validate_script_exists"] = 1.0

    # Determine expected artifact paths using config if deliverables exist; avoid awarding based on config alone
    cfg = parse_simple_yaml_config(config_yaml) if config_yaml.exists() else None
    expected = default_expected_paths()
    if isinstance(cfg, dict):
        # Only trust config if pipeline and app modules exist (avoid awarding points based solely on given input)
        if scores["run_pipeline_script_exists"] == 1.0 and (
            scores["app_net_module_exists"] == 1.0 or scores["app_extract_module_exists"] == 1.0
        ):
            expected["raw_html_path"] = cfg.get("raw_html_path", expected["raw_html_path"])
            expected["text_path"] = cfg.get("text_path", expected["text_path"])
            expected["metadata_path"] = cfg.get("metadata_path", expected["metadata_path"])

    raw_html_file = workspace / expected["raw_html_path"]
    text_file = workspace / expected["text_path"]
    metadata_file = workspace / expected["metadata_path"]

    # Artifacts existence
    if raw_html_file.exists() and raw_html_file.is_file():
        scores["artifacts_exist_raw_html"] = 1.0
    if text_file.exists() and text_file.is_file():
        scores["artifacts_exist_text"] = 1.0
    if metadata_file.exists() and metadata_file.is_file():
        scores["artifacts_exist_metadata"] = 1.0

    # Raw HTML sanity
    if scores["artifacts_exist_raw_html"] == 1.0:
        raw_bytes = read_bytes_safe(raw_html_file) or b""
        raw_lower = raw_bytes.lower() if raw_bytes else b""
        if len(raw_bytes) > 0 and b"<html" in raw_lower:
            scores["html_non_empty_contains_html_tag"] = 1.0

    # Text sanity
    if scores["artifacts_exist_text"] == 1.0:
        txt = read_text_safe(text_file) or ""
        wc = count_words(txt)
        if len(txt.strip()) > 0 and wc >= 50:
            scores["text_non_empty_min_50_words"] = 1.0

    # Metadata structure and consistency
    if scores["artifacts_exist_metadata"] == 1.0:
        meta = load_json_safe(metadata_file)
        required_keys = {"url", "fetched_at", "title", "word_count", "html_bytes", "text_chars"}
        if isinstance(meta, dict) and required_keys.issubset(set(meta.keys())):
            keys_ok = True
            url_val = meta.get("url")
            # URL must reference who.int
            if not isinstance(url_val, str) or "who.int" not in (url_val or ""):
                keys_ok = False
            if not parse_iso8601(meta.get("fetched_at")):
                keys_ok = False
            if not isinstance(meta.get("title"), str):
                keys_ok = False
            for k in ("word_count", "html_bytes", "text_chars"):
                if not isinstance(meta.get(k), int):
                    keys_ok = False
                    break
            if keys_ok:
                scores["metadata_contains_required_keys"] = 1.0

            consistent = True
            # Cross-check byte/char counts
            if raw_html_file.exists():
                rb = read_bytes_safe(raw_html_file) or b""
                if meta.get("html_bytes") != len(rb):
                    consistent = False
            else:
                consistent = False
            if text_file.exists():
                t = read_text_safe(text_file) or ""
                if meta.get("text_chars") != len(t):
                    consistent = False
                if meta.get("word_count") != count_words(t):
                    consistent = False
            else:
                consistent = False
            if consistent:
                scores["metadata_values_consistent"] = 1.0

            # URL path matches configured path if config is available and deliverables exist
            if isinstance(cfg, dict):
                configured_path = cfg.get("path", "/")
                if isinstance(meta.get("url"), str) and "who.int" in meta.get("url", "") and configured_path in meta.get("url", ""):
                    scores["metadata_url_uses_who_domain_and_configured_path"] = 1.0

    # Run validation script if present
    if validate_py.exists() and validate_py.is_file():
        code, out, err = run_subprocess([sys.executable, str(validate_py)], cwd=workspace, timeout=30)
        if code == 0:
            scores["validate_script_runs_success"] = 1.0

    # Validation summary contents
    validation_summary_path = validation_summary
    if validation_summary_path.exists() and validation_summary_path.is_file():
        vs_text = read_text_safe(validation_summary_path) or ""
        if "pass" in vs_text.lower():
            scores["validation_summary_contains_pass"] = 1.0

    # Status report checks
    if status_report.exists() and status_report.is_file():
        sr_text = read_text_safe(status_report) or ""
        has_refactoring = "refactoring changes" in sr_text.lower()
        has_how_to_run = "how to run" in sr_text.lower()
        has_clinic_rel = "clinic relevance" in sr_text.lower()
        if has_refactoring and has_how_to_run and has_clinic_rel:
            scores["status_report_sections_present"] = 1.0

        _, _, ref_lines = extract_section_lines(sr_text, "Refactoring changes")
        if ref_lines:
            bullets = [ln for ln in ref_lines if ln.strip().startswith(("-", "*"))]
            if 3 <= len(bullets) <= 7:
                scores["status_report_refactoring_bullets_3_to_7"] = 1.0

        _, _, run_lines = extract_section_lines(sr_text, "How to run")
        if run_lines:
            section_text = "\n".join(run_lines).lower()
            if "scripts/run_pipeline.py" in section_text and "scripts/validate.py" in section_text and "python" in section_text:
                scores["status_report_how_to_run_mentions_commands"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()