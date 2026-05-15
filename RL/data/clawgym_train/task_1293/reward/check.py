import json
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_scalar(value: str) -> Any:
    v = value.strip()
    if v == "" or v == "null" or v == "None":
        return None
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    # number?
    try:
        if "." in v or "e" in v.lower():
            return float(v)
        return int(v)
    except Exception:
        return v


def _load_yaml_minimal(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML loader sufficient for the provided config/editorial.yaml.
    Supports:
      - top-level mappings
      - nested mappings with 2-space indentation
      - lists of scalars (e.g., report_fields)
      - quoted strings and basic numeric/boolean scalars
    """
    text = _safe_read_text(path)
    if text is None:
        return None

    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Any, Optional[str]]] = [(0, root, None)]  # (indent, container, current_key_for_list_parent)

    current_key_for_list_parent: Optional[str] = None

    def current_container() -> Any:
        return stack[-1][1]

    def current_indent() -> int:
        return stack[-1][0]

    for raw_line in lines:
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 != 0:
            # Only handle multiples of 2 spaces
            return None

        # Pop to the correct indentation level
        while stack and indent < current_indent():
            stack.pop()
        if indent > current_indent():
            # Indentation must increase exactly by 2 relative to previous line
            if indent != current_indent() + 2:
                return None

        container = current_container()
        stripped = line.strip()

        if stripped.startswith("- "):
            # List item
            item = stripped[2:].strip()
            # Ensure current container is a list
            if not isinstance(container, list):
                # Need to convert the current (dict, key) to list if parent had pending key
                # Find parent container with dict and key
                if len(stack) >= 2 and isinstance(stack[-2][1], dict) and isinstance(container, dict):
                    # This scenario shouldn't occur in our limited parser
                    return None
                else:
                    # Create a list under the last key of the parent dict
                    # If current container isn't list, it must be dict and we added a key with value None in previous step
                    # Find the most recent dict with a pending key
                    if current_key_for_list_parent is None:
                        return None
            # Parse the item scalar if present, else prepare for nested structures
            if item == "":
                # Nested structures under list item not needed for this config
                return None
            container.append(_parse_scalar(item))
            continue

        if ":" in stripped:
            key, after = stripped.split(":", 1)
            key = key.strip()
            value = after.strip()
            if isinstance(container, dict):
                if value == "":
                    # Determine whether next lines form a dict or list
                    # Look ahead is complex; we set placeholder and wait for next lines
                    # For this minimal parser, we default to dict unless we see immediate "- " on next line
                    # Peek next non-empty, non-comment line
                    # Note: We'll tentatively create dict; if next line is "- ", we convert to list
                    # To enable conversion, we maintain a marker of last key to allow list creation
                    new_map: Dict[str, Any] = {}
                    container[key] = new_map
                    stack.append((indent + 2, new_map, None))
                    current_key_for_list_parent = key
                else:
                    # scalar value
                    container[key] = _parse_scalar(value)
                    current_key_for_list_parent = None
            else:
                return None

            # If the next line is a list item, we need to adjust the last inserted dict to a list
            # This requires peeking ahead in the original lines; implement a simple lookahead
            continue

        # If we encounter a list item after a key with empty value, convert the dict to list
        # The above logic can't easily handle dynamic lookahead; therefore implement a secondary pass:
        # To keep robustness, if parsing reaches here with unknown pattern, return None
        return None

    # Second pass to correct places where a dict with no entries indicates a list parent
    # For our config, we only need to ensure that "report_fields" is a list
    # If root contains "report_fields" and it is an empty dict, fix it by reading raw lines to populate the list
    if "report_fields" in root and isinstance(root["report_fields"], dict):
        # Re-parse just the report_fields list
        rf_list: List[str] = []
        in_rf = False
        rf_indent = None
        for raw_line in lines:
            line = raw_line.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            if re.match(r"^\s*report_fields\s*:\s*$", line):
                in_rf = True
                rf_indent = len(line) - len(line.lstrip(" "))
                continue
            if in_rf:
                ind = len(line) - len(line.lstrip(" "))
                if ind <= (rf_indent or 0):
                    break
                stripped = line.strip()
                if stripped.startswith("- "):
                    item = stripped[2:].strip()
                    rf_list.append(_parse_scalar(item))
        root["report_fields"] = rf_list

    # For "watch" and "editorial_policy", ensure they are dicts as expected
    if not isinstance(root.get("editorial_policy"), dict):
        # Try to repair by scanning lines
        pass
    if not isinstance(root.get("watch"), dict):
        pass

    return root


def _count_words(text: str) -> int:
    return len(text.split())


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    t = s.strip()
    t = t.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        datetime.fromisoformat(t)
        return True
    except Exception:
        return False


def _almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _recompute_metrics(submission: Dict[str, Any], config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        submission_id = submission["submission_id"]
        title = submission["title"]
        sections = submission.get("sections", [])
        references = submission.get("references", [])
        footnotes = submission.get("footnotes", [])
    except Exception:
        return None

    # word_count across all sections' text
    wc = 0
    for sec in sections:
        text = sec.get("text", "")
        if not isinstance(text, str):
            return None
        wc += _count_words(text)

    # citations counts
    cit_types = {"case": 0, "statute": 0, "article": 0}
    for ref in references:
        t = ref.get("type")
        if t in cit_types:
            cit_types[t] += 1

    total_cits = cit_types["case"] + cit_types["statute"] + cit_types["article"]
    case_ratio = (cit_types["case"] / total_cits) if total_cits > 0 else 0.0

    # footnotes metrics
    fn_count = 0
    fn_words_total = 0
    for fn in footnotes:
        text = fn.get("text", "")
        if not isinstance(text, str):
            return None
        fn_count += 1
        fn_words_total += _count_words(text)
    fn_avg = (fn_words_total / fn_count) if fn_count > 0 else 0.0

    # compliance using config thresholds
    ep = config.get("editorial_policy", {})
    try:
        min_case_ratio = float(ep.get("min_case_ratio"))
        max_avg_fn_words = float(ep.get("max_avg_footnote_words"))
    except Exception:
        return None

    compliance = {
        "case_ratio": case_ratio >= min_case_ratio,
        "avg_footnote_words": fn_avg <= max_avg_fn_words,
    }

    metrics = {
        "submission_id": submission_id,
        "title": title,
        "word_count": wc,
        "citations": dict(cit_types),
        "footnotes": {"count": fn_count, "avg_words": fn_avg},
        "citation_ratio": {"case": case_ratio},
        "compliance": compliance,
    }
    return metrics


def _validate_report_schema(report: Dict[str, Any]) -> bool:
    expected_top = {
        "submission_id",
        "title",
        "word_count",
        "citations",
        "footnotes",
        "citation_ratio",
        "compliance",
        "timestamp",
    }
    if set(report.keys()) != expected_top:
        return False
    if not isinstance(report["citations"], dict):
        return False
    if not isinstance(report["footnotes"], dict):
        return False
    if not isinstance(report["citation_ratio"], dict):
        return False
    if not isinstance(report["compliance"], dict):
        return False
    if set(report["citations"].keys()) != {"case", "statute", "article"}:
        return False
    if set(report["footnotes"].keys()) != {"count", "avg_words"}:
        return False
    if set(report["citation_ratio"].keys()) != {"case"}:
        return False
    if set(report["compliance"].keys()) != {"case_ratio", "avg_footnote_words"}:
        return False
    return True


def _find_watcher_script(workspace: Path) -> Optional[Path]:
    # Search for a script that references config/editorial.yaml and uses watch settings
    candidate_exts = {".py", ".sh", ".js", ".ts", ".rb", ".go"}
    try:
        for p in workspace.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in candidate_exts:
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "config/editorial.yaml" in txt and ("watch" in txt or "file_glob" in txt or "input_dir" in txt) and ("editorial_policy" in txt):
                return p
    except Exception:
        return None
    return None


def _extract_iso_from_line(line: str) -> Optional[str]:
    # Find a token that parses as ISO-8601
    tokens = re.split(r"\s+", line.strip())
    for tok in tokens:
        tok_clean = tok.strip().strip(",;")
        if _is_iso8601(tok_clean):
            return tok_clean
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "config_readable": 0.0,
        "report_exists": 0.0,
        "report_top_level_fields_exact": 0.0,
        "report_nested_schema_correct": 0.0,
        "report_timestamp_iso8601": 0.0,
        "report_values_correct": 0.0,
        "report_compliance_correct": 0.0,
        "cover_letter_exists": 0.0,
        "cover_letter_within_word_limit": 0.0,
        "cover_letter_rewritten_from_draft": 0.0,
        "log_file_has_entry": 0.0,
        "log_includes_compliance_summary": 0.0,
        "watcher_script_present": 0.0,
    }

    # Load config
    config_path = workspace / "config" / "editorial.yaml"
    config = _load_yaml_minimal(config_path)
    if isinstance(config, dict) and "editorial_policy" in config and "watch" in config:
        scores["config_readable"] = 1.0

    # Expected input and outputs
    expected_submission_id = "submission_2024_001"
    input_submission_path = workspace / "input" / "submissions" / f"{expected_submission_id}.json"
    input_cover_letter_draft_path = workspace / "input" / "submissions" / f"{expected_submission_id}_cover_letter_draft.txt"
    output_report_path = workspace / "output" / "reports" / f"{expected_submission_id}_metrics.json"
    output_cover_letter_path = workspace / "output" / "messages" / f"{expected_submission_id}_cover_letter_edited.txt"
    output_log_path = workspace / "output" / "logs" / "automation.log"

    # Check report existence
    report = _safe_load_json(output_report_path)
    if report is not None:
        scores["report_exists"] = 1.0

    # Validate report schema and timestamp
    if report is not None and _validate_report_schema(report):
        scores["report_top_level_fields_exact"] = 1.0
        scores["report_nested_schema_correct"] = 1.0
        if _is_iso8601(report.get("timestamp")):
            scores["report_timestamp_iso8601"] = 1.0

    # Recompute metrics from input and compare
    submission = _safe_load_json(input_submission_path)
    if submission is not None and isinstance(config, dict):
        recomputed = _recompute_metrics(submission, config)
    else:
        recomputed = None

    if report is not None and recomputed is not None:
        values_ok = True
        try:
            values_ok = (
                report.get("submission_id") == recomputed["submission_id"]
                and report.get("title") == recomputed["title"]
                and isinstance(report.get("word_count"), int)
                and report.get("word_count") == recomputed["word_count"]
                and isinstance(report.get("citations", {}).get("case"), int)
                and isinstance(report.get("citations", {}).get("statute"), int)
                and isinstance(report.get("citations", {}).get("article"), int)
                and report["citations"]["case"] == recomputed["citations"]["case"]
                and report["citations"]["statute"] == recomputed["citations"]["statute"]
                and report["citations"]["article"] == recomputed["citations"]["article"]
                and isinstance(report.get("footnotes", {}).get("count"), int)
                and report["footnotes"]["count"] == recomputed["footnotes"]["count"]
                and isinstance(report.get("footnotes", {}).get("avg_words"), (int, float))
                and _almost_equal(float(report["footnotes"]["avg_words"]), float(recomputed["footnotes"]["avg_words"]))
                and isinstance(report.get("citation_ratio", {}).get("case"), (int, float))
                and _almost_equal(float(report["citation_ratio"]["case"]), float(recomputed["citation_ratio"]["case"]))
            )
        except Exception:
            values_ok = False
        if values_ok:
            scores["report_values_correct"] = 1.0

        compliance_ok = True
        try:
            compliance_ok = (
                isinstance(report.get("compliance", {}).get("case_ratio"), bool)
                and isinstance(report.get("compliance", {}).get("avg_footnote_words"), bool)
                and report["compliance"]["case_ratio"] == recomputed["compliance"]["case_ratio"]
                and report["compliance"]["avg_footnote_words"] == recomputed["compliance"]["avg_footnote_words"]
            )
        except Exception:
            compliance_ok = False
        if compliance_ok:
            scores["report_compliance_correct"] = 1.0

    # Cover letter checks
    edited_text = _safe_read_text(output_cover_letter_path)
    if edited_text is not None:
        scores["cover_letter_exists"] = 1.0
        # Word limit
        max_words = None
        if isinstance(config, dict):
            ep = config.get("editorial_policy", {})
            try:
                max_words = int(ep.get("max_cover_letter_words"))
            except Exception:
                max_words = None
        if max_words is not None:
            if _count_words(edited_text) <= max_words:
                scores["cover_letter_within_word_limit"] = 1.0
        # Rewritten vs draft
        draft_text = _safe_read_text(input_cover_letter_draft_path) or ""
        if draft_text and edited_text.strip() != draft_text.strip():
            scores["cover_letter_rewritten_from_draft"] = 1.0

    # Log checks
    log_text = _safe_read_text(output_log_path)
    if log_text is not None:
        # At least one line with submission_id
        lines = [ln for ln in log_text.splitlines() if ln.strip()]
        matching_lines = [ln for ln in lines if expected_submission_id in ln]
        if matching_lines:
            scores["log_file_has_entry"] = 1.0
            # Check timestamp present (any ISO-like token)
            has_iso = any(_extract_iso_from_line(ln) is not None for ln in matching_lines)
            # Check compliance summary mentions both keys and a True/False
            has_compliance = any(
                ("case_ratio" in ln and "avg_footnote_words" in ln and re.search(r"\b(True|False)\b", ln))
                for ln in matching_lines
            )
            if has_iso:
                # We treat timestamp presence as part of having a valid entry; since we don't have a dedicated key, fold into log_file_has_entry if desired.
                pass
            if has_compliance:
                scores["log_includes_compliance_summary"] = 1.0

    # Watcher script presence
    watcher = _find_watcher_script(workspace)
    if watcher is not None:
        scores["watcher_script_present"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()