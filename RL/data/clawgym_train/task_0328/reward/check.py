import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _parse_subject(text: str) -> Optional[str]:
    # Extract the first "Subject:" header value
    for line in text.splitlines():
        if line.startswith("Subject:"):
            return line.split("Subject:", 1)[1].strip()
    return None


def _parse_forecasts_email(path: Path) -> Tuple[Optional[str], List[Dict[str, str]]]:
    """
    Returns (subject, list of records), where records have:
    name, position, xT_90, xGChain_90, Predicted_Minutes
    """
    text = _read_text(path)
    if text is None:
        return None, []
    subject = _parse_subject(text) or ""
    # Guard relevance
    if "Model Forecasts" not in subject:
        return subject, []
    # Extract rows from HTML table in tbody
    tbody_match = re.search(r"<tbody>(.*?)</tbody>", text, flags=re.S | re.I)
    records: List[Dict[str, str]] = []
    if not tbody_match:
        return subject, records
    tbody = tbody_match.group(1)
    # Find all <tr> rows
    for tr in re.findall(r"<tr>(.*?)</tr>", tbody, flags=re.S | re.I):
        tds = re.findall(r"<td>(.*?)</td>", tr, flags=re.S | re.I)
        if len(tds) != 5:
            continue
        name = re.sub(r"<.*?>", "", tds[0]).strip()
        position = re.sub(r"<.*?>", "", tds[1]).strip()
        xT = re.sub(r"<.*?>", "", tds[2]).strip()
        xGC = re.sub(r"<.*?>", "", tds[3]).strip()
        pm = re.sub(r"<.*?>", "", tds[4]).strip()
        records.append({
            "player": name,
            "position": position,
            "xT_90": xT,
            "xGChain_90": xGC,
            "Predicted_Minutes": pm,
        })
    return subject, records


