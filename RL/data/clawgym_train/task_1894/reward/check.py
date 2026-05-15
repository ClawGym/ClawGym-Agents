import json
import csv
import math
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import importlib.util


# Reimplementation constants and marker sets derived from input/scoring.py
LENGTH_NORM = 120
LENGTH_BONUS_COEFF = 0.2
CAP = 5

MARKERS = {
    "evidence": {"evidence", "data", "study", "source", "sources", "cite", "cited"},
    "coherence": {"because", "therefore", "however", "but", "hence", "thus", "so", "although", "despite"},
    "nuance": {"depends", "context", "nuance", "trade-off", "tradeoff", "complex", "ambiguous", "uncertain", "uncertainty"},
    "originality": {"novel", "original", "unexpected", "fresh", "insight", "insightful", "new"},
}


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_json_load(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def approx_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def parse_weights_yaml(path: Path) -> Optional[Dict[str, float]]:
    """
    Minimal YAML parser for the simple structure:
    weights:
      evidence: 0.45
      coherence: 0.25
      nuance: 0.20
      originality: 0.10
    """
    text = safe_read_text(path)
    if text is None:
        return None
    weights: Dict[str, float] = {}
    in_weights = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not in_weights:
            if stripped.startswith("weights:"):
                in_weights = True
            continue
        # Expect indented key: value
        if ":" in stripped:
            # handle indentation
            if not line.startswith(" ") and not line.startswith("\t"):
                # likely new section; stop
                break
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip()
            try:
                weights[key] = float(val)
            except Exception:
                return None
        else:
            # unexpected format
            continue
    expected_keys = {"evidence", "coherence", "nuance", "originality"}
    if not weights or set(weights.keys()) != expected_keys:
        return None
    return weights


def import_scoring_module(scoring_path: Path):
    try:
        spec = importlib.util.spec_from_file_location("scoring_ref", str(scoring_path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        return module
    except Exception:
        return None


def feature_counts_reimpl(text: str) -> Tuple[int, Dict[str, int]]:
    lower = text.lower()
    tokens = re.findall(r"\b[\w'-]+\b", lower)
    counts = {k: 0 for k in MARKERS.keys()}
    for tok in tokens:
        for cat, vocab in MARKERS.items():
            if tok in vocab:
                counts[cat] += 1
    return len(tokens), counts


def capped_counts_reimpl(counts: Dict[str, int]) -> Dict[str, int]:
    return {k: min(v, CAP) for k, v in counts.items()}


def weighted_sum_reimpl(cc: Dict[str, int], weights: Dict[str, float]) -> float:
    s = 0.0
    for k, v in cc.items():
        s += weights.get(k, 0.0) * v
    return s


def length_bonus_reimpl(tokens: int) -> float:
    return math.log(1.0 + tokens) / math.log(1.0 + LENGTH_NORM)


def final_score_reimpl(answer_text: str, weights: Dict[str, float]) -> Tuple[int, Dict[str, int], Dict[str, int], float, float, float]:
    tokens, raw_counts = feature_counts_reimpl(answer_text)
    cc = capped_counts_reimpl(raw_counts)
    S = weighted_sum_reimpl(cc, weights)
    lb = length_bonus_reimpl(tokens)
    final = S * (1.0 + LENGTH_BONUS_COEFF * lb)
    return tokens, raw_counts, cc, S, lb, final


def parse_transcript(transcript_path: Path) -> Optional[List[Dict[str, str]]]:
    text = safe_read_text(transcript_path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    q_pat = re.compile(r"^\[(\d{2}:\d{2})\]\s+Journalist:\s*(.*)$")
    a_pat = re.compile(r"^\[(\d{2}:\d{2})\]\s+Critic:\s*(.*)$")

    pairs: List[Dict[str, str]] = []
    pending_q: Optional[Tuple[str, str]] = None  # (timestamp, question)
    idx = 0
    while idx < len(lines):
        q_m = q_pat.match(lines[idx].strip())
        if q_m:
            q_ts = q_m.group(1)
            q_text = q_m.group(2)
            # find next critic line
            a_ts = None
            a_text = None
            j = idx + 1
            while j < len(lines):
                a_m = a_pat.match(lines[j].strip())
                if a_m:
                    a_ts = a_m.group(1)
                    a_text = a_m.group(2)
                    break
                # stop if another question appears before an answer
                if q_pat.match(lines[j].strip()):
                    break
                j += 1
            if a_ts is not None and a_text is not None:
                pairs.append(
                    {
                        "question_timestamp": q_ts,
                        "answer_timestamp": a_ts,
                        "question": q_text,
                        "answer": a_text,
                    }
                )
                idx = j + 1
                continue
        idx += 1

    return pairs


def compute_expected(pairs: List[Dict[str, str]], weights: Dict[str, float]) -> List[Dict[str, object]]:
    expected_rows: List[Dict[str, object]] = []
    for i, pair in enumerate(pairs, start=1):
        ans = pair["answer"]
        tokens, raw_counts, cc, S, lb, final = final_score_reimpl(ans, weights)
        expected_rows.append(
            {
                "answer_id": i,
                "question_timestamp": pair["question_timestamp"],
                "answer_timestamp": pair["answer_timestamp"],
                "question": pair["question"],
                "answer": ans,
                "tokens": tokens,
                "evidence_count": cc.get("evidence", 0),
                "coherence_count": cc.get("coherence", 0),
                "nuance_count": cc.get("nuance", 0),
                "originality_count": cc.get("originality", 0),
                "weighted_sum": S,
                "length_bonus": lb,
                "final_score": final,
            }
        )
    return expected_rows


def load_answers_csv(path: Path) -> Tuple[bool, List[Dict[str, str]], List[str]]:
    rows = read_csv_rows(path)
    if rows is None:
        return False, [], []
    header: List[str] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
    except Exception:
        return False, [], []
    return True, rows, header


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "answers_scored_csv_present_and_header": 0.0,
        "answers_scored_row_count_correct": 0.0,
        "feature_counts_correct_ratio": 0.0,
        "score_components_correct_ratio": 0.0,
        "final_scores_correct_ratio": 0.0,
        "questions_and_answers_text_exact_match_ratio": 0.0,
        "timestamps_match_ratio": 0.0,
        "summary_json_metrics_correct": 0.0,
        "diffs_csv_consistent_with_cross_validation": 0.0,
        "validation_md_contains_required_explanation": 0.0,
    }

    # Load inputs
    transcript_path = workspace / "input" / "interview_transcript.txt"
    config_path = workspace / "input" / "critic_config.yaml"
    scoring_path = workspace / "input" / "scoring.py"

    pairs = parse_transcript(transcript_path) or []
    weights = parse_weights_yaml(config_path)
    scoring_module = import_scoring_module(scoring_path)

    if weights is None or scoring_module is None or not hasattr(scoring_module, "compute_score"):
        # Without weights or scoring module, we cannot compute expected results; return zeros
        return scores

    expected_rows = compute_expected(pairs, weights)

    # answers_scored.csv checks
    answers_csv_path = workspace / "output" / "answers_scored.csv"
    ok, rows, header = load_answers_csv(answers_csv_path)
    required_header = [
        "answer_id",
        "question_timestamp",
        "answer_timestamp",
        "question",
        "answer",
        "tokens",
        "evidence_count",
        "coherence_count",
        "nuance_count",
        "originality_count",
        "weighted_sum",
        "length_bonus",
        "final_score",
    ]
    if ok and header == required_header:
        scores["answers_scored_csv_present_and_header"] = 1.0

    if ok and len(rows) == len(expected_rows) and len(expected_rows) > 0:
        scores["answers_scored_row_count_correct"] = 1.0
    elif ok and len(expected_rows) == 0 and len(rows) == 0:
        scores["answers_scored_row_count_correct"] = 1.0

    # Initialize ratios
    denom = max(1, len(expected_rows))
    feature_match = 0
    score_comp_match = 0
    final_score_match = 0
    text_match = 0
    ts_match = 0

    if ok and header == required_header and len(rows) == len(expected_rows):
        # Build row mapping by answer_id
        row_by_id: Dict[int, Dict[str, str]] = {}
        for r in rows:
            try:
                aid = int(r.get("answer_id", "").strip())
            except Exception:
                continue
            row_by_id[aid] = r

        for exp in expected_rows:
            aid = exp["answer_id"]  # type: ignore
            r = row_by_id.get(aid)
            if r is None:
                continue

            # Check timestamps
            if r.get("question_timestamp", "") == exp["question_timestamp"] and r.get("answer_timestamp", "") == exp["answer_timestamp"]:
                ts_match += 1

            # Check question/answer text exact match
            if r.get("question", "") == exp["question"] and r.get("answer", "") == exp["answer"]:
                text_match += 1

            # Feature counts and tokens
            try:
                tokens_ok = int(r.get("tokens", "0")) == exp["tokens"]
                ec_ok = int(r.get("evidence_count", "0")) == exp["evidence_count"]
                cc_ok = int(r.get("coherence_count", "0")) == exp["coherence_count"]
                nc_ok = int(r.get("nuance_count", "0")) == exp["nuance_count"]
                oc_ok = int(r.get("originality_count", "0")) == exp["originality_count"]
                if tokens_ok and ec_ok and cc_ok and nc_ok and oc_ok:
                    feature_match += 1
            except Exception:
                pass

            # Score components
            try:
                ws_ok = approx_equal(float(r.get("weighted_sum", "nan")), float(exp["weighted_sum"]))
                lb_ok = approx_equal(float(r.get("length_bonus", "nan")), float(exp["length_bonus"]))
                if ws_ok and lb_ok:
                    score_comp_match += 1
            except Exception:
                pass

            # Final score: also compare to imported compute_score directly
            try:
                imported_score = float(scoring_module.compute_score(exp["answer"], weights))  # type: ignore
                csv_final = float(r.get("final_score", "nan"))
                if approx_equal(csv_final, imported_score) and approx_equal(csv_final, float(exp["final_score"])):
                    final_score_match += 1
            except Exception:
                pass

    if denom > 0:
        scores["feature_counts_correct_ratio"] = feature_match / denom
        scores["score_components_correct_ratio"] = score_comp_match / denom
        scores["final_scores_correct_ratio"] = final_score_match / denom
        scores["questions_and_answers_text_exact_match_ratio"] = text_match / denom
        scores["timestamps_match_ratio"] = ts_match / denom

    # summary.json checks
    summary_path = workspace / "output" / "summary.json"
    summary = safe_json_load(summary_path)
    if summary is not None and isinstance(summary, dict):
        # Compute expected aggregates
        N = len(expected_rows)
        expected_num_pairs = N
        expected_avg = (sum(float(e["final_score"]) for e in expected_rows) / N) if N > 0 else 0.0
        per_totals = {
            "evidence": sum(int(e["evidence_count"]) for e in expected_rows),
            "coherence": sum(int(e["coherence_count"]) for e in expected_rows),
            "nuance": sum(int(e["nuance_count"]) for e in expected_rows),
            "originality": sum(int(e["originality_count"]) for e in expected_rows),
        }
        # Check fields
        try:
            np_ok = int(summary.get("number_of_pairs", -1)) == expected_num_pairs
            avg_ok = approx_equal(float(summary.get("average_final_score", float("nan"))), expected_avg)
            pct = summary.get("per_criterion_totals", {})
            pct_ok = (
                isinstance(pct, dict)
                and all(k in pct for k in per_totals.keys())
                and all(int(pct.get(k)) == per_totals[k] for k in per_totals.keys())
            )
            top3 = summary.get("top_3_answers_by_score", [])
            # Build expected top3 answer_ids by score
            exp_sorted = sorted(
                [{"answer_id": int(e["answer_id"]), "final_score": float(e["final_score"])} for e in expected_rows],
                key=lambda x: (-x["final_score"], x["answer_id"]),
            )
            exp_top3 = exp_sorted[:3]
            # Validate top3 presence: sorted non-increasing and set of ids matches
            top3_ok = False
            if isinstance(top3, list):
                try:
                    # extract
                    rep_ids = [int(item.get("answer_id")) for item in top3]
                    rep_scores = [float(item.get("final_score")) for item in top3]
                    # check non-increasing
                    non_increasing = all(rep_scores[i] >= rep_scores[i + 1] - 1e-12 for i in range(len(rep_scores) - 1))
                    # set match by ids
                    exp_ids = {item["answer_id"] for item in exp_top3}
                    rep_ids_set = set(rep_ids)
                    ids_match = (rep_ids_set == exp_ids)
                    top3_ok = non_increasing and ids_match
                except Exception:
                    top3_ok = False
            if np_ok and avg_ok and pct_ok and top3_ok:
                scores["summary_json_metrics_correct"] = 1.0
        except Exception:
            pass

    # diffs.csv checks (cross-validation)
    diffs_path = workspace / "output" / "diffs.csv"
    diffs_ok = False
    diffs_rows = read_csv_rows(diffs_path)
    if diffs_rows is not None:
        # Compute mismatches between imported and reimplemented (grader's reimpl) for each answer
        mismatches: List[Tuple[int, float, float, float]] = []
        for e in expected_rows:
            aid = int(e["answer_id"])
            ans_text = str(e["answer"])
            imported = float(scoring_module.compute_score(ans_text, weights))  # type: ignore
            _, _, _, _, _, reimpl_final = final_score_reimpl(ans_text, weights)
            diff = abs(imported - reimpl_final)
            if diff > 1e-9:
                mismatches.append((aid, imported, reimpl_final, diff))
        # Validate diffs.csv with expected mismatches
        # Header check
        header_ok = False
        try:
            with diffs_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
                header_ok = header == ["answer_id", "imported_score", "reimplemented_score", "absolute_diff"]
        except Exception:
            header_ok = False

        if header_ok:
            if len(mismatches) == 0:
                # Expect only header and no data
                diffs_ok = len(diffs_rows) == 0
            else:
                # Build map from answer_id to row values
                try:
                    by_id = {}
                    for r in diffs_rows:
                        aid = int(r.get("answer_id", "0"))
                        by_id[aid] = r
                    if len(by_id) == len(mismatches):
                        all_match = True
                        for (aid, imp, reimp, df) in mismatches:
                            r = by_id.get(aid)
                            if r is None:
                                all_match = False
                                break
                            try:
                                imp_ok = approx_equal(float(r.get("imported_score", "nan")), imp)
                                reimp_ok = approx_equal(float(r.get("reimplemented_score", "nan")), reimp)
                                diff_ok = approx_equal(float(r.get("absolute_diff", "nan")), df)
                                if not (imp_ok and reimp_ok and diff_ok):
                                    all_match = False
                                    break
                            except Exception:
                                all_match = False
                                break
                        diffs_ok = all_match
                except Exception:
                    diffs_ok = False

    if diffs_ok:
        scores["diffs_csv_consistent_with_cross_validation"] = 1.0

    # validation.md checks
    validation_path = workspace / "output" / "validation.md"
    vtxt = safe_read_text(validation_path)
    if vtxt is not None:
        # Check for mentions of constants and formula elements and diffs.csv
        has_len_norm = ("LENGTH_NORM" in vtxt) and ("120" in vtxt)
        has_len_coeff = ("LENGTH_BONUS_COEFF" in vtxt) and ("0.2" in vtxt)
        has_cap = ("CAP" in vtxt) and ("5" in vtxt)
        has_log_tokens = ("log" in vtxt.lower() and "tokens" in vtxt.lower())
        has_weighted = ("weighted" in vtxt.lower())
        has_diffs = ("diffs.csv" in vtxt)
        if has_len_norm and has_len_coeff and has_cap and has_log_tokens and has_weighted and has_diffs:
            scores["validation_md_contains_required_explanation"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()