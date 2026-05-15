import json
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _load_jsonl(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    try:
        data = []
        with path.open(encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception as e:
                    return None, f"Line {i} {type(e).__name__}: {e}"
                if not isinstance(obj, dict):
                    return None, f"Line {i}: not an object"
                data.append(obj)
        return data, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _parse_supporters_html(path: Path) -> Tuple[Optional[List[Tuple[str, int]]], Optional[str], Optional[int]]:
    text = _read_text(path)
    if text is None:
        return None, "read_error", None
    tbody_match = re.search(r"<tbody[^>]*>(.*?)</tbody>", text, flags=re.I | re.S)
    if not tbody_match:
        inner = ""
    else:
        inner = tbody_match.group(1)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", inner, flags=re.I | re.S)
    row_count = len(rows)
    # Extract supporters in order
    supporters = []
    for r in rows:
        m = re.search(r"<td>([^<]+)</td>\s*<td>\$?\s*([0-9]+)\s*</td>", r, flags=re.I | re.S)
        if not m:
            return None, "row_parse_error", row_count
        name = m.group(1).strip()
        pledge = int(m.group(2))
        supporters.append((name, pledge))
    return supporters, None, row_count


def _parse_csv_rows(path: Path) -> Tuple[Optional[List[List[str]]], Optional[str]]:
    try:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _compute_expected_summary(stories: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by_comm: Dict[str, Dict[str, Any]] = {}
    for s in stories:
        comm = s.get("community", "unknown")
        entry = by_comm.setdefault(comm, {"community": comm, "story_count": 0, "tag_counts": {}})
        entry["story_count"] += 1
        tags = s.get("tags", [])
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, str):
                    entry["tag_counts"][t] = entry["tag_counts"].get(t, 0) + 1
    expected: Dict[str, Dict[str, Any]] = {}
    for comm, entry in by_comm.items():
        tag_counts = entry["tag_counts"]
        sorted_tags = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        expected[comm] = {
            "community": comm,
            "story_count": entry["story_count"],
            "top_tags": [t for t, _ in sorted_tags],
        }
    return expected


def _validate_summary_schema(summary: Any) -> Tuple[bool, Optional[Dict[str, Dict[str, Any]]], Optional[str]]:
    if not isinstance(summary, list):
        return False, None, "not_list"
    mapping: Dict[str, Dict[str, Any]] = {}
    for idx, item in enumerate(summary):
        if not isinstance(item, dict):
            return False, None, f"item_{idx}_not_object"
        keys = set(item.keys())
        expected_keys = {"community", "story_count", "top_tags"}
        if keys != expected_keys:
            return False, None, f"item_{idx}_keys_mismatch"
        if not isinstance(item["community"], str):
            return False, None, f"item_{idx}_community_type"
        if not isinstance(item["story_count"], int):
            return False, None, f"item_{idx}_story_count_type"
        if not isinstance(item["top_tags"], list):
            return False, None, f"item_{idx}_top_tags_type"
        if len(item["top_tags"]) > 3:
            return False, None, f"item_{idx}_top_tags_len"
        for j, t in enumerate(item["top_tags"]):
            if not isinstance(t, str):
                return False, None, f"item_{idx}_top_tags_{j}_type"
        mapping[item["community"]] = {
            "community": item["community"],
            "story_count": item["story_count"],
            "top_tags": item["top_tags"],
        }
    return True, mapping, None


def _load_bug_report(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    obj, err = _load_json(path)
    if err is not None or obj is None:
        return None, err or "load_error"
    if not isinstance(obj, dict):
        return None, "not_object"
    if "errors" not in obj or not isinstance(obj["errors"], list):
        return None, "errors_list_missing"
    # Validate each error structure
    for i, e in enumerate(obj["errors"]):
        if not isinstance(e, dict):
            return None, f"error_{i}_not_object"
        for key in ("stage", "error_message", "root_cause", "fix"):
            if key not in e:
                return None, f"error_{i}_{key}_missing"
            if not isinstance(e[key], str) or not e[key].strip():
                return None, f"error_{i}_{key}_invalid"
    return obj, None


def _load_validation_json(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    obj, err = _load_json(path)
    if err is not None or obj is None:
        return None, err or "load_error"
    if not isinstance(obj, dict):
        return None, "not_object"
    required_keys = {
        "supporter_rows_in_html": int,
        "supporters_in_csv": int,
        "story_records_in_jsonl": int,
        "story_counts_by_community": dict,
    }
    for k, t in required_keys.items():
        if k not in obj:
            return None, f"{k}_missing"
        if not isinstance(obj[k], t):
            return None, f"{k}_type"
    # Ensure dict has string->int mapping
    sc = obj["story_counts_by_community"]
    for ck, cv in sc.items():
        if not isinstance(ck, str) or not isinstance(cv, int):
            return None, "story_counts_by_community_kv_type"
    return obj, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "stories_summary_json_valid": 0.0,
        "stories_summary_content_correct": 0.0,
        "supporters_csv_header_correct": 0.0,
        "supporters_csv_content_correct": 0.0,
        "bug_report_structure_valid": 0.0,
        "bug_report_includes_key_errors": 0.0,
        "validation_json_consistent": 0.0,
    }

    # Paths
    data_dir = workspace / "data"
    outputs_dir = workspace / "outputs"
    analysis_dir = workspace / "analysis"
    stories_jsonl_path = data_dir / "stories.jsonl"
    supporters_html_path = data_dir / "supporters.html"
    summary_json_path = outputs_dir / "stories_summary.json"
    supporters_csv_path = outputs_dir / "supporters.csv"
    bug_report_path = analysis_dir / "bug_report.json"
    validation_json_path = analysis_dir / "validation.json"

    # Load inputs for expected computations
    stories, stories_err = _load_jsonl(stories_jsonl_path)
    supporters_expected, supporters_parse_err, supporter_row_count = _parse_supporters_html(supporters_html_path)
    expected_summary_map: Optional[Dict[str, Dict[str, Any]]] = None
    expected_counts_by_comm: Optional[Dict[str, int]] = None
    if stories is not None:
        expected_summary_map = _compute_expected_summary(stories)
        expected_counts_by_comm = {k: v["story_count"] for k, v in expected_summary_map.items()}

    # Check stories_summary.json validity and content
    summary_obj, summary_load_err = _load_json(summary_json_path)
    summary_valid = False
    summary_map: Optional[Dict[str, Dict[str, Any]]] = None
    if summary_obj is not None:
        ok, mapping, _ = _validate_summary_schema(summary_obj)
        if ok and mapping is not None:
            summary_valid = True
            summary_map = mapping
    if summary_valid:
        scores["stories_summary_json_valid"] = 1.0

    if summary_valid and expected_summary_map is not None:
        # Compare communities set
        if set(summary_map.keys()) == set(expected_summary_map.keys()):
            # Compare per community story_count and top_tags lists
            per_comm_match = True
            for comm, exp in expected_summary_map.items():
                got = summary_map.get(comm)
                if got is None:
                    per_comm_match = False
                    break
                if got.get("story_count") != exp.get("story_count"):
                    per_comm_match = False
                    break
                if got.get("top_tags") != exp.get("top_tags"):
                    per_comm_match = False
                    break
            if per_comm_match:
                scores["stories_summary_content_correct"] = 1.0

    # Check supporters.csv header and content
    csv_rows, csv_err = _parse_csv_rows(supporters_csv_path)
    if csv_rows is not None and len(csv_rows) >= 1:
        header = csv_rows[0]
        if header == ["name", "monthly_pledge"]:
            scores["supporters_csv_header_correct"] = 1.0
        data_rows = csv_rows[1:]
        if supporters_expected is not None:
            # Compare count and ordered values (name, pledge)
            if len(data_rows) == len(supporters_expected):
                all_ok = True
                for i, row in enumerate(data_rows):
                    if len(row) != 2:
                        all_ok = False
                        break
                    name = row[0]
                    try:
                        pledge = int(row[1])
                    except:
                        all_ok = False
                        break
                    exp_name, exp_pledge = supporters_expected[i]
                    if name != exp_name or pledge != exp_pledge:
                        all_ok = False
                        break
                if all_ok:
                    scores["supporters_csv_content_correct"] = 1.0

    # Check bug_report.json structure and presence of key errors
    bug_report_obj, bug_err = _load_bug_report(bug_report_path)
    if bug_report_obj is not None:
        scores["bug_report_structure_valid"] = 1.0
        # Presence of FileNotFoundError (stories.json) and NameError (rows)
        errors_list = bug_report_obj.get("errors", [])
        found_fnf = False
        found_name = False
        for e in errors_list:
            msg = e.get("error_message", "")
            msg_low = msg.lower()
            if "filenotfounderror" in msg_low and ("no such file" in msg_low or "stories.json" in msg_low or "stories.jsonl" in msg_low):
                found_fnf = True
            if "nameerror" in msg_low and ("rows" in msg_low or "is not defined" in msg_low):
                found_name = True
        if found_fnf and found_name:
            scores["bug_report_includes_key_errors"] = 1.0

    # Check analysis/validation.json consistency
    validation_obj, validation_err = _load_validation_json(validation_json_path)
    if validation_obj is not None:
        # Compute actuals
        actual_supporter_rows_in_html = supporter_row_count if supporter_row_count is not None else None
        actual_supporters_in_csv = None
        if csv_rows is not None and len(csv_rows) >= 1:
            actual_supporters_in_csv = max(0, len(csv_rows) - 1)
        actual_story_records_in_jsonl = None
        if stories is not None:
            actual_story_records_in_jsonl = len(stories)
        actual_counts_by_comm = expected_counts_by_comm
        summary_counts_by_comm = None
        if summary_map is not None:
            summary_counts_by_comm = {k: v["story_count"] for k, v in summary_map.items()}

        v_ok = True

        # supporter_rows_in_html
        if actual_supporter_rows_in_html is None or validation_obj.get("supporter_rows_in_html") != actual_supporter_rows_in_html:
            v_ok = False

        # supporters_in_csv
        if actual_supporters_in_csv is None or validation_obj.get("supporters_in_csv") != actual_supporters_in_csv:
            v_ok = False

        # story_records_in_jsonl
        if actual_story_records_in_jsonl is None or validation_obj.get("story_records_in_jsonl") != actual_story_records_in_jsonl:
            v_ok = False

        # story_counts_by_community equal to both expected and summary
        v_counts = validation_obj.get("story_counts_by_community")
        if actual_counts_by_comm is None or summary_counts_by_comm is None:
            v_ok = False
        else:
            if v_counts != actual_counts_by_comm or v_counts != summary_counts_by_comm:
                v_ok = False

        if v_ok:
            scores["validation_json_consistent"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()