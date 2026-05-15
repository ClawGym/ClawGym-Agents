import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json_obj(path: Path) -> Optional[Any]:
    text = _safe_read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _compute_expected_summary_from_csv(csv_path: Path) -> Optional[Dict[str, Any]]:
    if not csv_path.exists():
        return None
    topic_counts: Dict[str, int] = {}
    source_titles: Dict[str, List[str]] = {}
    try:
        with csv_path.open(newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                t = (row.get("topic") or "").strip()
                s = (row.get("source") or "").strip()
                title = (row.get("title") or "").strip()
                if t:
                    topic_counts[t] = topic_counts.get(t, 0) + 1
                if s:
                    if s not in source_titles:
                        source_titles[s] = []
                    if title and title not in source_titles[s]:
                        source_titles[s].append(title)
    except Exception:
        return None
    summary = {
        "topics": topic_counts,
        "sources": {k: len(v) for k, v in source_titles.items()},
    }
    return summary


def _is_sorted_all_levels_text(text: str) -> bool:
    # Validate that keys at top-level and within "topics" and "sources" are sorted lexicographically.
    try:
        root_pairs = json.loads(text, object_pairs_hook=list)
        if not isinstance(root_pairs, list):
            return False
        top_keys = [k for k, _ in root_pairs]
        if top_keys != sorted(top_keys):
            return False
    except Exception:
        return False

    def extract_object_keys(block_text: str) -> List[str]:
        # Extract flat dict keys in the order they appear.
        return [m.group(1) for m in re.finditer(r'"\s*([^"\\]+)\s*"\s*:', block_text)]

    def find_object_for_key(full_text: str, key: str) -> Optional[str]:
        pattern = r'"\s*' + re.escape(key) + r'\s*"\s*:\s*\{'
        m = re.search(pattern, full_text)
        if not m:
            return None
        start = m.end() - 1  # position at '{'
        brace_count = 0
        i = start
        while i < len(full_text):
            c = full_text[i]
            if c == '{':
                brace_count += 1
            elif c == '}':
                brace_count -= 1
                if brace_count == 0:
                    return full_text[start : i + 1]
            i += 1
        return None

    for sub in ("sources", "topics"):
        obj_text = find_object_for_key(text, sub)
        if obj_text is None:
            return False
        keys = extract_object_keys(obj_text)
        if keys != sorted(keys):
            return False
    return True


def _all_int_counts(summary: Any) -> bool:
    if not isinstance(summary, dict):
        return False
    for k in ("topics", "sources"):
        sub = summary.get(k)
        if not isinstance(sub, dict):
            return False
        for v in sub.values():
            if not isinstance(v, int) or isinstance(v, bool):
                return False
    return True


def _compute_diff(original: Dict[str, Any], refactored: Dict[str, Any]) -> Dict[str, Any]:
    def diff_section(k: str) -> List[Dict[str, Any]]:
        a = original.get(k, {}) if isinstance(original.get(k), dict) else {}
        b = refactored.get(k, {}) if isinstance(refactored.get(k), dict) else {}
        keys = sorted(set(a.keys()) | set(b.keys()))
        diffs: List[Dict[str, Any]] = []
        for key in keys:
            av = a.get(key)
            bv = b.get(key)
            if av != bv:
                diffs.append({"key": key, "original": av if av is not None else None, "refactored": bv if bv is not None else None})
        return diffs

    topics_d = diff_section("topics")
    sources_d = diff_section("sources")
    return {
        "equal": len(topics_d) == 0 and len(sources_d) == 0,
        "differences": {
            "topics": topics_d,
            "sources": sources_d,
        },
    }


def _validate_diff_schema(diff_obj: Any) -> bool:
    if not isinstance(diff_obj, dict):
        return False
    if "equal" not in diff_obj or "differences" not in diff_obj:
        return False
    if not isinstance(diff_obj["equal"], bool):
        return False
    diffs = diff_obj["differences"]
    if not isinstance(diffs, dict):
        return False
    for key in ("topics", "sources"):
        if key not in diffs or not isinstance(diffs[key], list):
            return False
        for item in diffs[key]:
            if not isinstance(item, dict):
                return False
            if set(item.keys()) != {"key", "original", "refactored"}:
                return False
            if not isinstance(item["key"], str):
                return False
            if not (item["original"] is None or isinstance(item["original"], int)) and not isinstance(item["original"], bool):
                return False
            if not (item["refactored"] is None or isinstance(item["refactored"], int)) and not isinstance(item["refactored"], bool):
                return False
    return True


def _sources_json_valid(path: Path) -> Tuple[bool, bool]:
    """
    Returns (structure_ok, official_sources_ok)
    - structure_ok: has required fields and >=2 entries
    - official_sources_ok: at least two authoritative/official sources referenced (by org or content) with UTC access date indicator
    """
    obj = _safe_load_json_obj(path)
    if not isinstance(obj, list) or len(obj) < 2:
        return False, False
    structure_ok = True
    official_count = 0
    for item in obj:
        if not isinstance(item, dict):
            structure_ok = False
            continue
        required = ["query", "title", "publisher_or_org", "access_date_utc", "short_note"]
        for f in required:
            if f not in item or not isinstance(item[f], str) or not item[f].strip():
                structure_ok = False
        access = item.get("access_date_utc", "")
        utc_hint = access.endswith("Z") or "+00:00" in access or "UTC" in access.upper()
        pub = item.get("publisher_or_org", "")
        title = item.get("title", "")
        is_official = (
            "python software foundation" in pub.lower()
            or "docs.python.org" in title.lower()
            or "pep 8" in title.lower()
            or "pep 8" in pub.lower()
            or "python.org" in pub.lower()
        )
        if is_official and utc_hint:
            official_count += 1
    official_sources_ok = official_count >= 2
    return structure_ok, official_sources_ok


def _check_refactored_file_static(path: Path) -> Dict[str, float]:
    scores: Dict[str, float] = {
        "refactored_file_exists": 0.0,
        "refactored_uses_logging_news_agg_logger": 0.0,
        "refactored_cli_has_required_args": 0.0,
        "refactored_has_log_level_option": 0.0,
        "refactored_logs_to_stdout": 0.0,
        "refactored_no_print_statements": 0.0,
        "refactored_has_main_guard": 0.0,
        "refactored_uses_dataclass": 0.0,
        "refactored_has_type_hints_in_functions": 0.0,
        "refactored_header_references_sources": 0.0,
    }
    if not path.exists():
        return scores
    scores["refactored_file_exists"] = 1.0
    text = _safe_read_text(path) or ""
    if re.search(r'getLogger\(\s*[\'"]news_agg[\'"]\s*\)', text):
        scores["refactored_uses_logging_news_agg_logger"] = 1.0
    if "argparse" in text and "--input" in text and "--out" in text:
        scores["refactored_cli_has_required_args"] = 1.0
    if "--log-level" in text:
        scores["refactored_has_log_level_option"] = 1.0
    if "logging" in text and "sys.stdout" in text and ("StreamHandler" in text or "basicConfig" in text):
        scores["refactored_logs_to_stdout"] = 1.0
    has_print_code = any(re.match(r'^\s*print\s*\(', line) for line in text.splitlines())
    scores["refactored_no_print_statements"] = 1.0 if not has_print_code else 0.0
    if "__name__" in text and "if __name__ ==" in text:
        scores["refactored_has_main_guard"] = 1.0
    if "@dataclass" in text:
        scores["refactored_uses_dataclass"] = 1.0
    has_type_hint = any(re.match(r'^\s*def\s+\w+\s*\(.*\)\s*->\s*[\w\[\],\. ]+\s*:', line) for line in text.splitlines())
    scores["refactored_has_type_hints_in_functions"] = 1.0 if has_type_hint else 0.0
    top_lines = "\n".join(text.splitlines()[:40]).lower()
    mentions_pep8 = ("pep 8" in top_lines) or ("style guide for python code" in top_lines)
    mentions_logging = ("logging howto" in top_lines) or ("docs.python.org" in top_lines and "logging" in top_lines) or ("python software foundation" in top_lines and "logging" in top_lines)
    scores["refactored_header_references_sources"] = 1.0 if (mentions_pep8 and mentions_logging) else 0.0
    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "refactored_file_exists": 0.0,
        "refactored_uses_logging_news_agg_logger": 0.0,
        "refactored_cli_has_required_args": 0.0,
        "refactored_has_log_level_option": 0.0,
        "refactored_logs_to_stdout": 0.0,
        "refactored_no_print_statements": 0.0,
        "refactored_has_main_guard": 0.0,
        "refactored_uses_dataclass": 0.0,
        "refactored_has_type_hints_in_functions": 0.0,
        "refactored_header_references_sources": 0.0,
        "original_output_matches_expected": 0.0,
        "refactored_output_matches_expected": 0.0,
        "refactored_output_sorted_keys": 0.0,
        "refactored_counts_are_integers": 0.0,
        "diff_json_schema_valid": 0.0,
        "diff_json_correct_comparison": 0.0,
        "sources_json_structure": 0.0,
        "sources_json_official": 0.0,
        "email_to_editor_mentions": 0.0,
    }

    refactored_path = workspace / "out" / "bulletin_aggregator_refactored.py"
    static_scores = _check_refactored_file_static(refactored_path)
    scores.update(static_scores)

    input_csv = workspace / "input" / "sample_headlines.csv"
    expected = _compute_expected_summary_from_csv(input_csv)

    orig_path = workspace / "out" / "original_summary.json"
    orig_obj = _safe_load_json_obj(orig_path)
    if expected is not None and isinstance(orig_obj, dict) and (orig_obj == expected):
        scores["original_output_matches_expected"] = 1.0

    ref_path = workspace / "out" / "refactored_summary.json"
    ref_text = _safe_read_text(ref_path) or ""
    try:
        ref_obj = json.loads(ref_text)
    except Exception:
        ref_obj = None
    if expected is not None and isinstance(ref_obj, dict) and (ref_obj == expected):
        scores["refactored_output_matches_expected"] = 1.0
    if ref_text and _is_sorted_all_levels_text(ref_text):
        scores["refactored_output_sorted_keys"] = 1.0
    if isinstance(ref_obj, dict) and _all_int_counts(ref_obj):
        scores["refactored_counts_are_integers"] = 1.0

    diff_path = workspace / "out" / "diff.json"
    diff_obj = _safe_load_json_obj(diff_path)
    if _validate_diff_schema(diff_obj):
        scores["diff_json_schema_valid"] = 1.0
        if isinstance(orig_obj, dict) and isinstance(ref_obj, dict):
            computed_diff = _compute_diff(orig_obj, ref_obj)
            if computed_diff == diff_obj:
                scores["diff_json_correct_comparison"] = 1.0

    sources_path = workspace / "out" / "sources.json"
    struct_ok, official_ok = _sources_json_valid(sources_path)
    scores["sources_json_structure"] = 1.0 if struct_ok else 0.0
    scores["sources_json_official"] = 1.0 if official_ok else 0.0

    email_path = workspace / "out" / "email_to_editor.md"
    email_text = _safe_read_text(email_path) or ""
    mentions_diff = "diff.json" in email_text
    mentions_benefits = ("safer" in email_text.lower()) or ("cleaner" in email_text.lower()) or ("maintainable" in email_text.lower())
    mentions_chief = ("chief of staff" in email_text.lower())
    mentions_joe = ("joe" in email_text.lower())
    if email_text and mentions_diff and mentions_benefits and mentions_chief and mentions_joe:
        scores["email_to_editor_mentions"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()