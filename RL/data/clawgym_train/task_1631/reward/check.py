import csv
import json
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


REQUIRED_HEADER = ["name", "sport", "wins", "losses", "matches", "win_rate", "medal_ratio", "para_status"]
INPUT_ATHLETES_PATH = Path("input/data/athletes.csv")
OUTPUT_STATS_PATH = Path("out/athlete_stats.csv")
SCRIPT_PATH = Path("scripts/generate_stats.py")
DOC_PATH = Path("docs/draft_article.md")
FIX_REPORT_PATH = Path("out/status/fix_report.md")

ORIGINAL_DOC_TEXT = """# Weekly Performance Snapshot: Inclusive Focus

As a journalist covering athletes across both Paralympic and non-Paralympic sports, I want our metrics to fairly reflect everyone's performance.

Factbox (auto-updated fields):
- Para athletes representation: [PARA_FRACTION]=2/6 (33.0%)
- Average win rate (Para): [AVG_PARA_WIN_RATE]=60.0%
- Average win rate (Non-Para): [AVG_NONPARA_WIN_RATE]=80.0%
- Bruno Silva current win rate: [BRUNO_WIN_RATE]=50.0%

Notes: The para community's achievements deserve accurate context.
"""


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = [r for r in reader]
        return header, rows
    except Exception:
        return None


def _safe_int(v: str) -> Optional[int]:
    try:
        return int(v)
    except Exception:
        return None


def _safe_float(v: str) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _compute_expected_from_input(workspace: Path) -> Optional[List[Dict[str, object]]]:
    in_path = workspace / INPUT_ATHLETES_PATH
    data = _read_csv(in_path)
    if data is None:
        return None
    header, rows = data
    required_input_cols = {"name", "sport", "wins", "losses", "medals", "disability_class"}
    if not set(header or []).issuperset(required_input_cols):
        return None

    expected: List[Dict[str, object]] = []
    for r in rows:
        try:
            name = r["name"]
            sport = r["sport"]
            wins = int(r["wins"])
            losses = int(r["losses"])
            medals = int(r["medals"])
            disability_class = (r.get("disability_class") or "").strip()
        except Exception:
            return None
        matches = wins + losses
        if matches > 0:
            win_rate = wins / matches
            medal_ratio = round(medals / matches, 4)
        else:
            win_rate = 0.0
            medal_ratio = 0.0
        para = "Para" if (disability_class != "N/A" and disability_class != "") else "Non-Para"
        expected.append({
            "name": name,
            "sport": sport,
            "wins": wins,
            "losses": losses,
            "matches": matches,
            "win_rate": win_rate,
            "medal_ratio": medal_ratio,
            "para_status": para,
        })
    return expected


def _floats_close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _floats_close_round4(a: float, b: float, tol: float = 5e-5) -> bool:
    return abs(a - b) <= tol


def _build_expected_metrics(expected_rows: List[Dict[str, object]]) -> Dict[str, object]:
    total = len(expected_rows)
    para_rows = [r for r in expected_rows if r["para_status"] == "Para"]
    nonpara_rows = [r for r in expected_rows if r["para_status"] == "Non-Para"]
    x_para = len(para_rows)
    y_total = total
    z_percent = round(100.0 * (x_para / y_total) if y_total > 0 else 0.0, 1)

    def avg_win_rate(rows: List[Dict[str, object]]) -> float:
        if not rows:
            return 0.0
        s = sum(float(r["win_rate"]) for r in rows)
        return s / len(rows)

    avg_para = round(100.0 * avg_win_rate(para_rows), 1)
    avg_nonpara = round(100.0 * avg_win_rate(nonpara_rows), 1)

    bruno_rate = 0.0
    for r in expected_rows:
        if r["name"] == "Bruno Silva":
            bruno_rate = round(100.0 * float(r["win_rate"]), 1)
            break

    return {
        "para_fraction_str": f"{x_para}/{y_total} ({z_percent:.1f}%)",
        "avg_para_str": f"{avg_para:.1f}%",
        "avg_nonpara_str": f"{avg_nonpara:.1f}%",
        "bruno_str": f"{bruno_rate:.1f}%",
        "x_para": x_para,
        "y_total": y_total,
        "z_percent": z_percent,
        "avg_para": avg_para,
        "avg_nonpara": avg_nonpara,
        "bruno": bruno_rate,
    }


def _parse_article_values(text: str) -> Optional[Dict[str, str]]:
    patterns = {
        "PARA_FRACTION": r"\[PARA_FRACTION\]=([^\n\r]+)",
        "AVG_PARA_WIN_RATE": r"\[AVG_PARA_WIN_RATE\]=([^\n\r]+)",
        "AVG_NONPARA_WIN_RATE": r"\[AVG_NONPARA_WIN_RATE\]=([^\n\r]+)",
        "BRUNO_WIN_RATE": r"\[BRUNO_WIN_RATE\]=([^\n\r]+)",
    }
    result: Dict[str, str] = {}
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if not m:
            return None
        result[key] = m.group(1).strip()
    return result


