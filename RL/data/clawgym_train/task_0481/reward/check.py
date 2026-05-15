import json
import re
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_yaml_front_matter(md_text: str) -> Tuple[Dict[str, Any], str]:
    lines = md_text.splitlines()
    front: Dict[str, Any] = {}
    body_start_index = 0
    if len(lines) >= 1 and lines[0].strip() == "---":
        # find the closing '---'
        end_index = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_index = i
                break
        if end_index is not None:
            front_lines = lines[1:end_index]
            body_start_index = end_index + 1
            # minimal YAML parsing for the known schema
            key = None
            in_list = False
            list_accum: List[str] = []
            for ln in front_lines:
                if re.match(r"^\s*-\s+", ln) and key is not None and in_list:
                    item = re.sub(r"^\s*-\s+", "", ln).strip()
                    # strip optional quotes
                    if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                        item = item[1:-1]
                    list_accum.append(item)
                else:
                    m = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.*)$", ln.rstrip())
                    if m:
                        if key is not None and in_list:
                            front[key] = list_accum[:]
                            list_accum.clear()
                            in_list = False
                        key = m.group(1)
                        val = m.group(2).strip()
                        if val == "" and key == "follow_up_with":
                            in_list = True
                            list_accum = []
                        else:
                            # scalar
                            sval = val
                            if (sval.startswith('"') and sval.endswith('"')) or (sval.startswith("'") and sval.endswith("'")):
                                sval = sval[1:-1]
                            front[key] = sval
                    else:
                        # Non-matching line, if we were in a list, continue; else ignore
                        continue
            if key is not None and in_list:
                front[key] = list_accum[:]
        else:
            body_start_index = 0
    body = "\n".join(lines[body_start_index:])
    return front, body


def _find_markdown_links(md_body: str) -> List[str]:
    links = []
    # Match [text](link), ignoring images ![alt](link)
    pattern = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)]+)\)")
    for m in pattern.finditer(md_body):
        raw = m.group(1).strip()
        if not raw:
            continue
        # skip URLs and anchors
        lower = raw.lower()
        if "://" in lower or lower.startswith("mailto:") or lower.startswith("#"):
            continue
        links.append(raw)
    return links


