import json
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(row)
            return rows
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _num_equal(a: Any, b: Any, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _round_or_zero(value: float, ndigits: int) -> float:
    try:
        return round(value, ndigits)
    except Exception:
        return 0.0


def _compute_expected(resources: List[Dict[str, Any]], log_rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    # Filter resources: tags include "axios" or "redux" and level beginner or intermediate
    filtered_resources = []
    for r in resources:
        tags = r.get("tags", [])
        level = str(r.get("level", "")).strip().lower()
        tag_set = {str(t).strip().lower() for t in tags if isinstance(t, str)}
        if level in {"beginner", "intermediate"} and (("axios" in tag_set) or ("redux" in tag_set)):
            filtered_resources.append(r)

    res_by_topic: Dict[str, Dict[str, Any]] = {r.get("topic", ""): r for r in filtered_resources if isinstance(r.get("topic", ""), str)}

    # Group learning log by topic that exists in filtered resources
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in log_rows:
        topic = row.get("topic", "")
        if topic in res_by_topic:
            grouped.setdefault(topic, []).append(row)

    # Include topics with at least 2 sessions
    included_topics = []
    stats_by_topic: Dict[str, Dict[str, Any]] = {}
    for topic, rows in grouped.items():
        sessions = len(rows)
        if sessions >= 2:
            completions = 0
            errors_vals = []
            time_vals = []
            rating_vals = []
            for r in rows:
                try:
                    completions += int(str(r.get("completed", 0)).strip())
                except Exception:
                    completions += 0
                try:
                    errors_vals.append(float(str(r.get("errors", 0)).strip()))
                except Exception:
                    errors_vals.append(0.0)
                try:
                    time_vals.append(float(str(r.get("time_spent_min", 0)).strip()))
                except Exception:
                    time_vals.append(0.0)
                try:
                    rating_vals.append(float(str(r.get("rating", 0)).strip()))
                except Exception:
                    rating_vals.append(0.0)
            completion_rate = (completions / sessions) if sessions > 0 else 0.0
            avg_errors = (sum(errors_vals) / len(errors_vals)) if errors_vals else 0.0
            avg_time = (sum(time_vals) / len(time_vals)) if time_vals else 0.0
            avg_rating = (sum(rating_vals) / len(rating_vals)) if rating_vals else 0.0

            # Apply rounding as specified
            comp_rate_r = _round_or_zero(completion_rate, 4)
            avg_errors_r = _round_or_zero(avg_errors, 2)
            avg_time_r = _round_or_zero(avg_time, 1)
            avg_rating_r = _round_or_zero(avg_rating, 2)

            stats_by_topic[topic] = {
                "sessions": sessions,
                "completions": completions,
                "completion_rate": comp_rate_r,
                "avg_errors": avg_errors_r,
                "avg_time": avg_time_r,
                "avg_rating": avg_rating_r,
            }
            included_topics.append(topic)

    # Compute max errors and max time across included topics (using rounded stats as per spec)
    if included_topics:
        max_errors = max(stats_by_topic[t]["avg_errors"] for t in included_topics)
        max_time = max(stats_by_topic[t]["avg_time"] for t in included_topics)
    else:
        max_errors = 0.0
        max_time = 0.0

    # Build expected ranking objects
    expected_items: List[Dict[str, Any]] = []
    for topic in included_topics:
        res = res_by_topic[topic]
        st = stats_by_topic[topic]
        try:
            popularity_score = int(res.get("popularity_score", 0))
        except Exception:
            popularity_score = 0
        popularity_norm = popularity_score / 100.0 if popularity_score is not None else 0.0

        # components
        if max_errors == 0:
            errors_component = 0.2
        else:
            errors_component = 0.2 * (1 - (st["avg_errors"] / max_errors))

        if max_time == 0:
            time_component = 0.2
        else:
            time_component = 0.2 * (1 - (st["avg_time"] / max_time))

        novice_score = (0.5 * st["completion_rate"]) + errors_component + time_component + (0.1 * popularity_norm)
        novice_score_r = _round_or_zero(novice_score, 4)

        item = {
            "topic": topic,
            "type": res.get("type"),
            "level": res.get("level"),
            "tags": res.get("tags"),
            "popularity_score": popularity_score,
            "sessions": st["sessions"],
            "completion_rate": st["completion_rate"],
            "avg_errors": st["avg_errors"],
            "avg_time": st["avg_time"],
            "avg_rating": st["avg_rating"],
            "novice_score": novice_score_r,
            "_duration_min": res.get("duration_min"),
            "_summary": res.get("summary"),
        }
        expected_items.append(item)

    # Sort by novice_score desc, then popularity_score desc, then topic asc
    expected_items.sort(key=lambda x: (-x["novice_score"], -x["popularity_score"], x["topic"]))

    # Compute aggregates across all included topics used in the ranking
    total_sessions = sum(stats_by_topic[t]["sessions"] for t in included_topics) if included_topics else 0
    total_completions = sum(stats_by_topic[t]["completions"] for t in included_topics) if included_topics else 0
    topic_count = len(included_topics)
    weighted_rate = _round_or_zero(((total_completions / total_sessions) * 100.0) if total_sessions > 0 else 0.0, 1)

    aggregates = {
        "total_sessions": total_sessions,
        "total_completions": total_completions,
        "topic_count": topic_count,
        "weighted_rate": weighted_rate,
    }

    return expected_items, aggregates


def _build_expected_week3_block(expected_items: List[Dict[str, Any]], aggregates: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("Updated Week 3: Networking and State (Axios + Redux)")
    topn = min(5, len(expected_items))
    for idx in range(topn):
        item = expected_items[idx]
        topic = item["topic"]
        typ = item["type"]
        duration = item.get("_duration_min")
        summary = item.get("_summary", "")
        lines.append(f"{idx+1}. {topic} — {typ} — {duration} min")
        lines.append(f"{summary}")
    lines.append(
        f"Aggregate: {aggregates.get('total_sessions', 0)} sessions across {aggregates.get('topic_count', 0)} topics; weighted completion rate: {aggregates.get('weighted_rate', 0.0)}%"
    )
    return "\n".join(lines)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "ranking_file_valid": 0.0,
        "ranking_order_correct": 0.0,
        "ranking_values_correct": 0.0,
        "syllabus_block_heading_list_correct": 0.0,
        "syllabus_aggregate_line_correct": 0.0,
        "syllabus_outside_content_unchanged": 0.0,
    }

    # Load inputs
    resources_path = workspace / "input" / "resources.json"
    log_path = workspace / "input" / "learning_log.csv"
    syllabus_path = workspace / "docs" / "syllabus.md"

    resources = _safe_read_json(resources_path)
    log_rows = _safe_read_csv(log_path)
    if not isinstance(resources, list) or log_rows is None:
        # Without inputs, nothing can be validated
        return scores

    expected_items, aggregates = _compute_expected(resources, log_rows)

    # Prepare expected ranking objects stripped of helper fields
    expected_ranking = []
    for item in expected_items:
        expected_ranking.append({
            "topic": item["topic"],
            "type": item["type"],
            "level": item["level"],
            "tags": item["tags"],
            "popularity_score": item["popularity_score"],
            "sessions": item["sessions"],
            "completion_rate": item["completion_rate"],
            "avg_errors": item["avg_errors"],
            "avg_time": item["avg_time"],
            "avg_rating": item["avg_rating"],
            "novice_score": item["novice_score"],
        })

    # Check ranking JSON
    out_path = workspace / "output" / "novice_topics_ranking.json"
    out_json = _safe_read_json(out_path)
    ranking_values_ok = False
    ranking_order_ok = False
    if isinstance(out_json, list):
        scores["ranking_file_valid"] = 1.0
        # Order check
        order_ok = True
        if len(out_json) != len(expected_ranking):
            order_ok = False
        else:
            for idx, obj in enumerate(out_json):
                exp = expected_ranking[idx]
                if not isinstance(obj, dict):
                    order_ok = False
                    break
                if obj.get("topic") != exp["topic"]:
                    order_ok = False
                    break
        ranking_order_ok = order_ok
        scores["ranking_order_correct"] = 1.0 if order_ok else 0.0

        # Values check
        values_ok = True
        required_keys = ["topic", "type", "level", "tags", "popularity_score", "sessions",
                         "completion_rate", "avg_errors", "avg_time", "avg_rating", "novice_score"]
        if len(out_json) != len(expected_ranking):
            values_ok = False
        else:
            for idx, obj in enumerate(out_json):
                exp = expected_ranking[idx]
                for k in required_keys:
                    if k not in obj:
                        values_ok = False
                        break
                if not values_ok:
                    break
                if obj.get("topic") != exp["topic"]:
                    values_ok = False
                    break
                if obj.get("type") != exp["type"]:
                    values_ok = False
                    break
                if obj.get("level") != exp["level"]:
                    values_ok = False
                    break
                if obj.get("tags") != exp["tags"]:
                    values_ok = False
                    break
                try:
                    if int(obj.get("popularity_score")) != int(exp["popularity_score"]):
                        values_ok = False
                        break
                    if int(obj.get("sessions")) != int(exp["sessions"]):
                        values_ok = False
                        break
                except Exception:
                    values_ok = False
                    break
                if not _num_equal(obj.get("completion_rate"), exp["completion_rate"], tol=5e-5):
                    values_ok = False
                    break
                if not _num_equal(obj.get("avg_errors"), exp["avg_errors"], tol=5e-3):
                    values_ok = False
                    break
                if not _num_equal(obj.get("avg_time"), exp["avg_time"], tol=5e-3):
                    values_ok = False
                    break
                if not _num_equal(obj.get("avg_rating"), exp["avg_rating"], tol=5e-3):
                    values_ok = False
                    break
                if not _num_equal(obj.get("novice_score"), exp["novice_score"], tol=5e-5):
                    values_ok = False
                    break
        ranking_values_ok = values_ok
        scores["ranking_values_correct"] = 1.0 if values_ok else 0.0

    # Check syllabus (gate awarding by whether content matches expected to avoid pre-solution credit)
    syllabus_text = _read_text(syllabus_path)
    if syllabus_text is not None:
        start_marker = "<!-- WEEK3_START -->"
        end_marker = "<!-- WEEK3_END -->"
        start_idx = syllabus_text.find(start_marker)
        end_idx = syllabus_text.find(end_marker)
        markers_ok = (start_idx != -1 and end_idx != -1 and end_idx > start_idx)
        if markers_ok:
            before = syllabus_text[:start_idx]
            after = syllabus_text[end_idx + len(end_marker):]

            inside = syllabus_text[start_idx + len(start_marker):end_idx]
            inside_stripped = inside.strip("\n")

            expected_block = _build_expected_week3_block(expected_items, aggregates)
            inside_lines = [ln.rstrip() for ln in inside_stripped.split("\n") if ln is not None]
            expected_lines = [ln.rstrip() for ln in expected_block.split("\n")]

            heading_list_ok = False
            aggregate_ok = False
            if len(inside_lines) >= 1 and len(expected_lines) >= 1:
                expected_hl = expected_lines[:-1]
                actual_hl = inside_lines[:-1]
                heading_list_ok = (actual_hl == expected_hl)
                expected_agg = expected_lines[-1] if expected_lines else ""
                actual_agg = inside_lines[-1] if inside_lines else ""
                aggregate_ok = (actual_agg == expected_agg)

            # Only award syllabus-related points if content inside matches expected
            if heading_list_ok:
                scores["syllabus_block_heading_list_correct"] = 1.0
            if aggregate_ok:
                scores["syllabus_aggregate_line_correct"] = 1.0

            # Outside unchanged only meaningful if the inside block has been correctly updated
            if heading_list_ok and aggregate_ok:
                expected_before = (
                    "# Personal JS Learning Syllabus\n\n"
                    "## Week 1: JavaScript Fundamentals\n"
                    "- Variables, types, and control flow\n"
                    "- Functions and scope\n"
                    "- Arrays and objects\n\n"
                    "## Week 2: React Basics\n"
                    "- Components and props\n"
                    "- State and events\n"
                    "- Simple project: a counter app\n\n"
                    "## Week 3: Networking and State\n"
                )
                expected_after = (
                    "\n\n"
                    "## Week 4: Testing\n"
                    "- Intro to Jest\n"
                    "- Component testing with React Testing Library\n"
                )
                outside_ok = (before == expected_before and after == expected_after)
                scores["syllabus_outside_content_unchanged"] = 1.0 if outside_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()