import csv
import json
import math;
import re
import sys
import ast
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            header = reader.fieldnames if reader.fieldnames is not None else []
            return rows, header
    except Exception:
        return None, None


def _parse_yaml_config(path: Path) -> Optional[Dict]:
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    interval_bounds = None
    categories: List[Dict] = []
    in_categories = False
    current: Optional[Dict] = None
    for raw in lines:
        line = raw.rstrip()
        # Remove inline comments
        if "#" in line:
            line = line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        m_bounds = re.match(r"^\s*interval_bounds\s*:\s*([^\s#]+)\s*$", line)
        if m_bounds:
            interval_bounds = m_bounds.group(1).strip().strip("'\"")
            continue
        if re.match(r"^\s*categories\s*:\s*$", line):
            in_categories = True
            continue
        if in_categories:
            m_name = re.match(r"^\s*-\s*name\s*:\s*(.+?)\s*$", line)
            if m_name:
                if current:
                    categories.append(current)
                current = {"name": m_name.group(1).strip().strip("'\"")}
                continue
            if current is None:
                continue
            m_min = re.match(r"^\s*min\s*:\s*([0-9.]+)\s*$", line)
            if m_min:
                try:
                    current["min"] = float(m_min.group(1))
                except Exception:
                    return None
                continue
            m_max = re.match(r"^\s*max\s*:\s*([0-9.]+)\s*$", line)
            if m_max:
                try:
                    current["max"] = float(m_max.group(1))
                except Exception:
                    return None
                continue
            m_score = re.match(r"^\s*score\s*:\s*([0-9]+)\s*$", line)
            if m_score:
                try:
                    current["score"] = int(m_score.group(1))
                except Exception:
                    return None
                continue
    if current:
        categories.append(current)
    if interval_bounds is None or not categories:
        return None
    for c in categories:
        if not all(k in c for k in ("name", "min", "max", "score")):
            return None
    return {"interval_bounds": interval_bounds, "categories": categories}


def _parse_alert_constants(path: Path) -> Optional[Dict]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        tree = ast.parse(text, filename=str(path))
        thresholds = None
        interval_bounds = None
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "THRESHOLDS":
                        thresholds = ast.literal_eval(node.value)
                    if isinstance(t, ast.Name) and t.id == "INTERVAL_BOUNDS":
                        interval_bounds = ast.literal_eval(node.value)
        if thresholds is None or interval_bounds is None:
            return None
        norm = []
        for item in thresholds:
            try:
                norm.append({
                    "name": str(item["name"]),
                    "min": float(item["min"]),
                    "max": float(item["max"]),
                    "score": int(item["score"]),
                })
            except Exception:
                return None
        return {"THRESHOLDS": norm, "INTERVAL_BOUNDS": str(interval_bounds)}
    except Exception:
        return None


def _compare_config_vs_constants(yaml_conf: Dict, py_conf: Dict) -> List[str]:
    diffs: List[str] = []
    if yaml_conf is None or py_conf is None:
        diffs.append("uncomparable: missing config or constants")
        return diffs
    y_bounds = str(yaml_conf.get("interval_bounds", "")).strip()
    p_bounds = str(py_conf.get("INTERVAL_BOUNDS", "")).strip()
    if y_bounds != p_bounds:
        diffs.append(f"interval_bounds mismatch: yaml='{y_bounds}', python='{p_bounds}'")
    y_cats = yaml_conf.get("categories", [])
    p_cats = py_conf.get("THRESHOLDS", [])
    if len(y_cats) != len(p_cats):
        diffs.append(f"category_count mismatch: yaml={len(y_cats)}, python={len(p_cats)}")
    n = min(len(y_cats), len(p_cats))
    for i in range(n):
        yc = y_cats[i]
        pc = p_cats[i]
        if yc["name"] != pc["name"]:
            diffs.append(f"category[{i}] name mismatch: yaml='{yc['name']}', python='{pc['name']}'")
        if not math.isclose(float(yc["min"]), float(pc["min"]), rel_tol=0.0, abs_tol=1e-9):
            diffs.append(f"category[{i}] min mismatch: yaml={yc['min']}, python={pc['min']}")
        if not math.isclose(float(yc["max"]), float(pc["max"]), rel_tol=0.0, abs_tol=1e-9):
            diffs.append(f"category[{i}] max mismatch: yaml={yc['max']}, python={pc['max']}")
        if int(yc["score"]) != int(pc["score"]):
            diffs.append(f"category[{i}] score mismatch: yaml={yc['score']}, python={pc['score']}")
    y_names = [c["name"] for c in y_cats]
    p_names = [c["name"] for c in p_cats]
    if y_names != p_names:
        diffs.append(f"ordering mismatch: yaml_order={y_names}, python_order={p_names}")
    return diffs


