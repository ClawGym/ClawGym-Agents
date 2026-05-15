import json
import re
import sys
from pathlib import Path
from typing import Optional, List, Tuple, Dict


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def _safe_load_json(path: Path) -> Optional[dict]:
    txt = _safe_read_text(path)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def _list_html_files(root: Path) -> List[Path]:
    if not root.exists():
        return []
    return sorted([p for p in root.rglob("*.html") if p.is_file()])


def _extract_attr_value(tag: str, name: str) -> Optional[str]:
    pattern = re.compile(r'(?i)\b' + re.escape(name) + r'\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))')
    m = pattern.search(tag)
    if not m:
        return None
    val = m.group(1) if m.group(1) is not None else (m.group(2) if m.group(2) is not None else m.group(3))
    return val


def _has_attr(tag: str, name: str) -> bool:
    return re.search(r'(?i)\b' + re.escape(name) + r'\b\s*=', tag) is not None


def _scan_file_for_issues(path: Path) -> Dict[str, dict]:
    issues = {
        "missing_or_empty_alt": {"count": 0, "lines": []},
        "http_resources": {"count": 0, "lines": []},
        "forms_missing_action": {"count": 0, "lines": []},
    }
    text = _safe_read_text(path)
    if text is None:
        return issues
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        # IMG tags
        for img_tag in re.findall(r'(?is)<\s*img\b[^>]*>', line):
            alt_present = _has_attr(img_tag, "alt")
            missing_alt = not alt_present
            empty_alt = False
            if alt_present:
                alt_val = _extract_attr_value(img_tag, "alt")
                if alt_val is not None and alt_val == "":
                    empty_alt = True
            if missing_alt or empty_alt:
                issues["missing_or_empty_alt"]["count"] += 1
                issues["missing_or_empty_alt"]["lines"].append(idx)
            src_val = _extract_attr_value(img_tag, "src")
            if src_val is not None and src_val.strip().lower().startswith("http://"):
                issues["http_resources"]["count"] += 1
                issues["http_resources"]["lines"].append(idx)

        # SCRIPT tags
        for script_tag in re.findall(r'(?is)<\s*script\b[^>]*>', line):
            src_val = _extract_attr_value(script_tag, "src")
            if src_val is not None and src_val.strip().lower().startswith("http://"):
                issues["http_resources"]["count"] += 1
                issues["http_resources"]["lines"].append(idx)

        # LINK tags with rel="stylesheet"
        for link_tag in re.findall(r'(?is)<\s*link\b[^>]*>', line):
            rel_val = _extract_attr_value(link_tag, "rel")
            if rel_val is not None and "stylesheet" in rel_val.lower():
                href_val = _extract_attr_value(link_tag, "href")
                if href_val is not None and href_val.strip().lower().startswith("http://"):
                    issues["http_resources"]["count"] += 1
                    issues["http_resources"]["lines"].append(idx)

        # FORM tags
        for form_tag in re.findall(r'(?is)<\s*form\b[^>]*>', line):
            if not _has_attr(form_tag, "action"):
                issues["forms_missing_action"]["count"] += 1
                issues["forms_missing_action"]["lines"].append(idx)

    for key in issues:
        if isinstance(issues[key], dict) and "lines" in issues[key]:
            issues[key]["lines"].sort()
    return issues


def _compute_expected(workspace: Path) -> Tuple[List[str], Dict[str, dict], Dict[str, int]]:
    input_dir = workspace / "input" / "pages"
    files = _list_html_files(input_dir)
    rel_paths = [f.relative_to(workspace).as_posix() for f in files]
    rel_paths_sorted = sorted(rel_paths)
    per_file: Dict[str, dict] = {}
    totals = {
        "missing_or_empty_alt": 0,
        "http_resources": 0,
        "forms_missing_action": 0,
    }
    for rel in rel_paths_sorted:
        abs_path = workspace / rel
        issues = _scan_file_for_issues(abs_path)
        per_file[rel] = issues
        totals["missing_or_empty_alt"] += issues["missing_or_empty_alt"]["count"]
        totals["http_resources"] += issues["http_resources"]["count"]
        totals["forms_missing_action"] += issues["forms_missing_action"]["count"]
    return rel_paths_sorted, per_file, totals


