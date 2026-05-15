import json
import csv
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _compute_events_metrics(events_path: Path) -> Optional[Tuple[float, int]]:
    rows = _load_csv_dicts(events_path)
    if rows is None:
        return None
    total_hours = 0.0
    total_events = 0
    for row in rows:
        try:
            hours = float(row.get("hours_contributed", 0) or 0)
        except (ValueError, TypeError):
            hours = 0.0
        total_hours += hours
        total_events += 1
    return (round(total_hours, 2), total_events)


def _compute_car_metrics(car_path: Path) -> Optional[Tuple[int, float, Dict[str, int], Dict[str, int]]]:
    rows = _load_csv_dicts(car_path)
    if rows is None:
        return None
    task_type_counts: Dict[str, int] = {}
    helper_counts: Dict[str, int] = {}
    total_tasks = 0
    total_parts_cost = 0.0
    for row in rows:
        total_tasks += 1
        task = (row.get("task_type") or "").strip()
        helper = (row.get("helper_name") or "").strip()
        task_type_counts[task] = task_type_counts.get(task, 0) + 1
        helper_counts[helper] = helper_counts.get(helper, 0) + 1
        try:
            cost = float(row.get("parts_cost", 0) or 0)
        except (ValueError, TypeError):
            cost = 0.0
        total_parts_cost += cost
    return (total_tasks, round(total_parts_cost, 2), task_type_counts, helper_counts)


def _top_task_type(task_counts: Dict[str, int]) -> Tuple[Optional[str], int]:
    if not task_counts:
        return (None, 0)
    # max by count; if tie, Python's max will pick the first encountered which depends on dict insertion order
    return max(task_counts.items(), key=lambda kv: kv[1])


def _number_near_token(text: str, number_variants: List[str], token_variants: List[str], window: int = 50) -> bool:
    # check that one of number patterns appears within window characters of any token variant
    t = text.lower()
    # build positions of tokens
    token_positions = []
    for token in token_variants:
        start = 0
        tok = token.lower()
        while True:
            idx = t.find(tok, start)
            if idx == -1:
                break
            token_positions.append(idx)
            start = idx + 1
    if not token_positions:
        return False
    for num in number_variants:
        start = 0
        while True:
            idx = t.find(num.lower(), start)
            if idx == -1:
                break
            for tp in token_positions:
                if abs(idx - tp) <= window:
                    return True
            start = idx + 1
    return False


def _format_number_variants(value: float, integer_only: bool = False) -> List[str]:
    # Create common textual representations
    variants = set()
    if integer_only or float(value).is_integer():
        iv = int(round(value))
        variants.add(str(iv))
        variants.add(f"{iv}.0")
        variants.add(f"{iv}.00")
    else:
        variants.add(f"{value}")
        variants.add(f"{value:.2f}")
    return list(variants)


def _helpers_sorted_by_count(helper_counts: Dict[str, int], top_n: int = 3) -> List[Tuple[str, int]]:
    # Sort by count desc, then name asc to stabilize
    return sorted(helper_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]


def _has_verbatim_quote(letter_text: str, quotes_path: Path) -> bool:
    quotes_text = _read_text(quotes_path)
    if not quotes_text or not letter_text:
        return False
    lt = letter_text
    # Extract lines like '- Name: "Quote"'
    for line in quotes_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            entry = stripped[2:].strip()
        else:
            entry = stripped
        # Require exact substring presence (verbatim) of Name: "Quote"
        if entry and entry in lt:
            return True
    return False


def _has_double_check_note(letter_text: str) -> bool:
    if not letter_text:
        return False
    t = letter_text.lower()
    # Must mention CSV and metrics.json, and indicate double-checked
    has_csv = "csv" in t
    has_metrics = "metrics.json" in t
    # detect 'double-checked' or 'double checked'
    has_double_checked = ("double-checked" in t) or ("double checked" in t)
    return has_csv and has_metrics and has_double_checked


def _appendix_csv_valid_structure(appendix_path: Path) -> bool:
    rows = _load_csv_dicts(appendix_path)
    if rows is None:
        return False
    # Check header columns exactly
    try:
        with appendix_path.open("r", encoding="utf-8", newline="") as f:
            header = f.readline().strip()
    except Exception:
        return False
    return header == "task_type,count"


