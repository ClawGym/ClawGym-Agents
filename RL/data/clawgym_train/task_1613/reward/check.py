import json
import csv
import sys
import subprocess
import re
from pathlib import Path
from typing import List, Dict, Any, Optional


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _word_count(text: str) -> int:
    # Count words as sequences of letters/digits including apostrophes/hyphens inside words
    return len(re.findall(r"\b[\w]+(?:[-'][\w]+)*\b", text))


def _classify_and_key(stdout: str, stderr: str, exit_code: int, rules: Dict[str, List[str]]) -> (str, str):
    pass_tokens = rules.get("pass_tokens", [])
    warn_tokens = rules.get("warn_tokens", [])
    error_tokens = rules.get("error_tokens", [])

    def _contains_any(line: str, tokens: List[str]) -> bool:
        return any(tok in line for tok in tokens)

    status = "pass"
    key_line = ""

    if exit_code != 0 or _contains_any(stderr, error_tokens):
        status = "fail"
        # First error token line from stderr
        for line in stderr.splitlines():
            if _contains_any(line, error_tokens):
                key_line = line
                break
        if key_line == "":
            # Fallback: first line of stderr if tokens not found (shouldn't happen given rules)
            key_line = stderr.splitlines()[0] if stderr.splitlines() else ""
        return status, key_line

    # Not fail
    if _contains_any(stdout, warn_tokens):
        status = "warn"
        for line in stdout.splitlines():
            if _contains_any(line, warn_tokens):
                key_line = line
                break
        if key_line == "":
            key_line = stdout.splitlines()[0] if stdout.splitlines() else ""
        return status, key_line

    # Not warn
    if _contains_any(stdout, pass_tokens):
        status = "pass"
        for line in stdout.splitlines():
            if _contains_any(line, pass_tokens):
                key_line = line
                break
        if key_line == "":
            key_line = stdout.splitlines()[0] if stdout.splitlines() else ""
        return status, key_line

    # If none match (shouldn't happen with given tools), classify as pass with empty key_line
    status = "pass"
    key_line = ""
    return status, key_line


def _run_checks_from_config(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    checks_config_path = workspace / "input" / "checks.json"
    config = _safe_load_json(checks_config_path)
    if not isinstance(config, dict):
        return None
    checks = config.get("checks")
    rules = config.get("classification_rules")
    if not isinstance(checks, list) or not isinstance(rules, dict):
        return None

    results = []
    for chk in checks:
        if not isinstance(chk, dict):
            return None
        cmd = chk.get("command")
        if not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd):
            return None
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True
            )
            stdout = proc.stdout
            stderr = proc.stderr
            exit_code = proc.returncode
        except Exception:
            return None

        status, key_line = _classify_and_key(stdout, stderr, exit_code, rules)
        results.append({
            "id": chk.get("id"),
            "component": chk.get("component"),
            "command": cmd,
            "exit_code": exit_code,
            "status": status,
            "key_line": key_line,
            "stdout": stdout,
            "stderr": stderr
        })
    return results


def _parse_run_log(path: Path) -> Optional[List[Dict[str, Any]]]:
    data = _safe_load_json(path)
    if not isinstance(data, list):
        return None
    parsed = []
    for item in data:
        if not isinstance(item, dict):
            return None
        parsed.append(item)
    return parsed


def _validate_run_log_schema(records: List[Dict[str, Any]]) -> bool:
    required_fields = {
        "id": str,
        "component": str,
        "command": list,
        "exit_code": int,
        "status": str,
        "key_line": str,
        "stdout": str,
        "stderr": str
    }
    allowed_statuses = {"pass", "warn", "fail"}

    for rec in records:
        for k, typ in required_fields.items():
            if k not in rec:
                return False
            if typ is list:
                if not isinstance(rec[k], list) or not all(isinstance(x, str) for x in rec[k]):
                    return False
            elif not isinstance(rec[k], typ):
                return False
        if rec["status"] not in allowed_statuses:
            return False
    return True


