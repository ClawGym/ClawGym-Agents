import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _list_csv_files(root: Path) -> List[Path]:
    if not root.exists() or not root.is_dir():
        return []
    return sorted([p for p in root.rglob("*.csv") if p.is_file()])


def _parse_time_to_minutes(hhmm: str) -> Optional[int]:
    try:
        parts = hhmm.strip().split(":")
        if len(parts) != 2:
            return None
        h = int(parts[0])
        m = int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return h * 60 + m
    except Exception:
        return None


def _compute_expected_aggregates(logs_dir: Path) -> Optional[List[Dict[str, int]]]:
    csv_files = _list_csv_files(logs_dir)
    data_by_date: Dict[str, List[Tuple[str, str, str, str]]] = {}
    for csv_path in csv_files:
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                expected_fields = ["date", "kid_id", "kid_name", "checkin", "checkout"]
                if reader.fieldnames is None:
                    return None
                for k in expected_fields:
                    if k not in reader.fieldnames:
                        return None
                for row in reader:
                    d = row.get("date", "").strip()
                    kid_id = row.get("kid_id", "").strip()
                    kid_name = row.get("kid_name", "").strip()
                    ci = row.get("checkin", "").strip()
                    co = row.get("checkout", "").strip()
                    if not (d and kid_id and kid_name and ci and co):
                        return None
                    data_by_date.setdefault(d, []).append((kid_id, kid_name, ci, co))
        except Exception:
            return None
    aggregates: List[Dict[str, int]] = []
    for d in data_by_date:
        rows = data_by_date[d]
        total_checkins = len(rows)
        unique_kids = len({kid_id for kid_id, _, _, _ in rows})
        durations: List[int] = []
        for kid_id, kid_name, ci, co in rows:
            start_m = _parse_time_to_minutes(ci)
            end_m = _parse_time_to_minutes(co)
            if start_m is None or end_m is None:
                return None
            session = end_m - start_m
            if session < 0:
                return None
            durations.append(session)
        if len(durations) == 0:
            avg_session = 0
        else:
            avg_raw = sum(durations) / len(durations)
            avg_session = int(round(avg_raw))
        aggregates.append({
            "date": d,
            "total_checkins": total_checkins,
            "unique_kids": unique_kids,
            "avg_session_minutes": avg_session
        })
    aggregates.sort(key=lambda r: r["date"])
    return aggregates


