import json
import csv
import re
import sys
import ast
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_yaml_scalar(path: Path, key: str) -> Optional[str]:
    text = _read_text(path)
    if text is None:
        return None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.+?)\s*$")
    for line in text.splitlines():
        m = pattern.match(line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def _extract_function_docstring(py_path: Path, function_name: str) -> Optional[str]:
    try:
        text = _read_text(py_path)
        if text is None:
            return None
        node = ast.parse(text)
        for child in node.body:
            if isinstance(child, ast.FunctionDef) and child.name == function_name:
                return ast.get_docstring(child)
        for child in ast.walk(node):
            if isinstance(child, ast.FunctionDef) and child.name == function_name:
                return ast.get_docstring(child)
        return None
    except Exception:
        return None


def _parse_notes_file(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    lines = text.splitlines()
    data: Dict[str, Any] = {
        "meeting": None,
        "date": None,
        "participants": [],
        "agenda": [],
        "decisions": [],
        "action_items": [],
        "notes": [],
    }

    for i, line in enumerate(lines):
        if line.startswith("Meeting:"):
            data["meeting"] = line.split(":", 1)[1].strip()
        if line.startswith("Date:"):
            date_str = line.split(":", 1)[1].strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                data["date"] = date_str
        if line.startswith("Participants:"):
            participants_str = line.split(":", 1)[1].strip()
            parts = [p.strip() for p in participants_str.split(";") if p.strip()]
            data["participants"] = parts

    if data["date"] is None:
        return None

    def extract_bullets(start_label: str) -> List[str]:
        bullets: List[str] = []
        start_idx = None
        for idx, line in enumerate(lines):
            if line.strip() == f"{start_label}:":
                start_idx = idx + 1
                break
        if start_idx is None:
            return bullets
        for j in range(start_idx, len(lines)):
            l = lines[j]
            if re.match(r"^[A-Za-z].+:$", l.strip()) and l.strip() != f"{start_label}:":
                break
            if l.strip().startswith("-"):
                item = l.strip()[1:].strip()
                bullets.append(item)
        return bullets

    data["agenda"] = extract_bullets("Agenda")
    data["decisions"] = extract_bullets("Decisions")
    data["action_items"] = extract_bullets("Action items")
    data["notes"] = extract_bullets("Notes")

    return data


def _collect_meetings(notes_dir: Path) -> List[Dict[str, Any]]:
    meetings: List[Dict[str, Any]] = []
    if not notes_dir.exists():
        return meetings
    for p in sorted(notes_dir.glob("*.txt")):
        text = _read_text(p)
        if text is None:
            continue
        parsed = _parse_notes_file(text)
        if parsed is None:
            continue
        meetings.append(parsed)
    try:
        meetings.sort(key=lambda m: m["date"])
    except Exception:
        pass
    return meetings


def _expected_latest_and_previous(meetings: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not meetings:
        return None, None
    latest = meetings[-1]
    prev = meetings[-2] if len(meetings) >= 2 else None
    return latest, prev


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "output_dir_exists": 0.0,
        "summary_json_exists": 0.0,
        "summary_json_parseable": 0.0,
        "meeting_date_correct": 0.0,
        "participants_list_valid": 0.0,
        "agenda_matches": 0.0,
        "decisions_match": 0.0,
        "context_previous_meeting_date_correct": 0.0,
        "context_previous_decisions_match": 0.0,
        "action_items_present_and_structured": 0.0,
        "action_items_count_correct": 0.0,
        "action_item_references_include_expected_files": 0.0,
        "verification_statuses_correct": 0.0,
        "verification_evidence_present_and_relevant": 0.0,
        "notes_highlights_array_present": 0.0,
        "notes_highlights_cover_leakage": 0.0,
        "notes_highlights_cover_vgate": 0.0,
        "action_items_csv_exists": 0.0,
        "action_items_csv_columns_correct": 0.0,
        "action_items_csv_rows_consistent": 0.0,
    }

    notes_dir = workspace / "input" / "notes"
    meetings = _collect_meetings(notes_dir)
    latest, prev = _expected_latest_and_previous(meetings)

    if latest is None:
        return scores

    latest_date = latest.get("date")
    latest_agenda = latest.get("agenda", [])
    latest_decisions = latest.get("decisions", [])
    latest_notes = latest.get("notes", [])
    latest_participants = latest.get("participants", [])

    prev_date = prev.get("date") if prev else None
    prev_decisions = prev.get("decisions") if prev else None

    depo_yaml_path = workspace / "input" / "config" / "deposition.yaml"
    sim_json_path = workspace / "input" / "config" / "sim_config.json"
    model_py_path = workspace / "input" / "models" / "quantum_tunnel_model.py"

    anneal_current = _parse_yaml_scalar(depo_yaml_path, "anneal_temp_c")
    pitch_current_value = None
    sim_config = _load_json(sim_json_path)
    if isinstance(sim_config, dict):
        pitch_current_value = sim_config.get("nanowire_pitch_nm")
    docstring = _extract_function_docstring(model_py_path, "estimate_tunneling_current")

    expected_status = {
        "anneal": None,
        "pitch": None,
        "doc": None,
    }
    if anneal_current is not None:
        try:
            anneal_int = int(str(anneal_current).replace("C", "").strip())
        except Exception:
            anneal_int = None
        expected_status["anneal"] = "satisfied" if anneal_int == 375 else "pending"
    if pitch_current_value is not None:
        try:
            pitch_int = int(pitch_current_value)
        except Exception:
            pitch_int = None
        expected_status["pitch"] = "satisfied" if pitch_int == 16 else "pending"
    if docstring is not None:
        expected_status["doc"] = "satisfied" if ("WKB" in docstring) else "pending"

    output_dir = workspace / "output" / f"meeting_{latest_date}"
    if output_dir.exists() and output_dir.is_dir():
        scores["output_dir_exists"] = 1.0

    summary_json_path = output_dir / "summary.json"
    action_items_csv_path = output_dir / "action_items.csv"

    summary = _load_json(summary_json_path) if summary_json_path.exists() else None
    if summary_json_path.exists():
        scores["summary_json_exists"] = 1.0
    if summary is not None and isinstance(summary, dict):
        scores["summary_json_parseable"] = 1.0

    if isinstance(summary, dict):
        if summary.get("meeting_date") == latest_date:
            scores["meeting_date_correct"] = 1.0

        participants = summary.get("participants")
        if isinstance(participants, list) and participants:
            joined = " ".join(str(x) for x in participants).lower()
            required_names = ["alex", "maya", "ken", "priya"]
            if all(name in joined for name in required_names):
                scores["participants_list_valid"] = 1.0

        if isinstance(summary.get("agenda"), list) and summary.get("agenda") == latest_agenda:
            scores["agenda_matches"] = 1.0

        if isinstance(summary.get("decisions"), list) and summary.get("decisions") == latest_decisions:
            scores["decisions_match"] = 1.0

        context = summary.get("context")
        if isinstance(context, dict):
            if prev_date and context.get("previous_meeting_date") == prev_date:
                scores["context_previous_meeting_date_correct"] = 1.0
            if isinstance(prev_decisions, list) and context.get("previous_decisions") == prev_decisions:
                scores["context_previous_decisions_match"] = 1.0

        highlights = summary.get("notes_highlights")
        if isinstance(highlights, list):
            scores["notes_highlights_array_present"] = 1.0
            leak_ok = False
            vgate_ok = False
            for h in highlights:
                hl = str(h).lower()
                if ("leakage" in hl) and ("12" in hl):
                    leak_ok = True
                if ("vgate" in hl) or ("0.7" in hl) or ("sim_config.json" in hl.lower()):
                    vgate_ok = True
            if leak_ok:
                scores["notes_highlights_cover_leakage"] = 1.0
            if vgate_ok:
                scores["notes_highlights_cover_vgate"] = 1.0

        ai = summary.get("action_items")
        structured_ok = False
        count_ok = False
        refs_ok = False
        status_ok = False
        evidence_ok = False
        if isinstance(ai, list):
            if len(ai) == 3:
                count_ok = True
            required_fields = {"description", "owner", "due_date", "references", "verification_status", "verification_evidence"}
            structured_ok = all(isinstance(item, dict) and required_fields.issubset(item.keys()) for item in ai)

            def find_item_by_tokens(tokens: List[str]) -> Optional[Dict[str, Any]]:
                for item in ai:
                    desc = str(item.get("description", ""))
                    if all(t.lower() in desc.lower() for t in tokens):
                        return item
                return None

            anneal_item = find_item_by_tokens(["anneal_temp_c", "375"])
            pitch_item = find_item_by_tokens(["nanowire_pitch_nm", "16"])
            doc_item = find_item_by_tokens(["estimate_tunneling_current", "wkb"])

            refs_ok = True
            if anneal_item:
                refs = anneal_item.get("references")
                if not (isinstance(refs, list) and any(str(x) == "input/config/deposition.yaml" for x in refs)):
                    refs_ok = False
            else:
                refs_ok = False

            if pitch_item:
                refs = pitch_item.get("references")
                if not (isinstance(refs, list) and any(str(x) == "input/config/sim_config.json" for x in refs)):
                    refs_ok = False
            else:
                refs_ok = False

            if doc_item:
                refs = doc_item.get("references")
                if not (isinstance(refs, list) and any(str(x) == "input/models/quantum_tunnel_model.py" for x in refs)):
                    refs_ok = False
            else:
                refs_ok = False

            status_ok = True
            evidence_ok = True

            if anneal_item:
                owner_ok = str(anneal_item.get("owner", "")).lower() == "maya"
                due_ok = anneal_item.get("due_date") == "2026-04-20"
                vs = anneal_item.get("verification_status")
                vs_expected = expected_status["anneal"]
                vs_ok = (vs == vs_expected) if vs_expected is not None else False
                ev = str(anneal_item.get("verification_evidence", ""))
                ev_ok = bool(ev) and ("360" in ev or "anneal_temp_c" in ev)
                if not (owner_ok and due_ok and vs_ok and ev_ok):
                    status_ok = False
                if not ev_ok:
                    evidence_ok = False
            else:
                status_ok = False
                evidence_ok = False

            if pitch_item:
                owner_ok = str(pitch_item.get("owner", "")).lower() == "ken"
                due_ok = pitch_item.get("due_date") == "2026-04-18"
                vs = pitch_item.get("verification_status")
                vs_expected = expected_status["pitch"]
                vs_ok = (vs == vs_expected) if vs_expected is not None else False
                ev = str(pitch_item.get("verification_evidence", ""))
                ev_ok = bool(ev) and ("18" in ev or "nanowire_pitch_nm" in ev)
                if not (owner_ok and due_ok and vs_ok and ev_ok):
                    status_ok = False
                if not ev_ok:
                    evidence_ok = False
            else:
                status_ok = False
                evidence_ok = False

            if doc_item:
                owner_ok = str(doc_item.get("owner", "")).lower() == "alex"
                due_ok = doc_item.get("due_date") in (None, "", "null", "None")
                vs = doc_item.get("verification_status")
                vs_expected = expected_status["doc"]
                vs_ok = (vs == vs_expected) if vs_expected is not None else False
                ev = str(doc_item.get("verification_evidence", ""))
                ev_ok = bool(ev) and ("WKB" in ev or "wkb" in ev)
                if not (owner_ok and due_ok and vs_ok and ev_ok):
                    status_ok = False
                if not ev_ok:
                    evidence_ok = False
            else:
                status_ok = False
                evidence_ok = False

        if structured_ok:
            scores["action_items_present_and_structured"] = 1.0
        if count_ok:
            scores["action_items_count_correct"] = 1.0
        if refs_ok:
            scores["action_item_references_include_expected_files"] = 1.0
        if status_ok:
            scores["verification_statuses_correct"] = 1.0
        if evidence_ok:
            scores["verification_evidence_present_and_relevant"] = 1.0

    if action_items_csv_path.exists():
        scores["action_items_csv_exists"] = 1.0
        try:
            with action_items_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                if header == ["owner", "description", "due_date", "verification_status"]:
                    scores["action_items_csv_columns_correct"] = 1.0
                items = rows[1:]
                found = {"anneal": None, "pitch": None, "doc": None}
                for r in items:
                    if len(r) < 4:
                        continue
                    owner, desc, due, status = r[0], r[1], r[2], r[3]
                    dlow = desc.lower()
                    if "anneal_temp_c" in dlow and "375" in dlow:
                        found["anneal"] = (owner, due, status, desc)
                    elif "nanowire_pitch_nm" in dlow and "16" in dlow:
                        found["pitch"] = (owner, due, status, desc)
                    elif "estimate_tunneling_current" in dlow and "wkb" in dlow:
                        found["doc"] = (owner, due, status, desc)
                consistent = True
                if found["anneal"] is None:
                    consistent = False
                else:
                    owner, due, status, _ = found["anneal"]
                    if owner.lower() != "maya":
                        consistent = False
                    if due != "2026-04-20":
                        consistent = False
                    if expected_status["anneal"] is None or status != expected_status["anneal"]:
                        consistent = False
                if found["pitch"] is None:
                    consistent = False
                else:
                    owner, due, status, _ = found["pitch"]
                    if owner.lower() != "ken":
                        consistent = False
                    if due != "2026-04-18":
                        consistent = False
                    if expected_status["pitch"] is None or status != expected_status["pitch"]:
                        consistent = False
                if found["doc"] is None:
                    consistent = False
                else:
                    owner, due, status, _ = found["doc"]
                    if owner.lower() != "alex":
                        consistent = False
                    if due not in ("", "null", "None"):
                        consistent = False
                    if expected_status["doc"] is None or status != expected_status["doc"]:
                        consistent = False

                if consistent:
                    scores["action_items_csv_rows_consistent"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()