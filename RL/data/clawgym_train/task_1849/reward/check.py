import json
import csv
import sys
import re
from pathlib import Path
from typing import Tuple, List, Dict, Any


def _read_text(path: Path) -> Tuple[str, str]:
    try:
        return path.read_text(encoding="utf-8"), ""
    except Exception as e:
        return "", f"read_error:{e}"


def _load_json_array(path: Path) -> Tuple[List[dict], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data, ""
        return [], "not_list"
    except Exception as e:
        return [], f"json_error:{e}"


def _load_jsonl_objects(path: Path) -> Tuple[List[dict], str]:
    if not path.exists():
        return [], "missing"
    items = []
    try:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                return [], f"jsonl_line_not_object:{i}"
            items.append(obj)
        return items, ""
    except Exception as e:
        return [], f"jsonl_error:{e}"


def _prepare_new_shot(item: dict) -> dict:
    id_ = item["id"]
    title = item["title"]
    capture_date = item["capture_date"]
    duration_sec = int(item["duration_sec"])
    duration_min = round(duration_sec / 60.0, 1)
    tags = sorted(list(item.get("tags", [])))
    camera = item["camera"]
    location = item["location"]
    notes = str(item.get("notes", "")).strip()
    return {
        "id": id_,
        "title": title,
        "capture_date": capture_date,
        "duration_sec": duration_sec,
        "duration_min": duration_min,
        "tags": tags,
        "camera": camera,
        "location": location,
        "notes": notes,
    }


def _compute_expected(master: List[dict], incoming: List[dict]) -> Dict[str, Any]:
    master_ids = {m.get("id") for m in master if isinstance(m, dict) and "id" in m}
    skipped_duplicates = 0
    for obj in incoming:
        if isinstance(obj, dict) and "id" in obj and obj["id"] in master_ids:
            skipped_duplicates += 1

    seen_new_ids = set()
    new_shots_raw = []
    for obj in incoming:
        if not isinstance(obj, dict) or "id" not in obj:
            continue
        if obj["id"] in master_ids:
            continue
        if obj["id"] in seen_new_ids:
            continue
        seen_new_ids.add(obj["id"])
        new_shots_raw.append(obj)

    new_shots_prepared = []
    try:
        for obj in new_shots_raw:
            new_shots_prepared.append(_prepare_new_shot(obj))
    except Exception:
        new_shots_prepared = []

    new_shots_sorted = sorted(new_shots_prepared, key=lambda x: x.get("capture_date", ""))

    expected_new_json = new_shots_sorted

    header = ["id", "title", "capture_date", "duration_sec", "duration_min", "tags", "camera", "location"]
    expected_csv_rows = []
    for item in new_shots_sorted:
        tags_joined = "|".join(item.get("tags", []))
        row = [
            item["id"],
            item["title"],
            item["capture_date"],
            str(int(item["duration_sec"])),
            f"{float(item['duration_min']):.1f}",
            tags_joined,
            item["camera"],
            item["location"],
        ]
        expected_csv_rows.append(row)

    new_count = len(new_shots_sorted)
    total_minutes = round(sum(float(i["duration_min"]) for i in new_shots_sorted), 1) if new_shots_sorted else 0.0
    if new_shots_sorted:
        dates = [i["capture_date"] for i in new_shots_sorted]
        date_earliest = min(dates)
        date_latest = max(dates)
    else:
        date_earliest = ""
        date_latest = ""

    tag_counts: Dict[str, int] = {}
    for item in new_shots_sorted:
        for t in item.get("tags", []):
            tag_counts[t] = tag_counts.get(t, 0) + 1
    tag_freq_sorted = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))

    details = [
        {
            "id": i["id"],
            "title": i["title"],
            "capture_date": i["capture_date"],
            "duration_min": f"{float(i['duration_min']):.1f}",
        }
        for i in new_shots_sorted
    ]

    id_list_ordered = ", ".join([i["id"] for i in new_shots_sorted])

    merged_by_id: Dict[str, dict] = {}
    for m in master:
        if isinstance(m, dict) and "id" in m:
            merged_by_id[m["id"]] = m
    for item in new_shots_prepared:
        merged_by_id[item["id"]] = {
            "id": item["id"],
            "title": item["title"],
            "capture_date": item["capture_date"],
            "duration_sec": item["duration_sec"],
            "tags": item["tags"],
            "camera": item["camera"],
            "location": item["location"],
            "notes": item["notes"],
        }
    merged_list = list(merged_by_id.values())
    merged_sorted = sorted(merged_list, key=lambda x: x.get("capture_date", ""))

    return {
        "expected_new_json": expected_new_json,
        "expected_csv_header": header,
        "expected_csv_rows": expected_csv_rows,
        "report_new_count": new_count,
        "report_skipped_duplicates": skipped_duplicates,
        "report_total_minutes": total_minutes,
        "report_date_earliest": date_earliest,
        "report_date_latest": date_latest,
        "report_tag_freq_sorted": tag_freq_sorted,
        "report_details": details,
        "revised_update_new_count": new_count,
        "revised_update_total_minutes": total_minutes,
        "revised_update_id_list": id_list_ordered,
        "expected_updated_master": merged_sorted,
    }


