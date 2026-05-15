import json
import sys
import re
import csv
import importlib.util
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


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _load_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML loader for simple mappings with nested dicts via indentation.
    Supports lines of the form:
      key: "value"
      key:
        subkey: "value"
    Does not support lists or complex types. Sufficient for the provided config.
    """
    text = _read_text(path)
    if text is None:
        return None
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    try:
        for raw_line in text.splitlines():
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            line = raw_line.strip()
            if ":" not in line:
                return None
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            while stack and indent <= stack[-1][0]:
                stack.pop()
            current = stack[-1][1]
            if val == "":
                # start of nested dict
                new_map: Dict[str, Any] = {}
                current[key] = new_map
                stack.append((indent, new_map))
            else:
                # scalar
                sval = _strip_quotes(val)
                # Interpret common scalars
                if sval.lower() == "true":
                    current[key] = True
                elif sval.lower() == "false":
                    current[key] = False
                else:
                    current[key] = sval
        return root
    except Exception:
        return None


def _load_signature(py_path: Path) -> Optional[str]:
    try:
        spec = importlib.util.spec_from_file_location("sigmod", str(py_path))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore
        sig = getattr(mod, "SIGNATURE", None)
        if isinstance(sig, str):
            return sig
        return None
    except Exception:
        return None


def _parse_stakeholders_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows: List[Dict[str, Any]] = []
            for row in reader:
                # normalize booleans
                for k in ("notify_on_collab", "include_in_first_email"):
                    v = row.get(k, "")
                    if isinstance(v, str):
                        row[k] = v.strip().lower() == "true"
                    else:
                        row[k] = bool(v)
                rows.append(row)
            return rows
    except Exception:
        return None


def _compute_prototype_aggregates(protos: List[Dict[str, Any]]) -> Dict[str, Any]:
    statuses_count: Dict[str, int] = {}
    risks_set = set()
    actions_set = set()
    for p in protos:
        st = p.get("status", "")
        statuses_count[st] = statuses_count.get(st, 0) + 1
        for r in p.get("risks", []) or []:
            risks_set.add(r)
        for a in p.get("next_actions", []) or []:
            actions_set.add(a)
    unique_risks = sorted(risks_set)
    unique_actions = sorted(actions_set)
    return {
        "total_prototypes": len(protos),
        "statuses_count": statuses_count,
        "unique_risks": unique_risks,
        "unique_next_actions": unique_actions,
    }


def _extract_email_headers_and_body(text: str) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    lines = text.splitlines()
    non_empty_indices = [i for i, ln in enumerate(lines) if ln.strip() != ""]
    if len(non_empty_indices) < 3:
        return (None, None, None, "")
    first_three = non_empty_indices[:3]
    to_line = lines[first_three[0]].strip()
    cc_line = lines[first_three[1]].strip()
    subj_line = lines[first_three[2]].strip()
    if not to_line.startswith("To:") or not cc_line.startswith("Cc:") or not subj_line.startswith("Subject:"):
        return (None, None, None, "")
    to_val = to_line[len("To:"):].strip()
    cc_val = cc_line[len("Cc:"):].strip()
    subj_val = subj_line[len("Subject:"):].strip()
    body = "\n".join(lines[first_three[2] + 1:])  # everything after Subject line
    return (to_val, cc_val, subj_val, body)


def _clean_bullet_line(line: str) -> Optional[str]:
    m = re.match(r"^\s*([-*])\s+(.*)$", line)
    if m:
        return m.group(2).strip()
    # allow plain lines (no bullet), return trimmed non-empty
    s = line.strip()
    if s:
        return s
    return None


def _find_section_blocks(lines: List[str], titles: List[str]) -> Dict[str, Tuple[int, int]]:
    """
    Returns mapping from title to (start_idx_inclusive, end_idx_exclusive)
    Section titles may appear as exact title or markdown headings #/## + title.
    """
    title_indices: Dict[str, int] = {}
    # find indices for each title, the last match for each (should be unique ideally)
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        for t in titles:
            if stripped == t or stripped == f"# {t}" or stripped == f"## {t}" or stripped == f"### {t}":
                if t not in title_indices:
                    title_indices[t] = i
    blocks: Dict[str, Tuple[int, int]] = {}
    sorted_indices = sorted([(idx, t) for t, idx in title_indices.items()])
    for j, (idx, title) in enumerate(sorted_indices):
        end = len(lines)
        if j + 1 < len(sorted_indices):
            end = sorted_indices[j + 1][0]
        blocks[title] = (idx + 1, end)
    return blocks


def _section_content(lines: List[str], block: Tuple[int, int]) -> List[str]:
    s, e = block
    return lines[s:e]


def _contains_total_with_prototype(text: str, total: int) -> bool:
    # Look for number near the word "prototype" or "prototypes"
    pattern = re.compile(rf"\b{total}\b[^.\n]{{0,50}}\bprototypes?\b|\bprototypes?\b[^.\n]{{0,50}}\b{total}\b", re.IGNORECASE)
    return bool(pattern.search(text))


def _status_with_count_present(text: str, status: str, count: int) -> bool:
    # count near status within 10 characters either side, or in parentheses nearby
    esc_status = re.escape(status)
    patterns = [
        rf"\b{count}\b[^0-9]{{0,10}}{esc_status}",
        rf"{esc_status}[^0-9]{{0,10}}\b{count}\b",
        rf"{esc_status}\s*\(\s*{count}\s*\)",
    ]
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "email_headers_presence_and_order": 0.0,
        "email_to_correct": 0.0,
        "email_cc_correct": 0.0,
        "email_subject_contains_project_and_mdw": 0.0,
        "email_shared_history_opening_once": 0.0,
        "email_prototype_summary_present": 0.0,
        "email_risks_bulleted_top3_alphabetical": 0.0,
        "email_call_proposal_next_week_30min": 0.0,
        "email_closing_signoff_and_signature": 0.0,
        "report_sections_and_titles": 0.0,
        "report_overview_counts_correct": 0.0,
        "report_by_prototype_lines_correct": 0.0,
        "report_risks_list_correct": 0.0,
        "report_next_actions_list_correct": 0.0,
        "snapshot_structure_fields_present": 0.0,
        "snapshot_aggregates_correct": 0.0,
        "snapshot_subject_and_cc_consistency": 0.0,
    }

    # Load inputs
    cfg_path = workspace / "config" / "email_config.yaml"
    sig_path = workspace / "config" / "signature.py"
    proto_path = workspace / "data" / "prototype_status.json"
    stakeholders_path = workspace / "data" / "stakeholders.csv"

    cfg = _load_simple_yaml(cfg_path)
    sig = _load_signature(sig_path)
    protos = _load_json(proto_path)
    stakeholders = _parse_stakeholders_csv(stakeholders_path)

    # If any inputs are missing, some checks can't proceed
    # Compute expected aggregates if possible
    aggregates = None
    if isinstance(protos, list):
        aggregates = _compute_prototype_aggregates(protos)

    # Compute expected CC emails
    expected_cc: Optional[List[str]] = None
    if isinstance(stakeholders, list):
        expected_cc = [r["email"].strip() for r in stakeholders if r.get("notify_on_collab") and r.get("include_in_first_email")]

    # Expected recipient and subject tokens
    recipient_email = None
    recipient_name = None
    shared_history = None
    sign_off = None
    project_name = None
    collab_goal = None
    timeline = None
    if isinstance(cfg, dict):
        recipient = cfg.get("recipient", {}) if isinstance(cfg.get("recipient"), dict) else {}
        recipient_email = recipient.get("email")
        recipient_name = recipient.get("name")
        shared_history = recipient.get("shared_history")
        sign_off = cfg.get("sign_off")
        project_name = cfg.get("project_name")
        collab_goal = cfg.get("collaboration_goal")
        timeline = cfg.get("timeline") if isinstance(cfg.get("timeline"), dict) else None

    # Load deliverables
    email_path = workspace / "output" / "email_to_nika_zupanc.md"
    report_path = workspace / "output" / "prototype_status_report.md"
    snapshot_path = workspace / "output" / "project_snapshot.json"

    email_text = _read_text(email_path)
    report_text = _read_text(report_path)
    snapshot = _load_json(snapshot_path)

    # EMAIL checks
    to_val = cc_val = subj_val = None
    body = ""
    if email_text is not None:
        to_val, cc_val, subj_val, body = _extract_email_headers_and_body(email_text)
        if to_val is not None and cc_val is not None and subj_val is not None:
            scores["email_headers_presence_and_order"] = 1.0

    if recipient_email is not None and isinstance(to_val, str):
        if to_val.strip() == recipient_email.strip():
            scores["email_to_correct"] = 1.0

    if expected_cc is not None and isinstance(cc_val, str):
        actual_cc_list: List[str] = []
        if cc_val.strip() != "":
            actual_cc_list = [e.strip() for e in cc_val.split(",") if e.strip()]
        # Compare as sets and lengths to avoid duplicates
        if len(actual_cc_list) == len(expected_cc) and set(actual_cc_list) == set(expected_cc):
            scores["email_cc_correct"] = 1.0

    if isinstance(subj_val, str) and isinstance(project_name, str) and isinstance(collab_goal, str):
        contains_proj = project_name in subj_val
        contains_mdw = "Milan Design Week" in subj_val  # exact phrase
        if contains_proj and contains_mdw:
            scores["email_subject_contains_project_and_mdw"] = 1.0

    if isinstance(body, str) and isinstance(shared_history, str):
        body_lines = [ln for ln in body.splitlines()]
        # first non-empty line
        first_content_line = None
        for ln in body_lines:
            if ln.strip():
                first_content_line = ln
                break
        if first_content_line is not None:
            count_occ = body.count(shared_history)
            if shared_history in first_content_line and count_occ == 1:
                scores["email_shared_history_opening_once"] = 1.0

    if isinstance(body, str) and aggregates is not None:
        total = aggregates["total_prototypes"]
        statuses_count = aggregates["statuses_count"]
        has_total = _contains_total_with_prototype(body, total)
        all_statuses_ok = all(_status_with_count_present(body, st, cnt) for st, cnt in statuses_count.items())
        if has_total and all_statuses_ok:
            scores["email_prototype_summary_present"] = 1.0

    if isinstance(body, str) and aggregates is not None:
        # Expected top 3 risks
        expected_risks_sorted = aggregates["unique_risks"][:]
        # Dedup and sort already in aggregates
        top3 = expected_risks_sorted[:3]
        # Extract bullets exactly three
        bullets = []
        for ln in body.splitlines():
            m = re.match(r"^\s*([-*])\s+(.*)$", ln)
            if m:
                bullets.append(m.group(2).strip())
        if len(bullets) == 3 and bullets == top3:
            scores["email_risks_bulleted_top3_alphabetical"] = 1.0

    if isinstance(body, str):
        bl = body.lower()
        has_next_week = "next week" in bl
        has_30min = ("30-minute" in bl) or ("30 minute" in bl) or ("30min" in bl)
        asks_pref = ("preferred time" in bl) or ("what time works" in bl) or ("works for you" in bl) or ("suits you" in bl) or ("your availability" in bl) or ("let me know" in bl and "time" in bl)
        if has_next_week and has_30min and asks_pref:
            scores["email_call_proposal_next_week_30min"] = 1.0

    if isinstance(email_text, str) and isinstance(sign_off, str) and isinstance(sig, str):
        trimmed = email_text.rstrip()
        expected_tail = f"{sign_off},\n{sig}".rstrip()
        if trimmed.endswith(expected_tail):
            scores["email_closing_signoff_and_signature"] = 1.0

    # REPORT checks
    section_titles = ["Overview", "By Prototype", "Risks", "Next Actions"]
    if isinstance(report_text, str):
        report_lines = report_text.splitlines()
        blocks = _find_section_blocks(report_lines, section_titles)
        # Ensure all sections present exactly once
        if all(t in blocks for t in section_titles):
            scores["report_sections_and_titles"] = 1.0

        if "Overview" in blocks and aggregates is not None:
            overview_text = "\n".join(_section_content(report_lines, blocks["Overview"]))
            total_ok = _contains_total_with_prototype(overview_text, aggregates["total_prototypes"])
            statuses_ok = all(_status_with_count_present(overview_text, st, cnt) for st, cnt in aggregates["statuses_count"].items())
            if total_ok and statuses_ok:
                scores["report_overview_counts_correct"] = 1.0

        if "By Prototype" in blocks and isinstance(protos, list):
            byp_lines_raw = [ln.strip() for ln in _section_content(report_lines, blocks["By Prototype"])]
            # Remove empty lines
            byp_lines = [ln for ln in byp_lines_raw if ln]
            # Clean optional bullets
            cleaned_lines: List[str] = []
            for ln in byp_lines:
                cb = _clean_bullet_line(ln)
                if cb:
                    cleaned_lines.append(cb)
            expected_lines = [f"{p['name']} — {p['status']} — {p['last_updated']}" for p in protos]
            if len(cleaned_lines) == len(expected_lines) and set(cleaned_lines) == set(expected_lines):
                scores["report_by_prototype_lines_correct"] = 1.0

        if "Risks" in blocks and aggregates is not None:
            risks_lines_raw = [ln.strip() for ln in _section_content(report_lines, blocks["Risks"])]
            risks_clean = []
            for ln in risks_lines_raw:
                cb = _clean_bullet_line(ln)
                if cb:
                    risks_clean.append(cb)
            # Remove empties
            risks_clean = [r for r in risks_clean if r]
            expected_risks = aggregates["unique_risks"]
            if risks_clean == expected_risks:
                scores["report_risks_list_correct"] = 1.0

        if "Next Actions" in blocks and aggregates is not None:
            acts_lines_raw = [ln.strip() for ln in _section_content(report_lines, blocks["Next Actions"])]
            acts_clean = []
            for ln in acts_lines_raw:
                cb = _clean_bullet_line(ln)
                if cb:
                    acts_clean.append(cb)
            acts_clean = [a for a in acts_clean if a]
            expected_actions = aggregates["unique_next_actions"]
            if acts_clean == expected_actions:
                scores["report_next_actions_list_correct"] = 1.0

    # SNAPSHOT checks
    if isinstance(snapshot, dict):
        # Structure presence
        top_keys = set(snapshot.keys())
        expected_top = {"project", "recipient", "subject", "cc_emails", "aggregates"}
        struct_ok = top_keys == expected_top
        project = snapshot.get("project", {})
        recipient_obj = snapshot.get("recipient", {})
        proj_ok = isinstance(project, dict) and set(project.keys()) == {"name", "collaboration_goal", "timeline"}
        timeline_obj = project.get("timeline", {}) if isinstance(project, dict) else {}
        timeline_ok = isinstance(timeline_obj, dict) and set(timeline_obj.keys()) == {"prototype_ship_by", "pitch_deck_by"}
        recipient_ok = isinstance(recipient_obj, dict) and set(recipient_obj.keys()) == {"name", "email"}
        subject_ok = isinstance(snapshot.get("subject"), str)
        cc_ok = isinstance(snapshot.get("cc_emails"), list) and all(isinstance(e, str) for e in snapshot.get("cc_emails"))
        aggr_obj = snapshot.get("aggregates", {})
        aggr_ok = isinstance(aggr_obj, dict) and set(aggr_obj.keys()) == {"total_prototypes", "statuses_count", "unique_risks", "unique_next_actions"}
        if struct_ok and proj_ok and timeline_ok and recipient_ok and subject_ok and cc_ok and aggr_ok:
            scores["snapshot_structure_fields_present"] = 1.0

        # Aggregates correct and project fields
        agg_pass = False
        proj_pass = False
        if aggregates is not None and cfg is not None:
            # Compare aggregates
            snap_agg = snapshot.get("aggregates", {})
            if (
                isinstance(snap_agg, dict)
                and snap_agg.get("total_prototypes") == aggregates["total_prototypes"]
                and snap_agg.get("statuses_count") == aggregates["statuses_count"]
                and snap_agg.get("unique_risks") == aggregates["unique_risks"]
                and snap_agg.get("unique_next_actions") == aggregates["unique_next_actions"]
            ):
                agg_pass = True
            # Project fields
            proj = snapshot.get("project", {})
            expected_name = project_name
            expected_goal = collab_goal
            expected_timeline = timeline
            if (
                isinstance(proj, dict)
                and proj.get("name") == expected_name
                and proj.get("collaboration_goal") == expected_goal
                and isinstance(proj.get("timeline"), dict)
                and proj.get("timeline") == expected_timeline
            ):
                proj_pass = True
        if agg_pass and proj_pass:
            scores["snapshot_aggregates_correct"] = 1.0

        # Subject and CC consistency with email and inputs
        subj_consistent = False
        cc_consistent = False
        snap_subject = snapshot.get("subject")
        snap_cc = snapshot.get("cc_emails")
        if isinstance(subj_val, str) and isinstance(snap_subject, str) and isinstance(project_name, str):
            contains_proj = project_name in snap_subject
            contains_mdw = "Milan Design Week" in snap_subject
            if snap_subject == subj_val and contains_proj and contains_mdw:
                subj_consistent = True
        if expected_cc is not None and isinstance(snap_cc, list):
            if len(snap_cc) == len(expected_cc) and set(snap_cc) == set(expected_cc):
                cc_consistent = True
        if subj_consistent and cc_consistent:
            scores["snapshot_subject_and_cc_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()