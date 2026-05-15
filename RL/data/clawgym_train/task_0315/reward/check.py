import json
import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any


def _safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        data = path.read_text(encoding="utf-8")
        return True, data
    except Exception:
        return False, ""


def _safe_json_load(path: Path) -> Tuple[bool, Any]:
    ok, txt = _safe_read_text(path)
    if not ok:
        return False, None
    try:
        return True, json.loads(txt)
    except Exception:
        return False, None


def _safe_jsonl_load(path: Path) -> Tuple[bool, List[dict]]:
    ok, txt = _safe_read_text(path)
    if not ok:
        return False, []
    items = []
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            return False, []
        if not isinstance(obj, dict):
            return False, []
        items.append(obj)
    return True, items


def _normalize_newlines(s: str) -> str:
    # Handle files that may contain literal '\n' sequences
    if "\\n" in s and "\n" not in s:
        try:
            # Replace escaped sequences with actual newlines
            s = s.replace("\\n", "\n")
        except Exception:
            pass
    return s


def _classify_text(text: str) -> Dict[str, bool]:
    text_l = text.lower()
    themes = {
        "performance": any(k in text_l for k in ["slow", "performance", "regression"]),
        "api_break": any(k in text_l for k in ["deprecation", "deprecated", "breaking change", "typeerror"]),
        "install": any(k in text_l for k in ["pip", "install", "dependency", "version conflict"]),
        "doc": any(k in text_l for k in ["docs", "documentation", "example", "confusing"]),
    }
    # Determine 'other' for items that matched none of the above
    any_match = any(themes.values())
    themes["other"] = not any_match
    return themes


def _parse_emails(text: str) -> List[str]:
    # Split emails by lines containing only '---' or sequences.
    text = _normalize_newlines(text)
    # Split by '\n---\n' first
    parts = re.split(r"(?:^|\n)---(?:\n|$)", text)
    # Clean parts
    emails = [p.strip() for p in parts if p.strip()]
    return emails


def _parse_ci_log(text: str) -> Tuple[int, List[dict], Dict[str, Any]]:
    """
    Returns:
      failed_tests_count, failures_list, warnings_dict with {'count': int, 'messages': [str]}
    """
    text = _normalize_newlines(text)
    lines = text.splitlines()

    # Failed tests count: parse from summary "X failed"
    failed_tests = 0
    summary_line = ""
    for ln in reversed(lines):
        if "failed" in ln and "passed" in ln:
            summary_line = ln
            break
    if summary_line:
        m = re.search(r"(\d+)\s+failed", summary_line)
        if m:
            try:
                failed_tests = int(m.group(1))
            except Exception:
                failed_tests = 0

    # Extract failures
    failures: List[dict] = []
    # Find failure blocks
    try:
        failures_section_idx = None
        for i, ln in enumerate(lines):
            if re.search(r"=+ FAILURES =+", ln):
                failures_section_idx = i
                break
        if failures_section_idx is not None:
            # Scan after failures header
            i = failures_section_idx + 1
            while i < len(lines):
                # Header line with underscores and test name
                if re.match(r"_+", lines[i]):
                    # Next meaningful lines should include file:line: in test_name
                    j = i + 1
                    file_path = None
                    line_no = None
                    test_name = None
                    error_type = None
                    error_message = None
                    # gather until next underscores or end or blank line after block
                    while j < len(lines) and not re.match(r"_+", lines[j]):
                        m = re.match(r"(.+?):(\d+):\s+in\s+(.+)$", lines[j].strip())
                        if m and file_path is None:
                            file_path = m.group(1).strip()
                            try:
                                line_no = int(m.group(2))
                            except Exception:
                                line_no = None
                            test_name = m.group(3).strip()
                        # error line like "E   TypeError: message"
                        if lines[j].lstrip().startswith("E "):
                            m2 = re.match(r"\s*E\s+([A-Za-z0-9_]+):\s*(.*)$", lines[j])
                            if m2 and error_type is None:
                                error_type = m2.group(1)
                                error_message = m2.group(2).strip()
                        j += 1
                    if file_path and line_no is not None and test_name:
                        failures.append({
                            "test_name": test_name,
                            "file": file_path,
                            "line": int(line_no),
                            "error_type": error_type or "",
                            "error_message": error_message or "",
                        })
                    i = j
                else:
                    i += 1
    except Exception:
        failures = []

    # Extract warnings: collect unique deprecation warning message strings after "DeprecationWarning: "
    warning_messages = set()
    for ln in lines:
        if "DeprecationWarning:" in ln:
            # Extract message after the first colon after DeprecationWarning
            m = re.search(r"DeprecationWarning:\s*(.*)$", ln)
            if m:
                msg = m.group(1).strip()
                if msg:
                    warning_messages.add(msg)
    warnings = {
        "count": len(warning_messages),
        "messages": sorted(warning_messages),
    }

    return failed_tests, failures, warnings