def _contains_banned_terms(text: str) -> bool:
    banned = ["rto", "rpo", "dns", "nxdomain", "drift", "pipeline"]
    t = text.lower()
    return any(b in t for b in banned)


def _has_action_or_reassurance(text: str) -> bool:
    t = text.lower()
    reassurance_phrases = [
        "no action", "no outage", "no impact", "service remains", "operations continue",
        "we are monitoring", "we are investigating", "we will update", "no customer impact"
    ]
    action_phrases = [
        "please", "contact", "call", "email", "pause", "stop", "hold", "follow", "review",
        "check", "respond", "acknowledge", "update your", "save", "backup", "test",
        "prepare", "plan", "join", "attend", "open incident", "create ticket", "open a ticket",
        "open a case", "report to"
    ]
    return any(p in t for p in reassurance_phrases) or any(p in t for p in action_phrases)


def _extract_exec_overview_paragraph(md: str) -> Optional[str]:
    lines = md.splitlines()
    # Find section labelled "Executive overview"
    idx = None
    for i, line in enumerate(lines):
        if re.search(r"\bexecutive overview\b", line, re.IGNORECASE):
            idx = i
            break
    if idx is not None:
        # Collect subsequent non-empty lines until blank line or next heading
        collected = []
        for j in range(idx + 1, len(lines)):
            l = lines[j]
            if l.strip() == "":
                break
            if re.match(r"^\s*#{1,6}\s", l):
                break
            collected.append(l.strip())
        para = " ".join(collected).strip()
        if para:
            return para

    # Fallback: first non-empty paragraph
    collected = []
    started = False
    for l in lines:
        if not started and l.strip() == "":
            continue
        if not started and l.strip() != "":
            started = True
        if started:
            if l.strip() == "":
                break
            collected.append(l.strip())
    para = " ".join(collected).strip()
    return para if para else None


def _extract_results_bullets(md: str) -> List[str]:
    bullets = []
    for line in md.splitlines():
        if re.match(r"^\s*[-*]\s", line) and "—" in line:
            bullets.append(line.strip())
    return bullets


