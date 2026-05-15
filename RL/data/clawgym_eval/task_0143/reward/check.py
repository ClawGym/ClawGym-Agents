import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            first_line = f.readline()
            if not first_line:
                return None
            header = [h.strip() for h in first_line.rstrip("\r\n").split(",")]
            f.seek(0)
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None


def read_first_line(path: Path) -> Optional[str]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            line = f.readline()
            if line == "":
                return ""
            return line.rstrip("\r\n")
    except Exception:
        return None


def parse_simple_tasks_yaml(path: Path) -> Optional[List[Dict[str, str]]]:
    """
    Parse a very simple YAML structure like:
    tasks:
      - title: ...
        due: YYYY-MM-DD
        status: next|todo|done
    """
    text = read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    tasks: List[Dict[str, str]] = []
    in_tasks = False
    current: Optional[Dict[str, str]] = None
    try:
        for raw in lines:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            if stripped == "tasks:":
                in_tasks = True
                continue
            if not in_tasks:
                continue
            # Item start: "- "
            if re.match(r"^\s*-\s+", line):
                # Start a new task
                if current:
                    tasks.append(current)
                current = {}
                # There might be inline key after "- " but our file uses separate lines; ignore here
                continue
            # Key: value lines within a task (two-space indent typical)
            m = re.match(r"^\s{2,}([A-Za-z0-9_]+)\s*:\s*(.*)$", line)
            if m and current is not None:
                key = m.group(1)
                val = m.group(2)
                current[key] = val
        if current:
            tasks.append(current)
        # Validate tasks have required keys
        cleaned: List[Dict[str, str]] = []
        for t in tasks:
            if all(k in t for k in ("title", "due", "status")):
                cleaned.append({"title": t["title"], "due": t["due"], "status": t["status"]})
        return cleaned
    except Exception:
        return None


def extract_section_lines(doc_text: str, header: str, all_headers: List[str]) -> Optional[List[str]]:
    """
    Extract lines belonging to a section with exact header line match.
    Returns list of lines (without the header) up to but not including the next header from all_headers.
    """
    lines = doc_text.splitlines()
    indices = [i for i, l in enumerate(lines) if l.strip() == header]
    if not indices:
        return None
    start = indices[0] + 1
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].strip() in all_headers:
            end = i
            break
    return lines[start:end]


def find_bullet_lines(section_lines: Optional[List[str]]) -> List[str]:
    if not section_lines:
        return []
    return [l.strip() for l in section_lines if l.strip().startswith("- ")]


def parse_placeholders(text: str) -> List[str]:
    return re.findall(r"\{[^}]+\}", text)