def _read_aggregates_csv(path: Path) -> Optional[List[Dict[str, int]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            expected_headers = ["date", "total_checkins", "unique_kids", "avg_session_minutes"]
            if reader.fieldnames is None:
                return None
            if [h.strip() for h in reader.fieldnames] != expected_headers:
                return None
            rows: List[Dict[str, int]] = []
            for row in reader:
                try:
                    d = row["date"].strip()
                    tc = int(row["total_checkins"])
                    uk = int(row["unique_kids"])
                    av = int(row["avg_session_minutes"])
                    rows.append({
                        "date": d,
                        "total_checkins": tc,
                        "unique_kids": uk,
                        "avg_session_minutes": av
                    })
                except Exception:
                    return None
            return rows
    except Exception:
        return None


def _is_sorted_by_date(rows: List[Dict[str, int]]) -> bool:
    dates = [r["date"] for r in rows]
    return dates == sorted(dates)


def _count_total_csv_files_and_rows(logs_dir: Path) -> Tuple[int, Optional[int]]:
    csv_files = _list_csv_files(logs_dir)
    total_rows = 0
    for p in csv_files:
        try:
            with p.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header is None:
                    return (len(csv_files), None)
                count_in_file = 0
                for _ in reader:
                    count_in_file += 1
                total_rows += count_in_file
        except Exception:
            return (len(csv_files), None)
    return (len(csv_files), total_rows)


def _top3_busiest_days(aggregates: List[Dict[str, int]]) -> List[Dict[str, int]]:
    sorted_days = sorted(aggregates, key=lambda r: (-r["total_checkins"], -r["avg_session_minutes"], r["date"]))
    return sorted_days[:3]


def _deploy_script_references_venv_and_script(text: str) -> bool:
    if text is None:
        return False
    mentions_script = "scripts/aggregate.py" in text
    mentions_venv = (".venv/bin/python" in text) or ("source .venv" in text) or ("/.venv/" in text) or (".venv" in text)
    return mentions_script and mentions_venv


def _meeting_notes_contains_env_summary(notes: str, env: dict) -> bool:
    if notes is None or env is None:
        return False
    pyver = env.get("python_version")
    venv_path = env.get("venv_path")
    pip_freeze = env.get("pip_freeze")
    if not isinstance(pyver, str) or not pyver:
        return False
    if not isinstance(venv_path, str) or not venv_path:
        return False
    if not isinstance(pip_freeze, list):
        return False
    pkg_count = len(pip_freeze)
    cond_py = pyver in notes
    cond_venv = venv_path in notes or ".venv" in notes
    cond_pkg = str(pkg_count) in notes
    cond_agg_path = "output/aggregates.csv" in notes
    return cond_py, cond_venv, cond_pkg, cond_agg_path


def _meeting_notes_contains_data_summary(notes: str, csv_count: int, total_rows: Optional[int]) -> bool:
    if notes is None:
        return False
    if str(csv_count) not in notes:
        return False
    if total_rows is None:
        return False
    if str(total_rows) not in notes:
        return False
    return True


def _meeting_notes_lists_top3(notes: str, top3: List[Dict[str, int]]) -> bool:
    if notes is None:
        return False
    if not top3:
        return "busiest" in notes.lower()
    lines = notes.splitlines()
    for rec in top3:
        d = rec["date"]
        tc = str(rec["total_checkins"])
        av = str(rec["avg_session_minutes"])
        found = False
        for line in lines:
            if d in line and tc in line and av in line:
                found = True
                break
        if not found:
            return False
    return True


def _extract_action_items_section(notes: str) -> List[str]:
    lines = notes.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if "action items" in line.lower():
            idx = i
            break
    if idx is None:
        return lines
    section = []
    for j in range(idx + 1, len(lines)):
        section.append(lines[j])
    return section


def _line_has_owner_indicator(line: str) -> bool:
    lower = line.lower()
    if "owner" in lower:
        return True
    if re.search(r'@[A-Za-z][A-Za-z]+', line):
        return True
    if re.search(r'[-—–:]\s*[A-Z][a-z]+(?: [A-Z][a-z]+)?', line):
        return True
    if re.search(r'\(([A-Z][a-z]+(?: [A-Z][a-z]+)?)\)', line):
        return True
    return False


def _meeting_notes_action_items_with_owners(notes: str, top3: List[Dict[str, int]]) -> bool:
    if notes is None:
        return False
    if not top3:
        section_lines = _extract_action_items_section(notes)
        count = 0
        for line in section_lines:
            if _line_has_owner_indicator(line):
                count += 1
        return count >= 3
    dates = {rec["date"] for rec in top3}
    section_lines = _extract_action_items_section(notes)
    candidates = []
    for line in section_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r'^(\-|\*|\d+\.)\s+', stripped):
            candidates.append(stripped)
        else:
            if any(d in stripped for d in dates):
                candidates.append(stripped)
    count = 0
    seen_lines = set()
    for line in candidates:
        if line in seen_lines:
            continue
        if any(d in line for d in dates) and _line_has_owner_indicator(line):
            count += 1
            seen_lines.add(line)
    return count >= 3


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "env_report_present": 0.0,
        "env_report_fields_valid": 0.0,
        "venv_path_exists": 0.0,
        "aggregate_script_present": 0.0,
        "deploy_helper_references_venv_and_script": 0.0,
        "aggregates_csv_present_and_correct": 0.0,
        "aggregates_sorted_by_date": 0.0,
        "aggregates_uses_all_input_logs": 0.0,
        "meeting_notes_env_summary_present": 0.0,
        "meeting_notes_data_summary_present": 0.0,
        "meeting_notes_top3_busiest_listed": 0.0,
        "meeting_notes_action_items_with_owners": 0.0,
    }

    env_report_path = workspace / "build" / "env_report.json"
    aggregate_script_path = workspace / "scripts" / "aggregate.py"
    deploy_script_path = workspace / "deploy" / "run_aggregate.sh"
    output_aggregates_path = workspace / "output" / "aggregates.csv"
    logs_dir = workspace / "input" / "logs"
    meeting_notes_path = workspace / "MEETING_NOTES.md"

    expected_aggregates = _compute_expected_aggregates(logs_dir)
    csv_count, total_raw_rows = _count_total_csv_files_and_rows(logs_dir)
    top3_expected: List[Dict[str, int]] = []
    if expected_aggregates is not None:
        top3_expected = _top3_busiest_days(expected_aggregates)

    env_report = _safe_load_json(env_report_path) if env_report_path.exists() else None
    if env_report is not None:
        scores["env_report_present"] = 1.0
        pyver = env_report.get("python_version")
        venv_path_str = env_report.get("venv_path")
        pip_freeze = env_report.get("pip_freeze")
        fields_ok = (
            isinstance(pyver, str) and len(pyver) > 0 and
            isinstance(venv_path_str, str) and len(venv_path_str) > 0 and
            ".venv" in venv_path_str and
            isinstance(pip_freeze, list) and all(isinstance(x, str) for x in pip_freeze)
        )
        if fields_ok:
            scores["env_report_fields_valid"] = 1.0

        venv_path = None
        try:
            if isinstance(venv_path_str, str):
                venv_p = Path(venv_path_str)
                venv_path = venv_p if venv_p.is_absolute() else (workspace / venv_p)
        except Exception:
            venv_path = None
        if venv_path is not None and venv_path.exists() and venv_path.is_dir():
            scores["venv_path_exists"] = 1.0

    if aggregate_script_path.exists() and aggregate_script_path.is_file():
        scores["aggregate_script_present"] = 1.0

    deploy_text = _safe_read_text(deploy_script_path) if deploy_script_path.exists() else None
    if deploy_text is not None and _deploy_script_references_venv_and_script(deploy_text):
        scores["deploy_helper_references_venv_and_script"] = 1.0

    out_rows = _read_aggregates_csv(output_aggregates_path) if output_aggregates_path.exists() else None
    if expected_aggregates is not None and out_rows is not None:
        if out_rows == expected_aggregates:
            scores["aggregates_csv_present_and_correct"] = 1.0
        if _is_sorted_by_date(out_rows):
            scores["aggregates_sorted_by_date"] = 1.0
        if total_raw_rows is not None:
            if sum(r["total_checkins"] for r in out_rows) == total_raw_rows:
                scores["aggregates_uses_all_input_logs"] = 1.0

    notes_text = _safe_read_text(meeting_notes_path) if meeting_notes_path.exists() else None
    if notes_text is not None and env_report is not None:
        env_checks = _meeting_notes_contains_env_summary(notes_text, env_report)
        if isinstance(env_checks, tuple):
            if all(env_checks):
                scores["meeting_notes_env_summary_present"] = 1.0
        elif env_checks:
            scores["meeting_notes_env_summary_present"] = 1.0
    if notes_text is not None:
        if _meeting_notes_contains_data_summary(notes_text, csv_count, total_raw_rows):
            scores["meeting_notes_data_summary_present"] = 1.0
        if expected_aggregates is not None:
            if _meeting_notes_lists_top3(notes_text, top3_expected):
                scores["meeting_notes_top3_busiest_listed"] = 1.0
            if _meeting_notes_action_items_with_owners(notes_text, top3_expected):
                scores["meeting_notes_action_items_with_owners"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()