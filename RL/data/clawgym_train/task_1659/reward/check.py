import json
import sys
import re
import importlib
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def _safe_load_json(path: Path) -> Tuple[bool, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _safe_load_jsonl(path: Path) -> Tuple[bool, List[Dict[str, Any]]]:
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return False, []
                if not isinstance(obj, dict):
                    return False, []
                if not {"id", "text", "label"} <= set(obj.keys()):
                    return False, []
                records.append(obj)
        return True, records
    except Exception:
        return False, []


def _import_module_from_workspace(workspace: Path, module_name: str):
    # Ensure workspace path is on sys.path for namespace package imports
    if str(workspace) not in sys.path:
        sys.path.insert(0, str(workspace))
    try:
        return True, importlib.import_module(module_name)
    except Exception:
        return False, None


def _contains_heading(text: str, heading: str) -> bool:
    pattern = r"^\s{0,3}#{1,6}\s*" + re.escape(heading) + r"\s*$"
    for line in text.splitlines():
        if re.search(pattern, line, flags=re.IGNORECASE):
            return True
    return False


def _check_no_disk_write_to_config(test_text: str) -> bool:
    # Disallow attempts to open the config file for writing.
    if re.search(r'open\(\s*["\']config/terms\.json["\']\s*,\s*["\']w', test_text):
        return False
    if re.search(r'open\(\s*["\']config/terms\.json["\']\s*,\s*["\']a', test_text):
        return False
    if re.search(r'json\.dump\(.+open\(\s*["\']config/terms\.json["\']', test_text):
        return False
    return True


def _detect_threshold_decrease_assertion(test_text: str) -> bool:
    # Look for evidence that a copy of the config has threshold decreased to 1 AND used in an assertion with classify_text
    lowered_threshold_patterns = [
        r'\[\s*["\']threshold["\']\s*\]\s*=\s*1',
        r'\bdict\([^)]*threshold\s*=\s*1[^)]*\)',
        r'\bupdate\(\s*\{\s*["\']threshold["\']\s*:\s*1\s*\}\s*\)',
        r'\{\s*[^}]*["\']threshold["\']\s*:\s*1[^}]*\}',
        r'\bthreshold\s*=\s*1\b',
    ]
    has_lowering = any(re.search(p, test_text) for p in lowered_threshold_patterns)
    # Look for an assert that calls classify_text with some config var (heuristic)
    assert_calls = re.findall(r'assert\s+.+classify_text\s*\([^,]+,\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\)', test_text)
    # If we see at least one assert-on-classify_text and some threshold lowering code, accept
    return has_lowering and bool(assert_calls)


def _classify_dataset_via_module(workspace: Path) -> Tuple[bool, List[Tuple[str, bool, bool]]]:
    ok_module, mod = _import_module_from_workspace(workspace, "src.filter")
    if not ok_module or mod is None:
        return False, []
    cfg_path = workspace / "config" / "terms.json"
    try:
        cfg = mod.load_config(str(cfg_path))
    except Exception:
        return False, []
    ok_jsonl, records = _safe_load_jsonl(workspace / "data" / "sample_reports.jsonl")
    if not ok_jsonl:
        return False, []
    mismatches: List[Tuple[str, bool, bool]] = []
    for rec in records:
        try:
            pred = mod.classify_text(rec["text"], cfg)
        except Exception:
            return False, []
        if bool(pred) != bool(rec["label"]):
            mismatches.append((str(rec.get("id")), bool(rec["label"]), bool(pred)))
    return True, mismatches


def _readme_has_logic_note(text: str) -> bool:
    low = text.lower()
    mentions_presence = "presence" in low
    mentions_violent_terms = ("violent terms" in low) or ("violent" in low and "terms" in low)
    mentions_exceptions = "exceptions" in low
    mentions_threshold = "threshold" in low
    mentions_geq = (">=" in text) or ("greater than or equal" in low)
    return all([mentions_presence, mentions_violent_terms, mentions_exceptions, mentions_threshold, mentions_geq])


def _readme_has_dataset_summary(text: str, total: int, true_count: int, false_count: int) -> bool:
    flags = 0
    if re.search(rf"(?:total[^0-9]*{total}|{total}[^0-9]*total)", text, flags=re.IGNORECASE):
        flags += 1
    if re.search(rf"(?:true[^0-9]*{true_count}|{true_count}[^0-9]*true)", text, flags=re.IGNORECASE):
        flags += 1
    if re.search(rf"(?:false[^0-9]*{false_count}|{false_count}[^0-9]*false)", text, flags=re.IGNORECASE):
        flags += 1
    return flags == 3


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_threshold_is_2": 0.0,
        "config_exceptions_correct": 0.0,
        "config_violent_terms_unchanged": 0.0,
        "classification_matches_labels": 0.0,
        "tests_imports_and_loads_config": 0.0,
        "tests_reads_dataset_and_asserts": 0.0,
        "tests_threshold_decrease_demo": 0.0,
        "tests_no_disk_write_config": 0.0,
        "readme_has_tests_section": 0.0,
        "readme_mentions_threshold_and_exceptions": 0.0,
        "readme_includes_classification_logic_note": 0.0,
        "readme_includes_dataset_summary": 0.0,
    }

    # Expected constants
    expected_violent_terms = ["abuse", "assault", "hit", "threat", "kill"]
    expected_exceptions = ["support group", "hotline", "shelter", "resources"]
    expected_exceptions_set = set(map(str.lower, expected_exceptions))

    # Check config/terms.json
    cfg_path = workspace / "config" / "terms.json"
    ok_cfg, cfg = _safe_load_json(cfg_path)
    threshold_is_2 = False
    exceptions_ok = False
    violent_terms_ok = False
    if ok_cfg and isinstance(cfg, dict):
        try:
            thr = int(cfg.get("threshold", None))
        except Exception:
            thr = None
        if thr == 2:
            threshold_is_2 = True
            scores["config_threshold_is_2"] = 1.0
        exc = cfg.get("exceptions", None)
        if isinstance(exc, list):
            exc_set = set(map(str.lower, exc))
            if exc_set == expected_exceptions_set and len(exc) == 4:
                exceptions_ok = True
                scores["config_exceptions_correct"] = 1.0
        vt = cfg.get("violent_terms", None)
        if isinstance(vt, list) and vt == expected_violent_terms:
            violent_terms_ok = True
        # Only award violent_terms_unchanged when the new configuration is otherwise correct
        if threshold_is_2 and exceptions_ok and violent_terms_ok:
            scores["config_violent_terms_unchanged"] = 1.0

    # Check classification over dataset using src/filter.py and current config
    ok_classify, mismatches = _classify_dataset_via_module(workspace)
    if ok_classify and not mismatches:
        scores["classification_matches_labels"] = 1.0

    # Check tests/test_filter.py
    test_path = workspace / "tests" / "test_filter.py"
    ok_test_text, test_text = _safe_read_text(test_path)
    if ok_test_text and test_text:
        # Must import classifier from src/filter.py and load config from config/terms.json (via loader or direct)
        imports_classifier = (
            re.search(r'\bfrom\s+src\.filter\s+import\s+classify_text', test_text) or
            re.search(r'\bimport\s+src\.filter\b', test_text) or
            re.search(r'\bfrom\s+src\s+import\s+filter\b', test_text)
        )
        loads_config_via_func = re.search(r'\bload_config\s*\(', test_text) is not None
        loads_config_via_path = "config/terms.json" in test_text
        if imports_classifier and (loads_config_via_func or loads_config_via_path):
            scores["tests_imports_and_loads_config"] = 1.0

        # Must read dataset and assert per record
        reads_dataset = "data/sample_reports.jsonl" in test_text
        uses_assert = "assert " in test_text
        references_label = "label" in test_text
        references_classify = "classify_text" in test_text
        if reads_dataset and uses_assert and references_label and references_classify:
            scores["tests_reads_dataset_and_asserts"] = 1.0

        # Demonstrate threshold decrease via in-memory copy
        if _detect_threshold_decrease_assertion(test_text):
            scores["tests_threshold_decrease_demo"] = 1.0

        # Ensure no disk modification of config
        if _check_no_disk_write_to_config(test_text):
            scores["tests_no_disk_write_config"] = 1.0

    # Check README updates
    readme_path = workspace / "docs" / "README.md"
    ok_readme_text, readme_text = _safe_read_text(readme_path)
    if ok_readme_text and readme_text:
        # Section heading
        if _contains_heading(readme_text, "Violence filter tests"):
            scores["readme_has_tests_section"] = 1.0

        # Mentions threshold=2 and exceptions list items
        mentions_threshold_line = bool(re.search(r"threshold[^0-9]*2|2[^0-9]*threshold", readme_text, flags=re.IGNORECASE))
        exceptions_present = all(exc in readme_text for exc in expected_exceptions)
        if mentions_threshold_line and exceptions_present:
            scores["readme_mentions_threshold_and_exceptions"] = 1.0

        # Classification logic note
        if _readme_has_logic_note(readme_text):
            scores["readme_includes_classification_logic_note"] = 1.0

        # Dataset summary: compute from data file to be deterministic
        data_path = workspace / "data" / "sample_reports.jsonl"
        ok_jsonl, records = _safe_load_jsonl(data_path)
        if ok_jsonl:
            total = len(records)
            true_count = sum(1 for r in records if bool(r.get("label")) is True)
            false_count = total - true_count
            if total == 8 and true_count == 4 and false_count == 4 and _readme_has_dataset_summary(readme_text, total, true_count, false_count):
                scores["readme_includes_dataset_summary"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()