def _build_expected_doc_block(paths: List[str], per_file: Dict[str, dict], totals: Dict[str, int]) -> List[str]:
    lines = []
    lines.append("Automated HTML Audit Summary")
    lines.append(f"Totals: missing_or_empty_alt={totals['missing_or_empty_alt']}, http_resources={totals['http_resources']}, forms_missing_action={totals['forms_missing_action']}")
    lines.append("Per-file:")
    for p in paths:
        pf = per_file[p]
        a = pf["missing_or_empty_alt"]["count"]
        b = pf["http_resources"]["count"]
        c = pf["forms_missing_action"]["count"]
        lines.append(f"- {p}: missing_or_empty_alt={a}, http_resources={b}, forms_missing_action={c}")
    return lines


def _extract_marked_block(md_text: str, begin_marker: str, end_marker: str) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    lines = md_text.splitlines(keepends=True)
    begin_idx = None
    end_idx = None
    for i, ln in enumerate(lines):
        if begin_marker in ln:
            begin_idx = i
            break
    if begin_idx is None:
        return False, None, None, None
    for j in range(begin_idx + 1, len(lines)):
        if end_marker in lines[j]:
            end_idx = j
            break
    if end_idx is None:
        return False, None, None, None
    before = "".join(lines[: begin_idx + 1])
    block = "".join(lines[begin_idx + 1 : end_idx])
    after = "".join(lines[end_idx:])
    return True, before, block, after


