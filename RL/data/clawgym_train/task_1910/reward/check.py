import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _safe_float(x: str) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _safe_int(x: str) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def _compute_expected_slow_steps(rows: List[Dict[str, str]]) -> Optional[List[Dict[str, object]]]:
    try:
        # Filter successful
        succ = [r for r in rows if r.get("status", "").strip().lower() == "success"]
        groups: Dict[str, List[float]] = {}
        for r in succ:
            step = r.get("step", "").strip()
            dur_str = r.get("duration_seconds", "").strip()
            dur = _safe_float(dur_str)
            if step == "" or dur is None:
                return None
            groups.setdefault(step, []).append(dur)
        result = []
        for step, durs in groups.items():
            if len(durs) >= 3:
                avg = sum(durs) / len(durs) if len(durs) > 0 else 0.0
                mx = max(durs) if len(durs) > 0 else 0.0
                result.append(
                    {
                        "step": step,
                        "avg_duration_seconds": avg,
                        "count": len(durs),
                        "max_duration_seconds": mx,
                    }
                )
        # Sort by avg desc and take top 5
        result.sort(key=lambda d: d["avg_duration_seconds"], reverse=True)
        return result[:5]
    except Exception:
        return None


def _parse_csv_header_and_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def _extract_list_under_key(yaml_text: str, key_name: str) -> List[List[str]]:
    # Return list of lists found under occurrences of 'key_name:'
    lists_found: List[List[str]] = []
    lines = yaml_text.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        if re.match(rf"^\s*{re.escape(key_name)}\s*:\s*$", line):
            indent = len(line) - len(line.lstrip())
            j = i + 1
            items: List[str] = []
            while j < n:
                line_j = lines[j]
                if line_j.strip() == "":
                    j += 1
                    continue
                ind_j = len(line_j) - len(line_j.lstrip())
                if ind_j <= indent:
                    break
                m = re.match(r"^\s*-\s*(.+?)\s*$", line_j)
                if m:
                    val = m.group(1).strip()
                    # Strip quotes if present
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    items.append(val)
                else:
                    # Non-list content -> stop capturing
                    pass
                j += 1
            if items:
                lists_found.append(items)
            i = j
        else:
            i += 1
    return lists_found


def _find_concurrency_blocks(yaml_text: str) -> List[str]:
    blocks: List[str] = []
    lines = yaml_text.splitlines()
    n = len(lines)
    for i, line in enumerate(lines):
        if re.match(r"^\s*concurrency\s*:\s*$", line):
            indent = len(line) - len(line.lstrip())
            # capture until indent decreases or EOF
            j = i + 1
            collected = [line]
            while j < n:
                l = lines[j]
                if l.strip() == "":
                    collected.append(l)
                    j += 1
                    continue
                ind = len(l) - len(l.lstrip())
                if ind <= indent:
                    break
                collected.append(l)
                j += 1
            blocks.append("\n".join(collected))
    return blocks


def _find_uses_block(yaml_text: str, uses_pattern: str) -> List[str]:
    # Return text blocks where a 'uses:' line matches uses_pattern (substring), capturing some context lines
    blocks: List[str] = []
    lines = yaml_text.splitlines()
    n = len(lines)
    for i, line in enumerate(lines):
        if re.search(rf"\buses\s*:\s*{re.escape(uses_pattern)}", line):
            # capture following 20 lines for context
            start = max(0, i - 2)
            end = min(n, i + 20)
            blocks.append("\n".join(lines[start:end]))
    return blocks


def _find_key_value_after(lines: List[str], start_index: int, key: str) -> Optional[str]:
    # Find key: value after start_index among the next ~20 lines
    for j in range(start_index, min(len(lines), start_index + 20)):
        m = re.match(rf"^\s*{re.escape(key)}\s*:\s*(.+?)\s*$", lines[j])
        if m:
            return m.group(1).strip()
    return None


def _get_section(md_text: str, title: str) -> Optional[str]:
    # Find markdown section by heading text (case-insensitive). Return content until next heading or end.
    title_norm = title.strip().lower()
    lines = md_text.splitlines()
    n = len(lines)
    start_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^\s{0,3}#{1,6}\s+", line):
            heading_text = re.sub(r"^\s{0,3}#{1,6}\s+", "", line).strip()
            if heading_text.lower() == title_norm:
                start_idx = i + 1
                break
    if start_idx is None:
        return None
    # find next heading
    end_idx = n
    for j in range(start_idx, n):
        if re.match(r"^\s{0,3}#{1,6}\s+", lines[j]):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def _contains_all(text: str, substrings: List[str]) -> bool:
    t = text.lower()
    return all(s.lower() in t for s in substrings)


