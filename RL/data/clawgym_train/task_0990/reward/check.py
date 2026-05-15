import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional


def safe_read_text(path: Path) -> Tuple[Optional[str], bool]:
    try:
        text = path.read_text(encoding="utf-8")
        return text, True
    except Exception:
        return None, False


def safe_json_load(path: Path) -> Tuple[Optional[Any], bool]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False


def safe_read_jsonl(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], bool]:
    try:
        records: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records, True
    except Exception:
        return None, False


def compute_expected_totals(weights_path: Path, responses_path: Path) -> Tuple[Optional[Dict[str, float]], Optional[float], bool]:
    weights_json, ok_w = safe_json_load(weights_path)
    if not ok_w or not isinstance(weights_json, dict) or "weights" not in weights_json or not isinstance(weights_json["weights"], dict):
        return None, None, False
    weights: Dict[str, float] = {}
    try:
        for k, v in weights_json["weights"].items():
            weights[str(k)] = float(v)
    except Exception:
        return None, None, False

    records, ok_r = safe_read_jsonl(responses_path)
    if not ok_r or not isinstance(records, list):
        return None, None, False

    def compute_total(responses: Dict[str, Any], weights_map: Dict[str, float]) -> float:
        total_val = 0.0
        for q, w in weights_map.items():
            v = responses.get(q, "skip")
            if v is None:
                v = "skip"
            if isinstance(v, (int, float)):
                total_val += float(v) * float(w)
            elif isinstance(v, str) and v.strip().lower() == "skip":
                total_val += 0.0
            else:
                total_val += 0.0
        return total_val

    totals_by_id: Dict[str, float] = {}
    totals_list: List[float] = []
    for r in records:
        rid = r.get("id")
        responses = r.get("responses", {})
        if not isinstance(responses, dict):
            return None, None, False
        total = compute_total(responses, weights)
        totals_by_id[str(rid)] = total
        totals_list.append(total)
    avg = sum(totals_list) / float(len(totals_list)) if totals_list else 0.0
    return totals_by_id, avg, True


def approx_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def extract_average_literal_from_results(path: Path) -> Tuple[Optional[str], bool]:
    text, ok = safe_read_text(path)
    if not ok or text is None:
        return None, False
    m = re.search(r'"average_total"\s*:\s*([0-9eE\+\-\.]+)', text)
    if not m:
        return None, False
    return m.group(1), True


