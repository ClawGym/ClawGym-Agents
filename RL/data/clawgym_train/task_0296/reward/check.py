import csv
import json
import re
import sys
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None


def _compute_sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _parse_int(s: Any) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _parse_float(s: Any) -> Optional[float]:
    try:
        return float(str(s).strip())
    except Exception:
        return None


def _tokenize_for_jaccard(text: str) -> List[str]:
    if text is None:
        text = ""
    text = text.lower()
    # Keep only alphanumeric and spaces
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return text.split()


def _jaccard_score(a: str, b: str) -> float:
    ta = set(_tokenize_for_jaccard(a))
    tb = set(_tokenize_for_jaccard(b))
    union = ta | tb
    inter = ta & tb
    if len(union) == 0:
        return 1.0
    return len(inter) / len(union)


def _is_sorted_by_intent_id_then_rank(rows: List[Dict[str, Any]]) -> bool:
    last_intent_id = None
    last_rank = None
    for row in rows:
        cur_id = _parse_int(row.get("intent_id"))
        cur_rank = _parse_int(row.get("rank"))
        if cur_id is None or cur_rank is None:
            return False
        if last_intent_id is None:
            last_intent_id = cur_id
            last_rank = cur_rank
            continue
        if cur_id < last_intent_id:
            return False
        if cur_id == last_intent_id and cur_rank < last_rank:
            return False
        if cur_id > last_intent_id:
            # reset rank tracker
            last_rank = cur_rank
        else:
            last_rank = cur_rank
        last_intent_id = cur_id
    return True


