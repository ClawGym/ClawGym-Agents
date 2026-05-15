import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET
import importlib.util


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows
    except Exception:
        return None


def _compute_expected_summary(sessions_path: Path) -> Optional[Dict[str, Any]]:
    sessions = _safe_load_jsonl(sessions_path)
    if sessions is None:
        return None
    all_ends: List[int] = []
    dist_ends: Dict[int, List[int]] = {}
    total_arrows = 0
    for s in sessions:
        ends = s.get("end_totals", [])
        arrows_per_end = int(s.get("arrows_per_end", 0) or 0)
        d = s.get("distance_m", None)
        try:
            d_int = int(d) if d is not None else None
        except Exception:
            d_int = None
        all_ends.extend(ends)
        if d_int is None:
            # Use a sentinel for unknown; not expected here but keep stable
            d_int = -1
        dist_ends.setdefault(d_int, []).extend(ends)
        total_arrows += len(ends) * arrows_per_end
    total_ends = len(all_ends)
    avg = round(sum(all_ends) / total_ends, 1) if total_ends else 0.0
    best = max(all_ends) if all_ends else 0
    distances: Dict[int, Dict[str, Any]] = {}
    for d, vals in dist_ends.items():
        if vals:
            distances[d] = {"ends": len(vals), "avg": round(sum(vals) / len(vals), 1)}
        else:
            distances[d] = {"ends": 0, "avg": 0.0}
    return {
        "total_ends": total_ends,
        "total_arrows": total_arrows,
        "avg_score": avg,
        "best_end": best,
        "distances": distances,
    }


def _normalize_distances_keys_to_int(distances: Any) -> Optional[Dict[int, Dict[str, Any]]]:
    if not isinstance(distances, dict):
        return None
    norm: Dict[int, Dict[str, Any]] = {}
    try:
        for k, v in distances.items():
            if isinstance(k, int):
                key_int = k
            else:
                key_int = int(str(k).strip())
            if not isinstance(v, dict):
                return None
            ends = v.get("ends", None)
            avg = v.get("avg", None)
            if ends is None or avg is None:
                return None
            if not isinstance(ends, int):
                # Allow numeric that can be cast to int exactly
                try:
                    ends = int(ends)
                except Exception:
                    return None
            if not isinstance(avg, (int, float)):
                try:
                    avg = float(avg)
                except Exception:
                    return None
            norm[key_int] = {"ends": int(ends), "avg": round(float(avg), 1)}
        return norm
    except Exception:
        return None


def _parse_junit_xml(path: Path) -> Optional[Tuple[int, int, int]]:
    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
        total_tests = 0
        total_failures = 0
        total_errors = 0
        if root.tag == "testsuite":
            total_tests = int(root.attrib.get("tests", "0"))
            total_failures = int(root.attrib.get("failures", "0"))
            total_errors = int(root.attrib.get("errors", "0"))
        elif root.tag == "testsuites":
            for suite in root.findall("testsuite"):
                total_tests += int(suite.attrib.get("tests", "0"))
                total_failures += int(suite.attrib.get("failures", "0"))
                total_errors += int(suite.attrib.get("errors", "0"))
        else:
            # Try to sum across nested
            for suite in root.findall(".//testsuite"):
                total_tests += int(suite.attrib.get("tests", "0"))
                total_failures += int(suite.attrib.get("failures", "0"))
                total_errors += int(suite.attrib.get("errors", "0"))
        return (total_tests, total_failures, total_errors)
    except Exception:
        return None


def _import_module_from_path(module_name: str, path: Path):
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        return module
    except Exception:
        return None


def _regex_number_present(text: str, number_str: str) -> bool:
    # Ensure the number appears as a standalone numeric (not part of a larger number)
    # Escape dot for regex and assemble boundaries
    pattern = r"(?<!\d)" + re.escape(number_str) + r"(?!\d)"
    return re.search(pattern, text) is not None


def _has_distance_avg(msg: str, dist: int, avg: float) -> bool:
    # Contains 'avg' and the specific average value and the distance token like "18m" or "18 m"
    msg_low = msg.lower()
    if "avg" not in msg_low:
        return False
    dist_pattern = r"\b" + re.escape(str(dist)) + r"\s*m\b"
    if re.search(dist_pattern, msg_low) is None:
        return False
    avg_str = f"{avg:.1f}"
    return _regex_number_present(msg_low, avg_str)


