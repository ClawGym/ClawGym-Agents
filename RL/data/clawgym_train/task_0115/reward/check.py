import json
import csv
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# ------------------------
# Helper functions
# ------------------------

def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None

def write_json(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))

def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))

def first_paragraph(text: str) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    paras = []
    cur = []
    for ln in lines:
        if ln.strip() == "":
            if cur:
                paras.append(" ".join(cur))
                cur = []
            else:
                # consecutive blank lines -> skip
                pass
        else:
            cur.append(ln.strip())
    if cur:
        paras.append(" ".join(cur))
    return paras[0] if paras else ""

def discover_svgs(base_dir: Path) -> List[Path]:
    svgs: List[Path] = []
    if base_dir.is_dir():
        for p in base_dir.rglob("*.svg"):
            if p.is_file():
                svgs.append(p.resolve())
    svgs.sort()
    return svgs

def run_analyzer(workspace: Path, target_dir: Path) -> Tuple[Optional[str], Optional[str]]:
    script = workspace / "tools" / "analyze_svg.py"
    if not script.exists():
        return None, None
    try:
        proc = subprocess.run(
            ["python3", str(script), str(target_dir)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            check=False,
        )
        return proc.stdout, proc.stderr
    except Exception:
        return None, None

def load_jsonl_text(text: str) -> Optional[List[dict]]:
    results: List[dict] = []
    try:
        for line in text.splitlines():
            if line.strip() == "":
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                return None
            results.append(obj)
        return results
    except Exception:
        return None

def safe_load_jsonl_file(path: Path) -> Optional[List[dict]]:
    t = read_text(path)
    if t is None:
        return None
    return load_jsonl_text(t)

def parse_error_log(stderr_text: str) -> Dict[str, str]:
    """
    Parses lines like:
    ERROR /abs/path/to/file.svg: some error message details
    Returns mapping of posix-absolute-path -> error_message
    """
    mapping: Dict[str, str] = {}
    if not stderr_text:
        return mapping
    for line in stderr_text.splitlines():
        line = line.strip()
        if not line.startswith("ERROR"):
            continue
        # Accept both "ERROR path: msg" and "ERROR: Not a directory: ..."
        m = re.match(r"^ERROR\s+(.+?):\s*(.+)$", line)
        if m:
            pth = m.group(1).strip()
            msg = m.group(2).strip()
            # Normalize path separators to posix style
            try:
                posix = str(Path(pth).resolve()).replace("\\", "/")
                mapping[posix] = msg
            except Exception:
                # If path resolution fails, keep raw
                mapping[pth.replace("\\", "/")] = msg
        else:
            # fallback: if pattern is "ERROR: message", we skip as it doesn't map to a file
            pass
    return mapping

def parse_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[dict]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None, None
    try:
        # csv module can handle various newline forms
        rows: List[dict] = []
        # Extract header manually to preserve exact header order for validation
        first_line = text.splitlines()[0] if text.splitlines() else ""
        header = [h.strip() for h in next(csv.reader([first_line]))] if first_line else []
        reader = csv.DictReader(text.splitlines())
        for row in reader:
            rows.append(row)
        return header, rows
    except Exception:
        return None, None

def extract_approved_hex_codes(guidelines_path: Path) -> Optional[set]:
    text = read_text(guidelines_path)
    if text is None:
        return None
    # Extract hex codes from Approved color hex codes section
    # Use simple regex for #RRGGBB
    hexes = set([m.group(0).upper() for m in re.finditer(r"#(?:[0-9a-fA-F]{6})", text)])
    return hexes

def jsonl_to_analysis_map(jsonl: List[dict]) -> Dict[str, dict]:
    """
    Map posix-absolute-path -> analysis dict with colors and stroke_widths
    """
    mapping: Dict[str, dict] = {}
    for obj in jsonl:
        f = obj.get("file")
        if not isinstance(f, str):
            continue
        posix = f.replace("\\", "/")
        mapping[posix] = obj
    return mapping

def resolve_csv_file_to_abs(workspace: Path, csv_path_value: str, discovered: List[Path]) -> Optional[Path]:
    """
    Attempt to resolve the 'file' field from CSV to an absolute discovered Path.
    Try absolute, then relative to workspace, then match by basename.
    """
    if not csv_path_value or not isinstance(csv_path_value, str):
        return None
    cand = Path(csv_path_value)
    if cand.is_absolute() and cand.exists():
        return cand.resolve()
    cand2 = (workspace / csv_path_value).resolve()
    if cand2.exists():
        return cand2
    # Match by basename among discovered
    basename = Path(csv_path_value).name
    matches = [p for p in discovered if p.name == basename]
    if len(matches) == 1:
        return matches[0]
    return None

def parse_bool_cell(val: str) -> Optional[bool]:
    if val is None:
        return None
    s = str(val).strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    return None

def split_semicolon_list(val: str) -> List[str]:
    if val is None:
        return []
    s = str(val).strip()
    if s == "":
        return []
    parts = [p.strip() for p in s.split(";")]
    # preserve order, but normalize multiple empty to filtered
    return [p for p in parts if p != ""]

def join_semicolon_list(vals: List[str]) -> str:
    return ";".join(vals)

def compute_expected_compliance(approved: set, colors: List[str], stroke_widths: List[str]) -> Tuple[bool, bool, bool]:
    palette_ok = all(c.upper() in approved for c in colors)
    color_count_ok = len(set([c.upper() for c in colors])) <= 3
    # stroke_ok: all strokes exactly 1.5px when any; if none, it's OK
    if len(stroke_widths) == 0:
        stroke_ok = True
    else:
        stroke_ok = all(sw == "1.5px" for sw in stroke_widths)
    return palette_ok, stroke_ok, color_count_ok

def summarize_error_message(err_msg: str) -> str:
    # Return a shorter substring suitable for searching presence in summary
    if not err_msg:
        return ""
    # Take first 40 chars as representative
    return err_msg[:40]

# ------------------------
# Grader
# ------------------------

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    assets_dir = workspace / "assets" / "insignia"
    outputs_dir = workspace / "outputs"
    raw_dir = outputs_dir / "raw"
    analysis_jsonl_path = raw_dir / "analysis.jsonl"
    analyze_errors_log_path = raw_dir / "analyze_errors.log"
    matrix_csv_path = outputs_dir / "compliance_matrix.csv"
    summary_md_path = outputs_dir / "compliance_summary.md"
    email_short_path = outputs_dir / "email_update_short.txt"
    guidelines_path = workspace / "input" / "brand_guidelines.md"

    scores = {
        "analyzer_stdout_captured_match": 0.0,
        "analyzer_stderr_captured_match": 0.0,
        "matrix_header_correct": 0.0,
        "matrix_covers_all_svgs": 0.0,
        "matrix_values_correct": 0.0,
        "summary_intro_length_ok": 0.0,
        "summary_script_run_details_ok": 0.0,
        "summary_lists_all_svgs": 0.0,
        "email_short_length_ok": 0.0,
        "email_short_required_points": 0.0,
    }

    # Discover svg files
    discovered_svgs = discover_svgs(assets_dir)

    # Run analyzer to compute expected stdout/stderr
    exp_stdout, exp_stderr = run_analyzer(workspace, assets_dir)

    # Check outputs/raw/analysis.jsonl matches expected stdout
    actual_analysis_text = read_text(analysis_jsonl_path)
    if exp_stdout is not None and actual_analysis_text is not None:
        # Compare exact content
        if actual_analysis_text == exp_stdout:
            scores["analyzer_stdout_captured_match"] = 1.0
    # Check outputs/raw/analyze_errors.log matches expected stderr
    actual_errors_text = read_text(analyze_errors_log_path)
    if exp_stderr is not None and actual_errors_text is not None:
        if actual_errors_text == exp_stderr:
            scores["analyzer_stderr_captured_match"] = 1.0

    # Load guidelines for approved colors
    approved_hexes = extract_approved_hex_codes(guidelines_path) or set()

    # Build expected per-file analysis map and error map
    exp_analysis_map: Dict[str, dict] = {}
    exp_error_map: Dict[str, str] = {}
    if exp_stdout is not None:
        exp_jsonl = load_jsonl_text(exp_stdout) or []
        exp_analysis_map = jsonl_to_analysis_map(exp_jsonl)
    if exp_stderr is not None:
        exp_error_map = parse_error_log(exp_stderr)

    # Compliance matrix: header
    header, rows = parse_csv(matrix_csv_path)
    expected_header = ["file", "colors_used", "stroke_widths", "palette_ok", "stroke_ok", "color_count_ok", "parse_error"]
    if header is not None and header == expected_header:
        scores["matrix_header_correct"] = 1.0

    # Compliance matrix: coverage and values
    coverage_ok = False
    values_ok = False
    if rows is not None:
        # Build discovered set for mapping
        discovered_set = set([p.resolve() for p in discovered_svgs])
        # Map CSV rows by resolved absolute path
        csv_map: Dict[Path, dict] = {}
        for row in rows:
            csv_file_val = row.get("file", "")
            resolved = resolve_csv_file_to_abs(workspace, csv_file_val, discovered_svgs)
            if resolved is not None:
                csv_map[resolved] = row
        # Coverage: exactly all discovered once
        if set(csv_map.keys()) == discovered_set and len(csv_map) == len(discovered_set):
            coverage_ok = True
            scores["matrix_covers_all_svgs"] = 1.0
        # Values:
        all_ok = True
        for fpath in discovered_svgs:
            row = csv_map.get(fpath)
            if not row:
                all_ok = False
                continue
            # Determine expected based on exp_analysis_map / exp_error_map
            posix_abs = str(fpath.resolve()).replace("\\", "/")
            parse_error_expected = exp_error_map.get(posix_abs)
            # Parse actual row
            colors_used_list = split_semicolon_list(row.get("colors_used", ""))
            stroke_widths_list = split_semicolon_list(row.get("stroke_widths", ""))
            palette_ok_val = parse_bool_cell(row.get("palette_ok"))
            stroke_ok_val = parse_bool_cell(row.get("stroke_ok"))
            color_count_ok_val = parse_bool_cell(row.get("color_count_ok"))
            parse_error_val = (row.get("parse_error") or "").strip()
            # Validate
            if parse_error_expected:
                # For parse error files, booleans must be false and parse_error must match exactly the error message
                if palette_ok_val is not False or stroke_ok_val is not False or color_count_ok_val is not False:
                    all_ok = False
                if parse_error_val != parse_error_expected:
                    all_ok = False
                # Do not strictly check colors_used and stroke_widths for parse-error files
            else:
                # Must have empty parse_error
                if parse_error_val != "":
                    all_ok = False
                # Must match analysis data for colors and stroke widths
                analysis = exp_analysis_map.get(posix_abs)
                if not analysis:
                    all_ok = False
                else:
                    exp_colors = list(analysis.get("colors") or [])
                    exp_strokes = list(analysis.get("stroke_widths") or [])
                    # Expect semicolon-joined strings equal and uppercase hex
                    if colors_used_list != exp_colors:
                        all_ok = False
                    if stroke_widths_list != exp_strokes:
                        all_ok = False
                    # Compute expected booleans
                    palette_ok_exp, stroke_ok_exp, color_count_ok_exp = compute_expected_compliance(approved_hexes, exp_colors, exp_strokes)
                    if palette_ok_val is None or stroke_ok_val is None or color_count_ok_val is None:
                        all_ok = False
                    else:
                        if not (palette_ok_val == palette_ok_exp and stroke_ok_val == stroke_ok_exp and color_count_ok_val == color_count_ok_exp):
                            all_ok = False
        if all_ok:
            values_ok = True
            scores["matrix_values_correct"] = 1.0

    # Summary checks
    summary_text = read_text(summary_md_path) or ""
    if summary_text:
        # Intro length: first paragraph ≤120 words
        intro = first_paragraph(summary_text)
        if count_words(intro) <= 120:
            scores["summary_intro_length_ok"] = 1.0

        # Script run details: presence of section, command string, counts, and error summary
        has_section = re.search(r"script run details", summary_text, flags=re.IGNORECASE) is not None
        has_cmd = ("python3" in summary_text) and ("tools/analyze_svg.py" in summary_text) and ("assets/insignia" in summary_text)
        # Compute expected counts from discovered and analyzer results
        discovered_count = len(discovered_svgs)
        success_count = len(exp_analysis_map) if exp_analysis_map else 0
        error_count = len(exp_error_map) if exp_error_map else max(0, discovered_count - success_count)
        # Try to find numbers near context words
        def has_count(keyword: str, n: int) -> bool:
            pattern = re.compile(rf"{keyword}[^0-9]*{n}\b", flags=re.IGNORECASE)
            return pattern.search(summary_text) is not None
        has_discovered = has_count("discover", discovered_count)
        has_analyzed = has_count("analy", success_count) or has_count("success", success_count)
        has_errors = has_count("error", error_count) or has_count("parse", error_count)
        # Error message summarized
        err_msg_present = True
        if actual_errors_text:
            # Extract a representative error message
            err_map = parse_error_log(actual_errors_text)
            if err_map:
                # Use any one of the messages
                any_msg = next(iter(err_map.values()))
                frag = summarize_error_message(any_msg)
                if frag and (frag not in summary_text):
                    err_msg_present = False
        if has_section and has_cmd and has_discovered and has_analyzed and has_errors and err_msg_present:
            scores["summary_script_run_details_ok"] = 1.0

        # Checklist/table includes every .svg
        all_names_present = True
        for p in discovered_svgs:
            if p.name not in summary_text:
                all_names_present = False
                break
        # Also ensure references to rule categories exist somewhere
        rules_keywords_ok = all(k in summary_text.lower() for k in ["palette", "stroke", "color"])
        if all_names_present and rules_keywords_ok:
            scores["summary_lists_all_svgs"] = 1.0

    # Email short checks
    email_text = read_text(email_short_path) or ""
    if email_text:
        if count_words(email_text) <= 90:
            scores["email_short_length_ok"] = 1.0
        lower = email_text.lower()
        has_audit = ("audit" in lower) or ("audited" in lower) or ("assessment" in lower) or ("review" in lower)
        has_non_compliance = ("non-compliance" in lower) or ("noncompliance" in lower) or ("issues" in lower) or ("non compliant" in lower) or ("findings" in lower)
        has_color = "color" in lower or "colour" in lower
        has_stroke = "stroke" in lower
        has_eta = ("2 business days" in lower) or ("two business days" in lower)
        if has_audit and has_non_compliance and has_color and has_stroke and has_eta:
            scores["email_short_required_points"] = 1.0

    return scores

# ------------------------
# Main entrypoint
# ------------------------

def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()