import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _split_pipe(s: str) -> List[str]:
    if s is None:
        return []
    parts = [p.strip() for p in s.split("|") if p.strip() != ""]
    return parts


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _normalize_status(s: str) -> str:
    return (s or "").strip().lower()


def _normalize_tag_list(s: str) -> List[str]:
    return [t.strip().lower() for t in _split_pipe(s or "") if t.strip() != ""]


def _compute_expected_assignments(clients: List[Dict[str, str]], events: List[Dict[str, str]]) -> Dict[str, dict]:
    event_map = {}
    for e in events:
        try:
            event_map[e["event_id"]] = {
                "event_id": e["event_id"],
                "name": e["name"],
                "target_min_age": _parse_int(e["target_min_age"]),
                "target_max_age": _parse_int(e["target_max_age"]),
                "target_status": _normalize_status(e["target_status"]),
                "tags": _normalize_tag_list(e["tags"]),
                "event_date": e["event_date"],
                "event_time": e["event_time"],
                "location": e["location"],
            }
        except KeyError:
            continue

    assignments = {}
    for c in clients:
        cid = c.get("client_id", "")
        status = _normalize_status(c.get("status", ""))
        age = _parse_int(c.get("age", ""))
        ctags = _normalize_tag_list(c.get("tags", ""))

        scores = {}
        for ev_id, ev in event_map.items():
            score = 0
            if ev["target_status"] == "any" or ev["target_status"] == status:
                score += 2
            if age is not None and ev["target_min_age"] is not None and ev["target_max_age"] is not None:
                if ev["target_min_age"] <= age <= ev["target_max_age"]:
                    score += 1
            overlap = set(ctags) & set(ev["tags"])
            score += len(overlap)
            scores[ev_id] = score

        if not scores:
            rec_id = None
            total_score = 0
            was_tie = False
        else:
            max_score = max(scores.values()) if scores else 0
            winners = [ev for ev, sc in scores.items() if sc == max_score]
            if len(winners) != 1 or max_score == 0:
                rec_id = None
                total_score = 0
                was_tie = (len(winners) > 1 and max_score > 0)
            else:
                rec_id = winners[0]
                total_score = max_score
                was_tie = False

        rec_name = event_map[rec_id]["name"] if rec_id in event_map else ""
        assignments[cid] = {
            "client_id": cid,
            "recommended_event_id": rec_id,
            "recommended_event_name": rec_name,
            "total_score": total_score,
            "was_tie": was_tie,
            "next_suggested_day": (_split_pipe(c.get("preferred_days", ""))[:1] or [""])[0],
            "send_time_local": c.get("preferred_hour_local", ""),
            "timezone": c.get("timezone", ""),
        }
    return assignments


def _bool_from_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    sl = s.strip().lower()
    if sl == "true":
        return True
    if sl == "false":
        return False
    return None


def _find_contiguous_subsequence(haystack: List[str], needle: List[str]) -> bool:
    if not needle:
        return True
    n = len(needle)
    for i in range(0, len(haystack) - n + 1):
        if haystack[i:i + n] == needle:
            return True
    return False


def _load_inputs(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[Dict[str, str]]], Optional[str]]:
    clients_path = workspace / "input" / "clients.csv"
    events_path = workspace / "input" / "events.csv"
    brand_path = workspace / "input" / "brand_voice.txt"

    clients_rows, _ = _safe_read_csv(clients_path)
    events_rows, _ = _safe_read_csv(events_path)
    brand_voice = _safe_read_text(brand_path)
    return clients_rows, events_rows, brand_voice


def _validate_recommendations_header(fieldnames: Optional[List[str]]) -> bool:
    expected = [
        "client_id",
        "first_name",
        "last_name",
        "email",
        "recommended_event_id",
        "recommended_event_name",
        "total_score",
        "was_tie",
        "next_suggested_day",
        "send_time_local",
        "timezone",
        "email_file",
    ]
    return fieldnames == expected


