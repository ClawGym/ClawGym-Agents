import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _parse_csv_column_floats(p: Path, column: str) -> Optional[List[float]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or column not in reader.fieldnames:
                return None
            vals: List[float] = []
            for row in reader:
                if column not in row:
                    return None
                v = row[column]
                if v is None or str(v).strip() == "":
                    return None
                try:
                    vals.append(float(str(v).strip()))
                except Exception:
                    return None
            if not vals:
                return None
            return vals
    except Exception:
        return None


def _format_one_decimal(x: float) -> str:
    return f"{x:.1f}"


def _load_single_row_csv(p: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = [r for r in reader]
        non_empty_rows = [r for r in rows if any((cell or "").strip() for cell in r)]
        if not non_empty_rows:
            return None
        header = non_empty_rows[0]
        data_rows = non_empty_rows[1:]
        return header, data_rows
    except Exception:
        return None


def _compute_expected_metrics(workspace: Path, target_date: str) -> Optional[dict]:
    seismic_path = workspace / f"data/raw/seismic_{target_date}.csv"
    gas_path = workspace / f"data/raw/gas_{target_date}.csv"
    rsam_vals = _parse_csv_column_floats(seismic_path, "rsam")
    so2_vals = _parse_csv_column_floats(gas_path, "so2_tpd")
    if rsam_vals is None or so2_vals is None:
        return None
    rsam_mean = sum(rsam_vals) / len(rsam_vals)
    rsam_max = max(rsam_vals)
    so2_mean = sum(so2_vals) / len(so2_vals)
    so2_max = max(so2_vals)
    rsam_mean_s = _format_one_decimal(rsam_mean)
    rsam_max_s = _format_one_decimal(rsam_max)
    so2_mean_s = _format_one_decimal(so2_mean)
    so2_max_s = _format_one_decimal(so2_max)
    alert = "Elevated" if (float(rsam_mean_s) >= 160.0 or float(so2_mean_s) >= 450.0) else "Normal"
    return {
        "date": target_date,
        "rsam_mean": rsam_mean_s,
        "rsam_max": rsam_max_s,
        "so2_mean_tpd": so2_mean_s,
        "so2_max_tpd": so2_max_s,
        "alert_status": alert,
    }


def _cron_line_valid(cron_text: str) -> bool:
    lines = [ln.rstrip("\n") for ln in cron_text.splitlines()]
    first_line = None
    for ln in lines:
        if not ln.strip():
            continue
        if ln.strip().startswith("#"):
            continue
        first_line = ln
        break
    if not first_line:
        return False
    if not first_line.strip().startswith("15 6 * * *"):
        return False
    if "scripts/daily_ingest.sh" not in first_line:
        return False
    if "logs/daily_ingest.log" not in first_line:
        return False
    if ">>" not in first_line or "2>&1" not in first_line:
        return False
    try:
        before_redirect, _ = first_line.split(">>", 1)
        idx = before_redirect.rfind("scripts/daily_ingest.sh")
        if idx == -1:
            return False
        after_script = before_redirect[idx + len("scripts/daily_ingest.sh") :]
        if after_script.strip() != "":
            return False
    except ValueError:
        return False
    return True


def _contains_all(text: str, terms: List[str], case_insensitive: bool = True) -> bool:
    t = text if not case_insensitive else text.lower()
    for term in terms:
        tt = term if not case_insensitive else term.lower()
        if tt not in t:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "script_references_paths_and_outputs": 0.0,
        "script_accepts_optional_date_default_yesterday": 0.0,
        "cron_config_valid": 0.0,
        "processed_metrics_csv_structure_and_values": 0.0,
        "daily_status_md_contains_date_status_and_labeled_metrics": 0.0,
        "weekly_report_bullet_correct_position_and_format": 0.0,
        "data_processed_dir_present": 0.0,
        "reports_dir_present": 0.0,
        "logs_dir_present": 0.0,
    }

    target_date = "2025-04-14"
    expected = _compute_expected_metrics(workspace, target_date)

    script_path = workspace / "scripts/daily_ingest.sh"
    if script_path.exists() and script_path.is_file():
        content = _read_text(script_path) or ""
        if content.strip():
            scores["script_present"] = 1.0
        refs_ok = True
        if ("data/raw/seismic_" not in content) or ("data/raw/gas_" not in content):
            refs_ok = False
        if ("data/processed" not in content) or ("reports" not in content):
            refs_ok = False
        if ("docs/Weekly_Report.md" not in content) or ("AUTO-DAILY-SUMMARIES" not in content):
            refs_ok = False
        if "logs" not in content:
            refs_ok = False
        scores["script_references_paths_and_outputs"] = 1.0 if refs_ok else 0.0

        lc = content.lower()
        uses_arg = "$1" in content or re.search(r"\bargs?\b", lc) is not None
        has_yesterday = "yesterday" in lc or re.search(r"date\s+-d", lc) is not None
        logic_ok = bool(uses_arg and has_yesterday)
        scores["script_accepts_optional_date_default_yesterday"] = 1.0 if logic_ok else 0.0
    else:
        scores["script_present"] = 0.0
        scores["script_references_paths_and_outputs"] = 0.0
        scores["script_accepts_optional_date_default_yesterday"] = 0.0

    cron_path = workspace / "scheduler/volcano_daily.cron"
    cron_text = _read_text(cron_path) if cron_path.exists() else None
    if cron_text is not None and _cron_line_valid(cron_text):
        scores["cron_config_valid"] = 1.0
    else:
        scores["cron_config_valid"] = 0.0

    processed_path = workspace / f"data/processed/daily_metrics_{target_date}.csv"
    expected_header = ["date", "rsam_mean", "rsam_max", "so2_mean_tpd", "so2_max_tpd", "alert_status"]
    loaded = _load_single_row_csv(processed_path) if processed_path.exists() else None
    metrics_ok = False
    if loaded is not None and expected is not None:
        header, data_rows = loaded
        if header == expected_header and len(data_rows) == 1 and len(data_rows[0]) == 6:
            row = data_rows[0]
            expected_row = [
                expected["date"],
                expected["rsam_mean"],
                expected["rsam_max"],
                expected["so2_mean_tpd"],
                expected["so2_max_tpd"],
                expected["alert_status"],
            ]
            if row == expected_row:
                metrics_ok = True
    scores["processed_metrics_csv_structure_and_values"] = 1.0 if metrics_ok else 0.0

    daily_md_path = workspace / f"reports/daily_status_{target_date}.md"
    daily_text = _read_text(daily_md_path) if daily_md_path.exists() else None
    daily_ok = False
    if daily_text is not None and expected is not None:
        has_date = target_date in daily_text
        has_status = expected["alert_status"] in daily_text
        labels_set1 = ["rsam_mean", "rsam_max", "so2_mean_tpd", "so2_max_tpd"]
        labels_set2 = ["RSAM mean", "RSAM max", "SO2 mean", "SO2 max"]
        labels_present = _contains_all(daily_text, labels_set1, True) or _contains_all(daily_text, labels_set2, True)
        nums_present = all(
            v in daily_text for v in [expected["rsam_mean"], expected["rsam_max"], expected["so2_mean_tpd"], expected["so2_max_tpd"]]
        )
        if has_date and has_status and labels_present and nums_present:
            daily_ok = True
    scores["daily_status_md_contains_date_status_and_labeled_metrics"] = 1.0 if daily_ok else 0.0

    weekly_path = workspace / "docs/Weekly_Report.md"
    weekly_text = _read_text(weekly_path) if weekly_path.exists() else None
    bullet_ok = False
    if weekly_text is not None and expected is not None:
        lines = [ln.rstrip("\n") for ln in weekly_text.splitlines()]
        marker = "<!-- AUTO-DAILY-SUMMARIES: latest first -->"
        expected_bullet = f"- {target_date} — {expected['alert_status']}; RSAM mean {expected['rsam_mean']}, SO2 mean {expected['so2_mean_tpd']}"
        try:
            idx = lines.index(marker)
            if idx + 1 < len(lines) and lines[idx + 1].strip() == expected_bullet:
                bullet_ok = True
        except ValueError:
            bullet_ok = False
    scores["weekly_report_bullet_correct_position_and_format"] = 1.0 if bullet_ok else 0.0

    scores["data_processed_dir_present"] = 1.0 if (workspace / "data/processed").exists() and (workspace / "data/processed").is_dir() else 0.0
    scores["reports_dir_present"] = 1.0 if (workspace / "reports").exists() and (workspace / "reports").is_dir() else 0.0
    scores["logs_dir_present"] = 1.0 if (workspace / "logs").exists() and (workspace / "logs").is_dir() else 0.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()