def _normalize_block_lines(block: str) -> List[str]:
    raw_lines = block.splitlines()
    stripped = [ln.rstrip() for ln in raw_lines]
    start = 0
    while start < len(stripped) and stripped[start].strip() == "":
        start += 1
    end = len(stripped)
    while end > start and stripped[end - 1].strip() == "":
        end -= 1
    return stripped[start:end]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "perl_script_exists": 0.0,
        "report_json_parse": 0.0,
        "report_structure": 0.0,
        "report_files_sorted_paths": 0.0,
        "report_counts_lines_correct": 0.0,
        "report_totals_correct": 0.0,
        "docs_block_content_correct": 0.0,
        "email_headers_present": 0.0,
        "email_totals_correct": 0.0,
        "email_per_file_correct_order": 0.0,
        "email_review_line_present": 0.0,
    }

    expected_paths, expected_per_file, expected_totals = _compute_expected(workspace)

    # Check Perl script existence
    perl_path = workspace / "scripts" / "audit_html.pl"
    if perl_path.exists() and perl_path.is_file():
        scores["perl_script_exists"] = 1.0

    # Check audit_report.json correctness
    report_path = workspace / "output" / "audit_report.json"
    report_data = _safe_load_json(report_path)
    if report_data is not None:
        scores["report_json_parse"] = 1.0
        structure_ok = (
            isinstance(report_data, dict)
            and "files" in report_data
            and "totals" in report_data
            and isinstance(report_data.get("files"), list)
            and isinstance(report_data.get("totals"), dict)
        )
        if structure_ok:
            totals_obj = report_data["totals"]
            expected_total_keys = {"missing_or_empty_alt", "http_resources", "forms_missing_action"}
            if set(totals_obj.keys()) == expected_total_keys and all(isinstance(totals_obj[k], int) for k in expected_total_keys):
                scores["report_structure"] = 1.0

            files_list = report_data["files"]
            actual_paths = []
            files_entries_ok = True
            for entry in files_list:
                if not isinstance(entry, dict) or "path" not in entry:
                    files_entries_ok = False
                    break
                actual_paths.append(entry["path"])
            if files_entries_ok and actual_paths == expected_paths:
                scores["report_files_sorted_paths"] = 1.0

            counts_ok = True
            lines_sorted_ok = True
            if files_entries_ok and actual_paths == expected_paths:
                for entry in files_list:
                    p = entry["path"]
                    exp = expected_per_file.get(p, None)
                    if exp is None:
                        counts_ok = False
                        break
                    for key in ["missing_or_empty_alt", "http_resources", "forms_missing_action"]:
                        if key not in entry or not isinstance(entry[key], dict):
                            counts_ok = False
                            break
                        ec = entry[key].get("count", None)
                        elines = entry[key].get("lines", None)
                        if not isinstance(ec, int) or not isinstance(elines, list) or not all(isinstance(x, int) for x in elines):
                            counts_ok = False
                            break
                        if elines != sorted(elines):
                            lines_sorted_ok = False
                        if ec != exp[key]["count"] or elines != exp[key]["lines"]:
                            counts_ok = False
                            break
                    if not counts_ok:
                        break
            if counts_ok and lines_sorted_ok:
                scores["report_counts_lines_correct"] = 1.0

            totals_ok = (
                totals_obj.get("missing_or_empty_alt") == expected_totals["missing_or_empty_alt"]
                and totals_obj.get("http_resources") == expected_totals["http_resources"]
                and totals_obj.get("forms_missing_action") == expected_totals["forms_missing_action"]
            )
            if totals_ok:
                scores["report_totals_correct"] = 1.0

    # Check docs/audit_summary.md updated block
    docs_path = workspace / "docs" / "audit_summary.md"
    md_text = _safe_read_text(docs_path)
    begin_marker = "<!-- BEGIN AUTO-AUDIT -->"
    end_marker = "<!-- END AUTO-AUDIT -->"
    if md_text is not None:
        found, before, block, after = _extract_marked_block(md_text, begin_marker, end_marker)
        if found and before is not None and block is not None and after is not None:
            expected_block_lines = _build_expected_doc_block(expected_paths, expected_per_file, expected_totals)
            actual_block_lines = _normalize_block_lines(block)
            if actual_block_lines == expected_block_lines:
                scores["docs_block_content_correct"] = 1.0

    # Check email draft
    email_path = workspace / "output" / "audit_email_draft.txt"
    email_text = _safe_read_text(email_path)
    if email_text is not None:
        lines = [ln.rstrip("\r\n") for ln in email_text.splitlines()]
        to_ok = any(ln.strip() == "To: web-qa@example.com" for ln in lines)
        subj_ok = any(ln.strip() == "Subject: Weekly HTML audit results" for ln in lines)
        if to_ok and subj_ok:
            scores["email_headers_present"] = 1.0

        totals_line = f"Totals: missing_or_empty_alt={expected_totals['missing_or_empty_alt']}, http_resources={expected_totals['http_resources']}, forms_missing_action={expected_totals['forms_missing_action']}"
        totals_ok = any(ln.strip() == totals_line for ln in lines)
        if totals_ok:
            scores["email_totals_correct"] = 1.0

        expected_lines = []
        for p in expected_paths:
            pf = expected_per_file[p]
            a = pf["missing_or_empty_alt"]["count"]
            b = pf["http_resources"]["count"]
            c = pf["forms_missing_action"]["count"]
            expected_lines.append(f"{p}: missing_or_empty_alt={a}, http_resources={b}, forms_missing_action={c}")

        idx_positions = []
        all_found = True
        start_search = 0
        for exp in expected_lines:
            found_idx = None
            for i in range(start_search, len(lines)):
                stripped = lines[i].strip()
                if stripped == exp or stripped == f"- {exp}":
                    found_idx = i
                    break
            if found_idx is None:
                all_found = False
                break
            idx_positions.append(found_idx)
            start_search = found_idx + 1
        if all_found and idx_positions == sorted(idx_positions):
            scores["email_per_file_correct_order"] = 1.0

        last_non_empty = None
        for ln in reversed(lines):
            if ln.strip() != "":
                last_non_empty = ln.strip()
                break
        if last_non_empty == "Please review by EOD.":
            scores["email_review_line_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()