def _load_inputs(workspace: Path) -> Tuple[List[dict], List[dict], str]:
    master_path = workspace / "input" / "catalog" / "master_catalog.json"
    incoming_path = workspace / "input" / "incoming" / "new_shots.jsonl"

    master, err_m = _load_json_array(master_path)
    incoming, err_i = _load_jsonl_objects(incoming_path)

    if err_m or err_i:
        return [], [], f"{err_m}|{err_i}".strip("|")
    return master, incoming, ""


def _compare_json(a: Any, b: Any) -> bool:
    return a == b


def _read_csv_rows(path: Path) -> Tuple[List[str], List[List[str]], str]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return [], [], "empty"
        header = rows[0]
        data_rows = rows[1:]
        return header, data_rows, ""
    except Exception as e:
        return [], [], f"csv_error:{e}"


def _check_new_json(workspace: Path, expected: List[dict]) -> float:
    out_path = workspace / "output" / "ingest" / "new_shots_catalog.json"
    if not out_path.exists():
        return 0.0
    try:
        actual = json.loads(out_path.read_text(encoding="utf-8"))
        if not isinstance(actual, list):
            return 0.0
        if _compare_json(actual, expected):
            return 1.0
        return 0.0
    except Exception:
        return 0.0


def _check_new_csv(workspace: Path, header_expected: List[str], rows_expected: List[List[str]]) -> float:
    out_path = workspace / "output" / "ingest" / "new_shots_catalog.csv"
    if not out_path.exists():
        return 0.0
    header, rows, err = _read_csv_rows(out_path)
    if err:
        return 0.0
    if header != header_expected:
        return 0.0
    if len(rows) != len(rows_expected):
        return 0.0
    for r_act, r_exp in zip(rows, rows_expected):
        if r_act != r_exp:
            return 0.0
    return 1.0


def _extract_number(pattern: str, text: str, flags=0) -> Tuple[bool, str]:
    m = re.search(pattern, text, flags)
    if not m:
        return False, ""
    return True, m.group(1)


def _check_report_metrics(workspace: Path, expected: Dict[str, Any]) -> float:
    path = workspace / "output" / "reports" / "ingest_status.md"
    if not path.exists():
        return 0.0
    text, err = _read_text(path)
    if err:
        return 0.0

    ok = True

    found, val = _extract_number(r"New\s+shots\s+ingested:\s*(\d+)", text, flags=re.I)
    if not found or int(val) != int(expected["report_new_count"]):
        ok = False

    found, val = _extract_number(r"Skipped\s*\(duplicates\):\s*(\d+)", text, flags=re.I)
    if not found or int(val) != int(expected["report_skipped_duplicates"]):
        ok = False

    total_str = f"{float(expected['report_total_minutes']):.1f}"
    if not re.search(rf"Total\s+duration.*minutes.*[:\s]\s*{re.escape(total_str)}\b", text, flags=re.I) and \
       not re.search(rf"Total\s+duration.*[:]\s*{re.escape(total_str)}\s*minutes", text, flags=re.I):
        ok = False

    earliest = expected["report_date_earliest"]
    latest = expected["report_date_latest"]
    if earliest and latest:
        range_pattern = rf"Capture\s+date\s+range.*:\s*{re.escape(earliest)}\s*(?:-|–|—|→|to)\s*{re.escape(latest)}"
        if not re.search(range_pattern, text, flags=re.I):
            ok = False

    return 1.0 if ok else 0.0


