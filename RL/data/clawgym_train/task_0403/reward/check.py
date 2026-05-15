import json
import re
import sys
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _load_glossary(path: Path) -> Optional[Dict[str, str]]:
    data = _safe_load_json(path)
    if not isinstance(data, dict):
        return None
    terms = data.get("terms")
    if not isinstance(terms, list):
        return None
    syn_to_canonical: Dict[str, str] = {}
    for t in terms:
        if not isinstance(t, dict):
            return None
        canonical = t.get("canonical")
        syns = t.get("synonyms")
        if not isinstance(canonical, str) or not isinstance(syns, list):
            return None
        for s in syns:
            if isinstance(s, str) and s.strip():
                syn_to_canonical[s] = canonical
    return syn_to_canonical


def _load_refs(path: Path) -> Optional[set]:
    data = _safe_load_json(path)
    if not isinstance(data, dict):
        return None
    refs = data.get("refs")
    if isinstance(refs, list):
        return set([r for r in refs if isinstance(r, str)])
    return None


def _find_bracket_refs(text: str) -> List[str]:
    pattern = re.compile(r"\[ref:([A-Za-z0-9_]+)\]")
    return pattern.findall(text)


def _get_lines(path: Path) -> List[str]:
    txt = _safe_read_text(path)
    if txt is None:
        return []
    return txt.splitlines()


def _extract_changes_section_bullets(lines: List[str], section_title: str) -> Optional[List[str]]:
    # Returns list of bullet lines (starting with "- ") under a section title line exactly matching 'section_title:'
    # Section ends at blank line or next section with a trailing colon at line end.
    section_header_variants = {f"{section_title}:", section_title}
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() in section_header_variants:
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    bullets: List[str] = []
    for j in range(start_idx, len(lines)):
        l = lines[j].rstrip("\n")
        if not l.strip():
            # blank line marks possible end (but allow multiple blanks; still end)
            # Stop collecting at first blank, but continue only if next lines are bullets? We'll stop strictly at first blank or next section header.
            # To be strict and deterministic, stop at the first blank or next section header.
            break
        # If next section header encountered, stop.
        if l.strip().endswith(":") and l.strip()[:-1] and not l.strip().startswith("- "):
            break
        if l.strip().startswith("- "):
            bullets.append(l.strip())
        else:
            # Non-bullet line inside a section; still acceptable but does not count as bullet.
            continue
    return bullets


