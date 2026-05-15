import json
import sys
import csv
import math
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        if not path.exists():
            return None, f"missing:{path}"
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({(k.strip() if isinstance(k, str) else k): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows, None
    except Exception as e:
        return None, f"error:{e}"


def _safe_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None


def _float_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _format_rate_4(rate: float) -> str:
    return f"{rate:.4f}"


def _format_pct_1(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def _compute_expected(workspace: Path) -> Tuple[Optional[dict], Optional[str]]:
    campaigns_path = workspace / "input" / "newsletter_campaigns.csv"
    ann_path = workspace / "input" / "subject_annotations.csv"
    campaigns_rows, err1 = _read_csv(campaigns_path)
    ann_rows, err2 = _read_csv(ann_path)
    if campaigns_rows is None or ann_rows is None:
        return None, err1 or err2 or "missing inputs"

    ann_map: Dict[str, str] = {}
    for r in ann_rows:
        cid = r.get("campaign_id")
        tech = r.get("technique")
        if cid is None or tech is None:
            return None, "malformed annotations"
        ann_map[cid] = tech

    agg: Dict[str, Dict[str, float]] = {}
    total_delivered = 0
    total_opens = 0
    total_clicks = 0
    total_unsubs = 0
    campaign_count = 0

    for r in campaigns_rows:
        cid = r.get("campaign_id")
        if cid is None:
            return None, "malformed campaigns: missing campaign_id"
        if cid not in ann_map:
            continue
        sent = _safe_int(r.get("sent", ""))
        bounces = _safe_int(r.get("bounces", ""))
        opens = _safe_int(r.get("opens", ""))
        clicks = _safe_int(r.get("clicks", ""))
        unsubs = _safe_int(r.get("unsubscribes", ""))
        if None in (sent, bounces, opens, clicks, unsubs):
            return None, "malformed campaigns: numeric fields"
        delivered = sent - bounces

        technique = ann_map[cid]
        d = agg.setdefault(technique, {
            "campaigns": 0,
            "delivered": 0,
            "opens": 0,
            "clicks": 0,
            "unsubscribes": 0
        })
        d["campaigns"] += 1
        d["delivered"] += delivered
        d["opens"] += opens
        d["clicks"] += clicks
        d["unsubscribes"] += unsubs

        total_delivered += delivered
        total_opens += opens
        total_clicks += clicks
        total_unsubs += unsubs
        campaign_count += 1

    if campaign_count == 0 or total_delivered == 0:
        return None, "no data after join"

    technique_summary = {}
    for tech, vals in agg.items():
        delivered = vals["delivered"]
        opens = vals["opens"]
        clicks = vals["clicks"]
        unsubscribes = vals["unsubscribes"]
        open_rate = opens / delivered if delivered else 0.0
        click_rate = clicks / delivered if delivered else 0.0
        unsub_rate = unsubscribes / delivered if delivered else 0.0
        technique_summary[tech] = {
            "campaigns": int(vals["campaigns"]),
            "delivered": int(delivered),
            "opens": int(opens),
            "clicks": int(clicks),
            "unsubscribes": int(unsubscribes),
            "open_rate": open_rate,
            "click_rate": click_rate,
            "unsub_rate": unsub_rate
        }

    overall_open_rate = total_opens / total_delivered
    overall_click_rate = total_clicks / total_delivered
    overall_unsub_rate = total_unsubs / total_delivered

    ranking = []
    for tech, vals in technique_summary.items():
        ranking.append((tech, vals["click_rate"], vals["delivered"]))
    ranking.sort(key=lambda x: (-x[1], -x[2], x[0]))
    top_two = ranking[:2]

    ranking_bottom = []
    for tech, vals in technique_summary.items():
        ranking_bottom.append((tech, vals["click_rate"], vals["delivered"]))
    ranking_bottom.sort(key=lambda x: (x[1], x[2], x[0]))
    bottom = ranking_bottom[0] if ranking_bottom else None

    avg_delivered = total_delivered / campaign_count
    N = math.ceil(0.10 * avg_delivered)

    result = {
        "technique_summary": technique_summary,
        "overall": {
            "delivered": int(total_delivered),
            "open_rate": overall_open_rate,
            "click_rate": overall_click_rate,
            "unsub_rate": overall_unsub_rate
        },
        "top_two": [{"technique": t[0], "click_rate": t[1], "delivered": t[2]} for t in top_two],
        "bottom": {"technique": bottom[0], "click_rate": bottom[1], "delivered": bottom[2]} if bottom else None,
        "avg_delivered": avg_delivered,
        "sample_N": int(N)
    }
    return result, None


def _load_csv_strict(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows_list = list(reader)
        if not rows_list:
            return None, "empty csv"
        header = rows_list[0]
        rows = []
        for row in rows_list[1:]:
            if len(row) != len(header):
                return None, "malformed row length"
            rows.append({header[i]: row[i] for i in range(len(header))})
        return rows, None
    except Exception as e:
        return None, str(e)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists_and_sample_comment": 0.0,
        "technique_summary_exists_and_header": 0.0,
        "technique_summary_values_correct": 0.0,
        "overall_summary_exists_and_keys": 0.0,
        "overall_summary_values_correct": 0.0,
        "ranking_top_two_correct": 0.0,
        "ranking_bottom_correct": 0.0,
        "meeting_notes_exists_and_structure": 0.0,
        "meeting_notes_action1_correct": 0.0,
        "meeting_notes_action2_correct": 0.0,
        "meeting_notes_action3_correct": 0.0,
        "email_exists_and_subject": 0.0,
        "email_overall_summary_line": 0.0,
        "email_top_two_listed": 0.0,
        "email_ask_and_paths": 0.0,
    }

    expected, _ = _compute_expected(workspace)

    # Check script and sample command comment
    script_path = workspace / "scripts" / "analyze_subjects.py"
    try:
        if script_path.exists():
            found = False
            with script_path.open("r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= 10:
                        break
                    if line.lstrip().startswith("#") and "Example:" in line and "python3 scripts/analyze_subjects.py" in line:
                        if all(flag in line for flag in ["--campaigns", "--annotations", "--outdir", "--notes", "--email"]):
                            found = True
                            break
            scores["script_exists_and_sample_comment"] = 1.0 if found else 0.5
        else:
            scores["script_exists_and_sample_comment"] = 0.0
    except Exception:
        scores["script_exists_and_sample_comment"] = 0.0

    # technique_summary.csv checks
    ts_path = workspace / "outputs" / "technique_summary.csv"
    ts_rows, _ = _load_csv_strict(ts_path) if ts_path.exists() else (None, "missing")
    expected_header = [
        "technique", "campaigns", "delivered", "opens", "clicks", "unsubscribes",
        "open_rate", "click_rate", "unsub_rate"
    ]
    if ts_rows is not None:
        try:
            with ts_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            actual_header = header_line.split(",")
            scores["technique_summary_exists_and_header"] = 1.0 if actual_header == expected_header else 0.0
        except Exception:
            scores["technique_summary_exists_and_header"] = 0.0
    else:
        scores["technique_summary_exists_and_header"] = 0.0

    if ts_rows is not None and expected is not None:
        actual_map: Dict[str, Dict[str, str]] = {}
        for row in ts_rows:
            tech = row.get("technique")
            if tech is None:
                actual_map = {}
                break
            actual_map[tech] = row

        exp_map = expected["technique_summary"]
        ok = True
        if set(actual_map.keys()) != set(exp_map.keys()):
            ok = False
        else:
            for tech, vals in exp_map.items():
                arow = actual_map.get(tech, {})
                for k in ["campaigns", "delivered", "opens", "clicks", "unsubscribes"]:
                    av = arow.get(k)
                    ev = vals[k]
                    try:
                        if int(av) != int(ev):
                            ok = False
                    except Exception:
                        ok = False
                for k in ["open_rate", "click_rate", "unsub_rate"]:
                    av = arow.get(k)
                    ev = _format_rate_4(vals[k])
                    if av != ev:
                        ok = False
        scores["technique_summary_values_correct"] = 1.0 if ok else 0.0
    else:
        scores["technique_summary_values_correct"] = 0.0

    # overall_summary.json checks
    overall_path = workspace / "outputs" / "overall_summary.json"
    overall_data = None
    if overall_path.exists():
        try:
            with overall_path.open("r", encoding="utf-8") as f:
                overall_data = json.load(f)
            required_keys = {"overall_delivered", "overall_open_rate", "overall_click_rate", "overall_unsub_rate", "top_two_techniques", "bottom_technique"}
            if all(k in overall_data for k in required_keys):
                t2 = overall_data.get("top_two_techniques")
                btm = overall_data.get("bottom_technique")
                if isinstance(t2, list) and len(t2) == 2 and all(isinstance(x, dict) and "technique" in x and "click_rate" in x for x in t2) and isinstance(btm, dict) and "technique" in btm and "click_rate" in btm:
                    scores["overall_summary_exists_and_keys"] = 1.0
                else:
                    scores["overall_summary_exists_and_keys"] = 0.0
            else:
                scores["overall_summary_exists_and_keys"] = 0.0
        except Exception:
            scores["overall_summary_exists_and_keys"] = 0.0
    else:
        scores["overall_summary_exists_and_keys"] = 0.0

    if overall_data is not None and expected is not None:
        try:
            ok_vals = True
            exp_overall = expected["overall"]
            od = overall_data.get("overall_delivered")
            oor = overall_data.get("overall_open_rate")
            ocr = overall_data.get("overall_click_rate")
            our = overall_data.get("overall_unsub_rate")
            try:
                if int(od) != int(exp_overall["delivered"]):
                    ok_vals = False
            except Exception:
                ok_vals = False
            try:
                if not _float_equal(float(oor), float(exp_overall["open_rate"]), 1e-6):
                    ok_vals = False
                if not _float_equal(float(ocr), float(exp_overall["click_rate"]), 1e-6):
                    ok_vals = False
                if not _float_equal(float(our), float(exp_overall["unsub_rate"]), 1e-6):
                    ok_vals = False
            except Exception:
                ok_vals = False
            scores["overall_summary_values_correct"] = 1.0 if ok_vals else 0.0
        except Exception:
            scores["overall_summary_values_correct"] = 0.0
    else:
        scores["overall_summary_values_correct"] = 0.0

    # Rankings checks
    if overall_data is not None and expected is not None:
        try:
            actual_top_two = overall_data.get("top_two_techniques", [])
            exp_top_two = expected["top_two"]
            ok_top = True
            if len(actual_top_two) != 2:
                ok_top = False
            else:
                for i in range(2):
                    at = actual_top_two[i].get("technique")
                    if at != exp_top_two[i]["technique"]:
                        ok_top = False
                    else:
                        try:
                            if not _float_equal(float(actual_top_two[i].get("click_rate")), float(exp_top_two[i]["click_rate"]), 1e-6):
                                ok_top = False
                        except Exception:
                            ok_top = False
            scores["ranking_top_two_correct"] = 1.0 if ok_top else 0.0

            actual_bottom = overall_data.get("bottom_technique", {})
            exp_bottom = expected["bottom"]
            ok_bottom = True
            if exp_bottom is None:
                ok_bottom = False
            else:
                if actual_bottom.get("technique") != exp_bottom["technique"]:
                    ok_bottom = False
                else:
                    try:
                        if not _float_equal(float(actual_bottom.get("click_rate")), float(exp_bottom["click_rate"]), 1e-6):
                            ok_bottom = False
                    except Exception:
                        ok_bottom = False
            scores["ranking_bottom_correct"] = 1.0 if ok_bottom else 0.0
        except Exception:
            scores["ranking_top_two_correct"] = 0.0
            scores["ranking_bottom_correct"] = 0.0
    else:
        scores["ranking_top_two_correct"] = 0.0
        scores["ranking_bottom_correct"] = 0.0

    # Meeting notes checks
    notes_path = workspace / "meeting" / "next_steps.md"
    notes_text = None
    if notes_path.exists():
        try:
            notes_text = notes_path.read_text(encoding="utf-8")
        except Exception:
            notes_text = None
    if notes_text is not None:
        lines = [ln.rstrip("\n") for ln in notes_text.splitlines()]
        bullet_lines = [ln for ln in lines if ln.strip().startswith("- ") or ln.strip().startswith("* ")]
        non_empty_non_bullet = [ln for ln in lines if ln.strip() and not (ln.strip().startswith("- ") or ln.strip().startswith("* "))]
        if len(bullet_lines) == 3 and len(non_empty_non_bullet) >= 1:
            scores["meeting_notes_exists_and_structure"] = 1.0
        else:
            scores["meeting_notes_exists_and_structure"] = 0.0
    else:
        scores["meeting_notes_exists_and_structure"] = 0.0

    if notes_text is not None and expected is not None:
        lines = [ln.rstrip("\n") for ln in notes_text.splitlines()]
        bullets = [ln.strip() for ln in lines if ln.strip().startswith("- ") or ln.strip().startswith("* ")]
        if len(bullets) >= 3:
            try:
                b1 = bullets[0]
                top1_name = expected["top_two"][0]["technique"]
                phrase1 = f"Set up an A/B test using {top1_name}"
                has_phrase = phrase1 in b1
                N = expected["sample_N"]
                has_N = str(N) in b1
                scores["meeting_notes_action1_correct"] = 1.0 if (has_phrase and has_N) else 0.0
            except Exception:
                scores["meeting_notes_action1_correct"] = 0.0

            try:
                b2 = bullets[1]
                top2_name = expected["top_two"][1]["technique"]
                phrase2 = f"Prioritize {top2_name} for upcoming sends"
                has_phrase2 = phrase2 in b2
                top2_click = expected["top_two"][1]["click_rate"]
                overall_click = expected["overall"]["click_rate"]
                lift = (top2_click - overall_click) * 100.0
                top2_click_pct = _format_pct_1(top2_click)
                lift_pct = f"{lift:.1f}%"
                lift_pct_alt = f"+{lift:.1f}%"
                has_click = top2_click_pct in b2
                has_lift = (lift_pct in b2) or (lift_pct_alt in b2) or (f"{abs(lift):.1f}%" in b2)
                scores["meeting_notes_action2_correct"] = 1.0 if (has_phrase2 and has_click and has_lift) else 0.0
            except Exception:
                scores["meeting_notes_action2_correct"] = 0.0

            try:
                b3 = bullets[2]
                bottom_name = expected["bottom"]["technique"]
                phrase3 = f"Deprioritize {bottom_name}"
                has_phrase3 = phrase3 in b3
                bottom_click = expected["bottom"]["click_rate"]
                overall_click = expected["overall"]["click_rate"]
                deficit = (bottom_click - overall_click) * 100.0
                bottom_click_pct = _format_pct_1(bottom_click)
                deficit_pct = f"{deficit:.1f}%"
                deficit_alt = f"{abs(deficit):.1f}%"
                has_click3 = bottom_click_pct in b3
                has_deficit3 = (deficit_pct in b3) or (deficit_alt in b3) or (f"-{abs(deficit):.1f}%" in b3)
                scores["meeting_notes_action3_correct"] = 1.0 if (has_phrase3 and has_click3 and has_deficit3) else 0.0
            except Exception:
                scores["meeting_notes_action3_correct"] = 0.0
        else:
            scores["meeting_notes_action1_correct"] = 0.0
            scores["meeting_notes_action2_correct"] = 0.0
            scores["meeting_notes_action3_correct"] = 0.0
    else:
        scores["meeting_notes_action1_correct"] = 0.0
        scores["meeting_notes_action2_correct"] = 0.0
        scores["meeting_notes_action3_correct"] = 0.0

    # Email checks
    email_path = workspace / "drafts" / "team_update.txt"
    email_text = None
    if email_path.exists():
        try:
            email_text = email_path.read_text(encoding="utf-8")
        except Exception:
            email_text = None
    if email_text is not None:
        lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        if lines:
            subj_ok = lines[0].strip() == "Subject: Subject Lines Performance: Top Techniques and Next Steps"
            scores["email_exists_and_subject"] = 1.0 if subj_ok else 0.0
        else:
            scores["email_exists_and_subject"] = 0.0
    else:
        scores["email_exists_and_subject"] = 0.0

    if email_text is not None and expected is not None:
        lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        overall_open_pct = _format_pct_1(expected["overall"]["open_rate"])
        overall_click_pct = _format_pct_1(expected["overall"]["click_rate"])
        one_line_has_both = any((overall_open_pct in ln and overall_click_pct in ln) for ln in lines[1:]) if len(lines) > 1 else False
        scores["email_overall_summary_line"] = 1.0 if one_line_has_both else 0.0

        t1_name = expected["top_two"][0]["technique"]
        t2_name = expected["top_two"][1]["technique"]
        t1_pct = _format_pct_1(expected["top_two"][0]["click_rate"])
        t2_pct = _format_pct_1(expected["top_two"][1]["click_rate"])
        has_t1_name = t1_name in email_text
        has_t2_name = t2_name in email_text
        has_t1_pct = t1_pct in email_text
        has_t2_pct = t2_pct in email_text
        scores["email_top_two_listed"] = 1.0 if (has_t1_name and has_t1_pct and has_t2_name and has_t2_pct) else 0.0

        mentions_paths = ("outputs/technique_summary.csv" in email_text) and ("outputs/overall_summary.json" in email_text)
        asks_reply = ("reply" in email_text.lower()) and ("tip" in email_text.lower())
        scores["email_ask_and_paths"] = 1.0 if (mentions_paths and asks_reply) else 0.0
    else:
        scores["email_overall_summary_line"] = 0.0
        scores["email_top_two_listed"] = 0.0
        scores["email_ask_and_paths"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()