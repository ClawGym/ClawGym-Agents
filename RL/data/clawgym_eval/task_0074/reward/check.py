import sys
import json
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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


def _parse_int_safe(v: str) -> Optional[int]:
    try:
        return int(v.strip())
    except Exception:
        return None


def _parse_csv_laps(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                try:
                    laps = {
                        "lap": int(row["lap"]),
                        "lap_time_ms": int(row["lap_time_ms"]),
                        "sector1_ms": int(row.get("sector1_ms", 0)),
                        "sector2_ms": int(row.get("sector2_ms", 0)),
                        "sector3_ms": int(row.get("sector3_ms", 0)),
                        "status": (row.get("status") or "").strip(),
                        "tyre": (row.get("tyre") or "").strip(),
                    }
                    rows.append(laps)
                except Exception:
                    return None
            return rows
    except Exception:
        return None


def _strip_yaml_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_event_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    event = None
    track = None
    date = None
    sessions: List[Dict[str, str]] = []
    current_sess: Optional[Dict[str, str]] = None
    in_sessions = False
    lines = text.splitlines()
    for line in lines:
        raw = line
        line = line.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        # top-level keys
        if not line.startswith(" ") and ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = _strip_yaml_quotes(val.strip())
            if key == "event":
                event = val
            elif key == "track":
                track = val
            elif key == "date":
                date = val
            elif key == "sessions":
                in_sessions = True
                if current_sess:
                    sessions.append(current_sess)
                    current_sess = None
            else:
                # ignore unknown keys
                pass
            continue
        if in_sessions:
            stripped = line.lstrip()
            if stripped.startswith("-"):
                # new session item
                if current_sess:
                    sessions.append(current_sess)
                current_sess = {}
                # may have inline key after "- "
                after_dash = stripped[1:].strip()
                if after_dash:
                    if ":" in after_dash:
                        k, v = after_dash.split(":", 1)
                        k = k.strip()
                        v = _strip_yaml_quotes(v.strip())
                        current_sess[k] = v
            else:
                if ":" in stripped:
                    k, v = stripped.split(":", 1)
                    k = k.strip()
                    v = _strip_yaml_quotes(v.strip())
                    if current_sess is None:
                        current_sess = {}
                    current_sess[k] = v
    if current_sess:
        sessions.append(current_sess)
    if event is None or track is None or date is None:
        return None
    return {"event": event, "track": track, "date": date, "sessions": sessions}


def _format_ms_to_msssss(ms: int) -> str:
    if ms < 0:
        ms = 0
    minutes = ms // 60000
    rem = ms % 60000
    seconds = rem // 1000
    millis = rem % 1000
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _compute_session_stats(csv_path: Path) -> Optional[Dict[str, Any]]:
    rows = _parse_csv_laps(csv_path)
    if rows is None:
        return None
    total_laps = len(rows)
    valid_rows = [r for r in rows if r.get("status") == "valid"]
    invalid_laps = total_laps - len(valid_rows)
    valid_lap_times = [r["lap_time_ms"] for r in valid_rows]
    if valid_rows:
        best_lap_ms = min(valid_lap_times)
        # find lap number associated with first occurrence of best
        best_lap_number = None
        for r in valid_rows:
            if r["lap_time_ms"] == best_lap_ms:
                best_lap_number = r["lap"]
                break
        avg_valid = int(round(sum(valid_lap_times) / len(valid_lap_times)))
        top3 = sorted(valid_lap_times)[:3]
    else:
        best_lap_ms = None
        best_lap_number = None
        avg_valid = None
        top3 = []
    # tyre breakdown from valid laps
    tyres: Dict[str, List[int]] = {}
    for r in valid_rows:
        tyre = r.get("tyre") or ""
        tyres.setdefault(tyre, []).append(r["lap_time_ms"])
    tyre_breakdown: Dict[str, Dict[str, int]] = {}
    for tyre, times in tyres.items():
        if times:
            avg_ms = int(round(sum(times) / len(times)))
        else:
            avg_ms = None  # should not happen
        tyre_breakdown[tyre] = {"laps": len(times), "avg_ms": avg_ms}
    return {
        "total_laps": total_laps,
        "valid_laps": len(valid_rows),
        "invalid_laps": invalid_laps,
        "best_lap_ms": best_lap_ms,
        "best_lap_number": best_lap_number,
        "avg_valid_lap_ms": avg_valid,
        "top3_valid_laps_ms": sorted(top3),
        "tyre_breakdown": tyre_breakdown,
    }


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    # Load roster (driver)
    roster_path = workspace / "input" / "roster.json"
    roster = _load_json(roster_path)
    if roster is None or not isinstance(roster, dict) or "driver" not in roster:
        return None
    driver = roster.get("driver", {})
    if not isinstance(driver, dict):
        return None
    driver_full_name = driver.get("full_name")
    driver_car_number = driver.get("car_number")
    driver_team = driver.get("team")
    if driver_full_name is None or driver_car_number is None or driver_team is None:
        return None
    # Load event.yaml
    event_yaml_path = workspace / "input" / "event.yaml"
    event_data = _parse_event_yaml(event_yaml_path)
    if event_data is None:
        return None
    event_name = event_data["event"]
    track = event_data["track"]
    date = event_data["date"]
    sessions_yaml = event_data.get("sessions", [])
    if not isinstance(sessions_yaml, list) or len(sessions_yaml) < 1:
        return None
    # Compute expected per session
    expected_sessions: List[Dict[str, Any]] = []
    for sess in sessions_yaml:
        fpath = sess.get("file")
        label = sess.get("label")
        if not fpath or not label:
            return None
        csv_path = workspace / fpath
        stats = _compute_session_stats(csv_path)
        if stats is None:
            return None
        expected_sessions.append({
            "file": fpath,
            "label": label,
            **stats,
        })
    # Compute improvement (session2 faster positive)
    improvement = None
    if len(expected_sessions) >= 2:
        b1 = expected_sessions[0]["best_lap_ms"]
        b2 = expected_sessions[1]["best_lap_ms"]
        if isinstance(b1, int) and isinstance(b2, int):
            improvement = b1 - b2
    return {
        "driver": {
            "full_name": driver_full_name,
            "car_number": driver_car_number,
            "team": driver_team,
        },
        "event": {
            "name": event_name,
            "track": track,
            "date": date,
        },
        "sessions": expected_sessions,
        "best_lap_improvement_ms": improvement,
    }


def _extract_talking_points_from_notes(notes_text: str) -> List[str]:
    points: List[str] = []
    for line in notes_text.splitlines():
        stripped = line.strip()
        # match "- [tag] content"
        m = re.match(r"^-+\s*\[([A-Za-z]+)\]\s*(.+)$", stripped)
        if m:
            tag = m.group(1).lower()
            content = m.group(2).strip()
            if tag in {"sponsor", "highlight"}:
                points.append(content)
    return points


def _find_section_bullets(md_text: str, section_name: str) -> Optional[List[str]]:
    # Find a section by heading that contains section_name (case-insensitive),
    # then collect subsequent bullet lines until a non-bullet encountered.
    lines = md_text.splitlines()
    idx = -1
    target = section_name.lower()
    for i, line in enumerate(lines):
        if target in line.strip().lower():
            idx = i
            break
    if idx == -1:
        return None
    bullets: List[str] = []
    for j in range(idx + 1, len(lines)):
        line = lines[j]
        if re.match(r"^\s*-\s+", line):
            # collect bullet content after "- "
            content = re.sub(r"^\s*-\s+", "", line).strip()
            bullets.append(content)
        else:
            # stop when bullet sequence ends (but allow blank lines to be skipped)
            if line.strip() == "":
                continue
            else:
                break
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "metrics_json_present_and_parseable": 0.0,
        "metrics_driver_event_fields_correct": 0.0,
        "metrics_sessions_files_and_labels_correct": 0.0,
        "metrics_session1_stats_correct": 0.0,
        "metrics_session2_stats_correct": 0.0,
        "metrics_improvement_correct": 0.0,
        "metrics_tyre_breakdown_session1_correct": 0.0,
        "metrics_tyre_breakdown_session2_correct": 0.0,
        "sponsor_update_present_and_nonempty": 0.0,
        "sponsor_update_identifiers_present": 0.0,
        "sponsor_update_session1_bullet_includes_stats": 0.0,
        "sponsor_update_session2_bullet_includes_stats": 0.0,
        "sponsor_update_improvement_delta_present_and_correct": 0.0,
        "sponsor_update_talking_points_correct": 0.0,
    }

    expected = _compute_expected(workspace)

    # Load actual metrics.json
    metrics_path = workspace / "output" / "metrics.json"
    actual_metrics = _load_json(metrics_path)
    if isinstance(actual_metrics, dict):
        scores["metrics_json_present_and_parseable"] = 1.0

    # Validate metrics structure and values
    if expected is not None and isinstance(actual_metrics, dict):
        # driver & event fields
        act_driver = actual_metrics.get("driver", {})
        act_event = actual_metrics.get("event", {})
        try:
            drv_ok = (
                isinstance(act_driver, dict)
                and act_driver.get("full_name") == expected["driver"]["full_name"]
                and act_driver.get("car_number") == expected["driver"]["car_number"]
                and act_driver.get("team") == expected["driver"]["team"]
            )
            evt_ok = (
                isinstance(act_event, dict)
                and act_event.get("name") == expected["event"]["name"]
                and act_event.get("track") == expected["event"]["track"]
                and act_event.get("date") == expected["event"]["date"]
            )
            if drv_ok and evt_ok:
                scores["metrics_driver_event_fields_correct"] = 1.0
        except Exception:
            pass

        # sessions files and labels
        act_sessions = actual_metrics.get("sessions")
        sess_files_labels_ok = False
        if isinstance(act_sessions, list) and len(act_sessions) == len(expected["sessions"]):
            sess_files_labels_ok = True
            for i, exp_sess in enumerate(expected["sessions"]):
                act = act_sessions[i] if i < len(act_sessions) else None
                if not isinstance(act, dict):
                    sess_files_labels_ok = False
                    break
                if act.get("file") != exp_sess["file"] or act.get("label") != exp_sess["label"]:
                    sess_files_labels_ok = False
                    break
        if sess_files_labels_ok:
            scores["metrics_sessions_files_and_labels_correct"] = 1.0

        # per-session stats and tyre breakdown
        if isinstance(act_sessions, list) and len(act_sessions) >= 2:
            # Session 1
            try:
                act1 = act_sessions[0]
                exp1 = expected["sessions"][0]
                s1_ok = (
                    act1.get("total_laps") == exp1["total_laps"]
                    and act1.get("valid_laps") == exp1["valid_laps"]
                    and act1.get("invalid_laps") == exp1["invalid_laps"]
                    and act1.get("best_lap_ms") == exp1["best_lap_ms"]
                    and act1.get("best_lap_number") == exp1["best_lap_number"]
                    and act1.get("avg_valid_lap_ms") == exp1["avg_valid_lap_ms"]
                    and act1.get("top3_valid_laps_ms") == exp1["top3_valid_laps_ms"]
                )
                if s1_ok:
                    scores["metrics_session1_stats_correct"] = 1.0
                # Tyre breakdown session1 exact match
                tb1_act = act1.get("tyre_breakdown")
                tb1_exp = exp1["tyre_breakdown"]
                tb1_ok = isinstance(tb1_act, dict) and tb1_act == tb1_exp
                if tb1_ok:
                    scores["metrics_tyre_breakdown_session1_correct"] = 1.0
            except Exception:
                pass
            # Session 2
            try:
                act2 = act_sessions[1]
                exp2 = expected["sessions"][1]
                s2_ok = (
                    act2.get("total_laps") == exp2["total_laps"]
                    and act2.get("valid_laps") == exp2["valid_laps"]
                    and act2.get("invalid_laps") == exp2["invalid_laps"]
                    and act2.get("best_lap_ms") == exp2["best_lap_ms"]
                    and act2.get("best_lap_number") == exp2["best_lap_number"]
                    and act2.get("avg_valid_lap_ms") == exp2["avg_valid_lap_ms"]
                    and act2.get("top3_valid_laps_ms") == exp2["top3_valid_laps_ms"]
                )
                if s2_ok:
                    scores["metrics_session2_stats_correct"] = 1.0
                tb2_act = act2.get("tyre_breakdown")
                tb2_exp = exp2["tyre_breakdown"]
                tb2_ok = isinstance(tb2_act, dict) and tb2_act == tb2_exp
                if tb2_ok:
                    scores["metrics_tyre_breakdown_session2_correct"] = 1.0
            except Exception:
                pass

        # improvement
        try:
            exp_imp = expected.get("best_lap_improvement_ms")
            act_imp = actual_metrics.get("best_lap_improvement_ms")
            if isinstance(exp_imp, int) and act_imp == exp_imp:
                scores["metrics_improvement_correct"] = 1.0
        except Exception:
            pass

    # Sponsor update checks
    sponsor_path = workspace / "output" / "sponsor_update.md"
    sponsor_text = _read_text(sponsor_path)
    if sponsor_text is not None and sponsor_text.strip():
        scores["sponsor_update_present_and_nonempty"] = 1.0

    if expected is not None and sponsor_text is not None:
        # identifiers present
        identifiers_ok = True
        needed_substrings = [
            expected["event"]["name"],
            expected["event"]["track"],
            expected["event"]["date"],
            expected["driver"]["full_name"],
            expected["driver"]["team"],
        ]
        for s in needed_substrings:
            if s not in sponsor_text:
                identifiers_ok = False
                break
        # car number presence: allow plain "22" or "#22" or "No. 22"
        car_no = str(expected["driver"]["car_number"])
        if re.search(rf"(#|No\.?\s*)?{re.escape(car_no)}\b", sponsor_text) is None:
            identifiers_ok = False
        if identifiers_ok:
            scores["sponsor_update_identifiers_present"] = 1.0

        # session bullets contain stats and label
        # Compute expected time strings and counts
        exp_sess1 = expected["sessions"][0]
        exp_sess2 = expected["sessions"][1] if len(expected["sessions"]) > 1 else None

        def check_session_in_bullets(label: str, best_ms: int, avg_ms: int, valid: int, total: int) -> bool:
            # find bullet lines that include the session label
            bullet_lines = [ln for ln in sponsor_text.splitlines() if re.match(r"^\s*-\s+", ln)]
            lines_with_label = [ln for ln in bullet_lines if label in ln]
            if not lines_with_label:
                return False
            best_str = _format_ms_to_msssss(best_ms)
            avg_str = _format_ms_to_msssss(avg_ms)
            vt_str = f"{valid}/{total}"
            # check that across these lines, best, avg, and valid/total appear
            blob = "\n".join(lines_with_label)
            ok = (best_str in blob) and (avg_str in blob) and (vt_str in blob)
            return ok

        if isinstance(exp_sess1.get("best_lap_ms"), int) and isinstance(exp_sess1.get("avg_valid_lap_ms"), int):
            if check_session_in_bullets(
                exp_sess1["label"],
                exp_sess1["best_lap_ms"],
                exp_sess1["avg_valid_lap_ms"],
                exp_sess1["valid_laps"],
                exp_sess1["total_laps"],
            ):
                scores["sponsor_update_session1_bullet_includes_stats"] = 1.0

        if exp_sess2 and isinstance(exp_sess2.get("best_lap_ms"), int) and isinstance(exp_sess2.get("avg_valid_lap_ms"), int):
            if check_session_in_bullets(
                exp_sess2["label"],
                exp_sess2["best_lap_ms"],
                exp_sess2["avg_valid_lap_ms"],
                exp_sess2["valid_laps"],
                exp_sess2["total_laps"],
            ):
                scores["sponsor_update_session2_bullet_includes_stats"] = 1.0

        # improvement delta line
        if isinstance(expected.get("best_lap_improvement_ms"), int):
            delta_ms = expected["best_lap_improvement_ms"]
            delta_s = delta_ms / 1000.0
            delta_str = f"{delta_s:.3f} s"
            if delta_str in sponsor_text:
                scores["sponsor_update_improvement_delta_present_and_correct"] = 1.0

        # Sponsor talking points section
        notes_path = workspace / "input" / "notes.md"
        notes_text = _read_text(notes_path)
        if notes_text is not None:
            expected_points = _extract_talking_points_from_notes(notes_text)
            bullets = _find_section_bullets(sponsor_text, "Sponsor talking points")
            if bullets is not None:
                # Ensure bullets equal expected points exactly and no tags present
                no_tags = all("[" not in b and "]" not in b for b in bullets)
                if bullets == expected_points and no_tags:
                    scores["sponsor_update_talking_points_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()