def _extract_first_indices(text: str, needles: List[str]) -> List[int]:
    # Return the index positions of each needle in text (lowercased), or -1 if not found
    t = text.lower()
    positions = []
    for n in needles:
        idx = t.find(n.lower())
        positions.append(idx)
    return positions


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "slow_steps_file_exists_and_columns": 0.0,
        "slow_steps_values_correct": 0.0,
        "workflow_triggers": 0.0,
        "workflow_concurrency": 0.0,
        "workflow_matrix": 0.0,
        "workflow_setup_python_uses_matrix": 0.0,
        "workflow_cache": 0.0,
        "workflow_timeout": 0.0,
        "docs_triggers": 0.0,
        "docs_python_matrix": 0.0,
        "docs_pip_caching": 0.0,
        "docs_concurrency": 0.0,
        "docs_timeout": 0.0,
        "docs_top5_section": 0.0,
        "docs_top5_matches_output": 0.0,
        "report_changes_applied": 0.0,
        "report_slow_steps_matches_output": 0.0,
    }

    # 1) Validate output/slow_steps.csv
    data_csv = workspace / "data" / "ci_runs.csv"
    output_csv = workspace / "output" / "slow_steps.csv"

    header, rows = _parse_csv_header_and_rows(output_csv)
    expected_header = ["step", "avg_duration_seconds", "count", "max_duration_seconds"]
    if header is not None and header == expected_header:
        scores["slow_steps_file_exists_and_columns"] = 1.0

    # Compute expected from data/ci_runs.csv
    data_rows = _read_csv_dicts(data_csv)
    if data_rows is not None and header is not None and rows is not None:
        expected = _compute_expected_slow_steps(data_rows)
        if expected is not None:
            # Parse student's rows into dicts
            student = []
            ok_parse = True
            for r in rows:
                if len(r) != 4:
                    ok_parse = False
                    break
                step = r[0].strip()
                avg = _safe_float(r[1].strip())
                cnt = _safe_int(r[2].strip())
                mx = _safe_float(r[3].strip())
                if step == "" or avg is None or cnt is None or mx is None:
                    ok_parse = False
                    break
                student.append(
                    {
                        "step": step,
                        "avg_duration_seconds": avg,
                        "count": cnt,
                        "max_duration_seconds": mx,
                        # Keep raw strings for doc/report cross-checks
                        "_avg_str": r[1].strip(),
                        "_count_str": r[2].strip(),
                    }
                )
            if ok_parse:
                # Check length equals expected length (top 5 or fewer if fewer available)
                if len(student) == len(expected):
                    # Compare content and order strictly
                    match_all = True
                    for i in range(len(expected)):
                        e = expected[i]
                        s = student[i]
                        if e["step"] != s["step"]:
                            match_all = False
                            break
                        # floats with tolerance
                        if not (abs(float(e["avg_duration_seconds"]) - float(s["avg_duration_seconds"])) <= 1e-6):
                            match_all = False
                            break
                        if int(e["count"]) != int(s["count"]):
                            match_all = False
                            break
                        if not (abs(float(e["max_duration_seconds"]) - float(s["max_duration_seconds"])) <= 1e-6):
                            match_all = False
                            break
                    if match_all:
                        scores["slow_steps_values_correct"] = 1.0

    # 2) Validate .github/workflows/ci.yml modifications
    workflow_path = workspace / ".github" / "workflows" / "ci.yml"
    workflow_text = _read_text(workflow_path) or ""
    if workflow_text:
        # Triggers: push main only; pull_request
        # Extract branches under 'branches:'
        branches_lists = _extract_list_under_key(workflow_text, "branches")
        branches_ok = False
        for bl in branches_lists:
            # Accept only ['main']
            norm = [b.strip().strip('"').strip("'") for b in bl]
            if norm == ["main"]:
                branches_ok = True
        # Also ensure no wildcard in file
        no_wildcard = '"*"' not in workflow_text and "- \"*\"" not in workflow_text and "- '*'" not in workflow_text and "*\"" not in workflow_text
        # pull_request presence under on:
        pull_present = re.search(r"^\s*on\s*:\s*", workflow_text, flags=re.MULTILINE) is not None and re.search(
            r"^\s*pull_request\s*:", workflow_text, flags=re.MULTILINE
        ) is not None
        if branches_ok and no_wildcard and pull_present:
            scores["workflow_triggers"] = 1.0

        # Concurrency exists with group and cancel-in-progress: true
        blocks = _find_concurrency_blocks(workflow_text)
        conc_ok = False
        for b in blocks:
            has_group = re.search(r"group\s*:\s*ai-lab-ci-\$\{\{\s*github\.ref\s*\}\}", b) is not None
            has_cancel = re.search(r"cancel-in-progress\s*:\s*true", b, flags=re.IGNORECASE) is not None
            if has_group and has_cancel:
                conc_ok = True
                break
        if conc_ok:
            scores["workflow_concurrency"] = 1.0

        # Matrix for python-version: ["3.9","3.10","3.11"]
        py_lists = _extract_list_under_key(workflow_text, "python-version")
        matrix_ok = False
        for lst in py_lists:
            norm = [s.strip().strip('"').strip("'") for s in lst]
            if set(norm) == {"3.9", "3.10", "3.11"} and len(norm) == 3:
                matrix_ok = True
                break
        if matrix_ok:
            scores["workflow_matrix"] = 1.0

        # setup-python step uses matrix variable
        setup_blocks = _find_uses_block(workflow_text, "actions/setup-python")
        setup_ok = False
        for block in setup_blocks:
            if re.search(r"python-version\s*:\s*\$\{\{\s*matrix\.python-version\s*\}\}", block):
                setup_ok = True
                break
        if setup_ok:
            scores["workflow_setup_python_uses_matrix"] = 1.0

        # Cache step: actions/cache@v3 with path and key including runner.os, matrix.python-version, hashFiles('requirements.txt')
        cache_blocks = _find_uses_block(workflow_text, "actions/cache@v3")
        cache_ok = False
        for block in cache_blocks:
            # path line
            has_path = re.search(r"path\s*:\s*~\/\.cache\/pip", block) is not None
            # key contains required parts
            # Allow ${{ hashFiles('requirements.txt') }} or hashFiles('requirements.txt') within expression
            key_line = re.search(r"key\s*:\s*(.+)", block)
            if key_line:
                key_val = key_line.group(1)
            else:
                key_val = ""
            has_runner_os = "${{ runner.os }}" in block or "runner.os" in key_val
            has_matrix_ver = "${{ matrix.python-version }}" in block or "matrix.python-version" in key_val
            has_hash = "hashFiles('requirements.txt')" in block or 'hashFiles("requirements.txt")' in block
            if has_path and has_runner_os and has_matrix_ver and has_hash:
                cache_ok = True
                break
        # ensure requirements.txt exists at repo root
        if cache_ok and (workspace / "requirements.txt").exists():
            scores["workflow_cache"] = 1.0

        # Timeout minutes 30
        if re.search(r"timeout-minutes\s*:\s*30\b", workflow_text):
            scores["workflow_timeout"] = 1.0

    # 3) Validate docs/ci_guidelines.md content and top 5 section
    guidelines_path = workspace / "docs" / "ci_guidelines.md"
    guidelines_text = _read_text(guidelines_path) or ""
    if guidelines_text:
        # Triggers: push on main only; and pull requests
        if _contains_all(guidelines_text, ["push", "main", "pull request"]):
            scores["docs_triggers"] = 1.0
        # Python matrix: 3.9, 3.10, 3.11
        if all(s in guidelines_text for s in ["3.9", "3.10", "3.11"]):
            scores["docs_python_matrix"] = 1.0
        # Caching for pip
        if _contains_all(guidelines_text, ["cache", "pip"]):
            scores["docs_pip_caching"] = 1.0
        # Concurrency policy with group name and cancel behavior
        if "ai-lab-ci-${{ github.ref }}" in guidelines_text and re.search(r"cancel[- ]?in[- ]?progress", guidelines_text, flags=re.IGNORECASE):
            scores["docs_concurrency"] = 1.0
        # Timeout 30 minutes
        if re.search(r"30\s*minute", guidelines_text, flags=re.IGNORECASE) and re.search(r"timeout", guidelines_text, flags=re.IGNORECASE):
            scores["docs_timeout"] = 1.0

        # Top 5 slowest CI steps section
        section = _get_section(guidelines_text, "Top 5 slowest CI steps")
        if section is not None:
            scores["docs_top5_section"] = 1.0
            # Validate matches output/slow_steps.csv
            # Use the student's slow_steps.csv to source numbers/formatting
            out_header, out_rows = _parse_csv_header_and_rows(output_csv)
            if out_header == expected_header and out_rows is not None and len(out_rows) > 0:
                # Build expected order list from output file itself (to enforce sorting)
                # and validate the section contains each triplet: step, avg string, count string
                student_rows = []
                ok_parse = True
                for r in out_rows:
                    if len(r) != 4:
                        ok_parse = False
                        break
                    student_rows.append(
                        {
                            "step": r[0].strip(),
                            "avg_str": r[1].strip(),
                            "count_str": r[2].strip(),
                        }
                    )
                if ok_parse:
                    # Confirm ordering by positions of step names in section
                    positions = []
                    all_present = True
                    for item in student_rows:
                        sname = item["step"]
                        avg_s = item["avg_str"]
                        cnt_s = item["count_str"]
                        sec_lower = section.lower()
                        # Check presence
                        if sname.lower() not in sec_lower or avg_s.lower() not in sec_lower or cnt_s.lower() not in sec_lower:
                            all_present = False
                            break
                        positions.append(sec_lower.find(sname.lower()))
                    if all_present and positions == sorted(positions):
                        scores["docs_top5_matches_output"] = 1.0

    # 4) Validate reports/ci_status.md
    report_path = workspace / "reports" / "ci_status.md"
    report_text = _read_text(report_path) or ""
    if report_text:
        changes_sec = _get_section(report_text, "Changes Applied")
        slow_sec = _get_section(report_text, "Slow Steps Summary")

        if changes_sec is not None:
            # Check mentions: triggers, matrix, caching, concurrency, timeout
            # We'll check flexible keywords coverage
            checks = []
            # triggers: mention push main and PR
            checks.append(_contains_all(changes_sec, ["push", "main", "pull request"]))
            # matrix: versions or word matrix
            checks.append(("matrix" in changes_sec.lower()) or all(v in changes_sec for v in ["3.9", "3.10", "3.11"]))
            # caching: cache + pip and maybe path
            checks.append(_contains_all(changes_sec, ["cache", "pip"]))
            # concurrency: group name and cancel
            checks.append("ai-lab-ci-${{ github.ref }}" in changes_sec and re.search(r"cancel[- ]?in[- ]?progress", changes_sec, flags=re.IGNORECASE))
            # timeout: 30 minutes
            checks.append(re.search(r"timeout", changes_sec, flags=re.IGNORECASE) and re.search(r"30\s*minute", changes_sec, flags=re.IGNORECASE))
            if all(checks):
                scores["report_changes_applied"] = 1.0

        if slow_sec is not None:
            # Must match output/slow_steps.csv rows
            out_header, out_rows = _parse_csv_header_and_rows(output_csv)
            if out_header == expected_header and out_rows is not None and len(out_rows) > 0:
                # Build expected order list from output file
                student_rows = []
                ok_parse = True
                for r in out_rows:
                    if len(r) != 4:
                        ok_parse = False
                        break
                    student_rows.append(
                        {
                            "step": r[0].strip(),
                            "avg_str": r[1].strip(),
                            "count_str": r[2].strip(),
                        }
                    )
                if ok_parse:
                    positions = []
                    all_present = True
                    sec_lower = slow_sec.lower()
                    for item in student_rows:
                        sname = item["step"]
                        avg_s = item["avg_str"]
                        cnt_s = item["count_str"]
                        if sname.lower() not in sec_lower or avg_s.lower() not in sec_lower or cnt_s.lower() not in sec_lower:
                            all_present = False
                            break
                        positions.append(sec_lower.find(sname.lower()))
                    if all_present and positions == sorted(positions) and len(student_rows) == 5:
                        scores["report_slow_steps_matches_output"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()