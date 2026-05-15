import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_csv_dicts_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def to_float(s: Any) -> Optional[float]:
    try:
        if isinstance(s, (int, float)):
            return float(s)
        if isinstance(s, str):
            s2 = s.strip().replace("%", "")
            if s2 == "":
                return None
            return float(s2)
    except Exception:
        return None
    return None


def canonical_none_orchestrator(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = value.strip().lower()
    if v in {"none", "none yet", "n/a", "na", "no", "no orchestrator", "tbd"}:
        return "None"
    return value


def parse_meeting_notes(md_text: str) -> Dict[str, Dict[str, Any]]:
    lines = [ln.rstrip() for ln in md_text.splitlines()]
    records: Dict[str, Dict[str, Any]] = {}
    current_company: Optional[str] = None
    for i, ln in enumerate(lines):
        m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", ln.strip())
        if m:
            current_company = m.group(1).strip()
            stage = m.group(2).strip()
            records[current_company] = {
                "company": current_company,
                "stage": stage,
                "containerization_level": None,
                "orchestrator": None,
                "primary_cloud": None,
                "efficiency_metric_pct": None,
                "scalability_note": None,
            }
            continue
        if current_company is None:
            continue
        # Expect bullet lines with "- Key: Value"
        bl = ln.strip()
        if bl.startswith("- "):
            bl = bl[2:].strip()
            if ":" in bl:
                key, val = bl.split(":", 1)
                key = key.strip().lower()
                val = val.strip()
                if key == "status":
                    # Extract containerization level (pilot|partial|full) from parentheses
                    m2 = re.search(r"\b(pilot|partial|full)\b", val, flags=re.IGNORECASE)
                    if m2:
                        records[current_company]["containerization_level"] = m2.group(1).lower()
                elif key == "orchestrator":
                    records[current_company]["orchestrator"] = val
                elif key == "cloud":
                    records[current_company]["primary_cloud"] = val
                elif key == "efficiency":
                    # Extract percentages; prefer infra/cost-related metric
                    # Find all percents
                    percents = []
                    for pm in re.finditer(r"(\d+(?:\.\d+)?)\s*%", val):
                        num = pm.group(1)
                        start_idx = max(0, pm.start() - 40)
                        end_idx = min(len(val), pm.end() + 40)
                        context = val[start_idx:end_idx].lower()
                        percents.append((num, context))
                    chosen: Optional[str] = None
                    for num, context in percents:
                        if any(tok in context for tok in ["infra", "cost", "spend", "savings"]):
                            chosen = num
                            break
                    if chosen is None and percents:
                        chosen = percents[0][0]
                    if chosen is not None:
                        records[current_company]["efficiency_metric_pct"] = chosen
                elif key == "scalability":
                    records[current_company]["scalability_note"] = val
    return records


def normalize_container_level(level: Optional[str]) -> Optional[str]:
    if level is None:
        return None
    lv = level.strip().lower()
    if lv in {"pilot", "partial", "full"}:
        return lv
    return lv


def compute_expected_records(notes: Dict[str, Dict[str, Any]], csv_rows: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    # Index CSV rows by company
    csv_by_company: Dict[str, Dict[str, str]] = {}
    for row in csv_rows:
        comp = (row.get("company") or "").strip()
        if comp:
            csv_by_company[comp] = row

    all_companies = set(csv_by_company.keys()) | set(notes.keys())
    expected: Dict[str, Dict[str, Any]] = {}
    for comp in sorted(all_companies):
        n = notes.get(comp, {})
        c = csv_by_company.get(comp, {})
        stage_notes = (n.get("stage") or "").strip() or None
        stage_csv = (c.get("stage") or "").strip() or None

        level_notes = normalize_container_level(n.get("containerization_level"))
        level_csv = normalize_container_level((c.get("containerization_level") or "").strip() or None)

        orch_notes_raw = (n.get("orchestrator") or "").strip() or None
        orch_csv_raw = (c.get("orchestrator") or "").strip() or None

        cloud_notes = (n.get("primary_cloud") or "").strip() or None
        cloud_csv = (c.get("primary_cloud") or "").strip() or None

        eff_notes = to_float(n.get("efficiency_metric_pct")) if n.get("efficiency_metric_pct") is not None else None
        eff_csv = to_float(c.get("efficiency_metric_pct")) if c.get("efficiency_metric_pct") is not None else None

        scal_notes = (n.get("scalability_note") or "").strip() or None
        scal_csv = (c.get("scalability_note") or "").strip() or None

        # Reconciliation preferences
        stage_final = stage_csv if stage_csv else stage_notes
        level_final = level_csv if level_csv else level_notes
        orch_final_raw = orch_csv_raw if orch_csv_raw else orch_notes_raw
        orch_final = canonical_none_orchestrator(orch_final_raw)
        cloud_final = cloud_csv if cloud_csv else cloud_notes
        eff_final = eff_csv if eff_csv is not None else eff_notes
        scal_final = scal_csv if scal_csv else scal_notes

        # Build conflict note elements
        conflicts: List[str] = []
        def add_conf(field: str, nv: Any, cv: Any, transform: Optional[str] = None) -> None:
            # nv is "notes value", cv is "csv value"
            n_present = nv is not None and (str(nv).strip() != "")
            c_present = cv is not None and (str(cv).strip() != "")
            if n_present and c_present:
                # For efficiency, compare numerically
                is_diff = False
                if field == "efficiency_metric_pct":
                    nf = to_float(nv)
                    cf = to_float(cv)
                    if nf is None or cf is None:
                        is_diff = (str(nv).strip() != str(cv).strip())
                    else:
                        is_diff = abs(nf - cf) > 1e-9
                else:
                    is_diff = (str(nv).strip() != str(cv).strip())
                if is_diff:
                    conflicts.append(f"notes {field}='{str(nv).strip()}' vs csv {field}='{str(cv).strip()}'")

        add_conf("stage", stage_notes, stage_csv)
        add_conf("containerization_level", level_notes, level_csv)
        add_conf("orchestrator", orch_notes_raw, orch_csv_raw)
        add_conf("primary_cloud", cloud_notes, cloud_csv)
        add_conf("efficiency_metric_pct", eff_notes, eff_csv)
        add_conf("scalability_note", scal_notes, scal_csv)

        conflict_note = "; ".join(conflicts)

        expected[comp] = {
            "company": comp,
            "stage": stage_final or "",
            "containerization_level": level_final or "",
            "orchestrator": orch_final or "",
            "primary_cloud": cloud_final or "",
            "efficiency_metric_pct": eff_final if eff_final is not None else None,
            "scalability_note": scal_final or "",
            "source_files_csv_set": {"company_updates.csv", "meeting_notes.md"},
            "source_files_json_set": {"company_updates.csv", "meeting_notes.md"},
            "conflict_note_required_parts": conflicts,
        }
    return expected


def parse_summary_csv(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[List[str]]]:
    rows = read_csv_dicts_safe(path)
    if rows is None:
        return None, None
    headers = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            headers = next(reader)
    except Exception:
        headers = list(rows[0].keys()) if rows else []
    return rows, headers


def parse_source_files_field(value: str) -> List[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def extract_bullets(text: str) -> List[str]:
    bullets = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s)
    return bullets


def word_count(text: str) -> int:
    tokens = re.findall(r"\b\w[\w'-]*\b", text)
    return len(tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "summary_csv_exists": 0.0,
        "summary_csv_structure_fields": 0.0,
        "summary_csv_company_count": 0.0,
        "summary_csv_companies_set": 0.0,
        "summary_csv_values_correct": 0.0,
        "summary_csv_source_files_contains_both": 0.0,
        "summary_csv_containerization_level_normalized": 0.0,
        "summary_conflicts_include_required": 0.0,
        "summary_conflicts_no_false_positives": 0.0,
        "summary_json_exists": 0.0,
        "summary_json_structure_fields": 0.0,
        "summary_json_values_correct": 0.0,
        "summary_json_matches_csv_consistency": 0.0,
        "rewritten_messages_exists": 0.0,
        "rewritten_messages_count_matches": 0.0,
        "rewritten_messages_length_under_60": 0.0,
        "email_exists": 0.0,
        "email_subject_present": 0.0,
        "email_body_word_count_range": 0.0,
        "email_bullet_list_top3_correct": 0.0,
        "email_bullets_include_required_fields": 0.0,
        "email_next_step_one_sentence": 0.0,
    }

    # Input files
    input_dir = workspace / "input"
    output_dir = workspace / "output"

    notes_path = input_dir / "meeting_notes.md"
    updates_csv_path = input_dir / "company_updates.csv"
    raw_msgs_path = input_dir / "raw_messages.txt"

    notes_text = read_text_safe(notes_path)
    updates_rows = read_csv_dicts_safe(updates_csv_path)

    # If inputs missing, expected computation may be partial; handle gracefully
    notes_parsed: Dict[str, Dict[str, Any]] = {}
    if notes_text is not None:
        notes_parsed = parse_meeting_notes(notes_text)
    if updates_rows is None:
        updates_rows = []

    expected = compute_expected_records(notes_parsed, updates_rows)

    # Output files
    summary_csv_path = output_dir / "portfolio_containerization_summary.csv"
    summary_json_path = output_dir / "portfolio_containerization_summary.json"
    rewritten_msgs_path = output_dir / "rewritten_messages.txt"
    email_path = output_dir / "email_to_partner.md"

    # Check CSV summary
    if summary_csv_path.exists():
        scores["summary_csv_exists"] = 1.0
        rows, headers = parse_summary_csv(summary_csv_path)
        if rows is not None and headers is not None:
            required_fields = [
                "company",
                "stage",
                "containerization_level",
                "orchestrator",
                "primary_cloud",
                "efficiency_metric_pct",
                "scalability_note",
                "source_files",
                "conflict_note",
            ]
            if set(headers) == set(required_fields):
                scores["summary_csv_structure_fields"] = 1.0
            # Company count and set
            companies_in_csv = [r.get("company", "").strip() for r in rows]
            comp_set = set([c for c in companies_in_csv if c])
            if len(comp_set) == 4 and len(rows) == 4:
                scores["summary_csv_company_count"] = 1.0
            # Compare company set with expected
            expected_set = set(expected.keys())
            if comp_set == expected_set and len(companies_in_csv) == len(expected_set):
                scores["summary_csv_companies_set"] = 1.0

            # Per-record checks
            values_ok = True
            sourcefiles_ok = True
            levels_ok = True
            conflicts_required_ok = True
            conflicts_no_false_ok = True

            for r in rows:
                comp = r.get("company", "").strip()
                exp = expected.get(comp)
                if not exp:
                    values_ok = False
                    levels_ok = False
                    sourcefiles_ok = False
                    conflicts_required_ok = False
                    conflicts_no_false_ok = False
                    continue

                # stage
                if (r.get("stage") or "").strip() != exp["stage"]:
                    values_ok = False
                # containerization_level lowercase and match expected
                level = (r.get("containerization_level") or "").strip()
                if level != (exp["containerization_level"] or ""):
                    values_ok = False
                if level not in {"pilot", "partial", "full"}:
                    levels_ok = False
                # orchestrator
                orch_out = (r.get("orchestrator") or "").strip()
                if orch_out != (exp["orchestrator"] or ""):
                    values_ok = False
                # primary_cloud
                if (r.get("primary_cloud") or "").strip() != (exp["primary_cloud"] or ""):
                    values_ok = False
                # efficiency_metric_pct numeric and equals expected within tolerance
                eff_out = r.get("efficiency_metric_pct")
                eff_out_float = to_float(eff_out)
                eff_exp_float = exp["efficiency_metric_pct"]
                if eff_out_float is None or eff_exp_float is None or abs(eff_out_float - float(eff_exp_float)) > 1e-9:
                    values_ok = False
                # scalability_note
                if (r.get("scalability_note") or "").strip() != (exp["scalability_note"] or ""):
                    values_ok = False
                # source_files contains both filenames regardless of order
                sf_val = (r.get("source_files") or "").strip()
                sf_list = parse_source_files_field(sf_val)
                if not (set(sf_list) >= exp["source_files_csv_set"]):
                    sourcefiles_ok = False
                # conflict notes required substrings present
                conf = (r.get("conflict_note") or "").strip()
                for part in exp["conflict_note_required_parts"]:
                    if part not in conf:
                        conflicts_required_ok = False
                        break
                # no false positives: ensure that fields without conflicts are not mentioned in "notes FIELD='"
                fields = ["stage", "containerization_level", "orchestrator", "primary_cloud", "efficiency_metric_pct", "scalability_note"]
                conflicted_fields = set()
                for part in exp["conflict_note_required_parts"]:
                    m = re.match(r"notes\s+([a-z_]+)='", part)
                    if m:
                        conflicted_fields.add(m.group(1))
                for f in fields:
                    if f not in conflicted_fields:
                        if f"notes {f}='" in conf:
                            conflicts_no_false_ok = False
                            break

            if values_ok:
                scores["summary_csv_values_correct"] = 1.0
            if sourcefiles_ok:
                scores["summary_csv_source_files_contains_both"] = 1.0
            if levels_ok:
                scores["summary_csv_containerization_level_normalized"] = 1.0
            if conflicts_required_ok:
                scores["summary_conflicts_include_required"] = 1.0
            if conflicts_no_false_ok:
                scores["summary_conflicts_no_false_positives"] = 1.0

    # Check JSON summary
    if summary_json_path.exists():
        scores["summary_json_exists"] = 1.0
        data = load_json_safe(summary_json_path)
        if isinstance(data, list):
            # Structure fields
            struct_ok = True
            values_ok = True
            for item in data:
                if not isinstance(item, dict):
                    struct_ok = False
                    values_ok = False
                    break
                required_fields = [
                    "company",
                    "stage",
                    "containerization_level",
                    "orchestrator",
                    "primary_cloud",
                    "efficiency_metric_pct",
                    "scalability_note",
                    "source_files",
                    "conflict_note",
                ]
                if set(item.keys()) != set(required_fields):
                    struct_ok = False
                # Validate item values vs expected
                comp = (item.get("company") or "").strip()
                exp = expected.get(comp)
                if not exp:
                    values_ok = False
                    continue
                if (item.get("stage") or "") != exp["stage"]:
                    values_ok = False
                if (item.get("containerization_level") or "") != (exp["containerization_level"] or ""):
                    values_ok = False
                if (item.get("orchestrator") or "") != (exp["orchestrator"] or ""):
                    values_ok = False
                if (item.get("primary_cloud") or "") != (exp["primary_cloud"] or ""):
                    values_ok = False
                eff = item.get("efficiency_metric_pct")
                efff = to_float(eff)
                if efff is None or exp["efficiency_metric_pct"] is None or abs(efff - float(exp["efficiency_metric_pct"])) > 1e-9:
                    values_ok = False
                if (item.get("scalability_note") or "") != (exp["scalability_note"] or ""):
                    values_ok = False
                # source_files array contains both
                sf = item.get("source_files")
                if not isinstance(sf, list) or not (set([str(x) for x in sf]) >= exp["source_files_json_set"]):
                    values_ok = False
            if struct_ok:
                scores["summary_json_structure_fields"] = 1.0
            if values_ok:
                scores["summary_json_values_correct"] = 1.0

            # Cross-check JSON with CSV consistency on key fields if both exist
            if scores["summary_csv_exists"] > 0.5:
                csv_rows, _ = parse_summary_csv(summary_csv_path)
                if csv_rows is not None:
                    consistent = True
                    csv_map = {r.get("company", "").strip(): r for r in csv_rows}
                    for item in data:
                        comp = (item.get("company") or "").strip()
                        crow = csv_map.get(comp)
                        if not crow:
                            consistent = False
                            break
                        # Compare select fields
                        for key in ["stage", "containerization_level", "orchestrator", "primary_cloud", "scalability_note"]:
                            if (item.get(key) or "") != (crow.get(key) or ""):
                                consistent = False
                                break
                        # Efficiency compare
                        if abs((to_float(item.get("efficiency_metric_pct")) or -9999.0) - (to_float(crow.get("efficiency_metric_pct")) or -9999.0)) > 1e-9:
                            consistent = False
                            break
                    if consistent:
                        scores["summary_json_matches_csv_consistency"] = 1.0

    # Rewritten messages checks
    if rewritten_msgs_path.exists():
        scores["rewritten_messages_exists"] = 1.0
        orig = read_text_safe(raw_msgs_path) or ""
        out = read_text_safe(rewritten_msgs_path) or ""
        # Split original messages by blank lines (two or more newlines)
        orig_msgs = [m.strip() for m in re.split(r"\n\s*\n", orig.strip(), flags=re.MULTILINE) if m.strip() != ""]
        out_msgs = [m.strip() for m in re.split(r"\n\s*\n", out.strip(), flags=re.MULTILINE) if m.strip() != ""]
        if len(orig_msgs) == len(out_msgs) and len(out_msgs) > 0:
            scores["rewritten_messages_count_matches"] = 1.0
        # Each under 60 words
        if out_msgs:
            lengths_ok = all(word_count(m) <= 60 and word_count(m) > 0 for m in out_msgs)
            if lengths_ok:
                scores["rewritten_messages_length_under_60"] = 1.0

    # Email checks
    if email_path.exists():
        scores["email_exists"] = 1.0
        email_text = read_text_safe(email_path) or ""
        # Identify subject line: accept either a line starting with "Subject:" or first non-empty line as subject if followed by a blank line
        lines = email_text.splitlines()
        first_non_empty_idx = None
        for idx, ln in enumerate(lines):
            if ln.strip() != "":
                first_non_empty_idx = idx
                break
        subject_present = False
        body_text = ""
        if first_non_empty_idx is not None:
            first_line = lines[first_non_empty_idx].strip()
            if first_line.lower().startswith("subject:"):
                subject_present = True
                # Body is after this line
                body_text = "\n".join(lines[first_non_empty_idx + 1:]).strip()
                # If next line is blank, that's fine
            else:
                # Consider first line as subject if next line is blank
                next_line_blank = False
                if first_non_empty_idx + 1 < len(lines):
                    next_line_blank = lines[first_non_empty_idx + 1].strip() == ""
                if next_line_blank:
                    subject_present = True
                    body_text = "\n".join(lines[first_non_empty_idx + 2:]).strip()
                else:
                    # No clear subject-body separation; treat remaining as body
                    body_text = "\n".join(lines[first_non_empty_idx:]).strip()
        if subject_present:
            scores["email_subject_present"] = 1.0

        # Word count of body must be 150–220 words inclusive
        body_wc = word_count(body_text)
        if 150 <= body_wc <= 220:
            scores["email_body_word_count_range"] = 1.0

        # Bullet list correctness: top 3 companies by efficiency_metric_pct DESC from generated CSV summary
        bullets = extract_bullets(email_text)
        bullets_include_required = True
        bullets_top3_correct = False
        # Compute top 3 from CSV output if available
        if summary_csv_path.exists():
            out_rows, _ = parse_summary_csv(summary_csv_path)
            if out_rows is not None and len(out_rows) >= 3:
                arr = []
                for r in out_rows:
                    comp = (r.get("company") or "").strip()
                    eff = to_float(r.get("efficiency_metric_pct"))
                    level = (r.get("containerization_level") or "").strip()
                    orch = (r.get("orchestrator") or "").strip()
                    if eff is None:
                        continue
                    arr.append((comp, eff, level, orch))
                # Sort descending by efficiency, break ties by company name ascending
                arr_sorted = sorted(arr, key=lambda x: (-x[1], x[0]))
                top3 = arr_sorted[:3]
                # Check bullets
                if len(bullets) == 3:
                    # For each bullet line, ensure it contains company name, efficiency with % sign, containerization_level, orchestrator
                    all_bullets_ok = True
                    for idx, b in enumerate(bullets):
                        comp, eff, level, orch = top3[idx]
                        # Check company present
                        if comp not in b:
                            all_bullets_ok = False
                        # Check efficiency with % sign present and matches number (allow integer vs float formatting)
                        # Create regex to find number optionally with .0 and %
                        eff_pattern = re.compile(rf"\b{int(eff) if abs(eff - int(eff)) < 1e-9 else eff}%\b")
                        if not eff_pattern.search(b.replace(" ", "")) and not eff_pattern.search(b):
                            # Also try tolerant match: find a number followed by % and compare as float
                            nums = re.findall(r"(\d+(?:\.\d+)?)\s*%", b)
                            matched = any(abs(float(x) - eff) < 1e-9 for x in nums)
                            if not matched:
                                all_bullets_ok = False
                        # Check containerization level present (exact normalized)
                        if level not in b:
                            all_bullets_ok = False
                        # Check orchestrator present (case-sensitive as in summary)
                        if orch not in b:
                            all_bullets_ok = False
                    bullets_top3_correct = all_bullets_ok

                if bullets_top3_correct:
                    scores["email_bullet_list_top3_correct"] = 1.0

                # Validate bullets include required fields regardless of order/phrasing
                if len(bullets) == 3:
                    all_include = True
                    for b in bullets:
                        # crude checks: must include a % sign, a containerization level token, and an orchestrator-like token (non-empty sequence of letters/parentheses)
                        if "%" not in b:
                            all_include = False
                        if not any(tok in b for tok in ["pilot", "partial", "full"]):
                            all_include = False
                        # orchestrator presence: require a known orchestrator token or "None"
                        if not any(tok in b for tok in ["Kubernetes", "Docker", "None"]):
                            all_include = False
                    if all_include:
                        scores["email_bullets_include_required_fields"] = 1.0

        # Next-step ask: one sentence at end
        non_empty_lines = [ln.strip() for ln in email_text.splitlines() if ln.strip() != ""]
        ask_ok = False
        if non_empty_lines:
            last_line = non_empty_lines[-1]
            # Count sentence-ending punctuation .!? in the last line
            ends = re.findall(r"[\.!\?]", last_line)
            # one sentence if at least one terminator but not more than one
            if 1 <= len(ends) <= 1:
                ask_ok = True
        if ask_ok:
            scores["email_next_step_one_sentence"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()