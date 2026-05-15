import json
import re
import sys
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import csv


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_csv(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _run_validator_and_collect(workspace: Path) -> Optional[Dict[str, Any]]:
    validator = workspace / "input" / "tools" / "pattern_validate.py"
    catalog = workspace / "input" / "patterns" / "catalog.json"
    if not validator.exists() or not catalog.exists():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(validator), "--catalog", str(catalog)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except Exception:
        return None
    out = _normalize_newlines(proc.stdout)
    err = _normalize_newlines(proc.stderr)
    combined = out + err

    # Parse lines
    errors: Dict[str, Dict[str, Any]] = {}  # id -> {'name': str, 'codes': List[str], 'entries': List[Tuple[str, str]]}
    warnings: Dict[str, Dict[str, Any]] = {}
    valid_ids: set = set()
    total = None
    valid = None
    invalid = None
    warn_count = None

    re_issue = re.compile(r"^(ERROR|WARN)\s+([A-Z]\d{3})\s+Pattern\s+'(.+)'\s+\((.+)\):\s+(.+)$")
    re_ok = re.compile(r"^OK\s+Pattern\s+'(.+)'\s+\((.+)\)$")
    re_summary = re.compile(r"^SUMMARY\s+total=(\d+)\s+valid=(\d+)\s+invalid=(\d+)\s+warnings=(\d+)$")

    for line in _normalize_newlines(out).split("\n"):
        if not line.strip():
            continue
        m = re_issue.match(line.strip())
        if m:
            level, code, name, pid, message = m.groups()
            if level == "ERROR":
                bucket = errors.setdefault(pid, {"name": name, "codes": [], "entries": []})
                bucket["codes"].append(code)
                bucket["entries"].append((code, message))
            elif level == "WARN":
                bucket = warnings.setdefault(pid, {"name": name, "codes": [], "entries": []})
                bucket["codes"].append(code)
                bucket["entries"].append((code, message))
            continue
        m2 = re_ok.match(line.strip())
        if m2:
            name, pid = m2.groups()
            valid_ids.add(pid)
            continue

    for line in _normalize_newlines(err).split("\n"):
        if not line.strip():
            continue
        m = re_summary.match(line.strip())
        if m:
            total, valid, invalid, warn_count = map(int, m.groups())
            break

    if total is None or valid is None or invalid is None or warn_count is None:
        # Could not parse summary
        return {
            "combined": combined,
            "errors": errors,
            "warnings": warnings,
            "total": None,
            "valid": None,
            "invalid": None,
            "warning_count": None,
        }

    return {
        "combined": combined,
        "errors": errors,
        "warnings": warnings,
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "warning_count": warn_count,
    }


def _parse_raw_output_content(content: str) -> Dict[str, Any]:
    # Similar parser for robustness when needed
    errors: Dict[str, Dict[str, Any]] = {}
    warnings: Dict[str, Dict[str, Any]] = {}
    valid_ids: set = set()
    total = None
    valid = None
    invalid = None
    warn_count = None

    re_issue = re.compile(r"^(ERROR|WARN)\s+([A-Z]\d{3})\s+Pattern\s+'(.+)'\s+\((.+)\):\s+(.+)$")
    re_ok = re.compile(r"^OK\s+Pattern\s+'(.+)'\s+\((.+)\)$")
    re_summary = re.compile(r"^SUMMARY\s+total=(\d+)\s+valid=(\d+)\s+invalid=(\d+)\s+warnings=(\d+)$")

    for line in _normalize_newlines(content).split("\n"):
        s = line.strip()
        if not s:
            continue
        m = re_issue.match(s)
        if m:
            level, code, name, pid, message = m.groups()
            if level == "ERROR":
                bucket = errors.setdefault(pid, {"name": name, "codes": [], "entries": []})
                bucket["codes"].append(code)
                bucket["entries"].append((code, message))
            else:
                bucket = warnings.setdefault(pid, {"name": name, "codes": [], "entries": []})
                bucket["codes"].append(code)
                bucket["entries"].append((code, message))
            continue
        m2 = re_ok.match(s)
        if m2:
            name, pid = m2.groups()
            valid_ids.add(pid)
            continue
        m3 = re_summary.match(s)
        if m3:
            total, valid, invalid, warn_count = map(int, m3.groups())
            continue

    return {
        "errors": errors,
        "warnings": warnings,
        "valid_ids": valid_ids,
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "warning_count": warn_count,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "run_script_exists_executable": 0.0,
        "run_script_invokes_validator_and_redirects": 0.0,
        "run_script_mentions_report_paths": 0.0,
        "run_script_no_jq_usage": 0.0,
        "raw_output_exists": 0.0,
        "raw_output_exact_match": 0.0,
        "summary_json_exists_schema": 0.0,
        "summary_json_counts_correct": 0.0,
        "summary_json_groupings_correct": 0.0,
        "errors_csv_exists_schema": 0.0,
        "errors_csv_content_correct": 0.0,
        "status_msg_exists_length": 0.0,
        "status_msg_includes_counts": 0.0,
        "status_msg_mentions_errors_csv": 0.0,
        "status_msg_tone_constructive": 0.0,
    }

    # Expected results from running the authoritative validator (no workspace modification)
    expected = _run_validator_and_collect(workspace)

    # 1) Check the run script
    run_script = workspace / "tools" / "run_validation.sh"
    if run_script.exists() and run_script.is_file():
        # Executable bit or shebang present, count as "runnable"
        try:
            is_exec = run_script.stat().st_mode & 0o111 != 0
        except Exception:
            is_exec = False
        text = _read_text(run_script) or ""
        has_shebang = text.startswith("#!") if text else False
        if is_exec or has_shebang:
            scores["run_script_exists_executable"] = 1.0

        # Checks that it invokes the validator and redirects combined streams to the expected path
        # Look for "python3 input/tools/pattern_validate.py --catalog input/patterns/catalog.json"
        invokes = ("python3 input/tools/pattern_validate.py --catalog input/patterns/catalog.json" in text)
        # Combined redirection detection: either "2>&1" with ">" or pipefail "|&"
        redirects_combined = ("2>&1" in text or "|&" in text)
        # Ensure overwrite ">" used; if ">>" used, treat as fail
        overwrites = ("> workspace/reports/raw_output.txt" in text) and (">> workspace/reports/raw_output.txt" not in text)
        if invokes and redirects_combined and overwrites:
            scores["run_script_invokes_validator_and_redirects"] = 1.0

        # Mentions generating both summary.json and errors.csv at the exact paths
        mentions_summary = "workspace/reports/summary.json" in text
        mentions_errors_csv = "workspace/reports/errors.csv" in text
        if mentions_summary and mentions_errors_csv:
            scores["run_script_mentions_report_paths"] = 1.0

        # No jq usage (non-standard)
        if "jq " not in text and " jq" not in text:
            scores["run_script_no_jq_usage"] = 1.0

    # 2) Artifacts from a run
    raw_output_path = workspace / "workspace" / "reports" / "raw_output.txt"
    summary_json_path = workspace / "workspace" / "reports" / "summary.json"
    errors_csv_path = workspace / "workspace" / "reports" / "errors.csv"
    status_msg_path = workspace / "workspace" / "outbound" / "status_message.txt"

    # raw_output existence and content
    raw_content = _read_text(raw_output_path)
    if raw_content is not None and len(raw_content.strip()) > 0:
        scores["raw_output_exists"] = 1.0

    if expected is not None and raw_content is not None:
        combined_expected = _normalize_newlines(expected["combined"])
        if _normalize_newlines(raw_content) == combined_expected:
            scores["raw_output_exact_match"] = 1.0

    # 3) summary.json checks
    summary_data = _load_json(summary_json_path)
    if isinstance(summary_data, dict):
        required_keys = {
            "total_patterns": int,
            "valid_count": int,
            "invalid_count": int,
            "warning_count": int,
            "errors_by_pattern": list,
            "warnings_by_pattern": list,
        }
        type_ok = True
        for k, t in required_keys.items():
            if k not in summary_data:
                type_ok = False
                break
            if not isinstance(summary_data[k], t):
                type_ok = False
                break

        # Deep check items in lists
        if type_ok:
            def _list_schema_ok(items: Any) -> bool:
                if not isinstance(items, list):
                    return False
                for it in items:
                    if not isinstance(it, dict):
                        return False
                    if set(it.keys()) != {"id", "name", "codes"}:
                        return False
                    if not isinstance(it["id"], str):
                        return False
                    if not isinstance(it["name"], str):
                        return False
                    if not isinstance(it["codes"], list):
                        return False
                    for c in it["codes"]:
                        if not isinstance(c, str):
                            return False
                return True

            if _list_schema_ok(summary_data["errors_by_pattern"]) and _list_schema_ok(summary_data["warnings_by_pattern"]):
                scores["summary_json_exists_schema"] = 1.0

    # Validate counts and groupings vs expected validator output
    if summary_data and expected is not None and expected["total"] is not None:
        counts_match = (
            summary_data.get("total_patterns") == expected["total"]
            and summary_data.get("valid_count") == expected["valid"]
            and summary_data.get("invalid_count") == expected["invalid"]
            and summary_data.get("warning_count") == expected["warning_count"]
        )
        if counts_match:
            scores["summary_json_counts_correct"] = 1.0

        # Groupings check: compare errors_by_pattern and warnings_by_pattern codes per id and names
        def _to_map(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
            res: Dict[str, Dict[str, Any]] = {}
            for it in items:
                res[it["id"]] = {"name": it["name"], "codes": sorted(list(set(it["codes"])))}
            return res

        if isinstance(summary_data, dict) and "errors_by_pattern" in summary_data and "warnings_by_pattern" in summary_data:
            actual_err_map = _to_map(summary_data["errors_by_pattern"])
            actual_warn_map = _to_map(summary_data["warnings_by_pattern"])
            exp_err_map: Dict[str, Dict[str, Any]] = {}
            exp_warn_map: Dict[str, Dict[str, Any]] = {}

            for pid, info in expected["errors"].items():
                exp_err_map[pid] = {"name": info["name"], "codes": sorted(list(set(info["codes"])))}
            for pid, info in expected["warnings"].items():
                exp_warn_map[pid] = {"name": info["name"], "codes": sorted(list(set(info["codes"])))}

            # Compare maps: same keys, same names, same codes
            def _maps_equal(a: Dict[str, Dict[str, Any]], b: Dict[str, Dict[str, Any]]) -> bool:
                if set(a.keys()) != set(b.keys()):
                    return False
                for k in a:
                    if a[k]["name"] != b[k]["name"]:
                        return False
                    if a[k]["codes"] != b[k]["codes"]:
                        return False
                return True

            if _maps_equal(actual_err_map, exp_err_map) and _maps_equal(actual_warn_map, exp_warn_map):
                scores["summary_json_groupings_correct"] = 1.0

    # 4) errors.csv checks
    csv_parsed = _parse_csv(errors_csv_path)
    if csv_parsed is not None:
        header, rows = csv_parsed
        expected_header = ["id", "name", "level", "code", "message"]
        if header == expected_header:
            scores["errors_csv_exists_schema"] = 1.0

        if expected is not None:
            # Build expected error rows set of tuples for comparison
            exp_errors: List[Tuple[str, str, str, str, str]] = []
            for pid, info in expected["errors"].items():
                name = info["name"]
                for code, message in info["entries"]:
                    exp_errors.append((pid, name, "ERROR", code, message))
            exp_set = set(exp_errors)

            # Build actual set
            actual_set = set()
            only_errors = True
            for r in rows:
                if len(r) != 5:
                    only_errors = False
                    break
                rid, rname, rlevel, rcode, rmessage = r
                if rlevel != "ERROR":
                    only_errors = False
                    break
                actual_set.add((rid, rname, rlevel, rcode, rmessage))

            if only_errors and actual_set == exp_set:
                scores["errors_csv_content_correct"] = 1.0

    # 5) status message checks
    msg_text = _read_text(status_msg_path)
    if msg_text is not None:
        words = [w for w in re.findall(r"\b\w+\b", msg_text)]
        wc = len(words)
        if 80 <= wc <= 120:
            scores["status_msg_exists_length"] = 1.0

        # Includes counts from summary.json as numbers
        # We require all four numbers to appear in the message text
        if isinstance(summary_data, dict):
            nums_required = [
                summary_data.get("total_patterns"),
                summary_data.get("valid_count"),
                summary_data.get("invalid_count"),
                summary_data.get("warning_count"),
            ]
            if all(isinstance(n, int) for n in nums_required):
                present_nums = re.findall(r"\d+", msg_text)
                present_nums_int = set(int(n) for n in present_nums)
                if all(n in present_nums_int for n in nums_required):
                    scores["status_msg_includes_counts"] = 1.0

        # Mentions relative path to errors CSV
        if "workspace/reports/errors.csv" in msg_text:
            scores["status_msg_mentions_errors_csv"] = 1.0

        # Tone: avoid blamey or urgent phrasing; include friendly cue
        banned = ["asap", "trash", "frustrating", "urgent", "blame", "fault", "broken", "breaking"]
        lower = msg_text.lower()
        if not any(b in lower for b in banned):
            # Friendly tokens
            friendly_tokens = ["please", "thanks", "thank you", "appreciate", "let's", "team"]
            if any(tok in lower for tok in friendly_tokens):
                scores["status_msg_tone_constructive"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()