import csv
import json
import re
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None  # type: ignore


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _parse_simple_yaml_preferences(yaml_text: str) -> Optional[Dict[str, Any]]:
    prefs: Dict[str, Any] = {}
    lines = [ln.rstrip("\n") for ln in yaml_text.splitlines()]
    i = 0
    current_section: Optional[str] = None
    scoring_section: Optional[str] = None
    awards_section = False

    prefs["allow_mental_health_themes"] = []
    prefs["exclude_tags"] = []
    prefs["scoring"] = {"awards_bonus": {}}

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1
        if not line or line.startswith("#"):
            continue

        if re.match(r"^allow_mental_health_themes:\s*$", line):
            current_section = "allow_mental_health_themes"
            scoring_section = None
            awards_section = False
            continue
        elif re.match(r"^exclude_tags:\s*$", line):
            current_section = "exclude_tags"
            scoring_section = None
            awards_section = False
            continue
        elif line.startswith("min_film_rating:"):
            current_section = None
            scoring_section = None
            awards_section = False
            try:
                val = int(line.split(":", 1)[1].strip())
                prefs["min_film_rating"] = val
            except Exception:
                return None
            continue
        elif re.match(r"^scoring:\s*$", line):
            current_section = None
            scoring_section = "scoring"
            awards_section = False
            continue

        if current_section in ("allow_mental_health_themes", "exclude_tags"):
            m = re.match(r"^- (.+)$", line)
            if m:
                item = m.group(1).strip()
                prefs[current_section].append(item)
                continue
            else:
                current_section = None

        if scoring_section == "scoring":
            if re.match(r"^awards_bonus:\s*$", line):
                awards_section = True
                continue
            if awards_section:
                m = re.match(r"^(winner|nominee|none):\s*([0-9.]+)\s*$", line.strip())
                if m:
                    key = m.group(1)
                    try:
                        val = float(m.group(2))
                    except Exception:
                        return None
                    prefs["scoring"]["awards_bonus"][key] = val
                    continue
                else:
                    awards_section = False

            m = re.match(r"^(film_rating_weight|alignment_weight|engagement_weight):\s*([0-9.]+)\s*$", line.strip())
            if m:
                key = m.group(1)
                try:
                    val = float(m.group(2))
                except Exception:
                    return None
                prefs["scoring"][key] = val
                continue

    required_scoring = ["film_rating_weight", "alignment_weight", "engagement_weight"]
    if "min_film_rating" not in prefs:
        return None
    for k in required_scoring:
        if k not in prefs["scoring"]:
            return None
    for k in ["winner", "nominee", "none"]:
        if k not in prefs["scoring"]["awards_bonus"]:
            return None
    return prefs


