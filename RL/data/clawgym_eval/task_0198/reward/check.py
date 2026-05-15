import json
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, List


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _iter_jsx_files(base_dir: Path) -> List[Path]:
    if not base_dir.exists() or not base_dir.is_dir():
        return []
    return sorted(base_dir.rglob("*.jsx"))


def _count_hooks_in_text(text: str) -> Dict[str, int]:
    hooks = ["useState", "useEffect", "useMemo", "useCallback", "useRef", "useContext"]
    counts = {h: 0 for h in hooks}
    for h in hooks:
        counts[h] = len(re.findall(rf"\b{re.escape(h)}\b", text))
    return counts


def _merge_hook_counts(total: Dict[str, int], part: Dict[str, int]) -> Dict[str, int]:
    for k in total.keys():
        total[k] = total.get(k, 0) + part.get(k, 0)
    return total


def _find_deprecated_in_lines(lines: List[str], file_path: str) -> List[dict]:
    deprecated_names = [
        "componentWillMount",
        "componentWillReceiveProps",
        "componentWillUpdate",
        "UNSAFE_componentWillMount",
        "UNSAFE_componentWillReceiveProps",
        "UNSAFE_componentWillUpdate",
        "findDOMNode",
    ]
    results = []
    for idx, line in enumerate(lines, start=1):
        stripped = line.rstrip("\n").strip()
        # Deprecated lifecycle and methods (case-sensitive, whole-word)
        for name in deprecated_names:
            if re.search(rf"\b{re.escape(name)}\b", line):
                results.append({
                    "file_path": file_path,
                    "line": idx,
                    "identifier": name,
                    "code_snippet": stripped
                })
        # string-ref: JSX refs of the form ref="..."
        if re.search(r'\bref\s*=\s*"[^"]*"', line):
            results.append({
                "file_path": file_path,
                "line": idx,
                "identifier": "string-ref",
                "code_snippet": stripped
            })
    return results


def _compute_expected_audit(workspace: Path) -> Tuple[Optional[dict], List[Path]]:
    package_json_path = workspace / "input" / "app" / "package.json"
    src_dir = workspace / "input" / "app" / "src"

    pkg = _safe_load_json(package_json_path)
    if pkg is None:
        return None, []

    react_version = None
    react_dom_version = None
    try:
        react_version = pkg["dependencies"]["react"]
        react_dom_version = pkg["dependencies"]["react-dom"]
    except Exception:
        pass

    jsx_files = _iter_jsx_files(src_dir)

    # Compute hooks usage
    hooks_total = {h: 0 for h in ["useState", "useEffect", "useMemo", "useCallback", "useRef", "useContext"]}
    for f in jsx_files:
        text = _safe_read_text(f) or ""
        counts = _count_hooks_in_text(text)
        hooks_total = _merge_hook_counts(hooks_total, counts)

    # Compute deprecated usages
    deprecated_all = []
    for f in jsx_files:
        text = _safe_read_text(f)
        if text is None:
            continue
        rel_path = str(f.relative_to(workspace).as_posix()) if f.exists() else str(f.as_posix())
        lines = text.splitlines()
        deprecated_all.extend(_find_deprecated_in_lines(lines, rel_path))

    totals = {
        "total_deprecated": len(deprecated_all),
        "files_scanned": len(jsx_files),
        "jsx_files_scanned": len(jsx_files)
    }

    expected = {
        "react_version": react_version,
        "react_dom_version": react_dom_version,
        "hooks_usage": hooks_total,
        "deprecated_usages": deprecated_all,
        "totals": totals
    }
    return expected, jsx_files


def _normalize_deprecated_list(items: List[dict]) -> List[Tuple[str, int, str, str]]:
    normalized = []
    for it in items:
        try:
            file_path = it["file_path"]
            line = int(it["line"])
            identifier = it["identifier"]
            code_snippet = it["code_snippet"]
            normalized.append((file_path, line, identifier, code_snippet))
        except Exception:
            return []
    return sorted(normalized, key=lambda x: (x[0], x[1], x[2], x[3]))


def _parse_status_sections(md: str) -> Tuple[bool, Dict[str, Tuple[int, int, str]]]:
    lines = md.splitlines()
    indices = {}
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line == "React codebase audit: findings" and "title" not in indices:
            indices["title"] = i
        elif line == "Summary" and "Summary" not in indices:
            indices["Summary"] = i
        elif line == "Details" and "Details" not in indices:
            indices["Details"] = i
        elif line == "Next steps" and "Next steps" not in indices:
            indices["Next steps"] = i

    required = ["title", "Summary", "Details", "Next steps"]
    if not all(k in indices for k in required):
        return False, {}

    if not (indices["title"] < indices["Summary"] < indices["Details"] < indices["Next steps"]):
        return False, {}

    sections = {}
    s_start = indices["Summary"] + 1
    s_end = indices["Details"]
    sections["Summary"] = (s_start, s_end, "\n".join(lines[s_start:s_end]).strip())

    d_start = indices["Details"] + 1
    d_end = indices["Next steps"]
    sections["Details"] = (d_start, d_end, "\n".join(lines[d_start:d_end]).strip())

    n_start = indices["Next steps"] + 1
    n_end = len(lines)
    sections["Next steps"] = (n_start, n_end, "\n".join(lines[n_start:n_end]).strip())

    sections["title"] = (indices["title"], indices["title"] + 1, lines[indices["title"]].strip())

    return True, sections