def _collect_email_files(dir_path: Path) -> List[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    return sorted([p for p in dir_path.iterdir() if p.is_file() and p.suffix.lower() == ".txt"])


def _check_subject_line(lines: List[str], event_name: str, first_name: str) -> bool:
    if not lines:
        return False
    subject = lines[0].rstrip("\r\n")
    expected = f"Subject: {event_name} in Springfield — Invitation for {first_name}"
    return subject == expected


def _check_blank_line_after_subject(lines: List[str]) -> bool:
    if len(lines) < 2:
        return False
    return lines[1].strip() == ""


def _check_body_requirements(lines: List[str], body_start_index: int, client: Dict[str, str], event: Dict[str, str]) -> bool:
    body_lines = [ln.rstrip("\r\n") for ln in lines[body_start_index:]]
    body_text = "\n".join(body_lines)

    first_name = client.get("first_name", "")
    greeting_ok = False
    if first_name:
        greeting_ok = re.search(rf"\b(Hi|Hello|Dear)\s+{re.escape(first_name)}\b", body_text) is not None

    evt_name_ok = event["name"] in body_text
    evt_date_ok = event["event_date"] in body_text
    evt_time_ok = event["event_time"] in body_text
    evt_loc_ok = event["location"] in body_text

    status = _normalize_status(client.get("status", ""))
    if status == "renter":
        tailored_ok = ("getting ready to buy" in body_text) and ("homeownership" in body_text)
    elif status == "homeowner":
        tailored_ok = ("simplifying" in body_text) and ("right-sizing" in body_text) and ("downsizing" in body_text)
    else:
        tailored_ok = False

    cta_ok = "Reply to this email to save your seat." in body_text

    sig_block = [
        "Best regards,",
        "Alex Martinez, Realtor",
        "Main Street Realty",
        "(555) 123-4567",
    ]
    sig_ok = _find_contiguous_subsequence(body_lines, sig_block)

    disclaimers = [
        "This invitation is informational; there is no obligation to attend.",
        "If you received this by mistake, please disregard.",
    ]
    disclaimers_ok = _find_contiguous_subsequence(body_lines, disclaimers)

    return all([greeting_ok, evt_name_ok, evt_date_ok, evt_time_ok, evt_loc_ok, tailored_ok, cta_ok, sig_ok, disclaimers_ok])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "recommendations_header_and_columns": 0.0,
        "recommendations_clients_coverage": 0.0,
        "recommendations_assignments_correct": 0.0,
        "recommendations_contact_fields_correct": 0.0,
        "emails_exist_for_selected": 0.0,
        "emails_content_requirements": 0.0,
        "no_extra_emails_files": 0.0,
        "summary_counts_correct": 0.0,
        "summary_command_contains_required_paths": 0.0,
    }

    clients_rows, events_rows, _brand_text = _load_inputs(workspace)
    if not clients_rows or not events_rows:
        return scores

    clients_by_id = {c["client_id"]: c for c in clients_rows if "client_id" in c}
    events_by_id = {e["event_id"]: e for e in events_rows if "event_id" in e}

    expected = _compute_expected_assignments(clients_rows, events_rows)

    rec_path = workspace / "output" / "recommendations.csv"
    rec_rows, rec_header = _safe_read_csv(rec_path)

    if rec_rows is not None and _validate_recommendations_header(rec_header):
        scores["recommendations_header_and_columns"] = 1.0
    else:
        scores["recommendations_header_and_columns"] = 0.0

    rec_by_client: Dict[str, Dict[str, str]] = {}
    duplicates = False
    extra_ids_present = False
    if rec_rows is not None:
        for r in rec_rows:
            cid = r.get("client_id", "")
            if cid in rec_by_client:
                duplicates = True
            rec_by_client.setdefault(cid, r)
        expected_ids = set(clients_by_id.keys())
        rec_ids = set(rec_by_client.keys())
        missing = expected_ids - rec_ids
        extra = rec_ids - expected_ids
        extra_ids_present = len(extra) > 0
        if duplicates or extra_ids_present or len(missing) > 0:
            total = len(expected_ids)
            present = len(expected_ids & rec_ids) - (1 if duplicates else 0)
            present = max(present, 0)
            scores["recommendations_clients_coverage"] = (present / total) if total > 0 else 0.0
        else:
            total = len(expected_ids)
            present = len(expected_ids & rec_ids)
            scores["recommendations_clients_coverage"] = (present / total) if total > 0 else 0.0

    if rec_rows is not None and expected:
        correct_count = 0
        total = len(expected)
        for cid, exp in expected.items():
            r = rec_by_client.get(cid)
            if not r:
                continue
            rid = (r.get("recommended_event_id") or "").strip()
            rname = (r.get("recommended_event_name") or "").strip()
            rscore_str = (r.get("total_score") or "").strip()
            rscore = _parse_int(rscore_str) if rscore_str != "" else None
            rwas_tie = _bool_from_str(r.get("was_tie", ""))
            remail_file = (r.get("email_file") or "").strip()

            exp_id = exp["recommended_event_id"]
            exp_name = exp["recommended_event_name"]
            exp_score = exp["total_score"]
            exp_tie = exp["was_tie"]

            valid = True
            if exp_id is None:
                if rid != "" or rname != "" or remail_file != "":
                    valid = False
                if rscore != 0:
                    valid = False
                if rwas_tie is None or rwas_tie != exp_tie:
                    valid = False
            else:
                if rid != exp_id:
                    valid = False
                if rname != exp_name:
                    valid = False
                if rscore != exp_score:
                    valid = False
                if rwas_tie is None or rwas_tie is not False:
                    valid = False
                expected_email_path = f"output/emails/{cid}_{exp_id}.txt"
                if remail_file != expected_email_path:
                    valid = False

            if valid:
                correct_count += 1
        scores["recommendations_assignments_correct"] = (correct_count / total) if total > 0 else 0.0

    if rec_rows is not None:
        correct_count = 0
        total = len(expected)
        for cid, _exp in expected.items():
            r = rec_by_client.get(cid)
            c = clients_by_id.get(cid)
            if not r or not c:
                continue
            valid = True
            if (r.get("first_name") or "").strip() != (c.get("first_name") or "").strip():
                valid = False
            if (r.get("last_name") or "").strip() != (c.get("last_name") or "").strip():
                valid = False
            if (r.get("email") or "").strip() != (c.get("email") or "").strip():
                valid = False
            exp_day = (_split_pipe(c.get("preferred_days", ""))[:1] or [""])[0]
            if (r.get("next_suggested_day") or "").strip() != exp_day:
                valid = False
            if (r.get("send_time_local") or "").strip() != (c.get("preferred_hour_local") or "").strip():
                valid = False
            if (r.get("timezone") or "").strip() != (c.get("timezone") or "").strip():
                valid = False
            if valid:
                correct_count += 1
        scores["recommendations_contact_fields_correct"] = (correct_count / total) if total > 0 else 0.0

    emails_dir = workspace / "output" / "emails"
    selected_clients = []
    if rec_rows is not None:
        for cid, r in rec_by_client.items():
            rid = (r.get("recommended_event_id") or "").strip()
            if rid != "":
                selected_clients.append(cid)

    if rec_rows is not None:
        exist_count = 0
        total_sel = len(selected_clients)
        for cid in selected_clients:
            r = rec_by_client[cid]
            email_file_rel = (r.get("email_file") or "").strip()
            if email_file_rel == "":
                continue
            email_file_path = workspace / email_file_rel
            if email_file_path.exists() and email_file_path.is_file():
                exist_count += 1
        scores["emails_exist_for_selected"] = (exist_count / total_sel) if total_sel > 0 else 0.0

    if rec_rows is not None and events_by_id:
        pass_count = 0
        total_sel = len(selected_clients)
        for cid in selected_clients:
            r = rec_by_client[cid]
            client = clients_by_id.get(cid, {})
            rid = (r.get("recommended_event_id") or "").strip()
            email_file_rel = (r.get("email_file") or "").strip()
            if rid not in events_by_id or email_file_rel == "":
                continue
            ev = events_by_id[rid]
            email_path = workspace / email_file_rel
            content = _safe_read_text(email_path)
            if content is None:
                continue
            lines = content.splitlines()
            subj_ok = _check_subject_line(lines, ev["name"], client.get("first_name", ""))
            blank_ok = _check_blank_line_after_subject(lines)
            body_ok = _check_body_requirements(lines, 2, client, ev)
            if subj_ok and blank_ok and body_ok:
                pass_count += 1
        scores["emails_content_requirements"] = (pass_count / total_sel) if total_sel > 0 else 0.0

    all_email_files = _collect_email_files(emails_dir)
    extra_ok = None
    if rec_rows is not None:
        valid_pairs = set()
        for cid, r in rec_by_client.items():
            rid = (r.get("recommended_event_id") or "").strip()
            if rid != "":
                valid_pairs.add((cid, rid))
        total_sel = len(valid_pairs)
        if total_sel > 0:
            extra_ok = True
            for p in all_email_files:
                name = p.name
                if "_" in name and name.endswith(".txt"):
                    base = name[:-4]
                    if "_" not in base:
                        extra_ok = False
                        break
                    cid2, ev2 = base.split("_", 1)
                    if (cid2, ev2) not in valid_pairs:
                        extra_ok = False
                        break
                else:
                    extra_ok = False
                    break
            # Also ensure there isn't any missing expected email file
            if extra_ok:
                expected_files = {f"{cid}_{ev}.txt" for (cid, ev) in valid_pairs}
                actual_files = {p.name for p in all_email_files}
                if not expected_files.issubset(actual_files):
                    extra_ok = False
            scores["no_extra_emails_files"] = 1.0 if extra_ok else 0.0
        else:
            # No selected recipients; do not award credit for absence of emails
            scores["no_extra_emails_files"] = 0.0
    else:
        scores["no_extra_emails_files"] = 0.0

    summary_path = workspace / "output" / "summary.json"
    summary = _safe_load_json(summary_path)

    if summary is not None and rec_rows is not None:
        per_event_expected: Dict[str, int] = {}
        total_emails_drafted_expected = 0
        for cid, r in rec_by_client.items():
            rid = (r.get("recommended_event_id") or "").strip()
            email_file_rel = (r.get("email_file") or "").strip()
            if rid != "" and email_file_rel != "":
                email_path = workspace / email_file_rel
                if email_path.exists() and email_path.is_file():
                    per_event_expected[rid] = per_event_expected.get(rid, 0) + 1
                    total_emails_drafted_expected += 1
        count_no_clear_match_expected = sum(
            1 for _cid, r in rec_by_client.items() if (r.get("recommended_event_id") or "").strip() == ""
        )

        counts_ok = True
        for ev_id in events_by_id.keys():
            expected_count = per_event_expected.get(ev_id, 0)
            actual = summary.get(ev_id)
            if not isinstance(actual, int) or actual != expected_count:
                counts_ok = False
                break
        total_ok = isinstance(summary.get("total_emails_drafted"), int) and summary.get("total_emails_drafted") == total_emails_drafted_expected
        ncm_ok = isinstance(summary.get("count_no_clear_match"), int) and summary.get("count_no_clear_match") == count_no_clear_match_expected

        if counts_ok and total_ok and ncm_ok:
            scores["summary_counts_correct"] = 1.0
        else:
            scores["summary_counts_correct"] = 0.0
    else:
        scores["summary_counts_correct"] = 0.0

    if summary is not None:
        cmd = summary.get("command")
        if isinstance(cmd, str):
            tokens = ["input/clients.csv", "input/events.csv", "input/brand_voice.txt", "output/"]
            ok = True
            start = 0
            for t in tokens:
                idx = cmd.find(t, start)
                if idx == -1:
                    ok = False
                    break
                start = idx + len(t)
            scores["summary_command_contains_required_paths"] = 1.0 if ok else 0.0
        else:
            scores["summary_command_contains_required_paths"] = 0.0
    else:
        scores["summary_command_contains_required_paths"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()