def _strip_hash_heading(line: str) -> str:
    if line.lstrip().startswith("#"):
        # Remove leading markdown header markers and spaces
        stripped = line.lstrip()
        i = 0
        while i < len(stripped) and stripped[i] == '#':
            i += 1
        return stripped[i:].strip()
    return line.strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "initial_report_exists_and_valid": 0.0,
        "initial_report_file_path_correct": 0.0,
        "cleaned_file_exists": 0.0,
        "cleaned_terms_replaced": 0.0,
        "cleaned_citations_corrected": 0.0,
        "final_report_exists_and_valid_zero_errors": 0.0,
        "final_report_file_path_correct": 0.0,
        "notes_title_correct": 0.0,
        "notes_summary_lines_match_reports": 0.0,
        "notes_changes_made_list_covers_replacements": 0.0,
        "notes_action_items_exact": 0.0,
    }

    # Paths
    initial_md = workspace / "input/manuscript/chapter_draft.md"
    glossary_json = workspace / "input/reference/glossary.json"
    refs_json = workspace / "input/reference/refs.json"
    validator_py = workspace / "input/tools/validate_manuscript.py"

    cleaned_md = workspace / "output/manuscript/chapter_draft.cleaned.md"
    report_initial = workspace / "out/validation/report_initial.json"
    report_final = workspace / "out/validation/report_final.json"
    notes_md = workspace / "out/meeting/notes.md"

    # Load reports if present
    report_initial_data = _safe_load_json(report_initial)
    report_final_data = _safe_load_json(report_final)

    # Check initial report
    if isinstance(report_initial_data, dict):
        summary = report_initial_data.get("summary")
        errors = report_initial_data.get("errors")
        file_field = report_initial_data.get("file")
        if isinstance(summary, dict) and isinstance(errors, list) and "error_count" in summary and "warning_count" in summary:
            scores["initial_report_exists_and_valid"] = 1.0
        if file_field == str(initial_md):
            scores["initial_report_file_path_correct"] = 1.0

    # Cleaned file exists
    cleaned_text = _safe_read_text(cleaned_md)
    if cleaned_text is not None:
        scores["cleaned_file_exists"] = 1.0

    # Validate replacements in cleaned file against inputs
    initial_text = _safe_read_text(initial_md) or ""
    syn_to_canonical = _load_glossary(glossary_json) or {}
    allowed_refs = _load_refs(refs_json) or set()

    # Determine which synonyms appear in initial text (case-insensitive search for simplicity)
    found_synonyms = []
    it_lower = initial_text.lower()
    for syn, canon in syn_to_canonical.items():
        if syn.lower() in it_lower:
            found_synonyms.append((syn, canon))

    # Check that for all found synonyms in initial, the cleaned file has canonical and not the synonym
    terms_ok = False
    if cleaned_text is not None and found_synonyms:
        cleaned_lower = cleaned_text.lower()
        all_repl = True
        for syn, canon in found_synonyms:
            if syn.lower() in cleaned_lower:
                all_repl = False
                break
            if canon.lower() not in cleaned_lower:
                all_repl = False
                break
        if all_repl:
            terms_ok = True
    elif cleaned_text is not None and not found_synonyms:
        # No synonyms in initial, trivially satisfied
        terms_ok = True
    scores["cleaned_terms_replaced"] = 1.0 if terms_ok else 0.0

    # Check citation corrections: all refs in cleaned should be allowed; unknowns in initial should be corrected
    citations_ok = False
    if cleaned_text is not None:
        initial_refs = _find_bracket_refs(initial_text)
        cleaned_refs = _find_bracket_refs(cleaned_text)

        initial_unknown = [r for r in initial_refs if r not in allowed_refs]
        cleaned_unknown = [r for r in cleaned_refs if r not in allowed_refs]

        # Condition A: No unknown refs remain in cleaned
        cond_a = len(cleaned_unknown) == 0

        # Condition B: If there were unknowns initially, they should not be present in cleaned
        cond_b = True
        for r in initial_unknown:
            if f"[ref:{r}]" in cleaned_text:
                cond_b = False
                break

        # Additionally, for this dataset, ensure the specific intended correction if applicable
        specific_ok = True
        if "dayan_abbot_2001" in initial_unknown:
            specific_ok = "[ref:dayan_abbott_2001]" in cleaned_text

        citations_ok = cond_a and cond_b and specific_ok
    scores["cleaned_citations_corrected"] = 1.0 if citations_ok else 0.0

    # Check final report
    if isinstance(report_final_data, dict):
        summary_f = report_final_data.get("summary")
        errors_f = report_final_data.get("errors")
        file_field_f = report_final_data.get("file")
        if (
            isinstance(summary_f, dict)
            and isinstance(errors_f, list)
            and "error_count" in summary_f
            and "warning_count" in summary_f
            and isinstance(summary_f.get("error_count"), int)
            and summary_f.get("error_count") == 0
        ):
            scores["final_report_exists_and_valid_zero_errors"] = 1.0
        if file_field_f == str(cleaned_md):
            scores["final_report_file_path_correct"] = 1.0

    # Meeting notes checks
    notes_text = _safe_read_text(notes_md)
    if notes_text is not None:
        lines = notes_text.splitlines()
        # Title check: first non-empty line must equal the required title (allow optional leading Markdown heading markers)
        required_title = "Neuro Chapter Validation – Meeting Notes"
        first_non_empty = ""
        for l in lines:
            if l.strip():
                first_non_empty = l
                break
        if _strip_hash_heading(first_non_empty) == required_title:
            scores["notes_title_correct"] = 1.0

        # Summary lines: must include exact two lines with counts and paths
        def _find_summary_line(prefix: str) -> Optional[str]:
            for l in lines:
                if l.strip().startswith(prefix):
                    # Must match exactly after prefix formatting
                    return l.strip()
            return None

        # Build expected strings from reports if available
        init_err = None
        init_warn = None
        fin_err = None
        fin_warn = None
        if isinstance(report_initial_data, dict) and isinstance(report_initial_data.get("summary"), dict):
            init_err = report_initial_data["summary"].get("error_count")
            init_warn = report_initial_data["summary"].get("warning_count")
        if isinstance(report_final_data, dict) and isinstance(report_final_data.get("summary"), dict):
            fin_err = report_final_data["summary"].get("error_count")
            fin_warn = report_final_data["summary"].get("warning_count")

        summary_ok = False
        if init_err is not None and init_warn is not None and fin_err is not None and fin_warn is not None:
            expected_initial_line = f"Initial validation: error_count={init_err}, warning_count={init_warn}, report=out/validation/report_initial.json"
            expected_final_line = f"Final validation: error_count={fin_err}, warning_count={fin_warn}, report=out/validation/report_final.json"
            found_initial_line = _find_summary_line("Initial validation:")
            found_final_line = _find_summary_line("Final validation:")
            if found_initial_line == expected_initial_line and found_final_line == expected_final_line:
                summary_ok = True
        scores["notes_summary_lines_match_reports"] = 1.0 if summary_ok else 0.0

        # Changes Made bullets
        changes_bullets = _extract_changes_section_bullets(lines, "Changes Made")
        changes_ok = False
        if changes_bullets is not None:
            # Determine expected changes based on initial content
            expected_pairs = []
            for syn, canon in syn_to_canonical.items():
                if syn.lower() in (initial_text.lower()):
                    expected_pairs.append((syn, canon))
            # Citation fix expected pairs (just include the one we know from input)
            if "dayan_abbot_2001" in _find_bracket_refs(initial_text):
                expected_pairs.append(("dayan_abbot_2001", "dayan_abbott_2001"))

            # Each expected pair should appear together in a bullet line
            def pair_in_bullets(pair: Tuple[str, str]) -> bool:
                a, b = pair
                for bl in changes_bullets:
                    bl_lower = bl.lower()
                    if a.lower() in bl_lower and b.lower() in bl_lower:
                        return True
                return False

            all_present = True
            for p in expected_pairs:
                if not pair_in_bullets(p):
                    all_present = False
                    break
            changes_ok = all_present
        scores["notes_changes_made_list_covers_replacements"] = 1.0 if changes_ok else 0.0

        # Action Items exact
        action_bullets = _extract_changes_section_bullets(lines, "Action Items")
        action_ok = False
        if action_bullets is not None:
            # Normalize bullets to their text after "- "
            normalized = []
            for b in action_bullets:
                t = b.strip()
                if t.startswith("- "):
                    normalized.append(t[2:].strip())
                else:
                    normalized.append(t.strip())
            required_actions = {
                "Confirm with scientific editor whether \"astrocyte\" is the preferred singular/plural usage in this context.",
                "Scan remaining chapters with the same validator and standardize terms accordingly.",
            }
            if set(normalized) == required_actions and len(normalized) == 2:
                action_ok = True
        scores["notes_action_items_exact"] = 1.0 if action_ok else 0.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) > 1:
        workspace_path = sys.argv[1]
    scores = grade([], workspace_path)
    print(json.dumps(scores, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()