def count_sentences(text: str) -> int:
    # Simple sentence split on ., !, ? followed by space or end; remove empty fragments
    parts = re.split(r'[.!?]+(?:\s+|$)', text.strip())
    parts = [p for p in parts if p.strip()]
    return len(parts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "tests_file_exists": 0.0,
        "tests_file_uses_unittest": 0.0,
        "tests_file_contains_skip_test_hint": 0.0,
        "tests_file_contains_expected_totals_hint": 0.0,
        "tests_summary_exists_and_fields": 0.0,
        "tests_summary_all_passed": 0.0,
        "scores_json_exists_and_structure": 0.0,
        "scores_json_totals_match_expected": 0.0,
        "scores_json_average_matches": 0.0,
        "parent_note_replacements_done": 0.0,
        "parent_note_appendix_present_and_at_end": 0.0,
        "email_exists": 0.0,
        "email_mentions_wording_changes": 0.0,
        "email_includes_average_total_exact": 0.0,
        "email_includes_test_summary_numbers": 0.0,
        "email_mentions_files_and_length_ok": 0.0,
    }

    # Paths
    tests_file = workspace / "tests" / "test_score.py"
    summary_json_path = workspace / "tests" / "results" / "summary.json"
    weights_path = workspace / "config" / "weights.json"
    responses_jsonl_path = workspace / "data" / "sample_responses.jsonl"
    scores_json_path = workspace / "results" / "scores.json"
    parent_note_path = workspace / "docs" / "parent_note.md"
    email_path = workspace / "emails" / "update_to_team.txt"

    # Expected totals derived from task requirement
    expected_totals_declared = {"logan": 15.0, "maya": 10.0, "alex": 11.5}
    expected_avg_declared = (expected_totals_declared["logan"] + expected_totals_declared["maya"] + expected_totals_declared["alex"]) / 3.0

    # 1) tests/test_score.py checks
    text, ok_text = safe_read_text(tests_file)
    if ok_text and text is not None:
        scores["tests_file_exists"] = 1.0
        if "unittest" in text:
            scores["tests_file_uses_unittest"] = 1.0
        # Skip test hint: use of "skip" and assertion to 0.0 and compute_total reference
        skip_hint = ('"skip"' in text or "'skip'" in text) and ("0.0" in text or "0.0" in text) and ("compute_total" in text)
        if skip_hint:
            scores["tests_file_contains_skip_test_hint"] = 1.0
        # Expected totals test hint: references to the sample input and expected numbers
        totals_hint = ("data/sample_responses.jsonl" in text) and ("config/weights.json" in text) and ("15.0" in text) and ("10.0" in text) and ("11.5" in text)
        if totals_hint:
            scores["tests_file_contains_expected_totals_hint"] = 1.0

    # 2) tests/results/summary.json checks
    summary_obj, ok_summary = safe_json_load(summary_json_path)
    if ok_summary and isinstance(summary_obj, dict):
        fields_ok = True
        for k in ["tests_run", "failures", "errors", "passes"]:
            if k not in summary_obj or not isinstance(summary_obj[k], int):
                fields_ok = False
                break
        if fields_ok:
            scores["tests_summary_exists_and_fields"] = 1.0
            tests_run = summary_obj["tests_run"]
            failures = summary_obj["failures"]
            errors = summary_obj["errors"]
            passes = summary_obj["passes"]
            if tests_run >= 2 and failures == 0 and errors == 0 and passes == tests_run:
                scores["tests_summary_all_passed"] = 1.0

    # 3) results/scores.json checks
    scores_obj, ok_scores = safe_json_load(scores_json_path)
    records_ok = False
    avg_ok = False
    totals_match = False
    if ok_scores and isinstance(scores_obj, dict):
        records = scores_obj.get("records")
        average_total = scores_obj.get("average_total")
        if isinstance(records, list) and isinstance(average_total, (int, float)):
            scores["scores_json_exists_and_structure"] = 1.0
            # Build mapping by id from records
            rec_map: Dict[str, float] = {}
            try:
                for r in records:
                    rid = r.get("id")
                    total = r.get("total")
                    if not isinstance(rid, str) or not isinstance(total, (int, float)):
                        raise ValueError("Bad record structure")
                    rec_map[rid] = float(total)
                records_ok = True
            except Exception:
                records_ok = False

            # Compare totals to expected declared values
            if records_ok:
                expected_ids = set(expected_totals_declared.keys())
                rec_ids = set(rec_map.keys())
                if expected_ids.issubset(rec_ids):
                    matches = all(approx_equal(rec_map[i], expected_totals_declared[i]) for i in expected_ids)
                    if matches:
                        totals_match = True
                        scores["scores_json_totals_match_expected"] = 1.0

            # Compare average_total to recomputed from records in results file (internal consistency) and to declared expected
            if records_ok:
                if rec_map:
                    avg_from_records = sum(rec_map[i] for i in rec_map) / float(len(rec_map))
                else:
                    avg_from_records = 0.0
                if approx_equal(float(average_total), avg_from_records) and approx_equal(float(average_total), expected_avg_declared):
                    avg_ok = True
                    scores["scores_json_average_matches"] = 1.0

    # 4) docs/parent_note.md checks
    note_text, ok_note = safe_read_text(parent_note_path)
    if ok_note and note_text is not None:
        # Replacements done
        has_new_phrases = ("areas to explore further" in note_text) and ("typical range" in note_text)
        no_old_phrases = ("red flags" not in note_text) and (re.search(r"\bnormal\b", note_text) is None)
        if has_new_phrases and no_old_phrases:
            scores["parent_note_replacements_done"] = 1.0
        # Appendix at end exact
        lines = [ln.rstrip("\n") for ln in note_text.splitlines()]
        expected_footer = [
            "Testing and quality checks",
            "- Automated scoring validated on data/sample_responses.jsonl with expected totals: logan=15.0, maya=10.0, alex=11.5",
            "- Test summary: tests/results/summary.json",
            "- Latest run output: results/scores.json",
        ]
        if len(lines) >= 4 and lines[-4:] == expected_footer:
            scores["parent_note_appendix_present_and_at_end"] = 1.0

    # 5) emails/update_to_team.txt checks
    email_text, ok_email = safe_read_text(email_path)
    if ok_email and email_text is not None:
        scores["email_exists"] = 1.0
        # Mentions wording changes and why
        mentions_changes = ("red flags" in email_text and "areas to explore further" in email_text and "normal" in email_text and "typical range" in email_text)
        if mentions_changes:
            scores["email_mentions_wording_changes"] = 1.0

        # Includes exact average_total literal from results/scores.json
        avg_literal, ok_avg_lit = extract_average_literal_from_results(scores_json_path)
        if ok_avg_lit and avg_literal is not None and avg_literal in email_text:
            scores["email_includes_average_total_exact"] = 1.0

        # Includes passes, failures, errors from summary
        summary_obj_for_email, ok_summary_for_email = safe_json_load(summary_json_path)
        if ok_summary_for_email and isinstance(summary_obj_for_email, dict):
            try:
                passes_val = int(summary_obj_for_email.get("passes", -1))
                failures_val = int(summary_obj_for_email.get("failures", -1))
                errors_val = int(summary_obj_for_email.get("errors", -1))
                # Check presence of words and numbers
                has_words = ("passes" in email_text and "failures" in email_text and "errors" in email_text)
                has_numbers = (str(passes_val) in email_text and str(failures_val) in email_text and str(errors_val) in email_text)
                if has_words and has_numbers and passes_val >= 0 and failures_val >= 0 and errors_val >= 0:
                    scores["email_includes_test_summary_numbers"] = 1.0
            except Exception:
                pass

        # Mentions file locations and has 5–7 sentences
        mentions_files = ("docs/parent_note.md" in email_text and "tests/results/summary.json" in email_text and "results/scores.json" in email_text)
        num_sentences = count_sentences(email_text)
        if mentions_files and 5 <= num_sentences <= 7:
            scores["email_mentions_files_and_length_ok"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()