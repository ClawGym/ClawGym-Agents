import json
import sys
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _read_text(path: Path) -> Tuple[bool, str]:
    try:
        data = path.read_text(encoding="utf-8")
        return True, data
    except Exception:
        return False, ""


def _load_json(path: Path) -> Tuple[bool, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _load_csv_dicts(path: Path) -> Tuple[bool, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                row = dict(r)
                # Coerce types where possible
                try:
                    if "pid" in row:
                        row["pid"] = int(row["pid"])
                except Exception:
                    return False, []
                try:
                    if "cpu_percent" in row:
                        row["cpu_percent"] = float(row["cpu_percent"])
                except Exception:
                    return False, []
                try:
                    if "mem_mb" in row:
                        m = float(row["mem_mb"])
                        if m.is_integer():
                            m = int(m)
                        row["mem_mb"] = m
                except Exception:
                    return False, []
                rows.append(row)
        return True, rows
    except Exception:
        return False, []


def _near_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return a == b


def _contains_blocklist(name: str, blocklist: List[str]) -> bool:
    lower = name.lower()
    for term in blocklist:
        if term.lower() in lower:
            return True
    return False


def _compute_expected_from_inputs(workspace: Path) -> Dict[str, Any]:
    ok_csv, rows = _load_csv_dicts(workspace / "input" / "processes.csv")
    ok_sys, sysinfo = _load_json(workspace / "input" / "system_info.json")

    expected_thresholds = {
        "cpu_threshold": 5.0,
        "mem_threshold": 200,
        "purist_mode": True,
        "purist_blocklist": ["autoformat", "modernizer", "synonymizer"],
    }

    result: Dict[str, Any] = {
        "ok_csv": ok_csv,
        "ok_sys": ok_sys,
        "rows": rows if ok_csv else [],
        "sysinfo": sysinfo if ok_sys else {},
        "thresholds": expected_thresholds,
    }

    if not ok_csv:
        result.update(
            {
                "top_cpu": [],
                "top_mem": [],
                "flagged_processes": [],
                "over_cpu_count": 0,
                "over_mem_count": 0,
                "any_flagged": False,
            }
        )
        return result

    blocklist = expected_thresholds["purist_blocklist"]
    cpu_thr = expected_thresholds["cpu_threshold"]
    mem_thr = expected_thresholds["mem_threshold"]

    sorted_by_cpu = sorted(
        rows, key=lambda r: (-float(r.get("cpu_percent", 0.0)), int(r.get("pid", 0)))
    )
    sorted_by_mem = sorted(
        rows, key=lambda r: (-float(r.get("mem_mb", 0.0)), int(r.get("pid", 0)))
    )
    top_cpu_src = sorted_by_cpu[:5]
    top_mem_src = sorted_by_mem[:5]

    def _map_row(r: Dict[str, Any]) -> Dict[str, Any]:
        name = str(r.get("name", ""))
        cpu_val = float(r.get("cpu_percent", 0.0))
        mem_val = float(r.get("mem_mb", 0.0))
        mem_out: Any = int(mem_val) if float(mem_val).is_integer() else mem_val
        return {
            "pid": int(r.get("pid", 0)),
            "name": name,
            "cpu_percent": cpu_val,
            "mem_mb": mem_out,
            "flagged": _contains_blocklist(name, blocklist),
            "over_cpu_threshold": cpu_val > cpu_thr,
            "over_mem_threshold": float(mem_val) > float(mem_thr),
        }

    exp_top_cpu = [_map_row(r) for r in top_cpu_src]
    exp_top_mem = [_map_row(r) for r in top_mem_src]

    flagged_all = []
    for r in rows:
        if _contains_blocklist(str(r.get("name", "")), blocklist):
            flagged_all.append({"pid": int(r.get("pid", 0)), "name": str(r.get("name", ""))})
    seen = set()
    unique_flagged = []
    for fp in flagged_all:
        key = (fp["pid"], fp["name"])
        if key not in seen:
            seen.add(key)
            unique_flagged.append(fp)

    over_cpu_count = sum(1 for r in rows if float(r.get("cpu_percent", 0.0)) > cpu_thr)
    over_mem_count = sum(1 for r in rows if float(r.get("mem_mb", 0.0)) > float(mem_thr))
    any_flagged = len(unique_flagged) > 0

    result.update(
        {
            "top_cpu": exp_top_cpu,
            "top_mem": exp_top_mem,
            "flagged_processes": unique_flagged,
            "over_cpu_count": over_cpu_count,
            "over_mem_count": over_mem_count,
            "any_flagged": any_flagged,
        }
    )

    return result


def _compare_top_lists(expected: List[Dict[str, Any]], actual: List[Dict[str, Any]]) -> bool:
    if not isinstance(actual, list):
        return False
    if len(actual) != len(expected):
        return False
    req_keys = {"pid", "name", "cpu_percent", "mem_mb", "flagged", "over_cpu_threshold", "over_mem_threshold"}
    for e, a in zip(expected, actual):
        if not isinstance(a, dict):
            return False
        if set(a.keys()) != req_keys:
            return False
        try:
            if int(a["pid"]) != int(e["pid"]):
                return False
        except Exception:
            return False
        if str(a["name"]) != str(e["name"]):
            return False
        if not _near_equal(a["cpu_percent"], e["cpu_percent"], tol=1e-6):
            return False
        if not _near_equal(a["mem_mb"], e["mem_mb"], tol=1e-6):
            return False
        if bool(a["flagged"]) != bool(e["flagged"]):
            return False
        if bool(a["over_cpu_threshold"]) != bool(e["over_cpu_threshold"]):
            return False
        if bool(a["over_mem_threshold"]) != bool(e["over_mem_threshold"]):
            return False
    return True


def _unordered_set_of_pid_name(list_obj: Any) -> Any:
    if not isinstance(list_obj, list):
        return None
    s = set()
    for item in list_obj:
        if not isinstance(item, dict):
            return None
        if "pid" not in item or "name" not in item:
            return None
        try:
            s.add((int(item["pid"]), str(item["name"])))
        except Exception:
            return None
    return s


def _md_contains_os_and_disk(md_text: str, sysinfo: Dict[str, Any]) -> bool:
    if not isinstance(sysinfo, dict):
        return False
    os_name = str(sysinfo.get("os_name", ""))
    disk_total = sysinfo.get("disk_total_gb", None)
    disk_used = sysinfo.get("disk_used_gb", None)
    if not os_name or disk_total is None or disk_used is None:
        return False
    if os_name not in md_text:
        return False
    total_str = str(int(disk_total)) if isinstance(disk_total, (int, float)) and float(disk_total).is_integer() else str(disk_total)
    used_str = str(int(disk_used)) if isinstance(disk_used, (int, float)) and float(disk_used).is_integer() else str(disk_used)
    if total_str not in md_text or used_str not in md_text:
        return False
    return True


def _md_contains_top_lists(md_text: str, top_cpu: List[Dict[str, Any]], top_mem: List[Dict[str, Any]]) -> bool:
    for item in top_cpu:
        name = item["name"]
        cpu_val = item["cpu_percent"]
        if isinstance(cpu_val, float):
            cpu_str = f"{cpu_val}".rstrip("0").rstrip(".")
        else:
            cpu_str = str(cpu_val)
        mem_val = item["mem_mb"]
        mem_str = f"{mem_val}"
        if name not in md_text:
            return False
        if cpu_str not in md_text:
            return False
        if mem_str not in md_text:
            return False
    for item in top_mem:
        name = item["name"]
        mem_val = item["mem_mb"]
        mem_str = f"{mem_val}"
        if name not in md_text or mem_str not in md_text:
            return False
    return True


def _extract_appendix_section(md_text: str) -> str:
    lines = md_text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("#") and "system appendix" in line.lower():
            start_idx = i
    if start_idx is None:
        return ""
    content_lines: List[str] = []
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip().startswith("#"):
            break
        content_lines.append(lines[j])
    return "\n".join(content_lines).strip()


def _parse_bullets(section: str) -> List[str]:
    bullets = []
    for line in section.splitlines():
        if re.match(r'^\s*[-*+]\s+', line):
            bullets.append(line.strip())
    return bullets


def _find_flagged_sentence(section: str) -> Tuple[bool, str]:
    for line in section.splitlines():
        if "Flagged processes present:" in line:
            return True, line.strip()
    return False, ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_yaml_exact_values": 0.0,
        "system_report_json_structure_and_thresholds": 0.0,
        "top_cpu_correct": 0.0,
        "top_mem_correct": 0.0,
        "flagged_processes_correct": 0.0,
        "summary_field_includes_counts_and_flagged": 0.0,
        "system_report_md_os_and_disk": 0.0,
        "system_report_md_lists_match_json": 0.0,
        "draft_review_appendix_top3_cpu": 0.0,
        "draft_review_appendix_flagged_sentence_and_names": 0.0,
        "status_message_rewritten_length_and_content": 0.0,
        "status_message_formality_basic": 0.0,
    }

    expected_yaml = (
        "cpu_threshold: 5.0\n"
        "mem_threshold: 200\n"
        "purist_mode: true\n"
        "purist_blocklist: [\"autoformat\", \"modernizer\", \"synonymizer\"]\n"
    )
    cfg_path = workspace / "config" / "monitor.yaml"
    ok_cfg, cfg_text = _read_text(cfg_path)
    if ok_cfg:
        cfg_text_norm = cfg_text.replace("\r\n", "\n").replace("\r", "\n")
        if not cfg_text_norm.endswith("\n"):
            cfg_text_norm += "\n"
        if cfg_text_norm == expected_yaml:
            scores["config_yaml_exact_values"] = 1.0

    comp = _compute_expected_from_inputs(workspace)

    report_path = workspace / "output" / "system_report.json"
    ok_json, report = _load_json(report_path)
    if ok_json and isinstance(report, dict):
        th = report.get("thresholds")
        if isinstance(th, dict):
            exp_th = comp["thresholds"]
            if (
                set(th.keys()) == set(exp_th.keys())
                and _near_equal(th.get("cpu_threshold"), exp_th["cpu_threshold"])
                and _near_equal(th.get("mem_threshold"), exp_th["mem_threshold"])
                and bool(th.get("purist_mode")) is True
                and isinstance(th.get("purist_blocklist"), list)
                and [str(x) for x in th.get("purist_blocklist")] == exp_th["purist_blocklist"]
            ):
                if "top_cpu" in report and "top_mem" in report and "flagged_processes" in report and "summary" in report:
                    scores["system_report_json_structure_and_thresholds"] = 1.0

        if comp["ok_csv"]:
            exp_top_cpu = comp["top_cpu"]
            exp_top_mem = comp["top_mem"]
            if _compare_top_lists(exp_top_cpu, report.get("top_cpu", [])):
                scores["top_cpu_correct"] = 1.0
            if _compare_top_lists(exp_top_mem, report.get("top_mem", [])):
                scores["top_mem_correct"] = 1.0

            exp_flagged_set = {(fp["pid"], fp["name"]) for fp in comp["flagged_processes"]}
            actual_flagged_set = _unordered_set_of_pid_name(report.get("flagged_processes"))
            if actual_flagged_set is not None and actual_flagged_set == exp_flagged_set:
                scores["flagged_processes_correct"] = 1.0

            summary = report.get("summary", "")
            if isinstance(summary, str):
                over_cpu_count = comp["over_cpu_count"]
                over_mem_count = comp["over_mem_count"]
                any_flagged = comp["any_flagged"]
                has_cpu_count = str(over_cpu_count) in summary
                has_mem_count = str(over_mem_count) in summary
                flagged_str = "Yes" if any_flagged else "No"
                has_flagged_term = ("flagged" in summary.lower()) and (flagged_str.lower() in summary.lower())
                if has_cpu_count and has_mem_count and has_flagged_term:
                    scores["summary_field_includes_counts_and_flagged"] = 1.0

    md_path = workspace / "output" / "system_report.md"
    ok_md, md_text = _read_text(md_path)
    if ok_md:
        if comp["ok_sys"] and _md_contains_os_and_disk(md_text, comp["sysinfo"]):
            scores["system_report_md_os_and_disk"] = 1.0
        if ok_json and isinstance(report, dict):
            top_cpu_json = report.get("top_cpu", [])
            top_mem_json = report.get("top_mem", [])
            if isinstance(top_cpu_json, list) and isinstance(top_mem_json, list):
                if _md_contains_top_lists(md_text, top_cpu_json, top_mem_json):
                    scores["system_report_md_lists_match_json"] = 1.0

    draft_path = workspace / "docs" / "draft_review.md"
    ok_draft, draft_text = _read_text(draft_path)
    if ok_draft and comp["ok_csv"]:
        appendix = _extract_appendix_section(draft_text)
        if appendix:
            bullets = _parse_bullets(appendix)
            exp_top3 = comp["top_cpu"][:3]
            pass_top3 = False
            if len(bullets) >= 3:
                b1, b2, b3 = bullets[0], bullets[1], bullets[2]
                names = [exp_top3[0]["name"], exp_top3[1]["name"], exp_top3[2]["name"]]
                cpus = [
                    f"{exp_top3[0]['cpu_percent']}".rstrip("0").rstrip("."),
                    f"{exp_top3[1]['cpu_percent']}".rstrip("0").rstrip("."),
                    f"{exp_top3[2]['cpu_percent']}".rstrip("0").rstrip("."),
                ]
                conds = []
                for b, nm, cp in zip([b1, b2, b3], names, cpus):
                    conds.append(nm in b and cp in b)
                if all(conds):
                    pass_top3 = True
            if pass_top3:
                scores["draft_review_appendix_top3_cpu"] = 1.0

            has_sentence, sentence = _find_flagged_sentence(appendix)
            if has_sentence:
                expect_yes = comp["any_flagged"]
                expected_token = "Yes" if expect_yes else "No"
                if sentence.strip().endswith(expected_token):
                    if expect_yes:
                        flagged_names = {fp["name"] for fp in comp["flagged_processes"]}
                        names_present = all(name in appendix for name in flagged_names)
                        if names_present:
                            scores["draft_review_appendix_flagged_sentence_and_names"] = 1.0
                    else:
                        scores["draft_review_appendix_flagged_sentence_and_names"] = 1.0

    status_rewritten_path = workspace / "output" / "status_message_rewritten.txt"
    ok_status, status_text = _read_text(status_rewritten_path)
    if ok_status:
        words = re.findall(r"\b\w[\w'-]*\b", status_text)
        wc = len(words)
        len_ok = 80 <= wc <= 120
        has_status_report = "status report" in status_text.lower()
        has_attached = "attached" in status_text.lower()
        has_automated = "automated" in status_text.lower()
        has_modernizer = any(tok in status_text.lower() for tok in ["modernizer", "modernizers"])
        has_prose = "prose" in status_text.lower()
        if len_ok and has_status_report and has_attached and has_automated and has_modernizer and has_prose:
            scores["status_message_rewritten_length_and_content"] = 1.0

        informal_terms = ["hey", "sorry", "gonna", "kinda", "wanna", "lol", "!", "u ", " asap", "btw", "imo", "idk"]
        if not any(term in status_text.lower() for term in informal_terms):
            scores["status_message_formality_basic"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()