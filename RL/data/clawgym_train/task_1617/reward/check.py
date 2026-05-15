import json
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_json_load(path: Path) -> Optional[Any]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _safe_jsonl_load(path: Path) -> Optional[List[Dict[str, Any]]]:
    entries: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        entries.append(obj)
                    else:
                        return None
                except Exception:
                    return None
        return entries
    except Exception:
        return None


def _parse_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    val = s.strip()
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"
    try:
        datetime.fromisoformat(val)
        return True
    except Exception:
        return False


def _normalize_os_name(os_str: str) -> Optional[str]:
    if not isinstance(os_str, str):
        return None
    s = os_str.strip().lower()
    if s in ("windows", "win", "win32", "win64"):
        return "Windows"
    if s in ("macos", "darwin", "osx", "mac"):
        return "macOS"
    if s in ("linux",):
        return "Linux"
    if os_str in ("Windows", "macOS", "Linux"):
        return os_str
    return None


def _extract_cmd_field(entry: Dict[str, Any], key: str) -> Any:
    if key == "os":
        if "os" in entry:
            return entry.get("os")
        if "OS" in entry:
            return entry.get("OS")
    return entry.get(key)


def _count_error_entries(entries: List[Dict[str, Any]]) -> int:
    count = 0
    for e in entries:
        exit_code = _extract_cmd_field(e, "exit_code")
        stderr = _extract_cmd_field(e, "stderr")
        code_val = 0
        if isinstance(exit_code, int):
            code_val = exit_code
        elif isinstance(exit_code, str):
            try:
                code_val = int(exit_code.strip())
            except Exception:
                code_val = 0
        else:
            code_val = 0
        is_error = code_val != 0
        if not is_error and isinstance(stderr, str) and stderr.strip():
            is_error = True
        if is_error:
            count += 1
    return count


def _match_command_to_os_patterns(command: str, os_name: str) -> bool:
    if not isinstance(command, str):
        return False
    c = command.strip().lower()
    if os_name == "Windows":
        return (
            "get-ciminstance win32_startupcommand" in c
            or "schtasks /query" in c
            or ("reg query" in c and "currentversion\\run" in c and ("hkcu" in c or "hklm" in c))
        )
    if os_name == "macOS":
        return (
            "launchctl list" in c
            or (c.startswith("ls ") and ("launchagents" in c or "launchdaemons" in c))
            or ("osascript" in c and "login item" in c)
        )
    if os_name == "Linux":
        return (
            ("systemctl list-unit-files" in c and "--state=enabled" in c and "--type=service" in c)
            or (c.startswith("ls ") and ".config/autostart" in c)
            or (c.strip() == "crontab -l")
            or ("service --status-all" in c)
        )
    return False


def _load_keywords(workspace: Path) -> Optional[List[str]]:
    keywords_path = workspace / "input" / "keywords.json"
    kws = _safe_json_load(keywords_path)
    if not isinstance(kws, list):
        return None
    cleaned: List[str] = []
    for k in kws:
        if isinstance(k, str) and k.strip():
            cleaned.append(k.strip().lower())
        else:
            return None
    return cleaned