def _group_by_intent_id(rows: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    groups: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        iid = _parse_int(r.get("intent_id"))
        if iid is None:
            continue
        groups.setdefault(iid, []).append(r)
    return groups


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "cli_script_exists": 0.0,
        "cli_has_required_flags": 0.0,
        "translations_es_all_exists_and_columns": 0.0,
        "translations_es_all_sorted_and_ranks": 0.0,
        "translations_es_all_jaccard_scores_correct": 0.0,
        "translations_es_all_rank_ordering_valid": 0.0,
        "translations_es_all_intent_alignment_with_input": 0.0,
        "translations_es_top_exists_and_columns": 0.0,
        "translations_es_top_one_per_intent_and_sorted": 0.0,
        "top_matches_best_candidate_from_all": 0.0,
        "review_queue_exists_and_columns": 0.0,
        "review_queue_correct_filter_and_sort": 0.0,
        "metadata_json_exists_and_fields": 0.0,
        "metadata_input_sha256_matches": 0.0,
        "metadata_sample_count_matches_input": 0.0,
        "metadata_model_ids_include_required": 0.0,
        "metadata_threshold_beam_topk_present": 0.0,
        "all_candidates_within_topk_limit": 0.0,
    }

    # Paths
    input_csv_path = workspace / "input" / "english_intents.csv"
    all_csv_path = workspace / "output" / "translations_es_all.csv"
    top_csv_path = workspace / "output" / "translations_es_top.csv"
    review_csv_path = workspace / "output" / "review_queue.csv"
    metadata_path = workspace / "output" / "metadata.json"
    cli_script_path = workspace / "scripts" / "translate_intents.py"

    # Load input
    input_headers = None
    input_rows: List[Dict[str, str]] = []
    input_map_by_id: Dict[int, Dict[str, str]] = {}
    if input_csv_path.exists():
        res = _safe_read_csv_dicts(input_csv_path)
        if res is not None:
            input_headers, input_rows = res
            # Build mapping
            ok_input = True
            for r in input_rows:
                iid = _parse_int(r.get("intent_id"))
                if iid is None:
                    ok_input = False
                    break
                input_map_by_id[iid] = r
        else:
            ok_input = False
    else:
        ok_input = False

    input_sha256 = _compute_sha256_file(input_csv_path) if input_csv_path.exists() else None
    input_count = len(input_rows) if ok_input else 0

    # Check CLI script existence and flags
    if cli_script_path.exists() and cli_script_path.is_file():
        scores["cli_script_exists"] = 1.0
        content = _safe_read_text(cli_script_path) or ""
        required_flags = ["--input", "--outdir", "--beam", "--topk", "--threshold"]
        if all(flag in content for flag in required_flags):
            scores["cli_has_required_flags"] = 1.0

    # Load metadata
    metadata = _safe_load_json(metadata_path) if metadata_path.exists() else None
    if metadata is not None and isinstance(metadata, dict):
        # Basic fields presence
        has_required_fields = True
        # model_ids (list)
        model_ids = metadata.get("model_ids")
        transformers_version = metadata.get("transformers_version")
        beam_val = metadata.get("beam")
        topk_val = metadata.get("topk")
        threshold_val = metadata.get("threshold")
        input_sha_meta = metadata.get("input_sha256")
        sample_count_meta = metadata.get("sample_count")
        success_flag = metadata.get("success")

        # Basic presence checks
        if not (isinstance(model_ids, list) and len(model_ids) >= 2):
            has_required_fields = False
        if not isinstance(transformers_version, str) or not transformers_version:
            has_required_fields = False
        # beam/topk/threshold numeric
        beam_ok = isinstance(beam_val, int)
        topk_ok = isinstance(topk_val, int)
        threshold_ok = isinstance(threshold_val, (int, float))
        if not (beam_ok and topk_ok and threshold_ok):
            has_required_fields = False
        if not isinstance(input_sha_meta, str):
            has_required_fields = False
        if not isinstance(sample_count_meta, int):
            has_required_fields = False
        if not isinstance(success_flag, bool):
            has_required_fields = False

        # Required model ids include both repos
        required_models = {"Helsinki-NLP/opus-mt-en-es", "Helsinki-NLP/opus-mt-es-en"}
        model_ids_set = set(model_ids) if isinstance(model_ids, list) else set()
        if required_models.issubset(model_ids_set):
            scores["metadata_model_ids_include_required"] = 1.0

        if has_required_fields:
            scores["metadata_json_exists_and_fields"] = 1.0

        # Verify SHA256
        if input_sha256 is not None and input_sha_meta == input_sha256:
            scores["metadata_input_sha256_matches"] = 1.0

        # Verify sample_count
        if ok_input and isinstance(sample_count_meta, int) and sample_count_meta == input_count:
            scores["metadata_sample_count_matches_input"] = 1.0

        # beam/topk/threshold presence (already checked types)
        if beam_ok and topk_ok and threshold_ok:
            scores["metadata_threshold_beam_topk_present"] = 1.0
    else:
        metadata = {}

    # Load translations_es_all.csv
    all_headers = None
    all_rows: List[Dict[str, str]] = []
    if all_csv_path.exists():
        res = _safe_read_csv_dicts(all_csv_path)
        if res is not None:
            all_headers, all_rows = res

    # Validate translations_es_all.csv columns
    expected_all_headers = [
        "intent_id",
        "intent_name",
        "english_text",
        "candidate_es",
        "back_translation_en",
        "rank",
        "score",
    ]
    all_columns_ok = all_headers == expected_all_headers and len(all_rows) > 0 if all_headers else False
    if all_columns_ok:
        scores["translations_es_all_exists_and_columns"] = 1.0

    # Validate sorting and ranks
    all_sorted_and_ranks_ok = False
    if all_columns_ok:
        # Check global sort by intent_id asc then rank asc
        if _is_sorted_by_intent_id_then_rank(all_rows):
            groups = _group_by_intent_id(all_rows)
            ranks_ok = True
            for iid, grp in groups.items():
                # grp is encountered in global order due to prior check, but we need to filter rows for this iid
                grp_rows = [r for r in all_rows if _parse_int(r.get("intent_id")) == iid]
                # ranks must be 1..n for each group
                ranks = []
                for r in grp_rows:
                    rv = _parse_int(r.get("rank"))
                    if rv is None:
                        ranks_ok = False
                        break
                    ranks.append(rv)
                if not ranks:
                    ranks_ok = False
                    break
                expected_ranks = list(range(1, len(ranks) + 1))
                if ranks != expected_ranks:
                    ranks_ok = False
                    break
            if ranks_ok:
                all_sorted_and_ranks_ok = True
    if all_sorted_and_ranks_ok:
        scores["translations_es_all_sorted_and_ranks"] = 1.0

    # Validate jaccard scores correctness and intent alignment
    jaccard_ok = False
    alignment_ok = False
    ranking_ok = False
    within_topk_limit_ok = False
    if all_columns_ok:
        # jaccard
        jaccard_ok_flag = True
        for r in all_rows:
            eng = r.get("english_text", "")
            back = r.get("back_translation_en", "")
            score_str = r.get("score", "")
            score_val = _parse_float(score_str)
            if score_val is None:
                jaccard_ok_flag = False
                break
            comp = _jaccard_score(eng, back)
            if abs(comp - score_val) > 1e-6:
                jaccard_ok_flag = False
                break
        if jaccard_ok_flag:
            jaccard_ok = True

        # alignment
        alignment_flag = True
        if not ok_input:
            alignment_flag = False
        else:
            for r in all_rows:
                iid = _parse_int(r.get("intent_id"))
                if iid is None or iid not in input_map_by_id:
                    alignment_flag = False
                    break
                in_row = input_map_by_id[iid]
                if r.get("intent_name") != in_row.get("intent_name") or r.get("english_text") != in_row.get("english_text"):
                    alignment_flag = False
                    break
        if alignment_flag:
            alignment_ok = True

        # ranking validity within each intent (non-increasing score; ties by shorter candidate_es)
        ranking_flag = True
        groups = _group_by_intent_id(all_rows)
        for iid, _ in groups.items():
            grp_rows = [r for r in all_rows if _parse_int(r.get("intent_id")) == iid]
            # They are already sorted by rank ascending; validate by score non-increasing
            prev_score = None
            prev_len = None
            for r in grp_rows:
                score_val = _parse_float(r.get("score"))
                cand = r.get("candidate_es", "") or ""
                clen = len(cand)
                if score_val is None:
                    ranking_flag = False
                    break
                if prev_score is None:
                    prev_score = score_val
                    prev_len = clen
                    continue
                # non-increasing
                if score_val > prev_score + 1e-12:
                    ranking_flag = False
                    break
                # tie-break by shorter candidate length (ascending length when equal score)
                if abs(score_val - prev_score) <= 1e-12:
                    if clen < prev_len:
                        # current shorter than previous -> violates nondecreasing length
                        # We expect nondecreasing lengths across ties (shorter first), so current (later) cannot be shorter
                        ranking_flag = False
                        break
                prev_score = score_val
                prev_len = clen
            if not ranking_flag:
                break
        if ranking_flag:
            ranking_ok = True

        # topk limit
        topk_val = metadata.get("topk") if isinstance(metadata, dict) else None
        topk_int = None
        if isinstance(topk_val, int):
            topk_int = topk_val
        within_limit_flag = True
        if topk_int is not None:
            groups2 = _group_by_intent_id(all_rows)
            for iid, _ in groups2.items():
                count = sum(1 for r in all_rows if _parse_int(r.get("intent_id")) == iid)
                if count < 1 or count > topk_int:
                    within_limit_flag = False
                    break
        else:
            # If no topk provided in metadata, we can't verify; mark as False
            within_limit_flag = False
        if within_limit_flag:
            within_topk_limit_ok = True

    if jaccard_ok:
        scores["translations_es_all_jaccard_scores_correct"] = 1.0
    if alignment_ok:
        scores["translations_es_all_intent_alignment_with_input"] = 1.0
    if ranking_ok:
        scores["translations_es_all_rank_ordering_valid"] = 1.0
    if within_topk_limit_ok:
        scores["all_candidates_within_topk_limit"] = 1.0

    # Load translations_es_top.csv
    top_headers = None
    top_rows: List[Dict[str, str]] = []
    if top_csv_path.exists():
        res = _safe_read_csv_dicts(top_csv_path)
        if res is not None:
            top_headers, top_rows = res

    expected_top_headers = [
        "intent_id",
        "intent_name",
        "english_text",
        "selected_es",
        "score",
    ]
    top_columns_ok = top_headers == expected_top_headers and len(top_rows) > 0 if top_headers else False
    if top_columns_ok:
        scores["translations_es_top_exists_and_columns"] = 1.0

    # Validate top one per intent and sorted
    top_one_per_intent_sorted_ok = False
    if top_columns_ok and ok_input:
        # sorted by intent_id ascending
        sorted_flag = True
        last_id = None
        ids_seen = set()
        for r in top_rows:
            iid = _parse_int(r.get("intent_id"))
            if iid is None:
                sorted_flag = False
                break
            if last_id is not None and iid < last_id:
                sorted_flag = False
                break
            ids_seen.add(iid)
            last_id = iid
        if sorted_flag and len(ids_seen) == input_count and ids_seen == set(input_map_by_id.keys()):
            top_one_per_intent_sorted_ok = True
    if top_one_per_intent_sorted_ok:
        scores["translations_es_top_one_per_intent_and_sorted"] = 1.0

    # Verify top matches rank-1 from all.csv
    top_matches_all_ok = False
    if top_columns_ok and all_columns_ok:
        match_flag = True
        # Build map rank1 by intent from all
        rank1_by_intent: Dict[int, Dict[str, str]] = {}
        for r in all_rows:
            iid = _parse_int(r.get("intent_id"))
            rk = _parse_int(r.get("rank"))
            if iid is None or rk is None:
                match_flag = False
                break
            if rk == 1 and iid not in rank1_by_intent:
                rank1_by_intent[iid] = r
        if match_flag:
            for tr in top_rows:
                iid = _parse_int(tr.get("intent_id"))
                if iid is None or iid not in rank1_by_intent:
                    match_flag = False
                    break
                ar = rank1_by_intent[iid]
                # selected_es should equal candidate_es
                if tr.get("selected_es") != ar.get("candidate_es"):
                    match_flag = False
                    break
                # score should match
                ts = _parse_float(tr.get("score"))
                as_ = _parse_float(ar.get("score"))
                if ts is None or as_ is None or abs(ts - as_) > 1e-6:
                    match_flag = False
                    break
                # intent_name and english_text should match
                if tr.get("intent_name") != ar.get("intent_name") or tr.get("english_text") != ar.get("english_text"):
                    match_flag = False
                    break
        if match_flag:
            top_matches_all_ok = True
    if top_matches_all_ok:
        scores["top_matches_best_candidate_from_all"] = 1.0

    # Load review_queue.csv
    review_headers = None
    review_rows: List[Dict[str, str]] = []
    if review_csv_path.exists():
        res = _safe_read_csv_dicts(review_csv_path)
        if res is not None:
            review_headers, review_rows = res

    expected_review_headers = [
        "intent_id",
        "intent_name",
        "english_text",
        "selected_es",
        "score",
    ]
    review_columns_ok = review_headers == expected_review_headers and review_rows is not None and review_headers is not None
    if review_columns_ok:
        scores["review_queue_exists_and_columns"] = 1.0

    # Validate review queue correct filter and sort
    review_correct_ok = False
    threshold_val = metadata.get("threshold") if isinstance(metadata, dict) else None
    if review_columns_ok and top_columns_ok and isinstance(threshold_val, (int, float)):
        thr = float(threshold_val)
        # Expected rows: top rows where score < threshold
        exp_rows = [r for r in top_rows if (_parse_float(r.get("score")) is not None and _parse_float(r.get("score")) < thr)]
        # Sort expected by score ascending
        exp_rows_sorted = sorted(exp_rows, key=lambda r: (_parse_float(r.get("score")), _parse_int(r.get("intent_id"))))
        # Actual: review rows must all match entries from top with score < threshold, and sorted by score ascending
        # First, check all have score < threshold and belong to set
        review_ok_flag = True
        # Check sorting by score ascending
        last_score = None
        for rr in review_rows:
            sc = _parse_float(rr.get("score"))
            if sc is None:
                review_ok_flag = False
                break
            if last_score is not None and sc < last_score - 1e-12:
                review_ok_flag = False
                break
            last_score = sc
            if sc >= thr - 1e-12:  # must be strictly less than threshold (allow numerical tolerance)
                # if sc == thr, should not be included
                if sc >= thr - 1e-12 and sc <= thr + 1e-12:
                    # Consider sc equal to thr within tolerance -> treat as equal; should not be included
                    review_ok_flag = False
                    break
                else:
                    review_ok_flag = False
                    break
        # Compare content sets: by intent_id must match expected subset
        if review_ok_flag:
            exp_ids = [(_parse_int(r.get("intent_id")), r.get("intent_name"), r.get("english_text"), r.get("selected_es"), _parse_float(r.get("score"))) for r in exp_rows_sorted]
            act_ids = [(_parse_int(r.get("intent_id")), r.get("intent_name"), r.get("english_text"), r.get("selected_es"), _parse_float(r.get("score"))) for r in review_rows]
            # Exact order equality
            if exp_ids != act_ids:
                review_ok_flag = False
        if review_ok_flag:
            review_correct_ok = True
    if review_correct_ok:
        scores["review_queue_correct_filter_and_sort"] = 1.0

    return scores


def main() -> None:
        workspace = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade([], workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()