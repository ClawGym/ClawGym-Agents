import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional, Dict, Any, List


def safe_load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        if not path.exists():
            return None, f"missing:{path}"
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"error:{e}"


def safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        if not path.exists():
            return None, f"missing:{path}"
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, f"error:{e}"


def parse_week_from_filename(name: str) -> Optional[Tuple[datetime, datetime]]:
    m = re.match(r"log_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$", name)
    if not m:
        return None
    try:
        start = datetime.strptime(m.group(1), "%Y-%m-%d")
        end = datetime.strptime(m.group(2), "%Y-%m-%d")
        return start, end
    except Exception:
        return None


def read_week_csv(path: Path) -> Tuple[Optional[List[dict]], Optional[str]]:
    try:
        if not path.exists():
            return None, f"missing:{path}"
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                try:
                    _ = datetime.strptime(row["date"], "%Y-%m-%d")
                    row["tremor_score"] = float(row["tremor_score"])
                    row["mobility_minutes"] = float(row["mobility_minutes"])
                    row["sleep_hours"] = float(row["sleep_hours"])
                    row["therapy"] = (row.get("therapy") or "").strip()
                except Exception as e:
                    return None, f"parse_error:{e}"
                rows.append(row)
            if not rows:
                return None, "empty_csv"
            return rows, None
    except Exception as e:
        return None, f"error:{e}"


def compute_week_stats(rows: List[dict]) -> Dict[str, Any]:
    tremors = [r["tremor_score"] for r in rows]
    mobility = [r["mobility_minutes"] for r in rows]
    sleep = [r["sleep_hours"] for r in rows]
    therapies: Dict[str, int] = {}
    for r in rows:
        t = r.get("therapy", "")
        therapies[t] = therapies.get(t, 0) + 1
    avg_tremor = sum(tremors) / len(tremors) if tremors else 0.0
    avg_mob = sum(mobility) / len(mobility) if mobility else 0.0
    avg_sleep = sum(sleep) / len(sleep) if sleep else 0.0
    return {
        "avg_tremor_score": avg_tremor,
        "avg_mobility_minutes": avg_mob,
        "avg_sleep_hours": avg_sleep,
        "therapy_counts": therapies,
    }


def round2(x: float) -> float:
    return float(f"{x:.2f}")


def find_previous_week_file(incoming_dir: Path, current_start: datetime) -> Optional[Path]:
    candidates = []
    if not incoming_dir.exists():
        return None
    for p in incoming_dir.glob("log_*.csv"):
        parsed = parse_week_from_filename(p.name)
        if parsed is None:
            continue
        start, _ = parsed
        if start < current_start:
            candidates.append((start, p))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def extract_line_startswith(lines: List[str], prefix: str) -> Optional[str]:
    for line in lines:
        if line.strip().startswith(prefix):
            return line.strip()
    return None


def ensure_two_decimal_representation(val: Any) -> Optional[str]:
    if val is None:
        return None
    try:
        f = float(val)
        return f"{f:.2f}"
    except Exception:
        return None


