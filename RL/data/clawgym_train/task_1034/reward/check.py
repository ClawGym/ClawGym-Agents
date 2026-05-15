import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _load_json_safe(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return None, f"read_error:{e}"
    try:
        data = json.loads(text)
        return data, None
    except Exception as e:
        return None, f"json_error:{e}"


def _read_text_safe(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, f"read_error:{e}"


def _list_class_files(classes_dir: Path) -> List[Path]:
    if not classes_dir.exists() or not classes_dir.is_dir():
        return []
    files = sorted([p for p in classes_dir.glob("class_*.json") if p.is_file()])
    return files


def _approx_equal(a: float, b: float, tol: float = 1e-3) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _compute_expected(classes: List[Dict[str, Any]], prefs: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    expected: Dict[str, Dict[str, Any]] = {}
    budget = prefs.get("budget_max_usd")
    commute_max = prefs.get("commute_max_km")
    hours_max = prefs.get("weekly_hours_max")
    disliked_days = set(prefs.get("disliked_days", []))
    start_window = prefs.get("start_window")
    weights = prefs.get("weights", {})
    cw = float(weights.get("cost_weight", 0.0))
    dw = float(weights.get("distance_weight", 0.0))
    hw = float(weights.get("hours_weight", 0.0))
    sw = float(weights.get("schedule_fit_weight", 0.0))

    for cls in classes:
        if not isinstance(cls, dict):
            continue
        oid = cls.get("option_id")
        if not oid:
            continue
        try:
            tuition = float(cls.get("tuition_usd"))
            commute = float(cls.get("commute_km"))
            whours = float(cls.get("weekly_hours"))
        except Exception:
            # Malformed numeric fields -> treat as failing constraints
            tuition = float("inf")
            commute = float("inf")
            whours = float("inf")
        m_days = set(cls.get("meeting_days", [])) if isinstance(cls.get("meeting_days", []), list) else set()
        start_date = cls.get("start_date")

        reasons = []
        passes = True
        if not (isinstance(start_date, str) and isinstance(start_window, str) and len(start_date) == 10 and len(start_window) == 10):
            passes = False
            reasons.append("start_date before start_window or invalid date")
        else:
            if start_date < start_window:
                passes = False
                reasons.append("start_date before start_window")

        try:
            if tuition > float(budget):
                passes = False
                reasons.append("tuition exceeds budget_max_usd")
        except Exception:
            passes = False
            reasons.append("invalid budget_max_usd")

        try:
            if commute > float(commute_max):
                passes = False
                reasons.append("commute_km exceeds commute_max_km")
        except Exception:
            passes = False
            reasons.append("invalid commute_max_km")

        try:
            if whours > float(hours_max):
                passes = False
                reasons.append("weekly_hours exceeds weekly_hours_max")
        except Exception:
            passes = False
            reasons.append("invalid weekly_hours_max")

        try:
            cost_ratio = tuition / float(budget)
        except Exception:
            cost_ratio = float("inf")
        try:
            distance_ratio = commute / float(commute_max)
        except Exception:
            distance_ratio = float("inf")
        try:
            hours_ratio = whours / float(hours_max)
        except Exception:
            hours_ratio = float("inf")
        schedule_has_conflict = len(m_days.intersection(disliked_days)) > 0

        total_score = None
        if passes:
            total = (cw * cost_ratio) + (dw * distance_ratio) + (hw * hours_ratio) + (sw if schedule_has_conflict else 0.0)
            total_score = round(total + 0.0, 3)

        expected[oid] = {
            "option_id": oid,
            "title": cls.get("title"),
            "provider": cls.get("provider"),
            "contact_email": cls.get("contact_email"),
            "meeting_days": list(m_days),
            "start_date": start_date,
            "tuition_usd": cls.get("tuition_usd"),
            "commute_km": cls.get("commute_km"),
            "weekly_hours": cls.get("weekly_hours"),
            "passes": passes,
            "reasons": reasons,
            "ratios": {
                "cost_ratio": cost_ratio,
                "distance_ratio": distance_ratio,
                "hours_ratio": hours_ratio,
            },
            "schedule_has_conflict": schedule_has_conflict,
            "total_score": total_score,
        }
    return expected


def _extract_sentences(text: str) -> List[str]:
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = [s.strip() for s in parts if s.strip()]
    return sentences


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "decision_scores_exists": 0.0,
        "decision_scores_entries_cover_all_classes": 0.0,
        "decision_scores_field_presence_and_types": 0.0,
        "decision_scores_ratios_correct": 0.0,
        "decision_scores_schedule_conflict_correct": 0.0,
        "decision_scores_hard_constraints_and_reasons": 0.0,
        "decision_scores_total_score_correct_and_rules": 0.0,
        "decision_summary_exists": 0.0,
        "decision_summary_lists_all_classes_and_status": 0.0,
        "decision_summary_marks_top_choice_correct": 0.0,
        "decision_summary_top_choice_explanation": 0.0,
        "notes_updated_replaced_pending_line": 0.0,
        "notes_updated_includes_required_fields": 0.0,
        "notes_updated_bullets_and_topics": 0.0,
        "email_exists": 0.0,
        "email_to_and_subject_correct": 0.0,
        "email_body_content_requirements": 0.0,
    }

    # Load inputs
    prefs_path = workspace / "input" / "prefs.json"
    prefs, _ = _load_json_safe(prefs_path)
    class_files = _list_class_files(workspace / "input" / "classes")
    class_datas: List[Dict[str, Any]] = []
    classes_ok = True
    for cf in class_files:
        data, err = _load_json_safe(cf)
        if err is not None or not isinstance(data, dict):
            classes_ok = False
            break
        class_datas.append(data)

    expected_map: Dict[str, Dict[str, Any]] = {}
    if isinstance(prefs, dict) and classes_ok and len(class_datas) > 0:
        try:
            expected_map = _compute_expected(class_datas, prefs)
        except Exception:
            expected_map = {}

    # Determine expected chosen class (top among passing)
    chosen_oid: Optional[str] = None
    if expected_map:
        passing = [e for e in expected_map.values() if e["passes"]]
        if passing:
            passing_sorted = sorted(passing, key=lambda x: (x["total_score"], x["option_id"]))
            chosen_oid = passing_sorted[0]["option_id"]

    # Check decision_scores.json
    ds_path = workspace / "output" / "decision_scores.json"
    ds_data, ds_err = _load_json_safe(ds_path)
    if ds_err is None and isinstance(ds_data, list):
        scores["decision_scores_exists"] = 1.0

        discovered_oids = set([d.get("option_id") for d in class_datas if isinstance(d, dict) and d.get("option_id")])
        ds_oids = set()
        fields_ok = True
        ratios_ok = True
        sched_ok = True
        hc_ok = True
        totals_ok = True

        for item in ds_data:
            if not isinstance(item, dict):
                fields_ok = False
                continue
            oid = item.get("option_id")
            if oid:
                ds_oids.add(oid)
            required_keys = [
                "option_id",
                "title",
                "passes_hard_constraints",
                "exclusion_reasons",
                "cost_ratio",
                "distance_ratio",
                "hours_ratio",
                "schedule_has_conflict",
            ]
            for k in required_keys:
                if k not in item:
                    fields_ok = False
            if not isinstance(item.get("option_id"), str):
                fields_ok = False
            if not isinstance(item.get("title"), str):
                fields_ok = False
            if not isinstance(item.get("passes_hard_constraints"), bool):
                fields_ok = False
            if not isinstance(item.get("exclusion_reasons"), list):
                fields_ok = False
            for rk in ["cost_ratio", "distance_ratio", "hours_ratio"]:
                if not isinstance(item.get(rk), (int, float)):
                    fields_ok = False

            if oid in expected_map:
                exp = expected_map[oid]
                er = exp["ratios"]
                try:
                    if not _approx_equal(float(item.get("cost_ratio")), float(er["cost_ratio"]), tol=1e-3):
                        ratios_ok = False
                    if not _approx_equal(float(item.get("distance_ratio")), float(er["distance_ratio"]), tol=1e-3):
                        ratios_ok = False
                    if not _approx_equal(float(item.get("hours_ratio")), float(er["hours_ratio"]), tol=1e-3):
                        ratios_ok = False
                except Exception:
                    ratios_ok = False

                if bool(item.get("schedule_has_conflict")) != bool(exp["schedule_has_conflict"]):
                    sched_ok = False

                if bool(item.get("passes_hard_constraints")) != bool(exp["passes"]):
                    hc_ok = False

                if not exp["passes"]:
                    reasons_list = item.get("exclusion_reasons")
                    if not isinstance(reasons_list, list) or len(reasons_list) == 0:
                        hc_ok = False
                    else:
                        text_all = " ".join([str(r).lower() for r in reasons_list])
                        violated_cats = set()
                        for rs in exp["reasons"]:
                            rs_low = str(rs).lower()
                            if "start" in rs_low:
                                violated_cats.add("start")
                            if "tuition" in rs_low or "budget" in rs_low or "cost" in rs_low or "price" in rs_low:
                                violated_cats.add("tuition")
                            if "commute" in rs_low or "distance" in rs_low:
                                violated_cats.add("commute")
                            if "hours" in rs_low or "weekly" in rs_low:
                                violated_cats.add("hours")
                        for cat in violated_cats:
                            if cat == "start":
                                if not any(k in text_all for k in ["start", "start_date", "window"]):
                                    hc_ok = False
                            if cat == "tuition":
                                if not any(k in text_all for k in ["tuition", "budget", "cost", "price"]):
                                    hc_ok = False
                            if cat == "commute":
                                if not any(k in text_all for k in ["commute", "distance"]):
                                    hc_ok = False
                            if cat == "hours":
                                if not any(k in text_all for k in ["hours", "weekly"]):
                                    hc_ok = False
                else:
                    reasons_list = item.get("exclusion_reasons")
                    if not (isinstance(reasons_list, list) and len(reasons_list) == 0):
                        hc_ok = False

                if exp["passes"]:
                    if "total_score" not in item or not isinstance(item.get("total_score"), (int, float)):
                        totals_ok = False
                    else:
                        try:
                            if not _approx_equal(float(item.get("total_score")), float(exp["total_score"]), tol=1e-3):
                                totals_ok = False
                        except Exception:
                            totals_ok = False
                else:
                    if "total_score" in item:
                        totals_ok = False

        if discovered_oids and ds_oids == discovered_oids:
            scores["decision_scores_entries_cover_all_classes"] = 1.0
        elif discovered_oids:
            scores["decision_scores_entries_cover_all_classes"] = 0.0

        if fields_ok:
            scores["decision_scores_field_presence_and_types"] = 1.0
        if ratios_ok:
            scores["decision_scores_ratios_correct"] = 1.0
        if sched_ok:
            scores["decision_scores_schedule_conflict_correct"] = 1.0
        if hc_ok:
            scores["decision_scores_hard_constraints_and_reasons"] = 1.0
        if totals_ok:
            scores["decision_scores_total_score_correct_and_rules"] = 1.0

    # Check decision_summary.md
    summary_path = workspace / "output" / "decision_summary.md"
    summary_text, summary_err = _read_text_safe(summary_path)
    if summary_err is None and isinstance(summary_text, str):
        scores["decision_summary_exists"] = 1.0
        list_ok = True
        marks_top_ok = False
        explanation_ok = False

        def _find_near(txt: str, pattern: str) -> List[Tuple[int, int]]:
            spans = []
            if not pattern:
                return spans
            for m in re.finditer(re.escape(pattern), txt, flags=re.IGNORECASE):
                spans.append((m.start(), m.end()))
            return spans

        if expected_map:
            lowered = summary_text.lower()
            for oid, exp in expected_map.items():
                title = exp.get("title") or str(oid)
                positions = _find_near(summary_text, title)
                if not positions:
                    positions = _find_near(summary_text, str(oid))
                if not positions:
                    list_ok = False
                    continue
                start = max(0, positions[0][0] - 200)
                end = min(len(summary_text), positions[0][1] + 200)
                window = summary_text[start:end].lower()
                if any(k in window for k in ["pass", "fail", "passed", "failed"]):
                    if not exp["passes"]:
                        if not any(kw in window for kw in ["start", "budget", "tuition", "commute", "distance", "hours", "weekly"]):
                            list_ok = False
                else:
                    list_ok = False

            if list_ok:
                scores["decision_summary_lists_all_classes_and_status"] = 1.0

            if chosen_oid and chosen_oid in expected_map:
                chosen_title = expected_map[chosen_oid]["title"]
                t_positions = _find_near(summary_text, chosen_title)
                if t_positions:
                    s, e = t_positions[0]
                    around = summary_text[max(0, s - 200):min(len(summary_text), e + 200)].lower()
                    if ("top choice" in around) or (("top" in around) and ("choice" in around)):
                        marks_top_ok = True
                if marks_top_ok:
                    scores["decision_summary_marks_top_choice_correct"] = 1.0

                expl_window = ""
                if t_positions:
                    expl_window = summary_text[max(0, t_positions[0][0] - 400):min(len(summary_text), t_positions[0][1] + 800)]
                else:
                    expl_window = summary_text
                sentences = _extract_sentences(expl_window)
                keywords = [
                    (expected_map[chosen_oid].get("title") or "").lower(),
                    (expected_map[chosen_oid].get("provider") or "").lower(),
                    "fit", "fits", "priority", "priorities", "research", "schedule", "cost", "budget", "commute", "distance",
                ]
                relevant_sents = [s for s in sentences if any(k for k in keywords if k and k in s.lower())]
                if 2 <= len(relevant_sents) <= 4:
                    explanation_ok = True
                if explanation_ok:
                    scores["decision_summary_top_choice_explanation"] = 1.0

    # Check notes update
    notes_path = workspace / "input" / "notes" / "personal_notes.md"
    notes_text, notes_err = _read_text_safe(notes_path)
    if notes_err is None and isinstance(notes_text, str) and chosen_oid and chosen_oid in expected_map:
        chosen = expected_map[chosen_oid]
        # Replaced pending line
        if "Decision pending: [TO DECIDE]".lower() not in notes_text.lower():
            scores["notes_updated_replaced_pending_line"] = 1.0

        # Required fields: title, provider, meeting_days, start_date, tuition, commute, weekly_hours
        fields_ok = True
        if not chosen.get("title") or not chosen.get("provider"):
            fields_ok = False
        else:
            if (chosen["title"] not in notes_text) or (chosen["provider"] not in notes_text):
                fields_ok = False
        meeting_days = chosen.get("meeting_days", [])
        for d in meeting_days:
            if str(d) not in notes_text:
                fields_ok = False
        if str(chosen.get("start_date")) not in notes_text:
            fields_ok = False
        # Numeric appearances as integers when possible
        try:
            t_str = str(int(float(chosen.get("tuition_usd"))))
        except Exception:
            t_str = str(chosen.get("tuition_usd"))
        if t_str not in notes_text:
            fields_ok = False
        try:
            c_str = str(int(float(chosen.get("commute_km"))))
        except Exception:
            c_str = str(chosen.get("commute_km"))
        if c_str not in notes_text:
            fields_ok = False
        try:
            w_str = str(int(float(chosen.get("weekly_hours"))))
        except Exception:
            w_str = str(chosen.get("weekly_hours"))
        if w_str not in notes_text:
            fields_ok = False
        if fields_ok:
            scores["notes_updated_includes_required_fields"] = 1.0

        # Bullets 2–3 and topics coverage (cost, schedule, commute, research)
        idx = notes_text.find(chosen.get("title") or "")
        bullets_ok = False
        topics_ok = False
        if idx != -1:
            after = notes_text[idx:]
            lines = after.splitlines()
            bullet_lines = []
            for line in lines:
                if re.match(r'^\s*[-*]\s+', line):
                    bullet_lines.append(line.strip())
                elif bullet_lines and line.strip() == "":
                    break
                elif bullet_lines and not re.match(r'^\s*[-*]\s+', line):
                    break
            count = len(bullet_lines)
            if 2 <= count <= 3:
                bullets_ok = True
            text_join = " ".join(bullet_lines).lower()
            topic_hits = 0
            if any(k in text_join for k in ["cost", "tuition", "budget", "price"]):
                topic_hits += 1
            if any(k in text_join for k in ["schedule", "meeting", "days", "fit", "time"]):
                topic_hits += 1
            if any(k in text_join for k in ["commute", "distance", "travel"]):
                topic_hits += 1
            if any(k in text_join for k in ["research", "medieval", "blacksmith", "blacksmithing"]):
                topic_hits += 1
            if topic_hits >= 3:
                topics_ok = True
        if bullets_ok:
            scores["notes_updated_bullets_and_topics"] = 0.5 + (0.5 if topics_ok else 0.0)
        else:
            if topics_ok:
                scores["notes_updated_bullets_and_topics"] = 0.5

    # Check email draft
    email_path = workspace / "output" / "drafts" / "enrollment_email.txt"
    email_text, email_err = _read_text_safe(email_path)
    if email_err is None and isinstance(email_text, str):
        scores["email_exists"] = 1.0
        lines = [ln for ln in email_text.splitlines() if ln.strip() != ""]
        to_ok = False
        subj_ok = False
        body_ok_score = 0.0
        if isinstance(prefs, dict) and chosen_oid and chosen_oid in expected_map and len(lines) >= 2:
            chosen = expected_map[chosen_oid]
            expected_to = f"To: {chosen.get('contact_email', '')}"
            if lines[0].strip().lower() == expected_to.lower():
                to_ok = True
            subj = lines[1].strip()
            subj_expected_phrase = f"Enrollment inquiry: {chosen.get('title', '')} (Spring 2026)"
            if subj.lower().startswith("subject:") and subj_expected_phrase.lower() in subj.lower():
                subj_ok = True
            body = "\n".join(lines[2:]).lower()
            intro_ok = (("academic" in body) or ("researcher" in body)) and ("medieval" in body) and ("blacksmith" in body or "blacksmithing" in body)
            align_ok = ("research" in body) and ("schedule" in body)
            mdays = [str(d).lower() for d in (chosen.get("meeting_days") or [])]
            meeting_days_ok = all(d in body for d in mdays) if mdays else False
            disliked_days = [str(d).lower() for d in (prefs.get("disliked_days", []) if isinstance(prefs, dict) else [])]
            ask_disliked_ok = any(d in body for d in disliked_days) if disliked_days else False
            has_question = "?" in body
            ppe_ok = ("ppe" in body) or ("protective" in body and ("equipment" in body or "gear" in body)) or ("safety" in body and ("gear" in body or "equipment" in body))
            preread_ok = ("pre-reading" in body) or ("prereading" in body) or ("pre reading" in body) or ("reading" in body and ("recommend" in body or "recommended" in body or "suggest" in body or "suggested" in body)) or ("materials" in body and ("recommend" in body or "recommended" in body))
            signoff_ok = ("best regards" in body) and ("dr." in body or "dr " in body)
            body_ok_components = [
                intro_ok,
                align_ok,
                (meeting_days_ok and ask_disliked_ok and has_question),
                (ppe_ok and preread_ok),
                signoff_ok,
            ]
            body_ok_score = sum(1.0 for c in body_ok_components if c) / 5.0

        scores["email_to_and_subject_correct"] = 1.0 if (to_ok and subj_ok) else 0.0
        scores["email_body_content_requirements"] = max(0.0, min(1.0, body_ok_score))

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()