def word_count(text: str) -> int:
    # Count words by splitting on whitespace; this is sufficient for constraint enforcement.
    tokens = re.findall(r"\b\w[\w'-]*\b", text)
    return len(tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "weekly_summary_sections_present": 0.0,
        "weekly_summary_sections_order": 0.0,
        "regulatory_highlights_bullets_count_and_quotes": 0.0,
        "competitors_csv_header_correct": 0.0,
        "competitors_csv_rows_correct": 0.0,
        "weekly_summary_competitors_sentence_matches_count": 0.0,
        "weekly_summary_competitor_names_match_csv": 0.0,
        "open_questions_copied_verbatim": 0.0,
        "next_steps_bullets_correct": 0.0,
        "sources_used_include_required_paths": 0.0,
        "sources_used_paths_valid": 0.0,
        "outreach_rewrite_json_parse": 0.0,
        "outreach_rewrite_count_match_input": 0.0,
        "outreach_rewrite_ids_preserved": 0.0,
        "outreach_subject_length_ok": 0.0,
        "outreach_body_length_ok": 0.0,
        "outreach_placeholders_preserved": 0.0,
        "outreach_body_contains_required_term": 0.0,
    }

    # Paths
    reg_path = workspace / "input/research/regulation/psd2_psd3_notes.md"
    meeting_path = workspace / "input/notes/meetings/2026-04-10_partner_call.md"
    market_csv_path = workspace / "input/data/competitors/market_scan.csv"
    outreach_input_path = workspace / "input/messages/outreach_drafts.json"
    todo_yaml_path = workspace / "input/planning/todo.yaml"

    weekly_summary_path = workspace / "output/report/weekly_summary.md"
    competitors_out_csv_path = workspace / "output/data/competitors_in_austria.csv"
    outreach_rewrite_path = workspace / "output/messages/outreach_drafts_rewritten.json"

    # Load inputs
    reg_text = read_text(reg_path)
    meeting_text = read_text(meeting_path)
    market_csv = read_csv_dicts(market_csv_path)
    outreach_input_json = load_json(outreach_input_path)
    tasks_list = parse_simple_tasks_yaml(todo_yaml_path)

    # Expected filtered competitors from input
    expected_comp_rows: Optional[List[Tuple[str, str, str]]] = None
    expected_comp_names_set: Optional[set] = None
    if market_csv is not None:
        header_in, rows_in = market_csv
        try:
            expected_comp_rows = []
            for r in rows_in:
                supports = (r.get("supports_austria", "") or "").strip().upper()
                if supports == "TRUE":
                    name = (r.get("name") or "").strip()
                    pricing = (r.get("pricing_model") or "").strip()
                    settle = (r.get("settlement_time_days") or "").strip()
                    expected_comp_rows.append((name, pricing, settle))
            expected_comp_names_set = set([t[0] for t in expected_comp_rows])
        except Exception:
            expected_comp_rows = None
            expected_comp_names_set = None

    # Check competitors output CSV
    header_line = read_first_line(competitors_out_csv_path) if competitors_out_csv_path.exists() else None
    if header_line is not None and header_line == "name,pricing_model,settlement_time_days":
        scores["competitors_csv_header_correct"] = 1.0
    else:
        scores["competitors_csv_header_correct"] = 0.0

    out_csv = read_csv_dicts(competitors_out_csv_path) if competitors_out_csv_path.exists() else None
    out_comp_rows: Optional[List[Tuple[str, str, str]]] = None
    out_comp_names_set: Optional[set] = None
    if out_csv is not None:
        _, out_rows = out_csv
        try:
            out_comp_rows = []
            for r in out_rows:
                name = (r.get("name") or "").strip()
                pricing = (r.get("pricing_model") or "").strip()
                settle = (r.get("settlement_time_days") or "").strip()
                out_comp_rows.append((name, pricing, settle))
            out_comp_names_set = set([t[0] for t in out_comp_rows])
        except Exception:
            out_comp_rows = None
            out_comp_names_set = None

    if expected_comp_rows is not None and out_comp_rows is not None:
        if set(out_comp_rows) == set(expected_comp_rows):
            scores["competitors_csv_rows_correct"] = 1.0
        else:
            scores["competitors_csv_rows_correct"] = 0.0
    else:
        scores["competitors_csv_rows_correct"] = 0.0

    # Weekly summary checks
    weekly_text = read_text(weekly_summary_path)
    headers_required = [
        "Regulatory highlights (Austria/EEA):",
        "Competitors supporting Austria:",
        "Open questions from 2026-04-10 partner call:",
        "Next steps for the week:",
        "Sources used:",
    ]

    if weekly_text is not None:
        # Sections present
        present_flags = [header in [ln.strip() for ln in weekly_text.splitlines()] for header in headers_required]
        scores["weekly_summary_sections_present"] = 1.0 if all(present_flags) else 0.0

        # Sections order
        positions = []
        for header in headers_required:
            pos = None
            for i, l in enumerate(weekly_text.splitlines()):
                if l.strip() == header:
                    pos = i
                    break
            positions.append(pos)
        if all(p is not None for p in positions):
            in_order = all(positions[i] < positions[i + 1] for i in range(len(positions) - 1))
            scores["weekly_summary_sections_order"] = 1.0 if in_order else 0.0
        else:
            scores["weekly_summary_sections_order"] = 0.0

        # Regulatory highlights bullets
        reg_section_lines = extract_section_lines(weekly_text, headers_required[0], headers_required)
        reg_bullets = find_bullet_lines(reg_section_lines)
        reg_ok = False
        if reg_text is not None and 3 <= len(reg_bullets) <= 5:
            all_bullets_ok = True
            for b in reg_bullets:
                # Must end with required source tag
                suffix = "(source: input/research/regulation/psd2_psd3_notes.md)"
                if not b.endswith(" " + suffix):
                    all_bullets_ok = False
                    break
                # Must include one quoted phrase 3-10 words that exists verbatim in reg_text
                quotes = re.findall(r"\"([^\"]+)\"", b)
                quote_found_ok = False
                for q in quotes:
                    wc = len(q.strip().split())
                    if 3 <= wc <= 10 and q in reg_text:
                        quote_found_ok = True
                        break
                if not quote_found_ok:
                    all_bullets_ok = False
                    break
            reg_ok = all_bullets_ok
        scores["regulatory_highlights_bullets_count_and_quotes"] = 1.0 if reg_ok else 0.0

        # Competitors supporting Austria section: sentence and names
        comp_section_lines = extract_section_lines(weekly_text, headers_required[1], headers_required)
        comp_ok_cnt = False
        comp_ok_names = False
        x_val = None
        if comp_section_lines is not None:
            # Find the exact sentence line
            x_match_line_idx = None
            for idx, line in enumerate(comp_section_lines):
                m = re.match(r"^\s*Found\s+(\d+)\s+competitors\s+supporting\s+Austria\.\s*$", line)
                if m:
                    x_val = int(m.group(1))
                    x_match_line_idx = idx
                    break
            if x_match_line_idx is not None and out_comp_rows is not None:
                comp_ok_cnt = (x_val == len(out_comp_rows))
            # Parse names list line(s) - next non-empty line after the sentence
            names_line = None
            if x_match_line_idx is not None:
                for j in range(x_match_line_idx + 1, len(comp_section_lines)):
                    candid = comp_section_lines[j].strip()
                    if candid and not (candid in headers_required):
                        names_line = candid
                        break
            if names_line is not None and out_comp_names_set is not None:
                # Remove a leading bullet if present
                if names_line.startswith("- "):
                    names_line = names_line[2:].strip()
                # Split by comma
                names = [n.strip() for n in names_line.split(",") if n.strip()]
                comp_ok_names = set(names) == out_comp_names_set
        scores["weekly_summary_competitors_sentence_matches_count"] = 1.0 if comp_ok_cnt else 0.0
        scores["weekly_summary_competitor_names_match_csv"] = 1.0 if comp_ok_names else 0.0

        # Open questions verbatim
        oq_ok = False
        if meeting_text is not None:
            meeting_lines = [l.rstrip() for l in meeting_text.splitlines()]
            q_lines = [l.strip() for l in meeting_lines if l.strip().endswith("?")]
            oq_section_lines = extract_section_lines(weekly_text, headers_required[2], headers_required)
            oq_bullets = find_bullet_lines(oq_section_lines)
            # Compare sets; must match exactly those question lines (as bullets). The meeting q_lines already include "- " in this input.
            oq_ok = set(oq_bullets) == set(q_lines) and len(oq_bullets) == len(q_lines)
        scores["open_questions_copied_verbatim"] = 1.0 if oq_ok else 0.0

        # Next steps bullets correct
        next_steps_ok = False
        if tasks_list is not None:
            expected_bullets = []
            for t in tasks_list:
                if t.get("status") in ("next", "todo"):
                    expected_bullets.append(f"- [{t['status']}] {t['title']} (due: {t['due']})")
            next_section_lines = extract_section_lines(weekly_text, headers_required[3], headers_required)
            next_bullets = find_bullet_lines(next_section_lines)
            # Normalize bullets to exact matches
            # disallow any '- [done]' entries
            has_done = any(re.match(r"^- \[done\]", b) for b in next_bullets)
            next_steps_ok = (set(next_bullets) == set(expected_bullets)) and (len(next_bullets) == len(expected_bullets)) and (not has_done)
        scores["next_steps_bullets_correct"] = 1.0 if next_steps_ok else 0.0

        # Sources used
        sources_section_lines = extract_section_lines(weekly_text, headers_required[4], headers_required)
        sources_list: List[str] = []
        if sources_section_lines is not None:
            for raw in sources_section_lines:
                s = raw.strip()
                if not s:
                    continue
                if s.startswith("- "):
                    s = s[2:].strip()
                # Only consider non-empty lines
                if s:
                    sources_list.append(s)
        required_sources = {
            "input/research/regulation/psd2_psd3_notes.md",
            "input/notes/meetings/2026-04-10_partner_call.md",
            "input/data/competitors/market_scan.csv",
            "input/planning/todo.yaml",
        }
        allowed_sources = required_sources.union({"input/messages/outreach_drafts.json"})
        if set(required_sources).issubset(set(sources_list)):
            scores["sources_used_include_required_paths"] = 1.0
        else:
            scores["sources_used_include_required_paths"] = 0.0
        # All listed paths must be among allowed inputs
        if sources_list and all(src in allowed_sources for src in sources_list):
            scores["sources_used_paths_valid"] = 1.0
        else:
            # If section missing or includes invalid paths
            scores["sources_used_paths_valid"] = 0.0
    else:
        # Weekly summary missing: all related remain 0.0 by default
        pass

    # Outreach rewrite checks
    out_rewrite_json = load_json(outreach_rewrite_path) if outreach_rewrite_path.exists() else None
    if out_rewrite_json is not None and isinstance(out_rewrite_json, list):
        scores["outreach_rewrite_json_parse"] = 1.0
    else:
        scores["outreach_rewrite_json_parse"] = 0.0

    if outreach_input_json is not None and isinstance(outreach_input_json, list) and out_rewrite_json is not None and isinstance(out_rewrite_json, list):
        # Count match
        counts_match = len(out_rewrite_json) == len(outreach_input_json)
        scores["outreach_rewrite_count_match_input"] = 1.0 if counts_match else 0.0

        # Build mapping by id for both
        input_by_id: Dict[str, Dict[str, Any]] = {}
        for m in outreach_input_json:
            if isinstance(m, dict) and "id" in m:
                input_by_id[m["id"]] = m

        ids_preserved = True
        subj_len_ok = True
        body_len_ok = True
        placeholders_ok = True
        body_contains_term_ok = True

        for idx, out_msg in enumerate(out_rewrite_json):
            if not isinstance(out_msg, dict):
                ids_preserved = False
                subj_len_ok = False
                body_len_ok = False
                placeholders_ok = False
                body_contains_term_ok = False
                break
            # Required keys
            if "id" not in out_msg or "subject_rewrite" not in out_msg or "body_rewrite" not in out_msg:
                ids_preserved = False
                subj_len_ok = False
                body_len_ok = False
                placeholders_ok = False
                body_contains_term_ok = False
                break
            out_id = out_msg.get("id")
            if out_id not in input_by_id:
                ids_preserved = False
            # Subject length
            subject_rewrite = str(out_msg.get("subject_rewrite", ""))
            if len(subject_rewrite) > 60:
                subj_len_ok = False
            # Body word count
            body_rewrite = str(out_msg.get("body_rewrite", ""))
            wc = word_count(body_rewrite)
            if not (70 <= wc <= 120):
                body_len_ok = False
            # Placeholders preservation
            if out_id in input_by_id:
                orig = input_by_id[out_id]
                placeholders_in_subject = parse_placeholders(str(orig.get("subject", "")))
                placeholders_in_body = parse_placeholders(str(orig.get("body", "")))
                # For each placeholder in subject, ensure it exists in subject_rewrite
                for ph in placeholders_in_subject:
                    if ph not in subject_rewrite:
                        placeholders_ok = False
                        break
                # For each placeholder in body, ensure it exists in body_rewrite
                for ph in placeholders_in_body:
                    if ph not in body_rewrite:
                        placeholders_ok = False
                        break
            # Body must include at least one term
            if not re.search(r"\b(psd2|sepa|compliance)\b", body_rewrite, flags=re.IGNORECASE):
                body_contains_term_ok = False

        scores["outreach_rewrite_ids_preserved"] = 1.0 if ids_preserved else 0.0
        scores["outreach_subject_length_ok"] = 1.0 if subj_len_ok else 0.0
        scores["outreach_body_length_ok"] = 1.0 if body_len_ok else 0.0
        scores["outreach_placeholders_preserved"] = 1.0 if placeholders_ok else 0.0
        scores["outreach_body_contains_required_term"] = 1.0 if body_contains_term_ok else 0.0
    else:
        # If either input or output missing/malformed, keep zeros (already initialized)
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()