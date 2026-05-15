import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def parse_simple_yaml_checks(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser tailored for the provided checks.yaml structure.
    Supports:
      - scalar ints
      - quoted/unquoted strings on the same line
      - list under 'required_tools' with dash-prefixed items
    """
    text = read_text_safe(path)
    if text is None:
        return None
    cfg: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Handle list items for current list key
        if current_list_key is not None:
            if line.startswith("-"):
                item = line[1:].strip()
                # remove surrounding quotes if present
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                cfg[current_list_key].append(item)
                continue
            else:
                current_list_key = None  # fall through to process this line as a new key

        # Key: value or Key:
        m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
        if not m:
            # Unsupported line; skip
            continue
        key = m.group(1)
        val = m.group(2)

        if val == "":
            # Possibly start of a list
            if key == "required_tools":
                cfg[key] = []
                current_list_key = key
            else:
                cfg[key] = None
            continue

        # Scalar value
        # Strip quotes if present
        sval = val
        if (sval.startswith('"') and sval.endswith('"')) or (sval.startswith("'") and sval.endswith("'")):
            sval = sval[1:-1]
        # Try int
        if key.endswith("_min") or key.endswith("_percent_min"):
            try:
                cfg[key] = int(sval)
                continue
            except Exception:
                pass
        # For python_min_version keep as string
        cfg[key] = sval
    # Basic validation
    if "python_min_version" in cfg and isinstance(cfg.get("python_min_version"), str):
        pass
    if "disk_free_percent_min" in cfg and not isinstance(cfg.get("disk_free_percent_min"), int):
        # Try to coerce
        try:
            cfg["disk_free_percent_min"] = int(cfg["disk_free_percent_min"])
        except Exception:
            return None
    if "mem_free_percent_min" in cfg and not isinstance(cfg.get("mem_free_percent_min"), int):
        try:
            cfg["mem_free_percent_min"] = int(cfg["mem_free_percent_min"])
        except Exception:
            return None
    if "required_tools" in cfg and not isinstance(cfg.get("required_tools"), list):
        return None
    return cfg


def is_number(x: Any) -> bool:
    return isinstance(x, (int, float))


def parse_version_from_string(s: Optional[str]) -> Optional[Tuple[int, ...]]:
    if not s:
        return None
    # Find first version-like pattern, e.g., 3.8.10
    m = re.search(r"\d+(?:\.\d+)+", s)
    if not m:
        # Try single number
        m2 = re.search(r"\d+", s)
        if not m2:
            return None
        try:
            return (int(m2.group(0)),)
        except Exception:
            return None
    version_str = m.group(0)
    parts = version_str.split(".")
    ints: List[int] = []
    for p in parts:
        try:
            ints.append(int(p))
        except Exception:
            ints.append(0)
    return tuple(ints)


def compare_versions(a: Tuple[int, ...], b: Tuple[int, ...]) -> int:
    """
    Returns -1 if a<b, 0 if equal, 1 if a>b
    """
    # Normalize lengths
    maxlen = max(len(a), len(b))
    aa = a + (0,) * (maxlen - len(a))
    bb = b + (0,) * (maxlen - len(b))
    if aa < bb:
        return -1
    if aa > bb:
        return 1
    return 0


def extract_markdown_section(text: str, header: str) -> Optional[str]:
    """
    Extracts the content of a markdown section with '## {header}' until the next '## ' header or end of text.
    Case-sensitive match on header line starting with '## ' exactly.
    """
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == f"## {header}":
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    # Find next header
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if lines[j].strip().startswith("## ") and j > start_idx:
            end_idx = j
            break
    section = "\n".join(lines[start_idx:end_idx]).strip()
    return section


def find_bullet_lines(text: str) -> List[str]:
    bullets = []
    for line in text.splitlines():
        if re.match(r"^\s*[-*]\s+", line):
            bullets.append(line.strip())
    return bullets


def contains_pass_fail(line: str) -> Optional[bool]:
    if re.search(r"\bPASS\b", line, flags=re.IGNORECASE):
        return True
    if re.search(r"\bFAIL\b", line, flags=re.IGNORECASE):
        return False
    return None


def line_mentions_check(line: str, check: str) -> bool:
    check_patterns = {
        "disk": r"\bdisk\b",
        "mem": r"\bmem(ory)?\b",
        "python": r"\bpython\b",
        "tools": r"\btools?\b",
        "overall": r"\boverall\b",
    }
    pat = check_patterns.get(check, r"")
    return re.search(pat, line, flags=re.IGNORECASE) is not None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Initialize scores
    scores: Dict[str, float] = {
        "report_file_exists_and_parse": 0.0,
        "report_required_fields_present": 0.0,
        "report_errors_field_present_list": 0.0,
        "report_tools_mapping_valid": 0.0,
        "disk_ok_correct": 0.0,
        "mem_ok_correct": 0.0,
        "python_ok_correct": 0.0,
        "tools_ok_correct": 0.0,
        "overall_ok_correct": 0.0,
        "raw_log_present_nonempty": 0.0,
        "notes_file_exists_and_sections": 0.0,
        "notes_summary_covers_all_checks": 0.0,
        "notes_summary_includes_thresholds": 0.0,
        "notes_action_items_correctness": 0.0,
        "email_file_exists_and_length": 0.0,
        "email_includes_meeting_time_invite_and_status": 0.0,
        "validation_file_exists_and_matches_checks": 0.0,
    }

    # Paths
    config_path = workspace / "input" / "config" / "checks.yaml"
    report_path = workspace / "outputs" / "report" / "system_status.json"
    raw_log_path = workspace / "outputs" / "raw" / "commands_and_outputs.log"
    notes_path = workspace / "outputs" / "notes" / "tech_meeting_notes.md"
    email_path = workspace / "outputs" / "messages" / "volunteer_email_rewrite.txt"
    validation_path = workspace / "outputs" / "tests" / "validation.txt"

    cfg = parse_simple_yaml_checks(config_path)
    cfg_loaded = isinstance(cfg, dict) and len(cfg) > 0

    report = read_json_safe(report_path)
    if isinstance(report, dict):
        scores["report_file_exists_and_parse"] = 1.0

        # Required fields presence
        required_keys = {
            "timestamp",
            "workspace_path",
            "disk_used_percent",
            "disk_free_percent",
            "mem_total_mib",
            "mem_available_mib",
            "mem_free_percent",
            "cpu_cores",
            "python_version",
            "required_tools_present",
            "disk_ok",
            "mem_ok",
            "python_ok",
            "tools_ok",
            "overall_ok",
            "errors",
        }
        has_all = all(k in report for k in required_keys)
        # type checks for some fields (allow None for measured values)
        types_ok = True
        if has_all:
            if not isinstance(report.get("required_tools_present"), dict):
                types_ok = False
            if not isinstance(report.get("errors"), list):
                types_ok = False
            # booleans
            for bkey in ["disk_ok", "mem_ok", "python_ok", "tools_ok", "overall_ok"]:
                if not isinstance(report.get(bkey), bool):
                    types_ok = False
        if has_all and types_ok:
            scores["report_required_fields_present"] = 1.0
            scores["report_errors_field_present_list"] = 1.0
        else:
            # If errors key exists and is list, partial credit for errors field
            if isinstance(report.get("errors"), list):
                scores["report_errors_field_present_list"] = 1.0

        # Tools mapping validity
        tools_mapping_ok = False
        rtp = report.get("required_tools_present")
        if isinstance(rtp, dict):
            if cfg_loaded and isinstance(cfg.get("required_tools"), list):
                needed = set(cfg["required_tools"])
                tools_mapping_ok = needed.issubset(set(rtp.keys())) and all(
                    isinstance(rtp.get(t), bool) for t in needed
                )
            else:
                # If no config, ensure it is a non-empty dict of bools
                tools_mapping_ok = len(rtp) > 0 and all(isinstance(v, bool) for v in rtp.values())
        if tools_mapping_ok:
            scores["report_tools_mapping_valid"] = 1.0

        # Compute correctness of booleans per config and measured values
        # disk_ok
        if cfg_loaded and is_number(report.get("disk_free_percent")) and isinstance(report.get("disk_ok"), bool):
            exp_disk_ok = float(report["disk_free_percent"]) >= float(cfg["disk_free_percent_min"])
            if report["disk_ok"] == exp_disk_ok:
                scores["disk_ok_correct"] = 1.0

        # mem_ok
        if cfg_loaded and is_number(report.get("mem_free_percent")) and isinstance(report.get("mem_ok"), bool):
            exp_mem_ok = float(report["mem_free_percent"]) >= float(cfg["mem_free_percent_min"])
            if report["mem_ok"] == exp_mem_ok:
                scores["mem_ok_correct"] = 1.0

        # python_ok
        if cfg_loaded and isinstance(report.get("python_ok"), bool):
            rv = parse_version_from_string(report.get("python_version"))
            mv = parse_version_from_string(cfg.get("python_min_version"))
            if rv is not None and mv is not None:
                exp_python_ok = compare_versions(rv, mv) >= 0
                if report["python_ok"] == exp_python_ok:
                    scores["python_ok_correct"] = 1.0

        # tools_ok
        if isinstance(report.get("tools_ok"), bool) and tools_mapping_ok and cfg_loaded:
            needed_tools = cfg.get("required_tools", [])
            exp_tools_ok = all(bool(report["required_tools_present"].get(t)) for t in needed_tools)
            if report["tools_ok"] == exp_tools_ok:
                scores["tools_ok_correct"] = 1.0

        # overall_ok correctness
        # Only evaluate if the four booleans present and booleans
        if all(isinstance(report.get(k), bool) for k in ["disk_ok", "mem_ok", "python_ok", "tools_ok", "overall_ok"]):
            exp_overall_ok = report["disk_ok"] and report["mem_ok"] and report["python_ok"] and report["tools_ok"]
            if report["overall_ok"] == exp_overall_ok:
                scores["overall_ok_correct"] = 1.0

    # Raw log file
    raw_text = read_text_safe(raw_log_path)
    if isinstance(raw_text, str) and len(raw_text.strip()) > 0:
        scores["raw_log_present_nonempty"] = 1.0

    # Notes checks
    notes_text = read_text_safe(notes_path)
    if isinstance(notes_text, str) and "## System Status Summary" in notes_text and "## Action Items" in notes_text and "## Notes" in notes_text:
        scores["notes_file_exists_and_sections"] = 1.0

        # Summary coverage
        summary = extract_markdown_section(notes_text, "System Status Summary")
        if summary and isinstance(report, dict):
            bullets = find_bullet_lines(summary)
            have_all = True
            # Map check to expected pass/fail from report booleans
            checks = [
                ("disk", report.get("disk_ok")),
                ("mem", report.get("mem_ok")),
                ("python", report.get("python_ok")),
                ("tools", report.get("tools_ok")),
                ("overall", report.get("overall_ok")),
            ]
            for chk, val in checks:
                if not isinstance(val, bool):
                    have_all = False
                    break
                # Find a bullet that mentions the check and matches PASS/FAIL
                found = False
                for bl in bullets:
                    if line_mentions_check(bl, chk):
                        pf = contains_pass_fail(bl)
                        if pf is not None and pf == val:
                            found = True
                            break
                if not found:
                    have_all = False
                    break
            if have_all:
                scores["notes_summary_covers_all_checks"] = 1.0

            # Summary includes thresholds (disk, mem, python)
            thresh_ok = False
            if cfg_loaded:
                thresh_ok = True
                # Disk threshold number present
                if str(cfg.get("disk_free_percent_min")) not in summary:
                    thresh_ok = False
                # Mem threshold number present
                if str(cfg.get("mem_free_percent_min")) not in summary:
                    thresh_ok = False
                # Python min version present
                if str(cfg.get("python_min_version")) not in summary:
                    thresh_ok = False
            if thresh_ok:
                scores["notes_summary_includes_thresholds"] = 1.0

        # Action items correctness
        action_sec = extract_markdown_section(notes_text, "Action Items")
        if action_sec and isinstance(report, dict):
            action_bullets = find_bullet_lines(action_sec)
            # Remove empty bullets
            action_bullets = [b for b in action_bullets if b.strip("-* ").strip()]
            if isinstance(report.get("overall_ok"), bool):
                if report["overall_ok"] is True:
                    # Should include a single action item to confirm projector hookup and rehearsal flow.
                    # Require exactly one bullet and phrase presence.
                    if len(action_bullets) == 1 and re.search(r"confirm projector hookup and rehearsal flow", action_bullets[0], flags=re.IGNORECASE):
                        scores["notes_action_items_correctness"] = 1.0
                else:
                    # For each failing check, there should be a related action bullet
                    # Determine failing checks
                    failing_checks = []
                    if isinstance(report.get("disk_ok"), bool) and not report["disk_ok"]:
                        failing_checks.append(("disk", ["disk", "space", "free"]))
                    if isinstance(report.get("mem_ok"), bool) and not report["mem_ok"]:
                        failing_checks.append(("mem", ["memory", "ram", "mem", "free"]))
                    if isinstance(report.get("python_ok"), bool) and not report["python_ok"]:
                        failing_checks.append(("python", ["python", "install", "upgrade", "update"]))
                    if isinstance(report.get("tools_ok"), bool) and not report["tools_ok"]:
                        # include missing tool names if available
                        tool_terms = ["install", "path"]
                        rtp = report.get("required_tools_present")
                        if isinstance(rtp, dict):
                            missing = [t for t, present in rtp.items() if present is False]
                            tool_terms.extend(missing)
                        failing_checks.append(("tools", tool_terms))
                    # Validate at least one bullet per failing check
                    ok = True
                    for chk, terms in failing_checks:
                        found = False
                        for bl in action_bullets:
                            # Check that bullet mentions at least one of the terms
                            if any(re.search(rf"\b{re.escape(term)}\b", bl, flags=re.IGNORECASE) for term in terms):
                                found = True
                                break
                        if not found:
                            ok = False
                            break
                    # At least one action item must exist if there are failing checks
                    if ok and (len(action_bullets) >= max(1, len(failing_checks))):
                        scores["notes_action_items_correctness"] = 1.0

    # Email checks
    email_text = read_text_safe(email_path)
    if isinstance(email_text, str):
        # length <= 180 words (simple split on whitespace)
        words = [w for w in re.findall(r"\S+", email_text)]
        if 0 < len(words) <= 180:
            scores["email_file_exists_and_length"] = 1.0

        # Includes meeting time and invites help and status summary + cables/power
        conds = []
        # meeting time
        conds.append(re.search(r"\b7:00\s*pm\b", email_text, flags=re.IGNORECASE) is not None)
        conds.append(re.search(r"\bSunday\b", email_text, flags=re.IGNORECASE) is not None)
        # invite help
        conds.append(re.search(r"\bhelp\b", email_text, flags=re.IGNORECASE) is not None)
        # cables/power request
        conds.append(re.search(r"\bcables?\b", email_text, flags=re.IGNORECASE) is not None) or re.search(r"\bpower\b", email_text, flags=re.IGNORECASE) is not None
        # status summary high-level
        status_ok = False
        if isinstance(report, dict) and isinstance(report.get("overall_ok"), bool):
            if report["overall_ok"]:
                # look for OK/ready/clear
                status_ok = re.search(r"\bok\b|\ball set\b|\bready\b|\bgood shape\b", email_text, flags=re.IGNORECASE) is not None
            else:
                status_ok = re.search(r"\bissues?\b|\bproblems?\b|\bneeds?\b|\bnot ok\b|\bto address\b", email_text, flags=re.IGNORECASE) is not None
        else:
            # generic: accept presence of ok/issues for high-level
            status_ok = re.search(r"\bok\b|\bissues?\b", email_text, flags=re.IGNORECASE) is not None
        conds.append(status_ok)
        if all(conds):
            scores["email_includes_meeting_time_invite_and_status"] = 1.0

    # Validation file checks
    if isinstance(report, dict) and cfg_loaded:
        # Compute expected pass/fail for four checks from measured values + config
        expected: Dict[str, Optional[bool]] = {"disk": None, "mem": None, "python": None, "tools": None}
        # disk
        if is_number(report.get("disk_free_percent")):
            expected["disk"] = float(report["disk_free_percent"]) >= float(cfg["disk_free_percent_min"])
        # mem
        if is_number(report.get("mem_free_percent")):
            expected["mem"] = float(report["mem_free_percent"]) >= float(cfg["mem_free_percent_min"])
        # python
        rv = parse_version_from_string(report.get("python_version"))
        mv = parse_version_from_string(cfg.get("python_min_version"))
        if rv is not None and mv is not None:
            expected["python"] = compare_versions(rv, mv) >= 0
        # tools
        rtp = report.get("required_tools_present")
        if isinstance(rtp, dict) and isinstance(cfg.get("required_tools"), list):
            expected["tools"] = all(bool(rtp.get(t)) for t in cfg["required_tools"])

        val_text = read_text_safe(validation_path)
        if isinstance(val_text, str):
            lines = val_text.splitlines()
            all_match = True
            for chk, exp in expected.items():
                # Must have an expected value to verify
                if exp is None:
                    all_match = False
                    break
                # Find a line mentioning the check and containing PASS/FAIL
                found_line = None
                for line in lines:
                    if line_mentions_check(line, chk):
                        if re.search(r"\bPASS\b", line, flags=re.IGNORECASE) or re.search(r"\bFAIL\b", line, flags=re.IGNORECASE):
                            found_line = line
                            break
                if not found_line:
                    all_match = False
                    break
                is_pass = re.search(r"\bPASS\b", found_line, flags=re.IGNORECASE) is not None
                is_fail = re.search(r"\bFAIL\b", found_line, flags=re.IGNORECASE) is not None
                if not (is_pass or is_fail):
                    all_match = False
                    break
                if (is_pass and not exp) or (is_fail and exp):
                    all_match = False
                    break
            if all_match:
                scores["validation_file_exists_and_matches_checks"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()