def decide_recipient_and_keyword(tremor_change: Optional[float], mobility_pct_change: Optional[float], contacts: Optional[dict]) -> Tuple[Optional[str], Optional[str]]:
    if contacts is None:
        return None, None
    if tremor_change is None or mobility_pct_change is None:
        return contacts.get("support_group", {}).get("email"), "Update"
    if tremor_change <= -0.50 or mobility_pct_change >= 15.00:
        return contacts.get("integrative_clinic", {}).get("email"), "Improvement"
    elif tremor_change >= 0.50 or mobility_pct_change <= -15.00:
        return contacts.get("neurologist", {}).get("email"), "Concern"
    else:
        return contacts.get("support_group", {}).get("email"), "Update"


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_file_exists": 0.0,
        "metrics_fields_present": 0.0,
        "metrics_values_correct": 0.0,
        "metrics_values_rounded_two_decimals": 0.0,
        "therapy_counts_correct": 0.0,
        "changes_values_correct": 0.0,
        "email_file_exists": 0.0,
        "email_to_recipient_correct": 0.0,
        "email_subject_contains_required": 0.0,
        "email_contains_metrics_numbers": 0.0,
        "email_therapy_counts_listed": 0.0,
        "email_closing_names_present": 0.0,
        "processed_json_updated": 0.0,
        "processed_json_retains_prior": 0.0,
    }

    incoming_dir = workspace / "input" / "incoming"
    target_csv_rel = "input/incoming/log_2024-04-08_2024-04-14.csv"
    target_csv_path = workspace / target_csv_rel
    base_name = "log_2024-04-08_2024-04-14"
    metrics_path = workspace / "output" / "metrics" / f"{base_name}.json"
    email_path = workspace / "output" / "email_drafts" / f"{base_name}.txt"
    contacts_path = workspace / "input" / "contacts.json"
    processed_path = workspace / "state" / "processed.json"

    contacts, _ = safe_load_json(contacts_path)
    caregiver_name = contacts.get("caregiver_name") if contacts else None
    loved_one_name = contacts.get("loved_one_name") if contacts else None

    expected_stats_ok = False
    expected: Dict[str, Any] = {}
    expected_recipient_email: Optional[str] = None
    expected_subject_keyword: Optional[str] = None

    if target_csv_path.exists():
        rows_current, err_current = read_week_csv(target_csv_path)
        if not err_current and rows_current:
            current_stats = compute_week_stats(rows_current)
            parsed_target = parse_week_from_filename(target_csv_path.name)
            prev_path = None
            if parsed_target:
                current_start, _ = parsed_target
                prev_path = find_previous_week_file(incoming_dir, current_start)
            prev_stats = None
            if prev_path and prev_path.exists():
                rows_prev, err_prev = read_week_csv(prev_path)
                if not err_prev and rows_prev:
                    prev_stats = compute_week_stats(rows_prev)
            avg_tremor = round2(current_stats["avg_tremor_score"])
            avg_mob = round2(current_stats["avg_mobility_minutes"])
            avg_sleep = round2(current_stats["avg_sleep_hours"])
            tremor_change = None
            mobility_pct_change = None
            if prev_stats is not None:
                tremor_change = round2(current_stats["avg_tremor_score"] - prev_stats["avg_tremor_score"])
                if prev_stats["avg_mobility_minutes"] != 0:
                    mobility_pct_change = round2(((current_stats["avg_mobility_minutes"] - prev_stats["avg_mobility_minutes"]) / prev_stats["avg_mobility_minutes"]) * 100.0)
                else:
                    mobility_pct_change = None
            expected = {
                "week_start": target_csv_path.name.split("_")[1],
                "week_end": target_csv_path.name.split("_")[2].replace(".csv", ""),
                "avg_tremor_score": avg_tremor,
                "avg_mobility_minutes": avg_mob,
                "avg_sleep_hours": avg_sleep,
                "tremor_change": tremor_change,
                "mobility_pct_change": mobility_pct_change,
                "therapy_counts": current_stats["therapy_counts"],
            }
            expected_recipient_email, expected_subject_keyword = decide_recipient_and_keyword(tremor_change, mobility_pct_change, contacts)
            expected_stats_ok = True

    if metrics_path.exists():
        scores["metrics_file_exists"] = 1.0

    produced_metrics, _ = safe_load_json(metrics_path) if metrics_path.exists() else (None, "missing")

    required_fields = [
        "week_start",
        "week_end",
        "avg_tremor_score",
        "avg_mobility_minutes",
        "avg_sleep_hours",
        "tremor_change",
        "mobility_pct_change",
        "therapy_counts",
    ]
    if produced_metrics and isinstance(produced_metrics, dict):
        if all(k in produced_metrics for k in required_fields) and isinstance(produced_metrics.get("therapy_counts"), dict):
            scores["metrics_fields_present"] = 1.0

    if produced_metrics and expected_stats_ok:
        values_ok = True
        rounding_ok = True
        try:
            if produced_metrics.get("week_start") != expected.get("week_start"):
                values_ok = False
            if produced_metrics.get("week_end") != expected.get("week_end"):
                values_ok = False

            for key in ["avg_tremor_score", "avg_mobility_minutes", "avg_sleep_hours"]:
                val = produced_metrics.get(key)
                exp_val = expected.get(key)
                if not isinstance(val, (int, float)):
                    values_ok = False
                    rounding_ok = False
                    break
                if abs(float(val) - float(exp_val)) > 1e-6:
                    values_ok = False
                if abs(float(val) - round(float(val), 2)) > 1e-9:
                    rounding_ok = False

            for key in ["tremor_change", "mobility_pct_change"]:
                val = produced_metrics.get(key)
                exp = expected.get(key)
                if exp is None:
                    if val is not None:
                        values_ok = False
                else:
                    if not isinstance(val, (int, float)):
                        values_ok = False
                        rounding_ok = False
                    else:
                        if abs(float(val) - float(exp)) > 1e-6:
                            values_ok = False
                        if abs(float(val) - round(float(val), 2)) > 1e-9:
                            rounding_ok = False
        except Exception:
            values_ok = False
            rounding_ok = False

        if values_ok:
            scores["metrics_values_correct"] = 1.0
        if rounding_ok:
            scores["metrics_values_rounded_two_decimals"] = 1.0

        tc_ok = isinstance(produced_metrics.get("therapy_counts"), dict) and produced_metrics.get("therapy_counts") == expected.get("therapy_counts")
        scores["therapy_counts_correct"] = 1.0 if tc_ok else 0.0

        ch_ok = True
        for key in ["tremor_change", "mobility_pct_change"]:
            exp = expected.get(key)
            val = produced_metrics.get(key)
            if exp is None:
                if val is not None:
                    ch_ok = False
            else:
                if not isinstance(val, (int, float)) or abs(float(val) - float(exp)) > 1e-6:
                    ch_ok = False
        scores["changes_values_correct"] = 1.0 if ch_ok else 0.0

    if email_path.exists():
        scores["email_file_exists"] = 1.0

    email_text, _ = safe_read_text(email_path) if email_path.exists() else (None, "missing")
    if email_text:
        lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        to_line = extract_line_startswith(lines, "To:")
        subject_line = extract_line_startswith(lines, "Subject:")

        to_ok = False
        if to_line and expected_recipient_email:
            to_value = to_line.split("To:", 1)[1].strip()
            if to_value == expected_recipient_email:
                to_ok = True
        scores["email_to_recipient_correct"] = 1.0 if to_ok else 0.0

        subj_ok = False
        if subject_line and loved_one_name and expected_subject_keyword:
            subj = subject_line.split("Subject:", 1)[1]
            has_name = loved_one_name in subj
            has_dates = ("2024-04-08" in subj) and ("2024-04-14" in subj)
            has_keyword = expected_subject_keyword in subj
            subj_ok = bool(has_name and has_dates and has_keyword)
        scores["email_subject_contains_required"] = 1.0 if subj_ok else 0.0

        numbers_ok = False
        if produced_metrics:
            nums_required: List[str] = []
            for k in ["avg_tremor_score", "avg_mobility_minutes", "avg_sleep_hours", "tremor_change", "mobility_pct_change"]:
                val = produced_metrics.get(k)
                if val is None:
                    continue
                fmt = ensure_two_decimal_representation(val)
                if fmt:
                    nums_required.append(fmt)
            present_all = True
            for s in nums_required:
                if s not in email_text:
                    present_all = False
                    break
            numbers_ok = present_all
        scores["email_contains_metrics_numbers"] = 1.0 if numbers_ok else 0.0

        therapy_listed_ok = False
        if produced_metrics and isinstance(produced_metrics.get("therapy_counts"), dict):
            tc = produced_metrics["therapy_counts"]
            all_found = True
            for name, count in tc.items():
                count_str = str(count)
                found_for_this = False
                for ln in lines:
                    if name in ln and count_str in ln:
                        found_for_this = True
                        break
                if not found_for_this:
                    all_found = False
                    break
            therapy_listed_ok = all_found
        scores["email_therapy_counts_listed"] = 1.0 if therapy_listed_ok else 0.0

        closing_ok = False
        if caregiver_name and loved_one_name:
            closing_ok = (caregiver_name in email_text) and (loved_one_name in email_text)
        scores["email_closing_names_present"] = 1.0 if closing_ok else 0.0

    processed_data, _ = safe_load_json(processed_path)
    if processed_data and isinstance(processed_data.get("processed"), list):
        proc_list = processed_data.get("processed")
        has_new = target_csv_rel in proc_list
        has_prior = "input/incoming/log_2024-04-01_2024-04-07.csv" in proc_list
        if has_new:
            scores["processed_json_updated"] = 1.0
        if has_new and has_prior:
            scores["processed_json_retains_prior"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()