def _count_bullets(md_section_text: str) -> int:
    count = 0
    for line in md_section_text.splitlines():
        if re.match(r'^\s*([-*]|\d+\.)\s+\S', line):
            count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "audit_json_present_and_parseable": 0.0,
        "audit_json_react_versions_correct": 0.0,
        "audit_json_hooks_usage_counts_correct": 0.0,
        "audit_json_deprecated_usages_correct": 0.0,
        "audit_json_totals_correct": 0.0,
        "status_update_sections_order_and_headings": 0.0,
        "status_update_summary_includes_values_and_deprecated_counts": 0.0,
        "status_update_details_mentions_files": 0.0,
        "status_update_next_steps_2_to_3_actions": 0.0,
        "status_update_references_json_path": 0.0,
        "email_subject_and_greeting_format": 0.0,
        "email_mentions_version_and_total": 0.0,
        "email_bullet_list_covers_deprecated_identifiers": 0.0,
        "email_timeline_and_approval_and_references": 0.0,
    }

    expected_audit, jsx_files = _compute_expected_audit(workspace)

    audit_json_path = workspace / "output" / "tech-audit.json"
    audit_json = _safe_load_json(audit_json_path)
    if isinstance(audit_json, dict):
        scores["audit_json_present_and_parseable"] = 1.0

    if expected_audit is not None and isinstance(audit_json, dict):
        exp_r = expected_audit.get("react_version")
        exp_rd = expected_audit.get("react_dom_version")
        got_r = audit_json.get("react_version")
        got_rd = audit_json.get("react_dom_version")
        if got_r == exp_r and got_rd == exp_rd and isinstance(got_r, str) and isinstance(got_rd, str):
            scores["audit_json_react_versions_correct"] = 1.0

    if expected_audit is not None and isinstance(audit_json, dict):
        exp_hooks = expected_audit.get("hooks_usage")
        got_hooks = audit_json.get("hooks_usage")
        if isinstance(exp_hooks, dict) and isinstance(got_hooks, dict):
            required_hooks = ["useState", "useEffect", "useMemo", "useCallback", "useRef", "useContext"]
            if all(h in got_hooks for h in required_hooks):
                try:
                    match = all(int(got_hooks[h]) == int(exp_hooks[h]) for h in required_hooks)
                except Exception:
                    match = False
                if match:
                    scores["audit_json_hooks_usage_counts_correct"] = 1.0

    if expected_audit is not None and isinstance(audit_json, dict):
        exp_dep = expected_audit.get("deprecated_usages", [])
        got_dep = audit_json.get("deprecated_usages")
        if isinstance(got_dep, list):
            norm_exp = _normalize_deprecated_list(exp_dep)
            norm_got = _normalize_deprecated_list(got_dep)
            if norm_exp and norm_got and norm_exp == norm_got:
                scores["audit_json_deprecated_usages_correct"] = 1.0
            if not norm_exp and not exp_dep and not got_dep:
                scores["audit_json_deprecated_usages_correct"] = 1.0

    if expected_audit is not None and isinstance(audit_json, dict):
        exp_tot = expected_audit.get("totals", {})
        got_tot = audit_json.get("totals")
        if isinstance(got_tot, dict):
            try:
                cond = (
                    int(got_tot.get("total_deprecated", -1)) == int(exp_tot.get("total_deprecated", -2)) and
                    int(got_tot.get("files_scanned", -1)) == int(exp_tot.get("files_scanned", -2)) and
                    int(got_tot.get("jsx_files_scanned", -1)) == int(exp_tot.get("jsx_files_scanned", -2)) and
                    int(got_tot.get("files_scanned", -1)) == int(got_tot.get("jsx_files_scanned", -1))
                )
            except Exception:
                cond = False
            if cond:
                scores["audit_json_totals_correct"] = 1.0

    status_update_path = workspace / "output" / "status-update.md"
    status_text = _safe_read_text(status_update_path)
    ok_sections = False
    sections = {}
    if status_text is not None:
        ok_sections, sections = _parse_status_sections(status_text)
        if ok_sections:
            scores["status_update_sections_order_and_headings"] = 1.0

        if "output/tech-audit.json" in status_text:
            scores["status_update_references_json_path"] = 1.0

        if ok_sections and isinstance(audit_json, dict):
            summary_text = sections["Summary"][2]
            try:
                rv = audit_json.get("react_version")
                tot = audit_json.get("totals", {}).get("total_deprecated")
                fs = audit_json.get("totals", {}).get("files_scanned")
            except Exception:
                rv, tot, fs = None, None, None

            has_values = False
            if isinstance(rv, str) and rv in summary_text:
                try:
                    tot_str = str(int(tot))
                    fs_str = str(int(fs))
                    tot_ok = re.search(rf"\b{re.escape(tot_str)}\b", summary_text) is not None
                    fs_ok = re.search(rf"\b{re.escape(fs_str)}\b", summary_text) is not None
                    has_values = tot_ok and fs_ok
                except Exception:
                    has_values = False

            has_counts = False
            dep = audit_json.get("deprecated_usages")
            if isinstance(dep, list):
                counts: Dict[str, int] = {}
                for item in dep:
                    try:
                        ident = item["identifier"]
                        counts[ident] = counts.get(ident, 0) + 1
                    except Exception:
                        counts = {}
                        break
                if counts:
                    lines = summary_text.splitlines()
                    per_ident_ok = True
                    for ident, cnt in counts.items():
                        if cnt <= 0:
                            continue
                        line_found = False
                        for ln in lines:
                            if ident in ln and re.search(rf"\b{re.escape(str(cnt))}\b", ln):
                                line_found = True
                                break
                        if not line_found:
                            per_ident_ok = False
                            break
                    has_counts = per_ident_ok
                else:
                    has_counts = True

            if has_values and has_counts:
                scores["status_update_summary_includes_values_and_deprecated_counts"] = 1.0

        if ok_sections and isinstance(audit_json, dict):
            details_text = sections["Details"][2]
            dep = audit_json.get("deprecated_usages")
            if isinstance(dep, list):
                files_with_dep = sorted({d.get("file_path") for d in dep if isinstance(d, dict) and d.get("file_path")})
                if files_with_dep:
                    all_present = all(fp in details_text for fp in files_with_dep)
                    if all_present:
                        scores["status_update_details_mentions_files"] = 1.0
                else:
                    scores["status_update_details_mentions_files"] = 1.0

        if ok_sections:
            next_text = sections["Next steps"][2]
            bullets = _count_bullets(next_text)
            if 2 <= bullets <= 3:
                scores["status_update_next_steps_2_to_3_actions"] = 1.0

    email_path = workspace / "output" / "email-to-tech-lead.txt"
    email_text = _safe_read_text(email_path)
    if email_text is not None:
        lines = email_text.splitlines()
        subj_ok = False
        greet_ok = False
        if lines:
            first = lines[0].strip()
            if first.startswith("Subject:") and ("React audit results" in first):
                subj_ok = True
        if any(l.strip() == "Hi Alex," for l in lines[1:]):
            greet_ok = True
        if subj_ok and greet_ok:
            scores["email_subject_and_greeting_format"] = 1.0

        if isinstance(audit_json, dict):
            rv = audit_json.get("react_version")
            try:
                tot_val = int(audit_json.get("totals", {}).get("total_deprecated"))
            except Exception:
                tot_val = None
            has_version = isinstance(rv, str) and (rv in email_text)
            has_total = isinstance(tot_val, int) and (re.search(rf"\b{re.escape(str(tot_val))}\b", email_text) is not None)
            if has_version and has_total:
                scores["email_mentions_version_and_total"] = 1.0

        dep = audit_json.get("deprecated_usages") if isinstance(audit_json, dict) else None
        if isinstance(dep, list):
            bullets = [l for l in lines if re.match(r'^\s*[-*]\s+\S', l)]
            bullet_texts = "\n".join(bullets)
            idents = sorted({d.get("identifier") for d in dep if isinstance(d, dict) and d.get("identifier")})
            if idents:
                ok_all = all((ident in bullet_texts) for ident in idents)
                if ok_all and bullets:
                    scores["email_bullet_list_covers_deprecated_identifiers"] = 1.0
            else:
                scores["email_bullet_list_covers_deprecated_identifiers"] = 1.0

        refs_ok = ("output/tech-audit.json" in email_text) and ("output/status-update.md" in email_text)
        tl_ok = (re.search(r"(?i)\bDay\s*1\b", email_text) and re.search(r"(?i)\bDay\s*2\b", email_text)) or \
                (re.search(r"(?i)\bStep\s*1\b", email_text) and re.search(r"(?i)\bStep\s*2\b", email_text))
        approval_ok = re.search(r"(?i)\bapproval\b", email_text) is not None or re.search(r"(?i)\bapprove\b", email_text) is not None
        if refs_ok and tl_ok and approval_ok:
            scores["email_timeline_and_approval_and_references"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()