def _normalize_article(text: str) -> str:
    def repl_para(_):
        return "[PARA_FRACTION]=<VAL>"

    def repl_avg_para(_):
        return "[AVG_PARA_WIN_RATE]=<VAL>"

    def repl_avg_nonpara(_):
        return "[AVG_NONPARA_WIN_RATE]=<VAL>"

    def repl_bruno(_):
        return "[BRUNO_WIN_RATE]=<VAL>"

    text = re.sub(r"\[PARA_FRACTION\]=[^\n\r]+", repl_para, text)
    text = re.sub(r"\[AVG_PARA_WIN_RATE\]=[^\n\r]+", repl_avg_para, text)
    text = re.sub(r"\[AVG_NONPARA_WIN_RATE\]=[^\n\r]+", repl_avg_nonpara, text)
    text = re.sub(r"\[BRUNO_WIN_RATE\]=[^\n\r]+", repl_bruno, text)
    return "\n".join(text.splitlines())


def _script_checks(script_text: Optional[str]) -> Dict[str, float]:
    checks = {
        "script_win_rate_fieldname_correct": 0.0,
        "script_float_division_used": 0.0,
        "script_para_status_logic_generalized": 0.0,
        "script_handles_output_dir": 0.0,
    }
    if script_text is None:
        return checks

    txt = script_text

    # win_rate fieldname: expect 'win_rate' used and 'winrate' not used in headers or dict keys
    if ("win_rate" in txt) and ("winrate" not in txt):
        checks["script_win_rate_fieldname_correct"] = 1.0

    # float division: must not use integer division operator
    if "//" not in txt:
        checks["script_float_division_used"] = 1.0

    # para status logic generalized: avoid startswith("T") and prefer check against "N/A" and non-empty
    cond_good = (("'N/A'" in txt) or ("\"N/A\"" in txt)) and ("!=" in txt or "not" in txt)
    cond_bad = ("startswith(\"T\")" in txt) or ("startswith('T')" in txt)
    if cond_good and not cond_bad:
        checks["script_para_status_logic_generalized"] = 1.0

    # output dir handling
    if ("mkdir(" in txt) or ("makedirs(" in txt):
        checks["script_handles_output_dir"] = 1.0

    return checks


def _has_four_decimal_places(s: str) -> bool:
    if s is None:
        return False
    s = s.strip()
    return bool(re.fullmatch(r"-?\d+\.\d{4}", s))


