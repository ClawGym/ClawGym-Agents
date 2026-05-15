import sys
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Tuple, List, Dict, Any


def _safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def _safe_json_load(path: Path) -> Tuple[bool, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _safe_csv_read(path: Path) -> Tuple[bool, List[str], List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames if reader.fieldnames is not None else []
            rows = [dict(r) for r in reader]
            return True, header, rows
    except Exception:
        return False, [], []


def _count_lines(path: Path) -> Tuple[bool, int]:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            count = sum(1 for _ in f)
        return True, count
    except Exception:
        return False, 0


def _is_iso8601(ts: str) -> bool:
    # Accept common ISO-8601 formats, including 'Z'
    try:
        datetime.fromisoformat(ts)
        return True
    except Exception:
        pass
    try:
        if ts.endswith("Z"):
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return True
    except Exception:
        pass
    return False


def _float_or_none(s: str) -> Any:
    try:
        return float(s)
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _parse_title_rankings_rows(rows: List[Dict[str, str]]) -> Tuple[bool, List[Dict[str, Any]]]:
    parsed = []
    for r in rows:
        try:
            isbn = r.get("isbn", "")
            title = r.get("title", "")
            rc = int(r.get("review_count", ""))
            avg = float(r.get("avg_compound", ""))
            ps = float(r.get("positive_share", ""))
            ns = float(r.get("negative_share", ""))
        except Exception:
            return False, []
        parsed.append({
            "isbn": isbn,
            "title": title,
            "review_count": rc,
            "avg_compound": avg,
            "positive_share": ps,
            "negative_share": ns,
        })
    return True, parsed


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validate_sh_present_executable": 0.0,
        "validate_contains_lexicon_and_metadata_checks": 0.0,
        "validate_runs_sample_and_checks_rowcount": 0.0,
        "validate_checks_label_presence": 0.0,
        "validate_checks_top_title_sample": 0.0,
        "review_sentiment_file_structure": 0.0,
        "review_sentiment_rowcount_matches_input": 0.0,
        "sentiment_scores_ranges_and_sum": 0.0,
        "label_threshold_logic_applied": 0.0,
        "title_rankings_file_structure": 0.0,
        "title_rankings_filter_limit": 0.0,
        "title_rankings_sorting_correct": 0.0,
        "title_rankings_aggregates_correct": 0.0,
        "metadata_fields_and_types": 0.0,
        "metadata_lexicon_file_and_linecount": 0.0,
        "metadata_records_processed_consistency": 0.0,
    }

    # Check validation script existence and content
    validate_sh = workspace / "tests" / "validate.sh"
    if validate_sh.exists() and validate_sh.is_file():
        # Executable bit might not be preserved, allow presence as success, but prefer executable
        scores["validate_sh_present_executable"] = 1.0 if validate_sh.stat().st_mode & 0o111 else 0.5
        ok, script_text = _safe_read_text(validate_sh)
        if ok and script_text:
            # Lexicon and metadata checks presence
            if ("data/vendor/vader_lexicon.txt" in script_text
                    and "output/metadata.json" in script_text
                    and "line_count" in script_text):
                scores["validate_contains_lexicon_and_metadata_checks"] = 1.0
            # Runs sample and checks rowcount
            # Look for references to the sample input and output file and a line counting operation
            if ("input/reviews_sample.csv" in script_text
                    and "output/review_sentiment.csv" in script_text
                    and ("wc -l" in script_text or "awk" in script_text or "grep" in script_text)):
                scores["validate_runs_sample_and_checks_rowcount"] = 1.0
            # Checks label presence: positive and negative
            if ("positive" in script_text and "negative" in script_text
                    and "review_sentiment.csv" in script_text and ("grep" in script_text or "awk" in script_text)):
                scores["validate_checks_label_presence"] = 1.0
            # Checks top title for sample
            if ("The Wind's Path" in script_text and "title_rankings.csv" in script_text):
                scores["validate_checks_top_title_sample"] = 1.0

    # Paths
    input_reviews = workspace / "input" / "reviews.csv"
    rs_path = workspace / "output" / "review_sentiment.csv"
    tr_path = workspace / "output" / "title_rankings.csv"
    meta_path = workspace / "output" / "metadata.json"
    lexicon_path = workspace / "data" / "vendor" / "vader_lexicon.txt"

    # Read inputs
    input_ok, input_header, input_rows = _safe_csv_read(input_reviews)
    rs_ok, rs_header, rs_rows = _safe_csv_read(rs_path)
    tr_ok, tr_header, tr_rows = _safe_csv_read(tr_path)
    meta_ok, meta_json = _safe_json_load(meta_path)
    lex_ok, lex_lines = _count_lines(lexicon_path)

    # Review sentiment structure
    expected_rs_header = ["review_id", "isbn", "title", "pos", "neu", "neg", "compound", "label"]
    if rs_ok and rs_header == expected_rs_header:
        scores["review_sentiment_file_structure"] = 1.0

    # Rowcount matches input
    if input_ok and rs_ok:
        if len(rs_rows) == len(input_rows):
            scores["review_sentiment_rowcount_matches_input"] = 1.0

    # Sentiment scores ranges and sum to ~1
    if rs_ok and rs_rows:
        all_ok = True
        sum_ok = True
        for r in rs_rows:
            pos = _float_or_none(r.get("pos", ""))
            neu = _float_or_none(r.get("neu", ""))
            neg = _float_or_none(r.get("neg", ""))
            comp = _float_or_none(r.get("compound", ""))
            if pos is None or neu is None or neg is None or comp is None:
                all_ok = False
                break
            if not (0.0 - 1e-6 <= pos <= 1.0 + 1e-6 and 0.0 - 1e-6 <= neu <= 1.0 + 1e-6 and 0.0 - 1e-6 <= neg <= 1.0 + 1e-6):
                all_ok = False
                break
            if not (-1.0 - 1e-6 <= comp <= 1.0 + 1e-6):
                all_ok = False
                break
            if abs((pos + neu + neg) - 1.0) > 1e-2:
                sum_ok = False
                # Don't break; continue to check others
        if all_ok and sum_ok:
            scores["sentiment_scores_ranges_and_sum"] = 1.0

    # Label thresholds mapping
    if rs_ok and rs_rows:
        lbl_ok = True
        for r in rs_rows:
            lbl = (r.get("label") or "").strip().lower()
            comp = _float_or_none(r.get("compound", ""))
            if comp is None:
                lbl_ok = False
                break
            expected_label = "neutral"
            if comp >= 0.05:
                expected_label = "positive"
            elif comp <= -0.05:
                expected_label = "negative"
            if lbl not in ("positive", "negative", "neutral"):
                lbl_ok = False
                break
            if lbl != expected_label:
                lbl_ok = False
                break
        if lbl_ok:
            scores["label_threshold_logic_applied"] = 1.0

    # Title rankings structure
    expected_tr_header = ["isbn", "title", "review_count", "avg_compound", "positive_share", "negative_share"]
    if tr_ok and tr_header == expected_tr_header:
        scores["title_rankings_file_structure"] = 1.0

    # Parse title rankings rows
    tr_parsed_ok, tr_parsed_rows = (False, [])
    if tr_ok:
        tr_parsed_ok, tr_parsed_rows = _parse_title_rankings_rows(tr_rows)

    # Title rankings filter limit: <= 10 rows and all review_count >= 3
    if tr_parsed_ok:
        limit_ok = len(tr_parsed_rows) <= 10
        filter_ok = all(r["review_count"] >= 3 for r in tr_parsed_rows)
        if limit_ok and filter_ok:
            scores["title_rankings_filter_limit"] = 1.0

    # Title rankings aggregates and sorting correctness
    if rs_ok and tr_parsed_ok:
        # Build aggregation from review_sentiment.csv
        groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
        valid_rows = True
        for r in rs_rows:
            isbn = r.get("isbn")
            title = r.get("title")
            comp = _float_or_none(r.get("compound", ""))
            lbl = (r.get("label") or "").strip().lower()
            if isbn is None or title is None or comp is None or lbl not in ("positive", "negative", "neutral"):
                valid_rows = False
                break
            key = (isbn, title)
            g = groups.setdefault(key, {"count": 0, "sum_comp": 0.0, "pos": 0, "neg": 0})
            g["count"] += 1
            g["sum_comp"] += comp
            if lbl == "positive":
                g["pos"] += 1
            if lbl == "negative":
                g["neg"] += 1
        if valid_rows:
            # Compute expected rankings list
            expected = []
            for (isbn, title), g in groups.items():
                if g["count"] >= 3:
                    avg = g["sum_comp"] / g["count"]
                    ps = g["pos"] / g["count"]
                    ns = g["neg"] / g["count"]
                    expected.append({
                        "isbn": isbn,
                        "title": title,
                        "review_count": g["count"],
                        "avg_compound": avg,
                        "positive_share": ps,
                        "negative_share": ns,
                    })
            expected_sorted = sorted(
                expected,
                key=lambda x: (-x["avg_compound"], -x["review_count"], x["isbn"])
            )
            expected_top = expected_sorted[:min(10, len(expected_sorted))]

            # Aggregates correctness: values match for listed rows
            agg_ok = True
            # Build lookup for expected
            exp_map = {(e["isbn"], e["title"]): e for e in expected}
            for row in tr_parsed_rows:
                key = (row["isbn"], row["title"])
                if key not in exp_map:
                    agg_ok = False
                    break
                e = exp_map[key]
                if row["review_count"] != e["review_count"]:
                    agg_ok = False
                    break
                if not _approx_equal(row["avg_compound"], e["avg_compound"], 1e-6):
                    agg_ok = False
                    break
                if not _approx_equal(row["positive_share"], e["positive_share"], 1e-6):
                    agg_ok = False
                    break
                if not _approx_equal(row["negative_share"], e["negative_share"], 1e-6):
                    agg_ok = False
                    break
            if agg_ok:
                scores["title_rankings_aggregates_correct"] = 1.0

            # Sorting correctness: order equals expected first N
            sort_ok = True
            if len(tr_parsed_rows) != len(expected_top):
                sort_ok = False
            else:
                for got, exp in zip(tr_parsed_rows, expected_top):
                    if got["isbn"] != exp["isbn"] or got["title"] != exp["title"]:
                        sort_ok = False
                        break
            if sort_ok:
                scores["title_rankings_sorting_correct"] = 1.0

    # Metadata checks: fields and types
    if meta_ok and isinstance(meta_json, dict):
        fields_ok = True
        required_fields = [
            "lexicon_name",
            "source",
            "local_path",
            "downloaded",
            "line_count",
            "input_file",
            "records_processed",
        ]
        for k in required_fields:
            if k not in meta_json:
                fields_ok = False
                break
        if fields_ok:
            # Exact values for some fields
            name_ok = meta_json.get("lexicon_name") == "vader_lexicon.txt"
            source_ok = meta_json.get("source") == "official VADER sentiment resource"
            local_ok = meta_json.get("local_path") == "data/vendor/vader_lexicon.txt"
            # Types and format
            dl = meta_json.get("downloaded")
            dl_ok = isinstance(dl, str) and _is_iso8601(dl)
            lc = meta_json.get("line_count")
            lc_ok = isinstance(lc, int)
            inp = meta_json.get("input_file")
            inp_ok = isinstance(inp, str) and len(inp) > 0
            rp = meta_json.get("records_processed")
            rp_ok = isinstance(rp, int)
            if name_ok and source_ok and local_ok and dl_ok and lc_ok and inp_ok and rp_ok:
                scores["metadata_fields_and_types"] = 1.0

    # Metadata lexicon existence and line count consistency (>=6000)
    if meta_ok and isinstance(meta_json, dict):
        lc_meta = meta_json.get("line_count")
        if lex_ok and isinstance(lc_meta, int):
            if lex_lines == lc_meta and lex_lines >= 6000:
                scores["metadata_lexicon_file_and_linecount"] = 1.0

    # Metadata records_processed consistency with outputs and input
    if meta_ok and isinstance(meta_json, dict):
        rp = meta_json.get("records_processed")
        input_file_rel = meta_json.get("input_file")
        if isinstance(rp, int):
            # Compare with review_sentiment row count
            rs_count_ok = rs_ok and (len(rs_rows) == rp)
            # Compare with input file referenced, if exists
            if isinstance(input_file_rel, str) and input_file_rel:
                ref_path = workspace / input_file_rel
                ref_ok, _, ref_rows = _safe_csv_read(ref_path)
                in_count_ok = ref_ok and (len(ref_rows) == rp)
            else:
                in_count_ok = False
            # At least ensure consistency with review_sentiment or input file if available
            if rs_count_ok or in_count_ok:
                scores["metadata_records_processed_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()