def _compute_expected_triage(workspace: Path) -> Tuple[bool, dict]:
    issues_path = workspace / "input" / "issues.jsonl"
    emails_path = workspace / "input" / "feedback_emails.txt"
    ci_log_path = workspace / "input" / "ci_log.txt"

    ok_issues, issues_list = _safe_jsonl_load(issues_path)
    ok_emails, emails_text = _safe_read_text(emails_path)
    ok_ci, ci_text = _safe_read_text(ci_log_path)

    if not (ok_issues and ok_emails and ok_ci):
        return False, {}

    # Prepare themes structure
    theme_keys = ["performance", "api_break", "install", "doc", "other"]
    theme_counts = {k: 0 for k in theme_keys}
    theme_issue_ids = {k: [] for k in theme_keys}

    # Classify issues
    for item in issues_list:
        title = str(item.get("title", ""))
        body = str(item.get("body", ""))
        iid = item.get("id", None)
        text = f"{title}\n{body}"
        matches = _classify_text(text)
        # Increment counts for matched themes (per item once per theme)
        matched_any = False
        for k in theme_keys[:-1]:  # exclude 'other'
            if matches.get(k, False):
                theme_counts[k] += 1
                matched_any = True
                if isinstance(iid, int):
                    theme_issue_ids[k].append(iid)
        if not matched_any:
            theme_counts["other"] += 1
            if isinstance(iid, int):
                theme_issue_ids["other"].append(iid)

    # Classify emails
    emails = _parse_emails(emails_text)
    for mail in emails:
        matches = _classify_text(mail)
        matched_any = False
        for k in theme_keys[:-1]:
            if matches.get(k, False):
                theme_counts[k] += 1
                matched_any = True
        if not matched_any:
            theme_counts["other"] += 1

    # Sort issue_ids ascending and unique
    for k in theme_issue_ids:
        ids = [i for i in theme_issue_ids[k] if isinstance(i, int)]
        theme_issue_ids[k] = sorted(sorted(set(ids)))

    issues_total = len(issues_list)

    # Parse CI log
    failed_tests, failures, warnings = _parse_ci_log(ci_text)

    expected = {
        "issues_total": issues_total,
        "themes": {
            "performance": {"count": theme_counts["performance"], "issue_ids": theme_issue_ids["performance"]},
            "api_break": {"count": theme_counts["api_break"], "issue_ids": theme_issue_ids["api_break"]},
            "install": {"count": theme_counts["install"], "issue_ids": theme_issue_ids["install"]},
            "doc": {"count": theme_counts["doc"], "issue_ids": theme_issue_ids["doc"]},
            "other": {"count": theme_counts["other"], "issue_ids": theme_issue_ids["other"]},
        },
        "ci_failures": {
            "failed_tests": failed_tests,
            "failures": failures,
            "warnings": warnings,
        },
    }
    return True, expected


def _load_action_items_sections(path: Path) -> Tuple[bool, Dict[str, List[str]]]:
    ok, txt = _safe_read_text(path)
    if not ok:
        return False, {}
    txt = _normalize_newlines(txt)
    lines = txt.splitlines()

    # Identify sections by titles "Immediate", "Next release", "Follow-up" with optional markdown heading markers
    section_titles = ["Immediate", "Next release", "Follow-up"]
    sections: Dict[str, List[str]] = {t: [] for t in section_titles}

    current = None
    for ln in lines:
        # Heading match
        m = re.match(r"^\s{0,3}#*\s*(Immediate|Next release|Follow-up)\s*$", ln)
        if m:
            current = m.group(1)
            continue
        if current is not None:
            sections[current].append(ln)

    return True, sections


