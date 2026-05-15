import json
import sys
import csv
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_csv(path: Path, delimiter: str = ",") -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            rows = list(reader)
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def simple_yaml_parse(path: Path) -> Optional[Dict[str, object]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    result: Dict[str, object] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            val = val[1:-1]
        if val.isdigit():
            result[key] = int(val)
        else:
            # Try to parse common scalars (True/False)
            if val in ("True", "False"):
                result[key] = True if val == "True" else False
            else:
                result[key] = val
    return result


def safe_load_json(path: Path) -> Optional[Dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def parse_float_safe(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def compute_dataset_overview(workspace: Path) -> Optional[Dict[str, Dict[str, int]]]:
    data_dir = workspace / "data"
    overview: Dict[str, Dict[str, int]] = {}
    provisions_path = data_dir / "public_health_provisions.csv"
    mortality_path = data_dir / "smallpox_mortality.tsv"

    prov_rows = safe_load_csv(provisions_path, delimiter=",")
    if prov_rows is None:
        return None
    prov_columns = list(prov_rows[0].keys()) if prov_rows else []
    prov_unique_states = len(set([r.get("state", "") for r in prov_rows]))
    overview["data/public_health_provisions.csv"] = {
        "rows": len(prov_rows),
        "columns": len(prov_columns),
        "unique_states": prov_unique_states,
    }

    mort_rows = safe_load_csv(mortality_path, delimiter="\t")
    if mort_rows is None:
        return None
    mort_columns = list(mort_rows[0].keys()) if mort_rows else []
    mort_unique_states = len(set([r.get("state", "") for r in mort_rows]))
    overview["data/smallpox_mortality.tsv"] = {
        "rows": len(mort_rows),
        "columns": len(mort_columns),
        "unique_states": mort_unique_states,
    }

    return overview


def recompute_expected_changes(
    workspace: Path, start_year: int, end_year: int, group_by_clause: str, outcome_metric: str
) -> Optional[Tuple[List[Dict[str, object]], Dict[str, Dict[str, object]]]]:
    provisions_path = workspace / "data" / "public_health_provisions.csv"
    mortality_path = workspace / "data" / "smallpox_mortality.tsv"

    prov_rows = safe_load_csv(provisions_path, delimiter=",")
    mort_rows = safe_load_csv(mortality_path, delimiter="\t")
    if prov_rows is None or mort_rows is None:
        return None

    group_by_values: Dict[str, str] = {}
    for r in prov_rows:
        state = r.get("state")
        if state is None:
            continue
        val = r.get(group_by_clause)
        group_by_values[state] = val if val is not None else ""

    by_state: Dict[str, List[Dict[str, str]]] = {}
    for r in mort_rows:
        try:
            st = r["state"]
            _ = int(str(r["year"]).strip())
            metric_val = r.get(outcome_metric)
            if metric_val is None:
                continue
            _ = float(metric_val)
        except Exception:
            continue
        by_state.setdefault(st, []).append(r)

    per_state_results: List[Dict[str, object]] = []
    for state, rows in by_state.items():
        pre_vals: List[float] = []
        post_vals: List[float] = []
        for r in rows:
            try:
                yr = int(str(r["year"]).strip())
                val = float(r[outcome_metric])
            except Exception:
                continue
            if yr < start_year:
                pre_vals.append(val)
            elif start_year <= yr <= end_year:
                post_vals.append(val)
        if len(pre_vals) == 0 or len(post_vals) == 0:
            continue
        pre_avg = sum(pre_vals) / len(pre_vals)
        post_avg = sum(post_vals) / len(post_vals)
        diff = post_avg - pre_avg
        gval = group_by_values.get(state, "")
        result = {
            "state": state,
            "pre_avg": pre_avg,
            "post_avg": post_avg,
            "diff": diff,
            "has_quarantine_clause": gval,
        }
        per_state_results.append(result)

    group_map: Dict[str, List[Dict[str, object]]] = {}
    for r in per_state_results:
        gval = group_by_values.get(r["state"], "")
        group_key = str(gval)
        group_map.setdefault(group_key, []).append(r)

    group_summary: Dict[str, Dict[str, object]] = {}
    for gkey, items in group_map.items():
        if len(items) == 0:
            continue
        n_states = len(items)
        mean_post = sum([float(item["post_avg"]) for item in items]) / n_states
        mean_diff = sum([float(item["diff"]) for item in items]) / n_states
        group_summary[gkey] = {
            "group_value": gkey,
            "n_states": n_states,
            "mean_post_avg": mean_post,
            "mean_diff": mean_diff,
        }

    return per_state_results, group_summary


def read_csv_header_and_rows(path: Path, delimiter: str = ",") -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            header = reader.fieldnames
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def count_bullets_and_keywords(text: str, keywords: List[str]) -> int:
    count = 0
    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith(("- ", "* ")):
            if any(k.lower() in line_stripped.lower() for k in keywords):
                count += 1
    return count


def contains_any(text: str, patterns: List[str]) -> bool:
    lower = text.lower()
    return any(p.lower() in lower for p in patterns)


def find_numeric_mentions(text: str, numbers: List[float], decimals: int = 2) -> int:
    rounded_strs = [f"{n:.{decimals}f}" for n in numbers]
    lower = text.lower()
    count = 0
    for rs in rounded_strs:
        if rs in lower:
            count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "pre_tree_snapshot": 0.0,
        "datasets_overview_structure": 0.0,
        "datasets_overview_provisions_row": 0.0,
        "datasets_overview_mortality_row": 0.0,
        "config_edited_values": 0.0,
        "config_outcome_and_smooth_preserved": 0.0,
        "state_level_changes_structure": 0.0,
        "state_level_changes_content": 0.0,
        "summary_by_clause_structure": 0.0,
        "summary_by_clause_content": 0.0,
        "run_config_json_matches": 0.0,
        "post_tree_snapshot": 0.0,
        "notes_exists": 0.0,
        "notes_context_blurb": 0.0,
        "notes_bulleted_summary": 0.0,
        "notes_action_items": 0.0,
        "notes_lists_inputs": 0.0,
        "notes_mentions_exclusion": 0.0,
    }

    # 1) Pre-analysis tree snapshot
    pre_tree_path = workspace / "outputs" / "inspection" / "pre_analysis_tree.txt"
    pre_tree_text = safe_read_text(pre_tree_path)
    if pre_tree_text is not None and len(pre_tree_text.strip()) > 0:
        norm = pre_tree_text.replace("\\", "/")
        if "data/public_health_provisions.csv" in norm and "data/smallpox_mortality.tsv" in norm:
            scores["pre_tree_snapshot"] = 1.0

    # 1) Dataset overview structure and content
    datasets_overview_path = workspace / "outputs" / "inspection" / "datasets_overview.csv"
    header, rows = read_csv_header_and_rows(datasets_overview_path, delimiter=",")
    expected_columns = ["file_path", "rows", "columns", "unique_states"]
    if header is not None and rows is not None and [h.strip() for h in header] == expected_columns:
        if len(rows) == 2:
            scores["datasets_overview_structure"] = 1.0
        computed_overview = compute_dataset_overview(workspace)
        if computed_overview is not None:
            rows_by_fp = {r.get("file_path", ""): r for r in rows}
            prov_fp = "data/public_health_provisions.csv"
            if prov_fp in rows_by_fp and prov_fp in computed_overview:
                r = rows_by_fp[prov_fp]
                try:
                    r_rows = int(str(r.get("rows", "")).strip())
                    r_cols = int(str(r.get("columns", "")).strip())
                    r_ust = int(str(r.get("unique_states", "")).strip())
                    exp = computed_overview[prov_fp]
                    if r_rows == exp["rows"] and r_cols == exp["columns"] and r_ust == exp["unique_states"]:
                        scores["datasets_overview_provisions_row"] = 1.0
                except Exception:
                    pass
            mort_fp = "data/smallpox_mortality.tsv"
            if mort_fp in rows_by_fp and mort_fp in computed_overview:
                r = rows_by_fp[mort_fp]
                try:
                    r_rows = int(str(r.get("rows", "")).strip())
                    r_cols = int(str(r.get("columns", "")).strip())
                    r_ust = int(str(r.get("unique_states", "")).strip())
                    exp = computed_overview[mort_fp]
                    if r_rows == exp["rows"] and r_cols == exp["columns"] and r_ust == exp["unique_states"]:
                        scores["datasets_overview_mortality_row"] = 1.0
                except Exception:
                    pass

    # 2) Config edits
    config_path = workspace / "config" / "analysis.yaml"
    cfg = simple_yaml_parse(config_path)
    if cfg is not None:
        start_ok = cfg.get("start_year") == 1795
        end_ok = cfg.get("end_year") == 1805
        group_ok = str(cfg.get("group_by_clause", "")).strip() == "has_quarantine_clause"
        if start_ok and end_ok and group_ok:
            scores["config_edited_values"] = 1.0

        # Only award preservation if edits were made (to avoid scoring in scaffold state)
        if scores["config_edited_values"] > 0.0:
            om_ok = str(cfg.get("outcome_metric", "")).strip() == "smallpox_deaths_per_100k"
            sw_val = cfg.get("smooth_window", None)
            sw_ok = False
            try:
                sw_ok = int(str(sw_val).strip()) == 1
            except Exception:
                sw_ok = False
            if om_ok and sw_ok:
                scores["config_outcome_and_smooth_preserved"] = 1.0

    # Prepare expected computations only if config edits are correct
    expected_per_state: Optional[List[Dict[str, object]]] = None
    expected_group_summary: Optional[Dict[str, Dict[str, object]]] = None
    if scores["config_edited_values"] > 0.0:
        res = recompute_expected_changes(
            workspace,
            start_year=1795,
            end_year=1805,
            group_by_clause="has_quarantine_clause",
            outcome_metric="smallpox_deaths_per_100k",
        )
        if res is not None:
            expected_per_state, expected_group_summary = res

    # 3) Per-state results
    slc_path = workspace / "outputs" / "state_level_changes.csv"
    slc_header, slc_rows = read_csv_header_and_rows(slc_path, delimiter=",")
    expected_slc_columns = ["state", "pre_avg", "post_avg", "diff", "has_quarantine_clause"]
    if slc_header is not None and [h.strip() for h in slc_header] == expected_slc_columns and slc_rows is not None:
        scores["state_level_changes_structure"] = 1.0
        if expected_per_state is not None:
            exp_by_state = {r["state"]: r for r in expected_per_state}
            expected_states_set = set(exp_by_state.keys())
            found_states_set = set([r.get("state", "") for r in slc_rows])
            set_match = expected_states_set == found_states_set
            values_match = True
            for r in slc_rows:
                st = r.get("state", "")
                if st not in exp_by_state:
                    values_match = False
                    break
                exp = exp_by_state[st]
                pav = parse_float_safe(r.get("pre_avg", ""))
                pov = parse_float_safe(r.get("post_avg", ""))
                dv = parse_float_safe(r.get("diff", ""))
                if pav is None or pov is None or dv is None:
                    values_match = False
                    break
                if not (approx_equal(pav, exp["pre_avg"]) and approx_equal(pov, exp["post_avg"]) and approx_equal(dv, exp["diff"])):
                    values_match = False
                    break
                gval = r.get("has_quarantine_clause", "")
                if str(gval) not in ["True", "False"]:
                    values_match = False
                    break
                exp_gval = exp["has_quarantine_clause"]
                if str(gval) != str(exp_gval):
                    values_match = False
                    break
            if set_match and values_match:
                scores["state_level_changes_content"] = 1.0

    # 3) Group-level summaries
    sbc_path = workspace / "outputs" / "summary_by_clause.csv"
    sbc_header, sbc_rows = read_csv_header_and_rows(sbc_path, delimiter=",")
    expected_sbc_columns = ["group_value", "n_states", "mean_post_avg", "mean_diff"]
    if sbc_header is not None and [h.strip() for h in sbc_header] == expected_sbc_columns and sbc_rows is not None:
        scores["summary_by_clause_structure"] = 1.0
        if expected_group_summary is not None:
            seen = {r.get("group_value", "") for r in sbc_rows}
            has_true_false = ("True" in seen) and ("False" in seen)
            content_ok = True
            counts_ok = (len(sbc_rows) == 2)
            for r in sbc_rows:
                gv = r.get("group_value", "")
                if gv not in expected_group_summary:
                    content_ok = False
                    break
                try:
                    n_states = int(str(r.get("n_states", "")).strip())
                except Exception:
                    content_ok = False
                    break
                mp = parse_float_safe(r.get("mean_post_avg", ""))
                md = parse_float_safe(r.get("mean_diff", ""))
                if mp is None or md is None:
                    content_ok = False
                    break
                exp = expected_group_summary[gv]
                if n_states != int(exp["n_states"]):
                    content_ok = False
                    break
                if not (approx_equal(mp, exp["mean_post_avg"]) and approx_equal(md, exp["mean_diff"])):
                    content_ok = False
                    break
            if has_true_false and counts_ok and content_ok:
                scores["summary_by_clause_content"] = 1.0

    # 3) Run configuration saved
    run_config_path = workspace / "outputs" / "metadata" / "run_config.json"
    run_cfg = safe_load_json(run_config_path)
    if run_cfg is not None:
        try:
            rc_start = int(run_cfg.get("start_year"))
            rc_end = int(run_cfg.get("end_year"))
            rc_group = str(run_cfg.get("group_by_clause"))
            rc_outcome = str(run_cfg.get("outcome_metric"))
            conds = [
                rc_start == 1795,
                rc_end == 1805,
                rc_group == "has_quarantine_clause",
                rc_outcome == "smallpox_deaths_per_100k",
            ]
            if all(conds):
                scores["run_config_json_matches"] = 1.0
        except Exception:
            pass

    # 4) Post-analysis tree snapshot
    post_tree_path = workspace / "outputs" / "inspection" / "post_analysis_tree.txt"
    post_tree_text = safe_read_text(post_tree_path)
    if post_tree_text is not None and len(post_tree_text.strip()) > 0:
        norm_post = post_tree_text.replace("\\", "/")
        if (
            "outputs/state_level_changes.csv" in norm_post
            and "outputs/summary_by_clause.csv" in norm_post
            and "outputs/metadata/run_config.json" in norm_post
        ):
            scores["post_tree_snapshot"] = 1.0

    # 5) Meeting notes checks
    notes_path = workspace / "outputs" / "notes" / "meeting_notes.md"
    notes_text = safe_read_text(notes_path)
    if notes_text is not None and len(notes_text.strip()) > 0:
        scores["notes_exists"] = 1.0

        # Context blurb: at least 2 sentences and mentions constitution, public health, and quarantine/police powers
        paragraphs = [p.strip() for p in notes_text.split("\n\n") if p.strip()]
        context_ok = False
        if paragraphs:
            first_para = paragraphs[0]
            temp = first_para.replace("!", ".").replace("?", ".")
            sentences = [s.strip() for s in temp.split(".") if s.strip()]
            if len(sentences) >= 2:
                mentions_constitution = contains_any(first_para, ["constitution", "constitutional"])
                mentions_public_health = contains_any(first_para, ["public health"])
                mentions_quarantine_or_police = contains_any(first_para, ["quarantine", "police power", "police powers"])
                if mentions_constitution and mentions_public_health and mentions_quarantine_or_police:
                    context_ok = True
        if context_ok:
            scores["notes_context_blurb"] = 1.0

        # Bulleted summary: must reference 1795–1805, compare groups, and include numeric references or file references
        bullet_lines = [ln.strip() for ln in notes_text.splitlines() if ln.strip().startswith(("- ", "* "))]
        summary_ok = False
        if bullet_lines:
            has_period = contains_any(notes_text, ["1795–1805", "1795-1805"])
            has_compare = (contains_any(notes_text, ["with"]) and contains_any(notes_text, ["without"])) or contains_any(notes_text, ["True"]) or contains_any(notes_text, ["False"])
            numeric_refs_ok = False
            # Use expected group summary if available to check numeric references
            if expected_group_summary is not None:
                nums = []
                for gv in ["True", "False"]:
                    if gv in expected_group_summary:
                        nums.append(float(expected_group_summary[gv]["mean_post_avg"]))
                        nums.append(float(expected_group_summary[gv]["mean_diff"]))
                if find_numeric_mentions(notes_text.lower(), nums, decimals=2) >= 2:
                    numeric_refs_ok = True
            references_files = contains_any(notes_text, ["outputs/summary_by_clause.csv", "outputs/state_level_changes.csv"])
            if has_period and has_compare and (numeric_refs_ok or references_files):
                summary_ok = True
        if summary_ok:
            scores["notes_bulleted_summary"] = 1.0

        # Action items: at least 3 bullets with keywords
        action_count = count_bullets_and_keywords(notes_text, ["verify", "confirm", "identify", "check", "review"])
        if action_count >= 3:
            scores["notes_action_items"] = 1.0

        # Lists input files used
        if (
            "data/public_health_provisions.csv" in notes_text
            and "data/smallpox_mortality.tsv" in notes_text
            and "config/analysis.yaml" in notes_text
        ):
            scores["notes_lists_inputs"] = 1.0

        # Mentions exclusion due to missing periods
        if contains_any(notes_text, ["exclude", "excluded"]):
            scores["notes_mentions_exclusion"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()