def _summary_keys_and_types_ok(summary: Any) -> bool:
    if not isinstance(summary, dict):
        return False
    required = ["total_ends", "total_arrows", "avg_score", "best_end", "distances"]
    for k in required:
        if k not in summary:
            return False
    if not isinstance(summary["total_ends"], int):
        return False
    if not isinstance(summary["total_arrows"], int):
        return False
    if not isinstance(summary["avg_score"], (int, float)):
        return False
    if not isinstance(summary["best_end"], (int, float)):
        # best_end should be int but accept numeric
        return False
    if not isinstance(summary["distances"], dict):
        return False
    # Validate inner maps
    norm = _normalize_distances_keys_to_int(summary["distances"])
    return norm is not None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "tests_dir_present": 0.0,
        "junit_report_exists": 0.0,
        "junit_all_tests_passed": 0.0,
        "summary_json_exists": 0.0,
        "summary_keys_and_structure": 0.0,
        "summary_values_correct": 0.0,
        "status_message_from_summary_ok": 0.0,
        "empty_summary_status_ok": 0.0,
        "messages_rewritten_exists": 0.0,
        "messages_rewritten_three_lines": 0.0,
        "messages_rewritten_line_lengths_ok": 0.0,
        "messages_rewritten_topics_ok": 0.0,
    }

    # Check tests directory presence
    tests_dir = workspace / "tests"
    if tests_dir.exists() and tests_dir.is_dir():
        # look for at least one test_*.py
        test_files = list(tests_dir.rglob("test_*.py"))
        if len(test_files) > 0:
            scores["tests_dir_present"] = 1.0

    # Check JUnit report
    junit_path = workspace / "out" / "test-results.xml"
    if junit_path.exists() and junit_path.is_file():
        scores["junit_report_exists"] = 1.0
        parsed = _parse_junit_xml(junit_path)
        if parsed is not None:
            total, failures, errors = parsed
            if total > 0 and failures == 0 and errors == 0:
                scores["junit_all_tests_passed"] = 1.0

    # Expected summary from input
    sessions_path = workspace / "input" / "sessions.jsonl"
    expected_summary = _compute_expected_summary(sessions_path) if sessions_path.exists() else None

    # Check out/summary.json
    summary_path = workspace / "out" / "summary.json"
    summary_data = None
    if summary_path.exists() and summary_path.is_file():
        scores["summary_json_exists"] = 1.0
        summary_data = _safe_read_json(summary_path)
        if summary_data is not None and _summary_keys_and_types_ok(summary_data):
            scores["summary_keys_and_structure"] = 1.0

    # Compare values with expected
    if expected_summary is not None and summary_data is not None:
        try:
            # Normalize for comparison
            out_total_ends = int(summary_data.get("total_ends"))
            out_total_arrows = int(summary_data.get("total_arrows"))
            out_avg_score = round(float(summary_data.get("avg_score")), 1)
            out_best_end = int(summary_data.get("best_end"))
            out_distances = _normalize_distances_keys_to_int(summary_data.get("distances"))
            if out_distances is None:
                raise ValueError("Distances malformed")

            exp_total_ends = int(expected_summary["total_ends"])
            exp_total_arrows = int(expected_summary["total_arrows"])
            exp_avg_score = round(float(expected_summary["avg_score"]), 1)
            exp_best_end = int(expected_summary["best_end"])
            exp_distances = expected_summary["distances"]  # already int keys
            # Strict compare of distances entries
            dists_equal = True
            if set(out_distances.keys()) != set(exp_distances.keys()):
                dists_equal = False
            else:
                for k in out_distances.keys():
                    if out_distances[k]["ends"] != exp_distances[k]["ends"]:
                        dists_equal = False
                        break
                    if round(float(out_distances[k]["avg"]), 1) != round(float(exp_distances[k]["avg"]), 1):
                        dists_equal = False
                        break

            if (
                out_total_ends == exp_total_ends
                and out_total_arrows == exp_total_arrows
                and out_best_end == exp_best_end
                and out_avg_score == exp_avg_score
                and dists_equal
            ):
                scores["summary_values_correct"] = 1.0
        except Exception:
            pass

    # Import app/archery_stats.py to check format_status behavior
    module = _import_module_from_path("app.archery_stats", workspace / "app" / "archery_stats.py")

    # Status message from summary.json
    if module is not None and summary_data is not None and hasattr(module, "format_status"):
        try:
            msg = module.format_status(summary_data)  # type: ignore[attr-defined]
            if isinstance(msg, str):
                single_line = ("\n" not in msg) and ("\r" not in msg)
                within_120 = len(msg) <= 120
                # Check includes overall avg and best_end
                avg_str = f"{round(float(summary_data.get('avg_score', 0.0)), 1):.1f}"
                best_val = str(int(summary_data.get("best_end", 0)))
                avg_present = _regex_number_present(msg, avg_str)
                best_present = _regex_number_present(msg, best_val)

                # Check at least one distance average mention
                dist_map = _normalize_distances_keys_to_int(summary_data.get("distances"))
                has_one_dist_avg = False
                if dist_map:
                    for d, v in dist_map.items():
                        if _has_distance_avg(msg, d, float(v.get("avg", 0.0))):
                            has_one_dist_avg = True
                            break

                if single_line and within_120 and avg_present and best_present and has_one_dist_avg:
                    scores["status_message_from_summary_ok"] = 1.0
        except Exception:
            pass

    # Empty summary status behavior
    if module is not None and hasattr(module, "summarize_sessions") and hasattr(module, "format_status"):
        try:
            empty_summary = module.summarize_sessions([])  # type: ignore[attr-defined]
            empty_msg = module.format_status(empty_summary)  # type: ignore[attr-defined]
            if isinstance(empty_msg, str):
                single_line = ("\n" not in empty_msg) and ("\r" not in empty_msg)
                within_120 = len(empty_msg) <= 120
                # Look for any phrasing indicating no sessions yet
                eml = empty_msg.lower()
                indicative_phrases = [
                    "no session",
                    "no sessions",
                    "no practice",
                    "no data",
                    "no logs",
                    "nothing yet",
                    "nothing logged",
                    "nothing recorded",
                    "not yet",
                    "yet to start",
                    "start when ready",
                    "when you're ready",
                    "when you are ready",
                ]
                indicates_none = any(p in eml for p in indicative_phrases)
                if single_line and within_120 and indicates_none:
                    scores["empty_summary_status_ok"] = 1.0
        except Exception:
            pass

    # Messages rewritten checks
    messages_out = workspace / "out" / "messages_rewritten.md"
    if messages_out.exists() and messages_out.is_file():
        scores["messages_rewritten_exists"] = 1.0
        text = _safe_read_text(messages_out)
        if text is not None:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
            if len(lines) == 3:
                scores["messages_rewritten_three_lines"] = 1.0
                # Length checks
                if all(len(ln) <= 120 and not ln.startswith("#") for ln in lines):
                    scores["messages_rewritten_line_lengths_ok"] = 1.0
                # Topic checks
                topics_ok = True
                # Line 1: practice summary context
                l1 = lines[0].lower()
                l1_need = [
                    "practice",
                    "session",
                    "end",
                    "average",
                    "avg",
                    "breath",
                    "pace",
                    "consistency",
                    "groups",
                    "form",
                    "recap",
                    "today",
                ]
                if not any(t in l1 for t in l1_need):
                    topics_ok = False
                # Line 2: pre-competition encouragement context
                l2 = lines[1].lower()
                l2_need = [
                    "competition",
                    "event",
                    "calm",
                    "centered",
                    "focus",
                    "form",
                    "follow-through",
                    "follow through",
                    "routine",
                    "ready",
                    "trust",
                ]
                if not any(t in l2 for t in l2_need):
                    topics_ok = False
                # Line 3: missed session note context
                l3 = lines[2].lower()
                l3_need = [
                    "missed",
                    "make-up",
                    "make up",
                    "plan",
                    "momentum",
                    "skip",
                    "reschedule",
                    "homework",
                    "family",
                    "next",
                    "tomorrow",
                ]
                if not any(t in l3 for t in l3_need):
                    topics_ok = False
                if topics_ok:
                    scores["messages_rewritten_topics_ok"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()