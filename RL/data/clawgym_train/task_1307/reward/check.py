import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        lines = []
        text = _read_text(path)
        if text is None:
            return None
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                return None
            if not isinstance(obj, dict):
                return None
            lines.append(obj)
        return lines
    except Exception:
        return None


def _parse_schedule_yaml(path: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Minimal parser for the provided simple YAML structure.
    Expects:
    runs:
      - id: run_a
        delay_seconds: 1
        cmd: "python scripts/train_run_a.py --out outputs/runs/run_a.json"
      - id: run_b
        delay_seconds: 1
        cmd: "python scripts/train_run_b.py --out outputs/runs/run_b.json"
    """
    text = _read_text(path)
    if text is None:
        return None
    runs: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if re.match(r"^\s*-\s+id\s*:\s*", line):
            # Start a new run
            m = re.search(r"id\s*:\s*([A-Za-z0-9_\-]+)", line)
            if not m:
                return None
            if current is not None:
                runs.append(current)
            current = {"id": m.group(1)}
        elif current is not None:
            m_delay = re.search(r"delay_seconds\s*:\s*([0-9]+)", line)
            if m_delay:
                try:
                    current["delay_seconds"] = int(m_delay.group(1))
                except Exception:
                    return None
            m_cmd = re.search(r"cmd\s*:\s*[\"']?(.*?)[\"']?\s*$", line)
            if "cmd:" in line and m_cmd:
                # Extract command string; handle quoted or unquoted
                cmd_part = line.split("cmd:", 1)[1].strip()
                # Remove surrounding quotes if present
                if (cmd_part.startswith('"') and cmd_part.endswith('"')) or (cmd_part.startswith("'") and cmd_part.endswith("'")):
                    cmd_part = cmd_part[1:-1]
                current["cmd"] = cmd_part
    if current is not None:
        runs.append(current)
    # Validate collected runs
    if not runs:
        return None
    for r in runs:
        if "id" not in r or "delay_seconds" not in r or "cmd" not in r:
            return None
    return runs


def _parse_iso8601(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str):
        return None
    s = ts.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
            return datetime.fromisoformat(s2)
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _extract_section(text: str, title: str) -> Optional[str]:
    """
    Extracts the section content under a heading matching the given title.
    Matches headings like '# Summary', '## Summary', etc.
    Returns the content lines joined by '\n' until the next heading or EOF.
    """
    lines = text.splitlines()
    start_idx = None
    title_pattern = re.compile(r"^\s*#{0,6}\s*" + re.escape(title) + r"\s*$", re.IGNORECASE)
    heading_pattern = re.compile(r"^\s*#{1,6}\s+.+$")
    for i, line in enumerate(lines):
        if title_pattern.match(line):
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    # Find next heading
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if heading_pattern.match(lines[j]):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def _load_csv_with_header(path: Path) -> Optional[Dict[str, Any]]:
    """
    Returns dict with keys: header (List[str]), rows (List[Dict[str,str]])
    Where rows are dictionaries mapping header names to string cell values.
    """
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = [row for row in reader]
            # Ensure all rows have all columns
            for row in rows:
                if set(row.keys()) != set(header):
                    return None
            return {"header": header, "rows": rows}
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "runner_py_exists": 0.0,
        "stdout_run_a_captured": 0.0,
        "stdout_run_b_captured": 0.0,
        "execution_log_valid": 0.0,
        "execution_log_matches_schedule": 0.0,
        "metrics_jsons_valid": 0.0,
        "metrics_csv_valid": 0.0,
        "meeting_notes_summary_correct": 0.0,
        "meeting_notes_action_items_sufficient": 0.0,
    }

    # Check runner.py existence
    if (workspace / "runner.py").is_file():
        scores["runner_py_exists"] = 1.0

    # Parse schedule.yaml for later comparisons
    schedule_path = workspace / "input" / "schedule.yaml"
    schedule = _parse_schedule_yaml(schedule_path)

    # Check stdout captures
    stdout_a_path = workspace / "outputs" / "logs" / "run_a.stdout"
    stdout_b_path = workspace / "outputs" / "logs" / "run_b.stdout"
    txt_a = _read_text(stdout_a_path)
    if txt_a is not None:
        # We expect evidence of launch and completion
        if ("Starting run_a" in txt_a) and ("Completed run_a" in txt_a):
            scores["stdout_run_a_captured"] = 1.0
    txt_b = _read_text(stdout_b_path)
    if txt_b is not None:
        if ("Starting run_b" in txt_b) and ("Completed run_b" in txt_b):
            scores["stdout_run_b_captured"] = 1.0

    # Check execution log
    exec_log_path = workspace / "outputs" / "executions" / "log.jsonl"
    exec_entries = _load_jsonl(exec_log_path)
    exec_log_valid = False
    if exec_entries is not None and len(exec_entries) == 2:
        valid = True
        for rec in exec_entries:
            # Required fields
            for key in ("id", "cmd", "start_time", "end_time", "exit_code"):
                if key not in rec:
                    valid = False
                    break
            if not valid:
                break
            # Types and values
            if not isinstance(rec["id"], str):
                valid = False
                break
            if not isinstance(rec["cmd"], str):
                valid = False
                break
            dt_start = _parse_iso8601(rec["start_time"])
            dt_end = _parse_iso8601(rec["end_time"])
            if dt_start is None or dt_end is None:
                valid = False
                break
            try:
                exit_code_ok = int(rec["exit_code"]) == 0
            except Exception:
                exit_code_ok = False
            if not exit_code_ok:
                valid = False
                break
            if dt_end < dt_start:
                valid = False
                break
        if valid:
            exec_log_valid = True
            scores["execution_log_valid"] = 1.0

    # Check execution log matches schedule (order and cmd)
    if exec_log_valid and schedule is not None:
        try:
            ok = True
            if len(schedule) != len(exec_entries):
                ok = False
            else:
                for i, r in enumerate(exec_entries):
                    if r.get("id") != schedule[i].get("id"):
                        ok = False
                        break
                    if r.get("cmd") != schedule[i].get("cmd"):
                        ok = False
                        break
            if ok:
                scores["execution_log_matches_schedule"] = 1.0
        except Exception:
            pass

    # Load metrics JSONs
    metrics: Dict[str, Dict[str, Any]] = {}
    all_metrics_ok = True
    for rid in ("run_a", "run_b"):
        mpath = workspace / "outputs" / "runs" / f"{rid}.json"
        data = _load_json(mpath)
        if data is None:
            all_metrics_ok = False
            break
        # Required keys and types
        required_keys = ["run_id", "seed", "epochs", "accuracy", "loss"]
        if not all(k in data for k in required_keys):
            all_metrics_ok = False
            break
        if data.get("run_id") != rid:
            all_metrics_ok = False
            break
        # Type checks
        try:
            seed_ok = isinstance(data["seed"], int)
            epochs_ok = isinstance(data["epochs"], int)
            acc_ok = isinstance(data["accuracy"], (int, float))
            loss_ok = isinstance(data["loss"], (int, float))
        except Exception:
            seed_ok = epochs_ok = acc_ok = loss_ok = False
        if not (seed_ok and epochs_ok and acc_ok and loss_ok):
            all_metrics_ok = False
            break
        metrics[rid] = {
            "run_id": data["run_id"],
            "seed": int(data["seed"]),
            "epochs": int(data["epochs"]),
            "accuracy": float(data["accuracy"]),
            "loss": float(data["loss"]),
        }
    if all_metrics_ok and len(metrics) == 2:
        scores["metrics_jsons_valid"] = 1.0

    # Validate metrics.csv
    csv_path = workspace / "outputs" / "summary" / "metrics.csv"
    csv_loaded = _load_csv_with_header(csv_path)
    if csv_loaded is not None and scores["metrics_jsons_valid"] == 1.0:
        header = csv_loaded["header"]
        rows = csv_loaded["rows"]
        expected_header = ["run_id", "seed", "accuracy", "loss", "epochs"]
        header_ok = header == expected_header
        # Build map from CSV
        csv_map: Dict[str, Dict[str, str]] = {}
        for row in rows:
            rid = row.get("run_id")
            if not rid:
                header_ok = False
                break
            if rid in csv_map:
                # duplicate run id
                header_ok = False
                break
            csv_map[rid] = row
        values_ok = True
        if header_ok and len(rows) == 2:
            for rid, m in metrics.items():
                row = csv_map.get(rid)
                if row is None:
                    values_ok = False
                    break
                # Compare values with types
                try:
                    seed_val = int(row["seed"])
                    epochs_val = int(row["epochs"])
                    acc_val = float(row["accuracy"])
                    loss_val = float(row["loss"])
                except Exception:
                    values_ok = False
                    break
                if seed_val != m["seed"] or epochs_val != m["epochs"]:
                    values_ok = False
                    break
                # Float comparison with tolerance
                if abs(acc_val - m["accuracy"]) > 1e-9 or abs(loss_val - m["loss"]) > 1e-9:
                    values_ok = False
                    break
        else:
            values_ok = False
        if header_ok and values_ok:
            scores["metrics_csv_valid"] = 1.0

    # Validate meeting notes: Summary section must include each run id and its exact accuracy and loss values
    notes_path = workspace / "outputs" / "meeting" / "notes.md"
    notes_text = _read_text(notes_path)
    if notes_text is not None and scores["metrics_jsons_valid"] == 1.0:
        summary_section = _extract_section(notes_text, "Summary")
        if summary_section:
            # For each run, look for a line containing run_id and both accuracy and loss numbers
            def _float_to_str(x: float) -> str:
                # Use Python's default str formatting for floats
                return str(x)

            summary_ok = True
            for rid, m in metrics.items():
                acc_str = _float_to_str(m["accuracy"])
                loss_str = _float_to_str(m["loss"])
                found_line = False
                for line in summary_section.splitlines():
                    if (rid in line) and (acc_str in line) and (loss_str in line):
                        found_line = True
                        break
                if not found_line:
                    summary_ok = False
                    break
            if summary_ok:
                scores["meeting_notes_summary_correct"] = 1.0

        # Validate Action Items section: at least three bullet points referencing run_a and/or run_b
        action_section = _extract_section(notes_text, "Action Items")
        if action_section:
            bullets = []
            for line in action_section.splitlines():
                if re.match(r"^\s*[-*]\s+.+", line):
                    bullets.append(line.strip())
            # Require at least three bullets and each references run_a or run_b
            if len(bullets) >= 3:
                ref_count = 0
                for b in bullets:
                    if ("run_a" in b) or ("run_b" in b):
                        ref_count += 1
                # All three must reference a run id
                if ref_count >= 3:
                    scores["meeting_notes_action_items_sufficient"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()