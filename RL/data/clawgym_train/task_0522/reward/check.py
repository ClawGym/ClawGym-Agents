import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import runpy


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames[:] if reader.fieldnames else None
            return rows, header
    except Exception:
        return None, None


def _float(s: Any) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _int(s: Any) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _is_close(a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-2) -> bool:
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)


def _parse_html_tags(html: str) -> Dict[str, Dict[str, Optional[str]]]:
    # Extract <li data-show-id="..."> ... <span class="tag">Text</span> ... </li>
    # Return mapping: show_id -> {"web_tag": tag_text_or_None, "tag_category": mapped_category_or_None}
    tag_map = {
        "DIY Night": "DIY",
        "Sponsored Event": "Corporate",
    }
    results: Dict[str, Dict[str, Optional[str]]] = {}
    li_pattern = re.compile(r'<li[^>]*data-show-id="([^"]+)"[^>]*>(.*?)</li>', re.DOTALL | re.IGNORECASE)
    tag_span_pattern = re.compile(r'<span[^>]*class="tag"[^>]*>\s*(.*?)\s*</span>', re.DOTALL | re.IGNORECASE)
    for m in li_pattern.finditer(html):
        show_id = m.group(1)
        inner = m.group(2)
        tag_m = tag_span_pattern.search(inner)
        web_tag = tag_m.group(1).strip() if tag_m else None
        tag_category = tag_map.get(web_tag) if web_tag is not None else None
        results[show_id] = {"web_tag": web_tag, "tag_category": tag_category}
    return results


