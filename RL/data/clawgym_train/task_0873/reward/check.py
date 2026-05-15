import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Tuple[List[Dict[str, Any]], bool]:
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return ([], False)
                if not isinstance(obj, dict):
                    return ([], False)
                records.append(obj)
        return (records, True)
    except Exception:
        return ([], False)


def _safe_load_json(path: Path) -> Tuple[Dict[str, Any], bool]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return ({}, False)
        return (data, True)
    except Exception:
        return ({}, False)


def _safe_load_csv_dicts(path: Path) -> Tuple[List[Dict[str, str]], bool]:
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
        return (rows, True)
    except Exception:
        return ([], False)


def _sentence_split(text: str) -> List[str]:
    # Basic sentence splitter on ., ?, !, preserving clarity for given inputs.
    # Split on punctuation followed by whitespace.
    # Normalize whitespace and strip.
    parts = re.split(r'(?<=[\.\?\!])\s+', text)
    sentences: List[str] = []
    for p in parts:
        s = p.strip()
        if s:
            sentences.append(s)
    return sentences


def _list_input_docs(input_docs_dir: Path) -> List[Tuple[str, str]]:
    docs: List[Tuple[str, str]] = []
    if not input_docs_dir.exists() or not input_docs_dir.is_dir():
        return docs
    for p in sorted(input_docs_dir.glob("*.txt")):
        txt = _safe_read_text(p)
        if txt is None:
            continue
        doc_id = p.stem
        docs.append((doc_id, txt))
    return docs


def _load_places(input_places_csv: Path) -> Tuple[List[Dict[str, str]], bool]:
    rows, ok = _safe_load_csv_dicts(input_places_csv)
    if not ok:
        return ([], False)
    # Expect columns 'place_name' and 'normalized'
    required_cols = {"place_name", "normalized"}
    if not rows:
        return ([], False)
    # Validate header columns presence
    with input_places_csv.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except Exception:
            return ([], False)
    if not set(header) >= required_cols:
        return ([], False)
    # Validate rows have both fields non-empty
    for r in rows:
        if "place_name" not in r or "normalized" not in r:
            return ([], False)
        if not r["place_name"] or not r["normalized"]:
            return ([], False)
    return (rows, True)


def _compute_triplet_set_from_mentions(records: List[Dict[str, Any]]) -> Optional[set]:
    triplets = set()
    for r in records:
        if not isinstance(r, dict):
            return None
        if "doc_id" not in r or "place_normalized" not in r or "year" not in r:
            return None
        doc_id = r["doc_id"]
        place_norm = r["place_normalized"]
        year = r["year"]
        if not isinstance(doc_id, str) or not isinstance(place_norm, str):
            return None
        # Accept year as int-like; try cast
        if isinstance(year, int):
            y = year
        elif isinstance(year, str) and year.isdigit():
            y = int(year)
        else:
            return None
        triplets.add((doc_id, place_norm, y))
    return triplets


def _aggregate_counts(records: List[Dict[str, Any]]) -> Dict[Tuple[str, int], int]:
    agg: Dict[Tuple[str, int], int] = {}
    for r in records:
        try:
            place_norm = r["place_normalized"]
            year_val = r["year"]
            if not isinstance(place_norm, str):
                continue
            if not isinstance(year_val, int):
                if isinstance(year_val, str) and year_val.isdigit():
                    year_val = int(year_val)
                else:
                    continue
            key = (place_norm, int(year_val))
            agg[key] = agg.get(key, 0) + 1
        except Exception:
            continue
    return agg


def _compute_validation_metrics(pred: set, gold: set) -> Dict[str, Any]:
    tp = len(pred & gold)
    fp = len(pred - gold)
    fn = len(gold - pred)
    prec = (tp / (tp + fp)) if (tp + fp) > 0 else 1.0
    rec = (tp / (tp + fn)) if (tp + fn) > 0 else 1.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec}