def _parse_bullet(line: str) -> Optional[Dict[str, str]]:
    # Expected format: "<id> — <component> — <status> — <key_line>"
    m = re.match(r"^[-*]\s*(?P<id>[^—]+)\s+—\s+(?P<component>[^—]+)\s+—\s+(?P<status>[^—]+)\s+—\s+(?P<key_line>.+)$", line.strip())
    if not m:
        return None
    d = {k: v.strip() for k, v in m.groupdict().items()}
    return d


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "run_log_exists_and_schema_valid": 0.0,
        "run_log_order_and_commands_match": 0.0,
        "run_log_execution_match": 0.0,
        "run_log_status_and_key_line_correct": 0.0,
        "alerts_rewritten_structure_and_alignment": 0.0,
        "alerts_rewritten_no_banned_terms_and_word_limit": 0.0,
        "alerts_rewritten_word_count_field_correct": 0.0,
        "alerts_rewritten_action_or_reassurance_present": 0.0,
        "summary_exec_overview_counts_within_limit": 0.0,
        "summary_results_bullets_match_run_log": 0.0,
        "summary_recommended_actions_match_statuses": 0.0,
    }

    # Paths
    run_log_path = workspace / "output" / "run_log.json"
    alerts_out_path = workspace / "output" / "messaging" / "alerts_rewritten.csv"
    summary_path = workspace / "output" / "reports" / "dr_validation_summary.md"
    checks_config_path = workspace / "input" / "checks.json"
    alerts_in_path = workspace / "input" / "alerts_raw.csv"

    # Load run_log
    run_log_records = None
    if run_log_path.exists():
        run_log_records = _parse_run_log(run_log_path)
    # Validate schema
    if isinstance(run_log_records, list) and _validate_run_log_schema(run_log_records):
        scores["run_log_exists_and_schema_valid"] = 1.0
    else:
        scores["run_log_exists_and_schema_valid"] = 0.0

    # Load checks.json
    checks_config = _safe_load_json(checks_config_path)
    checks_list = []
    classification_rules = None
    if isinstance(checks_config, dict):
        checks_list = checks_config.get("checks") if isinstance(checks_config.get("checks"), list) else []
        classification_rules = checks_config.get("classification_rules") if isinstance(checks_config.get("classification_rules"), dict) else None

    # Check order and commands match
    if run_log_records is not None and isinstance(checks_list, list) and checks_list:
        total = len(checks_list)
        matches = 0
        if len(run_log_records) == total:
            for idx, chk in enumerate(checks_list):
                rl = run_log_records[idx]
                id_match = rl.get("id") == chk.get("id")
                comp_match = rl.get("component") == chk.get("component")
                cmd_match = rl.get("command") == chk.get("command")
                if id_match and comp_match and cmd_match:
                    matches += 1
        # Score as fraction across checks
        scores["run_log_order_and_commands_match"] = (matches / total) if total > 0 else 0.0
    else:
        scores["run_log_order_and_commands_match"] = 0.0

    # Execute commands to compute expected outcomes
    expected_exec = _run_checks_from_config(workspace) if checks_list else None

    # Compare execution outputs (exit_code, stdout, stderr)
    if run_log_records and expected_exec and len(run_log_records) == len(expected_exec):
        per = []
        for rl, exp in zip(run_log_records, expected_exec):
            ok = (rl.get("exit_code") == exp.get("exit_code") and
                  rl.get("stdout") == exp.get("stdout") and
                  rl.get("stderr") == exp.get("stderr"))
            per.append(1.0 if ok else 0.0)
        scores["run_log_execution_match"] = sum(per) / len(per) if per else 0.0
    else:
        scores["run_log_execution_match"] = 0.0

    # Compare classification and key_line
    if run_log_records and expected_exec and len(run_log_records) == len(expected_exec):
        per = []
        for rl, exp in zip(run_log_records, expected_exec):
            ok = (rl.get("status") == exp.get("status") and rl.get("key_line") == exp.get("key_line"))
            per.append(1.0 if ok else 0.0)
        scores["run_log_status_and_key_line_correct"] = sum(per) / len(per) if per else 0.0
    else:
        scores["run_log_status_and_key_line_correct"] = 0.0

    # Alerts rewriting checks
    alerts_in_rows = _safe_read_csv(alerts_in_path)
    alerts_out_rows = _safe_read_csv(alerts_out_path) if alerts_out_path.exists() else None

    # Structure and alignment
    if isinstance(alerts_in_rows, list) and isinstance(alerts_out_rows, list):
        # Required columns in exact order
        required_cols = ["id", "audience", "channel", "draft_message", "rewritten_message", "rewritten_word_count"]
        out_cols_ok = False
        try:
            with alerts_out_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
                out_cols_ok = header == required_cols
        except Exception:
            out_cols_ok = False

        alignment_ok = False
        if out_cols_ok and len(alerts_in_rows) == len(alerts_out_rows):
            # Map by id
            in_map = {row["id"]: row for row in alerts_in_rows}
            out_map = {row["id"]: row for row in alerts_out_rows}
            if set(in_map.keys()) == set(out_map.keys()):
                # For each id, audience, channel, draft_message must match
                alignment_ok = True
                for rid, inrow in in_map.items():
                    orow = out_map.get(rid, {})
                    if not (orow.get("audience") == inrow.get("audience") and
                            orow.get("channel") == inrow.get("channel") and
                            orow.get("draft_message") == inrow.get("draft_message") and
                            "rewritten_message" in orow and "rewritten_word_count" in orow):
                        alignment_ok = False
                        break
        scores["alerts_rewritten_structure_and_alignment"] = 1.0 if (out_cols_ok and alignment_ok) else 0.0
    else:
        scores["alerts_rewritten_structure_and_alignment"] = 0.0

    # Banned terms and word limit, and word count correctness, and action/reassurance
    banned_and_limit_scores = []
    wordcount_scores = []
    action_reassurance_scores = []
    if isinstance(alerts_out_rows, list):
        for row in alerts_out_rows:
            rewritten = row.get("rewritten_message", "") or ""
            # banned terms
            banned_ok = not _contains_banned_terms(rewritten)
            # word limit
            wc = _word_count(rewritten)
            limit_ok = wc <= 80 and wc >= 0
            banned_and_limit_scores.append(1.0 if (banned_ok and limit_ok) else 0.0)
            # word count field correct
            try:
                reported_wc = int(str(row.get("rewritten_word_count", "")).strip())
                wordcount_scores.append(1.0 if reported_wc == wc else 0.0)
            except Exception:
                wordcount_scores.append(0.0)
            # action or reassurance present
            ar_ok = _has_action_or_reassurance(rewritten)
            action_reassurance_scores.append(1.0 if ar_ok else 0.0)
        if banned_and_limit_scores:
            scores["alerts_rewritten_no_banned_terms_and_word_limit"] = sum(banned_and_limit_scores) / len(banned_and_limit_scores)
            scores["alerts_rewritten_word_count_field_correct"] = sum(wordcount_scores) / len(wordcount_scores)
            scores["alerts_rewritten_action_or_reassurance_present"] = sum(action_reassurance_scores) / len(action_reassurance_scores)
    # Summary checks
    summary_text = _safe_read_text(summary_path) if summary_path.exists() else None

    # Exec overview counts and word limit
    if summary_text and run_log_records:
        exec_para = _extract_exec_overview_paragraph(summary_text)
        if exec_para is not None:
            wc = _word_count(exec_para)
            within_limit = wc <= 120
            # compute counts from run_log
            counts = {"pass": 0, "warn": 0, "fail": 0}
            for rec in run_log_records:
                st = rec.get("status")
                if st in counts:
                    counts[st] += 1
            # require presence of each label and its count as a digit
            has_all = True
            for label in ["pass", "warn", "fail"]:
                # label
                if not re.search(rf"\b{label}\b", exec_para, flags=re.IGNORECASE):
                    has_all = False
                    break
                # number
                num = counts[label]
                if not re.search(rf"\b{num}\b", exec_para):
                    has_all = False
                    break
            scores["summary_exec_overview_counts_within_limit"] = 1.0 if (within_limit and has_all) else 0.0
        else:
            scores["summary_exec_overview_counts_within_limit"] = 0.0
    else:
        scores["summary_exec_overview_counts_within_limit"] = 0.0

    # Results bullets match run_log
    if summary_text and run_log_records:
        bullets = _extract_results_bullets(summary_text)
        # Parse bullets
        parsed_bullets = []
        for b in bullets:
            pb = _parse_bullet(b)
            if pb:
                parsed_bullets.append(pb)
        # Map by id
        pb_map = {b["id"]: b for b in parsed_bullets if "id" in b}
        total = len(run_log_records)
        matched = 0
        for rec in run_log_records:
            rid = rec.get("id")
            b = pb_map.get(rid)
            if not b:
                continue
            if (b.get("component") == rec.get("component") and
                b.get("status") == rec.get("status") and
                b.get("key_line") == rec.get("key_line")):
                matched += 1
        scores["summary_results_bullets_match_run_log"] = (matched / total) if total > 0 else 0.0
    else:
        scores["summary_results_bullets_match_run_log"] = 0.0

    # Recommended actions
    if summary_text and run_log_records:
        lines = [l.strip() for l in summary_text.splitlines() if l.strip()]
        needed_actions = []
        for rec in run_log_records:
            comp = rec.get("component")
            st = rec.get("status")
            if st == "fail":
                needed_actions.append(f"Open incident for {comp} and begin remediation")
            elif st == "warn":
                needed_actions.append(f"Create ticket to review {comp} within the week")
        found = 0
        for act in needed_actions:
            # Look for exact line match or contained in any line
            if any(act == l or act in l for l in lines):
                found += 1
        scores["summary_recommended_actions_match_statuses"] = (found / len(needed_actions)) if needed_actions else 0.0
    else:
        scores["summary_recommended_actions_match_statuses"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()