import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        records: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                s = line.strip("\n")
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                records.append(obj)
        return records
    except Exception:
        return None


def _extract_style_rules(md_text: str) -> Optional[Dict[str, Any]]:
    # Extract the first fenced json block ```json ... ```
    start_match = re.search(r"```json\s*", md_text, flags=re.IGNORECASE)
    if not start_match:
        return None
    start = start_match.end()
    end_match = re.search(r"\n```", md_text[start:])
    if not end_match:
        return None
    end = start + end_match.start()
    json_block = md_text[start:end].strip()
    try:
        rules = json.loads(json_block)
        if isinstance(rules, dict):
            return rules
        return None
    except Exception:
        return None


def _contains_word(text: str, word: str) -> bool:
    # word boundary match, case-sensitive
    pattern = r"\b" + re.escape(word) + r"\b"
    return re.search(pattern, text) is not None


def _find_counts_in_report(text: str) -> Tuple[Optional[int], Optional[int]]:
    # Extract "Ran X tests" and "failures=Y" counts if present
    ran = None
    failures = None
    m_ran = re.search(r"Ran\s+(\d+)\s+tests", text, flags=re.IGNORECASE)
    if m_ran:
        try:
            ran = int(m_ran.group(1))
        except Exception:
            ran = None
    m_fail = re.search(r"failures\s*=\s*(\d+)", text, flags=re.IGNORECASE)
    if m_fail:
        try:
            failures = int(m_fail.group(1))
        except Exception:
            failures = None
    return ran, failures


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        # Tests presence and behavior
        "tests_file_exists": 0.0,
        "tests_programmatically_parse_style_guide": 0.0,
        "tests_validate_subject_rules_present": 0.0,
        "tests_validate_forbidden_punctuation_present": 0.0,
        "tests_validate_slang_normalization_present": 0.0,
        "tests_validate_signoff_template_present": 0.0,
        "tests_validate_names_preserved_present": 0.0,
        "tests_validate_body_trim_present": 0.0,
        "tests_unittest_runner_compatible": 0.0,
        # Output artifact validity
        "rewrite_output_valid_jsonl": 0.0,
        "rewritten_covers_all_inputs": 0.0,
        # Conformance checks on rewritten outputs
        "rewritten_subject_rules_satisfied": 0.0,
        "rewritten_forbidden_punctuation_removed": 0.0,
        "rewritten_slang_normalized": 0.0,
        "rewritten_signoff_applied": 0.0,
        "rewritten_names_preserved": 0.0,
        "rewritten_body_trimmed": 0.0,
        # Test report checks
        "test_report_exists": 0.0,
        "test_report_contains_counts": 0.0,
        "test_report_zero_failures": 0.0,
    }

    # Load style guide rules
    style_path = workspace / "guidelines" / "style_guide.md"
    style_text = _read_text(style_path)
    style_rules: Optional[Dict[str, Any]] = None
    if style_text is not None:
        style_rules = _extract_style_rules(style_text)

    # Check tests content
    test_path = workspace / "tests" / "test_rewrite.py"
    test_text = _read_text(test_path)
    if test_text is not None:
        scores["tests_file_exists"] = 1.0

        # Programmatic parse evidence: references style_guide.md and uses json to load
        uses_style_path = ("style_guide.md" in test_text) or ("guidelines/style_guide.md" in test_text)
        uses_json_loading = ("json.loads" in test_text) or ("json.load" in test_text)
        if uses_style_path and uses_json_loading:
            scores["tests_programmatically_parse_style_guide"] = 1.0

        # Presence of assertions for specific rules (heuristic by key presence)
        if ("subject" in test_text and "max_subject_length" in test_text and "require_subject" in test_text):
            scores["tests_validate_subject_rules_present"] = 1.0

        if ("forbidden_punctuation" in test_text and "subject" in test_text and "body" in test_text):
            scores["tests_validate_forbidden_punctuation_present"] = 1.0

        if ("normalize_slang" in test_text and "body" in test_text):
            scores["tests_validate_slang_normalization_present"] = 1.0

        if "preferred_signoff_template" in test_text:
            scores["tests_validate_signoff_template_present"] = 1.0

        if ("recipient_name" in test_text and "sender_name" in test_text):
            scores["tests_validate_names_preserved_present"] = 1.0

        if ("strip(" in test_text or ".strip()" in test_text or "lstrip(" in test_text or "rstrip(" in test_text) and ("body" in test_text):
            scores["tests_validate_body_trim_present"] = 1.0

        if ("import unittest" in test_text or "from unittest" in test_text) and ("def test_" in test_text):
            scores["tests_unittest_runner_compatible"] = 1.0

    # Load input and output records
    input_path = workspace / "input" / "drafts.jsonl"
    output_path = workspace / "output" / "rewritten.jsonl"
    input_records = _load_jsonl(input_path)
    output_records = _load_jsonl(output_path)
    output_valid = False
    if output_records is not None:
        # Validate required fields exist and are strings
        all_valid = True
        for rec in output_records:
            for key in ("id", "recipient_name", "sender_name", "subject", "body"):
                if key not in rec:
                    all_valid = False
                    break
                if not isinstance(rec[key], str):
                    all_valid = False
                    break
            if not all_valid:
                break
        if all_valid and len(output_records) > 0:
            scores["rewrite_output_valid_jsonl"] = 1.0
            output_valid = True

    # Verify outputs cover all inputs by id
    if input_records is not None and output_records is not None:
        input_ids = {rec.get("id") for rec in input_records if isinstance(rec, dict)}
        output_ids = {rec.get("id") for rec in output_records if isinstance(rec, dict)}
        if input_ids and input_ids.issubset(output_ids):
            scores["rewritten_covers_all_inputs"] = 1.0

    # Conformance checks using rules and both input & output
    if style_rules is not None and output_valid:
        # Subject rules
        subj_ok = True
        require_subject = bool(style_rules.get("require_subject", False))
        max_sub_len = style_rules.get("max_subject_length", None)
        if max_sub_len is not None:
            try:
                max_sub_len = int(max_sub_len)
            except Exception:
                max_sub_len = None
        for rec in output_records:
            subj = rec.get("subject", "")
            if not isinstance(subj, str):
                subj_ok = False
                break
            if require_subject:
                if subj.strip() == "":
                    subj_ok = False
                    break
            if max_sub_len is not None:
                if len(subj) > int(max_sub_len):
                    subj_ok = False
                    break
        if subj_ok:
            scores["rewritten_subject_rules_satisfied"] = 1.0

        # Forbidden punctuation removed from subject and body
        forb = style_rules.get("forbidden_punctuation", [])
        if not isinstance(forb, list):
            forb = []
        forb = [str(c) for c in forb]
        forb_ok = True
        for rec in output_records:
            subj = rec.get("subject", "")
            body = rec.get("body", "")
            if not isinstance(subj, str) or not isinstance(body, str):
                forb_ok = False
                break
            for c in forb:
                if c in subj or c in body:
                    forb_ok = False
                    break
            if not forb_ok:
                break
        if forb_ok:
            scores["rewritten_forbidden_punctuation_removed"] = 1.0

        # Slang normalization
        slang_ok = True
        # We prefer to ensure no slang tokens remain and mapped tokens appear if present in input
        normalize = style_rules.get("normalize_slang", {})
        if not isinstance(normalize, dict):
            normalize = {}
        # Map input by id for comparison
        input_by_id: Dict[str, Dict[str, Any]] = {}
        if input_records is not None:
            for r in input_records:
                if isinstance(r, dict) and isinstance(r.get("id"), str):
                    input_by_id[r["id"]] = r
        for rec in output_records:
            out_id = rec.get("id", None)
            out_body = rec.get("body", "")
            if not isinstance(out_body, str):
                slang_ok = False
                break
            # Ensure slang keys not present as standalone tokens in output
            for k, v in normalize.items():
                if _contains_word(out_body, k):
                    slang_ok = False
                    break
            if not slang_ok:
                break
            # If input had slang token, ensure mapped token appears in output
            if out_id is not None and out_id in input_by_id:
                in_body = input_by_id[out_id].get("body", "")
                if isinstance(in_body, str):
                    for k, v in normalize.items():
                        if _contains_word(in_body, k):
                            # Expect the mapped value present as a word in output
                            if not _contains_word(out_body, v):
                                slang_ok = False
                                break
                    if not slang_ok:
                        break
        if slang_ok:
            scores["rewritten_slang_normalized"] = 1.0

        # Sign-off applied with exact sender_name
        sign_ok = True
        tmpl = style_rules.get("preferred_signoff_template", None)
        if not isinstance(tmpl, str):
            sign_ok = False
        else:
            for rec in output_records:
                sender = rec.get("sender_name", "")
                body = rec.get("body", "")
                if not isinstance(sender, str) or not isinstance(body, str):
                    sign_ok = False
                    break
                expected_sign = tmpl.replace("{sender_name}", sender)
                if not body.endswith(expected_sign):
                    sign_ok = False
                    break
        if sign_ok:
            scores["rewritten_signoff_applied"] = 1.0

        # Names preserved exactly compared to inputs
        names_ok = True
        if input_records is None:
            names_ok = False
        else:
            input_by_id = {r.get("id"): r for r in input_records if isinstance(r, dict)}
            for rec in output_records:
                rid = rec.get("id")
                if rid not in input_by_id:
                    # If we can't compare, fail this record
                    names_ok = False
                    break
                in_rec = input_by_id[rid]
                if rec.get("recipient_name") != in_rec.get("recipient_name"):
                    names_ok = False
                    break
                if rec.get("sender_name") != in_rec.get("sender_name"):
                    names_ok = False
                    break
        if names_ok:
            scores["rewritten_names_preserved"] = 1.0

        # Body trimmed
        trimmed_ok = True
        for rec in output_records:
            body = rec.get("body", "")
            if not isinstance(body, str):
                trimmed_ok = False
                break
            if body != body.strip():
                trimmed_ok = False
                break
        if trimmed_ok:
            scores["rewritten_body_trimmed"] = 1.0

    # Test report checks
    report_path = workspace / "output" / "test_report.txt"
    report_text = _read_text(report_path)
    if report_text is not None:
        scores["test_report_exists"] = 1.0
        ran, failures = _find_counts_in_report(report_text)
        if ran is not None and failures is not None:
            scores["test_report_contains_counts"] = 1.0
            if failures == 0 and ran >= 1:
                scores["test_report_zero_failures"] = 1.0

    return scores


def main() -> None:
        workspace = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade([], workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()