def _appendix_sorted_desc(appendix_path: Path) -> bool:
    rows = _load_csv_dicts(appendix_path)
    if rows is None:
        return False
    counts = []
    for r in rows:
        try:
            counts.append(int(r.get("count", "")))
        except Exception:
            return False
    # Non-increasing order
    return all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Paths
    events_csv = workspace / "input" / "community_events.csv"
    car_csv = workspace / "input" / "car_help_log.csv"
    quotes_md = workspace / "input" / "notes" / "community_quotes.md"
    metrics_json_path = workspace / "derived" / "metrics.json"
    letter_path = workspace / "output" / "thank_you_letter.md"
    appendix_path = workspace / "output" / "appendix_counts.csv"

    # Compute expected metrics from inputs
    events_metrics = _compute_events_metrics(events_csv) if events_csv.exists() else None
    car_metrics = _compute_car_metrics(car_csv) if car_csv.exists() else None

    expected_totals = None
    expected_task_counts = None
    expected_helper_counts = None
    expected_top_task = (None, 0)
    if events_metrics is not None and car_metrics is not None:
        hours, n_events = events_metrics
        total_tasks, parts_cost, task_counts, helper_counts = car_metrics
        expected_totals = {
            "community_hours": hours,
            "events": n_events,
            "car_tasks": total_tasks,
            "parts_cost": parts_cost,
        }
        expected_task_counts = task_counts
        expected_helper_counts = helper_counts
        expected_top_task = _top_task_type(task_counts)

    # Load metrics.json
    metrics = _load_json(metrics_json_path)
    metrics_ok = isinstance(metrics, dict)

    # Prepare scores
    scores = {
        "metrics_json_exists": 1.0 if metrics_ok else 0.0,
        "metrics_totals_match_inputs": 0.0,
        "metrics_task_type_counts_match_inputs": 0.0,
        "metrics_helper_counts_match_inputs": 0.0,
        "metrics_top_task_type_correct": 0.0,
        "letter_exists": 0.0,
        "letter_mentions_total_hours_and_events": 0.0,
        "letter_mentions_total_car_tasks": 0.0,
        "letter_includes_parts_cost_formatted": 0.0,
        "letter_includes_top_task_and_share": 0.0,
        "letter_includes_top_helpers_bulleted": 0.0,
        "letter_includes_verbatim_quote": 0.0,
        "letter_includes_double_check_note": 0.0,
        "letter_includes_data_snapshot": 0.0,
        "appendix_csv_exists_and_structure": 0.0,
        "appendix_counts_match_metrics": 0.0,
        "appendix_sorted_descending": 0.0,
    }

    # Validate metrics content
    if metrics_ok and expected_totals is not None:
        try:
            mtot = metrics.get("totals", {})
            if (
                isinstance(mtot, dict)
                and mtot.get("community_hours") == expected_totals["community_hours"]
                and mtot.get("events") == expected_totals["events"]
                and mtot.get("car_tasks") == expected_totals["car_tasks"]
                and mtot.get("parts_cost") == expected_totals["parts_cost"]
            ):
                scores["metrics_totals_match_inputs"] = 1.0
        except Exception:
            scores["metrics_totals_match_inputs"] = 0.0

    if metrics_ok and expected_task_counts is not None:
        try:
            mcounts = metrics.get("task_type_counts", {})
            if isinstance(mcounts, dict) and all(isinstance(v, int) for v in mcounts.values()):
                if mcounts == expected_task_counts:
                    scores["metrics_task_type_counts_match_inputs"] = 1.0
        except Exception:
            scores["metrics_task_type_counts_match_inputs"] = 0.0

    if metrics_ok and expected_helper_counts is not None:
        try:
            hcounts = metrics.get("helper_counts", {})
            if isinstance(hcounts, dict) and all(isinstance(v, int) for v in hcounts.values()):
                if hcounts == expected_helper_counts:
                    scores["metrics_helper_counts_match_inputs"] = 1.0
        except Exception:
            scores["metrics_helper_counts_match_inputs"] = 0.0

    if metrics_ok and expected_task_counts is not None:
        try:
            mtop = metrics.get("top_task_type", {})
            if isinstance(mtop, dict):
                mname = mtop.get("name")
                mcount = mtop.get("count")
                exp_name, exp_count = expected_top_task
                if mname == exp_name and mcount == exp_count:
                    scores["metrics_top_task_type_correct"] = 1.0
        except Exception:
            scores["metrics_top_task_type_correct"] = 0.0

    # Letter checks
    letter_text = _read_text(letter_path) if letter_path.exists() else None
    if letter_text is not None:
        scores["letter_exists"] = 1.0

    if letter_text is not None and expected_totals is not None:
        # hours and events
        hours_variants = _format_number_variants(expected_totals["community_hours"], integer_only=True)
        events_variants = _format_number_variants(expected_totals["events"], integer_only=True)
        has_hours = _number_near_token(letter_text, hours_variants, ["hour", "hours"])
        has_events = _number_near_token(letter_text, events_variants, ["event", "events"])
        if has_hours and has_events:
            scores["letter_mentions_total_hours_and_events"] = 1.0

        # car tasks near "task"
        tasks_variants = _format_number_variants(expected_totals["car_tasks"], integer_only=True)
        has_tasks = _number_near_token(letter_text, tasks_variants, ["task", "tasks"])
        if has_tasks:
            scores["letter_mentions_total_car_tasks"] = 1.0

        # parts cost formatted as $X.XX
        cost_str = f"{expected_totals['parts_cost']:.2f}"
        money_pattern = re.escape("$") + r"\s?" + re.escape(cost_str) + r"\b"
        if re.search(money_pattern, letter_text):
            scores["letter_includes_parts_cost_formatted"] = 1.0

    if letter_text is not None and car_metrics is not None:
        # top task type and share percent
        _, _, task_counts, _ = car_metrics
        top_name, top_count = _top_task_type(task_counts)
        total_tasks = sum(task_counts.values())
        share_percent = int(round(100 * (top_count / total_tasks))) if total_tasks > 0 else 0
        has_top_name = (top_name is None and True) or (top_name is not None and top_name in letter_text)
        has_share = f"{share_percent}%" in letter_text
        if has_top_name and has_share:
            scores["letter_includes_top_task_and_share"] = 1.0

        # helpers bullet list up to top 3 with counts in parentheses
        top_helpers = _helpers_sorted_by_count(car_metrics[3], top_n=3)
        # find bullet lines
        bullet_lines = [line.strip() for line in letter_text.splitlines() if line.strip().startswith(("-", "*"))]
        # Build expected patterns like "Name (count)"
        patterns = [re.compile(re.escape(f"{name} ({count})")) for name, count in top_helpers]
        # Check presence and order
        indices = []
        for pat in patterns:
            found_index = -1
            for idx, line in enumerate(bullet_lines):
                if pat.search(line):
                    found_index = idx
                    break
            if found_index == -1:
                indices = []
                break
            indices.append(found_index)
        if indices and indices == sorted(indices):
            scores["letter_includes_top_helpers_bulleted"] = 1.0

    if letter_text is not None and quotes_md.exists():
        if _has_verbatim_quote(letter_text, quotes_md):
            scores["letter_includes_verbatim_quote"] = 1.0

    if letter_text is not None:
        if _has_double_check_note(letter_text):
            scores["letter_includes_double_check_note"] = 1.0

    if letter_text is not None and metrics_ok:
        script_version = metrics.get("script_version")
        has_version = isinstance(script_version, str) and (script_version in letter_text)
        has_path = "derived/metrics.json" in letter_text
        if has_version and has_path:
            scores["letter_includes_data_snapshot"] = 1.0

    # Appendix checks
    if appendix_path.exists() and _appendix_csv_valid_structure(appendix_path):
        scores["appendix_csv_exists_and_structure"] = 1.0

    if metrics_ok and appendix_path.exists():
        # Compare counts with metrics
        rows = _load_csv_dicts(appendix_path)
        mcounts = metrics.get("task_type_counts") if isinstance(metrics, dict) else None
        if rows is not None and isinstance(mcounts, dict):
            try:
                # Create dict from appendix
                acounts: Dict[str, int] = {}
                valid = True
                for r in rows:
                    task_type = r.get("task_type")
                    try:
                        count = int(r.get("count", ""))
                    except Exception:
                        valid = False
                        break
                    if task_type is None:
                        valid = False
                        break
                    acounts[task_type] = count
                if valid and acounts == mcounts:
                    scores["appendix_counts_match_metrics"] = 1.0
            except Exception:
                scores["appendix_counts_match_metrics"] = 0.0

    if appendix_path.exists() and _appendix_sorted_desc(appendix_path):
        scores["appendix_sorted_descending"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()