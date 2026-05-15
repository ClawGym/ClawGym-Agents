import json
import sys
import re
import csv
from pathlib import Path
from typing import Optional, List, Dict, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def _safe_read_csv_dict(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _parse_markdown_sections(text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current_key: Optional[str] = None
    for line in text.splitlines():
        m = re.match(r'^\s{0,3}#{1,6}\s*(.+?)\s*$', line)
        if m:
            title = m.group(1).strip().rstrip(':').lower()
            current_key = title
            if current_key not in sections:
                sections[current_key] = []
        else:
            if current_key is not None:
                sections[current_key].append(line)
    return sections


def _count_bullets(lines: List[str]) -> int:
    count = 0
    for line in lines:
        if re.match(r'^\s*[-*]\s+', line):
            count += 1
        elif re.match(r'^\s*\d+[.)]\s+', line):
            count += 1
    return count


def _contains_any(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def _extract_path_like_count(text: str) -> int:
    tokens = re.findall(r'[\w\-.]+(?:/[\w\-.]+)+', text)
    return len(tokens)


def _normalize_line_for_match(s: str) -> str:
    s = s.strip()
    s = re.sub(r'^\s*>\s*', '', s)
    s = s.strip()
    return s


def _load_log_lines(path: Path) -> List[str]:
    content = _safe_read_text(path)
    if content is None:
        return []
    lines = [line.rstrip("\r\n") for line in content.splitlines()]
    return lines


def _compute_2023_summary(input_path: Path) -> Optional[Tuple[int, int, int, int, int, int]]:
    rows = _safe_read_csv_dict(input_path)
    if rows is None or len(rows) == 0:
        return None
    games = 0
    wins = 0
    losses = 0
    ties = 0
    pf = 0
    pa = 0
    required_keys = {"OLSM_Score", "Opp_Score", "Result"}
    if not required_keys.issubset(set(rows[0].keys())):
        return None
    for row in rows:
        try:
            games += 1
            pf += int(row["OLSM_Score"])
            pa += int(row["Opp_Score"])
            r = row["Result"]
            if r == "W":
                wins += 1
            elif r == "L":
                losses += 1
            elif r == "T":
                ties += 1
            else:
                return None
        except Exception:
            return None
    return (games, wins, losses, ties, pf, pa)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "log_file_present": 0.0,
        "log_contains_processing_lines": 0.0,
        "log_contains_traceback_keyerror": 0.0,
        "arch_doc_present": 0.0,
        "arch_current_state_findings": 0.0,
        "arch_proposed_solution_architecture": 0.0,
        "arch_data_model": 0.0,
        "arch_processing_flow": 0.0,
        "arch_directory_layout_tooling": 0.0,
        "arch_open_questions_risks": 0.0,
        "notes_present": 0.0,
        "notes_purpose_agenda": 0.0,
        "notes_key_decisions": 0.0,
        "notes_error_log_excerpt": 0.0,
        "notes_action_items_5": 0.0,
        "summary_file_header": 0.0,
        "summary_single_row_2023": 0.0,
        "summary_values_correct_2023": 0.0,
    }

    log_path = workspace / "output" / "logs" / "aggregator_run.txt"
    arch_doc_path = workspace / "output" / "architecture" / "hs_football_stats_architecture.md"
    notes_path = workspace / "output" / "meeting" / "booster_club_notes.md"
    summary_path = workspace / "output" / "prototype" / "season_summary_2023.csv"
    input_2023_path = workspace / "input" / "data" / "games_2023.csv"

    # Aggregator log checks
    log_lines = _load_log_lines(log_path)
    if log_path.exists() and log_lines:
        scores["log_file_present"] = 1.0
        log_text = "\n".join(log_lines)
        has_proc_2023 = "Processing: input/data/games_2023.csv" in log_text
        has_proc_2024 = "Processing: input/data/games_2024_preseason.csv" in log_text
        if has_proc_2023 and has_proc_2024:
            scores["log_contains_processing_lines"] = 1.0
        has_traceback = "Traceback" in log_text
        # Look for KeyError, preferably mentioning Opp_Score
        keyerror_tokens = ["KeyError", "KeyError:"]
        mentions_field = ("'Opp_Score'" in log_text) or ("Opp_Score" in log_text)
        if has_traceback and any(tok in log_text for tok in keyerror_tokens) and mentions_field:
            scores["log_contains_traceback_keyerror"] = 1.0

    # Architecture document checks
    arch_text = _safe_read_text(arch_doc_path) or ""
    if arch_text.strip():
        scores["arch_doc_present"] = 1.0
        sections = _parse_markdown_sections(arch_text)

        # Current State Findings
        cs_lines: List[str] = []
        for k in sections:
            if k.strip().lower().rstrip(':') == "current state findings":
                cs_lines = sections[k]
                break
        if cs_lines:
            bullet_count = _count_bullets(cs_lines)
            cs_text = "\n".join(cs_lines)
            ref_error = _contains_any(cs_text, ["aggregator_run.txt", "keyerror", "traceback"])
            mentions_mismatch = _contains_any(cs_text, ["delimiter", "header", "semicolon", "comma", "oppscore", "opp_score"])
            if bullet_count >= 3 and ref_error and mentions_mismatch:
                scores["arch_current_state_findings"] = 1.0

        # Proposed Solution Architecture
        psa_lines: List[str] = []
        for k in sections:
            if k.strip().lower().rstrip(':') == "proposed solution architecture":
                psa_lines = sections[k]
                break
        if psa_lines:
            psa_text = "\n".join(psa_lines).lower()
            has_ingestion = "ingestion" in psa_text
            has_validation = "validation" in psa_text
            has_standardization = ("standardization" in psa_text) or ("standardise" in psa_text) or ("standardize" in psa_text) or ("normalize" in psa_text)
            has_season_layout = "season" in psa_text or "by season" in psa_text
            has_outputs = ("artifact" in psa_text) or ("outputs" in psa_text) or ("summary" in psa_text)
            if has_ingestion and has_validation and has_standardization and has_season_layout and has_outputs:
                scores["arch_proposed_solution_architecture"] = 1.0

        # Data Model
        dm_lines: List[str] = []
        for k in sections:
            if k.strip().lower().rstrip(':') == "data model":
                dm_lines = sections[k]
                break
        if dm_lines:
            dm_text = "\n".join(dm_lines)
            has_season_field = re.search(r'\bseason\b', dm_text, flags=re.IGNORECASE) is not None
            field_tokens = ["Date", "Opponent", "HomeAway", "OLSM_Score", "Opp_Score", "OppScore", "Result", "PointsFor", "PointsAgainst", "Season"]
            present_fields = sum(1 for tok in field_tokens if re.search(r'\b' + re.escape(tok) + r'\b', dm_text, flags=re.IGNORECASE))
            if has_season_field and present_fields >= 5:
                scores["arch_data_model"] = 1.0

        # Processing Flow
        pf_lines: List[str] = []
        for k in sections:
            if k.strip().lower().rstrip(':') == "processing flow":
                pf_lines = sections[k]
                break
        if pf_lines:
            pf_text = "\n".join(pf_lines).lower()
            has_validation = "validation" in pf_text
            has_error_handling = ("error" in pf_text) or ("errors" in pf_text) or ("exception" in pf_text)
            has_format_drift = ("format" in pf_text) or ("delimiter" in pf_text) or ("header" in pf_text) or ("drift" in pf_text)
            if has_validation and has_error_handling and has_format_drift:
                scores["arch_processing_flow"] = 1.0

        # Directory Layout & Tooling
        dl_lines: List[str] = []
        for k in sections:
            k_norm = k.strip().lower().rstrip(':')
            if k_norm == "directory layout & tooling" or k_norm == "directory layout and tooling":
                dl_lines = sections[k]
                break
        if dl_lines:
            dl_text = "\n".join(dl_lines).lower()
            path_like_count = _extract_path_like_count(dl_text)
            mentions_layers = ("raw" in dl_text) or ("staged" in dl_text) or ("standardized" in dl_text) or ("standardised" in dl_text) or ("summaries" in dl_text)
            if path_like_count >= 3 and mentions_layers:
                scores["arch_directory_layout_tooling"] = 1.0

        # Open Questions & Risks
        oq_lines: List[str] = []
        for k in sections:
            k_norm = k.strip().lower().rstrip(':')
            if k_norm == "open questions & risks" or k_norm == "open questions and risks":
                oq_lines = sections[k]
                break
        if oq_lines:
            if any(line.strip() for line in oq_lines):
                scores["arch_open_questions_risks"] = 1.0

    # Meeting notes checks
    notes_text = _safe_read_text(notes_path) or ""
    if notes_text.strip():
        scores["notes_present"] = 1.0
        lower_notes = notes_text.lower()
        if ("purpose" in lower_notes) or ("agenda" in lower_notes):
            scores["notes_purpose_agenda"] = 1.0
        if ("key decisions" in lower_notes) or ("decisions" in lower_notes):
            scores["notes_key_decisions"] = 1.0
        log_lines_set = set([_normalize_line_for_match(x) for x in log_lines if _normalize_line_for_match(x)])
        notes_lines = [ln for ln in notes_text.splitlines()]
        match_count = 0
        for ln in notes_lines:
            norm_ln = _normalize_line_for_match(ln)
            if norm_ln.startswith("```") or not norm_ln:
                continue
            if len(norm_ln) < 5:
                continue
            if norm_ln in log_lines_set:
                match_count += 1
        if log_lines and match_count >= 3:
            scores["notes_error_log_excerpt"] = 1.0
        action_lines = [ln for ln in notes_lines if ("owner: tbd" in ln.lower() and ("due:" in ln.lower() or "due -" in ln.lower() or "due " in ln.lower()))]
        if len(action_lines) >= 5:
            scores["notes_action_items_5"] = 1.0

    # Prototype summary checks
    expected_header = ["Season", "Games", "Wins", "Losses", "Ties", "PointsFor", "PointsAgainst"]
    summary_rows: List[List[str]] = []
    header_ok = False
    if summary_path.exists():
        try:
            with summary_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header == expected_header:
                    header_ok = True
                for row in reader:
                    if any(cell.strip() for cell in row):
                        summary_rows.append(row)
        except Exception:
            pass
    if header_ok:
        scores["summary_file_header"] = 1.0
    if header_ok and len(summary_rows) == 1:
        row = summary_rows[0]
        if len(row) == len(expected_header) and row[0].strip() == "2023":
            scores["summary_single_row_2023"] = 1.0
    computed = _compute_2023_summary(input_2023_path)
    if header_ok and len(summary_rows) == 1 and computed is not None:
        games, wins, losses, ties, pf, pa = computed
        try:
            row_vals = summary_rows[0]
            ok_vals = (
                row_vals[0].strip() == "2023" and
                int(row_vals[1]) == games and
                int(row_vals[2]) == wins and
                int(row_vals[3]) == losses and
                int(row_vals[4]) == ties and
                int(row_vals[5]) == pf and
                int(row_vals[6]) == pa
            )
            if ok_vals:
                scores["summary_values_correct_2023"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()