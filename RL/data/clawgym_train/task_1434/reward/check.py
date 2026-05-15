import json
import sys
import re
import csv
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        try:
            return json.loads(path.read_text())
        except Exception:
            return None


def _parse_csv_readings(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                date = r.get("date")
                rh = r.get("rh_percent")
                if date is None or rh is None:
                    return None
                rows.append({
                    "date": date.strip(),
                    "rh": float(rh.strip()),
                })
        # Ensure sorted by date
        rows.sort(key=lambda x: x["date"])
        return rows
    except Exception:
        return None


def _compute_metrics_from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    dates = [r["date"] for r in rows]
    rhs = [r["rh"] for r in rows]
    start_date = dates[0]
    end_date = dates[-1]
    num_days = len(rows)
    avg_rh = sum(rhs) / num_days if num_days > 0 else 0.0
    max_rh = max(rhs) if rhs else 0.0
    ge60 = sum(1 for v in rhs if v >= 60.0)
    ge70 = sum(1 for v in rhs if v >= 70.0)
    # sequences >= 70% consecutive
    sequences: List[Dict[str, Any]] = []
    current_start: Optional[str] = None
    current_len = 0
    prev_date: Optional[datetime] = None
    for r in rows:
        dstr = r["date"]
        rh = r["rh"]
        d = datetime.strptime(dstr, "%Y-%m-%d").date()
        if rh >= 70.0:
            if current_start is None:
                current_start = dstr
                current_len = 1
            else:
                # Check if consecutive by 1 day increments; but since data has one per day ordered, we can just increment
                current_len += 1
        else:
            if current_start is not None:
                # Close out
                # previous row date is prev_date
                end_dstr = (prev_date.strftime("%Y-%m-%d") if prev_date is not None else current_start)
                sequences.append({
                    "start_date": current_start,
                    "end_date": end_dstr,
                    "length": current_len
                })
                current_start = None
                current_len = 0
        prev_date = d
    if current_start is not None:
        end_dstr = prev_date.strftime("%Y-%m-%d") if prev_date is not None else current_start
        sequences.append({
            "start_date": current_start,
            "end_date": end_dstr,
            "length": current_len
        })
    # Only include sequences with length >= 1 (we may later check triggers of >=3 in status)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "num_days": num_days,
        "avg_rh_percent": avg_rh,
        "max_rh_percent": max_rh,
        "count_days_rh_ge_60": ge60,
        "count_days_rh_ge_70": ge70,
        "sequences_rh_ge_70": sequences,
    }


def _almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _find_section_lines(text: str, heading: str) -> List[str]:
    # Return lines under the section heading until next heading or EOF
    lines = text.splitlines()
    section_lines: List[str] = []
    in_section = False
    heading_lower = heading.lower()
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not in_section:
            if line_stripped.lower().startswith(heading_lower):
                in_section = True
        else:
            # Stop if next heading (Markdown style) encountered
            if re.match(r"^\s*#{1,6}\s+", line_stripped):
                break
            # Also stop if another known section starts (Agenda/Key Questions/Action Items)
            if line_stripped.lower().startswith("agenda") and heading_lower != "agenda":
                break
            if line_stripped.lower().startswith("key questions") and heading_lower != "key questions":
                break
            if line_stripped.lower().startswith("action items") and heading_lower != "action items":
                break
            section_lines.append(line)
    return section_lines


