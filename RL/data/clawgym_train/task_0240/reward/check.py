import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _to_int(s: str) -> Optional[int]:
    try:
        return int(s.strip())
    except Exception:
        return None


def _normalize_hyphens(text: str) -> str:
    # Replace common unicode dash variants with standard hyphen
    return text.replace("\u2011", "-").replace("\u2012", "-").replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")


def _extract_paragraphs(md: str) -> List[str]:
    # Split on blank lines into paragraphs
    parts = re.split(r"\n\s*\n", md.strip(), flags=re.MULTILINE)
    return [p.strip() for p in parts if p.strip()]


def _tokens(text: str) -> List[str]:
    return re.findall(r"\b[\w']+\b", text)


def _compute_metrics(rows: List[Dict[str, str]]) -> Optional[Dict]:
    # Parse rows with types
    parsed = []
    for r in rows:
        d = _parse_date(r.get("date", ""))
        if d is None:
            return None
        likes = _to_int(r.get("likes", ""))
        if likes is None:
            return None
        answered_str = (r.get("answered", "") or "").strip().lower()
        if answered_str not in ("yes", "no"):
            return None
        parsed.append({
            "id": (r.get("id") or "").strip(),
            "date": d,
            "asker": (r.get("asker") or "").strip(),
            "category": (r.get("category") or "").strip(),
            "likes": likes,
            "answered": (answered_str == "yes"),
            "question_text": (r.get("question_text") or "").strip(),
        })
    if not parsed:
        return None

    # Determine 14-day window including endpoints
    max_date = max(p["date"] for p in parsed)
    start_date = max_date - timedelta(days=13)
    end_date = max_date

    window = [p for p in parsed if start_date <= p["date"] <= end_date]

    # Even if window empty, still compute metrics (but task expects data; however handle gracefully)
    total = len(window)
    answered_count = sum(1 for p in window if p["answered"])
    unique_askers = len(set(p["asker"] for p in window))
    sum_likes = sum(p["likes"] for p in window)
    avg_likes = (sum_likes / total) if total > 0 else 0.0

    answered_likes = [p["likes"] for p in window if p["answered"]]
    unanswered_likes = [p["likes"] for p in window if not p["answered"]]
    avg_ans = (sum(answered_likes) / len(answered_likes)) if answered_likes else 0.0
    avg_unans = (sum(unanswered_likes) / len(unanswered_likes)) if unanswered_likes else 0.0

    # Category stats
    cat_map: Dict[str, Dict[str, float]] = {}
    for p in window:
        c = p["category"]
        if c not in cat_map:
            cat_map[c] = {"count": 0, "sum_likes": 0.0}
        cat_map[c]["count"] += 1
        cat_map[c]["sum_likes"] += p["likes"]
    categories = []
    for c, v in cat_map.items():
        count = int(v["count"])
        avg = (v["sum_likes"] / count) if count > 0 else 0.0
        categories.append({"category": c, "count": count, "avg": avg})
    categories_sorted = sorted(categories, key=lambda x: (-x["avg"], x["category"].lower()))

    # Top 5 by likes
    top_sorted = sorted(window, key=lambda p: (-p["likes"], p["id"]))
    top5 = [{"id": p["id"], "category": p["category"], "likes": p["likes"]} for p in top_sorted[:5]]

    # Top 3 categories by avg likes among categories with at least 2 questions
    cats_2plus = [c for c in categories_sorted if c["count"] >= 2]
    top3_2plus = cats_2plus[:3]

    # Compute answer rate percentage with one decimal
    answer_rate = (answered_count / total * 100.0) if total > 0 else 0.0

    return {
        "start_date": start_date.date().isoformat(),
        "end_date": end_date.date().isoformat(),
        "total": total,
        "answered": answered_count,
        "answer_rate_pct_str": f"{answer_rate:.1f}%",
        "unique_askers": unique_askers,
        "avg_likes_str": f"{avg_likes:.1f}",
        "avg_likes_answered_str": f"{avg_ans:.1f}",
        "avg_likes_unanswered_str": f"{avg_unans:.1f}",
        "categories_sorted": [
            {"category": c["category"], "count": c["count"], "avg_str": f"{c['avg']:.1f}", "avg": c["avg"]}
            for c in categories_sorted
        ],
        "top5": top5,
        "top3_cats_2plus": [
            {"category": c["category"], "avg_str": f"{c['avg']:.1f}", "avg": c["avg"], "count": c["count"]}
            for c in top3_2plus
        ],
        "all_categories": [c["category"] for c in categories_sorted],
    }


def _find_line_with_keyword_and_number(lines: List[str], keyword: str, number_str: str) -> Optional[str]:
    for line in lines:
        if keyword.lower() in line.lower() and number_str in line:
            return line
    return None


def _contains_number_in_context(text: str, context_words: List[str], number_str: str) -> bool:
    tl = text.lower()
    if not all(w.lower() in tl for w in context_words):
        return False
    return number_str in text


