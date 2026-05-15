import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_csv_dicts(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    try:
        if not path.exists() or not path.is_file():
            return False, []
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return True, rows
    except Exception:
        return False, []


def _safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        if not path.exists() or not path.is_file():
            return False, ""
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def _safe_read_jsonl(path: Path) -> Tuple[bool, List[Dict]]:
    try:
        if not path.exists() or not path.is_file():
            return False, []
        items = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return True, items
    except Exception:
        return False, []


def _to_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _round_half_to_even(n: float, ndigits: int = 0) -> float:
    # Python's round is bankers rounding; use it for determinism
    return round(n, ndigits)


def _compute_expected_at_risk_by_state(workforce_rows: List[Dict[str, str]],
                                       pilot_rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], Dict[str, float], Dict[str, float], Dict[str, int]]:
    # Build index
    wf_by_depot = {r["depot_id"]: r for r in workforce_rows if "depot_id" in r}
    # pilot filter
    pilot_by_depot = {r["depot_id"]: r for r in pilot_rows if "depot_id" in r}
    allowed_stages = {"testing", "deployed"}
    pilot_depots = []
    for depot_id, p in pilot_by_depot.items():
        stage = (p.get("automation_stage") or "").strip().lower()
        if stage in allowed_stages and depot_id in wf_by_depot:
            pilot_depots.append(depot_id)

    # Aggregate across all depots in each state for denominators
    total_drivers_by_state_all = {}
    for r in workforce_rows:
        state = r.get("state")
        td = _to_int(r.get("total_drivers", ""))
        if state is None or td is None:
            continue
        total_drivers_by_state_all[state] = total_drivers_by_state_all.get(state, 0) + td

    # Per-state aggregates for pilot depots
    agg = {}
    for depot_id in pilot_depots:
        wf = wf_by_depot[depot_id]
        p = pilot_by_depot[depot_id]
        state = wf.get("state")
        if not state:
            continue
        td = _to_int(wf.get("total_drivers", ""))
        um = _to_int(wf.get("union_members_drivers", ""))
        low_pct = _to_float(p.get("expected_displacement_low_pct", ""))
        high_pct = _to_float(p.get("expected_displacement_high_pct", ""))
        if None in (td, um, low_pct, high_pct):
            continue
        d = agg.setdefault(state, {
            "depots_with_pilot": 0,
            "total_drivers_in_pilot_depots": 0,
            "sum_union_members": 0,
            "sum_at_risk_low_raw": 0.0,
            "sum_at_risk_high_raw": 0.0,
        })
        d["depots_with_pilot"] += 1
        d["total_drivers_in_pilot_depots"] += td
        d["sum_union_members"] += um
        d["sum_at_risk_low_raw"] += td * low_pct
        d["sum_at_risk_high_raw"] += td * high_pct

    # Compose rows
    rows = []
    for state in sorted(agg.keys()):
        d = agg[state]
        depots_with_pilot = d["depots_with_pilot"]
        total_drivers_in_pilot = d["total_drivers_in_pilot_depots"]
        est_low = int(_round_half_to_even(d["sum_at_risk_low_raw"], 0))
        est_high = int(_round_half_to_even(d["sum_at_risk_high_raw"], 0))
        union_pct = _round_half_to_even(100.0 * (d["sum_union_members"] / total_drivers_in_pilot) if total_drivers_in_pilot else 0.0, 1)
        denom_all = total_drivers_by_state_all.get(state, 0)
        share_pct = _round_half_to_even(100.0 * (total_drivers_in_pilot / denom_all) if denom_all else 0.0, 1)

        row = {
            "state": state,
            "depots_with_pilot": str(depots_with_pilot),
            "total_drivers_in_pilot_depots": str(total_drivers_in_pilot),
            "est_at_risk_low": str(est_low),
            "est_at_risk_high": str(est_high),
            "union_coverage_in_pilot_pct": f"{union_pct:.1f}",
            "share_of_state_drivers_in_pilot_pct": f"{share_pct:.1f}",
        }
        rows.append(row)

    # Overall totals for Key Stats
    overall_counts = {"pilot_depots": 0, "total_drivers_in_pilot": 0}
    overall_low_raw = 0.0
    overall_high_raw = 0.0
    for depot_id in pilot_depots:
        wf = wf_by_depot[depot_id]
        p = pilot_by_depot[depot_id]
        td = _to_int(wf.get("total_drivers", ""))
        low_pct = _to_float(p.get("expected_displacement_low_pct", ""))
        high_pct = _to_float(p.get("expected_displacement_high_pct", ""))
        if None in (td, low_pct, high_pct):
            continue
        overall_counts["pilot_depots"] += 1
        overall_counts["total_drivers_in_pilot"] += td
        overall_low_raw += td * low_pct
        overall_high_raw += td * high_pct
    overall_low = int(_round_half_to_even(overall_low_raw, 0))
    overall_high = int(_round_half_to_even(overall_high_raw, 0))

    # Planning counts by state
    planning_counts = {}
    for depot_id, p in pilot_by_depot.items():
        stage = (p.get("automation_stage") or "").strip().lower()
        if stage != "planning":
            continue
        wf = wf_by_depot.get(depot_id)
        if not wf:
            continue
        state = wf.get("state")
        if not state:
            continue
        planning_counts[state] = planning_counts.get(state, 0) + 1

    expected_totals = {
        "pilot_depots": float(overall_counts["pilot_depots"]),
        "total_drivers_in_pilot": float(overall_counts["total_drivers_in_pilot"]),
        "est_at_risk_low": float(overall_low),
        "est_at_risk_high": float(overall_high),
    }

    # Also build expected shares by state for later checks
    expected_shares = {}
    for r in rows:
        expected_shares[r["state"]] = _to_float(r["share_of_state_drivers_in_pilot_pct"]) or 0.0

    return rows, expected_totals, expected_shares, planning_counts