def _extract_bullets(lines: List[str]) -> List[str]:
    bullets: List[str] = []
    for ln in lines:
        if re.match(r"^\s*[-*\u2022]\s+", ln) or re.match(r"^\s*\d+\.\s+", ln):
            bullets.append(ln.strip())
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "metrics_file_present": 0.0,
        "metrics_fields_present": 0.0,
        "metrics_values_correct": 0.0,
        "metrics_sequences_correct": 0.0,
        "status_summary_period_and_metrics": 0.0,
        "status_summary_guideline_citations": 0.0,
        "status_summary_triggers_identified": 0.0,
        "status_summary_top3_issues": 0.0,
        "status_summary_prioritized_recommendations_with_citations": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_uses_context_and_budget": 0.0,
        "meeting_notes_action_items_with_owners_and_due_dates": 0.0,
        "meeting_notes_actions_cover_recommendations": 0.0,
        "validation_results_checks_present": 0.0,
        "validation_lists_counts_and_sequences": 0.0,
        "validation_includes_command": 0.0,
    }

    # Load inputs
    guidelines_path = workspace / "input" / "guidelines.md"
    readings_path = workspace / "input" / "crawlspace_readings.csv"
    inspection_path = workspace / "input" / "inspection_notes.md"
    meeting_ctx_path = workspace / "input" / "meeting_context.json"

    guidelines_txt = _read_text(guidelines_path) or ""
    inspection_txt = _read_text(inspection_path) or ""
    meeting_ctx = _load_json(meeting_ctx_path) or {}

    # Compute expected metrics from CSV
    rows = _parse_csv_readings(readings_path)
    expected_metrics: Optional[Dict[str, Any]] = None
    if rows is not None and len(rows) > 0:
        expected_metrics = _compute_metrics_from_rows(rows)

    # Check output metrics.json
    metrics_path = workspace / "output" / "data" / "metrics.json"
    metrics = _load_json(metrics_path)
    if metrics is not None:
        scores["metrics_file_present"] = 1.0
        # Check presence of required fields
        required_fields = [
            "start_date",
            "end_date",
            "num_days",
            "avg_rh_percent",
            "max_rh_percent",
            "count_days_rh_ge_60",
            "count_days_rh_ge_70",
            "sequences_rh_ge_70",
        ]
        if all(k in metrics for k in required_fields):
            scores["metrics_fields_present"] = 1.0

        # Compare values if expected available
        if expected_metrics is not None:
            correct = True
            try:
                if metrics.get("start_date") != expected_metrics["start_date"]:
                    correct = False
                if metrics.get("end_date") != expected_metrics["end_date"]:
                    correct = False
                if int(metrics.get("num_days")) != expected_metrics["num_days"]:
                    correct = False
                # avg and max numeric with small tolerance
                avg_ok = False
                try:
                    avg_ok = _almost_equal(float(metrics.get("avg_rh_percent")), float(expected_metrics["avg_rh_percent"]), tol=1e-6)
                except Exception:
                    avg_ok = False
                max_ok = False
                try:
                    max_ok = _almost_equal(float(metrics.get("max_rh_percent")), float(expected_metrics["max_rh_percent"]), tol=1e-6)
                except Exception:
                    max_ok = False
                if not (avg_ok and max_ok):
                    correct = False
                if int(metrics.get("count_days_rh_ge_60")) != expected_metrics["count_days_rh_ge_60"]:
                    correct = False
                if int(metrics.get("count_days_rh_ge_70")) != expected_metrics["count_days_rh_ge_70"]:
                    correct = False
            except Exception:
                correct = False
            scores["metrics_values_correct"] = 1.0 if correct else 0.0

            # Sequences compare (expect exact sequences at RH >= 70)
            seq_ok = False
            try:
                expected_seqs = [
                    s for s in expected_metrics["sequences_rh_ge_70"]
                    if s.get("length", 0) >= 1
                ]
                # Normalize sequences to list of tuples for comparison
                def norm_seq_list(seq_list: Any) -> List[Tuple[str, str, int]]:
                    out: List[Tuple[str, str, int]] = []
                    if isinstance(seq_list, list):
                        for s in seq_list:
                            if isinstance(s, dict):
                                sd = s.get("start_date")
                                ed = s.get("end_date")
                                ln = s.get("length")
                                if isinstance(sd, str) and isinstance(ed, str):
                                    try:
                                        ln_i = int(ln)
                                    except Exception:
                                        continue
                                    out.append((sd, ed, ln_i))
                    return sorted(out, key=lambda x: (x[0], x[1], x[2]))
                seq_ok = norm_seq_list(metrics.get("sequences_rh_ge_70")) == norm_seq_list(expected_seqs)
            except Exception:
                seq_ok = False
            scores["metrics_sequences_correct"] = 1.0 if seq_ok else 0.0

    # Status summary checks
    status_path = workspace / "output" / "status" / "crawlspace_status_summary.md"
    status_txt = _read_text(status_path) or ""
    if status_txt:
        # period and metrics: must include start and end dates and key metrics
        period_ok = False
        metrics_ok = False
        if expected_metrics is not None:
            start = expected_metrics["start_date"]
            end = expected_metrics["end_date"]
            if start in status_txt and end in status_txt:
                period_ok = True
            # Check presence of key numeric metrics: num_days, max_rh_percent, count_days_rh_ge_60, count_days_rh_ge_70
            nums_found = 0
            if str(expected_metrics["num_days"]) in status_txt:
                nums_found += 1
            if str(int(expected_metrics["max_rh_percent"])) in status_txt:
                nums_found += 1
            if str(expected_metrics["count_days_rh_ge_60"]) in status_txt:
                nums_found += 1
            if str(expected_metrics["count_days_rh_ge_70"]) in status_txt:
                nums_found += 1
            # Try to detect average with a flexible formatting: accept full precision, or rounded to 1 or 2 decimals, or integer rounded
            avg = expected_metrics["avg_rh_percent"]
            avg_strs = {
                f"{avg}",
                f"{avg:.1f}",
                f"{avg:.2f}",
                f"{round(avg)}",
                f"{int(avg)}",
            }
            avg_present = any(s in status_txt for s in avg_strs)
            # Require at least 3 of 4 numeric metrics plus average presence
            metrics_ok = (nums_found >= 3) and avg_present
        scores["status_summary_period_and_metrics"] = 1.0 if (period_ok and metrics_ok) else 0.0

        # guideline citations: reference guideline section IDs like G1/G2/G3
        cites = set(re.findall(r"\bG[1-4]\b", status_txt))
        scores["status_summary_guideline_citations"] = 1.0 if ("G2" in cites and ("G1" in cites or "G3" in cites)) else 0.0

        # triggers identified: mention RH >= 70 for 3+ days tied to G2
        lower_txt = status_txt.lower()
        trig_ok = False
        if "g2" in lower_txt and ("70" in lower_txt) and ("3" in lower_txt):
            trig_ok = True
        scores["status_summary_triggers_identified"] = 1.0 if trig_ok else 0.0

        # top 3 issues combining inspection notes with guideline triggers
        # look for at least three of these: musty odor, exposed soil/no vapor barrier, open vents/vent status, damp soil/puddle, downspout near foundation
        issue_keywords = {
            "musty": False,
            "vapor barrier": False,
            "exposed soil": False,
            "vent": False,
            "damp": False,
            "puddle": False,
            "downspout": False,
            "drain": False,
        }
        for k in list(issue_keywords.keys()):
            if k in lower_txt:
                issue_keywords[k] = True
        # Count categories (merge damp/puddle, vapor barrier/exposed soil, vent)
        categories = set()
        if issue_keywords["musty"]:
            categories.add("musty")
        if issue_keywords["vapor barrier"] or issue_keywords["exposed soil"]:
            categories.add("ground_cover")
        if issue_keywords["vent"]:
            categories.add("vent")
        if issue_keywords["damp"] or issue_keywords["puddle"] or issue_keywords["drain"]:
            categories.add("moisture_entry")
        if issue_keywords["downspout"]:
            categories.add("downspout")
        scores["status_summary_top3_issues"] = 1.0 if len(categories) >= 3 else 0.0

        # prioritized recommendations: High/Medium/Low with rationale and citing relevant guideline IDs
        # look for lines containing High/Medium/Low and at least 3 remediation keywords and presence of G3 or G2 citations
        lines = status_txt.splitlines()
        rec_lines = [ln for ln in lines if re.search(r"\b(High|Medium|Low)\b", ln, flags=re.IGNORECASE)]
        rec_text = "\n".join(rec_lines)
        rec_keywords = {
            "vapor": False,
            "dehumid": False,
            "vent": False,
            "drain": False,
        }
        for k in rec_keywords:
            if re.search(k, rec_text, flags=re.IGNORECASE):
                rec_keywords[k] = True
        rec_count = sum(1 for v in rec_keywords.values() if v)
        cites_rec = set(re.findall(r"\bG[1-4]\b", rec_text))
        has_priority_words = bool(rec_lines)
        # store remediation tags for later checks in meeting notes
        rec_tags_found = set([k for k, v in rec_keywords.items() if v])
        # Determine if prioritized and cited
        scores["status_summary_prioritized_recommendations_with_citations"] = 1.0 if (has_priority_words and rec_count >= 3 and ("G3" in cites_rec or "G2" in cites_rec)) else 0.0
    else:
        rec_tags_found = set()

    # Meeting notes checks
    meeting_notes_path = workspace / "output" / "meeting" / "meeting_notes.md"
    meeting_notes_txt = _read_text(meeting_notes_path) or ""
    if meeting_notes_txt:
        # Sections present
        has_agenda = "agenda" in meeting_notes_txt.lower()
        has_key_q = "key questions" in meeting_notes_txt.lower()
        has_actions = "action items" in meeting_notes_txt.lower()
        # Ensure bullets under each section
        agenda_bullets = _extract_bullets(_find_section_lines(meeting_notes_txt, "Agenda"))
        keyq_bullets = _extract_bullets(_find_section_lines(meeting_notes_txt, "Key Questions"))
        action_bullets = _extract_bullets(_find_section_lines(meeting_notes_txt, "Action Items"))
        sections_ok = has_agenda and has_key_q and has_actions and (len(agenda_bullets) > 0) and (len(keyq_bullets) > 0) and (len(action_bullets) > 0)
        scores["meeting_notes_sections_present"] = 1.0 if sections_ok else 0.0

        # Uses context and budget
        ctx_ok = False
        try:
            meeting_date_str = meeting_ctx.get("meeting_date")
            attendees = meeting_ctx.get("attendees", [])
            budget_usd = meeting_ctx.get("budget_usd")
            date_ok = meeting_date_str in meeting_notes_txt
            attendee_ok = any(a in meeting_notes_txt for a in attendees) if isinstance(attendees, list) else False
            budget_ok = False
            if budget_usd is not None:
                # Accept "2000", "$2000", "$2,000", "USD 2000"
                budget_patterns = [
                    re.escape(str(budget_usd)),
                    r"\$\s*%s" % re.escape(str(budget_usd)),
                    r"\$\s*2,\s*000",
                    r"USD\s*%s" % re.escape(str(budget_usd)),
                    r"budget",
                ]
                budget_ok = any(re.search(pat, meeting_notes_txt, flags=re.IGNORECASE) for pat in budget_patterns)
            ctx_ok = bool(date_ok and attendee_ok and budget_ok)
        except Exception:
            ctx_ok = False
        scores["meeting_notes_uses_context_and_budget"] = 1.0 if ctx_ok else 0.0

        # Action items with owners and due dates within 14 days
        owners = meeting_ctx.get("attendees", []) if isinstance(meeting_ctx.get("attendees"), list) else []
        meeting_date = None
        try:
            meeting_date = datetime.strptime(meeting_ctx.get("meeting_date"), "%Y-%m-%d").date()
        except Exception:
            meeting_date = None

        action_items_valid = 0
        action_items_total = 0
        due_date_pattern = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
        for ln in action_bullets:
            action_items_total += 1
            owner_present = any(o in ln for o in owners)
            due_ok = False
            if meeting_date is not None:
                m = due_date_pattern.search(ln)
                if m:
                    try:
                        due_d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                        if due_d >= meeting_date and due_d <= (meeting_date + timedelta(days=14)):
                            due_ok = True
                    except Exception:
                        due_ok = False
            if owner_present and due_ok:
                action_items_valid += 1
        # Require at least one valid action
        scores["meeting_notes_action_items_with_owners_and_due_dates"] = 1.0 if (action_items_valid >= 1) else 0.0

        # Actions cover recommendations: at least one action tied to each recommended remediation in the summary
        if rec_tags_found:
            cover_ok = True
            for tag in rec_tags_found:
                found = False
                for ln in action_bullets:
                    if re.search(tag, ln, flags=re.IGNORECASE):
                        found = True
                        break
                if not found:
                    cover_ok = False
                    break
            scores["meeting_notes_actions_cover_recommendations"] = 1.0 if cover_ok else 0.0
        else:
            # If no recommendations detected in summary, cannot validate coverage
            scores["meeting_notes_actions_cover_recommendations"] = 0.0
    # Validation results checks
    validation_path = workspace / "output" / "tests" / "validation_results.txt"
    validation_txt = _read_text(validation_path) or ""
    if validation_txt and expected_metrics is not None and metrics is not None:
        # Check PASS/FAIL lines for each field and an overall PASS/FAIL
        fields = [
            "start_date",
            "end_date",
            "num_days",
            "avg_rh_percent",
            "max_rh_percent",
            "count_days_rh_ge_60",
            "count_days_rh_ge_70",
            "sequences",
        ]
        field_checks = 0
        for fld in fields:
            if re.search(rf"{re.escape(fld)}.*\b(PASS|FAIL)\b", validation_txt, flags=re.IGNORECASE):
                field_checks += 1
        overall_present = bool(re.search(r"\boverall\b.*\b(PASS|FAIL)\b", validation_txt, flags=re.IGNORECASE))
        scores["validation_results_checks_present"] = 1.0 if (field_checks >= len(fields) and overall_present) else 0.0

        # Lists recomputed counts and sequences
        # Check counts with 60 and 70 present near numbers
        counts_ok = False
        # Allow forms with >= or ≥
        count60_pat = re.compile(r"(?:>=|≥)\s*60.*?\b%s\b" % re.escape(str(expected_metrics["count_days_rh_ge_60"])))
        count70_pat = re.compile(r"(?:>=|≥)\s*70.*?\b%s\b" % re.escape(str(expected_metrics["count_days_rh_ge_70"])))
        if count60_pat.search(validation_txt) and count70_pat.search(validation_txt):
            counts_ok = True
        # Sequences presence: look for date ranges
        seqs = [s for s in expected_metrics["sequences_rh_ge_70"] if s["length"] >= 1]
        seqs_ok = True
        for s in seqs:
            rng = f"{s['start_date']} to {s['end_date']}"
            if rng not in validation_txt:
                seqs_ok = False
                break
        scores["validation_lists_counts_and_sequences"] = 1.0 if (counts_ok and seqs_ok) else 0.0

        # Includes exact command executed: look for a 'python ' command or similar
        cmd_ok = bool(re.search(r"\bpython\s+[^\n\r]+", validation_txt, flags=re.IGNORECASE))
        scores["validation_includes_command"] = 1.0 if cmd_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()