def _recompute_matched_keywords(item: Dict[str, Any], keywords: List[str]) -> Optional[List[str]]:
    name = item.get("name")
    path_ident = item.get("path_or_identifier")
    text_parts: List[str] = []
    if isinstance(name, str):
        text_parts.append(name)
    if isinstance(path_ident, str):
        text_parts.append(path_ident)
    combined = " ".join(text_parts).lower()
    if not combined:
        return []
    matches: List[str] = []
    for kw in keywords:
        if kw in combined:
            matches.append(kw)
    seen = set()
    uniq: List[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq


def _parse_markdown_sections(text: str) -> Dict[str, Tuple[int, int]]:
    lines = text.splitlines()
    heading_indices = []
    for i, line in enumerate(lines):
        if line.strip().startswith("## "):
            heading_indices.append(i)
    sections: Dict[str, Tuple[int, int]] = {}
    for idx, start_line in enumerate(heading_indices):
        heading_line = lines[start_line].strip()
        title = heading_line[3:] if len(heading_line) >= 3 else heading_line
        end_line = len(lines)
        if idx + 1 < len(heading_indices):
            end_line = heading_indices[idx + 1]
        sections[title] = (start_line + 1, end_line)
    return sections


def _get_section_content(text: str, section_title: str) -> Optional[str]:
    sections = _parse_markdown_sections(text)
    if section_title not in sections:
        return None
    start, end = sections[section_title]
    lines = text.splitlines()
    content_lines = lines[start:end]
    return "\n".join(content_lines).rstrip("\n")


def _replace_section_content(text: str, section_title: str, replacement: str) -> Optional[str]:
    sections = _parse_markdown_sections(text)
    if section_title not in sections:
        return None
    start, end = sections[section_title]
    lines = text.splitlines()
    new_lines = lines[:start] + replacement.splitlines() + lines[end:]
    return "\n".join(new_lines)


def _remove_section(text: str, section_title: str) -> str:
    sections = _parse_markdown_sections(text)
    if section_title not in sections:
        return text
    start, end = sections[section_title]
    lines = text.splitlines()
    new_lines = lines[: start - 1] + lines[end:]
    return "\n".join(new_lines)


def _extract_first_line_title(text: str) -> Optional[str]:
    lines = text.splitlines()
    if not lines:
        return None
    first = lines[0].strip()
    if first.startswith("#"):
        first = first.lstrip("#").strip()
    if not first:
        return None
    return first


def _infer_exhibition_title_from_first_line(text: str) -> Optional[str]:
    title_line = _extract_first_line_title(text)
    if not title_line:
        return None
    parts = re.split(r"\s+[—-]\s+", title_line)
    if parts:
        return parts[0].strip()
    return title_line


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "commands_log_exists": 0.0,
        "commands_log_jsonl_valid": 0.0,
        "commands_at_least_two_from_os_list": 0.0,
        "commands_log_fields_complete": 0.0,
        "autostart_report_exists": 0.0,
        "autostart_report_structure_valid": 0.0,
        "autostart_report_sources_consistent_with_items": 0.0,
        "autostart_report_matched_keywords_correct": 0.0,
        "autostart_report_summary_totals_correct": 0.0,
        "autostart_report_summary_errors_logged_correct": 0.0,
        "review_revised_exists": 0.0,
        "review_tech_notes_single_paragraph_acknowledges_and_non_accusatory": 0.0,
        "review_appendix_present_and_consistent": 0.0,
        "review_preserves_other_sections": 0.0,
        "email_exists": 0.0,
        "email_to_and_subject_valid": 0.0,
        "email_body_apology_counts_steps": 0.0,
    }

    commands_log_path = workspace / "output" / "commands_log.jsonl"
    report_path = workspace / "output" / "autostart_report.json"
    revised_md_path = workspace / "output" / "review_draft_revised.md"
    email_path = workspace / "output" / "email_to_gallery.txt"
    input_md_path = workspace / "input" / "review_draft.md"

    input_md = _safe_read_text(input_md_path)
    keywords = _load_keywords(workspace)

    commands_entries = _safe_jsonl_load(commands_log_path)
    if commands_entries is not None:
        scores["commands_log_exists"] = 1.0
        fields_ok = True
        for e in commands_entries:
            ts = _extract_cmd_field(e, "timestamp")
            os_field = _extract_cmd_field(e, "os")
            cmd = _extract_cmd_field(e, "command")
            exit_code = _extract_cmd_field(e, "exit_code")
            stdout = _extract_cmd_field(e, "stdout")
            stderr = _extract_cmd_field(e, "stderr")
            if not isinstance(ts, str) or not _parse_iso8601(ts):
                fields_ok = False
                break
            if not isinstance(os_field, str) or not os_field.strip():
                fields_ok = False
                break
            if not isinstance(cmd, str) or not cmd.strip():
                fields_ok = False
                break
            if not (isinstance(exit_code, int) or isinstance(exit_code, str)):
                fields_ok = False
                break
            if not isinstance(stdout, (str, type(None))):
                fields_ok = False
                break
            if not isinstance(stderr, (str, type(None))):
                fields_ok = False
                break
        if fields_ok:
            scores["commands_log_jsonl_valid"] = 1.0

    report = _safe_json_load(report_path)
    if isinstance(report, dict):
        scores["autostart_report_exists"] = 1.0
        os_val = report.get("os")
        scanned_at = report.get("scanned_at")
        sources = report.get("sources")
        items = report.get("autostart_items")
        summary = report.get("summary")
        struct_ok = True
        norm_os = _normalize_os_name(os_val) if isinstance(os_val, str) else None
        if norm_os not in ("Windows", "macOS", "Linux"):
            struct_ok = False
        if not isinstance(scanned_at, str) or not _parse_iso8601(scanned_at):
            struct_ok = False
        if not (isinstance(sources, list) and all(isinstance(s, str) for s in sources)):
            struct_ok = False
        if not isinstance(items, list):
            struct_ok = False
        else:
            for it in items:
                if not isinstance(it, dict):
                    struct_ok = False
                    break
                if "name" not in it or "source" not in it or "path_or_identifier" not in it or "enabled" not in it or "user_scope" not in it or "matched_keywords" not in it:
                    struct_ok = False
                    break
                name_ok = (it["name"] is None) or isinstance(it["name"], str)
                source_ok = isinstance(it["source"], str)
                poi_ok = (it["path_or_identifier"] is None) or isinstance(it["path_or_identifier"], str)
                enabled_ok = (it["enabled"] in (True, False, None))
                user_scope_ok = it["user_scope"] in ("user", "system", "unknown")
                mk_ok = isinstance(it["matched_keywords"], list) and all(isinstance(k, str) for k in it["matched_keywords"])
                if not (name_ok and source_ok and poi_ok and enabled_ok and user_scope_ok and mk_ok):
                    struct_ok = False
                    break
        if not (isinstance(summary, dict) and all(k in summary for k in ("total_items", "flagged_items", "errors_logged"))):
            struct_ok = False
        else:
            if not (isinstance(summary.get("total_items"), int) and isinstance(summary.get("flagged_items"), int) and isinstance(summary.get("errors_logged"), int)):
                struct_ok = False
        if struct_ok:
            scores["autostart_report_structure_valid"] = 1.0

        if struct_ok:
            if isinstance(sources, list) and isinstance(items, list):
                if all(isinstance(it, dict) and it.get("source") in sources for it in items):
                    scores["autostart_report_sources_consistent_with_items"] = 1.0

        if struct_ok and keywords is not None:
            consistent = True
            for it in items:
                recomputed = _recompute_matched_keywords(it, keywords)
                if recomputed is None:
                    consistent = False
                    break
                reported = it.get("matched_keywords", [])
                if not isinstance(reported, list):
                    consistent = False
                    break
                if set([k.lower() for k in reported]) != set(recomputed):
                    consistent = False
                    break
            if consistent:
                scores["autostart_report_matched_keywords_correct"] = 1.0

        if struct_ok:
            total_items = len(items) if isinstance(items, list) else 0
            flagged_count = 0
            if isinstance(items, list):
                for it in items:
                    mk = it.get("matched_keywords", [])
                    if isinstance(mk, list) and len(mk) > 0:
                        flagged_count += 1
            if report["summary"].get("total_items") == total_items and report["summary"].get("flagged_items") == flagged_count:
                scores["autostart_report_summary_totals_correct"] = 1.0

        if struct_ok and commands_entries is not None:
            errors_logged_calc = _count_error_entries(commands_entries)
            if isinstance(report["summary"].get("errors_logged"), int) and report["summary"]["errors_logged"] == errors_logged_calc:
                scores["autostart_report_summary_errors_logged_correct"] = 1.0

        if commands_entries is not None and norm_os in ("Windows", "macOS", "Linux"):
            matched = 0
            for e in commands_entries:
                cmd = _extract_cmd_field(e, "command")
                if isinstance(cmd, str) and _match_command_to_os_patterns(cmd, norm_os):
                    matched += 1
            if matched >= 2:
                scores["commands_at_least_two_from_os_list"] = 1.0

    if commands_entries is not None and scores["commands_log_jsonl_valid"] == 1.0:
        consistent = True
        for e in commands_entries:
            os_field = _extract_cmd_field(e, "os")
            if not isinstance(os_field, str) or not os_field.strip():
                consistent = False
                break
            if "exit_code" not in e:
                consistent = False
                break
        if consistent:
            scores["commands_log_fields_complete"] = 1.0

    revised_text = _safe_read_text(revised_md_path)
    if isinstance(revised_text, str):
        scores["review_revised_exists"] = 1.0

        original_text = input_md if isinstance(input_md, str) else None
        appendix_title = "System Appendix (Audit Summary)"
        tech_title = "Technical Disruption Notes"
        if original_text is not None:
            orig_tech_content = _get_section_content(original_text, tech_title)
            orig_sanitized = original_text
            if orig_tech_content is not None:
                rep = ""
                new_orig = _replace_section_content(original_text, tech_title, rep)
                if isinstance(new_orig, str):
                    orig_sanitized = new_orig.replace("\r\n", "\n")
            rev_no_tech = _replace_section_content(revised_text, tech_title, "")
            if rev_no_tech is None:
                rev_no_tech = revised_text
            rev_sanitized = _remove_section(rev_no_tech, appendix_title).replace("\r\n", "\n")
            if orig_sanitized == rev_sanitized:
                scores["review_preserves_other_sections"] = 1.0

        rev_tech_content = _get_section_content(revised_text, tech_title)
        tech_ok = False
        if isinstance(rev_tech_content, str):
            content = rev_tech_content.strip()
            paragraphs = [p for p in re.split(r"\n\s*\n", content) if p.strip() != ""]
            single_para = len(paragraphs) == 1
            lower_content = content.lower()
            forbidden_patterns = [
                "artists’ software",
                "artists' software",
                "their program",
                "injected",
                "meddling",
            ]
            non_accusatory = not any(fp in lower_content for fp in forbidden_patterns)
            acknowledges = (
                ("auto-start" in lower_content)
                or ("login item" in lower_content)
                or ("notification" in lower_content)
                or ("notifications" in lower_content)
            )
            flagged_num = None
            if isinstance(report, dict):
                try:
                    flagged_num = int(report.get("summary", {}).get("flagged_items", None))
                except Exception:
                    flagged_num = None
            references = ("flag" in lower_content)
            if flagged_num is not None and isinstance(flagged_num, int):
                if str(flagged_num) in lower_content:
                    references = True
            if single_para and non_accusatory and acknowledges and references:
                tech_ok = True
        if tech_ok:
            scores["review_tech_notes_single_paragraph_acknowledges_and_non_accusatory"] = 1.0

        appendix_ok = False
        appendix_content = _get_section_content(revised_text, appendix_title)
        if appendix_content is not None:
            ac = appendix_content.strip()
            if isinstance(report, dict) and isinstance(report.get("summary", {}).get("flagged_items", None), int):
                flagged_num = report["summary"]["flagged_items"]
                if flagged_num == 0:
                    if re.search(r"\bno\b", ac.lower()) and ("identify" in ac.lower() or "identified" in ac.lower()):
                        appendix_ok = True
                else:
                    lines = [ln.strip() for ln in ac.splitlines() if ln.strip()]
                    flagged_items: List[Dict[str, Any]] = []
                    for it in report.get("autostart_items", []):
                        mk = it.get("matched_keywords", [])
                        if isinstance(mk, list) and len(mk) > 0:
                            flagged_items.append(it)
                    match_found = False
                    for it in flagged_items[:5]:
                        src = str(it.get("source", ""))
                        name = it.get("name")
                        path_ident = it.get("path_or_identifier")
                        token1 = None
                        if isinstance(name, str) and name.strip():
                            token1 = name.strip()
                        elif isinstance(path_ident, str) and path_ident.strip():
                            token1 = path_ident.strip()
                        if not token1 or not src:
                            continue
                        for ln in lines:
                            if token1 in ln and src in ln:
                                match_found = True
                                break
                        if match_found:
                            break
                    if match_found:
                        appendix_ok = True
        if appendix_ok:
            scores["review_appendix_present_and_consistent"] = 1.0

    email_text = _safe_read_text(email_path)
    if isinstance(email_text, str):
        scores["email_exists"] = 1.0
        to_match = re.search(r"^To:\s*(.+)$", email_text, re.IGNORECASE | re.MULTILINE)
        subj_match = re.search(r"^Subject:\s*(.+)$", email_text, re.IGNORECASE | re.MULTILINE)
        to_ok = False
        subject_ok = False
        if to_match:
            to_val = to_match.group(1).strip()
            if to_val.lower() == "tech@gallery.example":
                to_ok = True
        exhibition_title = None
        if isinstance(input_md, str):
            exhibition_title = _infer_exhibition_title_from_first_line(input_md)
        if subj_match:
            subject_val = subj_match.group(1).strip()
            subj_lower = subject_val.lower()
            has_prefix = "correction re:" in subj_lower
            has_suffix = "disruption note" in subj_lower
            title_ok = False
            if exhibition_title:
                if exhibition_title.lower() in subj_lower:
                    title_ok = True
                full_header = _extract_first_line_title(input_md) or ""
                if full_header and full_header.lower() in subj_lower:
                    title_ok = True
            subject_ok = has_prefix and has_suffix and title_ok
        if to_ok and subject_ok:
            scores["email_to_and_subject_valid"] = 1.0

        body_text = email_text
        if subj_match:
            body_start = subj_match.end()
            body_text = email_text[body_start:].strip()
        body_lower = body_text.lower()
        apology_ok = ("apolog" in body_lower) or ("sorry" in body_lower)
        total_ok = False
        flagged_ok = False
        if isinstance(report, dict) and isinstance(report.get("summary", {}), dict):
            total_items = report["summary"].get("total_items")
            flagged_items = report["summary"].get("flagged_items")
            try:
                if str(int(total_items)) in body_lower:
                    total_ok = True
            except Exception:
                pass
            try:
                if str(int(flagged_items)) in body_lower:
                    flagged_ok = True
            except Exception:
                pass
        step_keywords = [
            "do not disturb",
            "focus assist",
            "disable",
            "login item",
            "silence",
            "turn off",
            "mute",
            "notification",
            "temporarily",
            "snooze",
        ]
        found_set = set()
        for kw in step_keywords:
            if kw in body_lower:
                found_set.add(kw)
        steps_ok = len(found_set) >= 2
        if apology_ok and total_ok and flagged_ok and steps_ok:
            scores["email_body_apology_counts_steps"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()