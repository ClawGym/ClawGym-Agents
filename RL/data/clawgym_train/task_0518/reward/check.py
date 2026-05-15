import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_lines(path: Path) -> Optional[List[str]]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None


def _read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_sources(workspace: Path, rel_paths: List[str]) -> Dict[str, Optional[List[str]]]:
    result: Dict[str, Optional[List[str]]] = {}
    for rp in rel_paths:
        result[rp] = _read_lines(workspace / rp)
    return result


def _run_validator(workspace: Path) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    script = workspace / "scripts" / "validate_outputs.py"
    if not script.exists():
        return None, None, None
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception:
        return None, None, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "facts_json_parseable": 0.0,
        "facts_fields_and_ids_valid": 0.0,
        "facts_support_excerpts_correct": 0.0,
        "facts_coverage_requirements_met": 0.0,
        "email_invite_required_details": 0.0,
        "meeting_notes_basic_structure": 0.0,
        "meeting_notes_has_decisions_section": 0.0,
        "meeting_notes_references_known": 0.0,
        "meeting_notes_action_items_min3": 0.0,
        "key_facts_section_covers_all_ids": 0.0,
        "validator_run_success": 0.0,
        "validation_report_exists": 0.0,
        "validation_report_indicates_success": 0.0,
    }

    # Expected paths
    sources_list = [
        "input/docs/tamaizumi_history.md",
        "input/docs/water_quality_report.txt",
        "input/data/past_events.csv",
        "input/draft_invite.txt",
    ]
    sources_lines = _load_sources(workspace, sources_list)

    facts_path = workspace / "output" / "facts" / "facts_summary.json"
    email_path = workspace / "output" / "email_invite.txt"
    notes_path = workspace / "output" / "meeting_notes.md"
    report_path = workspace / "output" / "validation" / "validation_report.txt"

    # Facts checks
    facts = _read_json(facts_path)
    id_set = set()
    if isinstance(facts, list):
        scores["facts_json_parseable"] = 1.0
        # Validate fields, ids
        required_keys = {"id", "fact_text", "source_file", "support_lines", "support_excerpt"}
        fields_ok = True
        support_ok = True
        coverage_history = False
        coverage_water_numeric = False
        coverage_events_numeric = False

        # Prepare sources for support excerpt verification
        if any(sources_lines.get(p) is None for p in sources_list):
            support_ok = False

        if len(facts) < 5:
            fields_ok = False

        for i, fact in enumerate(facts, 1):
            if not isinstance(fact, dict):
                fields_ok = False
                support_ok = False
                break
            # Enforce exactly the required set of keys
            if set(fact.keys()) != required_keys:
                fields_ok = False

            fid = fact.get("id")
            if not isinstance(fid, str) or re.fullmatch(r"F\d+", fid) is None:
                fields_ok = False
            if fid in id_set:
                fields_ok = False
            id_set.add(fid)

            ftxt = fact.get("fact_text")
            if not isinstance(ftxt, str) or len(ftxt) == 0 or len(ftxt) > 280:
                fields_ok = False

            src = fact.get("source_file")
            if src not in sources_list:
                fields_ok = False

            sl = fact.get("support_lines")
            excerpt = fact.get("support_excerpt")
            # Support lines and excerpt check
            if (
                isinstance(src, str)
                and src in sources_list
                and sources_lines.get(src) is not None
                and isinstance(sl, list)
                and len(sl) == 2
                and all(isinstance(n, int) for n in sl)
                and isinstance(excerpt, str)
            ):
                src_lines = sources_lines[src]
                start, end = sl
                if start < 1 or end < start or end > len(src_lines):
                    support_ok = False
                else:
                    joined = "\n".join(src_lines[start - 1 : end])
                    if excerpt != joined:
                        support_ok = False
            else:
                support_ok = False

            # Coverage checks
            if isinstance(src, str) and src.endswith("tamaizumi_history.md"):
                coverage_history = True
            if isinstance(src, str) and src.endswith("water_quality_report.txt") and isinstance(ftxt, str) and re.search(r"\d", ftxt):
                coverage_water_numeric = True
            if isinstance(src, str) and src.endswith("past_events.csv") and isinstance(ftxt, str) and re.search(r"\d", ftxt):
                coverage_events_numeric = True

        scores["facts_fields_and_ids_valid"] = 1.0 if fields_ok else 0.0
        scores["facts_support_excerpts_correct"] = 1.0 if support_ok else 0.0
        coverage_ok = coverage_history and coverage_water_numeric and coverage_events_numeric
        scores["facts_coverage_requirements_met"] = 1.0 if coverage_ok else 0.0
    else:
        scores["facts_json_parseable"] = 0.0
        scores["facts_fields_and_ids_valid"] = 0.0
        scores["facts_support_excerpts_correct"] = 0.0
        scores["facts_coverage_requirements_met"] = 0.0
        id_set = set()

    # Email invite checks
    email_txt = _read_text(email_path)
    if isinstance(email_txt, str):
        length_ok = len(email_txt) <= 1200
        required_bits = ["2024-05-10", "18:00", "Community Center Room 2", "Tamaizumi-ike"]
        contains_ok = all(bit in email_txt for bit in required_bits)
        scores["email_invite_required_details"] = 1.0 if (length_ok and contains_ok) else 0.0
    else:
        scores["email_invite_required_details"] = 0.0

    # Meeting notes checks
    notes_txt = _read_text(notes_path)
    if isinstance(notes_txt, str):
        notes_lines = notes_txt.splitlines()
        basic_reqs = [
            "Tamaizumi-ike Community Meeting",
            "Date: 2024-05-10",
            "Agenda",
            "Key facts",
            "Action items",
        ]
        basic_ok = all(req in notes_txt for req in basic_reqs)
        scores["meeting_notes_basic_structure"] = 1.0 if basic_ok else 0.0

        # Decisions section explicitly required by the task
        has_decisions = "Decisions" in notes_txt
        scores["meeting_notes_has_decisions_section"] = 1.0 if has_decisions else 0.0

        # References [F#]
        ref_ids = set(re.findall(r"\[F(\d+)\]", notes_txt))
        ref_ids = {f"F{n}" for n in ref_ids}
        references_present = len(ref_ids) > 0
        if id_set:
            unknown = [rid for rid in ref_ids if rid not in id_set]
            refs_known_ok = references_present and len(unknown) == 0
        else:
            refs_known_ok = False
        scores["meeting_notes_references_known"] = 1.0 if refs_known_ok else 0.0

        # Action items: at least 3 bullet lines containing a [F#]
        action_item_lines = [
            line for line in notes_lines if line.strip().startswith("-") and re.search(r"\[F\d+\]", line) is not None
        ]
        scores["meeting_notes_action_items_min3"] = 1.0 if len(action_item_lines) >= 3 else 0.0

        # Key facts section should list facts with their ids: ensure all ids appear in that section
        key_facts_ids_ok = False
        if id_set and "Key facts" in notes_txt:
            # Find Key facts section bounds
            start_idx = None
            end_idx = None
            headings = ["Agenda", "Key facts", "Decisions", "Action items"]
            for i, line in enumerate(notes_lines):
                if "Key facts" in line:
                    start_idx = i + 1
                    break
            if start_idx is not None:
                for j in range(start_idx, len(notes_lines)):
                    if j != start_idx and any(h in notes_lines[j] for h in headings if h != "Key facts"):
                        end_idx = j
                        break
                if end_idx is None:
                    end_idx = len(notes_lines)
                section_text = "\n".join(notes_lines[start_idx:end_idx])
                section_ids = set(re.findall(r"\bF\d+\b", section_text))
                key_facts_ids_ok = id_set.issubset(section_ids)
        scores["key_facts_section_covers_all_ids"] = 1.0 if key_facts_ids_ok else 0.0
    else:
        scores["meeting_notes_basic_structure"] = 0.0
        scores["meeting_notes_has_decisions_section"] = 0.0
        scores["meeting_notes_references_known"] = 0.0
        scores["meeting_notes_action_items_min3"] = 0.0
        scores["key_facts_section_covers_all_ids"] = 0.0

    # Validator run and report checks
    retcode, stdout, stderr = _run_validator(workspace)
    if retcode is not None and stdout is not None:
        run_ok = (retcode == 0) and ("SUCCESS: All checks passed." in stdout)
        scores["validator_run_success"] = 1.0 if run_ok else 0.0
    else:
        scores["validator_run_success"] = 0.0

    report_txt = _read_text(report_path)
    if isinstance(report_txt, str):
        scores["validation_report_exists"] = 1.0
        scores["validation_report_indicates_success"] = 1.0 if "SUCCESS: All checks passed." in report_txt else 0.0
    else:
        scores["validation_report_exists"] = 0.0
        scores["validation_report_indicates_success"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    # Do not sort keys to preserve insertion order for downstream comparisons
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()