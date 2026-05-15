import csv
import json
import sys
import subprocess
import tempfile
import shutil
import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline='') as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _try_parse_list_cell(cell: str) -> Optional[List[str]]:
    if cell is None:
        return None
    s = cell.strip()
    # Try JSON list
    try:
        val = json.loads(s)
        if isinstance(val, list):
            return val
    except Exception:
        pass
    # Try Python literal list
    try:
        val = ast.literal_eval(s)
        if isinstance(val, list):
            return val
    except Exception:
        pass
    # Try comma-separated
    try:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        if parts:
            return parts
    except Exception:
        pass
    return None


def _parse_criteria_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Very small, targeted YAML parser for the provided criteria.yaml structure.
    Returns a dict with keys: selection_rules, scoring, style_constraints,
    or None on failure.
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    # Initialize structures
    selection_rules = {}
    scoring = {"weights": {}}
    style_constraints = {}

    current_section = None
    in_weights = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":") and not ":" in line[:-1]:
            # Section header
            name = line[:-1].strip()
            if name in ("selection_rules", "scoring", "style_constraints"):
                current_section = name
                in_weights = False
            elif name == "weights" and current_section == "scoring":
                in_weights = True
            else:
                # Unknown section - ignore
                pass
            continue

        # key: value lines
        if current_section == "selection_rules":
            # Handle lists and ints
            if line.startswith("excluded_sources:"):
                val = line.split(":", 1)[1].strip()
                try:
                    selection_rules["excluded_sources"] = ast.literal_eval(val)
                except Exception:
                    return None
            elif line.startswith("prefer_sources:"):
                val = line.split(":", 1)[1].strip()
                try:
                    selection_rules["prefer_sources"] = ast.literal_eval(val)
                except Exception:
                    return None
            elif line.startswith("max_quote_length_chars:"):
                val = line.split(":", 1)[1].strip()
                try:
                    selection_rules["max_quote_length_chars"] = int(val)
                except Exception:
                    return None
            elif line.startswith("max_red_flag_count:"):
                val = line.split(":", 1)[1].strip()
                try:
                    selection_rules["max_red_flag_count"] = int(val)
                except Exception:
                    return None
            elif line.startswith("top_n:"):
                val = line.split(":", 1)[1].strip()
                try:
                    selection_rules["top_n"] = int(val)
                except Exception:
                    return None
        elif current_section == "scoring":
            if in_weights:
                # Parse weight lines: key: value
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    try:
                        scoring["weights"][k] = float(v)
                    except Exception:
                        return None
            else:
                if line.startswith("readability_normalization_divisor:"):
                    val = line.split(":", 1)[1].strip()
                    try:
                        scoring["readability_normalization_divisor"] = float(val)
                    except Exception:
                        return None
        elif current_section == "style_constraints":
            if line.startswith("target_letter_word_count_range:"):
                val = line.split(":", 1)[1].strip()
                try:
                    style_constraints["target_letter_word_count_range"] = ast.literal_eval(val)
                except Exception:
                    return None
            elif line.startswith("avoid_terms:"):
                val = line.split(":", 1)[1].strip()
                try:
                    style_constraints["avoid_terms"] = ast.literal_eval(val)
                except Exception:
                    return None

    # Basic validation
    required_sel = {"excluded_sources", "max_quote_length_chars", "max_red_flag_count", "top_n", "prefer_sources"}
    required_sco = {"weights", "readability_normalization_divisor"}
    required_weights = {"relevance_hint", "readability", "red_flag_penalty"}
    required_style = {"target_letter_word_count_range", "avoid_terms"}
    if not (required_sel.issubset(set(selection_rules.keys())) and
            required_sco.issubset(set(scoring.keys())) and
            required_weights.issubset(set(scoring["weights"].keys())) and
            required_style.issubset(set(style_constraints.keys()))):
        return None

    return {
        "selection_rules": selection_rules,
        "scoring": scoring,
        "style_constraints": style_constraints
    }