def _compare_csv_rows(expected: List[Dict[str, str]], actual: List[Dict[str, str]], columns: List[str]) -> bool:
    if len(expected) != len(actual):
        return False
    for e_row, a_row in zip(expected, actual):
        for col in columns:
            if col not in a_row:
                return False
            # Compare numerics as numbers where appropriate
            ev = e_row[col]
            av = a_row[col]
            # Decide numeric or str by column
            if col in ("state",):
                if ev != av:
                    return False
            elif col in ("depots_with_pilot", "total_drivers_in_pilot_depots", "est_at_risk_low", "est_at_risk_high"):
                try:
                    if int(ev) != int(float(av)):
                        return False
                except Exception:
                    return False
            elif col in ("union_coverage_in_pilot_pct", "share_of_state_drivers_in_pilot_pct"):
                try:
                    if round(float(ev), 1) != round(float(av), 1):
                        return False
                except Exception:
                    return False
            else:
                if ev != av:
                    return False
    return True


def _extract_section(text: str, section_name: str) -> str:
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        l = line.strip().lower().rstrip(":")
        if l == section_name.lower():
            start_idx = i + 1
            break
        # Accept headings like "## Key Stats:" etc.
        if l.endswith(section_name.lower()):
            start_idx = i + 1
            break
    if start_idx is None:
        # try to find line that starts with section name
        for i, line in enumerate(lines):
            if line.strip().lower().startswith(section_name.lower()):
                start_idx = i + 1
                break
    if start_idx is None:
        return ""
    # Section ends at next blank line followed by a non-bullet or next section title
    content_lines = []
    for j in range(start_idx, len(lines)):
        if lines[j].strip() == "" and (j + 1 < len(lines) and lines[j + 1].strip() != "" and not lines[j + 1].lstrip().startswith(("-", "*", "•"))):
            break
        content_lines.append(lines[j])
    return "\n".join(content_lines).strip()