def _load_labeler(workspace: Path):
    labeler_path = workspace / "input" / "site" / "labeler.py"
    diy_keywords = [
        "community center",
        "house show",
        "warehouse",
        "co-op",
        "all-ages",
        "all ages",
        "zine library",
        "fundraiser",
        "collective",
    ]
    corporate_keywords = [
        "sponsored",
        "brand stage",
        "arena",
        "ticketmaster",
        "corporate festival",
        "corporate",
    ]
    DIY_TICKETING = {"at-door", "sliding-scale"}
    CORP_TICKETING = {"ticketmaster"}

    def fallback_categorize_show(notes: str, tickets_platform: str) -> str:
        n = (notes or "").lower()
        t = (tickets_platform or "").strip().lower()
        diy_bias = any(k in n for k in diy_keywords) or (t in DIY_TICKETING)
        corp_bias = any(k in n for k in corporate_keywords) or (t in CORP_TICKETING)
        if diy_bias and corp_bias:
            return "Mixed"
        if diy_bias:
            return "DIY"
        if corp_bias:
            return "Corporate"
        return "Mixed"

    if not labeler_path.exists():
        return fallback_categorize_show

    try:
        ns = runpy.run_path(str(labeler_path))
        if "categorize_show" in ns and callable(ns["categorize_show"]):
            return ns["categorize_show"]
        # If function missing, fall back
        return fallback_categorize_show
    except Exception:
        return fallback_categorize_show


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    # Load inputs
    csv_path = workspace / "input" / "tour_log.csv"
    html_path = workspace / "input" / "website" / "tour_archive.html"
    rows, _ = _safe_read_csv(csv_path)
    html = _safe_read_text(html_path)
    if rows is None or html is None:
        return None

    labeler = _load_labeler(workspace)
    by_id: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        sid = r.get("show_id")
        if not sid:
            continue
        attendees = _int(r.get("attendees"))
        merch = _float(r.get("merch_gross_usd"))
        notes = r.get("notes", "")
        tickets_platform = r.get("tickets_platform", "")
        derived = labeler(notes, tickets_platform)
        mpa = None
        if attendees is not None and merch is not None and attendees != 0:
            mpa = merch / attendees
        by_id[sid] = {
            "show_id": sid,
            "date": r.get("date"),
            "city": r.get("city"),
            "venue": r.get("venue"),
            "notes": notes,
            "attendees": attendees,
            "merch_gross_usd": merch,
            "tickets_platform": tickets_platform,
            "derived_category": derived,
            "merch_per_attendee": mpa,
        }

    tag_info = _parse_html_tags(html)
    for sid, data in by_id.items():
        tag_entry = tag_info.get(sid, {"web_tag": None, "tag_category": None})
        data["web_tag"] = tag_entry.get("web_tag")
        data["tag_category"] = tag_entry.get("tag_category")
        mismatch = (data["tag_category"] is not None) and (data["derived_category"] != data["tag_category"])
        data["mismatch"] = mismatch

    # Aggregates
    categories = ["DIY", "Corporate", "Mixed"]
    totals_by_category = {c: 0 for c in categories}
    attendees_by_category: Dict[str, List[int]] = {c: [] for c in categories}
    mpa_by_category: Dict[str, List[float]] = {c: [] for c in categories}
    for d in by_id.values():
        cat = d["derived_category"]
        if cat not in totals_by_category:
            continue
        totals_by_category[cat] += 1
        if d["attendees"] is not None:
            attendees_by_category[cat].append(d["attendees"])
        if d["merch_per_attendee"] is not None:
            mpa_by_category[cat].append(d["merch_per_attendee"])

    total_shows = sum(totals_by_category.values())
    percent_by_category: Dict[str, float] = {}
    for c in categories:
        percent_by_category[c] = (totals_by_category[c] / total_shows) if total_shows else 0.0

    def avg(lst: List[float]) -> Optional[float]:
        return (sum(lst) / len(lst)) if lst else None

    avg_attendees_by_category = {c: avg(attendees_by_category[c]) for c in categories}
    avg_mpa_by_category = {c: avg(mpa_by_category[c]) for c in categories}

    mismatches = []
    for d in by_id.values():
        if d["tag_category"] is not None and d["derived_category"] != d["tag_category"]:
            mismatches.append({
                "show_id": d["show_id"],
                "derived_category": d["derived_category"],
                "tag_category": d["tag_category"],
            })

    expected = {
        "by_id": by_id,
        "totals_by_category": totals_by_category,
        "percent_by_category": percent_by_category,
        "avg_attendees_by_category": avg_attendees_by_category,
        "avg_merch_per_attendee_by_category": avg_mpa_by_category,
        "mismatches": mismatches,
    }
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "show_classification_file_and_schema": 0.0,
        "show_classification_row_coverage": 0.0,
        "derived_category_accuracy": 0.0,
        "web_tag_mapping_accuracy": 0.0,
        "mismatch_flag_accuracy": 0.0,
        "merch_per_attendee_accuracy": 0.0,
        "summary_file_and_keys": 0.0,
        "summary_totals_correct": 0.0,
        "summary_percentages_correct": 0.0,
        "summary_averages_correct": 0.0,
        "summary_mismatches_correct": 0.0,
        "report_exists_and_length": 0.0,
        "report_mentions_categories_and_mismatch": 0.0,
        "report_includes_avg_merch_numbers": 0.0,
    }

    # Compute expected from inputs
    expected = _compute_expected(workspace)
    if expected is None:
        # Cannot compute anything without inputs; return zeros
        return scores

    expected_by_id = expected["by_id"]
    expected_totals = expected["totals_by_category"]
    expected_percents = expected["percent_by_category"]
    expected_avg_att = expected["avg_attendees_by_category"]
    expected_avg_mpa = expected["avg_merch_per_attendee_by_category"]
    expected_mismatches = expected["mismatches"]
    all_show_ids = set(expected_by_id.keys())
    categories = ["DIY", "Corporate", "Mixed"]

    # 1) Validate outputs/show_classification.csv
    sc_path = workspace / "outputs" / "show_classification.csv"
    sc_rows, sc_header = _safe_read_csv(sc_path)

    expected_header = [
        "show_id",
        "date",
        "city",
        "venue",
        "derived_category",
        "web_tag",
        "tag_category",
        "mismatch",
        "attendees",
        "merch_gross_usd",
        "merch_per_attendee",
    ]

    if sc_rows is not None and sc_header is not None and sc_header == expected_header:
        scores["show_classification_file_and_schema"] = 1.0

    # Proceed with row checks if rows available
    if sc_rows is not None:
        # Coverage
        present_ids = set()
        for r in sc_rows:
            sid = r.get("show_id")
            if sid:
                present_ids.add(sid)
        if all_show_ids:
            coverage = len(all_show_ids & present_ids) / len(all_show_ids)
            scores["show_classification_row_coverage"] = coverage

        # Derived category accuracy, tag mapping, mismatch flag, merch_per_attendee accuracy
        correct_derived = 0
        correct_tag_map = 0
        correct_mismatch = 0
        correct_mpa = 0
        considered = 0
        for r in sc_rows:
            sid = r.get("show_id")
            if sid not in expected_by_id:
                continue
            considered += 1
            exp = expected_by_id[sid]
            # Derived
            if r.get("derived_category") == exp["derived_category"]:
                correct_derived += 1
            # Tag mapping: web_tag must equal html web_tag (allow None -> empty)
            web_tag_out = r.get("web_tag")
            tag_category_out = r.get("tag_category")
            if (web_tag_out or None) == (exp["web_tag"] or None) and (tag_category_out or None) == (exp["tag_category"] or None):
                correct_tag_map += 1
            # Mismatch flag: true/false
            mismatch_str = (r.get("mismatch") or "").strip().lower()
            mismatch_bool = True if mismatch_str == "true" else False if mismatch_str == "false" else None
            if mismatch_bool is not None and mismatch_bool == bool(exp["mismatch"]):
                correct_mismatch += 1
            # Merch per attendee numeric closeness
            mpa_val = _float(r.get("merch_per_attendee"))
            if exp["merch_per_attendee"] is None:
                # If cannot compute, require empty/None
                if mpa_val is None:
                    correct_mpa += 1
            else:
                if mpa_val is not None and _is_close(mpa_val, exp["merch_per_attendee"], rel_tol=1e-6, abs_tol=1e-2):
                    correct_mpa += 1

        denom = max(considered, 1)
        scores["derived_category_accuracy"] = correct_derived / denom
        scores["web_tag_mapping_accuracy"] = correct_tag_map / denom
        scores["mismatch_flag_accuracy"] = correct_mismatch / denom
        scores["merch_per_attendee_accuracy"] = correct_mpa / denom

    # 2) Validate outputs/summary.json
    summary_path = workspace / "outputs" / "summary.json"
    summary = _safe_read_json(summary_path)
    required_keys = {
        "totals_by_category",
        "percent_by_category",
        "avg_attendees_by_category",
        "avg_merch_per_attendee_by_category",
        "mismatches_count",
        "mismatches",
    }
    if isinstance(summary, dict) and required_keys.issubset(summary.keys()):
        scores["summary_file_and_keys"] = 1.0

        # Totals correct
        totals_ok_count = 0
        totals = summary.get("totals_by_category", {})
        if isinstance(totals, dict):
            for c in categories:
                if _int(totals.get(c)) == expected_totals.get(c, None):
                    totals_ok_count += 1
        scores["summary_totals_correct"] = totals_ok_count / len(categories) if categories else 0.0

        # Percentages correct (accept 0-1 or 0-100)
        perc_ok_count = 0
        perc = summary.get("percent_by_category", {})
        if isinstance(perc, dict):
            for c in categories:
                reported = _float(perc.get(c))
                if reported is None:
                    continue
                exp_prop = expected_percents.get(c, 0.0)
                ok = False
                if _is_close(reported, exp_prop, abs_tol=1e-3):
                    ok = True
                elif _is_close(reported, exp_prop * 100.0, abs_tol=0.1):
                    ok = True
                if ok:
                    perc_ok_count += 1
        scores["summary_percentages_correct"] = perc_ok_count / len(categories) if categories else 0.0

        # Averages correct (attendees and mpa)
        avg_ok_total = 0
        avg_checks = 0
        avg_att = summary.get("avg_attendees_by_category", {})
        avg_mpa = summary.get("avg_merch_per_attendee_by_category", {})
        # attendees
        if isinstance(avg_att, dict):
            for c in categories:
                exp_val = expected_avg_att.get(c)
                rep = _float(avg_att.get(c))
                # If no shows, accept None/missing/0
                if expected_totals.get(c, 0) == 0:
                    if c not in avg_att or avg_att.get(c) in (None, "None", "", 0, 0.0):
                        avg_ok_total += 1
                else:
                    if rep is not None and exp_val is not None and _is_close(rep, float(exp_val), abs_tol=1e-6):
                        avg_ok_total += 1
                avg_checks += 1
        # mpa
        if isinstance(avg_mpa, dict):
            for c in categories:
                exp_val = expected_avg_mpa.get(c)
                rep = _float(avg_mpa.get(c))
                if expected_totals.get(c, 0) == 0:
                    if c not in avg_mpa or avg_mpa.get(c) in (None, "None", "", 0, 0.0):
                        avg_ok_total += 1
                else:
                    if rep is not None and exp_val is not None and _is_close(rep, float(exp_val), abs_tol=1e-2):
                        avg_ok_total += 1
                avg_checks += 1
        scores["summary_averages_correct"] = (avg_ok_total / avg_checks) if avg_checks else 0.0

        # Mismatches correct
        mismatches = summary.get("mismatches", [])
        mismatches_count = summary.get("mismatches_count")
        ok_count = 0.0
        # Count check
        if _int(mismatches_count) == len(expected_mismatches):
            ok_count += 0.5
        # Content check: compare sets of (show_id, derived, tag)
        def to_tuple_list(lst):
            out = []
            for x in lst:
                sid = x.get("show_id")
                d = x.get("derived_category")
                t = x.get("tag_category")
                out.append((sid, d, t))
            return sorted(out)

        if isinstance(mismatches, list):
            reported_set = set(to_tuple_list(mismatches))
            expected_set = set(to_tuple_list(expected_mismatches))
            if reported_set == expected_set:
                ok_count += 0.5
        scores["summary_mismatches_correct"] = ok_count

    # 3) Validate outputs/authenticity_report.md
    report_path = workspace / "outputs" / "authenticity_report.md"
    report_text = _safe_read_text(report_path)
    if report_text is not None:
        # Word count 150–250 inclusive
        words = re.findall(r"\b\S+\b", report_text)
        wc = len(words)
        if 150 <= wc <= 250:
            scores["report_exists_and_length"] = 1.0

        # Mentions categories and mismatches (call out show_ids)
        text_lower = report_text.lower()
        has_diy = "diy" in text_lower
        has_corp = "corporate" in text_lower
        has_mixed = "mixed" in text_lower
        # All categories mentioned
        cats_ok = has_diy and has_corp and has_mixed
        # All mismatch show_ids mentioned
        mism_ok = True
        for m in expected_mismatches:
            if m["show_id"] not in report_text:
                mism_ok = False
                break
        if cats_ok and mism_ok:
            scores["report_mentions_categories_and_mismatch"] = 1.0

        # Includes average merch-per-attendee numbers for DIY and Corporate (rounded to 2 decimals)
        def fmt2(x: Optional[float]) -> Optional[str]:
            if x is None:
                return None
            return f"{x:.2f}"

        diy_avg_mpa_str = fmt2(expected_avg_mpa.get("DIY"))
        corp_avg_mpa_str = fmt2(expected_avg_mpa.get("Corporate"))
        nums_ok = True
        if diy_avg_mpa_str is None or diy_avg_mpa_str not in report_text:
            nums_ok = False
        if corp_avg_mpa_str is None or corp_avg_mpa_str not in report_text:
            nums_ok = False
        if nums_ok:
            scores["report_includes_avg_merch_numbers"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()