def _recompute_metrics_via_script(workspace: Path, quotes_csv: Path, script_path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    """
    Run the provided CLI script in an isolated temp directory to recompute metrics.json,
    and return the parsed dict mapping id -> metrics.
    """
    if not script_path.exists() or not quotes_csv.exists():
        return None
    tempdir = Path(tempfile.mkdtemp(prefix="grader_tmp_"))
    try:
        cmd = [sys.executable, str(script_path), str(quotes_csv)]
        # Run with cwd=tempdir to avoid modifying workspace
        proc = subprocess.run(cmd, cwd=str(tempdir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # The script writes outputs/metrics.json under tempdir
        out_metrics = tempdir / "outputs" / "metrics.json"
        if proc.returncode != 0 or not out_metrics.exists():
            return None
        data = _safe_load_json(out_metrics)
        if not isinstance(data, dict):
            return None
        # Ensure each entry has required keys
        for qid, metrics in data.items():
            if not isinstance(metrics, dict):
                return None
            for key in ("readability_score", "red_flag_count", "flagged_terms", "char_count", "word_count"):
                if key not in metrics:
                    return None
        return data
    except Exception:
        return None
    finally:
        try:
            shutil.rmtree(tempdir, ignore_errors=True)
        except Exception:
            pass


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _compute_eligibility(source_relation: str, char_count: int, red_flag_count: int, rules: Dict[str, Any]) -> str:
    # Returns "kept" or "excluded: <reason>"
    if source_relation in rules.get("excluded_sources", []):
        return "excluded: source"
    if char_count > int(rules.get("max_quote_length_chars", 0)):
        return "excluded: length"
    if red_flag_count > int(rules.get("max_red_flag_count", 0)):
        return "excluded: red_flags"
    return "kept"


def _sort_desc(values: List[float]) -> bool:
    # Check non-increasing
    for i in range(1, len(values)):
        if values[i] > values[i-1] + 1e-12:
            return False
    return True


def _word_count(text: str) -> int:
    # Simple word count via whitespace split
    return len([w for w in re.findall(r"\b\w+\b", text)])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_json_matches_recomputed": 0.0,
        "quotes_ranked_has_required_columns": 0.0,
        "quotes_ranked_complete_and_sorted": 0.0,
        "quotes_ranked_metrics_consistent_with_metrics_json": 0.0,
        "quotes_ranked_eligibility_rules_applied": 0.0,
        "quotes_ranked_total_score_and_normalization_correct": 0.0,
        "final_letter_word_count_and_avoid_terms": 0.0,
        "final_letter_includes_exact_top_n_and_attribution": 0.0,
        "change_log_covers_required_points": 0.0
    }

    # Paths
    quotes_csv = workspace / "input" / "quotes.csv"
    criteria_yaml = workspace / "input" / "criteria.yaml"
    draft_letter = workspace / "input" / "draft_letter.md"
    script_path = workspace / "scripts" / "assess_text.py"
    metrics_json_path = workspace / "outputs" / "metrics.json"
    quotes_ranked_csv = workspace / "outputs" / "quotes_ranked.csv"
    final_letter_md = workspace / "outputs" / "final_letter.md"
    change_log_md = workspace / "outputs" / "change_log.md"

    # Load base inputs
    quotes_rows = _safe_read_csv_dicts(quotes_csv) or []
    quotes_by_id = {row.get("id", "").strip(): row for row in quotes_rows if row.get("id")}
    criteria = _parse_criteria_yaml(criteria_yaml)
    # Guard values
    selection_rules = criteria["selection_rules"] if criteria else {}
    scoring = criteria["scoring"] if criteria else {"weights": {}, "readability_normalization_divisor": 1.0}
    style_constraints = criteria["style_constraints"] if criteria else {"target_letter_word_count_range": [350, 550], "avoid_terms": []}

    # Recompute metrics via script to compare
    recomputed = _recompute_metrics_via_script(workspace, quotes_csv, script_path)

    # Load provided outputs
    provided_metrics = _safe_load_json(metrics_json_path)
    ranked_rows_raw = _safe_read_csv_dicts(quotes_ranked_csv)

    # 1) metrics_json_matches_recomputed
    if isinstance(provided_metrics, dict) and isinstance(recomputed, dict):
        # Compare keys and values exactly
        if set(provided_metrics.keys()) == set(recomputed.keys()):
            consistent = True
            for qid, met in provided_metrics.items():
                rmet = recomputed.get(qid, {})
                # All keys must match and values equal
                if not isinstance(met, dict) or not isinstance(rmet, dict):
                    consistent = False
                    break
                # Exact dict equality for metrics
                # Note: order of flagged_terms may matter; recomputed uses sorted unique
                # To be robust, compare as sets for flagged_terms and equality for others
                for k in ("readability_score", "red_flag_count", "char_count", "word_count"):
                    if k not in met or k not in rmet:
                        consistent = False
                        break
                    if isinstance(met[k], float) or isinstance(rmet[k], float):
                        if not _float_equal(float(met[k]), float(rmet[k])):
                            consistent = False
                            break
                    else:
                        if int(met[k]) != int(rmet[k]):
                            consistent = False
                            break
                if not consistent:
                    break
                mf = met.get("flagged_terms")
                rf = rmet.get("flagged_terms")
                try:
                    if sorted(list(mf)) != sorted(list(rf)):
                        consistent = False
                        break
                except Exception:
                    consistent = False
                    break
            scores["metrics_json_matches_recomputed"] = 1.0 if consistent else 0.0
        else:
            scores["metrics_json_matches_recomputed"] = 0.0
    else:
        scores["metrics_json_matches_recomputed"] = 0.0

    # Proceed only if we have ranked rows and provided_metrics
    if ranked_rows_raw is None:
        ranked_rows_raw = []
    # Normalize ranked rows by id map
    ranked_by_id = {}
    required_cols = [
        "id", "source_relation", "relevance_hint", "readability_score",
        "readability_normalized", "red_flag_count", "flagged_terms",
        "char_count", "total_score", "eligibility"
    ]

    # 2) quotes_ranked_has_required_columns
    if ranked_rows_raw:
        header_cols = list(ranked_rows_raw[0].keys())
        has_all = all(col in header_cols for col in required_cols)
        scores["quotes_ranked_has_required_columns"] = 1.0 if has_all else 0.0
    else:
        scores["quotes_ranked_has_required_columns"] = 0.0

    # Prepare comparisons if possible
    # Verify completeness and sorting by total_score desc
    if ranked_rows_raw:
        # Build list of total scores to verify sorting
        totals = []
        all_ids_in_ranked = set()
        for row in ranked_rows_raw:
            try:
                totals.append(float(row.get("total_score", "nan")))
                all_ids_in_ranked.add(row.get("id", "").strip())
            except Exception:
                totals.append(float("nan"))
        # Check all ids present from input/quotes.csv if available
        all_ids_in_input = set(quotes_by_id.keys())
        ids_complete = (len(all_ids_in_input) > 0 and all_ids_in_ranked == all_ids_in_input) or (len(all_ids_in_input) == 0 and len(all_ids_in_ranked) == 0)
        sorted_desc = _sort_desc(totals) if totals and all(not (v != v) for v in totals) else False  # v!=v for NaN
        scores["quotes_ranked_complete_and_sorted"] = 1.0 if (ids_complete and sorted_desc) else 0.0
    else:
        scores["quotes_ranked_complete_and_sorted"] = 0.0

    # 3) quotes_ranked_metrics_consistent_with_metrics_json
    metrics_consistent = True
    if isinstance(provided_metrics, dict) and ranked_rows_raw:
        for row in ranked_rows_raw:
            qid = row.get("id", "").strip()
            met = provided_metrics.get(qid)
            if not met:
                metrics_consistent = False
                break
            # Compare readability_score, red_flag_count, flagged_terms, char_count
            try:
                rscore_csv = float(row.get("readability_score"))
                rscore_json = float(met.get("readability_score"))
                if not _float_equal(rscore_csv, rscore_json):
                    metrics_consistent = False
                    break
                rfc_csv = int(row.get("red_flag_count"))
                rfc_json = int(met.get("red_flag_count"))
                if rfc_csv != rfc_json:
                    metrics_consistent = False
                    break
                ccount_csv = int(row.get("char_count"))
                ccount_json = int(met.get("char_count"))
                if ccount_csv != ccount_json:
                    metrics_consistent = False
                    break
                # flagged_terms
                ft_cell = row.get("flagged_terms", "")
                ft_list = _try_parse_list_cell(ft_cell)
                if ft_list is None:
                    metrics_consistent = False
                    break
                ft_list_sorted = sorted([str(x) for x in ft_list])
                ft_json_sorted = sorted([str(x) for x in met.get("flagged_terms", [])])
                if ft_list_sorted != ft_json_sorted:
                    metrics_consistent = False
                    break
            except Exception:
                metrics_consistent = False
                break
        scores["quotes_ranked_metrics_consistent_with_metrics_json"] = 1.0 if metrics_consistent else 0.0
    else:
        scores["quotes_ranked_metrics_consistent_with_metrics_json"] = 0.0

    # 4) quotes_ranked_eligibility_rules_applied and 5) total score correctness
    elig_ok = True
    score_ok = True
    if ranked_rows_raw and criteria and isinstance(provided_metrics, dict) and quotes_by_id:
        divisor = float(scoring.get("readability_normalization_divisor", 1.0))
        weights = scoring.get("weights", {})
        w_rel = float(weights.get("relevance_hint", 0.0))
        w_read = float(weights.get("readability", 0.0))
        w_pen = float(weights.get("red_flag_penalty", 0.0))

        for row in ranked_rows_raw:
            qid = row.get("id", "").strip()
            # Expected source_relation and relevance_hint from input
            base = quotes_by_id.get(qid)
            met = provided_metrics.get(qid)
            if base is None or met is None:
                elig_ok = False
                score_ok = False
                break
            try:
                # Eligibility
                src = row.get("source_relation", "").strip()
                src_expected = base.get("source_relation", "").strip()
                rel_csv = int(row.get("relevance_hint"))
                rel_expected = int(base.get("relevance_hint"))
                if src != src_expected or rel_csv != rel_expected:
                    elig_ok = False
                    # continue checking scores though
                rscore = float(row.get("readability_score"))
                rnorm = float(row.get("readability_normalized"))
                rfc = int(row.get("red_flag_count"))
                ccount = int(row.get("char_count"))
                # eligibility calculation
                expected_elig = _compute_eligibility(src, ccount, rfc, selection_rules)
                actual_elig = row.get("eligibility", "").strip()
                # Check "kept" vs "excluded:"
                if expected_elig == "kept":
                    if actual_elig != "kept":
                        elig_ok = False
                else:
                    if not actual_elig.startswith("excluded:"):
                        elig_ok = False
                # normalization
                expected_norm = rscore / divisor if divisor != 0 else 0.0
                if not _float_equal(rnorm, expected_norm):
                    score_ok = False
                # total score
                total_csv = float(row.get("total_score"))
                total_expected = (w_rel * rel_csv) + (w_read * expected_norm) - (w_pen * rfc)
                if not _float_equal(total_csv, total_expected):
                    score_ok = False
            except Exception:
                elig_ok = False
                score_ok = False
                break

        scores["quotes_ranked_eligibility_rules_applied"] = 1.0 if elig_ok else 0.0
        scores["quotes_ranked_total_score_and_normalization_correct"] = 1.0 if score_ok else 0.0
    else:
        scores["quotes_ranked_eligibility_rules_applied"] = 0.0
        scores["quotes_ranked_total_score_and_normalization_correct"] = 0.0

    # Determine top_n eligible ids by total_score from quotes_ranked.csv
    top_n_ids: List[str] = []
    kept_rows: List[Tuple[str, float]] = []
    if ranked_rows_raw and criteria:
        try:
            for row in ranked_rows_raw:
                elig = row.get("eligibility", "").strip()
                if elig == "kept":
                    qid = row.get("id", "").strip()
                    ts = float(row.get("total_score"))
                    kept_rows.append((qid, ts))
            # Sort by total_score descending
            kept_rows_sorted = sorted(kept_rows, key=lambda x: (-x[1], x[0]))
            n = int(selection_rules.get("top_n", 0))
            top_n_ids = [qid for qid, _ in kept_rows_sorted[:n]]
        except Exception:
            top_n_ids = []

    # Additional check: ensure top_n kept ordering matches top_n appearance order in CSV
    # (i.e., the first top_n kept rows encountered match top_n_ids)
    if ranked_rows_raw and top_n_ids:
        encountered_kept = [row.get("id", "").strip() for row in ranked_rows_raw if row.get("eligibility", "").strip() == "kept"]
        order_ok = encountered_kept[:len(top_n_ids)] == top_n_ids
        # If order isn't ok, penalize sorting check if not already failed
        if not order_ok and scores["quotes_ranked_complete_and_sorted"] == 1.0:
            scores["quotes_ranked_complete_and_sorted"] = 0.0

    # 6) final_letter_word_count_and_avoid_terms
    final_text = _safe_read_text(final_letter_md)
    if final_text is not None and criteria:
        # Word count
        wc = _word_count(final_text)
        low, high = style_constraints.get("target_letter_word_count_range", [350, 550])
        within_range = (wc >= int(low) and wc <= int(high))
        # Avoid terms
        avoid_terms = style_constraints.get("avoid_terms", [])
        avoids_all = True
        lower_text = final_text.lower()
        for term in avoid_terms:
            if term.lower() in lower_text:
                avoids_all = False
                break
        if within_range and avoids_all:
            scores["final_letter_word_count_and_avoid_terms"] = 1.0
        else:
            scores["final_letter_word_count_and_avoid_terms"] = 0.0
    else:
        scores["final_letter_word_count_and_avoid_terms"] = 0.0

    # 7) final_letter_includes_exact_top_n_and_attribution
    includes_ok = False
    if final_text is not None and top_n_ids and quotes_by_id:
        # Verify it includes exactly the top_n kept quotes verbatim and no others from the dataset
        present_ids = []
        for qid, row in quotes_by_id.items():
            text = row.get("quote_text", "")
            if text and text in final_text:
                present_ids.append(qid)
        # Must include exactly top_n_ids and no others
        if set(present_ids) == set(top_n_ids) and len(present_ids) == len(top_n_ids):
            # Check attribution for each included quote: parenthetical with source relation
            attrib_ok = True
            for qid in top_n_ids:
                src_rel = quotes_by_id[qid].get("source_relation", "")
                src_opt1 = f"({src_rel})"
                src_opt2 = f"({src_rel.replace('_', ' ')})"
                if src_opt1 not in final_text and src_opt2 not in final_text:
                    attrib_ok = False
                    break
            includes_ok = attrib_ok
        else:
            includes_ok = False
        scores["final_letter_includes_exact_top_n_and_attribution"] = 1.0 if includes_ok else 0.0
    else:
        scores["final_letter_includes_exact_top_n_and_attribution"] = 0.0

    # 8) change_log_covers_required_points
    change_text = _safe_read_text(change_log_md)
    if change_text is not None and top_n_ids:
        # Must mention changes to draft, included quotes with ids and sources, reasons for exclusions, and scoring/filtering
        has_changes = bool(re.search(r"change|rewrite|edited|modified", change_text, re.IGNORECASE))
        has_ids = all((qid in change_text) for qid in top_n_ids)
        has_sources = any(sr in change_text for sr in [quotes_by_id[qid].get("source_relation", "") for qid in top_n_ids])
        # mention exclusion reasons or flagged terms/thresholds
        has_excl_reasons = bool(re.search(r"exclude|excluded|flag|threshold|red[_ -]?flag|max_quote_length|max_red_flag_count", change_text, re.IGNORECASE))
        # mention scoring/filtering
        has_scoring = bool(re.search(r"score|scoring|weights|readability|rank|filter", change_text, re.IGNORECASE))
        if has_changes and has_ids and has_sources and has_excl_reasons and has_scoring:
            scores["change_log_covers_required_points"] = 1.0
        else:
            scores["change_log_covers_required_points"] = 0.0
    else:
        scores["change_log_covers_required_points"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()