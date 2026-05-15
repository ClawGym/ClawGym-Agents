import csv
import json
import re
import shlex
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s.strip())
    except Exception:
        return None


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s.strip())
    except Exception:
        return None


def _compute_expected(workspace: Path) -> Optional[List[Dict[str, object]]]:
    beds_path = workspace / "input" / "state_psych_beds.csv"
    pop_path = workspace / "input" / "state_population.csv"
    beds_rows = _read_csv_dicts(beds_path)
    pop_rows = _read_csv_dicts(pop_path)
    if beds_rows is None or pop_rows is None:
        return None

    beds_map: Dict[Tuple[str, int], int] = {}
    pop_map: Dict[Tuple[str, int], int] = {}
    for r in beds_rows:
        state = r.get("state")
        year = _safe_int(r.get("year", ""))
        beds = _safe_int(r.get("beds_public_psychiatric", ""))
        if state is None or year is None or beds is None:
            return None
        beds_map[(state, year)] = beds

    for r in pop_rows:
        state = r.get("state")
        year = _safe_int(r.get("year", ""))
        pop = _safe_int(r.get("population", ""))
        if state is None or year is None or pop is None:
            return None
        pop_map[(state, year)] = pop

    years = [1955, 1980]

    def has_years(mapping: Dict[Tuple[str, int], int], st: str, ys: List[int]) -> bool:
        return all((st, y) in mapping for y in ys)

    states_beds = set([s for (s, y) in beds_map.keys() if y in years])
    states_pop = set([s for (s, y) in pop_map.keys() if y in years])
    states_complete = []
    for s in sorted(states_beds & states_pop):
        if has_years(beds_map, s, years) and has_years(pop_map, s, years):
            states_complete.append(s)

    results: List[Dict[str, object]] = []
    for s in states_complete:
        beds_1955 = beds_map[(s, 1955)]
        beds_1980 = beds_map[(s, 1980)]
        pop_1955 = pop_map[(s, 1955)]
        pop_1980 = pop_map[(s, 1980)]
        if pop_1955 == 0 or pop_1980 == 0:
            return None
        beds_per_100k_1955 = (beds_1955 / pop_1955) * 100000.0
        beds_per_100k_1980 = (beds_1980 / pop_1980) * 100000.0
        abs_decline_beds = beds_1955 - beds_1980
        decline_per_100k = beds_per_100k_1955 - beds_per_100k_1980
        results.append({
            "state": s,
            "beds_1955": beds_1955,
            "beds_1980": beds_1980,
            "abs_decline_beds": abs_decline_beds,
            "pop_1955": pop_1955,
            "pop_1980": pop_1980,
            "beds_per_100k_1955": beds_per_100k_1955,
            "beds_per_100k_1980": beds_per_100k_1980,
            "decline_per_100k": decline_per_100k,
        })

    results.sort(key=lambda d: (-d["decline_per_100k"], d["state"]))
    for idx, d in enumerate(results, start=1):
        d["rank"] = idx
    return results


