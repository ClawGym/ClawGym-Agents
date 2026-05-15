import csv
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def safe_read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            return [row for row in reader]
    except Exception:
        return None


def safe_read_csv_header_and_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def _format_pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        pct = 0.0
    else:
        pct = (numerator / denominator) * 100.0
    return f"{pct:.2f}"


def _compute_expected_from_data(data_rows: List[Dict[str, str]], region_filter: str) -> Dict[str, List[List[str]]]:
    # Filter by region
    filtered = [r for r in data_rows if r.get("region") == region_filter]

    # Monthly summary: month, total, oppose, pct
    monthly_counts: Dict[str, Dict[str, int]] = {}
    for r in filtered:
        date = r.get("date", "")
        if len(date) >= 7:
            month = date[:7]
        else:
            continue
        if month not in monthly_counts:
            monthly_counts[month] = {"total": 0, "oppose": 0}
        monthly_counts[month]["total"] += 1
        if r.get("stance") == "oppose_change":
            monthly_counts[month]["oppose"] += 1
    months_sorted = sorted(monthly_counts.keys())
    expected_monthly_rows: List[List[str]] = []
    for m in months_sorted:
        total = monthly_counts[m]["total"]
        oppose = monthly_counts[m]["oppose"]
        pct = _format_pct(oppose, total)
        expected_monthly_rows.append([m, str(total), str(oppose), pct])

    # Channel breakdown: sort by total desc, then channel asc for determinism
    channel_counts: Dict[str, Dict[str, int]] = {}
    for r in filtered:
        ch = r.get("channel", "")
        if ch not in channel_counts:
            channel_counts[ch] = {"total": 0, "oppose": 0}
        channel_counts[ch]["total"] += 1
        if r.get("stance") == "oppose_change":
            channel_counts[ch]["oppose"] += 1
    channels_sorted = sorted(channel_counts.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
    expected_channel_rows: List[List[str]] = []
    for ch, counts in channels_sorted:
        total = counts["total"]
        oppose = counts["oppose"]
        pct = _format_pct(oppose, total)
        expected_channel_rows.append([ch, str(total), str(oppose), pct])

    # Top 3 ZIPs: sort by total desc; ties by ZIP numeric asc
    zip_counts: Dict[str, Dict[str, int]] = {}
    for r in filtered:
        z = r.get("zip", "")
        if z not in zip_counts:
            zip_counts[z] = {"total": 0, "oppose": 0}
        zip_counts[z]["total"] += 1
        if r.get("stance") == "oppose_change":
            zip_counts[z]["oppose"] += 1

    def zip_sort_key(item):
        z, counts = item
        try:
            znum = int(z)
        except Exception:
            znum = float("inf")
        return (-counts["total"], znum)

    zips_sorted = sorted(zip_counts.items(), key=zip_sort_key)
    top3 = zips_sorted[:3]
    expected_zip_rows: List[List[str]] = []
    for z, counts in top3:
        total = counts["total"]
        oppose = counts["oppose"]
        pct = _format_pct(oppose, total)
        expected_zip_rows.append([z, str(total), str(oppose), pct])

    return {
        "monthly": expected_monthly_rows,
        "channel": expected_channel_rows,
        "zip": expected_zip_rows,
    }


def _compare_csv_exact(path: Path, expected_header: List[str], expected_rows: List[List[str]]) -> bool:
    header, rows = safe_read_csv_header_and_rows(path)
    if header is None or rows is None:
        return False
    if header != expected_header:
        return False
    if len(rows) != len(expected_rows):
        return False
    for i, row in enumerate(rows):
        if row != expected_rows[i]:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_region_and_policy_updated": 0.0,
        "config_output_paths_updated": 0.0,
        "summary_csv_correct": 0.0,
        "channel_csv_correct": 0.0,
        "zip_csv_correct": 0.0,
        "config_snapshot_correct": 0.0,
        "script_updates_reflect_requirements": 0.0,
    }

    # Check updated config values
    cfg_path = workspace / "config" / "newsletter_config.json"
    cfg = safe_load_json(cfg_path)
    if isinstance(cfg, dict):
        if cfg.get("region_filter") == "Middle East" and cfg.get("policy_position") == "No policy changes in the Middle East":
            scores["config_region_and_policy_updated"] = 1.0
        if (
            cfg.get("summary_path") == "output/middle_east_summary.csv"
            and cfg.get("channel_path") == "output/middle_east_by_channel.csv"
            and cfg.get("zip_path") == "output/middle_east_top_zips.csv"
        ):
            scores["config_output_paths_updated"] = 1.0

    # Compute expected outputs from provided data
    data_path = workspace / "input" / "data" / "constituent_contacts.csv"
    data_rows = safe_read_csv_rows(data_path)
    expected = None
    if data_rows is not None:
        expected = _compute_expected_from_data(data_rows, "Middle East")

    # Validate summary CSV
    summary_path = workspace / "output" / "middle_east_summary.csv"
    expected_summary_header = ["month", "total_contacts", "oppose_contacts", "oppose_pct"]
    if expected is not None and summary_path.exists():
        if _compare_csv_exact(summary_path, expected_summary_header, expected["monthly"]):
            scores["summary_csv_correct"] = 1.0

    # Validate channel CSV
    channel_path = workspace / "output" / "middle_east_by_channel.csv"
    expected_channel_header = ["channel", "total_contacts", "oppose_contacts", "oppose_pct"]
    if expected is not None and channel_path.exists():
        if _compare_csv_exact(channel_path, expected_channel_header, expected["channel"]):
            scores["channel_csv_correct"] = 1.0

    # Validate ZIP CSV
    zip_path = workspace / "output" / "middle_east_top_zips.csv"
    expected_zip_header = ["zip", "total_contacts", "oppose_contacts", "oppose_pct"]
    if expected is not None and zip_path.exists():
        if _compare_csv_exact(zip_path, expected_zip_header, expected["zip"]):
            scores["zip_csv_correct"] = 1.0

    # Validate config snapshot JSON
    snapshot_path = workspace / "output" / "config_snapshot.json"
    snapshot = safe_load_json(snapshot_path)
    if isinstance(snapshot, dict):
        if set(snapshot.keys()) == {"region_filter", "policy_position"}:
            if (
                snapshot.get("region_filter") == "Middle East"
                and snapshot.get("policy_position") == "No policy changes in the Middle East"
            ):
                scores["config_snapshot_correct"] = 1.0

    # Script content checks for required updates (avoid awarding for pre-existing baseline)
    script_path = workspace / "scripts" / "report_script.py"
    try:
        script_text = script_path.read_text(encoding="utf-8")
    except Exception:
        script_text = None
    if script_text:
        required_snippets = [
            "input/data/constituent_contacts.csv",  # must still use the fixed input path
            "channel_path",                         # new channel output
            "zip_path",                             # new zip output
            "config_snapshot",                      # write config snapshot
            "oppose_change",                        # compute opposition
            "oppose_pct",                           # compute percent for outputs
        ]
        if all(snippet in script_text for snippet in required_snippets):
            scores["script_updates_reflect_requirements"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()