def _section_has_bullet_with_reference(section_lines: List[str], references: List[str]) -> bool:
    # Check at least one bullet line contains a reference string (case-sensitive contains)
    for ln in section_lines:
        if re.match(r"^\s*[-*]\s+", ln):
            for ref in references:
                if ref and ref in ln:
                    return True
    return False


def _extract_bullets(section_lines: List[str]) -> List[str]:
    return [ln for ln in section_lines if re.match(r"^\s*[-*]\s+", ln)]


def _text_outside_codeblocks(text: str) -> str:
    # Remove code blocks fenced with ```
    parts = []
    lines = text.splitlines()
    in_code = False
    for ln in lines:
        if ln.strip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            parts.append(ln)
    return "\n".join(parts)


def _count_words(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)


def _check_reply(
    path: Path,
    issue_id: int,
    expected_links: List[str],
    expected_codeblocks: List[str],
) -> Dict[str, float]:
    scores = {
        "exists": 0.0,
        "header_correct": 0.0,
        "footer_correct": 0.0,
        "word_limit_ok": 0.0,
        "links_preserved": 0.0,
        "codeblocks_preserved": 1.0 if not expected_codeblocks else 0.0,
    }
    ok, txt = _safe_read_text(path)
    if not ok:
        return scores
    scores["exists"] = 1.0

    txt = _normalize_newlines(txt)
    lines = [ln.rstrip("\n") for ln in txt.splitlines()]
    if not lines:
        return scores

    # Header check
    if lines[0].strip() == f"Re: #{issue_id}":
        scores["header_correct"] = 1.0

    # Footer check: last non-empty line equals exact sentence
    last_non_empty = ""
    for ln in reversed(lines):
        if ln.strip():
            last_non_empty = ln.strip()
            break
    if last_non_empty == "Thanks for helping improve the library.":
        scores["footer_correct"] = 1.0

    # Word count outside code blocks <= 120
    non_code_text = _text_outside_codeblocks(txt)
    if _count_words(non_code_text) <= 120:
        scores["word_limit_ok"] = 1.0

    # Links preserved: every expected link must appear exactly as substring
    if all(link in txt for link in expected_links):
        scores["links_preserved"] = 1.0

    # Codeblocks preserved: each expected codeblock must appear verbatim
    if expected_codeblocks:
        preserved = all(cb in txt for cb in expected_codeblocks)
        scores["codeblocks_preserved"] = 1.0 if preserved else 0.0

    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        # triage summary checks
        "triage_summary_exists": 0.0,
        "triage_json_valid": 0.0,
        "triage_issues_total_correct": 0.0,
        "triage_theme_performance_count_correct": 0.0,
        "triage_theme_api_break_count_correct": 0.0,
        "triage_theme_install_count_correct": 0.0,
        "triage_theme_doc_count_correct": 0.0,
        "triage_theme_other_count_correct": 0.0,
        "triage_theme_performance_issue_ids_correct": 0.0,
        "triage_theme_api_break_issue_ids_correct": 0.0,
        "triage_theme_install_issue_ids_correct": 0.0,
        "triage_theme_doc_issue_ids_correct": 0.0,
        "triage_theme_other_issue_ids_correct": 0.0,
        "triage_ci_failed_tests_correct": 0.0,
        "triage_ci_failure_entry_correct": 0.0,
        "triage_ci_warnings_count_correct": 0.0,
        "triage_ci_warnings_messages_correct": 0.0,
        # action items checks
        "action_items_exists": 0.0,
        "action_has_sections": 0.0,
        "action_immediate_has_referenced_bullet": 0.0,
        "action_next_release_has_referenced_bullet": 0.0,
        "action_follow_up_has_referenced_bullet": 0.0,
        "action_immediate_mentions_failure": 0.0,
        "action_immediate_mentions_top_theme": 0.0,
        # replies checks
        "reply_102_exists": 0.0,
        "reply_102_header_correct": 0.0,
        "reply_102_footer_correct": 0.0,
        "reply_102_word_limit_ok": 0.0,
        "reply_102_link_preserved": 0.0,
        "reply_102_codeblock_preserved": 0.0,
        "reply_104_exists": 0.0,
        "reply_104_header_correct": 0.0,
        "reply_104_footer_correct": 0.0,
        "reply_104_word_limit_ok": 0.0,
        "reply_104_link_preserved": 0.0,
    }

    # Compute expected triage from inputs
    have_expected, expected = _compute_expected_triage(workspace)

    # Load produced triage summary
    triage_path = workspace / "outputs" / "triage_summary.json"
    ok_triage_json, triage_obj = _safe_json_load(triage_path)
    if triage_path.exists():
        scores["triage_summary_exists"] = 1.0
    if ok_triage_json and isinstance(triage_obj, dict):
        scores["triage_json_valid"] = 1.0

    if have_expected and ok_triage_json and isinstance(triage_obj, dict):
        # Check issues_total
        if triage_obj.get("issues_total") == expected["issues_total"]:
            scores["triage_issues_total_correct"] = 1.0

        # Themes counts and issue_ids
        for theme_key in ["performance", "api_break", "install", "doc", "other"]:
            triage_theme = triage_obj.get("themes", {}).get(theme_key, {})
            exp_theme = expected["themes"][theme_key]
            # counts
            key_map = {
                "performance": "triage_theme_performance_count_correct",
                "api_break": "triage_theme_api_break_count_correct",
                "install": "triage_theme_install_count_correct",
                "doc": "triage_theme_doc_count_correct",
                "other": "triage_theme_other_count_correct",
            }
            if isinstance(triage_theme, dict) and triage_theme.get("count") == exp_theme["count"]:
                scores[key_map[theme_key]] = 1.0
            # issue_ids
            key_map_ids = {
                "performance": "triage_theme_performance_issue_ids_correct",
                "api_break": "triage_theme_api_break_issue_ids_correct",
                "install": "triage_theme_install_issue_ids_correct",
                "doc": "triage_theme_doc_issue_ids_correct",
                "other": "triage_theme_other_issue_ids_correct",
            }
            t_ids = triage_theme.get("issue_ids") if isinstance(triage_theme, dict) else None
            if isinstance(t_ids, list) and t_ids == exp_theme["issue_ids"]:
                scores[key_map_ids[theme_key]] = 1.0

        # CI failures checks
        tri_ci = triage_obj.get("ci_failures", {}) if isinstance(triage_obj, dict) else {}
        if isinstance(tri_ci, dict):
            if tri_ci.get("failed_tests") == expected["ci_failures"]["failed_tests"]:
                scores["triage_ci_failed_tests_correct"] = 1.0
            # failure entry
            tri_failures = tri_ci.get("failures", [])
            exp_failures = expected["ci_failures"]["failures"]
            # Require at least one failure and match the first expected
            if isinstance(tri_failures, list) and len(tri_failures) == len(exp_failures):
                # Strict comparison of dict for single failure
                if len(exp_failures) == 1 and isinstance(tri_failures[0], dict):
                    keys = ["test_name", "file", "line", "error_type", "error_message"]
                    if all(tri_failures[0].get(k) == exp_failures[0].get(k) for k in keys):
                        scores["triage_ci_failure_entry_correct"] = 1.0
                elif exp_failures == tri_failures:
                    scores["triage_ci_failure_entry_correct"] = 1.0
            # warnings
            tri_warn = tri_ci.get("warnings", {})
            if isinstance(tri_warn, dict):
                if tri_warn.get("count") == expected["ci_failures"]["warnings"]["count"]:
                    scores["triage_ci_warnings_count_correct"] = 1.0
                tri_msgs = tri_warn.get("messages", [])
                exp_msgs = expected["ci_failures"]["warnings"]["messages"]
                if isinstance(tri_msgs, list):
                    # Compare as sets or exact match? We'll compare sets to allow any ordering
                    if set(tri_msgs) == set(exp_msgs) and len(tri_msgs) == len(exp_msgs):
                        scores["triage_ci_warnings_messages_correct"] = 1.0

    # Action items checks
    action_path = workspace / "outputs" / "action_items.md"
    if action_path.exists():
        scores["action_items_exists"] = 1.0
    ok_sections, sections = _load_action_items_sections(action_path)
    if ok_sections:
        # Check presence of all three sections
        required_sections = ["Immediate", "Next release", "Follow-up"]
        if all(sec in sections for sec in required_sections):
            scores["action_has_sections"] = 1.0

        # Build references from expected triage
        # References: failing test name, file path, error type, error message, issue IDs as strings
        references_common = []
        if have_expected:
            exp_ci = expected["ci_failures"]
            if exp_ci["failures"]:
                failure = exp_ci["failures"][0]
                references_common.extend([
                    failure.get("test_name", ""),
                    failure.get("file", ""),
                    failure.get("error_type", ""),
                    failure.get("error_message", ""),
                ])
            # issue ids across all themes
            issue_ids = set()
            for th in expected["themes"].values():
                for iid in th["issue_ids"]:
                    issue_ids.add(str(iid))
                    issue_ids.add(f"#{iid}")
            references_common.extend(sorted(issue_ids))

        # Ensure at least one bullet with a reference in each section
        for sec, key in [("Immediate", "action_immediate_has_referenced_bullet"),
                         ("Next release", "action_next_release_has_referenced_bullet"),
                         ("Follow-up", "action_follow_up_has_referenced_bullet")]:
            lines = sections.get(sec, [])
            if _section_has_bullet_with_reference(lines, references_common):
                scores[key] = 1.0

        # Immediate mentions failure explicitly (test name or file or error type)
        if have_expected:
            failure_refs = []
            exp_ci = expected["ci_failures"]
            if exp_ci["failures"]:
                f = exp_ci["failures"][0]
                failure_refs = [f.get("test_name", ""), f.get("file", ""), f.get("error_type", "")]
            imm_lines = sections.get("Immediate", [])
            if _section_has_bullet_with_reference(imm_lines, [r for r in failure_refs if r]):
                scores["action_immediate_mentions_failure"] = 1.0

        # Immediate mentions top theme (by theme name or issue id within that theme)
        if have_expected:
            # Identify top themes by max count
            theme_counts = {k: expected["themes"][k]["count"] for k in ["performance", "install", "doc", "api_break", "other"]}
            if theme_counts:
                max_count = max(theme_counts.values())
                top_themes = [k for k, v in theme_counts.items() if v == max_count]
                # Build refs for top themes: theme name and their issue ids (string and #)
                top_refs = []
                for t in top_themes:
                    top_refs.append(t)
                    for iid in expected["themes"][t]["issue_ids"]:
                        top_refs.append(str(iid))
                        top_refs.append(f"#{iid}")
                imm_lines = sections.get("Immediate", [])
                if _section_has_bullet_with_reference(imm_lines, [r for r in top_refs if r]):
                    scores["action_immediate_mentions_top_theme"] = 1.0

    # Replies checks
    # Draft references (for preservation)
    draft_path = workspace / "input" / "draft_replies.md"
    ok_draft, draft_txt = _safe_read_text(draft_path)
    draft_txt = _normalize_newlines(draft_txt) if ok_draft else ""
    # Extract expected links and code blocks per issue based on the draft content provided
    # For this task, known expected items:
    expected_links_102 = ["[migration guide](https://example.org/migration)"]
    expected_codeblocks_102 = ["```python\nfrom mydf import concat\nresult = concat([s1, s2], infer_dtype=True)\n```"]
    expected_links_104 = ["[docs page](https://example.org/docs/join)"]
    expected_codeblocks_104: List[str] = []  # none in draft B

    # reply 102
    reply_102_path = workspace / "outputs" / "replies" / "reply_102.md"
    r102 = _check_reply(reply_102_path, 102, expected_links_102, expected_codeblocks_102)
    scores["reply_102_exists"] = r102["exists"]
    scores["reply_102_header_correct"] = r102["header_correct"]
    scores["reply_102_footer_correct"] = r102["footer_correct"]
    scores["reply_102_word_limit_ok"] = r102["word_limit_ok"]
    scores["reply_102_link_preserved"] = r102["links_preserved"]
    scores["reply_102_codeblock_preserved"] = r102["codeblocks_preserved"]

    # reply 104
    reply_104_path = workspace / "outputs" / "replies" / "reply_104.md"
    r104 = _check_reply(reply_104_path, 104, expected_links_104, expected_codeblocks_104)
    scores["reply_104_exists"] = r104["exists"]
    scores["reply_104_header_correct"] = r104["header_correct"]
    scores["reply_104_footer_correct"] = r104["footer_correct"]
    scores["reply_104_word_limit_ok"] = r104["word_limit_ok"]
    scores["reply_104_link_preserved"] = r104["links_preserved"]

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()