def _classify_value(val: float, categories: List[Dict], bounds: str) -> Optional[Tuple[str, int]]:
    # Closed intervals as per task
    for c in categories:
        if val >= float(c["min"]) - 1e-12 and val <= float(c["max"]) + 1e-12:
            return c["name"], int(c["score"])
    return None


def _compute_expected_classified(readings: List[Dict[str, str]], yaml_conf: Dict) -> Optional[List[Dict[str, str]]]:
    try:
        cats = yaml_conf["categories"]
        bounds = yaml_conf["interval_bounds"]
    except Exception:
        return None
    out = []
    for r in readings:
        try:
            site = r["site_id"]
            date = r["date"]
            pm = float(r["pm25_ugm3"])
        except Exception:
            return None
        cls = _classify_value(pm, cats, bounds)
        if cls is None:
            return None
        category, score = cls
        out.append({
            "site_id": site,
            "date": date,
            "pm25_ugm3": pm,
            "category": category,
            "severity_score": score,
        })
    out.sort(key=lambda x: (x["site_id"], x["date"]))
    return out


def _round3(x: float) -> str:
    return f"{round(x + 1e-12, 3):.3f}"


def _compute_rankings(expected_classified: List[Dict[str, str]]) -> Optional[List[Dict[str, str]]]:
    if expected_classified is None:
        return None
    site_scores: Dict[str, List[int]] = {}
    site_max_category: Dict[str, Tuple[int, str]] = {}
    for row in expected_classified:
        site = row["site_id"]
        score = int(row["severity_score"])
        cat = row["category"]
        site_scores.setdefault(site, []).append(score)
        if site not in site_max_category or score > site_max_category[site][0]:
            site_max_category[site] = (score, cat)
    items = []
    for site, scores in site_scores.items():
        mean = sum(scores) / float(len(scores)) if scores else 0.0
        max_cat = site_max_category.get(site, (None, None))[1]
        items.append((site, mean, max_cat))
    items.sort(key=lambda t: (-t[1], t[0]))
    rankings = []
    rank = 1
    for site, mean, max_cat in items:
        rankings.append({
            "site_id": site,
            "mean_severity_score": _round3(mean),
            "highest_category_observed": max_cat,
            "rank": str(rank),
        })
        rank += 1
    return rankings