def _parse_medical_email(path: Path) -> Tuple[Optional[str], Dict[str, Dict[str, str]]]:
    """
    Returns (subject, map[name_norm] = {"status": ..., "return_prob": ..., "minutes_cap": ...})
    """
    text = _read_text(path)
    if text is None:
        return None, {}
    subject = _parse_subject(text) or ""
    # Guard relevance
    if "Medical" not in subject:
        return subject, {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    data_started = False
    med_map: Dict[str, Dict[str, str]] = {}
    for ln in lines:
        if not data_started:
            # Detect header line
            if re.search(r"Player\s*-\s*Status\s*-\s*Return_Prob\s*-\s*Minutes_Cap", ln, flags=re.I):
                data_started = True
            continue
        parts = re.split(r"\s*-\s*", ln)
        if len(parts) != 4:
            continue
        name, status, return_prob, minutes_cap = [p.strip() for p in parts]
        med_map[_norm_name(name)] = {
            "status": status,
            "return_prob": return_prob,
            "minutes_cap": minutes_cap,
        }
    return subject, med_map


def _parse_training_email(path: Path) -> Tuple[Optional[str], Dict[str, str]]:
    """
    Returns (subject, map[name_norm] = risk_flag_text) with risk_flag_text in {"low","medium","high"}
    """
    text = _read_text(path)
    if text is None:
        return None, {}
    subject = _parse_subject(text) or ""
    # Guard relevance
    if "Training Load" not in subject:
        return subject, {}
    # Extract JSON object
    json_match = re.search(r"\{.*\}", text, flags=re.S)
    if not json_match:
        return subject, {}
    try:
        data = json.loads(json_match.group(0))
    except Exception:
        return subject, {}
    flag_map = {"green": "low", "amber": "medium", "red": "high"}
    out: Dict[str, str] = {}
    if isinstance(data, dict) and "players" in data and isinstance(data["players"], list):
        for p in data["players"]:
            try:
                nm = p.get("name", "")
                flag = p.get("flag", "")
                risk = flag_map.get(str(flag).strip().lower())
                if nm and risk:
                    out[_norm_name(nm)] = risk
            except Exception:
                continue
    return subject, out


def _extract_match_label_from_subject(subject: str) -> Optional[str]:
    # From "Model Forecasts - Matchday 7 (vs Riverdale)" -> "Matchday 7"
    m = re.search(r"Model Forecasts\s*-\s*([^\(]+)", subject)
    if m:
        return m.group(1).strip()
    return None


def _to_float(s: str) -> Optional[float]:
    try:
        if s is None or s == "":
            return None
        return float(s)
    except Exception:
        return None


def _to_int(s: str) -> Optional[int]:
    try:
        if s is None or s == "":
            return None
        # Allow float-like strings if integral (e.g., "85.0")
        v = float(s)
        if math.isfinite(v):
            return int(round(v))
        return None
    except Exception:
        return None


def _build_expected(emails_dir: Path) -> Tuple[bool, Dict[str, Dict[str, object]], List[str], Optional[str], List[str]]:
    """
    Returns:
    - success flag (True if sufficient inputs parsed),
    - expected_rows_map: key name_norm -> row dict for available players (>0 minutes),
    - expected_top5_ordered_names (display names) in order,
    - match_label,
    - allowed_subjects (subjects from relevant emails)
    """
    if not emails_dir.exists():
        return False, {}, [], None, []
    forecast_subject = None
    medical_subject = None
    training_subject = None
    forecast_records: List[Dict[str, str]] = []
    medical_map: Dict[str, Dict[str, str]] = {}
    training_map: Dict[str, str] = {}

    # Parse all .eml files and collect relevant
    for eml in sorted(emails_dir.glob("*.eml")):
        subj = None
        txt = _read_text(eml) or ""
        subj = _parse_subject(txt) or ""
        if "Model Forecasts" in subj:
            fs, fr = _parse_forecasts_email(eml)
            forecast_subject = fs
            forecast_records = fr
        elif "Medical" in subj:
            ms, mm = _parse_medical_email(eml)
            medical_subject = ms
            medical_map = mm
        elif "Training Load" in subj:
            ts, tm = _parse_training_email(eml)
            training_subject = ts
            training_map = tm
        else:
            # ignore logistics like travel update
            continue

    # Must have forecasts to proceed
    if forecast_subject is None or not forecast_records:
        return False, {}, [], None, []

    allowed_subjects = []
    if forecast_subject:
        allowed_subjects.append(forecast_subject)
    if medical_subject:
        allowed_subjects.append(medical_subject)
    if training_subject:
        allowed_subjects.append(training_subject)

    # Build per-player merged
    players: Dict[str, Dict[str, object]] = {}
    # First seed from forecasts
    for rec in forecast_records:
        name = rec.get("player", "").strip()
        if not name:
            continue
        norm = _norm_name(name)
        players[norm] = {
            "player": name,
            "position": rec.get("position", "").strip(),
            "xT_90": _to_float(rec.get("xT_90", "")),
            "xGChain_90": _to_float(rec.get("xGChain_90", "")),
            "Predicted_Minutes": _to_int(rec.get("Predicted_Minutes", "")),
            "status": "Unknown",
            "minutes_cap": None,
            "risk_flag": "Unknown",
            "source_emails": set([forecast_subject]) if forecast_subject else set(),
        }

    # Merge medical
    for norm_name, med in medical_map.items():
        if norm_name not in players:
            # If medical has a player not in forecasts, create partial?
            # According to inputs, all are in forecasts. We'll still create a stub to be safe.
            players[norm_name] = {
                "player": norm_name,  # fallback lower-case name
                "position": "",
                "xT_90": None,
                "xGChain_90": None,
                "Predicted_Minutes": None,
                "status": "Unknown",
                "minutes_cap": None,
                "risk_flag": "Unknown",
                "source_emails": set(),
            }
        row = players[norm_name]
        row["status"] = med.get("status", "Unknown")
        row["minutes_cap"] = _to_int(med.get("minutes_cap", ""))
        if medical_subject:
            row["source_emails"].add(medical_subject)

    # Merge training
    for norm_name, risk in training_map.items():
        if norm_name not in players:
            # training-only player (not expected here, but handle)
            players[norm_name] = {
                "player": norm_name,
                "position": "",
                "xT_90": None,
                "xGChain_90": None,
                "Predicted_Minutes": None,
                "status": "Unknown",
                "minutes_cap": None,
                "risk_flag": "Unknown",
                "source_emails": set(),
            }
        row = players[norm_name]
        row["risk_flag"] = risk if risk in ("low", "medium", "high") else "Unknown"
        if training_subject:
            row["source_emails"].add(training_subject)

    # Compute availability_minutes and filter > 0
    avail_players: Dict[str, Dict[str, object]] = {}
    for norm_name, row in players.items():
        status = row.get("status", "Unknown")
        pred_min = row.get("Predicted_Minutes")
        cap = row.get("minutes_cap")
        if isinstance(status, str) and status.strip() == "Out":
            availability = 0
        else:
            if pred_min is None and cap is None:
                availability = 0
            elif pred_min is not None and cap is not None:
                availability = min(int(pred_min), int(cap))
            elif pred_min is not None:
                availability = int(pred_min)
            else:
                availability = int(cap) if cap is not None else 0
        row["availability_minutes"] = int(availability)
        if row["availability_minutes"] > 0:
            # Build expected CSV row fields
            display_name = row["player"]
            # If display_name came from norm_name fallback, try to reconstruct nicer case
            if display_name == norm_name:
                # Title case fallback
                display_name = " ".join([w.capitalize() for w in norm_name.split()])
            avail_players[norm_name] = {
                "player": display_name,
                "position": row.get("position", ""),
                "status": status if isinstance(status, str) else "Unknown",
                "availability_minutes": int(row["availability_minutes"]),
                "xT_90": row.get("xT_90"),
                "xGChain_90": row.get("xGChain_90"),
                "risk_flag": row.get("risk_flag", "Unknown"),
                "source_emails": set([s for s in row.get("source_emails", set()) if s]),
            }

    # Ranking by xT_90 desc, tie by xGChain_90 desc
    def sort_key(item):
        _, r = item
        xt = r.get("xT_90")
        xgc = r.get("xGChain_90")
        # None considered as very small to push to end
        xtv = xt if isinstance(xt, (int, float)) else -1e18
        xgv = xgc if isinstance(xgc, (int, float)) else -1e18
        return (-xtv, -xgv)

    ordered = sorted(avail_players.items(), key=sort_key)
    top5_names = [r["player"] for _, r in ordered[:5]]

    match_label = _extract_match_label_from_subject(forecast_subject or "")

    return True, avail_players, top5_names, match_label, allowed_subjects


def _check_header(actual_cols: List[str], expected_cols: List[str]) -> bool:
    return actual_cols == expected_cols


def _parse_semicolon_subjects(cell: str) -> List[str]:
    if cell is None:
        return []
    parts = [p.strip() for p in str(cell).split(";")]
    parts = [p for p in parts if p]
    return parts


def _float_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "merged_csv_structure": 0.0,
        "merged_players_count_and_names": 0.0,
        "merged_values_correct": 0.0,
        "source_emails_ignore_logistics": 0.0,
        "top5_csv_structure": 0.0,
        "top5_order_and_values_correct": 0.0,
        "coach_digest_subject_correct": 0.0,
        "coach_digest_body_top5_correct": 0.0,
    }

    emails_dir = workspace / "input" / "emails"
    success, expected_map, expected_top5, match_label, allowed_subjects = _build_expected(emails_dir)

    # If we cannot compute expected due to missing inputs, return zeros
    merged_path = workspace / "output" / "merged_players.csv"
    top5_path = workspace / "output" / "player_ranking_top5.csv"
    digest_path = workspace / "output" / "coach_digest_email.txt"

    # Check merged CSV structure
    merged_rows = _safe_load_csv(merged_path)
    expected_cols = ["player", "position", "status", "availability_minutes", "xT_90", "xGChain_90", "risk_flag", "source_emails"]
    if merged_rows is not None:
        # Extract header from file
        try:
            with merged_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        if header and _check_header(header, expected_cols):
            scores["merged_csv_structure"] = 1.0

    # Check merged content names/count and values if expected available
    if success and merged_rows is not None and scores["merged_csv_structure"] > 0.0:
        # Build actual map
        actual_map: Dict[str, Dict[str, str]] = {}
        valid = True
        for row in merged_rows:
            nm = row.get("player", "")
            if not nm:
                valid = False
                break
            actual_map[_norm_name(nm)] = row
        if not valid:
            scores["merged_players_count_and_names"] = 0.0
            scores["merged_values_correct"] = 0.0
        else:
            expected_names = set(expected_map.keys())
            actual_names = set(actual_map.keys())
            if expected_names == actual_names and len(actual_names) == len(merged_rows):
                scores["merged_players_count_and_names"] = 1.0
            else:
                scores["merged_players_count_and_names"] = 0.0

            # Check per-player values, including source_emails, numeric types
            values_ok = True
            logistics_ok = True
            for norm_name, expected in expected_map.items():
                row = actual_map.get(norm_name)
                if row is None:
                    values_ok = False
                    break
                # position
                if row.get("position", "") != expected.get("position", ""):
                    values_ok = False
                    break
                # status
                if row.get("status", "") != expected.get("status", ""):
                    values_ok = False
                    break
                # availability_minutes integer
                av_actual = _to_int(row.get("availability_minutes", ""))
                if av_actual is None or av_actual != int(expected.get("availability_minutes", 0)):
                    values_ok = False
                    break
                # xT_90
                xt_actual = _to_float(row.get("xT_90", ""))
                if not _float_equal(xt_actual, expected.get("xT_90")):
                    values_ok = False
                    break
                # xGChain_90
                xgc_actual = _to_float(row.get("xGChain_90", ""))
                if not _float_equal(xgc_actual, expected.get("xGChain_90")):
                    values_ok = False
                    break
                # risk_flag
                if row.get("risk_flag", "") != expected.get("risk_flag", ""):
                    values_ok = False
                    break
                # source_emails content: compare as sets; ensure no logistics subjects
                actual_subjects = set(_parse_semicolon_subjects(row.get("source_emails", "")))
                expected_subjects = set(expected.get("source_emails", set()))
                # Canonicalize by trimming
                if actual_subjects != expected_subjects:
                    values_ok = False
                    break
                # Ensure none contain travel update
                for subj in actual_subjects:
                    if "Travel Update" in subj:
                        logistics_ok = False
                        break
                if not logistics_ok:
                    break
            scores["merged_values_correct"] = 1.0 if values_ok else 0.0
            scores["source_emails_ignore_logistics"] = 1.0 if logistics_ok else 0.0

    # Top5 CSV structure
    top5_rows = _safe_load_csv(top5_path)
    if top5_rows is not None:
        try:
            with top5_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        if header and _check_header(header, expected_cols):
            # must have exactly 5 rows
            if len(top5_rows) == 5:
                scores["top5_csv_structure"] = 1.0

    # Top5 order and values
    if success and top5_rows is not None and scores["top5_csv_structure"] > 0.0:
        # Verify order by xT_90 desc, tie xGChain_90 desc against expected_top5
        top5_ok = True
        # Build expected rows by norm name for quick lookup from merged (or expected_map)
        expected_by_display: Dict[str, Dict[str, object]] = {}
        for _, v in expected_map.items():
            expected_by_display[_norm_name(str(v.get("player", "")))] = v
        for idx, row in enumerate(top5_rows):
            if idx >= len(expected_top5):
                top5_ok = False
                break
            expected_name = expected_top5[idx]
            if _norm_name(row.get("player", "")) != _norm_name(expected_name):
                top5_ok = False
                break
            # Validate other fields against expected
            e = expected_by_display.get(_norm_name(expected_name))
            if e is None:
                top5_ok = False
                break
            if row.get("position", "") != e.get("position", ""):
                top5_ok = False
                break
            if row.get("status", "") != e.get("status", ""):
                top5_ok = False
                break
            av_actual = _to_int(row.get("availability_minutes", ""))
            if av_actual is None or av_actual != int(e.get("availability_minutes", 0)):
                top5_ok = False
                break
            if not _float_equal(_to_float(row.get("xT_90", "")), e.get("xT_90")):
                top5_ok = False
                break
            if not _float_equal(_to_float(row.get("xGChain_90", "")), e.get("xGChain_90")):
                top5_ok = False
                break
            if row.get("risk_flag", "") != e.get("risk_flag", ""):
                top5_ok = False
                break
            # source_emails sets equal
            actual_subjects = set(_parse_semicolon_subjects(row.get("source_emails", "")))
            expected_subjects = set(e.get("source_emails", set()))
            if actual_subjects != expected_subjects:
                top5_ok = False
                break
        scores["top5_order_and_values_correct"] = 1.0 if top5_ok else 0.0

    # Coach digest email
    digest_text = _read_text(digest_path)
    if success and digest_text is not None:
        lines = [ln.rstrip("\n") for ln in digest_text.splitlines()]
        if lines:
            subj_line = lines[0].strip()
            expected_subject_line = f"Subject: {match_label}" if match_label else None
            if expected_subject_line and subj_line == expected_subject_line:
                scores["coach_digest_subject_correct"] = 1.0
        # Parse body lines that match pattern "Name (Position) — xT_90, availability_minutes, status, risk_flag"
        body_lines = [ln for ln in lines[1:] if ln.strip()]
        # Regex: capture name, position, xt, avail, status, risk
        pattern = re.compile(r"^(?P<name>.+?) \((?P<pos>[^)]+)\) — (?P<xt>-?\d+(?:\.\d+)?),\s*(?P<av>\d+),\s*(?P<status>[^,]+),\s*(?P<risk>[A-Za-z]+)\s*$")
        extracted = []
        for ln in body_lines:
            m = pattern.match(ln.strip())
            if m:
                extracted.append(m.groupdict())
        body_ok = True
        if len(extracted) < 5:
            body_ok = False
        else:
            # Compare first 5 with expected order and values
            # Build expected map by norm name again
            expected_by_display: Dict[str, Dict[str, object]] = {}
            for _, v in expected_map.items():
                expected_by_display[_norm_name(str(v.get("player", "")))] = v
            for idx in range(5):
                item = extracted[idx]
                exp_name = expected_top5[idx] if idx < len(expected_top5) else None
                if exp_name is None:
                    body_ok = False
                    break
                if _norm_name(item["name"]) != _norm_name(exp_name):
                    body_ok = False
                    break
                e = expected_by_display.get(_norm_name(exp_name))
                if e is None:
                    body_ok = False
                    break
                if item["pos"] != e.get("position", ""):
                    body_ok = False
                    break
                # xT_90 float numeric comparison
                xt_val = _to_float(item["xt"])
                if not _float_equal(xt_val, e.get("xT_90")):
                    body_ok = False
                    break
                # availability int
                av_val = _to_int(item["av"])
                if av_val is None or av_val != int(e.get("availability_minutes", 0)):
                    body_ok = False
                    break
                # status exact
                if item["status"] != e.get("status", ""):
                    body_ok = False
                    break
                # risk exact
                if item["risk"] != e.get("risk_flag", ""):
                    body_ok = False
                    break
        scores["coach_digest_body_top5_correct"] = 1.0 if body_ok else 0.0
    else:
        # If we cannot compute expected, leave as 0.0
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()