def _float_close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _compute_diff_rows(pred: set, gold: set) -> List[Tuple[str, str, int, str]]:
    rows: List[Tuple[str, str, int, str]] = []
    missing = sorted(list(gold - pred))
    spurious = sorted(list(pred - gold))
    for (doc_id, place_norm, year) in missing:
        rows.append((doc_id, place_norm, int(year), "missing"))
    for (doc_id, place_norm, year) in spurious:
        rows.append((doc_id, place_norm, int(year), "spurious"))
    return rows


def _parse_ints_from_line(line: str) -> List[int]:
    return [int(x) for x in re.findall(r'(?<!\d)(\d+)(?!\d)', line)]


def _parse_floats_from_line(line: str) -> List[float]:
    # Match floats like 0.95 or integers
    vals: List[float] = []
    for m in re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', line):
        try:
            vals.append(float(m))
        except Exception:
            continue
    return vals


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "mentions_jsonl_exists": 0.0,
        "mentions_jsonl_valid_schema": 0.0,
        "summary_csv_correct": 0.0,
        "validation_metrics_correct": 0.0,
        "validation_diff_correct": 0.0,
        "status_update_present": 0.0,
        "status_update_counts_and_metrics": 0.0,
    }

    # Paths
    input_docs_dir = workspace / "input" / "docs"
    input_places_csv = workspace / "input" / "places.csv"
    input_gold_mentions = workspace / "input" / "gold_mentions.jsonl"

    output_mentions = workspace / "output" / "mentions.jsonl"
    output_summary = workspace / "output" / "summary.csv"
    output_validation_dir = workspace / "output" / "validation"
    output_metrics = output_validation_dir / "metrics.json"
    output_diff = output_validation_dir / "diff.csv"
    output_status = workspace / "output" / "status_update.md"

    # Load inputs needed for checks
    docs = _list_input_docs(input_docs_dir)
    doc_ids_set = set(doc_id for doc_id, _ in docs)
    all_sentences_count = 0
    for _, txt in docs:
        all_sentences_count += len(_sentence_split(txt))

    places_rows, places_ok = _load_places(input_places_csv)
    places_norm_set = set(r["normalized"] for r in places_rows) if places_ok else set()

    gold_records, gold_ok = _safe_load_jsonl(input_gold_mentions)
    gold_triplets = _compute_triplet_set_from_mentions(gold_records) if gold_ok else None

    # Check mentions.jsonl exists
    mentions_records: List[Dict[str, Any]] = []
    mentions_ok = False
    if output_mentions.exists() and output_mentions.is_file():
        scores["mentions_jsonl_exists"] = 1.0
        mentions_records, mentions_ok = _safe_load_jsonl(output_mentions)
        if not mentions_ok:
            mentions_records = []
    else:
        scores["mentions_jsonl_exists"] = 0.0
        mentions_ok = False

    # Validate mentions.jsonl schema and values
    mentions_schema_ok = False
    if mentions_ok:
        schema_good = True
        for r in mentions_records:
            # Required fields
            required = ["doc_id", "place_mention", "place_normalized", "year", "sentence_text"]
            if any(k not in r for k in required):
                schema_good = False
                break
            # Types
            if not isinstance(r["doc_id"], str) or not isinstance(r["place_mention"], str) or not isinstance(r["place_normalized"], str) or not isinstance(r["sentence_text"], str):
                schema_good = False
                break
            # Year type and range
            year_val = r["year"]
            if isinstance(year_val, int):
                y = year_val
            elif isinstance(year_val, str) and year_val.isdigit():
                y = int(year_val)
            else:
                schema_good = False
                break
            if y < 1800 or y > 1999:
                schema_good = False
                break
            # doc_id must be known
            if doc_ids_set:
                if r["doc_id"] not in doc_ids_set:
                    schema_good = False
                    break
            # place_normalized must be canonical
            if places_norm_set:
                if r["place_normalized"] not in places_norm_set:
                    schema_good = False
                    break
            # sentence_text should contain the year and the place mention (case-insensitive)
            if str(y) not in r["sentence_text"]:
                schema_good = False
                break
            if r["place_mention"].lower() not in r["sentence_text"].lower():
                schema_good = False
                break
        mentions_schema_ok = schema_good
    scores["mentions_jsonl_valid_schema"] = 1.0 if mentions_schema_ok else 0.0

    # summary.csv correctness: compare to aggregation from mentions
    summary_ok = False
    if mentions_schema_ok and output_summary.exists():
        summary_rows, summary_rows_ok = _safe_load_csv_dicts(output_summary)
        if summary_rows_ok:
            # Validate columns presence
            try:
                with output_summary.open("r", encoding="utf-8", errors="replace", newline="") as f:
                    reader = csv.reader(f)
                    header = next(reader)
            except Exception:
                header = []
            required_cols = {"place_normalized", "year", "count"}
            if required_cols.issubset(set(header)):
                # Parse rows and build dict
                parsed_summary: Dict[Tuple[str, int], int] = {}
                valid_rows = True
                for row in summary_rows:
                    if not all(k in row for k in ["place_normalized", "year", "count"]):
                        valid_rows = False
                        break
                    place_norm = row["place_normalized"]
                    year_str = row["year"]
                    count_str = row["count"]
                    try:
                        y = int(year_str)
                        c = int(count_str)
                    except Exception:
                        valid_rows = False
                        break
                    parsed_summary[(place_norm, y)] = c
                if valid_rows:
                    # Compute expected from mentions
                    expected_agg = _aggregate_counts(mentions_records)
                    summary_ok = expected_agg == parsed_summary
    scores["summary_csv_correct"] = 1.0 if summary_ok else 0.0

    # validation metrics correctness
    metrics_ok = False
    if output_metrics.exists() and output_metrics.is_file() and mentions_ok and gold_triplets is not None:
        # Load reported metrics
        reported_metrics, rep_ok = _safe_load_json(output_metrics)
        if rep_ok and all(k in reported_metrics for k in ["tp", "fp", "fn", "precision", "recall"]):
            # Compute our metrics
            pred_triplets = _compute_triplet_set_from_mentions(mentions_records)
            if pred_triplets is not None:
                calc = _compute_validation_metrics(pred_triplets, gold_triplets)
                # Compare with tolerance
                try:
                    rep_tp = int(reported_metrics["tp"])
                    rep_fp = int(reported_metrics["fp"])
                    rep_fn = int(reported_metrics["fn"])
                    rep_prec = float(reported_metrics["precision"])
                    rep_rec = float(reported_metrics["recall"])
                    if (
                        rep_tp == calc["tp"]
                        and rep_fp == calc["fp"]
                        and rep_fn == calc["fn"]
                        and _float_close(rep_prec, calc["precision"])
                        and _float_close(rep_rec, calc["recall"])
                    ):
                        metrics_ok = True
                except Exception:
                    metrics_ok = False
    scores["validation_metrics_correct"] = 1.0 if metrics_ok else 0.0

    # validation diff correctness
    diff_ok = False
    if output_diff.exists() and output_diff.is_file() and mentions_ok and gold_triplets is not None:
        # Load diff.csv
        diff_rows, diff_rows_ok = _safe_load_csv_dicts(output_diff)
        # Need header check
        try:
            with output_diff.open("r", encoding="utf-8", errors="replace", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = []
        required_cols = {"doc_id", "place_normalized", "year", "status"}
        if diff_rows_ok and required_cols.issubset(set(header)):
            # Build reported set
            reported_set = set()
            valid = True
            for row in diff_rows:
                try:
                    doc_id = row["doc_id"]
                    place_norm = row["place_normalized"]
                    year_val = int(row["year"])
                    status = row["status"]
                    if status not in ("missing", "spurious"):
                        valid = False
                        break
                    reported_set.add((doc_id, place_norm, year_val, status))
                except Exception:
                    valid = False
                    break
            if valid:
                pred_triplets = _compute_triplet_set_from_mentions(mentions_records)
                if pred_triplets is not None:
                    expected_rows = set(_compute_diff_rows(pred_triplets, gold_triplets))
                    exp = set(expected_rows)
                    if reported_set == exp:
                        diff_ok = True
    scores["validation_diff_correct"] = 1.0 if diff_ok else 0.0

    # status_update presence
    scores["status_update_present"] = 1.0 if output_status.exists() and output_status.is_file() else 0.0

    # status_update counts and metrics consistency
    status_ok = False
    if output_status.exists() and output_status.is_file():
        content = _safe_read_text(output_status) or ""
        # Length check: enforce not too long (<= 3000 chars)
        length_ok = len(content) <= 3000
        # Extract required info
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        # How to run: look for "run" keyword
        how_to_run_ok = any(re.search(r'\brun\b', ln, flags=re.IGNORECASE) for ln in lines)

        # Documents processed count
        docs_count_expected = len(doc_ids_set)
        sentences_count_expected = all_sentences_count
        total_extracted_expected = len(mentions_records) if mentions_ok else 0

        # Try to find counts on lines mentioning documents / sentences / extracted
        def _find_first_int_with_keyword(keyword: str) -> Optional[int]:
            for ln in lines:
                if re.search(keyword, ln, flags=re.IGNORECASE):
                    ints = _parse_ints_from_line(ln)
                    if ints:
                        return ints[0]
            return None

        docs_reported = _find_first_int_with_keyword(r'\b(documents?|docs?)\b')
        sentences_reported = _find_first_int_with_keyword(r'\bsentences?\b')
        extracted_reported = _find_first_int_with_keyword(r'\b(total|overall)\b.*\b(extract|mentions?)\b')

        counts_ok = True
        if docs_reported is None or docs_reported != docs_count_expected:
            counts_ok = False
        if sentences_reported is None or sentences_reported != sentences_count_expected:
            counts_ok = False
        if extracted_reported is None or extracted_reported != total_extracted_expected:
            counts_ok = False

        # Validation results tp/fp/fn, precision, recall from metrics.json
        tp_exp = fp_exp = fn_exp = None
        prec_exp = rec_exp = None
        if metrics_ok:
            rep_metrics, _ = _safe_load_json(output_metrics)
            try:
                tp_exp = int(rep_metrics["tp"])
                fp_exp = int(rep_metrics["fp"])
                fn_exp = int(rep_metrics["fn"])
                prec_exp = float(rep_metrics["precision"])
                rec_exp = float(rep_metrics["recall"])
            except Exception:
                pass

        # Extract reported from text
        def _find_metric_value(name: str, is_float: bool) -> Optional[float]:
            for ln in lines:
                if re.search(rf'\b{name}\b', ln, flags=re.IGNORECASE):
                    nums = _parse_floats_from_line(ln) if is_float else [float(x) for x in _parse_ints_from_line(ln)]
                    if nums:
                        return nums[0]
            return None

        tp_rep = _find_metric_value("tp", is_float=False)
        fp_rep = _find_metric_value("fp", is_float=False)
        fn_rep = _find_metric_value("fn", is_float=False)
        prec_rep = _find_metric_value("precision", is_float=True)
        rec_rep = _find_metric_value("recall", is_float=True)

        metrics_report_ok = True
        if metrics_ok and None not in (tp_exp, fp_exp, fn_exp, prec_exp, rec_exp):
            # Ensure reported numbers appear and match expected
            if tp_rep is None or int(tp_rep) != tp_exp:
                metrics_report_ok = False
            if fp_rep is None or int(fp_rep) != fp_exp:
                metrics_report_ok = False
            if fn_rep is None or int(fn_rep) != fn_exp:
                metrics_report_ok = False
            if prec_rep is None or not _float_close(float(prec_rep), float(prec_exp), tol=1e-6):
                metrics_report_ok = False
            if rec_rep is None or not _float_close(float(rec_rep), float(rec_exp), tol=1e-6):
                metrics_report_ok = False
        else:
            # If metrics.json invalid, we cannot verify; mark as False
            metrics_report_ok = False

        # Two concrete next-step improvements: look for at least two bullet-like lines
        bullet_lines = [ln for ln in lines if re.match(r'^(\-|\*|\d+\.)\s', ln)]
        improvements_ok = len(bullet_lines) >= 2

        status_ok = length_ok and how_to_run_ok and counts_ok and metrics_report_ok and improvements_ok

    scores["status_update_counts_and_metrics"] = 1.0 if status_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()