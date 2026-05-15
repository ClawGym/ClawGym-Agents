import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        lines = []
        with path.open("r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                lines.append(json.loads(ln))
        return lines
    except Exception:
        return None


def safe_load_keywords(path: Path) -> Optional[List[str]]:
    try:
        content = path.read_text(encoding="utf-8")
        kws = []
        for line in content.splitlines():
            kw = line.strip()
            if kw:
                kws.append(kw)
        return kws
    except Exception:
        return None


def count_overlapping_occurrences(text: str, sub: str) -> int:
    if not sub:
        return 0
    text_l = text.lower()
    sub_l = sub.lower()
    count = 0
    i = 0
    while True:
        idx = text_l.find(sub_l, i)
        if idx == -1:
            break
        count += 1
        i = idx + 1
    return count


def compute_expected_scan(movies: List[dict], keywords: List[str]) -> Dict[str, dict]:
    expected = {}
    for m in movies:
        movie_id = m.get("id")
        title = m.get("title")
        synopsis = m.get("synopsis") or ""
        review = m.get("review") or ""
        user_tags = m.get("user_tags") or []
        combined = synopsis + " " + review
        keyword_counts = {}
        total_hits = 0
        for kw in keywords:
            c = count_overlapping_occurrences(combined, kw)
            keyword_counts[kw] = c
            total_hits += c
        matched = [kw for kw in keywords if keyword_counts.get(kw, 0) > 0]
        matched_keywords = ";".join(matched)
        flagged = total_hits >= 2
        tags_has_spoiler = any(isinstance(t, str) and t == "spoiler" for t in user_tags)
        expected[movie_id] = {
            "movie_id": movie_id,
            "title": title,
            "keyword_hits": total_hits,
            "matched_keywords": matched_keywords,
            "flagged_by_threshold": flagged,
            "tags_has_spoiler": tags_has_spoiler,
        }
    return expected


def safe_load_csv(path: Path) -> Optional[Dict[str, object]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = []
            for row in reader:
                rows.append(row)
            return {"header": header, "rows": rows}
    except Exception:
        return None


def parse_bool_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    sl = s.strip().lower()
    if sl == "true":
        return True
    if sl == "false":
        return False
    return None


def extract_section(md_text: str, section_name: str) -> str:
    lines = md_text.splitlines()
    start_idx = None
    # Match either "# Section" or plain "Section" line
    for i, line in enumerate(lines):
        if re.match(rf"^\s*#\s*{re.escape(section_name)}\s*$", line, flags=re.IGNORECASE) or re.match(
            rf"^\s*{re.escape(section_name)}\s*$", line, flags=re.IGNORECASE
        ):
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    # End at next top-level section (plain name or '#')
    end_idx = len(lines)
    section_names = ["Purpose", "Scope", "Acceptance Criteria", "Test Cases", "Notes"]
    for j in range(start_idx, len(lines)):
        if re.match(r"^\s*#\s+", lines[j]):  # next markdown header
            end_idx = j
            break
        for name in section_names:
            if re.match(rf"^\s*{re.escape(name)}\s*$", lines[j], flags=re.IGNORECASE):
                end_idx = j
                break
        if end_idx != len(lines) and end_idx <= j:
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def find_test_case_blocks(md_text: str, tc_ids: List[str]) -> Dict[str, str]:
    """
    Find blocks in the Test Cases section only. A block starts with a line that begins with TC-xx.
    """
    section = extract_section(md_text, "Test Cases")
    if not section:
        return {}
    lines = section.splitlines()
    indices: List[Tuple[int, str]] = []
    for idx, line in enumerate(lines):
        m = re.match(r"^\s*(TC-\d{2})\b", line)
        if m:
            tc = m.group(1)
            if tc in tc_ids:
                indices.append((idx, tc))
    indices.sort()
    blocks: Dict[str, str] = {}
    for i, (start_idx, tc) in enumerate(indices):
        end_idx = len(lines)
        if i + 1 < len(indices):
            end_idx = indices[i + 1][0]
        block = "\n".join(lines[start_idx:end_idx]).strip()
        blocks[tc] = block
    return blocks


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "csv_exists_and_header": 0.0,
        "csv_row_count_matches_input": 0.0,
        "csv_keyword_hits_correct": 0.0,
        "csv_matched_keywords_correct": 0.0,
        "csv_flagged_threshold_correct": 0.0,
        "csv_tags_has_spoiler_correct": 0.0,
        "testplan_updated_acceptance_criteria_present": 0.0,
        "testplan_no_todo_placeholders": 0.0,
        "testplan_three_test_cases_present": 0.0,
        "testplan_cases_ids_titles_correct": 0.0,
        "testplan_cases_consistent_with_csv": 0.0,
        "report_exists": 0.0,
        "report_threshold_and_counts_correct": 0.0,
        "report_mismatch_list_correct": 0.0,
    }

    movies_path = workspace / "input" / "movies.jsonl"
    keywords_path = workspace / "input" / "spoiler_keywords.txt"
    csv_path = workspace / "output" / "spoiler_scan.csv"
    testplan_path = workspace / "docs" / "TESTPLAN.md"
    report_path = workspace / "reports" / "validation_summary.md"

    movies = safe_load_jsonl(movies_path)
    keywords = safe_load_keywords(keywords_path)

    expected_map = None
    if movies is not None and keywords is not None:
        expected_map = compute_expected_scan(movies, keywords)

    # CSV checks
    csv_data = safe_load_csv(csv_path)
    if csv_data is not None:
        header = csv_data["header"]
        rows = csv_data["rows"]
        expected_header = ["movie_id", "title", "keyword_hits", "matched_keywords", "flagged_by_threshold", "tags_has_spoiler"]
        scores["csv_exists_and_header"] = 1.0 if header == expected_header else 0.0

        if expected_map is not None:
            # row count and IDs
            if len(rows) == len(expected_map):
                csv_ids = {r.get("movie_id", "").strip() for r in rows}
                scores["csv_row_count_matches_input"] = 1.0 if set(expected_map.keys()) == csv_ids else 0.0
            else:
                scores["csv_row_count_matches_input"] = 0.0

            csv_map = {}
            for r in rows:
                mid = (r.get("movie_id") or "").strip()
                if mid:
                    csv_map[mid] = r

            kh_ok = True
            mk_ok = True
            ft_ok = True
            tag_ok = True
            for mid, exp in expected_map.items():
                r = csv_map.get(mid)
                if not r:
                    kh_ok = False
                    mk_ok = False
                    ft_ok = False
                    tag_ok = False
                    continue
                try:
                    kh_val = int((r.get("keyword_hits") or "").strip())
                except Exception:
                    kh_val = None
                if kh_val is None or kh_val != exp["keyword_hits"]:
                    kh_ok = False
                mk_val = (r.get("matched_keywords") or "").strip()
                if mk_val != exp["matched_keywords"]:
                    mk_ok = False
                fb_val = parse_bool_str(r.get("flagged_by_threshold"))
                if fb_val is None or fb_val != exp["flagged_by_threshold"]:
                    ft_ok = False
                ts_val = parse_bool_str(r.get("tags_has_spoiler"))
                if ts_val is None or ts_val != exp["tags_has_spoiler"]:
                    tag_ok = False
                title_val = (r.get("title") or "").strip()
                if title_val != exp["title"]:
                    mk_ok = False
            scores["csv_keyword_hits_correct"] = 1.0 if kh_ok else 0.0
            scores["csv_matched_keywords_correct"] = 1.0 if mk_ok else 0.0
            scores["csv_flagged_threshold_correct"] = 1.0 if ft_ok else 0.0
            scores["csv_tags_has_spoiler_correct"] = 1.0 if tag_ok else 0.0
        else:
            scores["csv_row_count_matches_input"] = 0.0
            scores["csv_keyword_hits_correct"] = 0.0
            scores["csv_matched_keywords_correct"] = 0.0
            scores["csv_flagged_threshold_correct"] = 0.0
            scores["csv_tags_has_spoiler_correct"] = 0.0
    else:
        scores["csv_exists_and_header"] = 0.0
        scores["csv_row_count_matches_input"] = 0.0
        scores["csv_keyword_hits_correct"] = 0.0
        scores["csv_matched_keywords_correct"] = 0.0
        scores["csv_flagged_threshold_correct"] = 0.0
        scores["csv_tags_has_spoiler_correct"] = 0.0

    # Test plan checks
    md_text = read_text(testplan_path)
    if md_text is not None:
        acc_text = extract_section(md_text, "Acceptance Criteria")
        acc_ok = False
        if acc_text:
            contains_keywords_file = "input/spoiler_keywords.txt" in acc_text
            contains_synopsis = re.search(r"\bsynopsis\b", acc_text, flags=re.IGNORECASE) is not None
            contains_review = re.search(r"\breview\b", acc_text, flags=re.IGNORECASE) is not None
            threshold_ok = (
                re.search(r">=\s*2", acc_text) is not None
                or re.search(r"\bat least\s+2\b", acc_text, flags=re.IGNORECASE) is not None
                or re.search(r"\bgreater than or equal to\s+2\b", acc_text, flags=re.IGNORECASE) is not None
            )
            acc_ok = contains_keywords_file and contains_synopsis and contains_review and threshold_ok
        scores["testplan_updated_acceptance_criteria_present"] = 1.0 if acc_ok else 0.0

        no_todo = "TODO:" not in md_text
        scores["testplan_no_todo_placeholders"] = 1.0 if no_todo else 0.0

        tc_ids = ["TC-01", "TC-02", "TC-03"]
        blocks = find_test_case_blocks(md_text, tc_ids)

        # Determine presence by verifying exactly 3 valid blocks each with required fields
        def block_has_required_fields(text: str) -> bool:
            has_id = re.search(r"\bTC-\d{2}\b", text) is not None
            has_movie_id = re.search(r"movie_id\s*[:\-]\s*[A-Za-z0-9]+", text, flags=re.IGNORECASE) is not None
            has_title = re.search(r"title\s*[:\-]\s*.+", text, flags=re.IGNORECASE) is not None
            has_hits = re.search(r"expected_keyword_hits\s*[:\-]\s*\d+", text, flags=re.IGNORECASE) is not None
            has_flag = re.search(r"expected_flagged_by_threshold\s*[:\-]\s*(true|false)", text, flags=re.IGNORECASE) is not None
            has_rationale = re.search(r"rationale", text, flags=re.IGNORECASE) is not None
            return all([has_id, has_movie_id, has_title, has_hits, has_flag, has_rationale])

        valid_blocks = {k: v for k, v in blocks.items() if block_has_required_fields(v)}
        scores["testplan_three_test_cases_present"] = 1.0 if set(valid_blocks.keys()) == set(tc_ids) and len(valid_blocks) == 3 else 0.0

        # IDs and titles check
        ids_titles_ok = True
        expected_cases = {
            "TC-01": {"movie_id": "M001", "title": "Silent Shores"},
            "TC-02": {"movie_id": "M002", "title": "Clockwork Garden"},
            "TC-03": {"movie_id": "M005", "title": "Last Light"},
        }
        for tc in tc_ids:
            block = blocks.get(tc, "")
            exp = expected_cases.get(tc, {})
            m_id_match = re.search(r"movie_id\s*[:\-]\s*([A-Za-z0-9]+)", block, flags=re.IGNORECASE)
            m_title_match = re.search(r"title\s*[:\-]\s*(.+)", block, flags=re.IGNORECASE)
            if not m_id_match or not m_title_match:
                ids_titles_ok = False
                continue
            found_id = m_id_match.group(1).strip()
            found_title = m_title_match.group(1).splitlines()[0].strip()
            if exp:
                if found_id != exp["movie_id"] or found_title != exp["title"]:
                    ids_titles_ok = False
        scores["testplan_cases_ids_titles_correct"] = 1.0 if ids_titles_ok and scores["testplan_three_test_cases_present"] == 1.0 else 0.0

        # Consistency with CSV
        consistent_ok = False
        if csv_data is not None and scores["testplan_three_test_cases_present"] == 1.0:
            consistent_ok = True
            csv_rows_by_id = {}
            for r in csv_data["rows"]:
                mid = (r.get("movie_id") or "").strip()
                if mid:
                    csv_rows_by_id[mid] = r
            for tc in tc_ids:
                block = blocks.get(tc, "")
                m_id_match = re.search(r"movie_id\s*[:\-]\s*([A-Za-z0-9]+)", block, flags=re.IGNORECASE)
                ek_match = re.search(r"expected_keyword_hits\s*[:\-]\s*(\d+)", block, flags=re.IGNORECASE)
                ef_match = re.search(r"expected_flagged_by_threshold\s*[:\-]\s*(true|false)", block, flags=re.IGNORECASE)
                rationale_has_keywords = bool(re.search(r"rationale", block, flags=re.IGNORECASE)) and (
                    any(kw in block.lower() for kw in ["dies", "killer is", "true identity", "twist", "ending"])
                )
                if not (m_id_match and ek_match and ef_match and rationale_has_keywords):
                    consistent_ok = False
                    continue
                found_id = m_id_match.group(1).strip()
                ek_val = int(ek_match.group(1))
                ef_val = True if ef_match.group(1).lower() == "true" else False
                csv_row = csv_rows_by_id.get(found_id)
                if not csv_row:
                    consistent_ok = False
                else:
                    try:
                        csv_kh = int((csv_row.get("keyword_hits") or "").strip())
                    except Exception:
                        csv_kh = None
                    csv_fb = parse_bool_str(csv_row.get("flagged_by_threshold"))
                    if csv_kh is None or csv_fb is None:
                        consistent_ok = False
                    else:
                        if ek_val != csv_kh or ef_val != csv_fb:
                            consistent_ok = False
        scores["testplan_cases_consistent_with_csv"] = 1.0 if consistent_ok else 0.0
    else:
        scores["testplan_updated_acceptance_criteria_present"] = 0.0
        scores["testplan_no_todo_placeholders"] = 0.0
        scores["testplan_three_test_cases_present"] = 0.0
        scores["testplan_cases_ids_titles_correct"] = 0.0
        scores["testplan_cases_consistent_with_csv"] = 0.0

    # Report checks
    report_text = read_text(report_path)
    if report_text is not None:
        scores["report_exists"] = 1.0
        threshold_ok = (
            re.search(r">=\s*2", report_text) is not None
            or re.search(r"\bat least\s+2\b", report_text, flags=re.IGNORECASE) is not None
            or re.search(r"\bgreater than or equal to\s+2\b", report_text, flags=re.IGNORECASE) is not None
        )
        counts_ok = False
        mismatch_list_ok = False

        total_count = None
        flagged_true = None
        tag_true = None
        mismatches = []
        csv_rows = csv_data["rows"] if csv_data is not None else None
        if csv_rows is not None:
            total_count = len(csv_rows)
            flagged_true = 0
            tag_true = 0
            for r in csv_rows:
                fb = parse_bool_str(r.get("flagged_by_threshold"))
                ts = parse_bool_str(r.get("tags_has_spoiler"))
                if fb is True:
                    flagged_true += 1
                if ts is True:
                    tag_true += 1
            for r in csv_rows:
                fb = parse_bool_str(r.get("flagged_by_threshold"))
                ts = parse_bool_str(r.get("tags_has_spoiler"))
                if fb is None or ts is None:
                    continue
                if fb != ts:
                    title = (r.get("title") or "").strip()
                    kh = (r.get("keyword_hits") or "").strip()
                    mk = (r.get("matched_keywords") or "").strip()
                    ts_str = "true" if ts else "false"
                    mismatches.append({
                        "title": title,
                        "keyword_hits": kh,
                        "matched_keywords": mk,
                        "tags_has_spoiler": ts_str,
                    })
        elif expected_map is not None:
            total_count = len(expected_map)
            flagged_true = sum(1 for v in expected_map.values() if v["flagged_by_threshold"])
            tag_true = sum(1 for v in expected_map.values() if v["tags_has_spoiler"])
            for v in expected_map.values():
                if v["flagged_by_threshold"] != v["tags_has_spoiler"]:
                    mismatches.append({
                        "title": v["title"],
                        "keyword_hits": str(v["keyword_hits"]),
                        "matched_keywords": v["matched_keywords"],
                        "tags_has_spoiler": "true" if v["tags_has_spoiler"] else "false",
                    })

        if total_count is not None and flagged_true is not None and tag_true is not None:
            # Require explicit labels or at least the exact numbers present
            has_threshold = threshold_ok
            has_total = re.search(rf"\b{total_count}\b", report_text) is not None
            has_flagged = re.search(rf"\b{flagged_true}\b", report_text) is not None
            has_tagtrue = re.search(rf"\b{tag_true}\b", report_text) is not None
            counts_ok = has_threshold and has_total and has_flagged and has_tagtrue

        bullet_lines = [ln.strip() for ln in report_text.splitlines() if re.match(r"^\s*[-*]\s+", ln)]
        if mismatches is not None:
            used_idx = set()
            for mm in mismatches:
                found = False
                for bi, bl in enumerate(bullet_lines):
                    if bi in used_idx:
                        continue
                    # Must contain title, keyword_hits, matched_keywords (if non-empty), and tags_has_spoiler boolean
                    if mm["title"] not in bl:
                        continue
                    if re.search(rf"\b{re.escape(mm['keyword_hits'])}\b", bl) is None:
                        continue
                    if mm["matched_keywords"]:
                        if mm["matched_keywords"] not in bl:
                            continue
                    if re.search(r"tags_has_spoiler", bl, flags=re.IGNORECASE) is None:
                        continue
                    if re.search(rf"\b{mm['tags_has_spoiler']}\b", bl, flags=re.IGNORECASE) is None:
                        continue
                    used_idx.add(bi)
                    found = True
                    break
                if not found:
                    break
            mismatch_list_ok = (len(used_idx) == len(mismatches))
        scores["report_threshold_and_counts_correct"] = 1.0 if counts_ok else 0.0
        scores["report_mismatch_list_correct"] = 1.0 if mismatch_list_ok else 0.0
    else:
        scores["report_exists"] = 0.0
        scores["report_threshold_and_counts_correct"] = 0.0
        scores["report_mismatch_list_correct"] = 0.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()