import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _tokenize(text: str) -> List[str]:
    # Lowercase, split on non-letters, keep [a-z]+ tokens only
    text = text.lower()
    tokens = re.findall(r"[a-z]+", text)
    return tokens


def _parse_semicolon_set(value: str) -> List[str]:
    if value is None:
        return []
    parts = [p.strip() for p in value.split(";")]
    return [p for p in parts if p != ""]


def _try_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _parse_date_ymd(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _float_safe(s: str) -> Optional[float]:
    try:
        return float(str(s).strip())
    except Exception:
        return None


def _compute_expected(workspace: Path) -> Optional[Dict]:
    input_csv = workspace / "input/submissions.csv"
    rows = _load_csv_dicts(input_csv)
    if rows is None:
        return None

    # Filter criteria
    tags_set = {
        "Indigenous", "Black", "Latinx", "AAPI", "Disabled",
        "LGBTQ+", "Refugee", "First-Gen", "Rural"
    }
    fresh_genres = {
        "speculative", "afrofuturism", "cli-fi", "hybrid",
        "experimental", "verse novel", "magical realism"
    }
    thematic_keywords = {"climate", "migration", "identity", "memory"}

    total_processed = len(rows)

    # Prepare per-row enriched data
    enriched = []
    for r in rows:
        # Basic fields
        submission_id = r.get("submission_id", "").strip()
        author_name = r.get("author_name", "").strip()
        author_identity_tags = r.get("author_identity_tags", "")
        genre = r.get("genre", "").strip()
        prior_publications_count = _try_int(r.get("prior_publications_count", ""))
        theme_keywords = r.get("theme_keywords", "")
        sample_path_rel = r.get("sample_path", "")
        submission_date_str = r.get("submission_date", "")

        if prior_publications_count is None:
            # Malformed numeric field; skip this row in expected
            continue

        # Filter checks
        # 1) underrepresented tags
        tags = _parse_semicolon_set(author_identity_tags)
        has_underrep = any(t in tags_set for t in tags)
        # 2) publication history
        pub_ok = prior_publications_count <= 1
        # 3) fresh genre
        genre_ok = genre in fresh_genres
        # 4) thematic alignment (semicolons; case-insensitive exact keyword match)
        themes = [t.strip().lower() for t in _parse_semicolon_set(theme_keywords)]
        theme_ok = any(t in thematic_keywords for t in themes)

        passes_filter = has_underrep and pub_ok and genre_ok and theme_ok

        # Metrics from sample
        sample_path = workspace / sample_path_rel
        sample_text = _read_text(sample_path) if passes_filter else None
        if passes_filter and sample_text is None:
            # If we cannot read sample, we cannot compute expected; fail early
            return None

        total_words = None
        unique_words = None
        unique_word_ratio = None
        if passes_filter:
            tokens = _tokenize(sample_text)
            total_words = len(tokens)
            unique_words = len(set(tokens))
            unique_word_ratio = (unique_words / total_words) if total_words > 0 else 0.0

        enriched.append({
            "row": r,
            "passes_filter": passes_filter,
            "submission_id": submission_id,
            "author_name": author_name,
            "author_identity_tags": author_identity_tags,
            "genre": genre,
            "prior_publications_count": prior_publications_count,
            "theme_keywords": theme_keywords,
            "sample_path_rel": sample_path_rel,
            "submission_date_str": submission_date_str,
            "submission_date": _parse_date_ymd(submission_date_str),
            "sample_text": sample_text,
            "total_words": total_words,
            "unique_words": unique_words,
            "unique_word_ratio": unique_word_ratio,
        })

    filtered = [e for e in enriched if e["passes_filter"]]

    # If any date parsing failed for filtered items, treat as invalid expected
    for e in filtered:
        if e["submission_date"] is None:
            return None

    # Ranking rules:
    # - unique_word_ratio desc
    # - submission_date desc
    # - prior_publications_count asc
    # - submission_id asc
    def sort_key(e):
        ratio = e["unique_word_ratio"]
        date_ord = e["submission_date"].toordinal()
        pubs = e["prior_publications_count"]
        sid = e["submission_id"]
        return (-ratio, -date_ord, pubs, sid)

    filtered_sorted = sorted(filtered, key=sort_key)
    top_k = filtered_sorted[:5]

    expected_ids = [e["submission_id"] for e in top_k]
    # Build expected metrics mapping
    metrics_by_id = {}
    for e in top_k:
        metrics_by_id[e["submission_id"]] = {
            "total_words": e["total_words"],
            "unique_words": e["unique_words"],
            "unique_word_ratio": e["unique_word_ratio"],
            "author_name": e["author_name"],
            "author_identity_tags": e["author_identity_tags"],
            "genre": e["genre"],
            "prior_publications_count": e["prior_publications_count"],
            "theme_keywords": e["theme_keywords"],
            "sample_text": e["sample_text"],
        }

    return {
        "total_processed": total_processed,
        "passed_filtering": len(filtered),
        "expected_ids": expected_ids,
        "metrics_by_id": metrics_by_id,
        "sets": {
            "underrep": tags_set,
            "genres": fresh_genres,
            "themes": thematic_keywords,
        },
    }


def _read_report(path: Path) -> Optional[str]:
    return _read_text(path)


def _parse_bulleted_ids_and_ratios(report_text: str) -> List[Tuple[str, Optional[float]]]:
    results = []
    for line in report_text.splitlines():
        if re.match(r"^\s*[-*]\s+", line):
            ids = re.findall(r"\bS\d+\b", line)
            # Find a float in the line (e.g., 0.123, 1.0)
            float_match = re.search(r"([0-9]*\.[0-9]+|[0-9]+)", line)
            ratio = None
            if float_match:
                try:
                    ratio = float(float_match.group(1))
                except Exception:
                    ratio = None
            if ids:
                # if multiple IDs, take the first
                results.append((ids[0], ratio))
    return results


def _round3(x: float) -> float:
    return round(float(x), 3)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "shortlist_csv_exists": 0.0,
        "shortlist_columns_and_order": 0.0,
        "shortlist_row_count_and_ids_order": 0.0,
        "shortlist_metrics_correct": 0.0,
        "snippets_exist_and_correct": 0.0,
        "report_counts_correct": 0.0,
        "report_filter_sets_listed": 0.0,
        "report_bulleted_ranking_with_ratios": 0.0,
        "reproduce_single_line": 0.0,
        "reproduce_mentions_input_file": 0.0,
    }

    expected = _compute_expected(workspace)
    # Paths
    shortlist_path = workspace / "outputs/shortlist.csv"
    report_path = workspace / "outputs/report.md"
    reproduce_path = workspace / "outputs/REPRODUCE.txt"
    snippets_dir = workspace / "outputs/snippets"

    # If expected couldn't be computed (missing/invalid inputs), fail output checks gracefully
    # We can still grade reproduce file presence
    # Grade REPRODUCE.txt
    rep_text = _read_text(reproduce_path)
    if rep_text is not None:
        lines = rep_text.splitlines()
        if len(lines) == 1 and len(lines[0].strip()) > 0:
            scores["reproduce_single_line"] = 1.0
            if "input/submissions.csv" in lines[0]:
                scores["reproduce_mentions_input_file"] = 1.0
        else:
            scores["reproduce_single_line"] = 0.0
            scores["reproduce_mentions_input_file"] = 0.0
    else:
        scores["reproduce_single_line"] = 0.0
        scores["reproduce_mentions_input_file"] = 0.0

    if expected is None:
        # Cannot compute expected; remaining checks remain 0.0
        return scores

    # Load shortlist.csv
    shortlist_rows = None
    if shortlist_path.exists():
        scores["shortlist_csv_exists"] = 1.0
        shortlist_rows = _load_csv_dicts(shortlist_path)
        if shortlist_rows is None:
            shortlist_rows = []
    else:
        scores["shortlist_csv_exists"] = 0.0
        shortlist_rows = []

    # Columns and order check
    required_columns = [
        "submission_id",
        "author_name",
        "author_identity_tags",
        "genre",
        "prior_publications_count",
        "theme_keywords",
        "total_words",
        "unique_words",
        "unique_word_ratio",
    ]
    columns_ok = False
    if shortlist_rows is not None and len(shortlist_rows) >= 0:
        # If there is at least a header (DictReader would have produced dicts)
        # We must validate columns strictly on the first row's keys if any, else try reading header manually
        try:
            with shortlist_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline()
            header = [h.strip() for h in header_line.strip().split(",")] if header_line else []
            if header == required_columns:
                columns_ok = True
        except Exception:
            columns_ok = False
    scores["shortlist_columns_and_order"] = 1.0 if columns_ok else 0.0

    # Row count and IDs order
    expected_ids = expected["expected_ids"]
    expected_count = len(expected_ids)
    got_ids = []
    if shortlist_rows:
        for row in shortlist_rows:
            got_ids.append(str(row.get("submission_id", "")).strip())
    ids_ok = (got_ids == expected_ids)
    count_ok = (len(shortlist_rows) == expected_count)
    scores["shortlist_row_count_and_ids_order"] = 1.0 if (ids_ok and count_ok) else 0.0

    # Metrics correctness
    metrics_ok_total = 0
    metrics_total_needed = max(expected_count, 1)
    if shortlist_rows and ids_ok and count_ok:
        per_row_ok = []
        for row in shortlist_rows:
            sid = str(row.get("submission_id", "")).strip()
            m = expected["metrics_by_id"].get(sid)
            if not m:
                per_row_ok.append(False)
                continue
            # Check author fields
            if str(row.get("author_name", "")).strip() != m["author_name"]:
                per_row_ok.append(False)
                continue
            if str(row.get("author_identity_tags", "")).strip() != m["author_identity_tags"]:
                per_row_ok.append(False)
                continue
            if str(row.get("genre", "")).strip() != m["genre"]:
                per_row_ok.append(False)
                continue
            # prior_publications_count
            row_pub = _try_int(row.get("prior_publications_count", ""))
            if row_pub is None or row_pub != m["prior_publications_count"]:
                per_row_ok.append(False)
                continue
            if str(row.get("theme_keywords", "")).strip() != m["theme_keywords"]:
                per_row_ok.append(False)
                continue
            # total_words, unique_words
            row_tw = _try_int(row.get("total_words", ""))
            row_uw = _try_int(row.get("unique_words", ""))
            if row_tw is None or row_uw is None:
                per_row_ok.append(False)
                continue
            if row_tw != m["total_words"] or row_uw != m["unique_words"]:
                per_row_ok.append(False)
                continue
            # unique_word_ratio rounding tolerance (3 decimals)
            row_uwr = _float_safe(row.get("unique_word_ratio", ""))
            if row_uwr is None:
                per_row_ok.append(False)
                continue
            if _round3(row_uwr) != _round3(m["unique_word_ratio"]):
                per_row_ok.append(False)
                continue
            per_row_ok.append(True)
        metrics_ok_total = sum(1 for x in per_row_ok if x)
        scores["shortlist_metrics_correct"] = metrics_ok_total / float(metrics_total_needed)
    else:
        scores["shortlist_metrics_correct"] = 0.0

    # Snippets exist and correct for expected shortlisted IDs
    snippet_checks = []
    if expected_count > 0:
        for sid in expected_ids:
            m = expected["metrics_by_id"][sid]
            orig_text = m["sample_text"]
            expected_snippet = orig_text[:200]
            snippet_path = snippets_dir / f"{sid}_snippet.txt"
            snip_text = _read_text(snippet_path)
            if snip_text is None:
                snippet_checks.append(False)
                continue
            # Compare exactly
            snippet_checks.append(snip_text == expected_snippet)
    if expected_count > 0:
        scores["snippets_exist_and_correct"] = (sum(1 for b in snippet_checks if b) / float(expected_count)) if snippet_checks else 0.0
    else:
        # If no expected IDs (no one passed), consider this check trivially satisfied
        scores["snippets_exist_and_correct"] = 1.0

    # Report checks
    report_text = _read_report(report_path)
    if report_text is not None:
        # Counts check: total processed and passed filtering
        # Search lines containing labelled numbers
        total_ok = False
        passed_ok = False
        for line in report_text.splitlines():
            l = line.lower()
            if ("total" in l and ("submission" in l or "processed" in l)):
                nums = re.findall(r"\b\d+\b", line)
                if nums:
                    try:
                        val = int(nums[0])
                        if val == expected["total_processed"]:
                            total_ok = True
                    except Exception:
                        pass
            if ("pass" in l or "filter" in l):
                nums = re.findall(r"\b\d+\b", line)
                if nums:
                    try:
                        # choose the first integer on the line
                        val = int(nums[0])
                        if val == expected["passed_filtering"]:
                            passed_ok = True
                    except Exception:
                        pass
        scores["report_counts_correct"] = 1.0 if (total_ok and passed_ok) else 0.0

        # Filter sets listed: each item must appear somewhere in the report
        sets_ok = True
        # Underrepresented tags
        for tag in sorted(expected["sets"]["underrep"]):
            if tag not in report_text:
                sets_ok = False
                break
        # Genres
        if sets_ok:
            for g in sorted(expected["sets"]["genres"]):
                if g not in report_text:
                    sets_ok = False
                    break
        # Themes
        if sets_ok:
            for t in sorted(expected["sets"]["themes"]):
                if t not in report_text:
                    sets_ok = False
                    break
        scores["report_filter_sets_listed"] = 1.0 if sets_ok else 0.0

        # Bulleted ranking with ratios
        bullets = _parse_bulleted_ids_and_ratios(report_text)
        ids_in_bullets = [sid for (sid, _) in bullets]
        ratios_in_bullets = {sid: ratio for (sid, ratio) in bullets}
        order_ok = ids_in_bullets == expected_ids
        ratios_ok = True
        if order_ok:
            for sid in expected_ids:
                ratio_value = ratios_in_bullets.get(sid)
                if ratio_value is None:
                    ratios_ok = False
                    break
                if _round3(ratio_value) != _round3(expected["metrics_by_id"][sid]["unique_word_ratio"]):
                    ratios_ok = False
                    break
        else:
            ratios_ok = False
        scores["report_bulleted_ranking_with_ratios"] = 1.0 if (order_ok and ratios_ok) else 0.0
    else:
        scores["report_counts_correct"] = 0.0
        scores["report_filter_sets_listed"] = 0.0
        scores["report_bulleted_ranking_with_ratios"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False, indent=None))


if __name__ == "__main__":
    main()