def _float_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _contains_line_with_tokens(text: str, tokens: List[str]) -> bool:
    for line in text.splitlines():
        if all(tok.lower() in line.lower() for tok in tokens):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "classified_readings_structure": 0.0,
        "classified_readings_content": 0.0,
        "site_rankings_structure": 0.0,
        "site_rankings_content": 0.0,
        "notifications_structure": 0.0,
        "notifications_constraints": 0.0,
        "status_summary_exists": 0.0,
        "status_summary_config_consistency": 0.0,
        "status_summary_category_counts": 0.0,
        "status_summary_ranked_list_top3": 0.0,
        "status_summary_update_mentions": 0.0,
    }

    pm_csv_path = workspace / "input" / "pm25_readings.csv"
    yaml_path = workspace / "input" / "severity_config.yaml"
    py_consts_path = workspace / "input" / "alert_constants.py"
    drafts_path = workspace / "input" / "notification_drafts.csv"

    pm_rows, pm_header = _load_csv(pm_csv_path)
    yaml_conf = _parse_yaml_config(yaml_path)
    py_conf = _parse_alert_constants(py_consts_path)
    drafts_rows, drafts_header = _load_csv(drafts_path)

    expected_classified = None
    expected_rankings = None
    category_counts = None
    diffs: List[str] = []
    if yaml_conf is not None:
        diffs = _compare_config_vs_constants(yaml_conf, py_conf if py_conf is not None else {"THRESHOLDS": [], "INTERVAL_BOUNDS": ""})
    if pm_rows is not None and yaml_conf is not None:
        expected_classified = _compute_expected_classified(pm_rows, yaml_conf)
        if expected_classified is not None:
            counts: Dict[str, int] = {}
            for row in expected_classified:
                counts[row["category"]] = counts.get(row["category"], 0) + 1
            category_counts = counts
            expected_rankings = _compute_rankings(expected_classified)

    cls_path = workspace / "output" / "classified_readings.csv"
    cls_rows, cls_header = _load_csv(cls_path)
    expected_header_cls = ["site_id", "date", "pm25_ugm3", "category", "severity_score"]
    if cls_rows is not None and cls_header == expected_header_cls:
        is_sorted = True
        for i in range(1, len(cls_rows)):
            a = (cls_rows[i - 1].get("site_id", ""), cls_rows[i - 1].get("date", ""))
            b = (cls_rows[i].get("site_id", ""), cls_rows[i].get("date", ""))
            if a > b:
                is_sorted = False
                break
        if is_sorted and pm_rows is not None and len(cls_rows) == len(pm_rows):
            scores["classified_readings_structure"] = 1.0
        else:
            scores["classified_readings_structure"] = 0.0
    else:
        scores["classified_readings_structure"] = 0.0

    if expected_classified is not None and cls_rows is not None and cls_header == expected_header_cls and len(cls_rows) == len(expected_classified):
        ok = True
        exp = expected_classified
        for row, erow in zip(cls_rows, exp):
            try:
                if row["site_id"] != erow["site_id"]:
                    ok = False
                    break
                if row["date"] != erow["date"]:
                    ok = False
                    break
                pm_out = float(row["pm25_ugm3"])
                if not _float_equal(pm_out, float(erow["pm25_ugm3"])):
                    ok = False
                    break
                if row["category"] != erow["category"]:
                    ok = False
                    break
                if int(row["severity_score"]) != int(erow["severity_score"]):
                    ok = False
                    break
            except Exception:
                ok = False
                break
        scores["classified_readings_content"] = 1.0 if ok else 0.0
    else:
        scores["classified_readings_content"] = 0.0

    ranking_path = workspace / "output" / "site_rankings.csv"
    rank_rows, rank_header = _load_csv(ranking_path)
    expected_rank_header = ["site_id", "mean_severity_score", "highest_category_observed", "rank"]
    if rank_rows is not None and rank_header == expected_rank_header:
        try:
            ranks = [int(r["rank"]) for r in rank_rows]
            is_sorted_rank = all(ranks[i] <= ranks[i + 1] for i in range(len(ranks) - 1))
            sequential = ranks == list(range(1, len(ranks) + 1))
            if expected_classified is not None:
                sites = sorted(set(r["site_id"] for r in expected_classified))
                correct_count = len(rank_rows) == len(sites)
            else:
                correct_count = True
            if is_sorted_rank and sequential and correct_count:
                scores["site_rankings_structure"] = 1.0
            else:
                scores["site_rankings_structure"] = 0.0
        except Exception:
            scores["site_rankings_structure"] = 0.0
    else:
        scores["site_rankings_structure"] = 0.0

    if expected_rankings is not None and rank_rows is not None and rank_header == expected_rank_header and len(rank_rows) == len(expected_rankings):
        ok = True
        try:
            exp_sorted = sorted(expected_rankings, key=lambda r: int(r["rank"]))
            got_sorted = sorted(rank_rows, key=lambda r: int(r["rank"]))
        except Exception:
            exp_sorted = expected_rankings
            got_sorted = rank_rows
        for gr, er in zip(got_sorted, exp_sorted):
            try:
                if gr["site_id"] != er["site_id"]:
                    ok = False
                    break
                if gr["mean_severity_score"] != er["mean_severity_score"]:
                    ok = False
                    break
                if gr["highest_category_observed"] != er["highest_category_observed"]:
                    ok = False
                    break
                if int(gr["rank"]) != int(er["rank"]):
                    ok = False
                    break
            except Exception:
                ok = False
                break
        scores["site_rankings_content"] = 1.0 if ok else 0.0
    else:
        scores["site_rankings_content"] = 0.0

    notif_path = workspace / "output" / "notifications_rewritten.csv"
    notif_rows, notif_header = _load_csv(notif_path)
    expected_notif_header = ["site_id", "original_chars", "rewritten_message"]
    if notif_rows is not None and notif_header == expected_notif_header:
        if drafts_rows is not None:
            draft_sites = [r["site_id"] for r in drafts_rows]
            output_sites = [r["site_id"] for r in notif_rows]
            structure_ok = sorted(draft_sites) == sorted(output_sites)
        else:
            structure_ok = len(notif_rows) > 0
        orig_ok = True
        if drafts_rows is not None:
            by_site_draft = {r["site_id"]: r["draft_message"] for r in drafts_rows}
            for r in notif_rows:
                try:
                    s = r["site_id"]
                    if s not in by_site_draft:
                        orig_ok = False
                        break
                    expected_len = len(by_site_draft[s])
                    if int(r["original_chars"]) != expected_len:
                        orig_ok = False
                        break
                except Exception:
                    orig_ok = False
                    break
        if structure_ok and orig_ok:
            scores["notifications_structure"] = 1.0
        else:
            scores["notifications_structure"] = 0.0
    else:
        scores["notifications_structure"] = 0.0

    if notif_rows is not None and expected_rankings is not None:
        site_to_highest = {r["site_id"]: r["highest_category_observed"] for r in expected_rankings}
        all_ok = True
        for r in notif_rows:
            try:
                site = r["site_id"]
                msg = r["rewritten_message"]
                if msg is None:
                    all_ok = False
                    break
                if len(msg) > 240:
                    all_ok = False
                    break
                if site not in msg:
                    all_ok = False
                    break
                hcat = site_to_highest.get(site)
                if hcat is None or hcat not in msg:
                    all_ok = False
                    break
                if "!" in msg:
                    all_ok = False
                    break
            except Exception:
                all_ok = False
                break
        scores["notifications_constraints"] = 1.0 if all_ok else 0.0
    else:
        scores["notifications_constraints"] = 0.0

    status_path = workspace / "output" / "status_summary.md"
    status_text = _read_text(status_path)
    if status_text is not None:
        scores["status_summary_exists"] = 1.0
    else:
        scores["status_summary_exists"] = 0.0

    if status_text is not None:
        lower = status_text.lower()
        has_consistency = ("consistency" in lower) or ("consistent" in lower)
        cfg_ok = False
        if diffs is not None:
            if len(diffs) == 0:
                if has_consistency and (("no mismatch" in lower) or ("no mismatches" in lower) or ("none" in lower)):
                    cfg_ok = True
            else:
                mentioned = False
                for d in diffs:
                    tokens = []
                    if "interval_bounds" in d:
                        tokens.append("interval_bounds")
                    if "category[" in d:
                        tokens.append("category")
                    m = re.findall(r"'([^']+)'", d)
                    for t in m:
                        if t and len(t) > 2:
                            tokens.append(t)
                    for t in tokens:
                        if t.lower() in lower:
                            mentioned = True
                            break
                    if mentioned:
                        break
                if has_consistency and mentioned:
                    cfg_ok = True
        scores["status_summary_config_consistency"] = 1.0 if cfg_ok else 0.0
    else:
        scores["status_summary_config_consistency"] = 0.0

    if status_text is not None and category_counts is not None and yaml_conf is not None:
        counts_ok = True
        for cat in yaml_conf["categories"]:
            name = cat["name"]
            cnt = category_counts.get(name, 0)
            if not _contains_line_with_tokens(status_text, [name, str(cnt)]):
                counts_ok = False
                break
        scores["status_summary_category_counts"] = 1.0 if counts_ok else 0.0
    else:
        scores["status_summary_category_counts"] = 0.0

    if status_text is not None and expected_rankings is not None:
        top3 = expected_rankings[:3]
        top_ok = True
        for entry in top3:
            sid = entry["site_id"]
            mean_str = entry["mean_severity_score"]
            if not _contains_line_with_tokens(status_text, [sid, mean_str]):
                top_ok = False
                break
        scores["status_summary_ranked_list_top3"] = 1.0 if top_ok else 0.0
    else:
        scores["status_summary_ranked_list_top3"] = 0.0

    if status_text is not None:
        lower = status_text.lower()
        has_pm = ("pm2.5" in lower) or ("pm 2.5" in lower) or ("pm25" in lower)
        has_bounds = "closed" in lower
        has_ties = ("tie" in lower) and ("alphabet" in lower)
        has_notable = ("notable" in lower) or ("finding" in lower) or ("observed" in lower)
        update_ok = has_pm and has_bounds and has_ties and has_notable
        scores["status_summary_update_mentions"] = 1.0 if update_ok else 0.0
    else:
        scores["status_summary_update_mentions"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()