def _parse_iso_datetime_aware(s: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return None
        return dt
    except Exception:
        return None


def _expected_screening_datetime(screening_date: str, screening_time: str, tz_name: str) -> Optional[datetime]:
    try:
        if ZoneInfo is None:
            return None
        tz = ZoneInfo(tz_name)
        y, m, d = [int(x) for x in screening_date.split("-")]
        hh, mm = [int(x) for x in screening_time.split(":")]
        return datetime(y, m, d, hh, mm, tzinfo=tz)
    except Exception:
        return None


def _read_screenings(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    path = workspace / "input" / "screenings.csv"
    rows = _safe_load_csv(path)
    if rows is None:
        return None
    out: List[Dict[str, Any]] = []
    try:
        for r in rows:
            tags = [t.strip() for t in (r.get("tags", "") or "").split(";") if t.strip()]
            out.append({
                "film_title": r.get("film_title", ""),
                "screening_date": r.get("screening_date", ""),
                "screening_time": r.get("screening_time", ""),
                "timezone": r.get("timezone", ""),
                "venue": r.get("venue", ""),
                "tags": tags,
                "film_rating": float(r.get("film_rating", "0") or "0"),
                "awards": (r.get("awards", "") or "").strip(),
                "mental_health_theme": (r.get("mental_health_theme", "") or "").strip(),
            })
    except Exception:
        return None
    return out


def _read_contacts(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    path = workspace / "input" / "contacts.json"
    data = _safe_load_json(path)
    if not isinstance(data, list):
        return None
    out: List[Dict[str, Any]] = []
    try:
        for c in data:
            out.append({
                "name": c.get("name", ""),
                "email": c.get("email", ""),
                "timezone": c.get("timezone", ""),
                "interest_tags": list(c.get("interest_tags", [])),
                "engagement_score": float(c.get("engagement_score", 0.0)),
                "notify_window_days": int(c.get("notify_window_days", 0)),
                "follow_up_window_days": int(c.get("follow_up_window_days", 0)),
            })
    except Exception:
        return None
    return out


def _read_preferences(workspace: Path) -> Optional[Dict[str, Any]]:
    path = workspace / "input" / "preferences.yaml"
    text = _safe_read_text(path)
    if text is None:
        return None
    return _parse_simple_yaml_preferences(text)


def _alignment_for_pair(film_theme: str, film_tags: List[str], contact_tags: List[str], allowed_themes: List[str]) -> float:
    film_theme = (film_theme or "").strip()
    ct_set = set(t.strip().lower() for t in contact_tags)
    film_tags_set = set(t.strip().lower() for t in film_tags)
    if film_theme.lower() in ct_set:
        return 1.0
    if ct_set.intersection(film_tags_set):
        return 0.8
    if film_theme and film_theme in allowed_themes:
        return 0.5
    return 0.0


def _priority_score(film_rating: float, alignment: float, engagement: float, weights: Dict[str, float], awards: str, awards_bonus: Dict[str, float]) -> float:
    fr_w = weights.get("film_rating_weight", 0.0)
    al_w = weights.get("alignment_weight", 0.0)
    en_w = weights.get("engagement_weight", 0.0)
    bonus = awards_bonus.get((awards or "").strip(), 0.0)
    return fr_w * (film_rating / 10.0) + al_w * alignment + en_w * engagement + bonus


def _load_schedule(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    path = workspace / "outputs" / "reminder_schedule.csv"
    rows = _safe_load_csv(path)
    if rows is None:
        return None
    return rows


def _check_required_columns(rows: List[Dict[str, Any]], required: List[str]) -> bool:
    if not rows:
        return False
    headers = set(rows[0].keys())
    for r in required:
        if r not in headers:
            return False
    return True


def _parse_date(s: str) -> Optional[date]:
    try:
        y, m, d = [int(x) for x in s.split("-")]
        return date(y, m, d)
    except Exception:
        return None


def _build_expected_pairs(screenings: List[Dict[str, Any]], contacts: List[Dict[str, Any]], prefs: Dict[str, Any]) -> List[Tuple[str, str]]:
    allow = set(prefs.get("allow_mental_health_themes", []))
    min_rating = float(prefs.get("min_film_rating", 0))
    exclude = set([t.lower() for t in prefs.get("exclude_tags", [])])

    included_films: List[Dict[str, Any]] = []
    for f in screenings:
        theme_allowed = (f["mental_health_theme"] in allow)
        rating_ok = (f.get("film_rating", 0.0) >= min_rating)
        tags = set([t.lower() for t in f.get("tags", [])])
        excluded = bool(exclude.intersection(tags))
        if theme_allowed and rating_ok and not excluded:
            included_films.append(f)

    pairs: List[Tuple[str, str]] = []
    for c in contacts:
        for f in included_films:
            pairs.append((c["email"], f["film_title"]))
    return pairs


def _get_contact_by_email(contacts: List[Dict[str, Any]], email: str) -> Optional[Dict[str, Any]]:
    for c in contacts:
        if c.get("email") == email:
            return c
    return None


def _get_film_by_title(screenings: List[Dict[str, Any]], title: str) -> Optional[Dict[str, Any]]:
    for f in screenings:
        if f.get("film_title") == title:
            return f
    return None


def _check_sorting(rows: List[Dict[str, Any]]) -> bool:
    parsed: List[Tuple[Optional[datetime], float]] = []
    for r in rows:
        send_on_str = r.get("send_on", "")
        send_dt = _parse_iso_datetime_aware(send_on_str)
        try:
            p = float(r.get("priority_score", "nan"))
        except Exception:
            p = float("nan")
        parsed.append((send_dt, p))
    if any(dt is None for dt, _ in parsed):
        return False
    ok = True
    for i in range(1, len(parsed)):
        prev_dt, prev_p = parsed[i - 1]
        cur_dt, cur_p = parsed[i]
        assert prev_dt is not None and cur_dt is not None
        if cur_dt < prev_dt:
            ok = False
            break
        if cur_dt == prev_dt and cur_p > prev_p:
            ok = False
            break
    return ok


def _latest_run_log(log_dir: Path) -> Optional[Path]:
    if not log_dir.exists() or not log_dir.is_dir():
        return None
    candidates = []
    for p in log_dir.glob("run_*.txt"):
        m = re.match(r"run_(\d{12})\.txt$", p.name)
        if m:
            candidates.append(p)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "reminder_schedule_exists_and_columns": 0.0,
        "reminder_schedule_filtering_and_pairs_count": 0.0,
        "reminder_schedule_actions_and_counts": 0.0,
        "reminder_schedule_screening_datetime_format": 0.0,
        "reminder_schedule_send_on_correctness": 0.0,
        "reminder_schedule_priority_score_correctness": 0.0,
        "reminder_schedule_sorting": 0.0,
        "reminder_schedule_template_path": 0.0,
        "updated_template_placeholders_preserved": 0.0,
        "updated_template_rsvp_and_boundary_note": 0.0,
        "generate_messages_script_present": 0.0,
        "messages_files_generated": 0.0,
        "messages_placeholders_filled": 0.0,
        "run_log_exists_and_includes_paths": 0.0,
        "run_log_action_counts_correct": 0.0,
    }

    screenings = _read_screenings(workspace) or []
    contacts = _read_contacts(workspace) or []
    prefs = _read_preferences(workspace)

    schedule_rows = _load_schedule(workspace)
    required_cols = [
        "contact_email",
        "contact_name",
        "film_title",
        "screening_datetime",
        "action",
        "send_on",
        "priority_score",
        "reason",
        "template_path",
    ]
    if schedule_rows is not None and _check_required_columns(schedule_rows, required_cols):
        scores["reminder_schedule_exists_and_columns"] = 1.0

    if schedule_rows is not None and prefs is not None and screenings and contacts:
        expected_pairs = _build_expected_pairs(screenings, contacts, prefs)
        expected_total_rows = len(expected_pairs) * 2
        pair_to_actions: Dict[Tuple[str, str], List[str]] = {}
        for r in schedule_rows:
            pair = (r.get("contact_email", ""), r.get("film_title", ""))
            act = r.get("action", "")
            pair_to_actions.setdefault(pair, []).append(act)
        all_pairs_ok = True
        for pair in expected_pairs:
            acts = pair_to_actions.get(pair, [])
            if sorted(acts) != ["follow_up", "reminder"]:
                all_pairs_ok = False
                break
        only_expected = set(pair_to_actions.keys()).issubset(set(expected_pairs))
        if all_pairs_ok and only_expected and len(schedule_rows) == expected_total_rows:
            scores["reminder_schedule_filtering_and_pairs_count"] = 1.0

        actions = [r.get("action", "") for r in schedule_rows]
        rem_count = actions.count("reminder")
        fu_count = actions.count("follow_up")
        if rem_count == fu_count == (len(schedule_rows) // 2) and set(actions) <= {"reminder", "follow_up"}:
            scores["reminder_schedule_actions_and_counts"] = 1.0

        correct_screening_dt = True
        for r in schedule_rows:
            film_title = r.get("film_title", "")
            f = _get_film_by_title(screenings, film_title)
            if not f:
                correct_screening_dt = False
                break
            expected_dt = _expected_screening_datetime(f["screening_date"], f["screening_time"], f["timezone"])
            sd_str = r.get("screening_datetime", "")
            parsed = _parse_iso_datetime_aware(sd_str)
            if expected_dt is None or parsed is None:
                if expected_dt is None and parsed is not None:
                    try:
                        parts = sd_str.split("T")
                        if len(parts) < 2:
                            correct_screening_dt = False
                            break
                        dpart = parts[0]
                        tpart = parts[1]
                        if dpart != f["screening_date"]:
                            correct_screening_dt = False
                            break
                        if not tpart.startswith(f["screening_time"]):
                            correct_screening_dt = False
                            break
                    except Exception:
                        correct_screening_dt = False
                        break
                else:
                    correct_screening_dt = False
                    break
            else:
                if parsed.replace(second=0, microsecond=0) != expected_dt.replace(second=0, microsecond=0):
                    correct_screening_dt = False
                    break
        if correct_screening_dt:
            scores["reminder_schedule_screening_datetime_format"] = 1.0

        send_on_ok = True
        for r in schedule_rows:
            email = r.get("contact_email", "")
            contact = _get_contact_by_email(contacts, email)
            film_title = r.get("film_title", "")
            film = _get_film_by_title(screenings, film_title)
            action = r.get("action", "")
            send_on_str = r.get("send_on", "")
            if not contact or not film or action not in ("reminder", "follow_up"):
                send_on_ok = False
                break

            sc_date = film.get("screening_date", "")
            sc_d = _parse_date(sc_date)
            if sc_d is None:
                send_on_ok = False
                break
            days_delta = contact["notify_window_days"] if action == "reminder" else contact["follow_up_window_days"]
            if not isinstance(days_delta, int):
                try:
                    days_delta = int(days_delta)
                except Exception:
                    send_on_ok = False
                    break
            if action == "reminder":
                target_date = sc_d - timedelta(days=days_delta)
            else:
                target_date = sc_d + timedelta(days=days_delta)

            if ZoneInfo is None:
                if (target_date.isoformat() not in send_on_str) or ("T10:00" not in send_on_str):
                    send_on_ok = False
                    break
            else:
                try:
                    tz = ZoneInfo(contact.get("timezone", ""))
                except Exception:
                    send_on_ok = False
                    break
                expected_dt = datetime(target_date.year, target_date.month, target_date.day, 10, 0, tzinfo=tz)
                parsed_so = _parse_iso_datetime_aware(send_on_str)
                if parsed_so is None:
                    send_on_ok = False
                    break
                if parsed_so != expected_dt:
                    send_on_ok = False
                    break
        if send_on_ok:
            scores["reminder_schedule_send_on_correctness"] = 1.0

        pr_ok = True
        for r in schedule_rows:
            email = r.get("contact_email", "")
            film_title = r.get("film_title", "")
            contact = _get_contact_by_email(contacts, email)
            film = _get_film_by_title(screenings, film_title)
            if not contact or not film:
                pr_ok = False
                break
            alignment = _alignment_for_pair(
                film.get("mental_health_theme", ""),
                film.get("tags", []),
                contact.get("interest_tags", []),
                prefs.get("allow_mental_health_themes", []),
            )
            expected_score = _priority_score(
                film.get("film_rating", 0.0),
                alignment,
                contact.get("engagement_score", 0.0),
                prefs.get("scoring", {}),
                film.get("awards", ""),
                prefs.get("scoring", {}).get("awards_bonus", {}),
            )
            try:
                got = float(r.get("priority_score", "nan"))
            except Exception:
                pr_ok = False
                break
            if not (abs(got - expected_score) <= 1e-6):
                pr_ok = False
                break
            reason = r.get("reason", "")
            if not isinstance(reason, str) or len(reason.strip()) == 0:
                pr_ok = False
                break
        if pr_ok:
            scores["reminder_schedule_priority_score_correctness"] = 1.0

        if _check_sorting(schedule_rows):
            scores["reminder_schedule_sorting"] = 1.0

        tpath_ok = all(r.get("template_path", "") == "outputs/updated_email_template.md" for r in schedule_rows)
        if tpath_ok:
            scores["reminder_schedule_template_path"] = 1.0

    updated_tpl_path = workspace / "outputs" / "updated_email_template.md"
    updated_tpl_text = _safe_read_text(updated_tpl_path) or ""
    placeholders = ["{name}", "{film_title}", "{date}", "{time}", "{venue}", "{theme}"]
    if updated_tpl_text:
        if all(ph in updated_tpl_text for ph in placeholders):
            scores["updated_template_placeholders_preserved"] = 1.0
        lower = updated_tpl_text.lower()
        has_rsvp = ("rsvp" in lower)
        boundary_a = ("not therapy" in lower) or ("discussion" in lower and "therapy" in lower and "not" in lower)
        boundary_b = ("personal" in lower) and (("clinical" in lower) or ("private" in lower)) and (("share" in lower) or ("shared" in lower) or ("sharing" in lower))
        if has_rsvp and boundary_a and boundary_b:
            scores["updated_template_rsvp_and_boundary_note"] = 1.0

    script_path = workspace / "scripts" / "generate_messages.py"
    if script_path.exists() and script_path.is_file():
        scores["generate_messages_script_present"] = 1.0

    messages_ok = False
    placeholders_filled_ok = False
    log_exists_ok = False
    log_counts_ok = False
    if schedule_rows is not None and len(schedule_rows) > 0:
        all_exist = True
        all_filled = True
        for r in schedule_rows:
            email = r.get("contact_email", "")
            action = r.get("action", "")
            film_title = r.get("film_title", "")
            msg_path = workspace / "outputs" / "messages" / email / f"{action}_{film_title}.md"
            if not msg_path.exists():
                all_exist = False
                break
            content = _safe_read_text(msg_path) or ""
            if any(ph in content for ph in ["{name}", "{film_title}", "{date}", "{time}", "{venue}", "{theme}"]):
                all_filled = False
                break
        if all_exist:
            messages_ok = True
            scores["messages_files_generated"] = 1.0
        if all_exist and all_filled:
            placeholders_filled_ok = True
            scores["messages_placeholders_filled"] = 1.0

        log_dir = workspace / "outputs" / "logs"
        latest_log = _latest_run_log(log_dir)
        if latest_log and latest_log.exists():
            text = _safe_read_text(latest_log) or ""
            if text:
                paths_listed = True
                for r in schedule_rows:
                    email = r.get("contact_email", "")
                    action = r.get("action", "")
                    film_title = r.get("film_title", "")
                    rel_path = f"outputs/messages/{email}/{action}_{film_title}.md"
                    if rel_path not in text:
                        paths_listed = False
                        break
                if paths_listed:
                    log_exists_ok = True
                    scores["run_log_exists_and_includes_paths"] = 1.0

                rem_matches = re.findall(r"reminder[^0-9]*([0-9]+)", text, flags=re.IGNORECASE)
                fu_matches = re.findall(r"follow[_ ]?up[^0-9]*([0-9]+)", text, flags=re.IGNORECASE)
                if rem_matches and fu_matches:
                    try:
                        rem_count_in_log = int(rem_matches[-1])
                        fu_count_in_log = int(fu_matches[-1])
                        rem_count_exp = sum(1 for r in schedule_rows if r.get("action") == "reminder")
                        fu_count_exp = sum(1 for r in schedule_rows if r.get("action") == "follow_up")
                        if rem_count_in_log == rem_count_exp and fu_count_in_log == fu_count_exp:
                            log_counts_ok = True
                            scores["run_log_action_counts_correct"] = 1.0
                    except Exception:
                        pass

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()