def _find_numbers(text: str) -> List[str]:
    # Extract integers and floats numbers as strings
    return re.findall(r"\d+(?:\.\d+)?", text)


def _line_has_numbers(line: str, numbers: List[str]) -> bool:
    # Check if line contains any of the number strings as standalone or part of percent (e.g., 65.4%)
    for n in numbers:
        if n in line:
            return True
    return False


def _tokenize_words(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z]+", text.lower())


def _remove_stopwords(tokens: List[str]) -> List[str]:
    stopwords = {
        "we", "us", "our", "ours", "they", "them", "their", "theirs", "you", "your", "yours", "i", "me", "my", "mine",
        "a", "an", "the", "and", "or", "but", "if", "then", "else", "for", "of", "on", "in", "to", "from", "by", "with",
        "as", "at", "it", "its", "is", "are", "was", "were", "be", "been", "being",
        "this", "that", "these", "those", "so", "because", "since", "also", "too", "very", "more", "most", "less", "than",
        "not", "no", "do", "does", "did", "can", "could", "would", "should", "may", "might", "will", "just", "already",
        "about", "into", "over", "under", "up", "down", "out", "what", "which", "who", "whom", "when", "where", "how",
        "has", "have", "had", "such", "been", "any", "all", "each", "per", "week", "month", "year", "time", "hours",
        "new", "last", "first"
    }
    return [t for t in tokens if t not in stopwords and len(t) > 1]


def _top_keywords_from_comments(comments: List[Dict]) -> List[str]:
    tokens = []
    for obj in comments:
        txt = (obj.get("comment_text") or "").lower()
        toks = _remove_stopwords(_tokenize_words(txt))
        tokens.extend(toks)
    freq = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    # sort by frequency desc then alphabetically
    sorted_tokens = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [t for t, _ in sorted_tokens[:5]]  # take top 5 to allow some flexibility


