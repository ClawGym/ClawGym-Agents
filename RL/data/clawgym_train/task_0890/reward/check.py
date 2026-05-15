import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    # skip malformed lines
                    pass
    except Exception:
        return []
    return rows

def parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    # Try ISO formats
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:len(fmt)], fmt)
        except Exception:
            continue
    return None

def normalize_text_value(v: Any) -> str:
    # Normalize value to a comparable multi-line text form
    if isinstance(v, list):
        items = []
        for x in v:
            if isinstance(x, str):
                ix = x.strip()
                if ix:
                    items.append(ix)
            else:
                items.append(str(x).strip())
        return "\n".join(items).strip()
    elif isinstance(v, str):
        return v.strip()
    else:
        return str(v).strip()

def split_items(v: Any) -> List[str]:
    # Split list-like content into items; used for counting
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        # Split on newlines or semicolons
        parts = []
        for piece in re.split(r"[\n;]", v):
            p = piece.strip()
            if p and p not in ("-", "•"):
                parts.append(p)
        return parts
    return [str(v).strip()] if str(v).strip() else []

def find_key(d: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    lower_map = {k.lower(): k for k in d.keys()}
    for c in candidates:
        if c in d:
            return c
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None

def tasks_from_input(obj: Any) -> List[Dict[str, Any]]:
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        if isinstance(obj.get("tasks"), list):
            return [x for x in obj["tasks"] if isinstance(x, dict)]
        # else: maybe it's just a dict with task entries? fallback none
    return []

def extract_task_id(task: Dict[str, Any]) -> Optional[str]:
    for k in ["id", "task_id", "key", "uid", "identifier", "name"]:
        if k in task and task[k] is not None:
            return str(task[k])
    # fallback: None
    return None

def extract_task_status(task: Dict[str, Any]) -> str:
    for k in ["status", "state", "phase"]:
        if k in task and isinstance(task[k], str) and task[k].strip():
            return task[k].strip()
    return "unknown"

def extract_task_due_date(task: Dict[str, Any]) -> Optional[datetime]:
    for k in ["due_date", "due", "dueDate", "deadline"]:
        if k in task:
            dt = parse_date(str(task[k]))
            if dt:
                return dt
    return None

def extract_task_blocker(task: Dict[str, Any]) -> bool:
    # consider multiple possible flags; also consider non-empty blockers array
    for k in ["blocker", "blocked", "has_blocker", "is_blocker", "isBlocked"]:
        if k in task and isinstance(task[k], bool):
            return bool(task[k])
    # blockers array or text
    for k in ["blockers"]:
        if k in task:
            val = task[k]
            if isinstance(val, list):
                return any(bool(str(x).strip()) for x in val)
            if isinstance(val, str):
                return bool(val.strip())
    return False

def extract_task_overdue(task: Dict[str, Any]) -> Optional[bool]:
    # explicit overdue flags
    for k in ["overdue", "is_overdue", "past_due", "pastDue"]:
        if k in task and isinstance(task[k], bool):
            return bool(task[k])
    return None

def determine_as_of(obj: Any) -> Optional[datetime]:
    if isinstance(obj, dict):
        for k in ["as_of", "today", "date", "asOf"]:
            if k in obj:
                dt = parse_date(str(obj[k]))
                if dt:
                    return dt
    return None

def compute_expected_from_tasks(tasks_obj: Any) -> Tuple[Dict[str, int], List[str], List[str]]:
    tasks = tasks_from_input(tasks_obj)
    status_counts: Dict[str, int] = {}
    overdue_ids: List[str] = []
    blocker_ids: List[str] = []

    # build status counts
    for t in tasks:
        st = extract_task_status(t)
        status_counts[st] = status_counts.get(st, 0) + 1

    # overdue logic:
    # 1) if explicit boolean present, use it
    # 2) else if as_of provided at top, compare due_date < as_of
    # 3) else leave overdue empty to keep deterministic
    top_as_of = determine_as_of(tasks_obj)
    for t in tasks:
        tid = extract_task_id(t)
        if not tid:
            continue
        overdue_flag = extract_task_overdue(t)
        if overdue_flag is True:
            overdue_ids.append(tid)
        elif overdue_flag is None and top_as_of is not None:
            due = extract_task_due_date(t)
            if due and due < top_as_of:
                overdue_ids.append(tid)

    # blockers list
    for t in tasks:
        tid = extract_task_id(t)
        if not tid:
            continue
        if extract_task_blocker(t):
            blocker_ids.append(tid)

    return status_counts, overdue_ids, blocker_ids

def parse_counts_table(md: str) -> Dict[str, int]:
    # Find a markdown table with headers Status and Count
    lines = md.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if "|" in line and "status" in line.lower() and "count" in line.lower():
            header_idx = i
            break
    counts: Dict[str, int] = {}
    if header_idx is None:
        return counts
    # rows follow after header and possibly a separator line
    i = header_idx + 1
    # skip separator lines like |---|---|
    if i < len(lines) and re.search(r"\|\s*-+\s*\|\s*-+\s*\|", lines[i]):
        i += 1
    # parse until a blank line or non-table line
    for j in range(i, len(lines)):
        row = lines[j]
        if "|" not in row:
            break
        cols = [c.strip() for c in row.strip().split("|") if c.strip() != ""]
        if len(cols) < 2:
            continue
        # assume first relevant cols are status and count
        status = cols[0]
        count_str = None
        # find the first integer-like column
        for c in cols[1:]:
            if re.fullmatch(r"\d+", c):
                count_str = c
                break
        if status and count_str is not None:
            try:
                counts[status] = int(count_str)
            except Exception:
                pass
    return counts

def extract_uuid_blocks(text: str) -> Dict[str, Any]:
    # Identify stdout/stderr blocks and IDs
    result = {
        "stdout_id": None,
        "stderr_id": None,
        "exit_id": None,
        "stdout_content": None,
        "stderr_content": None,
        "exit_code": None,
        "preamble": None
    }
    # Find first stdout
    m_stdout_open = re.search(r'<<<STDOUT:([^\>]+)>>>\n', text)
    m_stderr_open = re.search(r'<<<STDERR:([^\>]+)>>>\n', text)
    if m_stdout_open:
        sid = m_stdout_open.group(1)
        result["stdout_id"] = sid
        # find end
        m_stdout_close = re.search(r'<<<END_STDOUT:' + re.escape(sid) + r'>>>', text)
        if m_stdout_close:
            start = m_stdout_open.end()
            end = m_stdout_close.start()
            result["stdout_content"] = text[start:end]
            # preamble is before stdout open
            result["preamble"] = text[:m_stdout_open.start()]
    if m_stderr_open:
        tid = m_stderr_open.group(1)
        result["stderr_id"] = tid
        m_stderr_close = None
        if tid:
            m_stderr_close = re.search(r'<<<END_STDERR:' + re.escape(tid) + r'>>>', text)
        if m_stderr_close:
            start = m_stderr_open.end()
            end = m_stderr_close.start()
            result["stderr_content"] = text[start:end]
    # Exit block
    if result["stdout_id"]:
        eid = result["stdout_id"]
        m_exit = re.search(r'<<<EXIT:' + re.escape(eid) + r'>>>(\d+)<<<END_EXIT:' + re.escape(eid) + r'>>>', text)
        if m_exit:
            result["exit_id"] = eid
            result["exit_code"] = int(m_exit.group(1))
    else:
        # try generic exit detection
        m_exit_any = re.search(r'<<<EXIT:([^\>]+)>>>(\d+)<<<END_EXIT:\1>>>', text)
        if m_exit_any:
            result["exit_id"] = m_exit_any.group(1)
            result["exit_code"] = int(m_exit_any.group(2))
    return result

def objective_language_ok(s: str) -> bool:
    # Disallow subjective hedge words
    bad = ["maybe", "likely", "probably", "appears", "seems", "suggests", "might", "could be", "looks like"]
    low = s.lower()
    return not any(b in low for b in bad)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks: Dict[str, bool] = {
        "ops_json_exists": False,
        "ops_json_schema": False,
        "ops_json_counts_correct": False,
        "ops_md_exists": False,
        "ops_md_has_table_and_sections": False,
        "ops_md_counts_match": False,
        "ops_md_lists_overdue_ids": False,
        "daily_json_exists_and_values": False,
        "week_md_exists": False,
        "week_md_per_day_counts": False,
        "week_md_blockers_summary": False,
        "identity_files_exist_nonempty": False,
        "identity_no_placeholders": False,
        "identity_reflect_inputs": False,
        "safe_exec_exists": False,
        "safe_exec_structure_uuid": False,
        "safe_exec_stdout_match": False,
        "safe_exec_stderr_empty_exit0": False,
        "token_analysis_exists": False,
        "token_analysis_schema_valid": False,
        "token_analysis_objective_language": False,
    }

    # Paths
    ops_json_path = os.path.join(output_dir, "ops_summary.json")
    ops_md_path = os.path.join(output_dir, "ops_summary.md")
    tasks_json_path = os.path.join(input_dir, "tasks.json")

    daily_json_path = os.path.join(output_dir, "standups", "daily.json")
    standup_answers_path = os.path.join(input_dir, "standup_answers.json")

    week_summary_md_path = os.path.join(output_dir, "standups", "week_summary.md")
    week_jsonl_path = os.path.join(input_dir, "week_standups.jsonl")

    workspace_output_dir = os.path.join(output_dir, "workspace")
    soul_path = os.path.join(workspace_output_dir, "SOUL.md")
    user_path = os.path.join(workspace_output_dir, "USER.md")
    identity_path = os.path.join(workspace_output_dir, "IDENTITY.md")
    agents_path = os.path.join(workspace_output_dir, "AGENTS.md")
    identity_answers_path = os.path.join(input_dir, "identity_answers.json")

    safe_exec_path = os.path.join(output_dir, "security", "safe_exec_capture.txt")
    untrusted_input_path = os.path.join(input_dir, "untrusted_output.txt")

    token_analysis_path = os.path.join(output_dir, "security", "token_analysis.json")
    contracts_token_path = os.path.join(input_dir, "contracts_token.json")

    # 1) ops_summary.json and ops_summary.md
    tasks_obj = read_json(tasks_json_path)
    expected_status_counts: Dict[str, int] = {}
    expected_overdue_ids: List[str] = []
    expected_blocker_ids: List[str] = []
    if tasks_obj is not None:
        expected_status_counts, expected_overdue_ids, expected_blocker_ids = compute_expected_from_tasks(tasks_obj)

    if os.path.isfile(ops_json_path):
        ops_json = read_json(ops_json_path)
        if isinstance(ops_json, dict):
            checks["ops_json_exists"] = True
            # schema check
            has_keys = all(k in ops_json for k in ["status_counts", "overdue", "blockers"])
            correct_types = (
                isinstance(ops_json.get("status_counts"), dict)
                and isinstance(ops_json.get("overdue"), list)
                and isinstance(ops_json.get("blockers"), list)
            )
            # ensure counts are non-negative integers
            counts_ok = False
            if isinstance(ops_json.get("status_counts"), dict):
                counts_ok = all(
                    isinstance(k, str) and isinstance(v, int) and v >= 0
                    for k, v in ops_json["status_counts"].items()
                )
            checks["ops_json_schema"] = has_keys and correct_types and counts_ok

            # counts correct
            if tasks_obj is not None and checks["ops_json_schema"]:
                checks["ops_json_counts_correct"] = (
                    ops_json["status_counts"] == expected_status_counts
                    and sorted([str(i) for i in ops_json["overdue"]]) == sorted([str(i) for i in expected_overdue_ids])
                    and sorted([str(i) for i in ops_json["blockers"]]) == sorted([str(i) for i in expected_blocker_ids])
                )

    if os.path.isfile(ops_md_path):
        checks["ops_md_exists"] = True
        md_text = read_text(ops_md_path) or ""
        # Must contain a Status/Count table and labeled sections for Overdue and Blockers
        has_table = ("|" in md_text and ("status" in md_text.lower() and "count" in md_text.lower()))
        has_overdue_label = ("overdue" in md_text.lower())
        has_blockers_label = ("blocker" in md_text.lower())
        checks["ops_md_has_table_and_sections"] = has_table and has_overdue_label and has_blockers_label
        # counts match table rows
        table_counts = parse_counts_table(md_text)
        # We accept matching if for every expected status, the table has same count
        if expected_status_counts:
            counts_match = True
            for st, cnt in expected_status_counts.items():
                # find the matching status in a case-insensitive manner
                # The table may have status names with different casing; find any key equal ignoring case
                found = False
                for key, val in table_counts.items():
                    if key.strip().lower() == st.lower() and val == cnt:
                        found = True
                        break
                if not found:
                    counts_match = False
                    break
            checks["ops_md_counts_match"] = counts_match
        else:
            # If no tasks, counts should be empty or zero; accept empty
            checks["ops_md_counts_match"] = True
        # Overdue IDs listed
        if expected_overdue_ids:
            ids_present = all(str(tid) in md_text for tid in expected_overdue_ids)
            checks["ops_md_lists_overdue_ids"] = ids_present
        else:
            # If none overdue, ensure the section acknowledges none (look for 'none' or '0')
            checks["ops_md_lists_overdue_ids"] = ("overdue" in md_text.lower() and ("none" in md_text.lower() or re.search(r"\b0\b", md_text) is not None))

    # 2) daily standup
    answers_obj = read_json(standup_answers_path)
    if os.path.isfile(daily_json_path):
        out_daily = read_json(daily_json_path)
        if isinstance(out_daily, dict):
            # exactly keys: completed, planned, blockers
            keys = set(out_daily.keys())
            if keys == {"completed", "planned", "blockers"}:
                # non-empty values
                nonempty = all(bool(normalize_text_value(out_daily[k])) for k in ["completed", "planned", "blockers"])
                if answers_obj is not None and isinstance(answers_obj, dict):
                    # Compare normalized text values to input answers if possible
                    # Accept if normalized strings equal
                    match_all = True
                    for k in ["completed", "planned", "blockers"]:
                        in_k = find_key(answers_obj, [k])
                        if in_k is None:
                            # if input lacks the key, we only enforce non-empty
                            continue
                        if normalize_text_value(out_daily[k]) != normalize_text_value(answers_obj[in_k]):
                            match_all = False
                            break
                    checks["daily_json_exists_and_values"] = nonempty and match_all
                else:
                    checks["daily_json_exists_and_values"] = nonempty

    # 3) weekly history summary
    if os.path.isfile(week_summary_md_path):
        checks["week_md_exists"] = True
        week_md = read_text(week_summary_md_path) or ""
        week_rows = read_jsonl(week_jsonl_path)
        # Compute per day counts
        per_day_counts: List[Tuple[str, int, int]] = []
        blockers_set: List[str] = []
        for idx, row in enumerate(week_rows):
            if not isinstance(row, dict):
                continue
            date = str(row.get("date") or f"Day {idx+1}")
            comp_count = len(split_items(row.get("completed")))
            plan_count = len(split_items(row.get("planned")))
            per_day_counts.append((date, comp_count, plan_count))
            # blockers collect
            for b in split_items(row.get("blockers")):
                if b:
                    blockers_set.append(b)
        # Check counts are present in markdown (by simple presence of numbers near date)
        per_day_ok = True
        for date, c_cnt, p_cnt in per_day_counts:
            # Check date present
            if date not in week_md:
                per_day_ok = False
                break
            # Check that numbers appear somewhere (not necessarily same line)
            if str(c_cnt) not in week_md or str(p_cnt) not in week_md:
                per_day_ok = False
                break
        checks["week_md_per_day_counts"] = per_day_ok and len(per_day_counts) > 0
        # blockers summary: must include 'blockers' word and list items (if any)
        blockers_label = ("blocker" in week_md.lower())
        if blockers_set:
            all_blockers_present = all(b in week_md for b in blockers_set if b)
            checks["week_md_blockers_summary"] = blockers_label and all_blockers_present
        else:
            # If no blockers in the input, accept if file states no blockers or 0 blockers
            checks["week_md_blockers_summary"] = blockers_label and ("none" in week_md.lower() or re.search(r"\b0\b", week_md) is not None)

    # 4) identity files
    identity_files = [soul_path, user_path, identity_path, agents_path]
    if all(os.path.isfile(p) for p in identity_files):
        # non-empty
        nonempty = True
        contents = {}
        for p in identity_files:
            txt = read_text(p) or ""
            contents[p] = txt
            if not txt.strip():
                nonempty = False
        if nonempty:
            checks["identity_files_exist_nonempty"] = True
            # no placeholders like {{...}}
            no_placeholders = all(("{{" not in contents[p] and "}}" not in contents[p]) for p in identity_files)
            checks["identity_no_placeholders"] = no_placeholders
            # reflect inputs: attempt to check presence of agent name and user name/timezone if provided
            id_answers = read_json(identity_answers_path) or {}
            def find_value_by_keys(dct: Dict[str, Any], keys: List[str]) -> Optional[str]:
                if not isinstance(dct, dict):
                    return None
                for k, v in dct.items():
                    if isinstance(v, dict):
                        sub = find_value_by_keys(v, keys)
                        if sub:
                            return sub
                # direct keys by name contains substring
                for key in dct.keys():
                    for want in keys:
                        if want.lower() in key.lower():
                            val = dct.get(key)
                            if isinstance(val, str) and val.strip():
                                return val.strip()
                return None
            user_name = find_value_by_keys(id_answers, ["user_name", "name", "owner"])
            agent_name = find_value_by_keys(id_answers, ["agent_name", "agent"])
            tz = find_value_by_keys(id_answers, ["timezone", "time_zone"])
            all_text_concat = "\n".join(contents.values())
            reflect_ok = True
            if user_name and user_name not in all_text_concat:
                reflect_ok = False
            if agent_name and agent_name not in all_text_concat:
                reflect_ok = False
            if tz and tz not in all_text_concat:
                # timezone may appear or may be omitted in some files; if provided, ensure present
                reflect_ok = False
            checks["identity_reflect_inputs"] = reflect_ok

    # 5) safe_exec capture
    if os.path.isfile(safe_exec_path):
        checks["safe_exec_exists"] = True
        cap_text = read_text(safe_exec_path) or ""
        blocks = extract_uuid_blocks(cap_text)
        consistent_ids = (
            blocks["stdout_id"] is not None
            and blocks["stderr_id"] is not None
            and blocks["stdout_id"] == blocks["stderr_id"]
            and blocks["exit_id"] == blocks["stdout_id"]
        )
        preamble_ok = False
        if blocks["preamble"] is not None:
            low = blocks["preamble"].lower()
            preamble_ok = ("security" in low and "untrusted" in low and "rule" in low)
        checks["safe_exec_structure_uuid"] = consistent_ids and preamble_ok
        # stdout matches input file exactly
        in_text = read_text(untrusted_input_path)
        if in_text is None:
            # If no input file, do not award
            pass
        else:
            stdout_ok = (blocks["stdout_content"] == in_text)
            checks["safe_exec_stdout_match"] = stdout_ok
        # stderr empty and exit code 0
        stderr_empty = (blocks["stderr_content"] == "" or blocks["stderr_content"] is None and False)  # enforce empty string
        # treat None as missing; require empty string exactly
        stderr_empty = (blocks["stderr_content"] == "")
        exit_ok = (blocks["exit_code"] == 0)
        checks["safe_exec_stderr_empty_exit0"] = stderr_empty and exit_ok

    # 6) token analysis
    if os.path.isfile(token_analysis_path):
        checks["token_analysis_exists"] = True
        ta = read_json(token_analysis_path)
        schema_ok = False
        objective_ok = False
        if isinstance(ta, dict):
            required_top = ["summary", "findings", "trust_model", "token_fee_flow", "open_questions"]
            if all(k in ta for k in required_top):
                # types
                types_ok = (
                    isinstance(ta["summary"], str) and ta["summary"].strip() != "" and
                    isinstance(ta["findings"], list) and
                    isinstance(ta["trust_model"], dict) and
                    isinstance(ta["token_fee_flow"], dict) and
                    isinstance(ta["open_questions"], list)
                )
                # trust_model fields
                tm = ta.get("trust_model", {})
                tm_ok = (
                    isinstance(tm.get("upgrades"), str) and tm.get("upgrades", "").strip() != "" and
                    isinstance(tm.get("fees"), str) and tm.get("fees", "").strip() != "" and
                    isinstance(tm.get("pauses"), str) and tm.get("pauses", "").strip() != "" and
                    isinstance(tm.get("offchain_dependencies"), str) and tm.get("offchain_dependencies", "").strip() != ""
                )
                # token_fee_flow fields
                tff = ta.get("token_fee_flow", {})
                tff_ok = (
                    isinstance(tff.get("creation"), str) and tff.get("creation", "").strip() != "" and
                    isinstance(tff.get("fees_accrue"), str) and tff.get("fees_accrue", "").strip() != "" and
                    isinstance(tff.get("claims"), str) and tff.get("claims", "").strip() != "" and
                    isinstance(tff.get("mutability"), str) and tff.get("mutability", "").strip() != ""
                )
                # findings items
                findings_ok = True
                for f in ta.get("findings", []):
                    if not isinstance(f, dict):
                        findings_ok = False
                        break
                    for key in ["severity", "title", "location", "impact", "mode"]:
                        if key not in f:
                            findings_ok = False
                            break
                        if key != "mode" and (not isinstance(f[key], str) or f[key].strip() == ""):
                            findings_ok = False
                            break
                    if f.get("mode") not in ("confirmed", "conditional"):
                        findings_ok = False
                        break
                schema_ok = types_ok and tm_ok and tff_ok and findings_ok
                checks["token_analysis_schema_valid"] = schema_ok

                # Objective language in summary, findings titles/impact, trust_model fields, token_fee_flow fields
                if schema_ok:
                    obj_strings = [ta["summary"]]
                    for f in ta.get("findings", []):
                        obj_strings.extend([f.get("title",""), f.get("impact",""), f.get("location","")])
                    obj_strings.extend([tm.get("upgrades",""), tm.get("fees",""), tm.get("pauses",""), tm.get("offchain_dependencies","")])
                    obj_strings.extend([tff.get("creation",""), tff.get("fees_accrue",""), tff.get("claims",""), tff.get("mutability","")])
                    objective_ok = all(objective_language_ok(s) for s in obj_strings if isinstance(s, str))
                    checks["token_analysis_objective_language"] = objective_ok

    # Determine if any output artifact exists to avoid non-zero reward for no-op
    required_outputs = [
        ops_json_path, ops_md_path, daily_json_path, week_summary_md_path,
        soul_path, user_path, identity_path, agents_path,
        safe_exec_path, token_analysis_path
    ]
    any_output_present = any(os.path.isfile(p) for p in required_outputs)

    # Compute reward as fraction of passed checks; enforce 0.0 if no outputs
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = (passed / total) if total > 0 else 0.0
    if not any_output_present:
        reward = 0.0

    # Print result JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()