def _evaluate_fix_report(report_text: Optional[str], expected_metrics: Optional[Dict[str, object]]) -> Dict[str, float]:
    checks = {
        "fix_report_exists": 0.0,
        "fix_report_root_causes_at_least_two": 0.0,
        "fix_report_describes_fixes": 0.0,
        "fix_report_before_after_metrics_correct": 0.0,
        "fix_report_zero_matches_note": 0.0,
    }
    if report_text is None:
        return checks
    checks["fix_report_exists"] = 1.0
    text = report_text.lower()

    categories = {
        "para_classification_issue": any(k in text for k in ["misclass", "para status", "disability", "n/a", "startswith(\"t\")", "startswith('t')"]),
        "integer_division_issue": any(k in text for k in ["integer division", "wins // matches", "//", "float division"]),
        "header_fieldname_issue": any(k in text for k in ["winrate", "wrong field", "field name", "header", "column name", "win_rate key"]),
        "output_dir_issue": any(k in text for k in ["output directory", "mkdir", "makedirs", "ensure output", "parents=true", "parents = true"]),
    }
    if sum(1 for v in categories.values() if v) >= 2:
        checks["fix_report_root_causes_at_least_two"] = 1.0

    if any(k in text for k in ["fix", "fixed", "update", "updated", "change", "changed", "corrected", "patch"]):
        checks["fix_report_describes_fixes"] = 1.0

    if (("zero" in text and "match" in text) or ("division by zero" in text) or ("matches == 0" in text)):
        checks["fix_report_zero_matches_note"] = 1.0

    before_para_fraction = "2/6 (33.0%)"
    before_avg_para = "60.0%"
    before_avg_nonpara = "80.0%"
    before_bruno = "50.0%"

    if expected_metrics is not None:
        after_para_fraction = expected_metrics["para_fraction_str"]
        after_avg_para = expected_metrics["avg_para_str"]
        after_avg_nonpara = expected_metrics["avg_nonpara_str"]
        after_bruno = expected_metrics["bruno_str"]
        text_up = report_text

        conds = [
            (before_para_fraction in text_up and after_para_fraction in text_up),
            (before_avg_para in text_up and after_avg_para in text_up),
            (before_avg_nonpara in text_up and after_avg_nonpara in text_up),
            (before_bruno in text_up and after_bruno in text_up),
        ]
        if all(conds):
            checks["fix_report_before_after_metrics_correct"] = 1.0

    return checks


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "csv_exists_and_header_correct": 0.0,
        "csv_row_count_correct": 0.0,
        "csv_values_correct": 0.0,
        "csv_medal_ratio_format_4dp": 0.0,
        "article_updated_fields_correct": 0.0,
        "article_structure_preserved": 0.0,
        "script_win_rate_fieldname_correct": 0.0,
        "script_float_division_used": 0.0,
        "script_para_status_logic_generalized": 0.0,
        "script_handles_output_dir": 0.0,
        "fix_report_exists": 0.0,
        "fix_report_root_causes_at_least_two": 0.0,
        "fix_report_describes_fixes": 0.0,
        "fix_report_before_after_metrics_correct": 0.0,
        "fix_report_zero_matches_note": 0.0,
    }

    expected_rows = _compute_expected_from_input(workspace)
    produced_csv_path = workspace / OUTPUT_STATS_PATH
    produced_csv = _read_csv(produced_csv_path)

    if produced_csv is not None:
        header, rows = produced_csv
        if header == REQUIRED_HEADER:
            scores["csv_exists_and_header_correct"] = 1.0
        if expected_rows is not None and len(rows) == len(expected_rows):
            scores["csv_row_count_correct"] = 1.0
        if expected_rows is not None:
            exp_by_name = {r["name"]: r for r in expected_rows}
            ok = True
            fourdp_ok = True
            for r in rows:
                name = r.get("name", "")
                if name not in exp_by_name:
                    ok = False
                    break
                exp = exp_by_name[name]
                wins = _safe_int(r.get("wins", ""))
                losses = _safe_int(r.get("losses", ""))
                matches = _safe_int(r.get("matches", ""))
                win_rate = _safe_float(r.get("win_rate", ""))
                medal_ratio_str = r.get("medal_ratio", "")
                medal_ratio_val = _safe_float(medal_ratio_str)
                para_status = r.get("para_status", "")
                if None in (wins, losses, matches, win_rate, medal_ratio_val):
                    ok = False
                    break
                if wins != exp["wins"] or losses != exp["losses"]:
                    ok = False
                    break
                if matches != exp["matches"]:
                    ok = False
                    break
                if not _floats_close(float(win_rate), float(exp["win_rate"]), tol=1e-9):
                    ok = False
                    break
                if not _floats_close_round4(float(medal_ratio_val), float(exp["medal_ratio"]), tol=5e-5):
                    ok = False
                    break
                if para_status != exp["para_status"]:
                    ok = False
                    break
                if not _has_four_decimal_places(medal_ratio_str):
                    fourdp_ok = False
            if ok:
                scores["csv_values_correct"] = 1.0
            if fourdp_ok and rows:
                scores["csv_medal_ratio_format_4dp"] = 1.0

    article_path = workspace / DOC_PATH
    article_text = _read_text(article_path)
    if article_text is not None and expected_rows is not None:
        parsed_vals = _parse_article_values(article_text)
        expected_metrics = _build_expected_metrics(expected_rows)
        updated_ok = False
        if parsed_vals is not None:
            if parsed_vals.get("PARA_FRACTION") == expected_metrics["para_fraction_str"] \
               and parsed_vals.get("AVG_PARA_WIN_RATE") == expected_metrics["avg_para_str"] \
               and parsed_vals.get("AVG_NONPARA_WIN_RATE") == expected_metrics["avg_nonpara_str"] \
               and parsed_vals.get("BRUNO_WIN_RATE") == expected_metrics["bruno_str"]:
                scores["article_updated_fields_correct"] = 1.0
                updated_ok = True

        if updated_ok:
            normalized_current = _normalize_article(article_text)
            normalized_original = _normalize_article(ORIGINAL_DOC_TEXT)
            if normalized_current == normalized_original:
                scores["article_structure_preserved"] = 1.0

    script_text = _read_text(workspace / SCRIPT_PATH)
    script_scores = _script_checks(script_text)
    scores.update(script_scores)

    expected_metrics = _build_expected_metrics(expected_rows) if expected_rows is not None else None
    report_text = _read_text(workspace / FIX_REPORT_PATH)
    report_scores = _evaluate_fix_report(report_text, expected_metrics)
    scores.update(report_scores)

    for k, v in list(scores.items()):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        if fv < 0.0:
            fv = 0.0
        if fv > 1.0:
            fv = 1.0
        scores[k] = fv

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()