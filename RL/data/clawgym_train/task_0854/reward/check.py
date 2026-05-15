import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional


def _read_text_safe(path: Path) -> Tuple[bool, str]:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
        return True, data
    except Exception:
        return False, ""


def _load_json_safe(path: Path) -> Tuple[bool, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _load_jsonl_safe(path: Path) -> Tuple[bool, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return True, rows
    except Exception:
        return False, []


def _norm_title(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _close_enough_share(val: Any, count: int, total: int, tol_percent: float = 0.5) -> bool:
    # Accept share either as percentage (0..100) or fraction (0..1).
    try:
        v = float(val)
    except Exception:
        return False
    if total <= 0:
        return abs(v) < 1e-9
    pct = 100.0 * (count / total)
    if v <= 1.0:
        # treat as fraction
        return abs(v - (pct / 100.0)) <= (tol_percent / 100.0 + 1e-12)
    else:
        # treat as percentage
        return abs(v - pct) <= (tol_percent + 1e-12)


def _extract_expected_top_threshold(counts_by_id: Dict[str, int], top_n: int = 3) -> int:
    sorted_counts = sorted(counts_by_id.values(), reverse=True)
    if not sorted_counts:
        return 0
    if len(sorted_counts) < top_n:
        return sorted_counts[-1]
    return sorted_counts[top_n - 1]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "html_exists_and_nonempty": 0.0,
        "html_from_owasp_domain_and_title": 0.0,
        "derived_json_structure_valid": 0.0,
        "derived_titles_present_in_html": 0.0,
        "enriched_records_count_match_input": 0.0,
        "enriched_owasp_mapping_correct": 0.0,
        "summary_structure_valid": 0.0,
        "summary_aggregates_correct": 0.0,
        "summary_top_categories_correct": 0.0,
        "summary_categories_extracted_correct": 0.0,
        "unique_components_aggregated": 0.0,
        "report_sections_and_content": 0.0,
    }

    # Paths
    html_path = workspace / "web" / "owasp_top10_2021.html"
    derived_path = workspace / "derived" / "owasp_top10_2021.json"
    input_path = workspace / "input" / "findings.jsonl"
    enriched_path = workspace / "output" / "findings_enriched.jsonl"
    summary_path = workspace / "output" / "risk_summary.json"
    report_path = workspace / "output" / "risk_report.md"

    # Load files where applicable
    html_ok, html_text = _read_text_safe(html_path)
    if html_ok and len(html_text.strip()) > 0:
        scores["html_exists_and_nonempty"] = 1.0

    if html_ok and ("owasp.org" in html_text.lower()) and ("owasp top 10:2021" in html_text.lower() or "owasp top 10 2021" in html_text.lower() or "top 10 web application security risks" in html_text.lower()):
        scores["html_from_owasp_domain_and_title"] = 1.0

    derived_ok, derived_data = _load_json_safe(derived_path)
    derived_list: List[Dict[str, Any]] = derived_data if (derived_ok and isinstance(derived_data, list)) else []

    # Validate derived JSON structure
    def _validate_derived_struct(lst: List[Dict[str, Any]]) -> bool:
        if not isinstance(lst, list):
            return False
        if len(lst) != 10:
            return False
        seen_ids = set()
        for item in lst:
            if not isinstance(item, dict):
                return False
            if "id" not in item or "title" not in item:
                return False
            if not isinstance(item["id"], str) or not isinstance(item["title"], str):
                return False
            if not re.match(r"^A\d{2}:2021$", item["id"]):
                return False
            if not item["title"].strip():
                return False
            # Optional summary/description
            has_optional = False
            if "summary" in item and isinstance(item["summary"], str) and item["summary"].strip():
                has_optional = True
            if "description" in item and isinstance(item["description"], str) and item["description"].strip():
                has_optional = True or has_optional
            # We won't strictly require the optional field to exist for each item due to "if present".
            # But ensure object has no nonsense types.
            # Id uniqueness
            if item["id"] in seen_ids:
                return False
            seen_ids.add(item["id"])
        return True

    if _validate_derived_struct(derived_list):
        scores["derived_json_structure_valid"] = 1.0

    # Derived titles present in HTML content
    if scores["derived_json_structure_valid"] > 0.0 and html_ok:
        titles_present = True
        for item in derived_list:
            t = item.get("title", "")
            if not t or t.strip().lower() not in html_text.lower():
                # try relaxed: substring search (case-insensitive)
                if t and (t.lower() in html_text.lower()):
                    continue
                else:
                    # Another relaxed attempt: collapse spaces/hyphens
                    norm_t = _norm_title(t)
                    norm_html = _norm_title(html_text)
                    if norm_t and (norm_t in norm_html):
                        continue
                    titles_present = False
                    break
        if titles_present:
            scores["derived_titles_present_in_html"] = 1.0

    # Load input findings
    input_ok, input_rows = _load_jsonl_safe(input_path)
    # Load enriched findings
    enriched_ok, enriched_rows = _load_jsonl_safe(enriched_path)

    # Count match
    if input_ok and enriched_ok and len(input_rows) == len(enriched_rows) and len(enriched_rows) > 0:
        scores["enriched_records_count_match_input"] = 1.0

    # Build mapping from derived titles to ids
    title_to_id: Dict[str, str] = {}
    id_to_title: Dict[str, str] = {}
    if scores["derived_json_structure_valid"] > 0.0:
        for item in derived_list:
            title_to_id[_norm_title(item["title"])] = item["id"]
            id_to_title[item["id"]] = item["title"]

    # Validate enriched mapping correctness
    if input_ok and enriched_ok and scores["derived_json_structure_valid"] > 0.0:
        # Build dicts keyed by finding id
        in_by_id = {row.get("id"): row for row in input_rows if isinstance(row, dict) and "id" in row}
        en_by_id = {row.get("id"): row for row in enriched_rows if isinstance(row, dict) and "id" in row}
        mapping_correct = True
        if len(in_by_id) != len(input_rows) or len(en_by_id) != len(enriched_rows):
            mapping_correct = False
        else:
            for fid, in_row in in_by_id.items():
                if fid not in en_by_id:
                    mapping_correct = False
                    break
                hint = in_row.get("owasp_hint", "")
                expected_id = title_to_id.get(_norm_title(hint), "Unmapped")
                actual_id = en_by_id[fid].get("owasp_id")
                if actual_id != expected_id:
                    mapping_correct = False
                    break
        if mapping_correct:
            scores["enriched_owasp_mapping_correct"] = 1.0

    # Load and validate summary
    summary_ok, summary_data = _load_json_safe(summary_path)
    severity_totals_expected: Dict[str, int] = {}
    by_category_expected: Dict[str, int] = {}
    unmatched_expected = 0
    top_categories_threshold = 0
    top_counts_expected: Dict[str, int] = {}
    mapped_total = 0
    unique_components_expected: Dict[str, int] = {}

    # Compute expected aggregates if possible
    if enriched_ok:
        # Build counts
        severity_totals_expected = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
        # We'll recompute severity from input to avoid dependency on enriched correctness, but if input missing severity, use enriched
        if input_ok:
            for r in input_rows:
                sev = r.get("severity")
                if sev in severity_totals_expected:
                    severity_totals_expected[sev] += 1
        else:
            for r in enriched_rows:
                sev = r.get("severity")
                if sev in severity_totals_expected:
                    severity_totals_expected[sev] += 1

        # by_category and unmatched
        by_category_expected = {}
        unmatched_expected = 0
        for r in enriched_rows:
            oid = r.get("owasp_id")
            if oid and isinstance(oid, str) and oid != "Unmapped":
                by_category_expected[oid] = by_category_expected.get(oid, 0) + 1
            else:
                unmatched_expected += 1
        mapped_total = sum(by_category_expected.values())

        # unique components per OWASP id (exclude Unmapped)
        components_by_id: Dict[str, set] = {}
        for r in enriched_rows:
            oid = r.get("owasp_id")
            comp = r.get("component")
            if isinstance(oid, str) and oid != "Unmapped" and isinstance(comp, str):
                components_by_id.setdefault(oid, set()).add(comp)
        unique_components_expected = {oid: len(s) for oid, s in components_by_id.items()}

        # Compute top threshold
        top_categories_threshold = _extract_expected_top_threshold(by_category_expected, top_n=3)
        # Build expected counts for categories above or equal to threshold
        top_counts_expected = {oid: c for oid, c in by_category_expected.items() if c >= top_categories_threshold and mapped_total > 0}

    # Validate summary structure
    def _validate_summary_structure(sd: Any) -> bool:
        if not isinstance(sd, dict):
            return False
        req_keys = {"severity_totals", "by_category", "top_categories", "unmatched_count", "categories_extracted"}
        if not req_keys.issubset(sd.keys()):
            return False
        st = sd.get("severity_totals")
        if not isinstance(st, dict):
            return False
        for k in ["Low", "Medium", "High", "Critical"]:
            if k not in st or not isinstance(st[k], int):
                return False
        bc = sd.get("by_category")
        if not isinstance(bc, dict):
            return False
        for k, v in bc.items():
            if not isinstance(k, str) or not isinstance(v, int):
                return False
        tc = sd.get("top_categories")
        if not isinstance(tc, list) or len(tc) == 0:
            return False
        if len(tc) > 3:
            return False
        for item in tc:
            if not isinstance(item, dict):
                return False
            for f in ["id", "title", "count", "share"]:
                if f not in item:
                    return False
            if not isinstance(item["id"], str):
                return False
            if not isinstance(item["title"], str):
                return False
            if not isinstance(item["count"], int):
                return False
            # share numeric
            try:
                _ = float(item["share"])
            except Exception:
                return False
        if not isinstance(sd.get("unmatched_count"), int):
            return False
        if not isinstance(sd.get("categories_extracted"), int):
            return False
        return True

    if summary_ok and _validate_summary_structure(summary_data):
        scores["summary_structure_valid"] = 1.0

    # Validate summary values
    if summary_ok and scores["summary_structure_valid"] > 0.0 and enriched_ok:
        values_ok = True
        # Severity exact match
        st = summary_data["severity_totals"]
        if st != severity_totals_expected:
            values_ok = False
        # by_category: must match at least all mapped categories counts; allow extra keys (e.g., zeros) and possible inclusion of "Unmapped" which we ignore
        bc = summary_data["by_category"]
        for oid, cnt in by_category_expected.items():
            if bc.get(oid) != cnt:
                values_ok = False
                break
        # unmatched_count exact
        if summary_data.get("unmatched_count") != unmatched_expected:
            values_ok = False
        if values_ok:
            scores["summary_aggregates_correct"] = 1.0

        # top_categories correctness: counts and shares
        tc_list = summary_data["top_categories"]
        # Must be <= 3; ensure each item is among categories with count >= threshold and count matches
        tc_ok = True
        if len(tc_list) > 3:
            tc_ok = False
        # Determine threshold for top 3
        threshold = top_categories_threshold
        # Build set of valid ids at or above threshold (if mapped_total=0, allow empty)
        valid_ids = {oid for oid, cnt in by_category_expected.items() if cnt >= threshold} if mapped_total > 0 else set()
        # If there are fewer than 3 categories total, accept provided length
        for item in tc_list:
            oid = item["id"]
            title = item["title"]
            cnt = item["count"]
            share = item["share"]
            # If there are mapped findings, validate
            if mapped_total > 0:
                if oid not in by_category_expected:
                    tc_ok = False
                    break
                # count must match
                if by_category_expected.get(oid) != cnt:
                    tc_ok = False
                    break
                # id must be among valid top set (count >= threshold)
                if cnt < threshold:
                    tc_ok = False
                    break
                # title must match derived title if available
                if oid in id_to_title:
                    if title != id_to_title[oid]:
                        tc_ok = False
                        break
                # share close enough
                if not _close_enough_share(share, cnt, mapped_total):
                    tc_ok = False
                    break
            else:
                # If no mapped findings, counts should be 0 and share ~0
                if cnt != 0 or not _close_enough_share(share, 0, 0):
                    tc_ok = False
                    break
        # Additionally check ordering non-increasing by count
        counts_only = [item["count"] for item in tc_list]
        if any(counts_only[i] < counts_only[i + 1] for i in range(len(counts_only) - 1)):
            tc_ok = False

        if tc_ok:
            scores["summary_top_categories_correct"] = 1.0

        # categories_extracted equals derived size
        if scores["derived_json_structure_valid"] > 0.0:
            if summary_data.get("categories_extracted") == len(derived_list):
                scores["summary_categories_extracted_correct"] = 1.0

        # unique components per OWASP id
        unique_ok = False
        # Accept one of a few common key names
        for key in ["unique_components_by_category", "unique_components", "components_by_category"]:
            val = summary_data.get(key)
            if isinstance(val, dict) and unique_components_expected:
                # Validate that for all ids present in expected, values match; allow extra keys or missing zeros
                mismatch = False
                for oid, ucnt in unique_components_expected.items():
                    if val.get(oid) != ucnt:
                        mismatch = True
                        break
                if not mismatch:
                    unique_ok = True
                    break
        if unique_ok:
            scores["unique_components_aggregated"] = 1.0

    # Validate report sections and content
    report_ok, report_text = _read_text_safe(report_path)
    if report_ok and report_text.strip():
        # Required sections as substrings, case-insensitive
        required_sections = [
            "Data Sources",
            "Extraction Summary",
            "Findings Coverage",
            "Top Categories",
            "Unmapped",
        ]
        has_sections = all(sec.lower() in report_text.lower() for sec in required_sections)
        has_html_path = "web/owasp_top10_2021.html" in report_text
        # If derived known, check categories_extracted appears as a number in text
        extracted_ok = True
        if scores["derived_json_structure_valid"] > 0.0:
            extracted_ok = str(len(derived_list)) in report_text
        # Severity labels present
        severities_present = all(s in report_text for s in ["Low", "Medium", "High", "Critical"])
        # Unmatched count present
        unmatched_ok = True
        if enriched_ok:
            unmatched_ok = str(unmatched_expected) in report_text
        # Top categories mention: either id or title present for at least two items if possible
        top_mention_ok = True
        if enriched_ok and scores["derived_json_structure_valid"] > 0.0 and mapped_total > 0:
            # Determine top set threshold and candidate ids
            threshold = top_categories_threshold
            candidate_ids = [oid for oid, cnt in by_category_expected.items() if cnt >= threshold]
            mentions = 0
            for oid in candidate_ids:
                title = id_to_title.get(oid, "")
                if (oid in report_text) or (title and title in report_text):
                    mentions += 1
            top_mention_ok = mentions >= min(2, len(candidate_ids))
        if has_sections and has_html_path and extracted_ok and severities_present and unmatched_ok and top_mention_ok:
            scores["report_sections_and_content"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()