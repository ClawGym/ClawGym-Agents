import json
import sys
import re
from pathlib import Path
from datetime import date
from urllib.parse import urlparse


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _safe_read_lines(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def _strip_inline_comment(line: str) -> str:
    result = []
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            result.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            result.append(ch)
        elif ch == '#' and not in_single and not in_double:
            break
        else:
            result.append(ch)
        i += 1
    return "".join(result).rstrip()


def _parse_schedule_yaml(content: str) -> dict:
    out = {
        "schedule.cron": None,
        "runtime.lockfile": None,
        "paths.log_path": None,
        "paths.raw_dir": None,
        "paths.structured_dir": None,
        "retention.log_days": None,
        "retention.raw_days": None,
    }
    lines = [_strip_inline_comment(l).rstrip() for l in content.splitlines()]
    joined = "\n".join(lines)
    cron_match = re.search(r'^\s*cron:\s*"(.*?)"\s*$', joined, re.M)
    if cron_match:
        out["schedule.cron"] = cron_match.group(1).strip()
    lock_match = re.search(r'^\s*lockfile:\s*"(.*?)"\s*$', joined, re.M)
    if lock_match:
        out["runtime.lockfile"] = lock_match.group(1).strip()
    log_match = re.search(r'^\s*log_path:\s*"(.*?)"\s*$', joined, re.M)
    if log_match:
        out["paths.log_path"] = log_match.group(1).strip()
    raw_match = re.search(r'^\s*raw_dir:\s*"(.*?)"\s*$', joined, re.M)
    if raw_match:
        out["paths.raw_dir"] = raw_match.group(1).strip()
    structured_match = re.search(r'^\s*structured_dir:\s*"(.*?)"\s*$', joined, re.M)
    if structured_match:
        out["paths.structured_dir"] = structured_match.group(1).strip()
    log_days = re.search(r'^\s*log_retention_days:\s*(\d+)\s*$', joined, re.M)
    if log_days:
        out["retention.log_days"] = int(log_days.group(1))
    raw_days = re.search(r'^\s*raw_html_retention_days:\s*(\d+)\s*$', joined, re.M)
    if raw_days:
        out["retention.raw_days"] = int(raw_days.group(1))
    return out


def _parse_extract_required_keys(content: str):
    lines = [_strip_inline_comment(l) for l in content.splitlines()]
    required_keys = []
    in_output_schema = False
    in_required = False
    base_indent_schema = None
    base_indent_required = None
    for line in lines:
        if not line.strip():
            continue
        if not in_output_schema and re.match(r'^\s*output_schema:\s*$', line):
            in_output_schema = True
            base_indent_schema = len(line) - len(line.lstrip(" "))
            continue
        if in_output_schema:
            indent = len(line) - len(line.lstrip(" "))
            if indent <= base_indent_schema and not re.match(r'^\s*output_schema:\s*$', line):
                in_output_schema = False
                in_required = False
                continue
            if not in_required and re.match(r'^\s*required_keys:\s*$', line):
                in_required = True
                base_indent_required = indent
                continue
            if in_required:
                indent_req = len(line) - len(line.lstrip(" "))
                if indent_req <= base_indent_required and not re.match(r'^\s*-\s', line):
                    in_required = False
                    continue
                m = re.match(r'^\s*-\s*"(.*?)"\s*$', line)
                if m:
                    required_keys.append(m.group(1))
                    continue
                m2 = re.match(r"^\s*-\s*'(.*?)'\s*$", line)
                if m2:
                    required_keys.append(m2.group(1))
                    continue
                m3 = re.match(r'^\s*-\s*(\S.*?)\s*$', line)
                if m3:
                    required_keys.append(m3.group(1))
                    continue
    return required_keys


def _parse_targets(content: str):
    lines = [_strip_inline_comment(l) for l in content.splitlines()]
    targets = []
    current = None
    in_targets_list = False
    in_allowed_domains = False
    for line in lines:
        if not line.strip():
            continue
        if not in_targets_list and re.match(r'^\s*targets:\s*$', line):
            in_targets_list = True
            continue
        if in_targets_list:
            m_name_dq = re.match(r'^\s*-\s*name:\s*"(.*?)"\s*$', line)
            m_name_sq = re.match(r"^\s*-\s*name:\s*'(.*?)'\s*$", line)
            if m_name_dq or m_name_sq:
                if current:
                    targets.append(current)
                name_val = (m_name_dq or m_name_sq).group(1)
                current = {"name": name_val, "domain": None, "allowed_domains": []}
                in_allowed_domains = False
                continue
            if current is not None:
                mdom = re.match(r'^\s*domain:\s*"(.*?)"\s*$', line) or re.match(r"^\s*domain:\s*'(.*?)'\s*$", line) or re.match(r'^\s*domain:\s*(\S+)\s*$', line)
                if mdom:
                    current["domain"] = mdom.group(1).strip()
                    continue
                if re.match(r'^\s*allowed_domains:\s*$', line):
                    in_allowed_domains = True
                    continue
                if in_allowed_domains:
                    mad = re.match(r'^\s*-\s*"(.*?)"\s*$', line) or re.match(r"^\s*-\s*'(.*?)'\s*$", line) or re.match(r'^\s*-\s*(\S+)\s*$', line)
                    if mad:
                        current["allowed_domains"].append(mad.group(1).strip())
                        continue
    if current:
        targets.append(current)
    final = []
    for t in targets:
        if t.get("domain"):
            if "allowed_domains" not in t or t["allowed_domains"] is None:
                t["allowed_domains"] = []
            final.append(t)
    return final


def _load_jsonl(path: Path):
    try:
        if not path.exists():
            return None
        lines = _safe_read_lines(path)
        recs = []
        for line in lines:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                recs.append(obj)
            except Exception:
                return None
        return recs
    except Exception:
        return None


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def _is_bool(val) -> bool:
    return isinstance(val, bool)


def _is_int(val) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "runner_script_present": 0.0,
        "wrapper_script_valid": 0.0,
        "cron_file_valid": 0.0,
        "structured_jsonl_today_exists": 0.0,
        "structured_jsonl_parseable": 0.0,
        "structured_records_required_keys_present": 0.0,
        "structured_records_types_and_constraints_valid": 0.0,
        "raw_html_files_present_for_records": 0.0,
        "logs_present_and_nonempty": 0.0,
        "runner_references_config_files": 0.0,
    }

    schedule_cfg_path = workspace / "config" / "schedule.yaml"
    extract_cfg_path = workspace / "config" / "extract.yaml"
    targets_cfg_path = workspace / "config" / "targets.yaml"

    schedule_cfg_text = _read_text(schedule_cfg_path)
    extract_cfg_text = _read_text(extract_cfg_path)
    targets_cfg_text = _read_text(targets_cfg_path)

    sched = _parse_schedule_yaml(schedule_cfg_text) if schedule_cfg_text else {}
    required_keys = _parse_extract_required_keys(extract_cfg_text) if extract_cfg_text else []
    targets = _parse_targets(targets_cfg_text) if targets_cfg_text else []
    target_domains = [t.get("domain") for t in targets if t.get("domain")]
    allowed_domains_map = {t["domain"]: set(t.get("allowed_domains", [])) for t in targets if t.get("domain")}

    log_path_cfg = sched.get("paths.log_path") or "logs/holistic_monitor.log"
    raw_dir_cfg = sched.get("paths.raw_dir") or "outputs/raw_html"
    structured_dir_cfg = sched.get("paths.structured_dir") or "outputs/structured"
    lockfile_cfg = sched.get("runtime.lockfile") or "tmp/holistic_monitor.lock"
    cron_expr = sched.get("schedule.cron")

    log_path = workspace / log_path_cfg
    raw_dir = workspace / raw_dir_cfg
    structured_dir = workspace / structured_dir_cfg

    runner_path = workspace / "src" / "holistic_monitor.py"
    if runner_path.exists() and runner_path.is_file():
        scores["runner_script_present"] = 1.0
    else:
        scores["runner_script_present"] = 0.0

    runner_refs_score = 0.0
    runner_content = _read_text(runner_path) if runner_path.exists() else ""
    present_flags = [
        ("targets.yaml", "targets_yaml"),
        ("extract.yaml", "extract_yaml"),
        ("schedule.yaml", "schedule_yaml"),
    ]
    hits = 0
    for needle, _ in present_flags:
        if needle in runner_content:
            hits += 1
    if "config/" in runner_content:
        hits += 0.5
    if hits >= 3:
        runner_refs_score = 1.0
    elif hits >= 2:
        runner_refs_score = 0.67
    elif hits >= 1:
        runner_refs_score = 0.34
    else:
        runner_refs_score = 0.0
    scores["runner_references_config_files"] = runner_refs_score

    wrapper_path = workspace / "schedule" / "run_holistic_monitor.sh"
    wrapper_content = _read_text(wrapper_path)
    if wrapper_content:
        has_lockfile_ref = lockfile_cfg in wrapper_content if lockfile_cfg else ("lock" in wrapper_content)
        has_log_ref = log_path_cfg in wrapper_content if log_path_cfg else ("logs/" in wrapper_content)
        invokes_python = ("python " in wrapper_content or "python3 " in wrapper_content)
        invokes_runner = ("holistic_monitor.py" in wrapper_content) or ("src/" in wrapper_content)
        creates_dirs = ("mkdir" in wrapper_content or "install -d" in wrapper_content)
        has_lock_mech = ("flock" in wrapper_content) or ("noclobber" in wrapper_content) or ("lock" in wrapper_content)
        parts = [
            has_lockfile_ref,
            has_lock_mech,
            has_log_ref,
            invokes_python and invokes_runner,
            creates_dirs,
        ]
        scores["wrapper_script_valid"] = sum(1.0 for p in parts if p) / len(parts)
    else:
        scores["wrapper_script_valid"] = 0.0

    cron_path = workspace / "schedule" / "holistic_monitor.cron"
    cron_lines = []
    if cron_path.exists():
        cron_lines = [ln.strip() for ln in _safe_read_lines(cron_path) if ln.strip() and not ln.strip().startswith("#")]
    if len(cron_lines) == 1 and cron_expr:
        cron_line = cron_lines[0]
        cron_ok = cron_line.startswith(cron_expr) and "schedule/run_holistic_monitor.sh" in cron_line
        scores["cron_file_valid"] = 1.0 if cron_ok else 0.0
    else:
        scores["cron_file_valid"] = 0.0

    today = _today_str()
    structured_file = structured_dir / f"{today}.jsonl"
    if structured_file.exists() and structured_file.is_file():
        scores["structured_jsonl_today_exists"] = 1.0
    else:
        scores["structured_jsonl_today_exists"] = 0.0

    records = _load_jsonl(structured_file) if structured_file.exists() else None
    if records is None and structured_file.exists():
        scores["structured_jsonl_parseable"] = 0.0
    elif records is None and not structured_file.exists():
        scores["structured_jsonl_parseable"] = 0.0
    else:
        scores["structured_jsonl_parseable"] = 1.0

    if records is None or not required_keys:
        scores["structured_records_required_keys_present"] = 0.0 if structured_file.exists() else 0.0
    else:
        if len(records) == 0:
            scores["structured_records_required_keys_present"] = 1.0
        else:
            ok_count = 0
            for rec in records:
                if isinstance(rec, dict) and all(k in rec for k in required_keys):
                    ok_count += 1
            scores["structured_records_required_keys_present"] = ok_count / len(records) if records else 0.0

    if records is None:
        scores["structured_records_types_and_constraints_valid"] = 0.0 if structured_file.exists() else 0.0
    else:
        if len(records) == 0:
            scores["structured_records_types_and_constraints_valid"] = 1.0
        else:
            valid = 0
            for rec in records:
                ok = True
                page_type = rec.get("page_type")
                if page_type not in ("home", "about"):
                    ok = False
                if "about_link_found" in rec and not _is_bool(rec.get("about_link_found")):
                    ok = False
                if "http_status" not in rec or not _is_int(rec.get("http_status")):
                    ok = False
                if "phones_count" not in rec or not _is_int(rec.get("phones_count")) or rec.get("phones_count") < 0:
                    ok = False
                if "has_disclaimer_language" in rec and not _is_bool(rec.get("has_disclaimer_language")):
                    ok = False
                if "page_title" in rec and rec.get("page_title") is not None and not isinstance(rec.get("page_title"), str):
                    ok = False
                if "last_modified" in rec and not (rec.get("last_modified") is None or isinstance(rec.get("last_modified"), str)):
                    ok = False
                domain_val = rec.get("domain")
                if isinstance(domain_val, str):
                    if target_domains and domain_val not in target_domains:
                        ok = False
                else:
                    ok = False
                url_val = rec.get("url")
                if isinstance(url_val, str):
                    parsed = urlparse(url_val)
                    netloc = parsed.netloc
                    scheme = parsed.scheme
                    if page_type == "home":
                        if scheme != "https":
                            ok = False
                        if not domain_val or netloc.lower() != domain_val.lower():
                            ok = False
                    elif page_type == "about":
                        allowed = allowed_domains_map.get(domain_val, set())
                        if allowed and netloc not in allowed:
                            ok = False
                else:
                    ok = False
                valid += 1 if ok else 0
            scores["structured_records_types_and_constraints_valid"] = valid / len(records) if records else 0.0

    if records is None:
        scores["raw_html_files_present_for_records"] = 0.0 if structured_file.exists() else 0.0
    else:
        if len(records) == 0:
            scores["raw_html_files_present_for_records"] = 1.0
        else:
            present = 0
            total = 0
            for rec in records:
                dom = rec.get("domain")
                pt = rec.get("page_type")
                if isinstance(dom, str) and pt in ("home", "about"):
                    expected_name = f"{today}_{pt}.html"
                    expected_path = (workspace / raw_dir_cfg) / dom / expected_name
                    total += 1
                    if expected_path.exists() and expected_path.is_file():
                        present += 1
            if total == 0:
                scores["raw_html_files_present_for_records"] = 1.0
            else:
                scores["raw_html_files_present_for_records"] = present / total

    if log_path.exists() and log_path.is_file():
        try:
            size = log_path.stat().st_size
        except Exception:
            size = 0
        scores["logs_present_and_nonempty"] = 1.0 if size > 0 else 0.0
    else:
        scores["logs_present_and_nonempty"] = 0.0

    return scores


def main() -> None:
    workspace_arg = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_arg)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()