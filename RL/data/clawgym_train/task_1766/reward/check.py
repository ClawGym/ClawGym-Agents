import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Any


def _safe_load_json(path: Path) -> Tuple[Any, bool]:
    try:
        if not path.exists():
            return None, False
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False


def _safe_read_text(path: Path) -> Tuple[str, bool]:
    try:
        if not path.exists():
            return "", False
        return path.read_text(encoding="utf-8"), True
    except Exception:
        return "", False


def _run_simulation(workspace: Path) -> Tuple[Dict[str, int], Dict[str, str], bool]:
    """
    Returns:
      - counts_by_code: dict code -> hit_count
      - sim_severity_by_code: dict code -> observed severity (if multiple observed, last one wins)
      - parsed_ok: bool indicates whether we successfully parsed at least one line
    """
    counts: Dict[str, int] = {}
    sim_sev: Dict[str, str] = {}
    parsed_ok = False
    try:
        # Use the current Python executable for determinism
        res = subprocess.run(
            [sys.executable, "tools/simulate_validation_run.py"],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        out = res.stdout.splitlines()
        pat = re.compile(r'^(INFO|WARN|ERROR)\s+([A-Z0-9_]+):\s+(.*)$')
        for line in out:
            m = pat.match(line.strip())
            if not m:
                continue
            parsed_ok = True
            severity, code, _msg = m.groups()
            counts[code] = counts.get(code, 0) + 1
            sim_sev[code] = severity
    except Exception:
        parsed_ok = False
    return counts, sim_sev, parsed_ok


def _parse_raw_messages(workspace: Path) -> Tuple[Dict[str, Dict[str, str]], bool]:
    """
    Returns mapping: code -> {'severity': str, 'text': str}
    """
    raw_path = workspace / "input" / "raw_messages.json"
    data, ok = _safe_load_json(raw_path)
    if not ok or not isinstance(data, dict) or "messages" not in data or not isinstance(data["messages"], list):
        return {}, False
    mapping: Dict[str, Dict[str, str]] = {}
    try:
        for item in data["messages"]:
            if not isinstance(item, dict):
                return {}, False
            code = item.get("code")
            sev = item.get("severity")
            txt = item.get("text")
            if not isinstance(code, str) or not isinstance(sev, str) or not isinstance(txt, str):
                return {}, False
            mapping[code] = {"severity": sev, "text": txt}
    except Exception:
        return {}, False
    return mapping, True


def _load_message_rewrites(workspace: Path) -> Tuple[List[dict], bool]:
    out_path = workspace / "out" / "message_rewrites.json"
    data, ok = _safe_load_json(out_path)
    if not ok or not isinstance(data, list):
        return [], False
    # ensure all items are dicts
    for it in data:
        if not isinstance(it, dict):
            return [], False
    return data, True


def _load_frequency_csv(workspace: Path) -> Tuple[List[Dict[str, str]], bool, bool]:
    """
    Returns: (rows as list of dicts, file_exists, schema_ok)
    """
    csv_path = workspace / "out" / "frequency_summary.csv"
    if not csv_path.exists():
        return [], False, False
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            schema_ok = reader.fieldnames == ["code", "severity", "hit_count"]
        return rows, True, bool(schema_ok)
    except Exception:
        return [], True, False


def _compute_fraction(numer: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    val = numer / denom
    if val < 0.0:
        return 0.0
    if val > 1.0:
        return 1.0
    return float(val)


def _count_sentences(text: str) -> int:
    # Simple heuristic: split on ., !, ? and count non-empty segments
    parts = re.split(r'[.!?]+', text)
    cnt = sum(1 for p in parts if p.strip() != "")
    return cnt


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "simulation_run_parsed": 0.0,
        "rewrites_file_parsable": 0.0,
        "rewrites_cover_all_codes_exactly_once": 0.0,
        "rewrites_fields_valid": 0.0,
        "rewrites_severity_original_match_raw": 0.0,
        "rewrites_hit_count_and_appears_match": 0.0,
        "rewritten_text_length_compliance": 0.0,
        "rewritten_text_no_exclamation": 0.0,
        "rationale_sentence_count_valid": 0.0,
        "frequency_csv_parsable": 0.0,
        "frequency_csv_covers_all_codes": 0.0,
        "frequency_csv_values_match": 0.0,
        "rewrite_notes_present": 0.0,
        "rewrite_notes_top_three_covered": 0.0,
        "rewrite_notes_discrepancies_handled": 0.0,
        "rewrite_notes_final_line_count_correct": 0.0,
    }

    raw_map, raw_ok = _parse_raw_messages(workspace)
    sim_counts, sim_sev_by_code, sim_parsed = _run_simulation(workspace)
    scores["simulation_run_parsed"] = 1.0 if sim_parsed else 0.0

    # Load outputs
    rewrites, rewrites_ok = _load_message_rewrites(workspace)
    scores["rewrites_file_parsable"] = 1.0 if rewrites_ok else 0.0

    # Early exit computations set to 0 when inputs missing; continue to fill with zeros otherwise
    raw_codes = list(raw_map.keys()) if raw_ok else []
    raw_code_set = set(raw_codes)

    # Validate rewrites coverage
    if raw_ok and rewrites_ok:
        codes_in_rewrites = [it.get("code") for it in rewrites if isinstance(it, dict)]
        # Check duplicates and unknowns
        unique_codes = set(codes_in_rewrites)
        all_present_once = (
            len(rewrites) == len(raw_code_set)
            and len(unique_codes) == len(raw_code_set)
            and unique_codes == raw_code_set
        )
        scores["rewrites_cover_all_codes_exactly_once"] = 1.0 if all_present_once else 0.0

        # Fields validity
        required_fields = {
            "code": str,
            "severity": str,
            "original_text": str,
            "rewritten_text": str,
            "rationale": str,
            "hit_count": int,
            "appears_in_simulation": bool,
        }
        valid_count = 0
        for it in rewrites:
            ok_fields = True
            for k, typ in required_fields.items():
                if k not in it:
                    ok_fields = False
                    break
                val = it[k]
                # For int/bool types, allow exact types only
                if typ is int:
                    if not isinstance(val, int):
                        ok_fields = False
                        break
                elif typ is bool:
                    if not isinstance(val, bool):
                        ok_fields = False
                        break
                else:
                    if not isinstance(val, typ):
                        ok_fields = False
                        break
            if ok_fields:
                valid_count += 1
        scores["rewrites_fields_valid"] = _compute_fraction(valid_count, len(rewrites))

        # Severity and original_text match raw
        match_count = 0
        for it in rewrites:
            code = it.get("code")
            if code in raw_map:
                sev_ok = it.get("severity") == raw_map[code]["severity"]
                txt_ok = it.get("original_text") == raw_map[code]["text"]
                if sev_ok and txt_ok:
                    match_count += 1
        scores["rewrites_severity_original_match_raw"] = _compute_fraction(match_count, len(raw_code_set))

        # Hit count and appears match simulation
        hit_ok_count = 0
        for it in rewrites:
            code = it.get("code")
            expected_hit = sim_counts.get(code, 0)
            expected_appears = expected_hit > 0
            if isinstance(it.get("hit_count"), int) and it.get("hit_count") == expected_hit and it.get("appears_in_simulation") == expected_appears:
                hit_ok_count += 1
        scores["rewrites_hit_count_and_appears_match"] = _compute_fraction(hit_ok_count, len(raw_code_set))

        # Rewritten text length <= 120
        len_ok = 0
        no_exclaim_ok = 0
        for it in rewrites:
            rt = it.get("rewritten_text")
            if isinstance(rt, str):
                if len(rt) <= 120:
                    len_ok += 1
                if "!" not in rt:
                    no_exclaim_ok += 1
        scores["rewritten_text_length_compliance"] = _compute_fraction(len_ok, len(rewrites))
        scores["rewritten_text_no_exclamation"] = _compute_fraction(no_exclaim_ok, len(rewrites))

        # Rationale sentence count 1-2
        rat_ok = 0
        for it in rewrites:
            r = it.get("rationale")
            if isinstance(r, str):
                sc = _count_sentences(r)
                if 1 <= sc <= 2:
                    rat_ok += 1
        scores["rationale_sentence_count_valid"] = _compute_fraction(rat_ok, len(rewrites))

    # Frequency CSV validations
    freq_rows, freq_exists, freq_schema_ok = _load_frequency_csv(workspace)
    scores["frequency_csv_parsable"] = 1.0 if (freq_exists and freq_schema_ok) else 0.0

    if raw_ok and freq_exists and freq_schema_ok:
        codes_in_csv = [row.get("code") for row in freq_rows]
        csv_unique = set(codes_in_csv)
        coverage_ok = (
            len(freq_rows) == len(raw_code_set)
            and len(csv_unique) == len(raw_code_set)
            and csv_unique == raw_code_set
        )
        scores["frequency_csv_covers_all_codes"] = 1.0 if coverage_ok else 0.0

        # Validate each row values: severity matches raw, hit_count matches sim
        val_ok = 0
        for row in freq_rows:
            code = row.get("code")
            sev = row.get("severity")
            try:
                hc = int(row.get("hit_count")) if row.get("hit_count") is not None else None
            except Exception:
                hc = None
            sev_ok = (code in raw_map and sev == raw_map.get(code, {}).get("severity"))
            hc_ok = (hc is not None and hc == sim_counts.get(code, 0))
            if sev_ok and hc_ok:
                val_ok += 1
        denom = len(freq_rows) if freq_rows else len(raw_code_set)
        scores["frequency_csv_values_match"] = _compute_fraction(val_ok, denom)

    # rewrite_notes.md checks
    notes_path = workspace / "out" / "rewrite_notes.md"
    notes_text, notes_ok = _safe_read_text(notes_path)
    scores["rewrite_notes_present"] = 1.0 if notes_ok else 0.0

    # Top three codes by hit_count
    if raw_ok:
        # build counts for all raw codes (0 if absent)
        all_counts = {code: sim_counts.get(code, 0) for code in raw_code_set}
        # deterministic tie-breaker: by hit_count desc, then code asc
        top_sorted = sorted(all_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        top_three_codes = [c for c, _ in top_sorted[:3]]
    else:
        top_three_codes = []

    if notes_ok and top_three_codes:
        covered = 0
        for c in top_three_codes:
            if c in notes_text:
                covered += 1
        scores["rewrite_notes_top_three_covered"] = _compute_fraction(covered, len(top_three_codes))
    else:
        scores["rewrite_notes_top_three_covered"] = 0.0

    # Discrepancies handling: severity mismatch between sim and raw
    if raw_ok:
        mismatched_codes = []
        for code in raw_code_set:
            sim_sev = sim_sev_by_code.get(code)
            if sim_sev is not None and sim_sev != raw_map[code]["severity"]:
                mismatched_codes.append(code)
        if len(mismatched_codes) == 0:
            # No discrepancies to report
            scores["rewrite_notes_discrepancies_handled"] = 1.0 if notes_ok else 0.0
        else:
            if notes_ok:
                # Check all mismatched codes are mentioned
                mentioned = sum(1 for c in mismatched_codes if c in notes_text)
                scores["rewrite_notes_discrepancies_handled"] = _compute_fraction(mentioned, len(mismatched_codes))
            else:
                scores["rewrite_notes_discrepancies_handled"] = 0.0
    else:
        scores["rewrite_notes_discrepancies_handled"] = 0.0

    # Final line count correctness
    if notes_ok and rewrites_ok:
        # Count rewritten_text exceeding 120 chars
        exceed_count = 0
        for it in rewrites:
            rt = it.get("rewritten_text")
            if isinstance(rt, str) and len(rt) > 120:
                exceed_count += 1
        # Last non-empty line
        lines = [ln.rstrip("\n\r") for ln in notes_text.splitlines()]
        last_non_empty = ""
        for ln in reversed(lines):
            if ln.strip() != "":
                last_non_empty = ln.strip()
                break
        if last_non_empty:
            # Check that the line contains the number and references 120
            has_number = str(exceed_count) in last_non_empty
            mentions_120 = "120" in last_non_empty
            scores["rewrite_notes_final_line_count_correct"] = 1.0 if (has_number and mentions_120) else 0.0
        else:
            scores["rewrite_notes_final_line_count_correct"] = 0.0
    else:
        scores["rewrite_notes_final_line_count_correct"] = 0.0

    return scores


def main() -> None:
        workspace_path = "."
        if len(sys.argv) >= 2 and sys.argv[1]:
            workspace_path = sys.argv[1]
        result = grade([], workspace_path)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()