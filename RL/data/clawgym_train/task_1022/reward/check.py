import json
import csv
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_yaml_config(path: Path) -> Optional[Dict[str, List[str]]]:
    """
    Minimal YAML parser for the expected structure:
    holistic_keywords:
      - ...
    evidence_keywords:
      - ...
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    result: Dict[str, List[str]] = {}
    current_key: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        # Top-level keys
        if not line.startswith(" ") and line.endswith(":"):
            key = line.strip().rstrip(":")
            if key in ("holistic_keywords", "evidence_keywords"):
                current_key = key
                result[current_key] = []
            else:
                # Unknown key; keep going but don't collect
                current_key = None
            continue
        # List items
        m = re.match(r"^\s*-\s*(.+)$", line)
        if m and current_key:
            val = m.group(1).strip()
            result[current_key].append(val)
    # Validate presence
    if "holistic_keywords" not in result or "evidence_keywords" not in result:
        return None
    return result


def _count_substring_case_insensitive(text: str, sub: str) -> int:
    # Count possibly overlapping occurrences of sub (case-insensitive)
    if not sub:
        return 0
    t = text.lower()
    s = sub.lower()
    count = 0
    start = 0
    while True:
        idx = t.find(s, start)
        if idx == -1:
            break
        count += 1
        start = idx + 1
    return count


def _compute_keyword_counts(text: str, keywords: List[str]) -> int:
    total = 0
    for kw in keywords:
        total += _count_substring_case_insensitive(text, kw)
    return total


def _find_present_terms_unique(text: str, terms: List[str]) -> List[str]:
    present = []
    lower_text = text.lower()
    for t in terms:
        if _count_substring_case_insensitive(lower_text, t) > 0:
            present.append(t)
    return present


def _count_citations(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if line.strip().lower().startswith("citation:"):
            count += 1
    return count


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validator_logs_exists_and_complete": 0.0,
        "validator_logs_exit_and_counts_correct": 0.0,
        "metrics_csv_exists_and_complete": 0.0,
        "keyword_counts_and_category_correct": 0.0,
        "validator_counts_in_metrics_correct": 0.0,
        "routed_copies_exist_and_correct": 0.0,
        "aggregates_json_exists_and_correct": 0.0,
        "aggregates_consistent_with_metrics": 0.0,
    }

    input_dir = workspace / "input"
    drafts_dir = input_dir / "drafts"
    config_path = input_dir / "config.yaml"

    # Discover posts
    discovered_posts_paths: List[Path] = sorted(drafts_dir.glob("*.md"))
    discovered_posts: List[str] = [str((Path("input") / "drafts" / p.name).as_posix()) for p in discovered_posts_paths]

    # Load config
    config = _parse_simple_yaml_config(config_path)
    if config is None:
        holistic_keywords: List[str] = []
        evidence_keywords_cfg: List[str] = []
    else:
        holistic_keywords = config.get("holistic_keywords", [])
        evidence_keywords_cfg = config.get("evidence_keywords", [])

    # Validator evidence terms (from validator.py)
    EVIDENCE_TERMS = ["evidence", "randomized", "trial", "peer-reviewed", "systematic", "placebo", "control"]

    # Compute expected metrics from inputs
    expected_by_post: Dict[str, Dict] = {}
    for p in discovered_posts_paths:
        rel_post = str((Path("input") / "drafts" / p.name).as_posix())
        text = _safe_read_text(p) or ""
        holistic_count = _compute_keyword_counts(text, holistic_keywords) if holistic_keywords else 0
        evidence_count = _compute_keyword_counts(text, evidence_keywords_cfg) if evidence_keywords_cfg else 0
        category = "holistic" if holistic_count >= evidence_count else "blogger_evidence"
        present_terms = _find_present_terms_unique(text, EVIDENCE_TERMS)
        present_groups_count = len(present_terms)
        citations = _count_citations(text)
        exit_code = 0 if citations > 0 else 1
        warnings_count = present_groups_count  # one warning per unique evidence term
        errors_count = 1 if citations == 0 else 0
        expected_by_post[rel_post] = {
            "holistic_count": holistic_count,
            "evidence_count": evidence_count,
            "category": category,
            "present_groups_count": present_groups_count,
            "citations": citations,
            "exit_code": exit_code,
            "validator_warning_count": warnings_count,
            "validator_error_count": errors_count,
            "filename": p.name,
            "content": text,
        }

    # Paths to outputs
    logs_path = workspace / "out" / "validation" / "validator_logs.jsonl"
    metrics_path = workspace / "out" / "summary" / "metrics.csv"
    aggregates_path = workspace / "out" / "summary" / "aggregates.json"
    routed_holistic_dir = workspace / "out" / "routed" / "holistic"
    routed_blogger_dir = workspace / "out" / "routed" / "blogger_evidence"

    # Check validator logs presence and completeness
    logs_exists = logs_path.exists() and logs_path.is_file()
    logs_by_post: Dict[str, Dict] = {}
    logs_ok = False
    if logs_exists:
        try:
            lines = logs_path.read_text(encoding="utf-8").splitlines()
            # Each line should be a JSON object with fields: post, exit_code, stdout, stderr
            parse_ok = True
            temp_logs_by_post: Dict[str, Dict] = {}
            for line in lines:
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        parse_ok = False
                        break
                    if not all(k in obj for k in ("post", "exit_code", "stdout", "stderr")):
                        parse_ok = False
                        break
                    if not isinstance(obj["post"], str):
                        parse_ok = False
                        break
                    if not isinstance(obj["exit_code"], int):
                        parse_ok = False
                        break
                    if not isinstance(obj["stdout"], str) or not isinstance(obj["stderr"], str):
                        parse_ok = False
                        break
                    # Ensure unique per post
                    if obj["post"] in temp_logs_by_post:
                        parse_ok = False
                        break
                    temp_logs_by_post[obj["post"]] = {
                        "exit_code": obj["exit_code"],
                        "stdout": obj["stdout"],
                        "stderr": obj["stderr"],
                    }
                except Exception:
                    parse_ok = False
                    break
            # Completeness: number of lines equals number of discovered posts and posts match
            if parse_ok:
                posts_in_logs = set(temp_logs_by_post.keys())
                expected_posts_set = set(discovered_posts)
                if posts_in_logs == expected_posts_set and len(lines) == len(discovered_posts):
                    logs_by_post = temp_logs_by_post
                    logs_ok = True
        except Exception:
            logs_ok = False
    scores["validator_logs_exists_and_complete"] = 1.0 if logs_ok else 0.0

    # Check logs content correctness vs expected (exit codes, warnings/errors counts, stdout numbers)
    logs_content_ok = False
    if logs_ok:
        content_ok = True
        for post, exp in expected_by_post.items():
            log = logs_by_post.get(post, None)
            if log is None:
                content_ok = False
                break
            # Exit code
            if log["exit_code"] != exp["exit_code"]:
                content_ok = False
                break
            # Count warnings and errors in stderr lines
            stderr = log["stderr"]
            warn_count = sum(1 for ln in stderr.splitlines() if ln.startswith("Warning:"))
            err_count = sum(1 for ln in stderr.splitlines() if ln.startswith("Error:"))
            if warn_count != exp["validator_warning_count"] or err_count != exp["validator_error_count"]:
                content_ok = False
                break
            # Parse stdout numbers
            stdout = log["stdout"]
            # Extract present_groups_count
            m_groups = re.search(r":\s*(\d+)\s+evidence-centric term groups present", stdout)
            m_cit = re.search(r"Citations found:\s*(\d+)", stdout)
            if not m_groups or not m_cit:
                content_ok = False
                break
            try:
                groups_num = int(m_groups.group(1))
                cits_num = int(m_cit.group(1))
            except Exception:
                content_ok = False
                break
            if groups_num != exp["present_groups_count"] or cits_num != exp["citations"]:
                content_ok = False
                break
        logs_content_ok = content_ok
    scores["validator_logs_exit_and_counts_correct"] = 1.0 if logs_content_ok else 0.0

    # Check metrics.csv presence and completeness
    metrics_exists = metrics_path.exists() and metrics_path.is_file()
    metrics_by_post: Dict[str, Dict] = {}
    metrics_ok = False
    header_expected = ["post", "holistic_count", "evidence_count", "category", "validator_warning_count", "validator_error_count"]
    if metrics_exists:
        try:
            with metrics_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if not rows:
                metrics_ok = False
            else:
                header = rows[0]
                if header != header_expected:
                    metrics_ok = False
                else:
                    parse_ok = True
                    temp_metrics: Dict[str, Dict] = {}
                    for r in rows[1:]:
                        if len(r) != len(header_expected):
                            parse_ok = False
                            break
                        post, hol_s, ev_s, cat, warn_s, err_s = r
                        if post in temp_metrics:
                            parse_ok = False
                            break
                        try:
                            hol = int(hol_s)
                            ev = int(ev_s)
                            warn = int(warn_s)
                            err = int(err_s)
                        except Exception:
                            parse_ok = False
                            break
                        if cat not in ("holistic", "blogger_evidence"):
                            parse_ok = False
                            break
                        temp_metrics[post] = {
                            "holistic_count": hol,
                            "evidence_count": ev,
                            "category": cat,
                            "validator_warning_count": warn,
                            "validator_error_count": err,
                        }
                    if parse_ok:
                        # Completeness: same posts as discovered
                        if set(temp_metrics.keys()) == set(discovered_posts) and len(temp_metrics) == len(discovered_posts):
                            metrics_by_post = temp_metrics
                            metrics_ok = True
        except Exception:
            metrics_ok = False
    scores["metrics_csv_exists_and_complete"] = 1.0 if metrics_ok else 0.0

    # Check keyword counts and category correctness in metrics vs expected
    counts_and_category_ok = False
    if metrics_ok and expected_by_post:
        ok = True
        for post, exp in expected_by_post.items():
            row = metrics_by_post.get(post)
            if row is None:
                ok = False
                break
            if row["holistic_count"] != exp["holistic_count"]:
                ok = False
                break
            if row["evidence_count"] != exp["evidence_count"]:
                ok = False
                break
            # Category correctness defined by counts: holistic_count >= evidence_count => holistic else blogger_evidence
            expected_category = exp["category"]
            if row["category"] != expected_category:
                ok = False
                break
        counts_and_category_ok = ok
    scores["keyword_counts_and_category_correct"] = 1.0 if counts_and_category_ok else 0.0

    # Check validator counts in metrics are correct
    validator_counts_ok = False
    if metrics_ok and expected_by_post:
        ok = True
        for post, exp in expected_by_post.items():
            row = metrics_by_post.get(post)
            if row is None:
                ok = False
                break
            if row["validator_warning_count"] != exp["validator_warning_count"]:
                ok = False
                break
            if row["validator_error_count"] != exp["validator_error_count"]:
                ok = False
                break
        validator_counts_ok = ok
    scores["validator_counts_in_metrics_correct"] = 1.0 if validator_counts_ok else 0.0

    # Check routed copies exist and match expected category and content
    routed_ok = False
    if expected_by_post:
        ok = True
        for post, exp in expected_by_post.items():
            filename = Path(post).name
            if exp["category"] == "holistic":
                expected_path = routed_holistic_dir / filename
            else:
                expected_path = routed_blogger_dir / filename
            if not expected_path.exists() or not expected_path.is_file():
                ok = False
                break
            routed_text = _safe_read_text(expected_path)
            if routed_text is None or routed_text != exp["content"]:
                ok = False
                break
        routed_ok = ok
    scores["routed_copies_exist_and_correct"] = 1.0 if routed_ok else 0.0

    # Check aggregates.json exists and is correct vs expected and consistent with metrics
    aggregates_exists = aggregates_path.exists() and aggregates_path.is_file()
    aggregates_ok = False
    aggregates_consistent = False
    if aggregates_exists and expected_by_post:
        try:
            agg_obj = json.loads(aggregates_path.read_text(encoding="utf-8"))
            # Validate required keys
            required_keys = {
                "total_posts",
                "count_by_category",
                "avg_holistic_count",
                "avg_evidence_count",
                "percent_with_validator_warnings",
                "percent_with_validator_errors",
            }
            if not isinstance(agg_obj, dict) or set(agg_obj.keys()) != required_keys:
                aggregates_ok = False
            else:
                # Compute expected from ground truth
                total = len(expected_by_post)
                expected_counts_by_cat = {"holistic": 0, "blogger_evidence": 0}
                sum_hol = 0
                sum_ev = 0
                with_warn = 0
                with_err = 0
                for exp in expected_by_post.values():
                    expected_counts_by_cat[exp["category"]] += 1
                    sum_hol += exp["holistic_count"]
                    sum_ev += exp["evidence_count"]
                    if exp["validator_warning_count"] > 0:
                        with_warn += 1
                    if exp["validator_error_count"] > 0:
                        with_err += 1
                expected_avg_hol = (sum_hol / total) if total > 0 else 0.0
                expected_avg_ev = (sum_ev / total) if total > 0 else 0.0
                expected_pct_warn = (with_warn * 100.0 / total) if total > 0 else 0.0
                expected_pct_err = (with_err * 100.0 / total) if total > 0 else 0.0

                # Validate types
                types_ok = (
                    isinstance(agg_obj["total_posts"], int) and
                    isinstance(agg_obj["count_by_category"], dict) and
                    all(k in agg_obj["count_by_category"] for k in ("holistic", "blogger_evidence")) and
                    isinstance(agg_obj["count_by_category"]["holistic"], int) and
                    isinstance(agg_obj["count_by_category"]["blogger_evidence"], int) and
                    isinstance(agg_obj["avg_holistic_count"], (int, float)) and
                    isinstance(agg_obj["avg_evidence_count"], (int, float)) and
                    isinstance(agg_obj["percent_with_validator_warnings"], (int, float)) and
                    isinstance(agg_obj["percent_with_validator_errors"], (int, float))
                )
                if types_ok:
                    # Compare values
                    vals_ok = (
                        agg_obj["total_posts"] == total and
                        agg_obj["count_by_category"]["holistic"] == expected_counts_by_cat["holistic"] and
                        agg_obj["count_by_category"]["blogger_evidence"] == expected_counts_by_cat["blogger_evidence"] and
                        _approx_equal(float(agg_obj["avg_holistic_count"]), expected_avg_hol) and
                        _approx_equal(float(agg_obj["avg_evidence_count"]), expected_avg_ev) and
                        _approx_equal(float(agg_obj["percent_with_validator_warnings"]), expected_pct_warn) and
                        _approx_equal(float(agg_obj["percent_with_validator_errors"]), expected_pct_err)
                    )
                    aggregates_ok = vals_ok
                else:
                    aggregates_ok = False

                # Consistency with metrics.csv (if metrics_ok)
                if metrics_ok:
                    total_m = len(metrics_by_post)
                    sum_hol_m = sum(v["holistic_count"] for v in metrics_by_post.values())
                    sum_ev_m = sum(v["evidence_count"] for v in metrics_by_post.values())
                    with_warn_m = sum(1 for v in metrics_by_post.values() if v["validator_warning_count"] > 0)
                    with_err_m = sum(1 for v in metrics_by_post.values() if v["validator_error_count"] > 0)
                    count_by_cat_m = {"holistic": 0, "blogger_evidence": 0}
                    for v in metrics_by_post.values():
                        count_by_cat_m[v["category"]] += 1
                    avg_hol_m = (sum_hol_m / total_m) if total_m > 0 else 0.0
                    avg_ev_m = (sum_ev_m / total_m) if total_m > 0 else 0.0
                    pct_warn_m = (with_warn_m * 100.0 / total_m) if total_m > 0 else 0.0
                    pct_err_m = (with_err_m * 100.0 / total_m) if total_m > 0 else 0.0
                    aggregates_consistent = (
                        agg_obj["total_posts"] == total_m and
                        agg_obj["count_by_category"].get("holistic") == count_by_cat_m["holistic"] and
                        agg_obj["count_by_category"].get("blogger_evidence") == count_by_cat_m["blogger_evidence"] and
                        _approx_equal(float(agg_obj["avg_holistic_count"]), avg_hol_m) and
                        _approx_equal(float(agg_obj["avg_evidence_count"]), avg_ev_m) and
                        _approx_equal(float(agg_obj["percent_with_validator_warnings"]), pct_warn_m) and
                        _approx_equal(float(agg_obj["percent_with_validator_errors"]), pct_err_m)
                    )
                else:
                    aggregates_consistent = False
        except Exception:
            aggregates_ok = False
            aggregates_consistent = False

    scores["aggregates_json_exists_and_correct"] = 1.0 if aggregates_ok else 0.0
    scores["aggregates_consistent_with_metrics"] = 1.0 if aggregates_consistent else 0.0

    return scores


def main() -> None:
        workspace = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade([], workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()