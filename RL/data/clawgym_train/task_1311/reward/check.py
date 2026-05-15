import json
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, Dict, List

# Baseline README content from task inputs for unchanged-sections comparison
ORIGINAL_README = """# Orders, Decorations, and Medals of Canada — Working Manuscript

This repository contains the working files for a historian’s manuscript examining the evolution of Canada’s system of honours and orders, with emphasis on the Order of Canada and related decorations. The project includes text chapters, image assets of insignia, and build scripts for PDF proofing.

## Introduction
This manuscript surveys the development of modern Canadian honours, including the establishment of the Order of Canada (1967), the Order of Military Merit, and related decorations. It integrates archival findings with a catalogue of insignia and ribbons.

## Current Build Notes
Draft chapters are prepared in Markdown. The planned build workflow uses pandoc and a LaTeX engine to produce PDFs for internal review. Before the final indexing pass, we must confirm environment readiness.

## System Requirements (to be updated)
The following placeholder checklist is outdated and must be refreshed based on a live audit:
- OS kernel: (update)
- Python 3: (update)
- Pandoc: (update)
- LaTeX (pdflatex): (update)
- Disk space (working dir): (should be ≥ 2 GB free)
- Locale support: en_CA (update)

Please replace this entire section with a concise, current summary derived from a fresh system audit.

## File Structure
- manuscript/ — chapter drafts and notes
- figures/ — insignia and ribbon images (TIFF/PNG)
- build/ — scripts and templates for PDF rendering

## Contact
For questions about the manuscript or build process, contact the project maintainer.
"""

ERROR_TOKENS = [
    "command not found",
    "not found",
    "no such file or directory",
    "is not recognized",
    "cannot execute",
    "not installed",
    "failed",
    "error",
]


def read_text_safe(path: Path) -> Optional[str]:
    try:
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def normalize_newlines(s: str) -> str:
    return "\n".join([line.rstrip() for line in s.replace("\r\n", "\n").replace("\r", "\n").split("\n")])


def contains_error_text(text: str) -> bool:
    tl = text.lower()
    return any(tok in tl for tok in ERROR_TOKENS)


def first_nonempty_line(text: str) -> str:
    for ln in text.splitlines():
        l = ln.strip()
        if l:
            return l
    return ""


def extract_python_version(text: str) -> Optional[str]:
    m = re.search(r"\bPython\s+([0-9]+(?:\.[0-9]+)+)", text)
    return m.group(1) if m else None


def extract_pandoc_version(text: str) -> Optional[str]:
    for line in text.splitlines():
        m = re.match(r"\s*pandoc\s+([0-9]+(?:\.[0-9]+)+)", line.strip())
        if m:
            return m.group(1)
    return None


def extract_pdflatex_version(text: str) -> Optional[str]:
    line = first_nonempty_line(text)
    m = re.search(r"([0-9]+(?:\.[0-9]+)+)", line)
    return m.group(1) if m else None


