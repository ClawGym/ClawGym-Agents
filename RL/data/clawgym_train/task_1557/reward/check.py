import json
import sys
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        records = []
        for ln in lines:
            if not ln.strip():
                continue
            obj = json.loads(ln)
            if not isinstance(obj, dict):
                return None
            records.append(obj)
        return records
    except Exception:
        return None


def _is_iso8601(ts: Any) -> bool:
    if not isinstance(ts, str) or not ts.strip():
        return False
    s = ts.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def _compute_sha256_and_size(path: Path) -> Optional[Tuple[str, int]]:
    try:
        h = hashlib.sha256()
        size = 0
        with path.open("rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
        return h.hexdigest(), size
    except Exception:
        return None


def _load_case_metadata(workspace: Path) -> Optional[Dict[str, Any]]:
    return _load_json(workspace / "input" / "case_metadata.json")


def _match_command_patterns(cmd: str, pattern: Any) -> bool:
    # pattern can be a string (substring) or a tuple/list of substrings that must all be present
    if isinstance(pattern, str):
        return pattern in cmd
    try:
        return all(sub in cmd for sub in pattern)
    except Exception:
        return False


def _categorize_commands(records: List[Dict[str, Any]]) -> Dict[str, bool]:
    # Categories and acceptable command patterns
    patterns: Dict[str, List[Any]] = {
        "os_host": [
            "uname -srm",
            "systeminfo",
            ("wmic", "os", "get", "Caption"),
            ("wmic", "os", "get", "Caption,Version"),
        ],
        "uptime": [
            "uptime",
            ("wmic", "os", "get", "LastBootUpTime"),
        ],
        "cpu": [
            "lscpu",
            "sysctl -n machdep.cpu.brand_string",
            ("wmic", "cpu", "get", "Name"),
            ("wmic", "cpu", "get", "Name,NumberOfCores,NumberOfLogicalProcessors"),
        ],
        "memory": [
            "free -m",
            "vm_stat",
            ("wmic", "OS", "get", "TotalVisibleMemorySize"),
            ("wmic", "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory"),
        ],
        "disks": [
            "df -h",
            ("wmic", "logicaldisk", "get", "Size"),
            ("wmic", "logicaldisk", "get", "Size,FreeSpace,Caption"),
        ],
        "network_interfaces": [
            "ip -o -4 addr",
            "ifconfig",
            "ipconfig",
        ],
        "listening_ports": [
            "ss -tulwn",
            ("lsof", "-nP", "-iTCP"),
            ("lsof", "-iTCP", "LISTEN"),
            "netstat -ano",
        ],
    }
    found = {k: False for k in patterns.keys()}
    for rec in records:
        cmd = rec.get("command", "")
        if not isinstance(cmd, str):
            continue
        for cat, opts in patterns.items():
            if found[cat]:
                continue
            if any(_match_command_patterns(cmd, p) for p in opts):
                found[cat] = True
    return found


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "commands_log_exists": 0.0,
        "commands_log_records_well_formed": 0.0,
        "commands_attempted_required_categories": 0.0,
        "summary_json_exists": 0.0,
        "summary_json_fields_from_metadata": 0.0,
        "summary_json_structure_and_types": 0.0,
        "summary_failures_cover_failed_commands": 0.0,
        "readiness_value_valid": 0.0,
        "readiness_consistent_with_disks_if_available": 0.0,
        "external_reference_summary_status_valid": 0.0,
        "external_artifacts_and_hash_match_when_downloaded": 0.0,
        "report_md_exists": 0.0,
        "report_md_header_includes_metadata": 0.0,
        "report_md_summary_mentions_readiness_and_case": 0.0,
        "report_md_connectivity_section_matches_status": 0.0,
        "report_md_references_some_commands": 0.0,
    }

    # Paths
    commands_path = workspace / "artifacts" / "raw" / "commands.jsonl"
    summary_path = workspace / "artifacts" / "report" / "system_status_summary.json"
    report_md_path = workspace / "artifacts" / "report" / "system_status_report.md"
    pem_path = workspace / "artifacts" / "external" / "cacert.pem"
    sha_path = workspace / "artifacts" / "external" / "cacert.sha256"

    # Load inputs
    metadata = _load_case_metadata(workspace)
    commands_records = _load_jsonl(commands_path) if commands_path.exists() else None
    summary = _load_json(summary_path) if summary_path.exists() else None
    report_md = _read_text(report_md_path) if report_md_path.exists() else None

    # commands_log_exists
    if commands_path.exists() and commands_path.is_file():
        try:
            if commands_path.stat().st_size > 0:
                scores["commands_log_exists"] = 1.0
        except Exception:
            pass

    # commands_log_records_well_formed
    if commands_records is not None and len(commands_records) >= 5:
        ok = True
        for rec in commands_records:
            if not isinstance(rec, dict):
                ok = False
                break
            # required fields with types
            ts = rec.get("timestamp")
            cmd = rec.get("command")
            exit_code = rec.get("exit_code")
            stdout = rec.get("stdout")
            stderr = rec.get("stderr")
            if not _is_iso8601(ts):
                ok = False
                break
            if not isinstance(cmd, str):
                ok = False
                break
            if not isinstance(exit_code, int):
                ok = False
                break
            if not isinstance(stdout, str):
                ok = False
                break
            if not isinstance(stderr, str):
                ok = False
                break
        if ok:
            scores["commands_log_records_well_formed"] = 1.0

    # commands_attempted_required_categories
    if commands_records:
        found = _categorize_commands(commands_records)
        # Require all 7 categories attempted at least once
        if all(found.values()):
            scores["commands_attempted_required_categories"] = 1.0

    # summary_json_exists
    if summary_path.exists() and summary_path.is_file() and summary is not None:
        scores["summary_json_exists"] = 1.0

    # summary_json_fields_from_metadata
    if metadata and summary:
        if (
            summary.get("case_number") == metadata.get("case_number")
            and summary.get("officer_name") == metadata.get("officer_name")
            and summary.get("station") == metadata.get("station")
        ):
            scores["summary_json_fields_from_metadata"] = 1.0

    # summary_json_structure_and_types
    if summary:
        try:
            required_string_fields = ["case_number", "officer_name", "station", "timestamp", "hostname", "os", "uptime_or_last_boot", "cpu_model"]
            ok = True
            for k in required_string_fields:
                v = summary.get(k)
                if not isinstance(v, str) or not v.strip():
                    ok = False
                    break
            if ok and not _is_iso8601(summary.get("timestamp")):
                ok = False
            # Optional numeric fields (may be missing or non-number if not derivable); if present must be number
            for k in ["cpu_cores_logical", "memory_total_mb", "memory_available_mb", "listening_ports_count"]:
                if k in summary and summary.get(k) is not None and not isinstance(summary.get(k), (int, float)):
                    ok = False
                    break
            # disks
            disks = summary.get("disks")
            if not isinstance(disks, list):
                ok = False
            else:
                for d in disks:
                    if not isinstance(d, dict):
                        ok = False
                        break
                    # Expect at least one identifier among identifier or mount
                    if not (("identifier" in d and isinstance(d.get("identifier"), str)) or ("mount" in d and isinstance(d.get("mount"), str))):
                        # allow when both missing but other fields present? Be strict: require at least one
                        ok = False
                        break
                    for numk in ["total_gb", "used_gb"]:
                        if numk in d and d.get(numk) is not None and not isinstance(d.get(numk), (int, float)):
                            ok = False
                            break
                    if not ok:
                        break
            # network_interfaces
            nics = summary.get("network_interfaces")
            if not isinstance(nics, list):
                ok = False
            else:
                for n in nics:
                    if not isinstance(n, dict):
                        ok = False
                        break
                    if "name" not in n or not isinstance(n.get("name"), str):
                        ok = False
                        break
                    if "ipv4" in n and n.get("ipv4") is not None and not isinstance(n.get("ipv4"), str):
                        ok = False
                        break
            # top processes arrays
            for arrk in ["top_processes_cpu", "top_processes_mem"]:
                arr = summary.get(arrk)
                if not isinstance(arr, list):
                    ok = False
                    break
                if len(arr) > 5:
                    ok = False
                    break
            # external_reference basic presence - detailed validation in separate key
            if not isinstance(summary.get("external_reference"), dict):
                ok = False
            # failures
            fails = summary.get("failures")
            if not isinstance(fails, list):
                ok = False
            else:
                for f in fails:
                    if not isinstance(f, dict):
                        ok = False
                        break
                    if "command" not in f or "error_snippet" not in f:
                        ok = False
                        break
                    if not isinstance(f.get("command"), str) or not isinstance(f.get("error_snippet"), str):
                        ok = False
                        break
            # readiness presence checked in dedicated key, but ensure it's a string here if present
            if "readiness" in summary and not isinstance(summary.get("readiness"), str):
                ok = False

            if ok:
                scores["summary_json_structure_and_types"] = 1.0
        except Exception:
            pass

    # summary_failures_cover_failed_commands
    if summary and isinstance(summary.get("failures"), list) and commands_records is not None:
        fails_list = summary.get("failures")
        failed_cmds = [rec.get("command") for rec in commands_records if isinstance(rec, dict) and isinstance(rec.get("exit_code"), int) and rec.get("exit_code") != 0 and isinstance(rec.get("command"), str)]
        if not failed_cmds:
            scores["summary_failures_cover_failed_commands"] = 1.0
        else:
            # Build set of commands present in failures
            failed_in_summary = set()
            for f in fails_list:
                cmd = f.get("command")
                if isinstance(cmd, str):
                    failed_in_summary.add(cmd)
            if all(cmd in failed_in_summary for cmd in failed_cmds):
                scores["summary_failures_cover_failed_commands"] = 1.0

    # readiness_value_valid
    if summary and isinstance(summary.get("readiness"), str):
        if summary.get("readiness") in {"ready", "needs_attention", "indeterminate"}:
            scores["readiness_value_valid"] = 1.0

    # readiness_consistent_with_disks_if_available
    if summary and isinstance(summary.get("disks"), list) and summary.get("readiness") in {"ready", "needs_attention", "indeterminate"}:
        disks = summary.get("disks")
        # Collect disks with numeric total and used
        numeric_disks = []
        for d in disks:
            if isinstance(d, dict):
                tg = d.get("total_gb")
                ug = d.get("used_gb")
                if isinstance(tg, (int, float)) and isinstance(ug, (int, float)):
                    numeric_disks.append((tg, ug))
        if numeric_disks:
            any_ge_10 = any((tg - ug) >= 10.0 for tg, ug in numeric_disks)
            derived = "ready" if any_ge_10 else "needs_attention"
            if summary.get("readiness") == derived:
                scores["readiness_consistent_with_disks_if_available"] = 1.0
        else:
            # If we cannot derive, then 'indeterminate' should be used
            if summary.get("readiness") == "indeterminate":
                scores["readiness_consistent_with_disks_if_available"] = 1.0

    # external_reference_summary_status_valid
    if summary and isinstance(summary.get("external_reference"), dict):
        ext = summary.get("external_reference")
        file_ok = ext.get("file") == "cacert.pem"
        source_ok = ext.get("source") == "cURL project"
        status_ok = ext.get("status") in {"downloaded", "failed"}
        sha_ok = True
        size_ok = True
        if "sha256" in ext and ext.get("sha256") is not None and not (isinstance(ext.get("sha256"), str) and len(ext.get("sha256")) == 64 and all(c in "0123456789abcdefABCDEF" for c in ext.get("sha256"))):
            sha_ok = False
        if "size_bytes" in ext and ext.get("size_bytes") is not None and not isinstance(ext.get("size_bytes"), int):
            size_ok = False
        if file_ok and source_ok and status_ok and sha_ok and size_ok:
            scores["external_reference_summary_status_valid"] = 1.0

    # external_artifacts_and_hash_match_when_downloaded
    if summary and isinstance(summary.get("external_reference"), dict):
        ext = summary.get("external_reference")
        status = ext.get("status")
        if status == "downloaded":
            calc = _compute_sha256_and_size(pem_path) if pem_path.exists() else None
            sha_file_ok = False
            sha_content = None
            if sha_path.exists():
                sha_text = _read_text(sha_path)
                if sha_text is not None:
                    sha_line = sha_text.strip().split()[0] if sha_text.strip() else ""
                    if len(sha_line) == 64 and all(c in "0123456789abcdefABCDEF" for c in sha_line):
                        sha_file_ok = True
                        sha_content = sha_line.lower()
            if calc and sha_file_ok:
                computed_sha, size_bytes = calc[0].lower(), calc[1]
                if (
                    ext.get("sha256", "").lower() == computed_sha
                    and sha_content == computed_sha
                    and ext.get("size_bytes") == size_bytes
                ):
                    scores["external_artifacts_and_hash_match_when_downloaded"] = 1.0
        elif status == "failed":
            # If failed, we don't require the files; pass this check as N/A by giving full credit
            scores["external_artifacts_and_hash_match_when_downloaded"] = 1.0

    # report_md_exists
    if report_md_path.exists() and report_md is not None:
        scores["report_md_exists"] = 1.0

    # report_md_header_includes_metadata
    if report_md and metadata:
        header_ok = True
        for key in ["case_number", "officer_name", "station"]:
            if metadata.get(key) not in report_md:
                header_ok = False
                break
        if header_ok:
            scores["report_md_header_includes_metadata"] = 1.0

    # report_md_summary_mentions_readiness_and_case
    if report_md and summary:
        readiness = summary.get("readiness")
        case_num = summary.get("case_number")
        if isinstance(readiness, str) and isinstance(case_num, str) and (readiness in report_md) and (case_num in report_md):
            scores["report_md_summary_mentions_readiness_and_case"] = 1.0

    # report_md_connectivity_section_matches_status
    if report_md and summary and isinstance(summary.get("external_reference"), dict):
        ext = summary.get("external_reference")
        status = ext.get("status")
        if status == "downloaded":
            sha = ext.get("sha256")
            size_bytes = ext.get("size_bytes")
            ok = True
            if "cURL" not in report_md and "cURL project" not in report_md:
                ok = False
            if "cacert.pem" not in report_md:
                ok = False
            if not (isinstance(sha, str) and sha and sha in report_md):
                ok = False
            if isinstance(size_bytes, int) and str(size_bytes) not in report_md:
                ok = False
            if ok:
                scores["report_md_connectivity_section_matches_status"] = 1.0
        elif status == "failed":
            # Look for failure wording
            if ("failed" in report_md.lower()) or ("error" in report_md.lower()):
                scores["report_md_connectivity_section_matches_status"] = 1.0

    # report_md_references_some_commands
    if report_md and commands_records:
        md = report_md
        # count how many exact command strings are mentioned
        mentioned = 0
        seen_cmds = set()
        for rec in commands_records:
            cmd = rec.get("command")
            if isinstance(cmd, str) and cmd not in seen_cmds:
                if cmd in md:
                    seen_cmds.add(cmd)
                    mentioned += 1
                if mentioned >= 2:
                    break
        if mentioned >= 2:
            scores["report_md_references_some_commands"] = 1.0

    return scores


def main() -> None:
        workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade([], workspace_path)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()