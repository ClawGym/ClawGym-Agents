import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        txt = _read_text_safe(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _read_csv_dicts_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _parse_float(value: Any) -> Optional[float]:
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _normalize_str(val: Any) -> str:
    s = str(val)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _compute_stats_summary(match_rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    # Convert types where needed
    normalized = []
    for r in match_rows:
        try:
            kills = int(r["kills"])
            deaths = int(r["deaths"])
            result = str(r["result"]).strip()
            game = str(r["game"]).strip()
            map_name = str(r["map"]).strip()
        except Exception:
            continue
        normalized.append(
            {
                "game": game,
                "map": map_name,
                "result": result,
                "kills": kills,
                "deaths": deaths,
            }
        )

    def aggregate_by(key: str) -> Dict[str, Dict[str, Any]]:
        agg: Dict[str, Dict[str, Any]] = {}
        for r in normalized:
            name = r[key]
            a = agg.setdefault(
                name,
                {
                    "matches": 0,
                    "wins": 0,
                    "losses": 0,
                    "kills": 0,
                    "deaths": 0,
                },
            )
            a["matches"] += 1
            if r["result"] == "W":
                a["wins"] += 1
            elif r["result"] == "L":
                a["losses"] += 1
            a["kills"] += r["kills"]
            a["deaths"] += r["deaths"]
        return agg

    out: List[Dict[str, Any]] = []
    # By game
    by_game = aggregate_by("game")
    for name, a in by_game.items():
        matches = a["matches"]
        wins = a["wins"]
        losses = a["losses"]
        kills = a["kills"]
        deaths = a["deaths"]
        win_rate = (wins / matches) if matches > 0 else 0.0
        kd_ratio = (kills / deaths) if deaths != 0 else float("inf")
        out.append(
            {
                "group_type": "game",
                "group_name": name,
                "matches": matches,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "kills": kills,
                "deaths": deaths,
                "kd_ratio": kd_ratio,
            }
        )
    # By map
    by_map = aggregate_by("map")
    for name, a in by_map.items():
        matches = a["matches"]
        wins = a["wins"]
        losses = a["losses"]
        kills = a["kills"]
        deaths = a["deaths"]
        win_rate = (wins / matches) if matches > 0 else 0.0
        kd_ratio = (kills / deaths) if deaths != 0 else float("inf")
        out.append(
            {
                "group_type": "map",
                "group_name": name,
                "matches": matches,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "kills": kills,
                "deaths": deaths,
                "kd_ratio": kd_ratio,
            }
        )
    return out


def _parse_stats_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _read_csv_dicts_safe(path)
    if rows is None:
        return None
    parsed: List[Dict[str, Any]] = []
    required_cols = [
        "group_type",
        "group_name",
        "matches",
        "wins",
        "losses",
        "win_rate",
        "kills",
        "deaths",
        "kd_ratio",
    ]
    # Validate columns:
    if any(set(required_cols) - set(r.keys()) for r in rows):
        return None
    for r in rows:
        try:
            group_type = str(r["group_type"]).strip()
            group_name = str(r["group_name"]).strip()
            matches = int(str(r["matches"]).strip())
            wins = int(str(r["wins"]).strip())
            losses = int(str(r["losses"]).strip())
            win_rate = float(str(r["win_rate"]).strip())
            kills = int(str(r["kills"]).strip())
            deaths = int(str(r["deaths"]).strip())
            kd_ratio = float(str(r["kd_ratio"]).strip())
        except Exception:
            return None
        parsed.append(
            {
                "group_type": group_type,
                "group_name": group_name,
                "matches": matches,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "kills": kills,
                "deaths": deaths,
                "kd_ratio": kd_ratio,
            }
        )
    return parsed


def _extract_validation(report: Any) -> Tuple[List[Dict[str, Any]], Optional[bool]]:
    # Accept a dict with a key containing per-question list, or a list
    questions: List[Dict[str, Any]] = []
    all_passed: Optional[bool] = None
    if isinstance(report, dict):
        # try common keys
        for key in ["questions", "per_question", "items", "results"]:
            v = report.get(key)
            if isinstance(v, list):
                questions = [q for q in v if isinstance(q, dict)]
                break
        if not questions and "id" in report:
            questions = [report]
        # find all_passed
        for k in report.keys():
            if k.lower() == "all_passed":
                ap = report.get(k)
                if isinstance(ap, bool):
                    all_passed = ap
                    break
    elif isinstance(report, list):
        questions = [q for q in report if isinstance(q, dict)]
        # no top-level all_passed in list; leave None
    return questions, all_passed


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "quiz_json_structure": 0.0,
        "quiz_ids_and_count": 0.0,
        "quiz_choices_and_correct_labels": 0.0,
        "quiz_type_mix": 0.0,
        "quiz_evidence_citations": 0.0,
        "answer_key_matches_quiz": 0.0,
        "validation_report_integrity": 0.0,
        "validation_computed_matches_choice": 0.0,
        "stats_summary_exists_and_columns": 0.0,
        "stats_summary_values_correct": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_action_coverage": 0.0,
        "meeting_notes_fields_and_tbd": 0.0,
        "email_rewrite_exists": 0.0,
        "email_rewrite_subject_and_length": 0.0,
        "email_rewrite_tone_constraints": 0.0,
        "email_rewrite_request_intact": 0.0,
    }

    # Paths
    input_csv_path = workspace / "input" / "match_logs.csv"
    brief_path = workspace / "input" / "assignment_brief.md"
    quiz_json_path = workspace / "output" / "quiz" / "quiz.json"
    answer_key_path = workspace / "output" / "quiz" / "answer_key.csv"
    validation_report_path = workspace / "output" / "validation" / "report.json"
    stats_summary_path = workspace / "output" / "stats" / "summary.csv"
    meeting_transcript_path = workspace / "input" / "meeting_transcript.md"
    meeting_notes_path = workspace / "output" / "meeting" / "notes.md"
    email_draft_path = workspace / "input" / "email_draft.txt"
    email_rewrite_path = workspace / "output" / "communication" / "email_rewrite.txt"

    # Load quiz.json
    quiz = _load_json_safe(quiz_json_path)
    quiz_list: List[Dict[str, Any]] = []
    if isinstance(quiz, list) and len(quiz) > 0 and all(isinstance(q, dict) for q in quiz):
        quiz_list = quiz
        # Basic structure check
        expected_fields = {"id", "stem", "choices", "correct", "type", "evidence"}
        try:
            has_all_fields = all(expected_fields.issubset(set(q.keys())) for q in quiz_list)
        except Exception:
            has_all_fields = False
        if has_all_fields:
            scores["quiz_json_structure"] = 1.0

    # Quiz IDs and count
    if quiz_list:
        ids = [q.get("id") for q in quiz_list]
        if len(quiz_list) == 6 and len(set(ids)) == 6 and set(ids) == {f"Q{i}" for i in range(1, 7)}:
            scores["quiz_ids_and_count"] = 1.0

    # Choices and correct labels
    choices_ok = True
    correct_ok = True
    if quiz_list:
        for q in quiz_list:
            ch = q.get("choices")
            if not isinstance(ch, dict):
                choices_ok = False
                break
            if set(ch.keys()) != {"A", "B", "C", "D"}:
                choices_ok = False
                break
            corr = q.get("correct")
            if corr not in {"A", "B", "C", "D"}:
                correct_ok = False
                break
        if choices_ok and correct_ok:
            scores["quiz_choices_and_correct_labels"] = 1.0

    # Type mix: at least 2 direct and at least 2 aggregate
    if quiz_list:
        types = [q.get("type") for q in quiz_list]
        direct_count = sum(1 for t in types if t == "direct")
        aggregate_count = sum(1 for t in types if t == "aggregate")
        if direct_count >= 2 and aggregate_count >= 2:
            scores["quiz_type_mix"] = 1.0

    # Evidence citations: evidence should cite match_ids and/or groupings
    def _evidence_has_citation(ev: Any) -> bool:
        if ev is None:
            return False
        if not isinstance(ev, str):
            try:
                ev = json.dumps(ev)
            except Exception:
                ev = str(ev)
        ev_l = ev.lower()
        # Check for match_id references like M1..M99 or groupings like map/game/opponent names
        has_match_id = bool(re.search(r"\bM\d+\b", ev))
        grouping_keywords = [
            "map",
            "game",
            "opponent",
            "ascent",
            "bind",
            "haven",
            "king's row",
            "ilios",
            "valorant",
            "overwatch 2",
        ]
        has_grouping = any(gk in ev_l for gk in grouping_keywords)
        return has_match_id or has_grouping

    if quiz_list:
        all_have_evidence = all(_evidence_has_citation(q.get("evidence")) for q in quiz_list)
        if all_have_evidence:
            scores["quiz_evidence_citations"] = 1.0

    # Answer key CSV matches quiz
    answer_rows = _read_csv_dicts_safe(answer_key_path)
    if answer_rows is not None and quiz_list:
        # Validate columns
        cols_ok = True
        for r in answer_rows:
            if set(r.keys()) != {"id", "correct"}:
                cols_ok = False
                break
        if cols_ok:
            # Map quiz id->correct
            quiz_map = {q["id"]: q["correct"] for q in quiz_list if "id" in q and "correct" in q}
            ans_map = {r["id"]: r["correct"] for r in answer_rows if "id" in r and "correct" in r}
            if set(quiz_map.keys()) == set(ans_map.keys()) == {f"Q{i}" for i in range(1, 7)}:
                all_match = all(ans_map[k] == quiz_map[k] for k in quiz_map.keys())
                if all_match:
                    scores["answer_key_matches_quiz"] = 1.0

    # Validation report integrity and matching
    validation = _load_json_safe(validation_report_path)
    val_questions: List[Dict[str, Any]] = []
    val_all_passed: Optional[bool] = None
    if validation is not None:
        val_questions, val_all_passed = _extract_validation(validation)
        has_fields = True
        ids_ok = False
        if val_questions:
            for v in val_questions:
                # Required per-question fields
                if not {"id", "computed_answer", "matches_correct", "note"}.issubset(v.keys()):
                    has_fields = False
                    break
                if not isinstance(v.get("matches_correct"), bool):
                    has_fields = False
                    break
            ids = [v.get("id") for v in val_questions]
            ids_ok = set(ids) == {f"Q{i}" for i in range(1, 7)}
        if has_fields and ids_ok:
            scores["validation_report_integrity"] = 1.0

        # all_passed true (either explicit or infer by AND)
        if val_questions:
            all_true = all(bool(v.get("matches_correct")) for v in val_questions)
            if val_all_passed is None:
                # If not provided, infer; but requirement asks to include it. We'll still accept if all_true.
                pass_flag = all_true
            else:
                pass_flag = (val_all_passed is True) and all_true
            if pass_flag:
                scores["validation_report_all_passed"] = 1.0
            else:
                scores["validation_report_all_passed"] = 0.0
        else:
            scores["validation_report_all_passed"] = 0.0
    else:
        scores["validation_report_all_passed"] = 0.0

    # Computed answer matches the selected choice text
    comp_match = False
    if quiz_list and val_questions:
        quiz_by_id: Dict[str, Dict[str, Any]] = {q["id"]: q for q in quiz_list if "id" in q}
        ok = True
        for v in val_questions:
            qid = v.get("id")
            if qid not in quiz_by_id:
                ok = False
                break
            q = quiz_by_id[qid]
            choices = q.get("choices", {})
            correct_letter = q.get("correct")
            if not isinstance(choices, dict) or correct_letter not in choices:
                ok = False
                break
            chosen_text = choices[correct_letter]
            computed = v.get("computed_answer")
            if _normalize_str(chosen_text) != _normalize_str(computed):
                ok = False
                break
        if ok:
            comp_match = True
    scores["validation_computed_matches_choice"] = 1.0 if comp_match else 0.0

    # Stats summary correctness
    match_rows = _read_csv_dicts_safe(input_csv_path)
    # Existence and columns check for summary
    stats_parsed = _parse_stats_csv(stats_summary_path)
    if stats_parsed is not None:
        scores["stats_summary_exists_and_columns"] = 1.0
    # Values comparison only if we have input CSV and parsed summary
    if match_rows is not None and stats_parsed is not None:
        expected = _compute_stats_summary(match_rows)
        # Build maps by (group_type, group_name)
        exp_map = {(e["group_type"], e["group_name"]): e for e in expected}
        got_map = {(g["group_type"], g["group_name"]): g for g in stats_parsed}
        # Must have exactly the same groups
        groups_match = set(exp_map.keys()) == set(got_map.keys())
        all_vals_ok = groups_match
        if groups_match:
            for key in exp_map.keys():
                e = exp_map[key]
                g = got_map[key]
                if (
                    e["matches"] != g["matches"]
                    or e["wins"] != g["wins"]
                    or e["losses"] != g["losses"]
                    or not _float_equal(float(e["win_rate"]), float(g["win_rate"]))
                    or e["kills"] != g["kills"]
                    or e["deaths"] != g["deaths"]
                    or not _float_equal(float(e["kd_ratio"]), float(g["kd_ratio"]))
                ):
                    all_vals_ok = False
                    break
        if all_vals_ok:
            scores["stats_summary_values_correct"] = 1.0

    # Meeting notes checks
    notes_txt = _read_text_safe(meeting_notes_path)
    if notes_txt is not None:
        scores["meeting_notes_exists"] = 1.0
        notes_l = notes_txt.lower()
        # Coverage of expected action items from transcript
        patterns = [
            "ascent attack",            # "Review Ascent attack strats"
            "rematch vs northside",     # "schedule a rematch vs Northside HS"
            "collect povs",             # "Collect POVs..."
            "shorten callouts",         # "Comms..."
            "flick drills",             # "15m flick drills"
            "map win rates",            # "Create a one-page recap of map win rates"
            "default on bind",          # "try new default on Bind"
            "coach-approved quiz",      # "share coach-approved quiz"
        ]
        coverage = all(p in notes_l for p in patterns)
        scores["meeting_notes_action_coverage"] = 1.0 if coverage else 0.0
        # Fields and TBD
        task_count = len(re.findall(r"\btask\s*:", notes_l))
        owner_count = len(re.findall(r"\bowner\s*:", notes_l))
        due_count = len(re.findall(r"\bdue[_\s]?date\s*:", notes_l))
        context_count = len(re.findall(r"\bcontext\s*:", notes_l))
        has_tbd = "tbd" in notes_l
        fields_ok = task_count >= 8 and owner_count >= task_count and due_count >= task_count and context_count >= task_count and has_tbd
        scores["meeting_notes_fields_and_tbd"] = 1.0 if fields_ok else 0.0

    # Email rewrite checks
    email_rewrite = _read_text_safe(email_rewrite_path)
    if email_rewrite is not None:
        scores["email_rewrite_exists"] = 1.0
        # Subject and length
        lines = [ln.strip() for ln in email_rewrite.splitlines() if ln.strip() != ""]
        first_line = lines[0] if lines else ""
        has_subject = first_line.lower().startswith("subject:")
        # Count words
        words = re.findall(r"\b\w+\b", email_rewrite)
        word_count = len(words)
        length_ok = 120 <= word_count <= 160
        scores["email_rewrite_subject_and_length"] = 1.0 if (has_subject and length_ok) else 0.0
        # Tone constraints: remove slang/dismissive terms
        banned_substrings = ["lol", "retro", "ancient", "fwiw", " u ", "\nu ", "\tu "]
        tone_ok = True
        low = email_rewrite.lower()
        for b in banned_substrings:
            if b in low:
                tone_ok = False
                break
        scores["email_rewrite_tone_constraints"] = 1.0 if tone_ok else 0.0
        # Request intact: permission/approval + data + quiz + share
        contains_quiz = "quiz" in low
        contains_data = "data" in low
        contains_share = "share" in low or "sharing" in low
        contains_permission = any(x in low for x in ["permission", "approve", "approval", "consent", "authorization"])
        request_ok = contains_quiz and contains_data and contains_share and contains_permission
        scores["email_rewrite_request_intact"] = 1.0 if request_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()