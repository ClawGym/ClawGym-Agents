import csv
import json
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _read_promises(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _safe_read_csv(path)
    if rows is None:
        return None
    # Validate minimal required columns
    required_cols = ["party", "year", "state", "topic", "pledge_text"]
    if not rows:
        # Could be empty file; still return empty list if columns exist
        # But we cannot confirm columns via DictReader if empty; we re-open to get fieldnames
        try:
            with path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header is None or any(col not in header for col in required_cols):
                    return None
        except Exception:
            return None
        return []
    # Ensure columns present
    if any(c not in rows[0] for c in required_cols):
        return None
    return rows


def _compute_aggregates(promises: List[Dict[str, str]]) -> Tuple[List[Dict[str, Any]], Dict[str, int], Dict[str, int], int]:
    party_topic_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    party_totals: Dict[str, int] = defaultdict(int)
    topic_totals: Dict[str, int] = defaultdict(int)
    for r in promises:
        party = r["party"]
        topic = r["topic"]
        party_topic_counts[(party, topic)] += 1
        party_totals[party] += 1
        topic_totals[topic] += 1
    overall_total = sum(party_totals.values())
    # Build aggregates list
    aggregates: List[Dict[str, Any]] = []
    for (party, topic), cnt in party_topic_counts.items():
        total_for_party = party_totals.get(party, 0)
        share = 0.0
        if total_for_party > 0:
            share = round((cnt * 100.0) / total_for_party, 1)
        aggregates.append({
            "party": party,
            "topic": topic,
            "pledge_count": cnt,
            "share_of_party_pledges": share,
        })
    # Sort for determinism (not required for grading equality but helps)
    aggregates.sort(key=lambda d: (d["party"], d["topic"]))
    return aggregates, dict(party_totals), dict(topic_totals), overall_total


def _safe_read_results_aggregates(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, None
            rows_raw = list(reader)
    except Exception:
        return None, None
    # Convert to structured dict rows while keeping original string for share to validate formatting
    header_expected = ["party", "topic", "pledge_count", "share_of_party_pledges"]
    rows: List[Dict[str, Any]] = []
    for row in rows_raw:
        if len(row) != len(header):
            return None, header  # malformed row
        row_map = {header[i]: row[i] for i in range(len(header))}
        # Attempt type coercion
        try:
            pledge_count = int(row_map.get("pledge_count", ""))
            share_str = row_map.get("share_of_party_pledges", "")
            # Normalize share parsing
            share_val = float(share_str)
        except Exception:
            return None, header
        rows.append({
            "party": row_map.get("party", ""),
            "topic": row_map.get("topic", ""),
            "pledge_count": pledge_count,
            "share_str": row_map.get("share_of_party_pledges", ""),
            "share_val": share_val,
        })
    return rows, header


def _numbers_from_aggregates(aggregates: List[Dict[str, Any]],
                             party_totals: Dict[str, int],
                             topic_totals: Dict[str, int],
                             overall_total: int) -> Dict[str, Any]:
    # Return useful sets for downstream text checks
    count_numbers = set(str(r["pledge_count"]) for r in aggregates)
    share_numbers = set(f"{r['share_of_party_pledges']:.1f}" for r in aggregates)
    share_numbers_with_pct = set(f"{r['share_of_party_pledges']:.1f}%" for r in aggregates)
    party_total_numbers = set(str(v) for v in party_totals.values())
    topic_total_numbers = set(str(v) for v in topic_totals.values())
    overall_total_number = str(overall_total)
    return {
        "count_numbers": count_numbers,
        "share_numbers": share_numbers,
        "share_numbers_with_pct": share_numbers_with_pct,
        "party_total_numbers": party_total_numbers,
        "topic_total_numbers": topic_total_numbers,
        "overall_total_number": overall_total_number,
    }


def _extract_numbers(text: str) -> List[str]:
    # Extract number tokens like 12, 12.3, optionally attached with % will be captured separately by stripping
    matches = re.findall(r"\d+(?:\.\d+)?%?", text)
    return matches


def _normalize_number_token(tok: str) -> str:
    return tok.strip()


def _line_is_bullet(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("- ") or stripped.startswith("* ")


def _contains_phrase_method(text: str) -> bool:
    t = text.lower()
    return ("each row" in t) and ("pledge" in t) and ("counted once" in t)


def _find_party_total_mentioned(text: str, party: str, total: int) -> bool:
    # Check if party name appears within 60 chars of the total number token
    t = text
    total_str = str(total)
    positions = [m.start() for m in re.finditer(re.escape(party), t)]
    for pos in positions:
        start = max(0, pos - 60)
        end = min(len(t), pos + 60)
        window = t[start:end]
        # number token matching with boundaries
        for m in re.finditer(r"\b" + re.escape(total_str) + r"\b", window):
            return True
    return False


def _top_three_topics_per_party(aggregates: List[Dict[str, Any]]) -> Dict[str, List[Tuple[str, int, float]]]:
    # Build mapping from party to list of (topic, count, share) top-3 with ties broken alphabetically by topic
    party_to_topics: Dict[str, List[Tuple[str, int, float]]] = defaultdict(list)
    for r in aggregates:
        party_to_topics[r["party"]].append((r["topic"], int(r["pledge_count"]), float(r["share_of_party_pledges"])))
    result: Dict[str, List[Tuple[str, int, float]]] = {}
    for party, items in party_to_topics.items():
        items_sorted = sorted(items, key=lambda x: (-x[1], x[0].lower()))
        top3 = items_sorted[:3]
        result[party] = top3
    return result


def _validate_bulleted_top_three(report_text: str, expected_top3: Dict[str, List[Tuple[str, int, float]]]) -> bool:
    # For each party, for each expected entry, find a bullet line containing party, topic, count, and share
    lines = report_text.splitlines()
    bullet_lines = [ln for ln in lines if _line_is_bullet(ln)]
    # Normalize bullet lines for case-insensitive search but maintain original for numbers and percent
    ok = True
    for party, topics in expected_top3.items():
        for topic, count, share in topics:
            found = False
            share_patterns = [f"{share:.1f}%", f"{share:.1f} percent"]
            count_pattern = str(count)
            for ln in bullet_lines:
                lower_ln = ln.lower()
                if party.lower() in lower_ln and topic.lower() in lower_ln:
                    # check count as a whole number token in this line
                    if not re.search(r"\b" + re.escape(count_pattern) + r"\b", ln):
                        continue
                    # check share exists in line
                    if any(pat in lower_ln for pat in [sp.lower() for sp in share_patterns]):
                        found = True
                        break
            if not found:
                ok = False
                break
        if not ok:
            break
    return ok


def _check_neutral_tone(text: str) -> bool:
    banned = [
        "stuffed",
        "chest thumping",
        "lopsided spectacle",
        "hype",
        "tiresome",
    ]
    t = text.lower()
    return not any(b in t for b in banned)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "aggregates_file_exists": 0.0,
        "aggregates_structure": 0.0,
        "aggregates_values_correct": 0.0,
        "overall_summary_exists": 0.0,
        "overall_summary_structure": 0.0,
        "overall_summary_correct": 0.0,
        "overall_summary_reconciles_with_aggregates": 0.0,
        "report_exists": 0.0,
        "report_word_count": 0.0,
        "report_method_statement": 0.0,
        "report_party_totals_mentioned": 0.0,
        "report_bulleted_top_three_per_party": 0.0,
        "report_neutral_tone": 0.0,
        "department_update_exists": 0.0,
        "department_update_word_count": 0.0,
        "department_update_numbers_from_aggregates": 0.0,
        "department_update_neutral_tone": 0.0,
        "department_update_email_format": 0.0,
        "executive_summary_exists": 0.0,
        "executive_summary_word_count": 0.0,
        "executive_summary_numbers_from_aggregates": 0.0,
        "executive_summary_next_steps": 0.0,
        "executive_summary_neutral_tone": 0.0,
    }

    # Load inputs
    promises_path = workspace / "input" / "promises.csv"
    notes_path = workspace / "input" / "notes.md"
    promises = _read_promises(promises_path)
    notes_text = _safe_read_text(notes_path) or ""

    # Compute expected aggregates from promises if available
    expected_aggregates: List[Dict[str, Any]] = []
    expected_party_totals: Dict[str, int] = {}
    expected_topic_totals: Dict[str, int] = {}
    expected_overall_total: int = 0
    if promises is not None:
        expected_aggregates, expected_party_totals, expected_topic_totals, expected_overall_total = _compute_aggregates(promises)

    # Check aggregates CSV
    agg_path = workspace / "results" / "aggregates_by_party_topic.csv"
    if agg_path.exists():
        scores["aggregates_file_exists"] = 1.0
        rows, header = _safe_read_results_aggregates(agg_path)
        if rows is not None and header is not None:
            # Structure check
            if header == ["party", "topic", "pledge_count", "share_of_party_pledges"]:
                # Validate each share_str has one decimal place format
                one_decimal_ok = True
                for r in rows:
                    share_str = r["share_str"]
                    # Must be numeric string with one decimal place
                    if not re.fullmatch(r"\d+(?:\.\d)?", share_str):
                        one_decimal_ok = False
                        break
                if one_decimal_ok:
                    scores["aggregates_structure"] = 1.0
            # Values correct check if we have expected aggregates
            if promises is not None and rows is not None:
                # Build mapping from results
                result_map = {(r["party"], r["topic"]): (int(r["pledge_count"]), float(r["share_val"]), r["share_str"]) for r in rows}
                expected_map = {(r["party"], r["topic"]): (int(r["pledge_count"]), float(r["share_of_party_pledges"])) for r in expected_aggregates}
                # Compare keys
                if set(result_map.keys()) == set(expected_map.keys()):
                    ok_vals = True
                    for key in expected_map:
                        exp_count, exp_share = expected_map[key]
                        res_count, res_share_val, res_share_str = result_map[key]
                        if res_count != exp_count:
                            ok_vals = False
                            break
                        # share numeric equality to one decimal, and string formatting exactly one decimal
                        if round(res_share_val, 1) != round(exp_share, 1):
                            ok_vals = False
                            break
                        if res_share_str != f"{exp_share:.1f}":
                            ok_vals = False
                            break
                    if ok_vals:
                        scores["aggregates_values_correct"] = 1.0
    # overall_summary.json checks
    summary_path = workspace / "results" / "overall_summary.json"
    if summary_path.exists():
        scores["overall_summary_exists"] = 1.0
        summary = _safe_load_json(summary_path)
        if isinstance(summary, dict) and "party_totals" in summary and "topic_totals" in summary and "overall_total" in summary:
            if isinstance(summary["party_totals"], dict) and isinstance(summary["topic_totals"], dict) and isinstance(summary["overall_total"], int):
                scores["overall_summary_structure"] = 1.0
            # Correctness vs input
            if promises is not None:
                exp_party = expected_party_totals
                exp_topic = expected_topic_totals
                exp_overall = expected_overall_total
                # Convert keys to str, values to int
                try:
                    party_ok = {str(k): int(v) for k, v in summary["party_totals"].items()} == {str(k): int(v) for k, v in exp_party.items()}
                    topic_ok = {str(k): int(v) for k, v in summary["topic_totals"].items()} == {str(k): int(v) for k, v in exp_topic.items()}
                    overall_ok = int(summary["overall_total"]) == int(exp_overall)
                    if party_ok and topic_ok and overall_ok:
                        scores["overall_summary_correct"] = 1.0
                except Exception:
                    pass
            # Reconcile with aggregates_by_party_topic.csv
            if agg_path.exists():
                rows, header = _safe_read_results_aggregates(agg_path)
                if rows is not None:
                    # Sum by party and topic from aggregates file
                    agg_party_counts: Dict[str, int] = defaultdict(int)
                    agg_topic_counts: Dict[str, int] = defaultdict(int)
                    total = 0
                    for r in rows:
                        p = r["party"]
                        t = r["topic"]
                        c = int(r["pledge_count"])
                        agg_party_counts[p] += c
                        agg_topic_counts[t] += c
                        total += c
                    try:
                        party_ok = {str(k): int(v) for k, v in summary["party_totals"].items()} == {str(k): int(v) for k, v in agg_party_counts.items()}
                        topic_ok = {str(k): int(v) for k, v in summary["topic_totals"].items()} == {str(k): int(v) for k, v in agg_topic_counts.items()}
                        overall_ok = int(summary["overall_total"]) == int(total)
                        if party_ok and topic_ok and overall_ok:
                            scores["overall_summary_reconciles_with_aggregates"] = 1.0
                    except Exception:
                        pass

    # Prepare expected top-3 and number sets if we have promises
    expected_top3: Dict[str, List[Tuple[str, int, float]]] = {}
    nums_from_agg: Dict[str, Any] = {}
    if promises is not None:
        # For expected_top3, we need the full aggregates including shares
        # Rebuild merges shares from expected_aggregates
        exp_aggs_by_party_topic = defaultdict(dict)
        for r in expected_aggregates:
            exp_aggs_by_party_topic[r["party"]][r["topic"]] = (r["pledge_count"], r["share_of_party_pledges"])
        # Build list of dicts to feed into _top_three_topics_per_party
        top_input = []
        for party, topic_map in exp_aggs_by_party_topic.items():
            for topic, (cnt, share) in topic_map.items():
                top_input.append({"party": party, "topic": topic, "pledge_count": cnt, "share_of_party_pledges": share})
        expected_top3 = _top_three_topics_per_party(top_input)
        nums_from_agg = _numbers_from_aggregates(expected_aggregates, expected_party_totals, expected_topic_totals, expected_overall_total)

    # report.md checks
    report_path = workspace / "results" / "report.md"
    report_text = _safe_read_text(report_path)
    if report_text is not None:
        scores["report_exists"] = 1.0
        # word count
        words = re.findall(r"\b\w+\b", report_text)
        if 400 <= len(words) <= 600:
            scores["report_word_count"] = 1.0
        # method statement
        if _contains_phrase_method(report_text):
            scores["report_method_statement"] = 1.0
        # party totals mentioned near party names
        party_totals_ok = True
        if promises is not None:
            for party, total in expected_party_totals.items():
                if not _find_party_total_mentioned(report_text, party, total):
                    party_totals_ok = False
                    break
            if party_totals_ok:
                scores["report_party_totals_mentioned"] = 1.0
        # bulleted top three per party with counts and shares
        if promises is not None and expected_top3:
            if _validate_bulleted_top_three(report_text, expected_top3):
                scores["report_bulleted_top_three_per_party"] = 1.0
        # neutral tone check (avoid loaded phrases)
        if _check_neutral_tone(report_text):
            scores["report_neutral_tone"] = 1.0

    # department_update_rewrite.txt checks
    dep_update_path = workspace / "results" / "department_update_rewrite.txt"
    dep_text = _safe_read_text(dep_update_path)
    if dep_text is not None:
        scores["department_update_exists"] = 1.0
        words = re.findall(r"\b\w+\b", dep_text)
        if 80 <= len(words) <= 120:
            scores["department_update_word_count"] = 1.0
        # numbers from aggregates: include 1-2 specific numbers from computed aggregates
        if promises is not None and nums_from_agg:
            allowed_numbers = set()
            allowed_numbers |= nums_from_agg["count_numbers"]
            allowed_numbers |= nums_from_agg["share_numbers"]
            allowed_numbers |= nums_from_agg["share_numbers_with_pct"]
            allowed_numbers |= nums_from_agg["party_total_numbers"]
            allowed_numbers |= nums_from_agg["topic_total_numbers"]
            allowed_numbers.add(nums_from_agg["overall_total_number"])
            tokens = _extract_numbers(dep_text)
            count_allowed = 0
            for tok in tokens:
                norm = _normalize_number_token(tok)
                # Normalize percent by stripping percent for checking both forms
                if norm.endswith("%") and norm[:-1] in allowed_numbers:
                    count_allowed += 1
                elif norm in allowed_numbers:
                    count_allowed += 1
            if 1 <= count_allowed <= 2:
                scores["department_update_numbers_from_aggregates"] = 1.0
        # neutral tone and removal of loaded language
        if _check_neutral_tone(dep_text):
            scores["department_update_neutral_tone"] = 1.0
        # email format: starts with "Dear" (case-insensitive) within first 50 chars
        if re.search(r"\bDear\b", dep_text, flags=re.IGNORECASE) and dep_text.strip().lower().startswith(("dear",)):
            scores["department_update_email_format"] = 1.0

    # executive_summary.txt checks
    exec_path = workspace / "results" / "executive_summary.txt"
    exec_text = _safe_read_text(exec_path)
    if exec_text is not None:
        scores["executive_summary_exists"] = 1.0
        words = re.findall(r"\b\w+\b", exec_text)
        if 150 <= len(words) <= 200:
            scores["executive_summary_word_count"] = 1.0
        if promises is not None and nums_from_agg:
            allowed_numbers = set()
            allowed_numbers |= nums_from_agg["count_numbers"]
            allowed_numbers |= nums_from_agg["share_numbers"]
            allowed_numbers |= nums_from_agg["share_numbers_with_pct"]
            allowed_numbers |= nums_from_agg["party_total_numbers"]
            allowed_numbers |= nums_from_agg["topic_total_numbers"]
            allowed_numbers.add(nums_from_agg["overall_total_number"])
            tokens = _extract_numbers(exec_text)
            count_allowed = 0
            for tok in tokens:
                norm = _normalize_number_token(tok)
                if norm.endswith("%") and norm[:-1] in allowed_numbers:
                    count_allowed += 1
                elif norm in allowed_numbers:
                    count_allowed += 1
            if count_allowed >= 2:
                scores["executive_summary_numbers_from_aggregates"] = 1.0
        # next steps presence
        if re.search(r"\bnext\b", exec_text, flags=re.IGNORECASE) and re.search(r"\bstep", exec_text, flags=re.IGNORECASE):
            scores["executive_summary_next_steps"] = 1.0
        # neutral tone
        if _check_neutral_tone(exec_text):
            scores["executive_summary_neutral_tone"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()