def parse_df_available(text: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Parse 'df -h .' output and return (available_bytes, raw_avail_token_str)
    Returns (None, None) if cannot parse.
    """
    if not text or contains_error_text(text):
        return (None, None)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return (None, None)
    header = lines[0]
    data_line = lines[1]
    header_cols = re.split(r"\s+", header.strip())
    data_cols = re.split(r"\s+", data_line.strip())

    avail_idx = None
    for idx, col in enumerate(header_cols):
        if col.lower().startswith("avail"):
            avail_idx = idx
            break

    avail_token = None
    if avail_idx is not None and avail_idx < len(data_cols):
        avail_token = data_cols[avail_idx]
    else:
        m = re.search(r"(\d+(?:\.\d+)?\s*[KMGTPE]i?B?|\d+(?:\.\d+)?[KMGTPE])", data_line)
        if m:
            avail_token = m.group(1)

    if not avail_token:
        return (None, None)

    bytes_val = human_to_bytes(avail_token)
    return (bytes_val, avail_token)


def human_to_bytes(token: str) -> Optional[float]:
    """
    Convert a human-readable size string (e.g., '30G', '29.8Gi', '1024M', '123B') to bytes.
    Returns None if cannot parse.
    """
    t = token.strip()
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGTP]i?B?|[KMGTP]i?|[KMGTP]|B|Bytes?)?\s*$", t, re.IGNORECASE)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "").strip().lower()

    if unit in ("", "b", "byte", "bytes"):
        factor = 1
    elif unit in ("k", "kb"):
        factor = 1000 ** 1
    elif unit in ("m", "mb"):
        factor = 1000 ** 2
    elif unit in ("g", "gb"):
        factor = 1000 ** 3
    elif unit in ("t", "tb"):
        factor = 1000 ** 4
    elif unit in ("p", "pb"):
        factor = 1000 ** 5
    elif unit in ("ki", "kib"):
        factor = 1024 ** 1
    elif unit in ("mi", "mib"):
        factor = 1024 ** 2
    elif unit in ("gi", "gib"):
        factor = 1024 ** 3
    elif unit in ("ti", "tib"):
        factor = 1024 ** 4
    elif unit in ("pi", "pib"):
        factor = 1024 ** 5
    else:
        unit2 = unit.lower()
        if unit2.endswith("ib"):
            base = unit2[:-2]
            mapping = {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4, "p": 1024 ** 5}
            factor = mapping.get(base, None)
        elif unit2.endswith("i"):
            base = unit2[:-1]
            mapping = {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4, "p": 1024 ** 5}
            factor = mapping.get(base, None)
        else:
            factor = None
    if factor is None:
        return None
    return num * factor


def parse_locale_en_ca_presence(text: str) -> Tuple[str, bool]:
    """
    Returns ('Unknown'|'Known', present_bool_if_known)
    """
    if text is None or text.strip() == "":
        return ("Unknown", False)
    if contains_error_text(text):
        return ("Unknown", False)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    present = any(re.match(r"^en_CA(\.|$)", ln) for ln in lines)
    return ("Known", present)


def compute_expected_statuses(workspace: Path) -> Dict[str, dict]:
    raw_dir = workspace / "system_status" / "raw"
    contents = {
        "uname": read_text_safe(raw_dir / "uname.txt"),
        "python3": read_text_safe(raw_dir / "python3.txt"),
        "pandoc": read_text_safe(raw_dir / "pandoc.txt"),
        "pdflatex": read_text_safe(raw_dir / "pdflatex.txt"),
        "df": read_text_safe(raw_dir / "df.txt"),
        "locale": read_text_safe(raw_dir / "locale.txt"),
    }

    expected = {}

    uname_text = contents["uname"]
    if uname_text and not contains_error_text(uname_text):
        uname_detail = first_nonempty_line(uname_text)
        expected["uname"] = {"status": "Present", "detail": uname_detail}
    else:
        expected["uname"] = {"status": "Missing", "error": first_nonempty_line(uname_text or "")}

    py_text = contents["python3"]
    py_ver = None
    if py_text and not contains_error_text(py_text):
        py_ver = extract_python_version(py_text)
    if py_ver:
        expected["python3"] = {"status": "Present", "version": py_ver}
    else:
        expected["python3"] = {"status": "Missing", "error": first_nonempty_line(py_text or "")}

    pandoc_text = contents["pandoc"]
    pandoc_ver = None
    if pandoc_text and not contains_error_text(pandoc_text):
        pandoc_ver = extract_pandoc_version(pandoc_text)
    if pandoc_ver:
        expected["pandoc"] = {"status": "Present", "version": pandoc_ver}
    else:
        expected["pandoc"] = {"status": "Missing", "error": first_nonempty_line(pandoc_text or "")}

    pdf_text = contents["pdflatex"]
    pdf_ver = None
    if pdf_text and not contains_error_text(pdf_text):
        pdf_ver = extract_pdflatex_version(pdf_text)
    if pdf_ver:
        expected["pdflatex"] = {"status": "Present", "version": pdf_ver}
    else:
        expected["pdflatex"] = {"status": "Missing", "error": first_nonempty_line(pdf_text or "")}

    df_text = contents["df"]
    avail_bytes, avail_token = parse_df_available(df_text or "")
    if avail_bytes is None:
        expected["disk"] = {"label": "Unknown", "available_bytes": None, "token": None}
    else:
        threshold = 2 * (1024 ** 3)
        label = "Sufficient" if avail_bytes >= threshold else "Low"
        expected["disk"] = {"label": label, "available_bytes": avail_bytes, "token": avail_token}

    loc_text = contents["locale"]
    known_or_unknown, present = parse_locale_en_ca_presence(loc_text or "")
    if known_or_unknown == "Unknown":
        expected["locale"] = {"status": "Unknown"}
    else:
        expected["locale"] = {"status": "Present" if present else "Missing"}

    return expected


def section_between(text: str, start_heading: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extract the section body between a heading that starts with start_heading (exact match)
    and the next '## ' heading. Returns (prefix, section_body, suffix).
    If not found, returns (None, None, None).
    """
    text_nl = normalize_newlines(text)
    lines = text_nl.split("\n")
    start_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == start_heading:
            start_idx = i
            break
    if start_idx is None:
        return (None, None, None)
    end_idx = None
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("## ") and j > start_idx:
            end_idx = j
            break
    if end_idx is None:
        end_idx = len(lines)
    prefix = "\n".join(lines[:start_idx])
    body = "\n".join(lines[start_idx + 1:end_idx])
    suffix = "\n".join(lines[end_idx:])
    return (prefix, body, suffix)


def find_line_with_terms(lines: List[str], required_terms: List[str]) -> Optional[str]:
    for ln in lines:
        check = ln.lower()
        if all(term.lower() in check for term in required_terms):
            return ln
    return None


def has_timestamped_header(report_text: str) -> bool:
    lines = [ln.strip() for ln in report_text.splitlines() if ln.strip()]
    for i in range(min(5, len(lines))):
        ln = lines[i]
        if ln.startswith("#"):
            if re.search(r"\d{4}-\d{1,2}-\d{1,2}", ln) or re.search(r"\d{1,2}:\d{2}", ln):
                return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "raw_uname_saved": 0.0,
        "raw_python3_saved": 0.0,
        "raw_pandoc_saved": 0.0,
        "raw_pdflatex_saved": 0.0,
        "raw_df_saved": 0.0,
        "raw_locale_saved": 0.0,
        "audit_report_header_timestamped": 0.0,
        "audit_report_findings_section": 0.0,
        "audit_report_statuses_correct": 0.0,
        "audit_report_error_references": 0.0,
        "audit_report_action_items_present": 0.0,
        "readme_section_replaced": 0.0,
        "readme_statuses_correct": 0.0,
        "readme_other_sections_unchanged": 0.0,
    }

    # Raw files checks
    raw_dir = workspace / "system_status" / "raw"
    raw_files = {
        "raw_uname_saved": raw_dir / "uname.txt",
        "raw_python3_saved": raw_dir / "python3.txt",
        "raw_pandoc_saved": raw_dir / "pandoc.txt",
        "raw_pdflatex_saved": raw_dir / "pdflatex.txt",
        "raw_df_saved": raw_dir / "df.txt",
        "raw_locale_saved": raw_dir / "locale.txt",
    }
    raw_contents = {}
    for key, path in raw_files.items():
        text = read_text_safe(path)
        raw_contents[key] = text
        if text is not None and text.strip() != "":
            scores[key] = 1.0
        else:
            scores[key] = 0.0

    # Compute expected statuses from raw outputs
    expected = compute_expected_statuses(workspace)

    # Audit report checks
    audit_path = workspace / "system_status" / "audit_report.md"
    audit_text = read_text_safe(audit_path)
    if audit_text:
        # Timestamped header
        if has_timestamped_header(audit_text):
            scores["audit_report_header_timestamped"] = 1.0

        # Findings section present
        audit_norm = normalize_newlines(audit_text)
        audit_lines = audit_norm.split("\n")
        findings_present = any(ln.strip().lower().startswith("##") and "findings" in ln.strip().lower() for ln in audit_lines)
        if findings_present:
            scores["audit_report_findings_section"] = 1.0

        # Status correctness
        status_ok = True
        os_line = find_line_with_terms(audit_lines, ["os kernel", "uname"])
        py_line = find_line_with_terms(audit_lines, ["python 3"])
        pandoc_line = find_line_with_terms(audit_lines, ["pandoc"])
        latex_line = find_line_with_terms(audit_lines, ["latex", "pdflatex"])
        disk_line = find_line_with_terms(audit_lines, ["disk space", "working"])
        locale_line = find_line_with_terms(audit_lines, ["locale", "en_ca"])

        def line_has_status(line: Optional[str], must: str) -> bool:
            if not line:
                return False
            return ("status:" in line.lower()) and (must.lower() in line.lower())

        must = expected["uname"]["status"]
        status_ok &= line_has_status(os_line, must)

        must = expected["python3"]["status"]
        status_ok &= line_has_status(py_line, must)

        must = expected["pandoc"]["status"]
        status_ok &= line_has_status(pandoc_line, must)

        must = expected["pdflatex"]["status"]
        status_ok &= line_has_status(latex_line, must)

        must_disk = expected["disk"]["label"]
        if disk_line:
            status_ok &= ("sufficient" in disk_line.lower() or "low" in disk_line.lower() or "unknown" in disk_line.lower())
            if must_disk != "Unknown":
                status_ok &= (must_disk.lower() in disk_line.lower())
                status_ok &= bool(re.search(r"\d", disk_line))
        else:
            status_ok = False

        must_loc = expected["locale"]["status"]
        status_ok &= line_has_status(locale_line, must_loc)

        scores["audit_report_statuses_correct"] = 1.0 if status_ok else 0.0

        # Error references for Missing tools
        error_ref_ok = True
        item_lines_map = {
            "uname": os_line,
            "python3": py_line,
            "pandoc": pandoc_line,
            "pdflatex": latex_line,
        }
        for tool_key, line in item_lines_map.items():
            if expected.get(tool_key, {}).get("status") == "Missing":
                if not line:
                    error_ref_ok = False
                    continue
                expected_raw_name = f"{tool_key}.txt" if tool_key != "pdflatex" else "pdflatex.txt"
                raw_ref_ok = ("system_status/raw/" in line) and (expected_raw_name in line)
                excerpt = expected[tool_key].get("error", "")
                excerpt = excerpt.strip()
                excerpt_ok = True
                if excerpt:
                    snippet = excerpt[:20]
                    excerpt_ok = (snippet.lower() in line.lower())
                else:
                    excerpt_ok = False
                if not (raw_ref_ok and excerpt_ok):
                    error_ref_ok = False
        scores["audit_report_error_references"] = 1.0 if error_ref_ok else 0.0

        # Action Items section enumerates issues
        action_present = any(ln.strip().lower().startswith("##") and "action items" in ln.strip().lower() for ln in audit_lines)
        action_ok = False
        if action_present:
            prefix, body, suffix = section_between(audit_norm, "## Action Items")
            body_text = body or ""
            issues = []
            for tool_key, label_terms in [
                ("uname", ["OS kernel", "uname"]),
                ("python3", ["Python 3"]),
                ("pandoc", ["Pandoc"]),
                ("pdflatex", ["LaTeX", "pdflatex"]),
            ]:
                if expected.get(tool_key, {}).get("status") == "Missing":
                    issues.append(label_terms[0])
            if expected["disk"]["label"] == "Low":
                issues.append("Disk space")
            if expected["locale"]["status"] in ("Unknown", "Missing"):
                issues.append("Locale")
            if issues:
                action_ok = all(any(term.lower() in ln.lower() for ln in body_text.splitlines()) for term in issues)
            else:
                action_ok = True
        scores["audit_report_action_items_present"] = 1.0 if (action_present and action_ok) else 0.0
    else:
        scores["audit_report_header_timestamped"] = 0.0
        scores["audit_report_findings_section"] = 0.0
        scores["audit_report_statuses_correct"] = 0.0
        scores["audit_report_error_references"] = 0.0
        scores["audit_report_action_items_present"] = 0.0

    # README checks
    readme_path = workspace / "docs" / "README.md"
    readme_text = read_text_safe(readme_path)
    if readme_text:
        readme_norm = normalize_newlines(readme_text)

        has_new_heading = "## System Requirements" in readme_norm
        has_old_heading = "## System Requirements (to be updated)" in readme_norm
        if has_new_heading and not has_old_heading:
            scores["readme_section_replaced"] = 1.0

        prefix, section_body, suffix = section_between(readme_norm, "## System Requirements")
        if section_body is not None:
            section_lines = [ln for ln in section_body.split("\n") if ln.strip()]

            def find_line_for(label_terms: List[str]) -> Optional[str]:
                return find_line_with_terms(section_lines, [t.lower() for t in label_terms])

            os_ln = find_line_for(["OS kernel"])
            py_ln = find_line_for(["Python 3"])
            pandoc_ln = find_line_for(["Pandoc"])
            latex_ln = find_line_for(["LaTeX", "pdflatex"])
            disk_ln = find_line_for(["Disk space"])
            locale_ln = find_line_for(["Locale", "en_CA"])

            all_present = all([os_ln, py_ln, pandoc_ln, latex_ln, disk_ln, locale_ln])
            statuses_ok = all_present

            def line_has_keyword(line: Optional[str], keyword: str) -> bool:
                return bool(line and keyword.lower() in line.lower())

            expected_statuses = compute_expected_statuses(workspace)
            if statuses_ok:
                statuses_ok &= line_has_keyword(os_ln, expected_statuses["uname"]["status"])
                statuses_ok &= line_has_keyword(py_ln, expected_statuses["python3"]["status"])
                statuses_ok &= line_has_keyword(pandoc_ln, expected_statuses["pandoc"]["status"])
                statuses_ok &= line_has_keyword(latex_ln, expected_statuses["pdflatex"]["status"])
                for ln, exp in [(py_ln, expected_statuses["python3"]["status"]),
                                (pandoc_ln, expected_statuses["pandoc"]["status"]),
                                (latex_ln, expected_statuses["pdflatex"]["status"])]:
                    if exp == "Present":
                        if not re.search(r"\d", ln or ""):
                            statuses_ok = False
                disk_label = expected_statuses["disk"]["label"]
                statuses_ok &= line_has_keyword(disk_ln, disk_label)
                if disk_label != "Unknown":
                    statuses_ok &= bool(re.search(r"\d", disk_ln or ""))
                statuses_ok &= line_has_keyword(locale_ln, expected_statuses["locale"]["status"])

            scores["readme_statuses_correct"] = 1.0 if statuses_ok else 0.0

            # Verify other sections unchanged compared to the original file outside replaced section
            orig_prefix, orig_body, orig_suffix = section_between(normalize_newlines(ORIGINAL_README), "## System Requirements (to be updated)")
            unchanged_ok = False
            if orig_prefix is not None:
                current_prefix = prefix if prefix is not None else ""
                current_suffix = suffix if suffix is not None else ""
                unchanged_ok = (normalize_newlines(current_prefix) == normalize_newlines(orig_prefix)) and \
                               (normalize_newlines(current_suffix) == normalize_newlines(orig_suffix))
            scores["readme_other_sections_unchanged"] = 1.0 if unchanged_ok else 0.0
        else:
            scores["readme_statuses_correct"] = 0.0
            scores["readme_other_sections_unchanged"] = 0.0
    else:
        scores["readme_section_replaced"] = 0.0
        scores["readme_statuses_correct"] = 0.0
        scores["readme_other_sections_unchanged"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()