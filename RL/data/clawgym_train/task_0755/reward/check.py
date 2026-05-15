import json
import sys
import csv
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def parse_simple_yaml(text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key in ["challenge_weight", "photoshoot_weight", "vote_weight"]:
        m = re.search(rf"^{key}:\s*([0-9]*\.?[0-9]+)\s*$", text, re.MULTILINE)
        if m:
            try:
                result[key] = float(m.group(1))
            except Exception:
                pass
    m = re.search(r"^episodes_include:\s*\[([^\]]*)\]\s*$", text, re.MULTILINE)
    if m:
        inner = m.group(1).strip()
        if inner:
            parts = [p.strip() for p in inner.split(",")]
            vals: List[int] = []
            for p in parts:
                try:
                    vals.append(int(p))
                except Exception:
                    pass
            result["episodes_include"] = vals
        else:
            result["episodes_include"] = []
    return result


def safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "" or s.lower() == "nan" or s.lower() == "none":
            return None
        return float(s)
    except Exception:
        return None


def safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        if isinstance(x, int):
            return x
        s = str(x).strip()
        if s == "" or s.lower() == "nan" or s.lower() == "none":
            return None
        return int(s)
    except Exception:
        return None


def mean_std(values: List[float], ddof: int) -> Tuple[float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    var_num = sum((v - mean) ** 2 for v in values)
    denom = max(1, n - ddof)
    var = var_num / denom if denom > 0 else 0.0
    std = math.sqrt(var)
    return mean, std


def compute_expected_outputs(
    episodes_rows: List[Dict[str, str]],
    contestants_rows: List[Dict[str, str]],
    episodes_include: List[int],
    weights: Tuple[float, float, float],
    ddof_z: int,
    ddof_consistency: int,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[int, Dict[str, Any]]]:
    eps_set = set(episodes_include)
    rows = []
    for r in episodes_rows:
        ep = safe_int(r.get("episode"))
        if ep is None or ep not in eps_set:
            continue
        try:
            rows.append({
                "episode": ep,
                "contestant": r.get("contestant", "").strip(),
                "challenge_score": float(r.get("challenge_score")),
                "photoshoot_score": float(r.get("photoshoot_score")),
                "public_vote": float(r.get("public_vote")),
                "eliminated": int(r.get("eliminated")),
            })
        except Exception:
            continue

    by_episode: Dict[int, List[Dict[str, Any]]] = {}
    for rec in rows:
        by_episode.setdefault(rec["episode"], []).append(rec)

    w_chal, w_photo, w_vote = weights
    per_episode_index: Dict[int, List[Tuple[str, float]]] = {}
    per_contestant_index: Dict[str, List[Tuple[int, float]]] = {}
    for ep, recs in by_episode.items():
        chal_vals = [r["challenge_score"] for r in recs]
        pho_vals = [r["photoshoot_score"] for r in recs]
        vote_vals = [r["public_vote"] for r in recs]
        m_c, s_c = mean_std(chal_vals, ddof_z)
        m_p, s_p = mean_std(pho_vals, ddof_z)
        m_v, s_v = mean_std(vote_vals, ddof_z)
        indexes = []
        for r in recs:
            z_c = (r["challenge_score"] - m_c) / s_c if s_c > 0 else 0.0
            z_p = (r["photoshoot_score"] - m_p) / s_p if s_p > 0 else 0.0
            z_v = (r["public_vote"] - m_v) / s_v if s_v > 0 else 0.0
            w_idx = w_chal * z_c + w_photo * z_p + w_vote * z_v
            indexes.append((r["contestant"], w_idx))
            per_contestant_index.setdefault(r["contestant"], []).append((ep, w_idx))
        per_episode_index[ep] = indexes

    episode_trends_expected: Dict[int, Dict[str, Any]] = {}
    for ep in sorted(by_episode.keys()):
        idxs = [idx for (_name, idx) in per_episode_index.get(ep, [])]
        m, s = mean_std(idxs, ddof_consistency)
        bottom_sorted = sorted(per_episode_index.get(ep, []), key=lambda x: x[1])
        bottom3_names = [name for name, _ in bottom_sorted[:3]]
        episode_trends_expected[ep] = {
            "episode": ep,
            "episode_mean_index": m,
            "episode_std_index": s,
            "bottom3": bottom3_names,
        }

    cycle_map: Dict[str, Any] = {}
    for r in contestants_rows:
        name = (r.get("contestant") or "").strip()
        cycle_map[name] = r.get("cycle")

    contestant_summary_expected: Dict[str, Dict[str, Any]] = {}
    contestant_names = set(cycle_map.keys())
    for name in contestant_names:
        idxs = [idx for (ep, idx) in per_contestant_index.get(name, [])]
        count = len(idxs)
        avg_index = sum(idxs) / count if count > 0 else 0.0
        _, cons_std = mean_std(idxs, ddof_consistency)
        elim_ep = None
        rel_rows = [r for r in rows if r["contestant"] == name]
        rel_rows_sorted = sorted(rel_rows, key=lambda r: r["episode"])
        for r in rel_rows_sorted:
            if r["eliminated"] == 1:
                elim_ep = r["episode"]
                break
        eliminated_in = elim_ep if elim_ep is not None else ""
        contestant_summary_expected[name] = {
            "contestant": name,
            "cycle": cycle_map.get(name),
            "episodes_count": count,
            "avg_index": avg_index,
            "consistency_score": cons_std,
            "eliminated_in": eliminated_in,
        }

    return contestant_summary_expected, episode_trends_expected


def nearly_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def compare_contestant_summary(
    actual_rows: List[Dict[str, str]],
    expected_variants: List[Dict[str, Dict[str, Any]]]
) -> bool:
    required_cols = ["contestant", "cycle", "episodes_count", "avg_index", "consistency_score", "eliminated_in"]
    actual_fieldnames = set(actual_rows[0].keys()) if actual_rows else set()
    if set(required_cols) != actual_fieldnames:
        return False

    actual_by_name: Dict[str, Dict[str, Any]] = {}
    for r in actual_rows:
        name = (r.get("contestant") or "").strip()
        if not name:
            return False
        cyc = r.get("cycle")
        ep_count = safe_int(r.get("episodes_count"))
        avg_idx = safe_float(r.get("avg_index"))
        cons = safe_float(r.get("consistency_score"))
        elim_raw = r.get("eliminated_in")
        elim_val = None
        if elim_raw is None:
            elim_val = ""
        else:
            elim_raw = str(elim_raw).strip()
            if elim_raw == "":
                elim_val = ""
            else:
                ev = safe_int(elim_raw)
                elim_val = ev if ev is not None else ""
        actual_by_name[name] = {
            "contestant": name,
            "cycle": cyc,
            "episodes_count": ep_count,
            "avg_index": avg_idx,
            "consistency_score": cons,
            "eliminated_in": elim_val,
        }

    for expected in expected_variants:
        if set(actual_by_name.keys()) != set(expected.keys()):
            continue
        all_ok = True
        for name, exp in expected.items():
            act = actual_by_name.get(name)
            if act is None:
                all_ok = False
                break
            if str(act["cycle"]).strip() != str(exp["cycle"]).strip():
                all_ok = False
                break
            if act["episodes_count"] != exp["episodes_count"]:
                all_ok = False
                break
            if act["avg_index"] is None or not nearly_equal(act["avg_index"], float(exp["avg_index"])):
                all_ok = False
                break
            if act["consistency_score"] is None or not nearly_equal(act["consistency_score"], float(exp["consistency_score"])):
                all_ok = False
                break
            exp_elim = exp["eliminated_in"]
            act_elim = act["eliminated_in"]
            if (exp_elim == "" and (act_elim == "" or act_elim is None)) or (exp_elim != "" and act_elim == exp_elim):
                pass
            else:
                all_ok = False
                break
        if all_ok:
            return True
    return False


def compare_episode_trends(
    actual: Any,
    episodes_include: List[int],
    expected_variants: List[Dict[int, Dict[str, Any]]]
) -> bool:
    if not isinstance(actual, list):
        return False
    try:
        actual_by_ep: Dict[int, Dict[str, Any]] = {}
        for item in actual:
            if not isinstance(item, dict):
                return False
            ep = safe_int(item.get("episode"))
            if ep is None:
                return False
            bottom3 = item.get("bottom3")
            if not isinstance(bottom3, list):
                return False
            if "episode_mean_index" not in item or "episode_std_index" not in item:
                return False
            actual_by_ep[ep] = {
                "episode_mean_index": safe_float(item.get("episode_mean_index")),
                "episode_std_index": safe_float(item.get("episode_std_index")),
                "bottom3": [str(x) for x in bottom3],
            }
    except Exception:
        return False

    if set(actual_by_ep.keys()) != set(episodes_include):
        return False

    for expected in expected_variants:
        if set(expected.keys()) != set(episodes_include):
            continue
        all_ok = True
        for ep in episodes_include:
            act = actual_by_ep.get(ep)
            exp = expected.get(ep)
            if act is None or exp is None:
                all_ok = False
                break
            if act["episode_mean_index"] is None or not nearly_equal(act["episode_mean_index"], float(exp["episode_mean_index"])):
                all_ok = False
                break
            if act["episode_std_index"] is None or not nearly_equal(act["episode_std_index"], float(exp["episode_std_index"])):
                all_ok = False
                break
            if list(act["bottom3"]) != list(exp["bottom3"]):
                all_ok = False
                break
        if all_ok:
            return True

    return False


def extract_top3_from_summary(summary_rows: List[Dict[str, str]]) -> Tuple[List[str], List[str]]:
    items = []
    for r in summary_rows:
        name = (r.get("contestant") or "").strip()
        avg_idx = safe_float(r.get("avg_index"))
        cons = safe_float(r.get("consistency_score"))
        if name and avg_idx is not None and cons is not None:
            items.append((name, avg_idx, cons))
    top_perf = sorted(items, key=lambda x: (-x[1], x[0]))[:3]
    top_perf_names = [x[0] for x in top_perf]
    most_cons = sorted(items, key=lambda x: (x[2], x[0]))[:3]
    most_cons_names = [x[0] for x in most_cons]
    return top_perf_names, most_cons_names


def contains_heading(text: str, heading: str) -> bool:
    pattern = re.compile(rf"\b{re.escape(heading)}\b", re.IGNORECASE)
    return bool(pattern.search(text))


def line_contains_episode_range(text: str, start_ep: int, end_ep: int) -> bool:
    for line in text.splitlines():
        if re.search(r"\bepisode", line, flags=re.IGNORECASE):
            has_start = re.search(rf"\b{start_ep}\b", line) is not None
            has_end = re.search(rf"\b{end_ep}\b", line) is not None
            if has_start and has_end:
                return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_weights_set": 0.0,
        "config_episodes_include_set": 0.0,
        "contestant_summary_exists_and_columns": 0.0,
        "contestant_summary_values_correct": 0.0,
        "episode_trends_exists_and_structure": 0.0,
        "episode_trends_values_correct": 0.0,
        "summary_report_exists": 0.0,
        "summary_report_top_performers_present": 0.0,
        "summary_report_most_consistent_present": 0.0,
        "summary_report_notes_include_weights_and_range": 0.0,
        "no_hardcoded_names_in_analyze_py": 0.0,
    }

    cfg_path = workspace / "config" / "analysis.yaml"
    episodes_path = workspace / "input" / "episodes.csv"
    contestants_path = workspace / "input" / "contestants.csv"
    summary_csv_path = workspace / "output" / "contestant_summary.csv"
    trends_json_path = workspace / "output" / "episode_trends.json"
    report_md_path = workspace / "output" / "summary_report.md"
    analyze_script_path = workspace / "scripts" / "analyze.py"

    cfg_text = read_text(cfg_path) or ""
    cfg_parsed = parse_simple_yaml(cfg_text) if cfg_text else {}
    cw = cfg_parsed.get("challenge_weight")
    pw = cfg_parsed.get("photoshoot_weight")
    vw = cfg_parsed.get("vote_weight")
    if cw == 0.3 and pw == 0.5 and vw == 0.2:
        scores["config_weights_set"] = 1.0
    epis = cfg_parsed.get("episodes_include")
    if isinstance(epis, list) and epis == [1, 2, 3, 4, 5, 6, 7, 8]:
        scores["config_episodes_include_set"] = 1.0

    episodes_rows = read_csv_dicts(episodes_path) or []
    contestants_rows = read_csv_dicts(contestants_path) or []

    expected_variants_summary: List[Dict[str, Dict[str, Any]]] = []
    expected_variants_trends: List[Dict[int, Dict[str, Any]]] = []
    if episodes_rows and contestants_rows:
        required_eps = [1, 2, 3, 4, 5, 6, 7, 8]
        weights = (0.3, 0.5, 0.2)
        exp_sum_A, exp_tr_A = compute_expected_outputs(
            episodes_rows, contestants_rows, required_eps, weights, ddof_z=1, ddof_consistency=1
        )
        expected_variants_summary.append(exp_sum_A)
        expected_variants_trends.append(exp_tr_A)
        exp_sum_B, exp_tr_B = compute_expected_outputs(
            episodes_rows, contestants_rows, required_eps, weights, ddof_z=0, ddof_consistency=0
        )
        expected_variants_summary.append(exp_sum_B)
        expected_variants_trends.append(exp_tr_B)

    summary_rows = read_csv_dicts(summary_csv_path)
    if summary_rows is not None and len(summary_rows) > 0:
        required_cols = ["contestant", "cycle", "episodes_count", "avg_index", "consistency_score", "eliminated_in"]
        header_cols = list(summary_rows[0].keys())
        if header_cols == required_cols:
            scores["contestant_summary_exists_and_columns"] = 1.0
        if expected_variants_summary:
            try:
                if compare_contestant_summary(summary_rows, expected_variants_summary):
                    scores["contestant_summary_values_correct"] = 1.0
            except Exception:
                pass

    trends = read_json(trends_json_path)
    if trends is not None:
        if isinstance(trends, list):
            try:
                present_eps = set()
                struct_ok = True
                for item in trends:
                    if not isinstance(item, dict):
                        struct_ok = False
                        break
                    if "episode" not in item or "episode_mean_index" not in item or "episode_std_index" not in item or "bottom3" not in item:
                        struct_ok = False
                        break
                    ep = safe_int(item.get("episode"))
                    if ep is None:
                        struct_ok = False
                        break
                    present_eps.add(ep)
                    if not isinstance(item.get("bottom3"), list):
                        struct_ok = False
                        break
                if struct_ok and present_eps == {1, 2, 3, 4, 5, 6, 7, 8}:
                    scores["episode_trends_exists_and_structure"] = 1.0
            except Exception:
                pass

        if expected_variants_trends:
            try:
                if compare_episode_trends(trends, [1, 2, 3, 4, 5, 6, 7, 8], expected_variants_trends):
                    scores["episode_trends_values_correct"] = 1.0
            except Exception:
                pass

    report_text = read_text(report_md_path)
    if report_text is not None and report_text.strip() != "":
        scores["summary_report_exists"] = 1.0
        if summary_rows:
            try:
                top3, most3 = extract_top3_from_summary(summary_rows)
                has_top_heading = contains_heading(report_text, "Top performers")
                has_cons_heading = contains_heading(report_text, "Most consistent")
                top_names_present = all(name in report_text for name in top3)
                cons_names_present = all(name in report_text for name in most3)
                if has_top_heading and top_names_present:
                    scores["summary_report_top_performers_present"] = 1.0
                if has_cons_heading and cons_names_present:
                    scores["summary_report_most_consistent_present"] = 1.0
            except Exception:
                pass
        has_weights = ("0.3" in report_text) and ("0.5" in report_text) and ("0.2" in report_text)
        has_range = line_contains_episode_range(report_text, 1, 8)
        if has_weights and has_range:
            scores["summary_report_notes_include_weights_and_range"] = 1.0

    # Gate the hardcoding check so it doesn't award points on the scaffold workspace.
    # Only evaluate if core deliverables exist and validate correctly.
    if scores["contestant_summary_values_correct"] == 1.0 and scores["episode_trends_values_correct"] == 1.0:
        analyze_text = read_text(analyze_script_path) or ""
        if analyze_text:
            hardcoded_names = ["Ala", "Beata", "Celina", "Dagmara", "Ewa"]
            hardcoded_eps = [str(e) for e in range(1, 13)]
            has_names = any(re.search(rf"\b{re.escape(n)}\b", analyze_text) for n in hardcoded_names)
            has_hardcoded_eps = any(re.search(rf"\b{re.escape(e)}\b", analyze_text) for e in hardcoded_eps)
            if not has_names and not has_hardcoded_eps:
                scores["no_hardcoded_names_in_analyze_py"] = 1.0

    return scores


def main() -> None:
    workspace_arg = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_arg)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()