def _resolve_link_relative_to_workspace(base_file: Path, rel_link: str, workspace: Path) -> Path:
    # Attempt to resolve to a normalized path relative to workspace root
    joined = (base_file.parent / rel_link)
    try:
        abs_path = joined.resolve()
    except Exception:
        # fallback: normalize manually
        abs_path = Path(os.path.normpath(str(joined)))
    try:
        rel = abs_path.resolve().relative_to(workspace.resolve())
        return workspace / rel
    except Exception:
        # If it can't be made relative (e.g., outside workspace), keep absolute
        return abs_path


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _last_non_empty_line(s: str) -> str:
    for line in reversed(s.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _run_encrypt_tool(workspace: Path) -> Tuple[int, str, str]:
    cmd = ["python3", "tools/encrypt.py"]
    try:
        proc = subprocess.run(cmd, cwd=str(workspace), capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        # Could not invoke; emulate failure with stderr summary
        return 1, "", f"{e}"


def _collect_expected_from_workspace(workspace: Path) -> Dict[str, Any]:
    # Collect drafts
    drafts_info = []
    for md in sorted(workspace.glob("drafts/**/*.md")):
        text = _read_text(md)
        if text is None:
            continue
        front, body = _parse_yaml_front_matter(text)
        title = front.get("title")
        review_due = front.get("review_due")
        follow = front.get("follow_up_with")
        if not isinstance(title, str) or not isinstance(review_due, str) or _parse_date(review_due) is None:
            continue
        if not isinstance(follow, list):
            follow = []
        links = _find_markdown_links(body)
        missing: List[str] = []
        for lk in links:
            resolved_path = _resolve_link_relative_to_workspace(md, lk, workspace)
            # Make string relative to workspace if possible
            try:
                rel = resolved_path.resolve().relative_to(workspace.resolve())
                candidate = workspace / rel
                rel_str = rel.as_posix()
            except Exception:
                candidate = resolved_path
                rel_str = str(resolved_path)
            if not candidate.exists():
                missing.append(rel_str)
        severity = "warning" if len(missing) > 0 else "normal"
        drafts_info.append({
            "type": "draft",
            "date": review_due,
            "title": title,
            "people": follow,
            "missing_attachments": missing,
            "severity": severity,
            "source_file": md.as_posix(),
        })
    # Collect todos
    todos_info = []
    todo_path = workspace / "notes" / "todo.md"
    todo_text = _read_text(todo_path)
    if todo_text is not None:
        for line in todo_text.splitlines():
            m = re.match(r"^\s*REMIND\s+(\d{4}-\d{2}-\d{2}):\s*(.+?)\s*$", line)
            if m:
                d = m.group(1)
                txt = m.group(2)
                if _parse_date(d) is not None:
                    todos_info.append({
                        "type": "todo",
                        "date": d,
                        "title": txt,
                        "severity": "normal",
                        "source_file": todo_path.as_posix(),
                    })
    # Run tool and expected tool error
    exit_code, out, err = _run_encrypt_tool(workspace)
    tool_log = {
        "cmd": "python3 tools/encrypt.py",
        "exit_code": exit_code,
        "stdout": out,
        "stderr": err,
    }
    tool_error_info = None
    if exit_code != 0:
        # determine latest date among drafts and todos
        all_dates = []
        for it in drafts_info + todos_info:
            if isinstance(it.get("date"), str) and _parse_date(it["date"]) is not None:
                all_dates.append(it["date"])
        assigned_date = None
        if all_dates:
            assigned_date = max(all_dates)
        error_entry = {
            "type": "tool_error",
            "title": "Encrypt tool check failed",
            "severity": "error",
            "source_file": "tools/encrypt.py",
            "error_summary": _last_non_empty_line(err),
        }
        if assigned_date is not None:
            error_entry["date"] = assigned_date
        tool_error_info = error_entry
    return {
        "drafts": drafts_info,
        "todos": todos_info,
        "tool_error": tool_error_info,
        "tool_log": tool_log,
    }


def _is_sorted_by_date(items: List[Dict[str, Any]]) -> bool:
    prev: Optional[str] = None
    for obj in items:
        d = obj.get("date")
        if d is None:
            # date omitted only allowed when there are no other items; but for sorting, treat None as smallest
            d_key = ""
        else:
            d_key = d
        if prev is not None and d_key < prev:
            return False
        prev = d_key
    return True


def _match_item(actual: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    # Match on type, title, and date (or lack thereof)
    if actual.get("type") != expected.get("type"):
        return False
    if actual.get("title") != expected.get("title"):
        return False
    if ("date" in expected) != ("date" in actual):
        return False
    if "date" in expected and actual.get("date") != expected.get("date"):
        return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "reminders_json_exists_and_parseable": 0.0,
        "reminders_json_items_count": 0.0,
        "reminders_json_drafts_correct": 0.0,
        "reminders_json_todos_correct": 0.0,
        "reminders_json_tool_error_entry": 0.0,
        "reminders_json_sorted_by_date": 0.0,
        "notifications_exists_and_format": 0.0,
        "notifications_lines_match_count": 0.0,
        "notifications_cover_all_items": 0.0,
        "encrypt_log_exists_and_content": 0.0,
    }

    # Compute expected data from workspace
    expected = _collect_expected_from_workspace(workspace)
    expected_drafts: List[Dict[str, Any]] = expected["drafts"]
    expected_todos: List[Dict[str, Any]] = expected["todos"]
    expected_tool_error: Optional[Dict[str, Any]] = expected["tool_error"]
    tool_log_expected = expected["tool_log"]
    expected_count = len(expected_drafts) + len(expected_todos) + (1 if expected_tool_error is not None else 0)

    # Load reminders JSON
    reminders_path = workspace / "reminders" / "reminders.json"
    reminders_data = _load_json(reminders_path)
    if isinstance(reminders_data, list):
        scores["reminders_json_exists_and_parseable"] = 1.0
        # items count
        if len(reminders_data) == expected_count:
            scores["reminders_json_items_count"] = 1.0

        # sorted by date ascending
        # Ensure date strings are proper ISO or absent for tool_error when no other items exist
        # Validate that if there are any non-tool_error items, all items must have 'date' (tool_error included).
        all_have_dates = all(("date" in it and isinstance(it.get("date"), str)) for it in reminders_data)
        if expected_count == 0:
            # nothing to require
            pass
        else:
            # If expected_tool_error is present, it should include date unless there were no drafts/todos
            pass
        if _is_sorted_by_date(reminders_data):
            scores["reminders_json_sorted_by_date"] = 1.0

        # Validate drafts
        draft_ok = True
        for exp in expected_drafts:
            matched = None
            for act in reminders_data:
                if _match_item(act, exp):
                    matched = act
                    break
            if matched is None:
                draft_ok = False
                break
            # Check fields for draft
            if matched.get("type") != "draft":
                draft_ok = False
                break
            if matched.get("severity") != exp.get("severity"):
                draft_ok = False
                break
            if matched.get("source_file") != exp.get("source_file"):
                draft_ok = False
                break
            if matched.get("people") != exp.get("people"):
                draft_ok = False
                break
            # missing_attachments exact list
            if matched.get("missing_attachments") != exp.get("missing_attachments"):
                draft_ok = False
                break
            # ensure no error_summary for drafts
            if "error_summary" in matched:
                draft_ok = False
                break
        if draft_ok and len(expected_drafts) > 0:
            scores["reminders_json_drafts_correct"] = 1.0
        elif draft_ok and len(expected_drafts) == 0:
            # If no drafts expected, consider this check as passing if there are no drafts in actual
            if all(it.get("type") != "draft" for it in reminders_data):
                scores["reminders_json_drafts_correct"] = 1.0

        # Validate todos
        todos_ok = True
        for exp in expected_todos:
            matched = None
            for act in reminders_data:
                if _match_item(act, exp):
                    matched = act
                    break
            if matched is None:
                todos_ok = False
                break
            if matched.get("type") != "todo":
                todos_ok = False
                break
            if matched.get("severity") != "normal":
                todos_ok = False
                break
            if matched.get("source_file") != exp.get("source_file"):
                todos_ok = False
                break
            if "people" in matched:
                todos_ok = False
                break
            if "missing_attachments" in matched:
                todos_ok = False
                break
            if "error_summary" in matched:
                todos_ok = False
                break
        if todos_ok and len(expected_todos) > 0:
            scores["reminders_json_todos_correct"] = 1.0
        elif todos_ok and len(expected_todos) == 0:
            if all(it.get("type") != "todo" for it in reminders_data):
                scores["reminders_json_todos_correct"] = 1.0

        # Validate tool_error
        tool_err_ok = False
        if expected_tool_error is None:
            # No tool error expected; ensure none present
            tool_err_ok = all(it.get("type") != "tool_error" for it in reminders_data)
        else:
            # Find tool_error
            candidates = [it for it in reminders_data if it.get("type") == "tool_error"]
            if len(candidates) == 1:
                act = candidates[0]
                # date rules
                if ("date" in expected_tool_error) != ("date" in act):
                    tool_err_ok = False
                else:
                    if "date" not in expected_tool_error or act.get("date") == expected_tool_error.get("date"):
                        # check other fields
                        if act.get("title") == "Encrypt tool check failed" and act.get("severity") == "error" and act.get("source_file") == "tools/encrypt.py":
                            errsum = act.get("error_summary")
                            if isinstance(errsum, str) and errsum.strip() == _last_non_empty_line(tool_log_expected["stderr"]).strip():
                                # ensure no people/missing_attachments
                                if "people" not in act and "missing_attachments" not in act:
                                    tool_err_ok = True
        if tool_err_ok:
            scores["reminders_json_tool_error_entry"] = 1.0
    else:
        # Not a list or cannot parse
        pass

    # Notifications checks
    notifications_path = workspace / "reminders" / "notifications.txt"
    notif_text = _read_text(notifications_path)
    if isinstance(reminders_data, list) and notif_text is not None:
        lines = [ln for ln in notif_text.splitlines() if ln.strip() != ""]
        scores["notifications_exists_and_format"] = 1.0
        if len(lines) == len(reminders_data):
            scores["notifications_lines_match_count"] = 1.0

        # Check that for each reminder item, there exists a line that includes date (if present), title, type, severity
        def line_covers(item: Dict[str, Any], line: str) -> bool:
            need = []
            if "date" in item:
                need.append(str(item["date"]))
            need.append(str(item.get("title", "")))
            need.append(str(item.get("type", "")))
            need.append(str(item.get("severity", "")))
            return all((str(x) in line) for x in need)

        cover_ok = True
        unused_lines = set(range(len(lines)))
        for it in reminders_data:
            found = False
            for idx in list(unused_lines):
                if line_covers(it, lines[idx]):
                    found = True
                    unused_lines.remove(idx)
                    break
            if not found:
                cover_ok = False
                break
        if cover_ok:
            scores["notifications_cover_all_items"] = 1.0

    # Encrypt log checks
    encrypt_log_path = workspace / "logs" / "encrypt_check.txt"
    log_text = _read_text(encrypt_log_path)
    if log_text is not None:
        cmd_ok = "python3 tools/encrypt.py" in log_text
        exit_ok = False
        # try to find the exit code number in the log
        try:
            exit_code_expected = int(tool_log_expected["exit_code"])
            # Look for a standalone number or after typical labels
            # First, try regex to find a number following 'exit' or 'code'
            m = re.search(r"(exit\s*code\s*[:=]?\s*|exit\s*[:=]?\s*|code\s*[:=]?\s*)(-?\d+)", log_text, flags=re.IGNORECASE)
            if m:
                exit_ok = (int(m.group(2)) == exit_code_expected)
            else:
                # Fallback: check that the exact number appears somewhere
                exit_ok = re.search(rf"\b{exit_code_expected}\b", log_text) is not None
        except Exception:
            exit_ok = False
        stdout_ok = True
        if isinstance(tool_log_expected["stdout"], str) and tool_log_expected["stdout"]:
            stdout_ok = tool_log_expected["stdout"] in log_text
        stderr_ok = True
        if isinstance(tool_log_expected["stderr"], str) and tool_log_expected["stderr"]:
            stderr_full_present = tool_log_expected["stderr"] in log_text
            stderr_last_line_present = _last_non_empty_line(tool_log_expected["stderr"]) in log_text
            stderr_ok = stderr_full_present or stderr_last_line_present
        if cmd_ok and exit_ok and stdout_ok and stderr_ok:
            scores["encrypt_log_exists_and_content"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()