def _read_output_bed_declines(path: Path) -> Optional[List[Dict[str, object]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None
    if not rows or len(rows) < 2:
        return None
    header = rows[0]
    expected_header = [
        "state",
        "beds_1955",
        "beds_1980",
        "abs_decline_beds",
        "pop_1955",
        "pop_1980",
        "beds_per_100k_1955",
        "beds_per_100k_1980",
        "decline_per_100k",
        "rank",
    ]
    if header != expected_header:
        return [{"__bad_header__": header}]
    out_rows: List[Dict[str, object]] = []
    for row in rows[1:]:
        if len(row) != len(expected_header):
            return None
        st = row[0]
        b55 = _safe_int(row[1])
        b80 = _safe_int(row[2])
        abd = _safe_int(row[3])
        p55 = _safe_int(row[4])
        p80 = _safe_int(row[5])
        bp55 = _safe_float(row[6])
        bp80 = _safe_float(row[7])
        dpk = _safe_float(row[8])
        rk = _safe_int(row[9])
        if any(v is None for v in (st, b55, b80, abd, p55, p80, bp55, bp80, dpk, rk)):
            return None
        out_rows.append({
            "state": st,
            "beds_1955": b55,
            "beds_1980": b80,
            "abs_decline_beds": abd,
            "pop_1955": p55,
            "pop_1980": p80,
            "beds_per_100k_1955": bp55,
            "beds_per_100k_1980": bp80,
            "decline_per_100k": dpk,
            "rank": rk,
        })
    return out_rows


def _almost_equal(a: float, b: float, tol: float = 0.1) -> bool:
    return abs(a - b) <= tol


def _format_one_decimal(x: float) -> str:
    return f"{x:.1f}"


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _nonempty_lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "results_csv_exists_and_columns": 0.0,
        "results_csv_rowcount_and_states": 0.0,
        "results_csv_values_correct": 0.0,
        "results_csv_sorted_and_ranked": 0.0,
        "top5_summary_exists_and_lines": 0.0,
        "top5_summary_top5_order_and_values": 0.0,
        "email_subject_line": 0.0,
        "email_greeting": 0.0,
        "email_word_count": 0.0,
        "email_mentions_metric": 0.0,
        "email_mentions_time_window": 0.0,
        "email_includes_top_five_states": 0.0,
        "email_includes_top_five_values": 0.0,
        "email_next_step": 0.0,
        "email_closing_and_name": 0.0,
        "run_command_present": 0.0,
        "run_command_references_script": 0.0,
    }

    expected = _compute_expected(workspace)

    bed_declines_path = workspace / "output" / "bed_declines_1955_1980.csv"
    produced = None
    bad_header_flag = False
    if bed_declines_path.exists():
        produced = _read_output_bed_declines(bed_declines_path)
        if produced is not None and isinstance(produced, list) and produced and "__bad_header__" in produced[0]:
            bad_header_flag = True
            produced = None

    if bed_declines_path.exists() and not bad_header_flag and produced is not None:
        scores["results_csv_exists_and_columns"] = 1.0

    if expected is not None and produced is not None:
        expected_states = [d["state"] for d in expected]
        prod_states = [d["state"] for d in produced]
        if len(produced) == len(expected) and set(prod_states) == set(expected_states):
            scores["results_csv_rowcount_and_states"] = 1.0

    if expected is not None and produced is not None:
        correct_values = True
        correct_order = True

        produced_sorted_desc = all(
            produced[i]["decline_per_100k"] >= produced[i + 1]["decline_per_100k"]
            for i in range(len(produced) - 1)
        )
        ranks_ok = [d["rank"] for d in produced] == list(range(1, len(produced) + 1))
        expected_order = [d["state"] for d in expected]
        produced_order = [d["state"] for d in produced]
        if expected_order != produced_order:
            correct_order = False

        exp_by_state = {d["state"]: d for d in expected}
        for row in produced:
            st = row["state"]
            exp = exp_by_state.get(st)
            if exp is None:
                correct_values = False
                break
            if not (row["beds_1955"] == exp["beds_1955"] and
                    row["beds_1980"] == exp["beds_1980"] and
                    row["abs_decline_beds"] == exp["abs_decline_beds"] and
                    row["pop_1955"] == exp["pop_1955"] and
                    row["pop_1980"] == exp["pop_1980"]):
                correct_values = False
                break
            if not (_almost_equal(row["beds_per_100k_1955"], exp["beds_per_100k_1955"]) and
                    _almost_equal(row["beds_per_100k_1980"], exp["beds_per_100k_1980"]) and
                    _almost_equal(row["decline_per_100k"], exp["decline_per_100k"])):
                correct_values = False
                break
            if row["rank"] != (expected_order.index(st) + 1):
                correct_order = False

        if correct_values:
            scores["results_csv_values_correct"] = 1.0
        if correct_order and produced_sorted_desc and ranks_ok:
            scores["results_csv_sorted_and_ranked"] = 1.0

    top5_path = workspace / "output" / "top5_summary.txt"
    top5_text = _safe_read_text(top5_path) if top5_path.exists() else None
    if top5_text:
        lines = _nonempty_lines(top5_text)
        if expected is not None and len(expected) >= 5:
            exp_top5 = expected[:5]
            exp_states = [d["state"] for d in exp_top5]
            ordered_lines = []
            for ln in lines:
                if any(s in ln for s in exp_states):
                    ordered_lines.append(ln)
            if len(ordered_lines) >= 5:
                scores["top5_summary_exists_and_lines"] = 1.0
                ok = True
                for i in range(5):
                    exp_state = exp_states[i]
                    exp_decline_one_decimal = _format_one_decimal(exp_top5[i]["decline_per_100k"])
                    exp_abs_decline = exp_top5[i]["abs_decline_beds"]
                    ln = ordered_lines[i]
                    if exp_state not in ln:
                        ok = False
                        break
                    if exp_decline_one_decimal not in ln:
                        ok = False
                        break
                    if str(exp_abs_decline) not in ln:
                        ok = False
                        break
                if ok:
                    scores["top5_summary_top5_order_and_values"] = 1.0

    email_path = workspace / "output" / "email_to_curator.txt"
    email_text = _safe_read_text(email_path) if email_path.exists() else None
    if email_text:
        lines = email_text.splitlines()
        content_lower = email_text.lower()

        subject_required = "Brief: 1955–1980 psychiatric bed declines by state"
        has_subject_exact = any(ln.strip() == subject_required for ln in lines)
        has_subject_prefixed = any(ln.strip().startswith("Subject:") and ln.strip()[8:].strip() == subject_required for ln in lines)
        if has_subject_exact or has_subject_prefixed:
            scores["email_subject_line"] = 1.0

        if any("dr. alvarez" in ln.lower() for ln in lines):
            scores["email_greeting"] = 1.0

        words = re.findall(r"\b\w+(?:'\w+)?\b", email_text)
        if 150 <= len(words) <= 220:
            scores["email_word_count"] = 1.0

        if re.search(r"per[- ]?100,?000|per[- ]?100k", content_lower):
            scores["email_mentions_metric"] = 1.0

        if "1955" in email_text and "1980" in email_text:
            scores["email_mentions_time_window"] = 1.0

        if expected is not None:
            top5 = expected[:5]
            top5_states = [d["state"] for d in top5]
            top5_values_strs = [_format_one_decimal(d["decline_per_100k"]) for d in top5]
            if all(any(st in ln for ln in lines) for st in top5_states):
                scores["email_includes_top_five_states"] = 1.0
            if all(val in email_text for val in top5_values_strs):
                scores["email_includes_top_five_values"] = 1.0

        if re.search(r"next step|next steps|policy|milestone|link", content_lower):
            scores["email_next_step"] = 1.0

        closings = [
            "sincerely", "best regards", "best,", "regards", "thank you", "thanks", "warm regards",
            "respectfully", "kind regards"
        ]
        has_closing = any(any(c in ln.lower() for c in closings) for ln in lines)
        last_nonempty = None
        for ln in reversed(lines):
            if ln.strip():
                last_nonempty = ln.strip()
                break
        has_name = bool(last_nonempty and re.search(r"[A-Za-z]{2,}", last_nonempty))
        if has_closing and has_name:
            scores["email_closing_and_name"] = 1.0

    run_cmd_path = workspace / "output" / "run_command.txt"
    run_cmd_text = _safe_read_text(run_cmd_path) if run_cmd_path.exists() else None
    if run_cmd_text:
        first_line = ""
        for ln in run_cmd_text.splitlines():
            if ln.strip():
                first_line = ln.strip()
                break
        if first_line:
            scores["run_command_present"] = 1.0
            try:
                tokens = shlex.split(first_line)
            except Exception:
                tokens = first_line.split()
            script_exists = False
            for t in tokens:
                if t.endswith(".py") or t.endswith(".sh"):
                    p = (workspace / t).resolve()
                    if p.exists():
                        script_exists = True
                        break
                    alt = workspace / t
                    if alt.exists():
                        script_exists = True
                        break
            if script_exists:
                scores["run_command_references_script"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()