def _check_report_tags_and_details(workspace: Path, expected: Dict[str, Any]) -> float:
    path = workspace / "output" / "reports" / "ingest_status.md"
    if not path.exists():
        return 0.0
    text, err = _read_text(path)
    if err:
        return 0.0

    ok = True

    expected_tags = [t for t, c in expected["report_tag_freq_sorted"]]
    expected_counts_map = dict(expected["report_tag_freq_sorted"])
    pairs = re.findall(r"([A-Za-z0-9_\-]+)\s*:\s*(\d+)", text)
    filtered_pairs = [(t, int(c)) for (t, c) in pairs if t in expected_counts_map]
    if len(filtered_pairs) != len(expected_tags):
        ok = False
    else:
        for (t, c), t_exp in zip(filtered_pairs, expected_tags):
            if t != t_exp or c != expected_counts_map[t]:
                ok = False
                break

    details: List[Dict[str, str]] = expected["report_details"]
    if len(details) == 0:
        pass
    else:
        lines = text.splitlines()
        for d in details:
            id_ = d["id"]
            title = d["title"]
            date = d["capture_date"]
            dur = d["duration_min"]
            found_line = False
            for ln in lines:
                if (id_ in ln) and (title in ln) and (date in ln):
                    found_line = True
                    break
            if not found_line:
                ok = False
                break
            if not re.search(rf"\b{re.escape(dur)}\b", text):
                ok = False
                break

    return 1.0 if ok else 0.0


def _check_revised_update_metrics_and_placeholders(workspace: Path, expected: Dict[str, Any]) -> float:
    path = workspace / "output" / "communications" / "revised_update.md"
    if not path.exists():
        return 0.0
    text, err = _read_text(path)
    if err:
        return 0.0

    if any(p in text for p in ["{NEW_COUNT}", "{TOTAL_MINUTES}", "{ID_LIST}"]):
        return 0.0

    new_count = int(expected["revised_update_new_count"])
    total_minutes_str = f"{float(expected['revised_update_total_minutes']):.1f}"
    id_list = expected["revised_update_id_list"]

    if not re.search(rf"\b{new_count}\b", text):
        return 0.0
    if not re.search(rf"\b{re.escape(total_minutes_str)}\b", text):
        return 0.0
    if id_list:
        if id_list not in text:
            return 0.0

    return 1.0


def _check_revised_update_length(workspace: Path) -> float:
    path = workspace / "output" / "communications" / "revised_update.md"
    if not path.exists():
        return 0.0
    text, err = _read_text(path)
    if err:
        return 0.0
    words = re.findall(r"[A-Za-z0-9']+", text)
    count = len(words)
    if 60 <= count <= 120:
        return 1.0
    return 0.0


def _check_updated_master_catalog(workspace: Path, expected: List[dict]) -> float:
    path = workspace / "output" / "catalog" / "updated_master_catalog.json"
    if not path.exists():
        return 0.0
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(actual, list):
            return 0.0
        if _compare_json(actual, expected):
            return 1.0
        return 0.0
    except Exception:
        return 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "new_shots_catalog_json_correct": 0.0,
        "new_shots_catalog_csv_correct": 0.0,
        "ingest_status_report_metrics_correct": 0.0,
        "ingest_status_report_tags_and_details": 0.0,
        "revised_update_placeholders_and_values": 0.0,
        "revised_update_length_requirement": 0.0,
        "updated_master_catalog_json_correct": 0.0,
    }

    master, incoming, err = _load_inputs(workspace)
    if err:
        return scores

    expected = _compute_expected(master, incoming)

    scores["new_shots_catalog_json_correct"] = _check_new_json(workspace, expected["expected_new_json"])
    scores["new_shots_catalog_csv_correct"] = _check_new_csv(
        workspace, expected["expected_csv_header"], expected["expected_csv_rows"]
    )
    scores["ingest_status_report_metrics_correct"] = _check_report_metrics(workspace, expected)
    scores["ingest_status_report_tags_and_details"] = _check_report_tags_and_details(workspace, expected)
    scores["revised_update_placeholders_and_values"] = _check_revised_update_metrics_and_placeholders(workspace, expected)
    scores["revised_update_length_requirement"] = _check_revised_update_length(workspace)
    scores["updated_master_catalog_json_correct"] = _check_updated_master_catalog(workspace, expected["expected_updated_master"])

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()