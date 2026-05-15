import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


ORIGINAL_COLUMNS = [
    "post_id",
    "language",
    "match_id",
    "opponent",
    "date",
    "text",
    "likes",
    "shares",
    "comments",
]

TOP_COLUMNS_ORDER = [
    "rank",
    "post_id",
    "language",
    "opponent",
    "date",
    "text_en",
    "engagement_score",
]


def _read_csv_utf8(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(row) for row in reader]
            return headers, rows
    except Exception:
        return None, None


def _read_text_utf8(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _contains_hangul(s: str) -> bool:
    for ch in s:
        code = ord(ch)
        if (0xAC00 <= code <= 0xD7A3) or (0x1100 <= code <= 0x11FF) or (0x3130 <= code <= 0x318F):
            return True
    return False


def _has_ascii_letters(s: str) -> bool:
    return any(ch.isalpha() and ord(ch) < 128 for ch in s)


def _parse_int(val: str) -> Optional[int]:
    try:
        return int(str(val).strip())
    except Exception:
        return None


def _extract_numbers(text: str) -> List[float]:
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
    out: List[float] = []
    for n in nums:
        try:
            out.append(float(n))
        except Exception:
            pass
    return out


def _sentence_count(text: str) -> int:
    # Count sentence-ending punctuation (., !, ?). Merge ellipses into one.
    t = re.sub(r"\.\.+", ".", text)
    parts = re.split(r"[.!?]+", t)
    # Count non-empty segments that have at least one alphanumeric
    count = 0
    for p in parts:
        if re.search(r"[A-Za-z0-9\uAC00-\uD7A3]", p):
            count += 1
    return max(0, count)


def _compute_engagement(row: Dict[str, str]) -> Optional[int]:
    likes = _parse_int(row.get("likes", ""))
    shares = _parse_int(row.get("shares", ""))
    comments = _parse_int(row.get("comments", ""))
    if likes is None or shares is None or comments is None:
        return None
    return likes + 2 * shares + comments


def _sort_key_for_top(row: Dict[str, str]) -> Tuple[int, int, int]:
    eng = _parse_int(row.get("engagement_score", ""))
    shares = _parse_int(row.get("shares", ""))
    likes = _parse_int(row.get("likes", ""))
    # Use very small values if parsing fails to avoid crashing; but correctness checks will fail elsewhere
    if eng is None:
        eng = -10**12
    if shares is None:
        shares = -10**12
    if likes is None:
        likes = -10**12
    # For descending sort, we return tuple to sort reverse later or use negatives.
    return (eng, shares, likes)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "normalized_exists_utf8": 0.0,
        "normalized_includes_original_columns": 0.0,
        "normalized_has_added_columns": 0.0,
        "normalized_row_count_match": 0.0,
        "engagement_score_correctness": 0.0,
        "text_en_translation_checks": 0.0,
        "top_posts_file_structure": 0.0,
        "top_posts_ranking_correctness": 0.0,
        "report_overview_bilingual_structure": 0.0,
        "report_highlights_by_opponent": 0.0,
        "report_top_chants_korean": 0.0,
        "fan_club_announcement_ko": 0.0,
        "outreach_email_bilingual": 0.0,
        "error_analysis_covers_failure_and_fixes": 0.0,
    }

    # Load inputs and outputs
    data_csv = workspace / "data" / "social_posts.csv"
    norm_csv = workspace / "processed" / "normalized_posts.csv"
    top_csv = workspace / "outputs" / "top_posts_ranked.csv"
    report_md = workspace / "reports" / "weekly_bilingual_report.md"
    fan_msg = workspace / "messages" / "fan_club_announcement_ko.txt"
    outreach_msg = workspace / "messages" / "outreach_email_bilingual.txt"
    error_log = workspace / "logs" / "format_posts_error.txt"
    script_py = workspace / "scripts" / "format_posts.py"
    diagnostics_md = workspace / "diagnostics" / "error_analysis.md"

    # Load original data
    orig_headers, orig_rows = _read_csv_utf8(data_csv)

    # Load normalized posts
    norm_headers, norm_rows = _read_csv_utf8(norm_csv)
    if norm_headers is not None and norm_rows is not None:
        scores["normalized_exists_utf8"] = 1.0

    # Check columns and row counts
    if norm_headers is not None and norm_rows is not None:
        # original columns present
        if all(col in norm_headers for col in ORIGINAL_COLUMNS):
            scores["normalized_includes_original_columns"] = 1.0
        # added columns
        if "engagement_score" in norm_headers and "text_en" in norm_headers:
            scores["normalized_has_added_columns"] = 1.0
        # row count matches original
        if orig_rows is not None:
            if len(norm_rows) == len(orig_rows):
                scores["normalized_row_count_match"] = 1.0

    # Engagement score correctness
    eng_ok = True
    if norm_rows is None or norm_headers is None:
        eng_ok = False
    else:
        for row in norm_rows:
            comp = _compute_engagement(row)
            eng = _parse_int(row.get("engagement_score", ""))
            if comp is None or eng is None or comp != eng:
                eng_ok = False
                break
    scores["engagement_score_correctness"] = 1.0 if eng_ok else 0.0

    # text_en translation checks
    trans_ok = True
    if norm_rows is None or norm_headers is None:
        trans_ok = False
    else:
        for row in norm_rows:
            lang = (row.get("language") or "").strip().lower()
            orig_text = row.get("text") or ""
            text_en = row.get("text_en") or ""
            if lang == "en":
                # Must be copied as-is
                if orig_text.strip() != text_en.strip():
                    trans_ok = False
                    break
            elif lang == "ko":
                # Must be translated to English: non-empty, different from original, has ascii letters, and no Hangul
                if not text_en.strip():
                    trans_ok = False
                    break
                if text_en.strip() == orig_text.strip():
                    trans_ok = False
                    break
                if _contains_hangul(text_en):
                    trans_ok = False
                    break
                if not _has_ascii_letters(text_en):
                    trans_ok = False
                    break
            else:
                # Unknown language; require non-empty text_en
                if not text_en.strip():
                    trans_ok = False
                    break
    scores["text_en_translation_checks"] = 1.0 if trans_ok else 0.0

    # Top posts ranked file structure
    top_headers, top_rows = _read_csv_utf8(top_csv)
    structure_ok = False
    if top_headers is not None and top_rows is not None:
        if top_headers == TOP_COLUMNS_ORDER and len(top_rows) == 5:
            # ranks should be 1..5
            ranks_seq_ok = True
            for idx, row in enumerate(top_rows, start=1):
                r = _parse_int(row.get("rank", ""))
                if r != idx:
                    ranks_seq_ok = False
                    break
            if ranks_seq_ok:
                structure_ok = True
    scores["top_posts_file_structure"] = 1.0 if structure_ok else 0.0

    # Top posts ranking correctness (requires normalized file)
    ranking_ok = False
    if norm_rows is not None and top_rows is not None and structure_ok:
        # Build mapping by post_id for normalized rows
        norm_by_id: Dict[str, Dict[str, str]] = {}
        for r in norm_rows:
            pid = str(r.get("post_id", "")).strip()
            if pid:
                norm_by_id[pid] = r

        # Compute expected top 5 by engagement_score desc, tie-break by shares then likes
        rows_with_scores = []
        for r in norm_rows:
            eng = _parse_int(r.get("engagement_score", ""))
            sh = _parse_int(r.get("shares", ""))
            lk = _parse_int(r.get("likes", ""))
            pid = str(r.get("post_id", "")).strip()
            if eng is None or sh is None or lk is None or not pid:
                # Malformed data: cannot validate
                rows_with_scores = []
                break
            rows_with_scores.append((eng, sh, lk, pid))
        if rows_with_scores:
            rows_with_scores.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
            expected_top_ids = [pid for _, _, _, pid in rows_with_scores[:5]]

            # Validate top_rows content
            consistent = True
            for idx, row in enumerate(top_rows):
                expected_pid = expected_top_ids[idx]
                row_pid = str(row.get("post_id", "")).strip()
                if row_pid != expected_pid:
                    consistent = False
                    break
                # Check fields match normalized for the selected post
                nrow = norm_by_id.get(expected_pid)
                if not nrow:
                    consistent = False
                    break
                # engagement_score equality
                tr_eng = _parse_int(row.get("engagement_score", ""))
                nr_eng = _parse_int(nrow.get("engagement_score", ""))
                if tr_eng is None or nr_eng is None or tr_eng != nr_eng:
                    consistent = False
                    break
                # language/opponent/date/text_en equality
                for fld in ["language", "opponent", "date", "text_en"]:
                    if (row.get(fld) or "").strip() != (nrow.get(fld) or "").strip():
                        consistent = False
                        break
                if not consistent:
                    break
                # Ensure rows are in descending engagement order as well
                if idx > 0:
                    prev_eng = _parse_int(top_rows[idx - 1].get("engagement_score", ""))
                    curr_eng = tr_eng
                    if prev_eng is None or curr_eng is None or prev_eng < curr_eng:
                        consistent = False
                        break
            ranking_ok = consistent
    scores["top_posts_ranking_correctness"] = 1.0 if ranking_ok else 0.0

    # Report checks
    report_text = _read_text_utf8(report_md)
    overview_ok = False
    highlights_ok = False
    chants_ok = False

    if report_text is not None and norm_rows is not None:
        lines = [ln.rstrip("\n") for ln in report_text.splitlines()]
        # Overview: find heading line that contains "Overview"
        overview_idx = -1
        for i, ln in enumerate(lines):
            if "overview" in ln.lower():
                overview_idx = i
                break
        if overview_idx != -1:
            # find next two non-empty lines
            subsequent = [ln for ln in lines[overview_idx + 1:] if ln.strip() != ""]
            if len(subsequent) >= 2:
                en_line = subsequent[0]
                ko_line = subsequent[1]
                en_sent_ok = (not _contains_hangul(en_line)) and _has_ascii_letters(en_line) and (2 <= _sentence_count(en_line) <= 3)
                ko_sent_ok = _contains_hangul(ko_line) and (2 <= _sentence_count(ko_line) <= 3)
                overview_ok = en_sent_ok and ko_sent_ok

        # Highlights by opponent present in data: compute counts and averages from normalized
        opp_counts: Dict[str, int] = {}
        opp_sums: Dict[str, int] = {}
        for r in norm_rows:
            opp = (r.get("opponent") or "").strip()
            eng = _parse_int(r.get("engagement_score", ""))
            if not opp or eng is None:
                continue
            opp_counts[opp] = opp_counts.get(opp, 0) + 1
            opp_sums[opp] = opp_sums.get(opp, 0) + eng
        opp_avgs: Dict[str, float] = {opp: (opp_sums[opp] / opp_counts[opp]) for opp in opp_counts.keys() if opp_counts[opp] > 0}

        # Find bullet lines
        bullet_lines = [ln for ln in lines if re.match(r"^\s*[-*]\s", ln)]
        per_opp_ok = True
        for opp, cnt in opp_counts.items():
            avg = opp_avgs.get(opp)
            # Find matching bullet
            found = False
            for bl in bullet_lines:
                if opp in bl:
                    # bilingual one line: has Hangul and ASCII letters
                    if not (_contains_hangul(bl) and _has_ascii_letters(bl)):
                        continue
                    nums = _extract_numbers(bl)
                    has_count = any(abs(num - cnt) < 1e-9 for num in nums)
                    has_avg_close = any(abs(num - avg) <= 0.5 and abs(num - cnt) > 1e-9 for num in nums) if avg is not None else False
                    if has_count and has_avg_close:
                        found = True
                        break
            if not found:
                per_opp_ok = False
                break
        highlights_ok = per_opp_ok

        # Top Chants (Korean) includes "대~한민국!" or "대한민국"
        chants_ok = ("대~한민국" in report_text) or ("대한민국" in report_text)

    scores["report_overview_bilingual_structure"] = 1.0 if overview_ok else 0.0
    scores["report_highlights_by_opponent"] = 1.0 if highlights_ok else 0.0
    scores["report_top_chants_korean"] = 1.0 if chants_ok else 0.0

    # Fan club announcement (Korean)
    fan_text = _read_text_utf8(fan_msg)
    fan_ok = False
    if fan_text is not None and norm_rows is not None:
        # Build set of opponent names from expected top 5
        # Compute expected top 5 again using normalized
        rows_with_scores = []
        for r in norm_rows:
            eng = _parse_int(r.get("engagement_score", ""))
            sh = _parse_int(r.get("shares", ""))
            lk = _parse_int(r.get("likes", ""))
            pid = str(r.get("post_id", "")).strip()
            if eng is None or sh is None or lk is None or not pid:
                rows_with_scores = []
                break
            rows_with_scores.append((eng, sh, lk, pid, r))
        if rows_with_scores:
            rows_with_scores.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
            top5 = [r for _, _, _, _, r in rows_with_scores[:5]]
            top_opponents = { (tr.get("opponent") or "").strip() for tr in top5 if (tr.get("opponent") or "").strip() }
        else:
            top_opponents = set()

        has_korean = _contains_hangul(fan_text)
        has_chant = ("대~한민국" in fan_text)
        references_top = any(opp in fan_text for opp in top_opponents) if top_opponents else False
        fan_ok = has_korean and has_chant and references_top
    scores["fan_club_announcement_ko"] = 1.0 if fan_ok else 0.0

    # Outreach email bilingual
    outreach_text = _read_text_utf8(outreach_msg)
    outreach_ok = False
    if outreach_text is not None and norm_rows is not None:
        lines = [ln.rstrip("\n") for ln in outreach_text.splitlines()]
        subject_lines = [ln for ln in lines if ln.strip().lower().startswith("subject")]
        has_two_subjects = len(subject_lines) >= 2
        subj_has_ko = any(_contains_hangul(ln) for ln in subject_lines)
        subj_has_en = any(_has_ascii_letters(ln) and not _contains_hangul(ln) for ln in subject_lines)

        # paragraphs after subjects
        # Identify paragraphs: split by blank lines
        body_lines = lines
        # find index after last subject line
        last_subj_idx = -1
        for i, ln in enumerate(lines):
            if ln.strip().lower().startswith("subject"):
                last_subj_idx = i
        if last_subj_idx >= 0:
            body_lines = lines[last_subj_idx + 1:]
        # collect paragraphs
        paras: List[str] = []
        current: List[str] = []
        for ln in body_lines:
            if ln.strip() == "":
                if current:
                    paras.append("\n".join(current).strip())
                    current = []
            else:
                current.append(ln)
        if current:
            paras.append("\n".join(current).strip())
        has_two_paras = len(paras) >= 2
        en_para_ok = False
        ko_para_ok = False
        if has_two_paras:
            en_para = paras[0]
            ko_para = paras[1]
            en_para_ok = _has_ascii_letters(en_para) and not _contains_hangul(en_para)
            ko_para_ok = _contains_hangul(ko_para)

        # include one concrete data point from top 5 (opponent name or engagement score number)
        # Compute expected top5 again
        rows_with_scores2 = []
        for r in norm_rows:
            eng = _parse_int(r.get("engagement_score", ""))
            sh = _parse_int(r.get("shares", ""))
            lk = _parse_int(r.get("likes", ""))
            pid = str(r.get("post_id", "")).strip()
            if eng is None or sh is None or lk is None or not pid:
                rows_with_scores2 = []
                break
            rows_with_scores2.append((eng, sh, lk, pid, r))
        includes_datapoint = False
        if rows_with_scores2:
            rows_with_scores2.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
            top5 = [r for _, _, _, _, r in rows_with_scores2[:5]]
            top_opponents = { (tr.get("opponent") or "").strip() for tr in top5 if (tr.get("opponent") or "").strip() }
            top_eng_scores = { str(_parse_int(tr.get("engagement_score", "") or "")) for tr in top5 if tr.get("engagement_score") is not None }
            # Check if any opponent or engagement score number appears in the whole text
            text_all = outreach_text
            includes_datapoint = any(opp and opp in text_all for opp in top_opponents) or any(num and num in text_all for num in top_eng_scores)

        outreach_ok = has_two_subjects and subj_has_ko and subj_has_en and has_two_paras and en_para_ok and ko_para_ok and includes_datapoint
    scores["outreach_email_bilingual"] = 1.0 if outreach_ok else 0.0

    # Error analysis diagnostics
    diag_text = _read_text_utf8(diagnostics_md)
    error_log_text = _read_text_utf8(error_log)
    script_text = _read_text_utf8(script_py)
    error_ok = False
    if diag_text is not None:
        # Must quote the exact error line naming missing column
        has_keyerror_line = "KeyError: 'engagement_score'" in diag_text
        # Fix (a): mention processed/normalized_posts.csv and rerun
        mentions_processed = "processed/normalized_posts.csv" in diag_text
        # Accept language about re-running; be flexible: look for "re-run", "re run", or "run the script again"
        mentions_rerun = any(sub in diag_text.lower() for sub in ["re-run", "re run", "run the script again", "re-running", "rerun"])
        fix_a_ok = mentions_processed and has_keyerror_line

        # Fix (b): modify script to compute engagement_score from likes, shares, comments
        mentions_compute = ("compute" in diag_text.lower() or "calculate" in diag_text.lower()) and "engagement_score" in diag_text
        mentions_fields = all(x in diag_text for x in ["likes", "shares", "comments"])
        fix_b_ok = mentions_compute and mentions_fields

        # Include corrected example command using processed file and unmodified script
        # Look for a line with python scripts/format_posts.py processed/normalized_posts.csv <some_output.csv>
        command_ok = False
        for ln in diag_text.splitlines():
            if "python" in ln and "scripts/format_posts.py" in ln and "processed/normalized_posts.csv" in ln and ".csv" in ln:
                # ensure there are at least 3 tokens (python, script, input, output)
                toks = ln.strip().split()
                if len(toks) >= 4:
                    command_ok = True
                    break

        error_ok = has_keyerror_line and fix_a_ok and fix_b_ok and command_ok
    scores["error_analysis_covers_failure_and_fixes"] = 1.0 if error_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()