def _extract_section_lines(md_text: str, header_substring: str, other_headers: List[str]) -> List[str]:
    lines = md_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if header_substring.lower() in line.lower():
            start = i + 1
            break
    if start is None:
        return []
    # Find end: next other header occurrence
    end = len(lines)
    for j in range(start, len(lines)):
        for h in other_headers:
            if h.lower() in lines[j].lower():
                end = j
                break
        if end != len(lines):
            break
    # Return non-empty lines in section range
    return [ln for ln in lines[start:end] if ln.strip()]


def _line_order_indices(lines: List[str], names: List[str]) -> List[int]:
    # Returns indices of first occurrence of each name in lines; -1 if not found
    indices = []
    for name in names:
        idx = -1
        for i, ln in enumerate(lines):
            if name.lower() in ln.lower():
                idx = i
                break
        indices.append(idx)
    return indices


def _find_float_after_keyword(text: str, keyword: str, expected: str) -> bool:
    # Find a float token within some characters after keyword that equals expected (string match)
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    for m in pattern.finditer(text):
        start = m.end()
        window = text[start:start + 60]  # 60-char window after keyword
        floats = re.findall(r"(\d+\.\d)", window)
        if expected in floats:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "engagement_summary_exists": 0.0,
        "engagement_summary_overview_window_correct": 0.0,
        "engagement_summary_overview_totals_correct": 0.0,
        "engagement_summary_overview_uniques_and_averages_correct": 0.0,
        "engagement_summary_category_breakdown_correct": 0.0,
        "engagement_summary_top5_correct": 0.0,
        "rewritten_post_exists": 0.0,
        "rewritten_post_word_count_250_350": 0.0,
        "rewritten_post_by_the_numbers_present_and_positioned": 0.0,
        "rewritten_post_by_the_numbers_metrics_correct": 0.0,
        "rewritten_post_by_the_numbers_top3_categories_correct": 0.0,
        "rewritten_post_principles_present": 0.0,
        "rewritten_post_ending_call_to_action": 0.0,
    }

    # Load data and compute expected metrics
    input_csv = workspace / "input" / "fan_questions.csv"
    rows = _load_csv_rows(input_csv)
    metrics = None
    if rows is not None:
        metrics = _compute_metrics(rows)

    # Check engagement summary
    summary_path = workspace / "outputs" / "engagement_summary.md"
    if summary_path.exists():
        scores["engagement_summary_exists"] = 1.0
        summary_text = _read_text(summary_path) or ""
        # Proceed only if metrics are available
        if metrics is not None:
            # Overview window correct
            has_overview_header = "Overview (last 14 days)" in summary_text
            ref_line = f"Reference window: {metrics['start_date']} to {metrics['end_date']}"
            if has_overview_header and (ref_line in summary_text):
                scores["engagement_summary_overview_window_correct"] = 1.0

            # Overview totals correct
            totals_ok = False
            if "Overview (last 14 days)" in summary_text:
                # Find lines
                lines = summary_text.splitlines()
                total_ok = any(("Total questions" in ln and str(metrics["total"]) in ln) for ln in lines)
                answered_line_ok = any(
                    ("Questions answered" in ln and str(metrics["answered"]) in ln and metrics["answer_rate_pct_str"] in ln)
                    for ln in lines
                )
                if total_ok and answered_line_ok:
                    totals_ok = True
            if totals_ok:
                scores["engagement_summary_overview_totals_correct"] = 1.0

            # Overview uniques and averages
            ua_ok = False
            if "Overview (last 14 days)" in summary_text:
                lines = summary_text.splitlines()
                unique_ok = any(("Unique askers" in ln and str(metrics["unique_askers"]) in ln) for ln in lines)
                avg_total_ok = any(("Average likes per question" in ln and metrics["avg_likes_str"] in ln) for ln in lines)
                # Average likes for answered vs unanswered
                av_ans_un_ok = any(
                    (("Average likes for answered" in ln) and
                     (metrics["avg_likes_answered_str"] in ln) and
                     (metrics["avg_likes_unanswered_str"] in ln))
                    for ln in lines
                )
                if unique_ok and avg_total_ok and av_ans_un_ok:
                    ua_ok = True
            if ua_ok:
                scores["engagement_summary_overview_uniques_and_averages_correct"] = 1.0

            # Category breakdown correctness and order
            cat_ok = False
            order_ok = False
            if "Category breakdown (last 14 days)" in summary_text:
                section_lines = _extract_section_lines(
                    summary_text,
                    "Category breakdown (last 14 days)",
                    ["Top 5 questions by likes (last 14 days)", "Overview (last 14 days)"]
                )
                expected_cats = metrics["categories_sorted"]
                found_all = True
                for c in expected_cats:
                    name = c["category"]
                    cnt = str(c["count"])
                    avg_str = c["avg_str"]
                    # find a line with the category name containing both the count and avg
                    match = False
                    for ln in section_lines:
                        if name.lower() in ln.lower():
                            # ensure count integer present as a stand-alone number and avg as one-decimal float
                            has_count = bool(re.search(rf"(?<![\d.]){re.escape(cnt)}(?![\d.])", ln))
                            has_avg = (avg_str in ln)
                            if has_count and has_avg:
                                match = True
                                break
                    if not match:
                        found_all = False
                        break
                if found_all:
                    cat_ok = True
                    # Check order by average_likes descending: appearance order should match expected order
                    names_expected = [c["category"] for c in expected_cats]
                    indices = _line_order_indices(section_lines, names_expected)
                    # All indices must be non-negative and non-decreasing
                    if all(idx >= 0 for idx in indices):
                        order_ok = all(indices[i] <= indices[i+1] for i in range(len(indices)-1))
            if cat_ok and order_ok:
                scores["engagement_summary_category_breakdown_correct"] = 1.0

            # Top 5 questions by likes section
            top5_ok = False
            if "Top 5 questions by likes (last 14 days)" in summary_text:
                top_lines = _extract_section_lines(
                    summary_text,
                    "Top 5 questions by likes (last 14 days)",
                    ["Category breakdown (last 14 days)", "Overview (last 14 days)"]
                )
                # Require at least 5 entries matching expected order with id, category, and likes
                expected_top = metrics["top5"]
                matches_in_order = True
                # Find lines containing each expected id, in order, and verify category and likes on that line
                search_pos = 0
                for item in expected_top:
                    found_at = -1
                    for i in range(search_pos, len(top_lines)):
                        ln = top_lines[i]
                        if item["id"] in ln:
                            # verify category and likes present
                            cat_ok_line = item["category"].lower() in ln.lower()
                            # likes as standalone integer
                            like_ok_line = bool(re.search(rf"(?<![\d.]){item['likes']}(?![\d.])", ln))
                            if cat_ok_line and like_ok_line:
                                found_at = i
                                break
                    if found_at == -1:
                        matches_in_order = False
                        break
                    search_pos = found_at + 1
                if matches_in_order:
                    top5_ok = True
            if top5_ok:
                scores["engagement_summary_top5_correct"] = 1.0

    # Check rewritten post
    post_path = workspace / "outputs" / "rewritten_post.md"
    if post_path.exists():
        scores["rewritten_post_exists"] = 1.0
        post_text_raw = _read_text(post_path) or ""
        post_text = post_text_raw.strip()
        # Word count 250-350
        words = _tokens(post_text)
        if 250 <= len(words) <= 350:
            scores["rewritten_post_word_count_250_350"] = 1.0

        # By the numbers paragraph after opening paragraph
        paras = _extract_paragraphs(post_text)
        if len(paras) >= 2:
            bynum_para = paras[1]
            if re.search(r"\bby the numbers\b", bynum_para, flags=re.IGNORECASE):
                scores["rewritten_post_by_the_numbers_present_and_positioned"] = 1.0

        # Metrics correctness in By the numbers paragraph
        if metrics is not None and len(paras) >= 2:
            bynum = paras[1]
            metrics_ok = True
            # total questions
            if not _contains_number_in_context(bynum, ["total", "question"], str(metrics["total"])):
                metrics_ok = False
            # answered count and answer rate
            answered_ok = ("answer" in bynum.lower() and re.search(rf"(?<![\d.]){metrics['answered']}(?![\d.])", bynum))
            rate_ok = (metrics["answer_rate_pct_str"] in bynum)
            if not (answered_ok and rate_ok):
                metrics_ok = False
            if metrics_ok:
                scores["rewritten_post_by_the_numbers_metrics_correct"] = 1.0

            # Top 3 categories with at least 2 questions and their avg likes (one decimal)
            top3_ok = True
            for c in metrics["top3_cats_2plus"]:
                name = c["category"]
                avg_str = c["avg_str"]
                # Require the category name present and a matching float (one decimal) shortly after it
                name_present = name.lower() in bynum.lower()
                float_after = _find_float_after_keyword(bynum, name, avg_str)
                if not (name_present and float_after):
                    top3_ok = False
                    break
            if top3_ok:
                scores["rewritten_post_by_the_numbers_top3_categories_correct"] = 1.0

        # Principles present (breathing routine, pre-point decision, accept the result)
        norm = _normalize_hyphens(post_text).lower()
        principles_ok = all([
            "breathing routine" in norm,
            "pre-point decision" in norm,
            "accept the result" in norm,
        ])
        if principles_ok:
            scores["rewritten_post_principles_present"] = 1.0

        # Ending call to action inviting readers to send questions for next week
        # Check last non-empty paragraph contains "question" and "next week"
        last_para = paras[-1] if paras else post_text
        lp = last_para.strip().lower()
        if ("question" in lp and "next week" in lp):
            scores["rewritten_post_ending_call_to_action"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()