def _count_bullets(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if line.strip().startswith(("-", "*", "•")):
            count += 1
    return count


def _contains_exact_phrase(text: str, phrase: str) -> bool:
    return phrase.lower() in text.lower()


def _sentence_with_both_numbers(text: str, low: int, high: int) -> bool:
    # Split into sentences by ., !, ?
    sentences = re.split(r"(?<=[\.\!\?])\s+", text.strip())
    for s in sentences:
        if re.search(rf"\b{low}\b", s) and re.search(rf"\b{high}\b", s):
            return True
    return False


def _non_accusatory(text: str) -> bool:
    # Avoid strongly accusatory phrases from the draft
    banned_phrases = [
        "fed up",
        "you are failing",
        "failing the workforce",
        "shoved aside",
        "rip jobs",
        "we demand a slowdown",
        "demand a slowdown",
        "we will amplify",
        "slam on the brakes at random",
    ]
    lower = text.lower()
    for bp in banned_phrases:
        if bp in lower:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "at_risk_by_state_exists": 0.0,
        "at_risk_by_state_columns_and_order": 0.0,
        "at_risk_by_state_row_count": 0.0,
        "at_risk_by_state_values_correct": 0.0,
        "at_risk_by_state_sorted_by_state": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_key_stats_present": 0.0,
        "meeting_notes_member_concerns_top3": 0.0,
        "meeting_notes_action_items_min_count_and_numbers": 0.0,
        "meeting_notes_data_checks_anomalies_and_planning_by_state": 0.0,
        "meeting_notes_assumptions_present_near_bottom": 0.0,
        "statement_rewritten_exists": 0.0,
        "statement_rewritten_length_ok": 0.0,
        "statement_rewritten_references_range": 0.0,
        "statement_rewritten_tone_nonaccusatory": 0.0,
    }

    input_dir = workspace / "input"
    output_dir = workspace / "output"

    # Load input files
    ok_wf, wf_rows = _safe_read_csv_dicts(input_dir / "workforce_by_depot.csv")
    ok_pilot, pilot_rows = _safe_read_csv_dicts(input_dir / "automation_pilot.csv")
    ok_comments, comments = _safe_read_jsonl(input_dir / "member_comments.jsonl")

    # Precompute expected values if inputs present
    expected_rows = []
    expected_totals = {}
    expected_shares = {}
    planning_counts = {}
    if ok_wf and ok_pilot:
        expected_rows, expected_totals, expected_shares, planning_counts = _compute_expected_at_risk_by_state(wf_rows, pilot_rows)

    # 1) Validate output/at_risk_by_state.csv
    at_risk_path = output_dir / "at_risk_by_state.csv"
    ok_csv, out_rows = _safe_read_csv_dicts(at_risk_path)
    if ok_csv:
        scores["at_risk_by_state_exists"] = 1.0
        # Check columns and order
        expected_cols = [
            "state",
            "depots_with_pilot",
            "total_drivers_in_pilot_depots",
            "est_at_risk_low",
            "est_at_risk_high",
            "union_coverage_in_pilot_pct",
            "share_of_state_drivers_in_pilot_pct",
        ]
        try:
            with at_risk_path.open(newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
            if header == expected_cols:
                scores["at_risk_by_state_columns_and_order"] = 1.0
        except Exception:
            pass

        # Row count and sorted
        if ok_wf and ok_pilot:
            if len(out_rows) == len(expected_rows):
                scores["at_risk_by_state_row_count"] = 1.0
            # Check sorted by state
            actual_states = [r.get("state", "") for r in out_rows]
            if actual_states == sorted(actual_states):
                scores["at_risk_by_state_sorted_by_state"] = 1.0
            # Compare values strictly
            if _compare_csv_rows(expected_rows, out_rows, expected_cols):
                scores["at_risk_by_state_values_correct"] = 1.0

    # 2) Validate output/meeting_notes.md
    notes_path = output_dir / "meeting_notes.md"
    ok_md, notes_text = _safe_read_text(notes_path)
    if ok_md and notes_text.strip():
        scores["meeting_notes_exists"] = 1.0

        # Key Stats section
        key_stats = _extract_section(notes_text, "Key Stats")
        ks_ok = False
        if key_stats and expected_totals:
            # Need number of pilot depots, total drivers in pilot depots, estimated at-risk range low–high
            needed_numbers = [
                str(int(expected_totals.get("pilot_depots", 0))),
                str(int(expected_totals.get("total_drivers_in_pilot", 0))),
                str(int(expected_totals.get("est_at_risk_low", 0))),
                str(int(expected_totals.get("est_at_risk_high", 0))),
            ]
            present = [_line_has_numbers(key_stats, [n]) for n in needed_numbers]
            if all(present):
                ks_ok = True
        scores["meeting_notes_key_stats_present"] = 1.0 if ks_ok else 0.0

        # Member Concerns section: top 3 recurring keywords with example phrase or quote
        mc = _extract_section(notes_text, "Member Concerns")
        mc_ok = False
        if mc and ok_comments:
            top_kw = _top_keywords_from_comments(comments)  # top 5; accept any 3 appearing in bullets
            # consider bullet lines in this section
            bullet_lines = [ln for ln in mc.splitlines() if ln.strip().startswith(("-", "*", "•"))]
            matched_count = 0
            for ln in bullet_lines:
                # Check contains keyword from top_kw
                if any(re.search(rf"\b{re.escape(k)}\b", ln.lower()) for k in top_kw):
                    # Check has a short example phrase or quote (presence of quotes " or ')
                    if '"' in ln or "'" in ln:
                        matched_count += 1
            if matched_count >= 3:
                mc_ok = True
        scores["meeting_notes_member_concerns_top3"] = 1.0 if mc_ok else 0.0

        # Action Items section: at least 5 bullet points, at least two items reference computed numbers
        ai = _extract_section(notes_text, "Action Items")
        ai_ok = False
        if ai and expected_totals:
            bullets = [ln for ln in ai.splitlines() if ln.strip().startswith(("-", "*", "•"))]
            if len(bullets) >= 5:
                # Build list of acceptable numbers: overall totals and shares by state
                nums = [
                    str(int(expected_totals.get("pilot_depots", 0))),
                    str(int(expected_totals.get("total_drivers_in_pilot", 0))),
                    str(int(expected_totals.get("est_at_risk_low", 0))),
                    str(int(expected_totals.get("est_at_risk_high", 0))),
                ]
                # shares
                for v in expected_shares.values():
                    nums.append(f"{round(v, 1):.1f}")
                ref_count = 0
                for b in bullets:
                    if _line_has_numbers(b, nums):
                        ref_count += 1
                if ref_count >= 2:
                    ai_ok = True
        scores["meeting_notes_action_items_min_count_and_numbers"] = 1.0 if ai_ok else 0.0

        # Data Checks: anomalies message and planning counts by state in a single sentence
        dc = _extract_section(notes_text, "Data Checks")
        dc_ok = False
        if dc and ok_wf and ok_pilot:
            anomalies_expected_none = True
            # check phrase "No data anomalies found."
            has_phrase = _contains_exact_phrase(dc, "No data anomalies found.")
            # build planning sentence check: single line containing all states and counts
            # Determine all states from workforce
            states = sorted(set([r.get("state") for r in wf_rows if r.get("state")]))
            # For any state not in planning_counts, count is 0
            for st in states:
                if st not in planning_counts:
                    planning_counts[st] = 0
            one_line_ok = False
            lines = [ln.strip() for ln in dc.splitlines() if ln.strip()]
            for ln in lines:
                if "planning" in ln.lower():
                    ok_all = True
                    for st in states:
                        cnt = planning_counts.get(st, 0)
                        # Need state code and count nearby, in any order in the line
                        pattern = re.compile(rf"\b{re.escape(st)}\b.*\b{cnt}\b|\b{cnt}\b.*\b{re.escape(st)}\b")
                        if not pattern.search(ln):
                            ok_all = False
                            break
                    if ok_all:
                        one_line_ok = True
                        break
            if anomalies_expected_none and has_phrase and one_line_ok:
                dc_ok = True
        scores["meeting_notes_data_checks_anomalies_and_planning_by_state"] = 1.0 if dc_ok else 0.0

        # Assumptions at bottom
        bottom_lines = [ln for ln in notes_text.splitlines() if ln.strip()]
        assumptions_ok = False
        if bottom_lines:
            tail = "\n".join(bottom_lines[-10:]).lower()
            if "assumption" in tail:
                assumptions_ok = True
        scores["meeting_notes_assumptions_present_near_bottom"] = 1.0 if assumptions_ok else 0.0

    # 3) Validate output/statement_rewritten.txt
    stmt_path = output_dir / "statement_rewritten.txt"
    ok_stmt, stmt_text = _safe_read_text(stmt_path)
    if ok_stmt and stmt_text.strip():
        scores["statement_rewritten_exists"] = 1.0
        # length 150–220 words
        words = re.findall(r"[A-Za-z0-9']+", stmt_text)
        if 150 <= len(words) <= 220:
            scores["statement_rewritten_length_ok"] = 1.0
        # includes a sentence that references overall estimated at‑risk range (low–high)
        if expected_totals:
            low = int(expected_totals.get("est_at_risk_low", 0))
            high = int(expected_totals.get("est_at_risk_high", 0))
            if _sentence_with_both_numbers(stmt_text, low, high):
                scores["statement_rewritten_references_range"] = 1.0
        # tone: non-accusatory
        if _non_accusatory(stmt_text):
            scores["statement_rewritten_tone_nonaccusatory"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()