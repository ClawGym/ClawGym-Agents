import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _normalize_heading(line: str) -> str:
    # Remove leading # and spaces, then strip
    s = line.lstrip("#").strip()
    return s


def _extract_sections_md(text: str, expected_headings: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """
    Returns a dict mapping heading->content (string including newlines) and a list of headings found in order.
    Headings are lines that normalize exactly to one of expected_headings.
    """
    lines = text.splitlines()
    positions = []
    for idx, line in enumerate(lines):
        norm = _normalize_heading(line)
        if norm in expected_headings:
            positions.append((idx, norm))
    sections = {}
    order = []
    for i, (idx, name) in enumerate(positions):
        start = idx + 1
        end = positions[i + 1][0] if i + 1 < len(positions) else len(lines)
        content = "\n".join(lines[start:end]).strip()
        sections[name] = content
        order.append(name)
    return sections, order


def _parse_meeting_context(text: str) -> Dict[str, str]:
    data = {}
    for line in text.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            data[key] = val
    return data


def _parse_notes(text: str) -> Dict[str, Any]:
    """
    Parses hematology_notes.md to extract:
    - terms list with fields from Topic/Term/Definition/Mnemonic/Links
    - questions list (strings without 'Q:' tag, stripped)
    - todos list (strings without 'TODO:' tag, stripped)
    """
    lines = text.splitlines()
    current_topic = None
    terms = []
    questions = []
    todos = []

    i = 0
    while i < len(lines):
        raw = lines[i].strip()
        if raw.startswith("Topic:"):
            current_topic = raw[len("Topic:"):].strip()
            i += 1
            continue
        if raw.startswith("Q:"):
            questions.append(raw[len("Q:"):].strip())
            i += 1
            continue
        if raw.startswith("TODO:"):
            todos.append(raw[len("TODO:"):].strip())
            i += 1
            continue
        if raw.startswith("Term:"):
            term_name = raw[len("Term:"):].strip()
            definition = None
            mnemonic = None
            links: List[str] = []
            # scan subsequent lines until next Term: or Topic: or EOF
            j = i + 1
            while j < len(lines):
                r2 = lines[j].strip()
                if r2.startswith("Topic:") or r2.startswith("Term:"):
                    break
                if r2.startswith("Definition:"):
                    definition = r2[len("Definition:"):].strip()
                elif r2.startswith("Mnemonic:"):
                    mnemonic_val = r2[len("Mnemonic:"):].strip()
                    mnemonic = mnemonic_val if mnemonic_val != "" else None
                elif r2.startswith("Links:"):
                    links_str = r2[len("Links:"):].strip()
                    if links_str == "":
                        links = []
                    else:
                        links = [s.strip() for s in links_str.split(",")]
                # ignore Q: and TODO: for terms data here
                j += 1
            terms.append({
                "topic": current_topic if current_topic is not None else "",
                "term": term_name,
                "definition": definition if definition is not None else "",
                "mnemonic": mnemonic if mnemonic is not None else None,
                "links": links,
            })
            i = j
            continue
        i += 1

    return {"terms": terms, "questions": questions, "todos": todos}


def _safe_float(x: str) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _safe_date(x: str) -> Optional[datetime]:
    # Expect ISO date YYYY-MM-DD
    try:
        return datetime.strptime(x.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _compute_progress_metrics(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    hours_vals = []
    ratings = []
    topics = []
    for r in rows:
        h = _safe_float(r.get("hours", ""))
        if h is None:
            return {}
        hours_vals.append(h)
        c = _safe_float(r.get("comprehension_rating", ""))
        if c is None:
            return {}
        ratings.append(c)
        topics.append(r.get("topic", "").strip())
    total_hours = sum(hours_vals) if hours_vals else 0.0
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0.0
    unique_topics = list(dict.fromkeys(topics).keys())
    count_logs = len(rows)
    return {
        "total_hours": total_hours,
        "avg_rating_1dp": f"{avg_rating:.1f}",
        "unique_topics": unique_topics,
        "count_logs": count_logs,
    }


def _recently_completed(rows: List[Dict[str, str]], n: int = 3) -> List[Dict[str, Any]]:
    rows_with_date = []
    for r in rows:
        d = _safe_date(r.get("date", ""))
        if d is None:
            return []
        rows_with_date.append((d, r))
    rows_sorted = sorted(rows_with_date, key=lambda x: x[0])
    recent = [r for _, r in rows_sorted[-n:]]
    # Normalize fields for checking
    out = []
    for r in recent:
        out.append({
            "topic": r.get("topic", "").strip(),
            "hours": r.get("hours", "").strip(),
            "comprehension_rating": r.get("comprehension_rating", "").strip(),
        })
    return out


def _compute_gaps(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    """
    Returns a dict: topic -> { "avg_rating": float, "has_outstanding": bool, "include": bool }
    Include if avg_rating < 3 or has_outstanding True
    """
    from collections import defaultdict
    topic_hours = defaultdict(list)
    topic_ratings = defaultdict(list)
    topic_outstanding_any = defaultdict(bool)
    for r in rows:
        topic = r.get("topic", "").strip()
        c = _safe_float(r.get("comprehension_rating", ""))
        if c is None:
            return {}
        topic_ratings[topic].append(c)
        ot = r.get("outstanding_tasks", "")
        if ot is not None and ot.strip() != "":
            topic_outstanding_any[topic] = True or topic_outstanding_any[topic]
    gaps = {}
    for topic in set(list(topic_ratings.keys()) + list(topic_outstanding_any.keys())):
        ratings = topic_ratings.get(topic, [])
        avg = sum(ratings) / len(ratings) if ratings else 0.0
        has_ot = bool(topic_outstanding_any.get(topic, False))
        include = (avg < 3.0) or has_ot
        gaps[topic] = {"avg_rating": avg, "has_outstanding": has_ot, "include": include}
    return gaps


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "concepts_json_parses_and_shape": 0.0,
        "concepts_terms_count_match": 0.0,
        "concepts_terms_fields_match": 0.0,
        "questions_todos_json_parses_and_shape": 0.0,
        "questions_list_match": 0.0,
        "todos_list_match": 0.0,
        "progress_report_has_sections": 0.0,
        "progress_report_metrics_correct": 0.0,
        "progress_report_recently_completed_correct": 0.0,
        "progress_report_gaps_next_focus_correct": 0.0,
        "meeting_notes_has_sections": 0.0,
        "meeting_info_matches_context": 0.0,
        "meeting_agenda_uses_questions_and_gaps": 0.0,
        "meeting_action_items_minimum_and_fields": 0.0,
        "meeting_action_items_due_date_and_owner_valid": 0.0,
        "meeting_action_items_origins_valid": 0.0,
    }

    # Load inputs
    notes_path = workspace / "input" / "hematology_notes.md"
    study_log_path = workspace / "input" / "study_log.csv"
    meeting_context_path = workspace / "input" / "meeting_context.txt"

    notes_text = _read_text(notes_path)
    study_rows = _parse_csv_dicts(study_log_path)
    meeting_context_text = _read_text(meeting_context_path)

    # Prepare expected from notes
    expected_terms = []
    expected_questions: List[str] = []
    expected_todos: List[str] = []
    if notes_text is not None:
        parsed_notes = _parse_notes(notes_text)
        expected_terms = parsed_notes.get("terms", [])
        expected_questions = parsed_notes.get("questions", [])
        expected_todos = parsed_notes.get("todos", [])

    # 1) Validate output/concepts.json
    concepts_path = workspace / "output" / "concepts.json"
    concepts_data = _load_json(concepts_path)
    shape_ok = False
    if concepts_data is not None and isinstance(concepts_data, dict) and "terms" in concepts_data and isinstance(concepts_data["terms"], list):
        shape_ok = True
    scores["concepts_json_parses_and_shape"] = 1.0 if shape_ok else 0.0

    if shape_ok and notes_text is not None:
        out_terms = concepts_data["terms"]
        # Count match
        count_match = float(len(out_terms) == len(expected_terms))
        scores["concepts_terms_count_match"] = count_match

        # Fields match: compare each expected dict to corresponding out dict strictly
        if len(out_terms) == len(expected_terms) and len(expected_terms) > 0:
            correct = 0
            for exp, got in zip(expected_terms, out_terms):
                # Ensure keys exist and types correct
                ok = (
                    isinstance(got, dict)
                    and got.get("topic") == exp.get("topic")
                    and got.get("term") == exp.get("term")
                    and got.get("definition") == exp.get("definition")
                    and ("mnemonic" in got)
                    and (got.get("mnemonic") == exp.get("mnemonic"))
                    and isinstance(got.get("links"), list)
                    and got.get("links") == exp.get("links")
                )
                if ok:
                    correct += 1
            scores["concepts_terms_fields_match"] = correct / len(expected_terms)
        elif len(expected_terms) == 0:
            # If there were no terms to expect (empty notes), consider fields match as 1 if out_terms is empty
            scores["concepts_terms_fields_match"] = 1.0 if len(out_terms) == 0 else 0.0
        else:
            scores["concepts_terms_fields_match"] = 0.0
    else:
        # If inputs missing or shape bad, leave zeros
        pass

    # 2) Validate output/questions_todos.json
    qt_path = workspace / "output" / "questions_todos.json"
    qt_data = _load_json(qt_path)
    qt_shape_ok = False
    if isinstance(qt_data, dict) and "questions" in qt_data and "todos" in qt_data and isinstance(qt_data["questions"], list) and isinstance(qt_data["todos"], list):
        # Ensure all elements are strings
        if all(isinstance(x, str) for x in qt_data["questions"]) and all(isinstance(x, str) for x in qt_data["todos"]):
            qt_shape_ok = True
    scores["questions_todos_json_parses_and_shape"] = 1.0 if qt_shape_ok else 0.0

    if qt_shape_ok and notes_text is not None:
        # Strict match with expected order and content
        scores["questions_list_match"] = 1.0 if qt_data["questions"] == expected_questions else 0.0
        scores["todos_list_match"] = 1.0 if qt_data["todos"] == expected_todos else 0.0

    # 3) Validate output/progress_report.md
    pr_path = workspace / "output" / "progress_report.md"
    pr_text = _read_text(pr_path)
    expected_pr_headings = ["Summary", "Metrics", "Recently Completed", "Gaps and Next Focus"]
    sections = {}
    order = []
    if pr_text is not None:
        sections, order = _extract_sections_md(pr_text, expected_pr_headings)
        # Check all expected headings present and in order
        has_all_sections = all(h in sections for h in expected_pr_headings)
        in_order = [h for h in order if h in expected_pr_headings] == expected_pr_headings
        scores["progress_report_has_sections"] = 1.0 if (has_all_sections and in_order) else 0.0

    # Metrics correctness
    metrics_score = 0.0
    recently_score = 0.0
    gaps_score = 0.0
    if study_rows is not None and pr_text is not None:
        metrics = _compute_progress_metrics(study_rows)
        if metrics:
            metrics_content = sections.get("Metrics", "")
            checks = 0
            passed = 0

            # total hours: search for exact numeric string (allow both int-like and one decimal)
            total_hours_str = f"{metrics['total_hours']:.1f}"
            checks += 1
            if total_hours_str in metrics_content:
                passed += 1

            # avg rating to one decimal
            avg_str = metrics["avg_rating_1dp"]
            checks += 1
            if avg_str in metrics_content:
                passed += 1

            # unique topics: each topic should appear by name
            checks += 1
            if all(t in metrics_content for t in metrics["unique_topics"]):
                passed += 1

            # count of log entries
            checks += 1
            if str(metrics["count_logs"]) in metrics_content:
                passed += 1

            metrics_score = passed / checks if checks > 0 else 0.0

        # Recently Completed
        recent_expected = _recently_completed(study_rows, n=3)
        rc_content = sections.get("Recently Completed", "") if sections else ""
        if recent_expected and rc_content:
            rc_pass = 0
            for item in recent_expected:
                # Check that topic, hours, and comprehension_rating appear
                if (item["topic"] in rc_content and item["hours"] in rc_content and item["comprehension_rating"] in rc_content):
                    rc_pass += 1
            recently_score = rc_pass / len(recent_expected) if recent_expected else 0.0

        # Gaps and Next Focus
        gaps = _compute_gaps(study_rows)
        gf_content = sections.get("Gaps and Next Focus", "") if sections else ""
        if gaps and gf_content:
            # Determine expected included topics
            expected_gap_topics = [t for t, info in gaps.items() if info.get("include")]
            # All expected topics must be present by name
            present_topics = all(t in gf_content for t in expected_gap_topics) if expected_gap_topics else True
            # Ensure reasons are mentioned: either "outstanding" for outstanding tasks condition, or indication of low (<3)
            reason_indicators = []
            for t in expected_gap_topics:
                info = gaps[t]
                indicators = []
                if info.get("has_outstanding"):
                    indicators.append("outstanding")
                if info.get("avg_rating", 0) < 3.0:
                    indicators.append("low")  # accept generic 'low' indication
                    indicators.append("< 3")
                    indicators.append("below 3")
                reason_indicators.extend(indicators)
            # For robustness: require that at least one 'outstanding' appears if any topic had outstanding tasks,
            # and at least one of ('low', '< 3', 'below 3') appears if any topic had avg < 3
            need_outstanding = any(gaps[t]["has_outstanding"] for t in expected_gap_topics)
            need_low = any(gaps[t]["avg_rating"] < 3.0 for t in expected_gap_topics)
            outstanding_ok = (("outstanding" in gf_content.lower()) if need_outstanding else True)
            low_ok = (("low" in gf_content.lower()) or ("< 3" in gf_content) or ("below 3" in gf_content)) if need_low else True

            gaps_score = 1.0 if (present_topics and outstanding_ok and low_ok) else 0.0

    scores["progress_report_metrics_correct"] = metrics_score
    scores["progress_report_recently_completed_correct"] = recently_score
    scores["progress_report_gaps_next_focus_correct"] = gaps_score

    # 4) Validate output/meeting_notes.md
    mn_path = workspace / "output" / "meeting_notes.md"
    mn_text = _read_text(mn_path)
    expected_mn_headings = ["Meeting Info", "Agenda", "Action Items"]
    mn_sections = {}
    mn_order = []
    if mn_text is not None:
        mn_sections, mn_order = _extract_sections_md(mn_text, expected_mn_headings)
        has_all_mn = all(h in mn_sections for h in expected_mn_headings)
        in_order_mn = [h for h in mn_order if h in expected_mn_headings] == expected_mn_headings
        scores["meeting_notes_has_sections"] = 1.0 if (has_all_mn and in_order_mn) else 0.0

    # Meeting Info matches context
    meeting_info_score = 0.0
    meeting_date_str = None
    due_date_str = None
    allowed_owners = set()
    if mn_text is not None and meeting_context_text is not None:
        ctx = _parse_meeting_context(meeting_context_text)
        mi_content = mn_sections.get("Meeting Info", "") if mn_sections else ""
        title_ok = ctx.get("Meeting") in mi_content if ctx.get("Meeting") else False
        date_ok = ctx.get("Date") in mi_content if ctx.get("Date") else False
        attendees_ok = ctx.get("Attendees") in mi_content if ctx.get("Attendees") else False
        meeting_info_score = 1.0 if (title_ok and date_ok and attendees_ok) else 0.0

        # compute due date = meeting date + 14 days
        dt_raw = ctx.get("Date", "")
        # Extract date portion 'YYYY-MM-DD' from 'YYYY-MM-DD hh:mm'
        m = re.match(r"(\d{4}-\d{2}-\d{2})", dt_raw)
        if m:
            meeting_date_str = m.group(1)
            try:
                md = datetime.strptime(meeting_date_str, "%Y-%m-%d").date()
                due = md + timedelta(days=14)
                due_date_str = due.isoformat()
            except Exception:
                due_date_str = None

        # Allowed owners
        # From attendees names in context
        attendees = ctx.get("Attendees", "")
        # Expect 'Self (Alex), Peer (Sam)'
        allowed_owners = {"Self (Alex)", "Peer (Sam)"}

    scores["meeting_info_matches_context"] = meeting_info_score

    # Agenda uses questions and gaps
    agenda_score = 0.0
    if mn_text is not None:
        agenda_content = mn_sections.get("Agenda", "") if mn_sections else ""
        # Load questions from output/questions_todos.json if available
        if qt_data and isinstance(qt_data, dict):
            q_list = qt_data.get("questions", []) if isinstance(qt_data.get("questions", []), list) else []
        else:
            q_list = expected_questions
        # derive gaps topics from study rows
        gap_topics = []
        if study_rows is not None:
            gaps = _compute_gaps(study_rows)
            gap_topics = [t for t, info in gaps.items() if info.get("include")]
        # Check that at least one question appears and at least one gap topic appears
        has_question = any((q in agenda_content) for q in q_list) if q_list else False
        has_gap_topic = any((t in agenda_content) for t in gap_topics) if gap_topics else False
        if has_question and has_gap_topic:
            agenda_score = 1.0
    scores["meeting_agenda_uses_questions_and_gaps"] = agenda_score

    # Action items validation
    ai_min_fields_score = 0.0
    ai_due_owner_score = 0.0
    ai_origin_score = 0.0
    if mn_text is not None:
        ai_content = mn_sections.get("Action Items", "") if mn_sections else ""
        lines = ai_content.splitlines()
        # Parse items by 'Description:' start
        items = []
        current = None
        for ln in lines:
            l = ln.strip()
            if not l:
                continue
            if l.lower().startswith("description:"):
                # push previous
                if current:
                    items.append(current)
                current = {"Description": l.split(":", 1)[1].strip()}
            elif current is not None and l.lower().startswith("origin:"):
                current["Origin"] = l.split(":", 1)[1].strip()
            elif current is not None and l.lower().startswith("owner:"):
                current["Owner"] = l.split(":", 1)[1].strip()
            elif current is not None and l.lower().startswith("due date:"):
                current["Due Date"] = l.split(":", 1)[1].strip()
            else:
                # Non-key line; ignore
                continue
        if current:
            items.append(current)

        # Check minimum count and that each has required fields non-empty
        required_fields = ["Description", "Origin", "Owner", "Due Date"]
        if items:
            valid_field_items = [it for it in items if all((k in it and isinstance(it[k], str) and it[k].strip() != "") for k in required_fields)]
            ai_min_fields_score = 1.0 if (len(items) >= 5 and len(valid_field_items) >= 5) else 0.0

            # Due dates and owners
            if due_date_str is not None and allowed_owners:
                # Validate each of the first 5 valid items for due date and owner
                checks = 0
                passed = 0
                for it in valid_field_items[:5]:
                    checks += 1
                    owner_ok = it.get("Owner") in allowed_owners
                    due_ok = due_date_str in it.get("Due Date", "")
                    if owner_ok and due_ok:
                        passed += 1
                ai_due_owner_score = (passed / checks) if checks > 0 else 0.0

            # Origins validity: must match one of questions/todos (minus tags) or outstanding_tasks values
            allowed_origins = set()
            # From questions_todos.json if present
            if qt_data and isinstance(qt_data, dict):
                qs = qt_data.get("questions", [])
                ts = qt_data.get("todos", [])
                if isinstance(qs, list):
                    allowed_origins.update([q.strip() for q in qs if isinstance(q, str)])
                if isinstance(ts, list):
                    allowed_origins.update([t.strip() for t in ts if isinstance(t, str)])
            # Fallback/add from notes parsing
            allowed_origins.update([q.strip() for q in expected_questions])
            allowed_origins.update([t.strip() for t in expected_todos])
            # From study log outstanding_tasks non-empty
            if study_rows is not None:
                for r in study_rows:
                    ot = r.get("outstanding_tasks", "")
                    if ot is not None and ot.strip() != "":
                        allowed_origins.add(ot.strip())
            if allowed_origins:
                origin_checks = 0
                origin_pass = 0
                for it in valid_field_items[:5]:
                    origin_checks += 1
                    origin_ok = it.get("Origin", "").strip() in allowed_origins
                    if origin_ok:
                        origin_pass += 1
                ai_origin_score = (origin_pass / origin_checks) if origin_checks > 0 else 0.0

    scores["meeting_action_items_minimum_and_fields"] = ai_min_fields_score
    scores["meeting_action_items_due_date_and_owner_valid"] = ai_due_owner_score
    scores["meeting_action_items_origins_valid"] = ai_origin_score

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()