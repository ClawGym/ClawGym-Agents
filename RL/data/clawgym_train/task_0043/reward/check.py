import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Tuple[bool, Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return False, None
        return True, path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False, None


def _load_json_safe(path: Path) -> Tuple[bool, Optional[Any]]:
    try:
        if not path.exists() or not path.is_file():
            return False, None
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _find_section(md_text: str, title: str) -> Optional[str]:
    lines = md_text.splitlines()
    title_lower = title.strip().lower()
    start_idx = None
    for i, line in enumerate(lines):
        if title_lower in line.strip().lower():
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    # Collect until next markdown heading
    collected: List[str] = []
    for j in range(start_idx, len(lines)):
        line = lines[j]
        if line.strip().startswith("#"):
            break
        collected.append(line)
    section = "\n".join(collected).strip()
    return section if section else None


def _count_bullets(text: str) -> int:
    count = 0
    for line in text.splitlines():
        l = line.strip()
        if l.startswith("- ") or l.startswith("* ") or re.match(r"^\d+\.\s+", l):
            count += 1
    return count


def _compute_expected_from_inventory(inv: List[Dict[str, Any]]) -> Dict[str, Any]:
    available = [x for x in inv if x.get("status") == "available"]
    # Rules from tests/test_inventory.py
    # 1) designer caps exactly 'HVRMINN'
    designer_fail = [x for x in available if x.get("designer") != "HVRMINN"]
    # 2) decade == '1980s'
    decade_fail = [x for x in available if x.get("decade") != "1980s"]
    # 3) sku format ^HV-198[0-9]-[A-Z0-9]{4}$
    pat = re.compile(r"^HV-198[0-9]-[A-Z0-9]{4}$")
    sku_fail = [x for x in available if not pat.match((x.get("sku") or ""))]
    total_failures = len(designer_fail) + len(decade_fail) + len(sku_fail)
    return {
        "available": available,
        "designer_fail_count": len(designer_fail),
        "decade_fail_count": len(decade_fail),
        "sku_fail_count": len(sku_fail),
        "total_failures": total_failures,
        "expected_tests_run": 3,
        "expected_errors": 0,
        "expected_success": total_failures == 0,
    }


def _parse_unittest_output_numbers(text: str) -> Dict[str, Optional[int]]:
    # Extract "Ran X tests" and failures/errors from FAILED(...) or OK
    numbers: Dict[str, Optional[int]] = {"testsRun": None, "failures": None, "errors": None}
    m = re.search(r"Ran\s+(\d+)\s+tests?", text)
    if m:
        try:
            numbers["testsRun"] = int(m.group(1))
        except Exception:
            numbers["testsRun"] = None
    # Look for FAILED (failures=F[, errors=E]) or OK
    m2 = re.search(r"FAILED\s*\(([^)]+)\)", text)
    if m2:
        inside = m2.group(1)
        mf = re.search(r"failures\s*=\s*(\d+)", inside)
        me = re.search(r"errors\s*=\s*(\d+)", inside)
        try:
            numbers["failures"] = int(mf.group(1)) if mf else 0
        except Exception:
            numbers["failures"] = None
        try:
            numbers["errors"] = int(me.group(1)) if me else 0
        except Exception:
            numbers["errors"] = None
    else:
        # If OK appears, assume failures=0, errors=0
        if re.search(r"^OK\b", text, flags=re.MULTILINE) or " OK" in text:
            numbers["failures"] = 0
            numbers["errors"] = 0
    return numbers


def _contains_number(text: str, number: int) -> bool:
    # Search for whole integer occurrence
    pattern = r"(?<!\d)" + re.escape(str(number)) + r"(?!\d)"
    return re.search(pattern, text) is not None


def _sentence_split(text: str) -> List[str]:
    parts = re.split(r"[.!?]+", text)
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "tests_outputs_exist": 0.0,
        "test_summary_schema": 0.0,
        "test_summary_expected_values": 0.0,
        "test_results_consistent_with_summary": 0.0,
        "catalog_exists": 0.0,
        "catalog_filtered_correctly": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_tests_summary": 0.0,
        "meeting_notes_release_artifact": 0.0,
        "meeting_notes_action_items_quality": 0.0,
        "meeting_notes_next_steps": 0.0,
        "email_exists": 0.0,
        "email_addressed_ava": 0.0,
        "email_summaries_and_counts": 0.0,
        "email_prioritize_and_signoff": 0.0,
    }

    out_dir = workspace / "out"
    test_results_path = out_dir / "test_results.txt"
    test_summary_path = out_dir / "test_summary.json"
    catalog_path = out_dir / "catalog.json"
    notes_path = out_dir / "meeting_notes.md"
    email_path = out_dir / "email_to_dev.txt"
    inventory_path = workspace / "data" / "inventory.json"
    agenda_path = workspace / "docs" / "meeting_agenda.md"

    # Existence of outputs (tests)
    tr_ok, tr_text = _read_text_safe(test_results_path)
    ts_ok, ts_json = _load_json_safe(test_summary_path)
    if tr_ok and ts_ok:
        scores["tests_outputs_exist"] = 1.0

    # Validate test summary schema
    if ts_ok and isinstance(ts_json, dict):
        required_keys = ["testsRun", "failures", "errors", "wasSuccessful", "failedTests", "errorTests"]
        types_ok = all(k in ts_json for k in required_keys)
        types_ok = types_ok and isinstance(ts_json.get("testsRun"), int)
        types_ok = types_ok and isinstance(ts_json.get("failures"), int)
        types_ok = types_ok and isinstance(ts_json.get("errors"), int)
        types_ok = types_ok and isinstance(ts_json.get("wasSuccessful"), bool)
        types_ok = types_ok and isinstance(ts_json.get("failedTests"), list)
        types_ok = types_ok and isinstance(ts_json.get("errorTests"), list)
        if types_ok:
            scores["test_summary_schema"] = 1.0

    # Compute expected from inventory and compare with summary values
    inv_ok, inv = _load_json_safe(inventory_path)
    if inv_ok and isinstance(inv, list) and ts_ok and isinstance(ts_json, dict):
        expected = _compute_expected_from_inventory(inv)
        expected_tests_run = expected["expected_tests_run"]
        expected_failures = expected["total_failures"]
        expected_errors = expected["expected_errors"]
        expected_success = expected["expected_success"]
        # also check failedTests length equals failures and errorTests equals errors
        failed_tests_len = len(ts_json.get("failedTests")) if isinstance(ts_json.get("failedTests"), list) else -1
        error_tests_len = len(ts_json.get("errorTests")) if isinstance(ts_json.get("errorTests"), list) else -1
        if (
            ts_json.get("testsRun") == expected_tests_run
            and ts_json.get("failures") == expected_failures
            and ts_json.get("errors") == expected_errors
            and ts_json.get("wasSuccessful") == expected_success
            and failed_tests_len == expected_failures
            and error_tests_len == expected_errors
        ):
            scores["test_summary_expected_values"] = 1.0

    # Test results consistent with summary
    if tr_ok and ts_ok and isinstance(ts_json, dict):
        parsed = _parse_unittest_output_numbers(tr_text or "")
        consistent = True
        # Check testsRun
        if parsed["testsRun"] is not None:
            consistent = consistent and (parsed["testsRun"] == ts_json.get("testsRun"))
        # If any failures/errors > 0, expect FAILED line; else OK
        failures = ts_json.get("failures")
        errors = ts_json.get("errors")
        if isinstance(failures, int) and isinstance(errors, int):
            if failures == 0 and errors == 0:
                consistent = consistent and ("OK" in (tr_text or ""))
            else:
                # Ensure FAILED and counts match if present
                consistent = consistent and ("FAILED" in (tr_text or ""))
                if parsed["failures"] is not None:
                    consistent = consistent and (parsed["failures"] == failures)
                if parsed["errors"] is not None:
                    consistent = consistent and (parsed["errors"] == errors)
        if consistent:
            scores["test_results_consistent_with_summary"] = 1.0

    # Catalog existence
    cat_ok, cat_json = _load_json_safe(catalog_path)
    if cat_ok and isinstance(cat_json, list):
        scores["catalog_exists"] = 1.0

    # Catalog filtered correctness against inventory
    if inv_ok and isinstance(inv, list) and cat_ok and isinstance(cat_json, list):
        expected_available = [x for x in inv if x.get("status") == "available"]
        if cat_json == expected_available:
            scores["catalog_filtered_correctly"] = 1.0

    # Meeting notes existence
    mn_ok, mn_text = _read_text_safe(notes_path)
    if mn_ok and isinstance(mn_text, str) and mn_text.strip():
        scores["meeting_notes_exists"] = 1.0

    # Meeting notes: Tests Summary section with numbers from test_summary.json
    if mn_ok and ts_ok and isinstance(ts_json, dict):
        section = _find_section(mn_text or "", "Tests Summary")
        if section:
            t_ok = _contains_number(section, int(ts_json.get("testsRun", -1)))
            f_ok = _contains_number(section, int(ts_json.get("failures", -1)))
            e_ok = _contains_number(section, int(ts_json.get("errors", -1)))
            if t_ok and f_ok and e_ok:
                scores["meeting_notes_tests_summary"] = 1.0

    # Meeting notes: Release Artifact section lists path and count
    if mn_ok and cat_ok and isinstance(cat_json, list):
        section = _find_section(mn_text or "", "Release Artifact")
        if section:
            path_ok = "out/catalog.json" in section
            count_ok = _contains_number(section, len(cat_json))
            if path_ok and count_ok:
                scores["meeting_notes_release_artifact"] = 1.0

    # Meeting notes: Action Items section quality (>=3 items, topical)
    if mn_ok:
        action_section = _find_section(mn_text or "", "Action Items")
        topical_ok = False
        count_ok = False
        if action_section:
            bullets = _count_bullets(action_section)
            count_ok = bullets >= 3
            # Check topical keywords from agenda and failures
            agenda_ok, agenda_text = _read_text_safe(agenda_path)
            keywords = set()
            if agenda_ok and agenda_text:
                # Derive a simple set of keywords from agenda
                for kw in ["SKU", "designer", "capitalization", "Smoke test", "smoke test", "packaging", "release", "CI"]:
                    if kw.lower() in agenda_text.lower():
                        keywords.add(kw.lower())
            # Also ensure failure-related topics are present if failures exist
            musts: List[str] = []
            if ts_ok and isinstance(ts_json, dict) and isinstance(ts_json.get("failures"), int) and ts_json.get("failures") > 0:
                # If failures, expect mention of 'sku' or 'designer'
                musts = ["sku", "designer"]
            text_lower = action_section.lower()
            topical_hits = 0
            for k in keywords:
                if k in text_lower:
                    topical_hits += 1
            # Check must topics
            must_ok = all(m in text_lower for m in musts) if musts else True
            # At least two topical hits or must_ok if there are musts
            topical_ok = (topical_hits >= 2) and must_ok
        if count_ok and topical_ok:
            scores["meeting_notes_action_items_quality"] = 1.0

    # Meeting notes: Next Steps section mentions upcoming dev call
    if mn_ok:
        section = _find_section(mn_text or "", "Next Steps")
        if section:
            # Look for reference to dev call/meeting
            if re.search(r"\bdev\b", section.lower()) or re.search(r"\bcall\b", section.lower()) or re.search(r"\bmeeting\b", section.lower()):
                # Ensure some actionable content (at least one bullet or sentence)
                has_content = bool(section.strip())
                if has_content:
                    scores["meeting_notes_next_steps"] = 1.0

    # Email existence
    em_ok, em_text = _read_text_safe(email_path)
    if em_ok and isinstance(em_text, str) and em_text.strip():
        scores["email_exists"] = 1.0

    # Email addressed to Ava
    if em_ok and em_text:
        first_part = em_text[:200]
        if re.search(r"\bava\b", first_part, flags=re.IGNORECASE):
            scores["email_addressed_ava"] = 1.0

    # Email summaries and counts: 3–6 sentences, includes test numbers and catalog info
    if em_ok and em_text and ts_ok and isinstance(ts_json, dict) and cat_ok and isinstance(cat_json, list):
        sentences = _sentence_split(em_text)
        length_ok = 3 <= len(sentences) <= 6
        # test numbers present
        tests_run = ts_json.get("testsRun")
        failures = ts_json.get("failures")
        errors = ts_json.get("errors")
        tests_ok = False
        if isinstance(tests_run, int) and isinstance(failures, int) and isinstance(errors, int):
            # Check presence in same sentence or across text with context
            tests_ok = (
                _contains_number(em_text, tests_run)
                and re.search(r"fail", em_text, flags=re.IGNORECASE) is not None
                and _contains_number(em_text, failures)
                and re.search(r"error", em_text, flags=re.IGNORECASE) is not None
                and _contains_number(em_text, errors)
            )
        # catalog path and count
        catalog_ok = ("out/catalog.json" in em_text) and _contains_number(em_text, len(cat_json))
        if length_ok and tests_ok and catalog_ok:
            scores["email_summaries_and_counts"] = 1.0

    # Email prioritization of fixes and courteous sign-off
    if em_ok and em_text:
        # Prioritize fixes request for failing checks (SKU or designer)
        prioritize = re.search(r"prioriti[sz]e|priority|focus on", em_text, flags=re.IGNORECASE) is not None
        fix = re.search(r"\bfix|address|resolve", em_text, flags=re.IGNORECASE) is not None
        topical = re.search(r"\bSKU\b|\bdesigner\b|capitalization", em_text, flags=re.IGNORECASE) is not None
        request_ok = prioritize and fix and topical
        # Courteous sign-off at the end
        lines = [l.strip() for l in em_text.splitlines() if l.strip()]
        signoff_ok = False
        if lines:
            tail = " ".join(lines[-2:]) if len(lines) >= 2 else lines[-1]
            if re.search(r"\b(Thanks|Thank you|Best|Regards|Sincerely|Cheers)\b", tail, flags=re.IGNORECASE):
                signoff_ok = True
        if request_ok and signoff_ok:
            scores["email_prioritize_and_signoff"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()