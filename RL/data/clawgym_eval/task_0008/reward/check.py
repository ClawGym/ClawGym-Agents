import json
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def safe_load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data, None
        return None, "JSON is not an object"
    except Exception as e:
        return None, str(e)


def safe_load_json_list(path: Path) -> Tuple[Optional[list], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data, None
        return None, "JSON is not a list"
    except Exception as e:
        return None, str(e)


def safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def compute_expected_scan_data(workspace: Path) -> Optional[dict]:
    deps_path = workspace / "input" / "dependencies.json"
    db_path = workspace / "input" / "vuln_db.json"
    deps, e1 = safe_load_json_list(deps_path)
    db, e2 = safe_load_json_list(db_path)
    if deps is None or db is None:
        return None

    db_by_pkg: Dict[str, List[dict]] = {}
    for entry in db:
        pkg = entry.get("package")
        db_by_pkg.setdefault(pkg, []).append(entry)

    vulns: List[dict] = []
    for dep in deps:
        name = dep.get("name")
        version = dep.get("version")
        for entry in db_by_pkg.get(name, []):
            affected = entry.get("affected_versions", [])
            if version in affected:
                vulns.append({
                    "package": name,
                    "version": version,
                    "id": entry.get("id"),
                    "severity": entry.get("severity"),
                    "title": entry.get("title"),
                })

    vulns.sort(key=lambda v: (v.get("package", ""), v.get("id", "")))

    sev_counts: Dict[str, int] = {"High": 0, "Medium": 0, "Low": 0}
    for v in vulns:
        sev = v.get("severity", "Unknown")
        if sev not in sev_counts:
            sev_counts[sev] = 0
        sev_counts[sev] += 1

    result = {
        "vulnerabilities": vulns,
        "severity_counts": sev_counts,
        "total": len(vulns),
    }
    return result


def load_current_scan(workspace: Path) -> Tuple[Optional[dict], Optional[str]]:
    scan_path = workspace / "out" / "scan_results.json"
    return safe_load_json(scan_path)


def load_baseline_scan(workspace: Path) -> Tuple[Optional[dict], Optional[str]]:
    baseline_path = workspace / "input" / "baseline_scan.json"
    return safe_load_json(baseline_path)


def extract_section_bullets(lines: List[str], header_phrase: str) -> List[str]:
    header_idx = None
    lower_phrase = header_phrase.lower()
    for i, line in enumerate(lines):
        if lower_phrase in line.lower():
            header_idx = i
            break
    bullets: List[str] = []
    if header_idx is None:
        return bullets
    j = header_idx + 1
    while j < len(lines):
        s = lines[j].strip()
        if (("since baseline" in s.lower() and not s.startswith("- "))
                or "next actions" in s.lower()):
            break
        if s.startswith("- "):
            bullets.append(s)
            j += 1
            continue
        if s == "":
            j += 1
            continue
        break
    return bullets


def extract_section_actions(lines: List[str], header_phrase: str) -> List[str]:
    header_idx = None
    lower_phrase = header_phrase.lower()
    for i, line in enumerate(lines):
        if lower_phrase in line.lower():
            header_idx = i
            break
    actions: List[str] = []
    if header_idx is None:
        return actions
    j = header_idx + 1
    while j < len(lines):
        s = lines[j].strip()
        if ("since baseline" in s.lower() and not s.lower().startswith("action:")):
            break
        if s.lower().startswith("next actions"):
            j += 1
            continue
        if s.lower().startswith("action:"):
            actions.append(s)
            j += 1
            continue
        if s == "":
            j += 1
            continue
        break
    return actions


def contains_total_line(lines: List[str], total: int) -> bool:
    pat = re.compile(r"\btotal\b", flags=re.IGNORECASE)
    num_pat = re.compile(rf"\b{re.escape(str(total))}\b")
    for line in lines:
        if pat.search(line) and num_pat.search(line):
            return True
    return False


def contains_severity_counts(lines: List[str], sev_counts: Dict[str, int]) -> bool:
    for sev in ["High", "Medium", "Low"]:
        count = sev_counts.get(sev, 0)
        found = False
        num_pat = re.compile(rf"\b{re.escape(str(count))}\b")
        for line in lines:
            if sev in line and num_pat.search(line):
                found = True
                break
        if not found:
            return False
    return True


def expected_diff_lines(current: dict, baseline: dict) -> Tuple[List[str], List[str]]:
    def to_map(data: dict) -> Dict[Tuple[str, str, str], dict]:
        out: Dict[Tuple[str, str, str], dict] = {}
        vulns = data.get("vulnerabilities", []) if isinstance(data, dict) else []
        for v in vulns:
            key = (v.get("package"), v.get("version"), v.get("id"))
            out[key] = v
        return out

    cur_map = to_map(current)
    base_map = to_map(baseline)
    new_keys = sorted(set(cur_map.keys()) - set(base_map.keys()))
    resolved_keys = sorted(set(base_map.keys()) - set(cur_map.keys()))
    new_lines = []
    for key in new_keys:
        v = cur_map[key]
        new_lines.append(f"- {v.get('id')} on {v.get('package')}@{v.get('version')} ({v.get('severity')}).")
    resolved_lines = []
    for key in resolved_keys:
        v = base_map[key]
        resolved_lines.append(f"- {v.get('id')} on {v.get('package')}@{v.get('version')} ({v.get('severity')}).")
    return new_lines, resolved_lines


def expected_next_actions_lines(current: dict) -> List[str]:
    out = []
    vulns = current.get("vulnerabilities", []) if isinstance(current, dict) else []
    for v in vulns:
        if v.get("severity") == "High":
            out.append(f"Action: prioritize patch for {v.get('package')}@{v.get('version')} (ID: {v.get('id')}).")
    return sorted(out)


def compare_json_dicts(a: dict, b: dict) -> bool:
    def sort_vulns(d: dict) -> dict:
        d2 = dict(d)
        vulns = d2.get("vulnerabilities")
        if isinstance(vulns, list):
            try:
                vulns_sorted = sorted(vulns, key=lambda v: (v.get("package", ""), v.get("id", "")))
                d2["vulnerabilities"] = vulns_sorted
            except Exception:
                pass
        return d2

    a_sorted = sort_vulns(a)
    b_sorted = sort_vulns(b)
    return a_sorted == b_sorted


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "scan_results_json_valid": 0.0,
        "scan_results_matches_expected": 0.0,
        "report_file_exists": 0.0,
        "report_summary_counts_correct": 0.0,
        "report_new_since_baseline_correct": 0.0,
        "report_resolved_since_baseline_correct": 0.0,
        "report_next_actions_correct": 0.0,
        "report_closing_line_present": 0.0,
    }

    current_scan, _ = load_current_scan(workspace)
    if current_scan is not None and isinstance(current_scan, dict):
        scores["scan_results_json_valid"] = 1.0
    else:
        current_scan = None

    expected = compute_expected_scan_data(workspace)
    if expected is not None and current_scan is not None:
        if compare_json_dicts(current_scan, expected):
            scores["scan_results_matches_expected"] = 1.0

    report_path = workspace / "out" / "security_status_update.md"
    report_text, _ = safe_read_text(report_path)
    lines: List[str] = []
    if report_text is not None:
        scores["report_file_exists"] = 1.0
        lines = report_text.splitlines()

    if current_scan is not None and lines:
        total = current_scan.get("total")
        sev_counts = current_scan.get("severity_counts", {})
        if isinstance(total, int) and isinstance(sev_counts, dict):
            has_total = contains_total_line(lines, total)
            has_sev = contains_severity_counts(lines, sev_counts)
            if has_total and has_sev:
                scores["report_summary_counts_correct"] = 1.0

    baseline_scan, _ = load_baseline_scan(workspace)
    if current_scan is not None and baseline_scan is not None and lines:
        expected_new, expected_resolved = expected_diff_lines(current_scan, baseline_scan)
        new_bullets = extract_section_bullets(lines, "New since baseline")
        resolved_bullets = extract_section_bullets(lines, "Resolved since baseline")
        if set(new_bullets) == set(expected_new) and len(new_bullets) == len(expected_new):
            scores["report_new_since_baseline_correct"] = 1.0
        if set(resolved_bullets) == set(expected_resolved) and len(resolved_bullets) == len(expected_resolved):
            scores["report_resolved_since_baseline_correct"] = 1.0

    if current_scan is not None and lines:
        expected_actions = expected_next_actions_lines(current_scan)
        actions_lines = extract_section_actions(lines, "Next actions")
        if set(actions_lines) == set(expected_actions) and len(actions_lines) == len(expected_actions):
            scores["report_next_actions_correct"] = 1.0

    if lines:
        cmd_str = "python3 tools/deps_audit.py --deps input/dependencies.json --db input/vuln_db.json --out out/scan_results.json"
        found = any(cmd_str in line for line in lines)
        if found:
            scores["report_closing_line_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()