import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_parse_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _split_sentences(text: str) -> List[str]:
    # Split on '.', '!' or '?' characters; ignore empty segments
    parts = re.split(r"[.!?]", text)
    sentences = [p.strip() for p in parts if p.strip() != ""]
    return sentences


def _count_words(text: str) -> int:
    # Split on whitespace
    return len(text.split())


def _float_eq(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _parse_logs(log_text: str) -> Tuple[set, Dict[int, Tuple[str, Optional[str]]], Dict[str, int]]:
    ids_in_log: set = set()
    events: Dict[int, Tuple[int, str, Optional[str]]] = {}  # id -> (index, status, error_message)
    error_type_counts: Dict[str, int] = {}
    lines = log_text.splitlines()
    for idx, line in enumerate(lines):
        # Find any id in line for ids_in_log
        m_id = re.search(r"id=(\d+)", line)
        if m_id:
            id_val = int(m_id.group(1))
            ids_in_log.add(id_val)
        # ERROR lines
        m_err = re.match(r".*ERROR id=(\d+)\s+(.*)$", line)
        if m_err:
            e_id = int(m_err.group(1))
            msg = m_err.group(2).strip()
            events[e_id] = (idx, "ERROR", msg)
            continue
        # SUCCESS lines must contain [SUCCESS]
        if "[SUCCESS]" in line:
            m = re.search(r"id=(\d+)", line)
            if m:
                s_id = int(m.group(1))
                events[s_id] = (idx, "SUCCESS", None)
    # Build final status dict using last event index
    final_status: Dict[int, Tuple[str, Optional[str]]] = {}
    # sort by index ensure last event kept (but we already overwrite with increasing idx)
    for rid, (_idx, status, msg) in events.items():
        final_status[rid] = (status, msg)
    # error type counts from final statuses only (as per requirement)
    for rid, (status, msg) in final_status.items():
        if status == "ERROR" and msg is not None:
            error_type_counts[msg] = error_type_counts.get(msg, 0) + 1
    return ids_in_log, final_status, error_type_counts


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "simplified_resources_exists": 0.0,
        "simplified_resources_records_valid": 0.0,
        "top_improvements_exists": 0.0,
        "top_improvements_ranking_correct": 0.0,
        "summary_json_exists": 0.0,
        "summary_json_content_correct": 0.0,
        "filtering_correct": 0.0,
        "processed_count_matches_success_criteria": 0.0,
    }

    # Load inputs
    csv_path = workspace / "input" / "resources.csv"
    log_path = workspace / "logs" / "translate_run.log"
    resources_rows = _safe_parse_csv(csv_path)
    log_text = _safe_read_text(log_path)

    if resources_rows is None or log_text is None:
        # Cannot compute expected behavior without inputs
        return scores

    # Build CSV maps
    csv_by_id: Dict[int, Dict[str, str]] = {}
    csv_ids_set: set = set()
    for row in resources_rows:
        try:
            rid = int(row.get("id", "").strip())
        except Exception:
            continue
        csv_by_id[rid] = row
        csv_ids_set.add(rid)

    # Parse logs
    ids_in_log, final_status, error_type_counts = _parse_logs(log_text)
    orphan_log_ids = sorted(list(ids_in_log - csv_ids_set))
    missing_in_log_ids = sorted(list(csv_ids_set - ids_in_log))

    # Determine excluded by tag (internal)
    excluded_by_tag_ids = []
    for rid, row in csv_by_id.items():
        tags = row.get("tags", "") or ""
        tag_list = [t.strip() for t in tags.split(",")]
        if "internal" in tag_list:
            excluded_by_tag_ids.append(rid)
    excluded_by_tag_ids = sorted(excluded_by_tag_ids)

    # Determine final error ids
    error_ids = sorted([rid for rid, (st, _msg) in final_status.items() if st == "ERROR"])
    # Determine final success ids
    success_ids = sorted([rid for rid, (st, _msg) in final_status.items() if st == "SUCCESS"])

    # Processable ids: in CSV, SUCCESS, not internal
    processable_expected = sorted([rid for rid in success_ids if rid in csv_ids_set and rid not in excluded_by_tag_ids])

    # Prepare outputs paths
    out_dir = workspace / "output"
    jsonl_path = out_dir / "simplified_resources.jsonl"
    top_csv_path = out_dir / "top_improvements.csv"
    summary_json_path = out_dir / "summary.json"

    # Check existence
    if jsonl_path.is_file():
        scores["simplified_resources_exists"] = 1.0
    if top_csv_path.is_file():
        scores["top_improvements_exists"] = 1.0
    if summary_json_path.is_file():
        scores["summary_json_exists"] = 1.0

    # Load simplified_resources.jsonl and validate
    simplified_valid = False
    simplified_ids: List[int] = []
    simplified_by_id: Dict[int, Dict[str, Any]] = {}
    # We'll also compute metrics consistency flags
    if jsonl_path.is_file():
        txt = _safe_read_text(jsonl_path)
        if txt is not None:
            lines = [ln for ln in txt.splitlines() if ln.strip() != ""]
            parsed_records: List[Dict[str, Any]] = []
            try:
                for ln in lines:
                    rec = json.loads(ln)
                    if not isinstance(rec, dict):
                        raise ValueError("Non-object JSON line")
                    parsed_records.append(rec)
            except Exception:
                parsed_records = []

            # Validate records
            required_fields = [
                "id",
                "title",
                "original_lang",
                "source_lang",
                "was_translated",
                "original_sentence_count",
                "original_word_count",
                "avg_words_per_sentence_before",
                "simplified_sentence_count",
                "simplified_word_count",
                "avg_words_per_sentence_after",
                "improvement_score",
                "simplified_text",
            ]
            structure_ok = True
            metrics_ok = True
            ids_ok = True
            titles_ok = True
            flags_ok = True

            seen_ids = set()
            for rec in parsed_records:
                # Presence and types
                for k in required_fields:
                    if k not in rec:
                        structure_ok = False
                        break
                if not structure_ok:
                    break
                # Basic type checks
                if not isinstance(rec["id"], int):
                    structure_ok = False
                    break
                if not isinstance(rec["title"], str):
                    structure_ok = False
                    break
                if not isinstance(rec["original_lang"], str):
                    structure_ok = False
                    break
                if not isinstance(rec["source_lang"], str):
                    structure_ok = False
                    break
                if not isinstance(rec["was_translated"], bool):
                    structure_ok = False
                    break
                if not isinstance(rec["original_sentence_count"], int):
                    structure_ok = False
                    break
                if not isinstance(rec["original_word_count"], int):
                    structure_ok = False
                    break
                if not isinstance(rec["avg_words_per_sentence_before"], (int, float)):
                    structure_ok = False
                    break
                if not isinstance(rec["simplified_sentence_count"], int):
                    structure_ok = False
                    break
                if not isinstance(rec["simplified_word_count"], int):
                    structure_ok = False
                    break
                if not isinstance(rec["avg_words_per_sentence_after"], (int, float)):
                    structure_ok = False
                    break
                if not isinstance(rec["improvement_score"], (int, float)):
                    structure_ok = False
                    break
                if not isinstance(rec["simplified_text"], str) or rec["simplified_text"].strip() == "":
                    structure_ok = False
                    break

                rid = rec["id"]
                if rid in seen_ids:
                    ids_ok = False
                    break
                seen_ids.add(rid)

                # Cross-check with CSV record existence
                if rid not in csv_by_id:
                    ids_ok = False
                    break

                simplified_ids.append(rid)
                simplified_by_id[rid] = rec

                # Title check equals CSV title
                csv_title = csv_by_id[rid].get("title", "")
                if rec["title"] != csv_title:
                    titles_ok = False

                # Flags check
                original_lang = csv_by_id[rid].get("lang", "")
                if rec["original_lang"] != original_lang:
                    flags_ok = False
                if original_lang == "en":
                    if rec["was_translated"] is not False or rec["source_lang"] != "en":
                        flags_ok = False
                else:
                    if rec["was_translated"] is not True or rec["source_lang"] != original_lang:
                        flags_ok = False

                # Metrics check: compute original from CSV text
                original_text = csv_by_id[rid].get("text", "")
                orig_sents = _split_sentences(original_text)
                orig_sent_count = len(orig_sents)
                orig_word_count = _count_words(original_text)
                avg_before = (float(orig_word_count) / orig_sent_count) if orig_sent_count > 0 else 0.0

                if rec["original_sentence_count"] != orig_sent_count:
                    metrics_ok = False
                if rec["original_word_count"] != orig_word_count:
                    metrics_ok = False
                if not _float_eq(float(rec["avg_words_per_sentence_before"]), avg_before):
                    metrics_ok = False

                # Metrics check after: based on simplified_text
                simp_text = rec["simplified_text"]
                simp_sents = _split_sentences(simp_text)
                simp_sent_count = len(simp_sents)
                simp_word_count = _count_words(simp_text)
                avg_after = (float(simp_word_count) / simp_sent_count) if simp_sent_count > 0 else 0.0
                if rec["simplified_sentence_count"] != simp_sent_count:
                    metrics_ok = False
                if rec["simplified_word_count"] != simp_word_count:
                    metrics_ok = False
                if not _float_eq(float(rec["avg_words_per_sentence_after"]), avg_after):
                    metrics_ok = False

                # Improvement check
                improvement = avg_before - avg_after
                if not _float_eq(float(rec["improvement_score"]), improvement):
                    metrics_ok = False

            # Id set must match expected processable ids exactly
            if set(simplified_ids) != set(processable_expected):
                ids_ok = False

            simplified_valid = structure_ok and metrics_ok and ids_ok and titles_ok and flags_ok

    if simplified_valid:
        scores["simplified_resources_records_valid"] = 1.0

    # Filtering correctness: ensure no ERROR or missing_in_log appear in outputs (jsonl and top csv)
    filtering_ok = False
    if simplified_valid:
        simplified_set = set(simplified_ids)
        has_bad = any(rid in simplified_set for rid in error_ids) or any(rid in simplified_set for rid in missing_in_log_ids)
        filtering_ok = not has_bad

        # Also check top_improvements.csv for bad ids if exists
        if top_csv_path.is_file():
            # Parse csv
            try:
                with top_csv_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    top_rows = [row for row in reader]
                top_ids = []
                for row in top_rows:
                    try:
                        top_ids.append(int((row.get("id") or "").strip()))
                    except Exception:
                        filtering_ok = False
                        top_ids = []
                        break
                if any(rid in set(error_ids) for rid in top_ids) or any(rid in set(missing_in_log_ids) for rid in top_ids):
                    filtering_ok = False
            except Exception:
                filtering_ok = False
    scores["filtering_correct"] = 1.0 if filtering_ok else 0.0

    # Top improvements correctness
    top_ok = False
    if top_csv_path.is_file() and simplified_valid:
        try:
            with top_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames
                rows = [row for row in reader]
            # Columns exact
            if header != ["id", "title", "improvement_score"]:
                top_ok = False
            else:
                # Compute ranking from simplified records
                records = []
                for rid in simplified_ids:
                    rec = simplified_by_id[rid]
                    # Use improvement_score from recomputed values (already checked consistency)
                    imp = float(rec["improvement_score"])
                    records.append((rid, rec["title"], imp))
                # Sort: improvement desc, id asc
                expected_sorted = sorted(records, key=lambda t: (-t[2], t[0]))
                expected_top = expected_sorted[:3]
                # Validate number of rows: exactly min(3, len(records))
                if len(rows) != len(expected_top):
                    top_ok = False
                else:
                    # Validate order and values
                    match_all = True
                    for i, row in enumerate(rows):
                        try:
                            rid = int((row.get("id") or "").strip())
                            title = row.get("title", "")
                            imp = float(row.get("improvement_score", "nan"))
                        except Exception:
                            match_all = False
                            break
                        erid, etitle, eimp = expected_top[i]
                        if rid != erid or title != etitle or not _float_eq(imp, eimp):
                            match_all = False
                            break
                    top_ok = match_all
        except Exception:
            top_ok = False
    scores["top_improvements_ranking_correct"] = 1.0 if top_ok else 0.0

    # Processed count matches success criteria (jsonl count == expected, summary processed_ids length == expected if summary exists)
    processed_count_ok = False
    if simplified_valid:
        count_jsonl_ok = (len(simplified_ids) == len(processable_expected))
        summary_ok_count = True
        if summary_json_path.is_file():
            summary_obj = _safe_load_json(summary_json_path)
            if isinstance(summary_obj, dict):
                processed_ids_in_summary = summary_obj.get("processed_ids")
                if isinstance(processed_ids_in_summary, list):
                    try:
                        pid_set = set(int(x) for x in processed_ids_in_summary)
                        summary_ok_count = (pid_set == set(processable_expected)) and (len(processed_ids_in_summary) == len(processable_expected))
                    except Exception:
                        summary_ok_count = False
                else:
                    summary_ok_count = False
            else:
                summary_ok_count = False
        processed_count_ok = count_jsonl_ok and summary_ok_count
    scores["processed_count_matches_success_criteria"] = 1.0 if processed_count_ok else 0.0

    # Summary content correctness
    summary_ok = False
    if summary_json_path.is_file():
        summary_obj = _safe_load_json(summary_json_path)
        if isinstance(summary_obj, dict):
            try:
                # resources_in_csv should be an integer count
                ric = summary_obj.get("resources_in_csv", None)
                ids_in_log_field = summary_obj.get("ids_in_log", None)
                processed_ids_field = summary_obj.get("processed_ids", None)
                error_ids_field = summary_obj.get("error_ids", None)
                missing_in_log_ids_field = summary_obj.get("missing_in_log_ids", None)
                orphan_log_ids_field = summary_obj.get("orphan_log_ids", None)
                excluded_by_tag_ids_field = summary_obj.get("excluded_by_tag_ids", None)
                error_type_counts_field = summary_obj.get("error_type_counts", None)

                if not isinstance(ric, int):
                    summary_ok = False
                else:
                    checks = []

                    checks.append(ric == len(csv_ids_set))

                    # ids_in_log list, compare as set
                    if isinstance(ids_in_log_field, list):
                        try:
                            ids_in_log_list = [int(x) for x in ids_in_log_field]
                            checks.append(set(ids_in_log_list) == set(ids_in_log))
                        except Exception:
                            checks.append(False)
                    else:
                        checks.append(False)

                    # processed_ids list equals expected
                    if isinstance(processed_ids_field, list):
                        try:
                            pset = set(int(x) for x in processed_ids_field)
                            checks.append(pset == set(processable_expected))
                        except Exception:
                            checks.append(False)
                    else:
                        checks.append(False)

                    # error_ids list equals final error ids (from final statuses)
                    if isinstance(error_ids_field, list):
                        try:
                            eset = set(int(x) for x in error_ids_field)
                            checks.append(eset == set(error_ids))
                        except Exception:
                            checks.append(False)
                    else:
                        checks.append(False)

                    # missing_in_log_ids
                    if isinstance(missing_in_log_ids_field, list):
                        try:
                            mis_set = set(int(x) for x in missing_in_log_ids_field)
                            checks.append(mis_set == set(missing_in_log_ids))
                        except Exception:
                            checks.append(False)
                    else:
                        checks.append(False)

                    # orphan_log_ids
                    if isinstance(orphan_log_ids_field, list):
                        try:
                            orp_set = set(int(x) for x in orphan_log_ids_field)
                            checks.append(orp_set == set(orphan_log_ids))
                        except Exception:
                            checks.append(False)
                    else:
                        checks.append(False)

                    # excluded_by_tag_ids
                    if isinstance(excluded_by_tag_ids_field, list):
                        try:
                            ex_set = set(int(x) for x in excluded_by_tag_ids_field)
                            checks.append(ex_set == set(excluded_by_tag_ids))
                        except Exception:
                            checks.append(False)
                    else:
                        checks.append(False)

                    # error_type_counts dict equals computed map
                    if isinstance(error_type_counts_field, dict):
                        # Keys are strings, values are ints
                        etc_ok = True
                        # compare exact mapping
                        # Normalize keys and values
                        try:
                            # ensure values are ints
                            normalized = {str(k): int(v) for k, v in error_type_counts_field.items()}
                            etc_ok = (normalized == error_type_counts)
                        except Exception:
                            etc_ok = False
                        checks.append(etc_ok)
                    else:
                        checks.append(False)

                    summary_ok = all(checks)
            except Exception:
                summary_ok = False
    scores["summary_json_content_correct"] = 1.0 if summary_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()