import json
import sys
import re
import csv
from pathlib import Path
from typing import Optional, List, Dict, Tuple


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


def _read_csv_dicts(p: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        # Ensure header validity (no None keys)
        if any(None in row for row in rows):
            return None
        return rows
    except Exception:
        return None


def _parse_float_str(val: str) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    # remove commas and currency symbols
    s = s.replace(",", "")
    s = s.replace("$", "")
    # handle parentheses for negative?
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except Exception:
        return None


def _extract_html_off_court_metrics(html: str) -> Dict[str, Optional[float]]:
    metrics = {
        "scholarships_awarded": None,
        "program_reach_2020_students": None,
        "youth_centers_opened": None,
    }
    if not html:
        return metrics
    # Scholarships
    m = re.search(r"awarded\s+(\d+)\s+scholarships", html, re.IGNORECASE)
    if m:
        try:
            metrics["scholarships_awarded"] = float(m.group(1))
        except Exception:
            pass
    # Program reach 2020
    m2 = re.search(r"reach(?:ing|ed)\s+([\d,]+)\s+students\s+in\s+2020", html, re.IGNORECASE)
    if m2:
        val = _parse_float_str(m2.group(1))
        metrics["program_reach_2020_students"] = val
    # Youth centers opened
    m3 = re.search(r"opened\s+(\d+)\s+youth\s+learning\s+centers", html, re.IGNORECASE)
    if m3:
        try:
            metrics["youth_centers_opened"] = float(m3.group(1))
        except Exception:
            pass
    return metrics


def _sum_grants(csv_rows: Optional[List[Dict[str, str]]]) -> Optional[float]:
    if not csv_rows:
        return None
    total = 0.0
    for row in csv_rows:
        if "AmountUSD" not in row:
            return None
        v = _parse_float_str(row.get("AmountUSD", ""))
        if v is None:
            return None
        total += v
    return total


def _compute_scores(on_court: Dict[str, Optional[float]], off_court: Dict[str, Optional[float]]) -> Optional[Tuple[float, float, float]]:
    # weights and normalization from input/notes/evaluation_criteria.md
    titles = on_court.get("titles")
    mvps = on_court.get("mvps")
    career_points = on_court.get("career_points")
    scholarships = off_court.get("scholarships_awarded")
    grants_total_usd = off_court.get("grants_total_usd")
    program_reach = off_court.get("program_reach_2020_students")
    if None in (titles, mvps, career_points, scholarships, grants_total_usd, program_reach):
        return None
    # Normalize and cap at 1.0
    n_titles = min(1.0, float(titles) / 3.0)
    n_mvps = min(1.0, float(mvps) / 3.0)
    n_points = min(1.0, float(career_points) / 25000.0)
    on_court_score = 0.4 * n_titles + 0.3 * n_mvps + 0.3 * n_points

    n_scholarships = min(1.0, float(scholarships) / 150.0)
    n_grants = min(1.0, float(grants_total_usd) / 4000000.0)
    n_reach = min(1.0, float(program_reach) / 3000.0)
    off_court_score = 0.4 * n_scholarships + 0.4 * n_grants + 0.2 * n_reach

    overall_score = 0.5 * on_court_score + 0.5 * off_court_score
    return (on_court_score, off_court_score, overall_score)


def _find_required_rows(rows: List[Dict[str, str]], category: str, metrics: List[str]) -> Dict[str, Dict[str, str]]:
    found = {}
    for row in rows:
        if row.get("category", "").strip() == category and row.get("metric", "").strip() in metrics:
            found[row["metric"].strip()] = row
    return found


def _parse_report_paragraphs(text: str) -> List[str]:
    # Split by blank lines as paragraph delimiters
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return paras


def _word_count(text: str) -> int:
    # Count words by splitting on whitespace
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def _extract_floats_from_text(text: str) -> List[float]:
    # Match floats including integers and decimals
    matches = re.findall(r"(?<![\w])[-+]?\d+(?:\.\d+)?(?![\w])", text)
    vals = []
    for m in matches:
        try:
            vals.append(float(m))
        except Exception:
            continue
    return vals


def _normalize_apostrophe(s: str) -> str:
    return s.replace("’", "'").strip().lower()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_csv_exists_and_columns": 0.0,
        "metrics_required_rows_present": 0.0,
        "metrics_values_correct_on_court": 0.0,
        "metrics_values_correct_off_court": 0.0,
        "metrics_grants_total_correct": 0.0,
        "metrics_sources_correct": 0.0,
        "metrics_scores_correct": 0.0,
        "report_exists_and_citations": 0.0,
        "report_exec_summary_length": 0.0,
        "report_methods_description": 0.0,
        "report_scores_discussed_and_present": 0.0,
        "report_strengths_limitations_present": 0.0,
        "report_concluding_judgment_present": 0.0,
        "report_discrepancies_or_consistency_statement": 0.0,
        "email_exists_and_headers": 0.0,
        "email_recipients_filtered_correct": 0.0,
        "email_subject_correct": 0.0,
        "email_includes_paths": 0.0,
        "email_body_word_count": 0.0,
        "email_scores_present_numeric": 0.0,
        "email_from_line_present": 0.0,
    }

    # Load input sources expected for recomputation
    input_json_path = workspace / "input" / "data" / "season_stats.json"
    input_html_path = workspace / "input" / "articles" / "player_legacy.html"
    input_grants_csv_path = workspace / "input" / "data" / "community_grants.csv"
    input_rubric_md_path = workspace / "input" / "notes" / "evaluation_criteria.md"
    input_contacts_csv_path = workspace / "input" / "contacts" / "department_list.csv"

    season_stats = _load_json(input_json_path) if input_json_path.exists() else None
    html_text = _read_text(input_html_path) if input_html_path.exists() else None
    grants_rows = _read_csv_dicts(input_grants_csv_path) if input_grants_csv_path.exists() else None
    rubric_text = _read_text(input_rubric_md_path) if input_rubric_md_path.exists() else None
    contacts_rows = _read_csv_dicts(input_contacts_csv_path) if input_contacts_csv_path.exists() else None

    expected_on_court = {}
    if season_stats and "career" in season_stats:
        car = season_stats["career"]
        expected_on_court = {
            "titles": float(car.get("titles")) if car.get("titles") is not None else None,
            "mvps": float(car.get("mvps")) if car.get("mvps") is not None else None,
            "career_points": float(car.get("points")) if car.get("points") is not None else None,
            "games": float(car.get("games")) if car.get("games") is not None else None,
            "assists": float(car.get("assists")) if car.get("assists") is not None else None,
        }
    expected_off_court_html = _extract_html_off_court_metrics(html_text) if html_text else {
        "scholarships_awarded": None,
        "program_reach_2020_students": None,
        "youth_centers_opened": None,
    }
    expected_grants_total = _sum_grants(grants_rows) if grants_rows else None

    expected_off_court = {
        "scholarships_awarded": expected_off_court_html.get("scholarships_awarded"),
        "grants_total_usd": expected_grants_total,
        "program_reach_2020_students": expected_off_court_html.get("program_reach_2020_students"),
        "youth_centers_opened": expected_off_court_html.get("youth_centers_opened"),
    }

    expected_scores = _compute_scores(
        {
            "titles": expected_on_court.get("titles"),
            "mvps": expected_on_court.get("mvps"),
            "career_points": expected_on_court.get("career_points"),
        },
        expected_off_court,
    )

    # Check metrics CSV
    metrics_csv_path = workspace / "output" / "structured" / "ellis_metrics.csv"
    metrics_rows: Optional[List[Dict[str, str]]] = None
    if metrics_csv_path.exists():
        metrics_rows = _read_csv_dicts(metrics_csv_path)
        if metrics_rows is not None:
            # Check columns
            cols = list(metrics_rows[0].keys()) if metrics_rows else []
            if cols == ["category", "metric", "value", "unit", "source_file"]:
                scores["metrics_csv_exists_and_columns"] = 1.0

    if metrics_rows:
        # Find required rows
        required_on_court_metrics = ["titles", "mvps", "career_points", "games", "assists"]
        required_off_court_metrics = ["scholarships_awarded", "grants_total_usd", "program_reach_2020_students", "youth_centers_opened"]
        required_score_metrics = ["on_court_score", "off_court_score", "overall_score"]

        on_rows = _find_required_rows(metrics_rows, "on_court", required_on_court_metrics)
        off_rows = _find_required_rows(metrics_rows, "off_court", required_off_court_metrics)
        score_rows = _find_required_rows(metrics_rows, "scores", required_score_metrics)

        if all(m in on_rows for m in required_on_court_metrics) and \
           all(m in off_rows for m in required_off_court_metrics) and \
           all(m in score_rows for m in required_score_metrics):
            scores["metrics_required_rows_present"] = 1.0

        # Validate values on-court
        oc_ok = True
        if expected_on_court:
            for m in required_on_court_metrics:
                row = on_rows.get(m)
                if not row:
                    oc_ok = False
                    break
                val = _parse_float_str(row.get("value", ""))
                exp = expected_on_court.get(m)
                if val is None or exp is None or abs(val - exp) > 1e-6:
                    oc_ok = False
                    break
        else:
            oc_ok = False
        scores["metrics_values_correct_on_court"] = 1.0 if oc_ok else 0.0

        # Validate values off-court (non-grants)
        off_ok = True
        for m in ["scholarships_awarded", "program_reach_2020_students", "youth_centers_opened"]:
            row = off_rows.get(m)
            exp = expected_off_court.get(m)
            if row is None or exp is None:
                off_ok = False
                break
            val = _parse_float_str(row.get("value", ""))
            if val is None or abs(val - exp) > 1e-6:
                off_ok = False
                break
        scores["metrics_values_correct_off_court"] = 1.0 if off_ok else 0.0

        # Validate grants_total_usd value and unit, and sum correctness
        grants_ok = False
        grants_row = off_rows.get("grants_total_usd")
        if grants_row and expected_grants_total is not None:
            gval = _parse_float_str(grants_row.get("value", ""))
            unit = (grants_row.get("unit") or "").strip().lower()
            if gval is not None and abs(gval - expected_grants_total) <= 1e-6 and "usd" in unit:
                grants_ok = True
        scores["metrics_grants_total_correct"] = 1.0 if grants_ok else 0.0

        # Validate sources for each metric row
        sources_ok = True
        # on_court rows should cite JSON
        for m in required_on_court_metrics:
            r = on_rows.get(m)
            if not r:
                sources_ok = False
                break
            sf = (r.get("source_file") or "").strip()
            if sf != "input/data/season_stats.json":
                sources_ok = False
                break
        # off_court from HTML
        for m in ["scholarships_awarded", "program_reach_2020_students", "youth_centers_opened"]:
            r = off_rows.get(m)
            if not r:
                sources_ok = False
                break
            sf = (r.get("source_file") or "").strip()
            if sf != "input/articles/player_legacy.html":
                sources_ok = False
                break
        # grants_total_usd from CSV
        gr = off_rows.get("grants_total_usd")
        if not gr or (gr.get("source_file") or "").strip() != "input/data/community_grants.csv":
            sources_ok = False
        # scores rows from rubric md
        for m in required_score_metrics:
            r = score_rows.get(m)
            if not r:
                sources_ok = False
                break
            sf = (r.get("source_file") or "").strip()
            if sf != "input/notes/evaluation_criteria.md":
                sources_ok = False
                break
        scores["metrics_sources_correct"] = 1.0 if sources_ok else 0.0

        # Validate scores
        scores_ok = False
        if expected_scores is not None:
            try:
                oc_row = score_rows.get("on_court_score")
                of_row = score_rows.get("off_court_score")
                ov_row = score_rows.get("overall_score")
                oc_val = _parse_float_str(oc_row.get("value", "")) if oc_row else None
                of_val = _parse_float_str(of_row.get("value", "")) if of_row else None
                ov_val = _parse_float_str(ov_row.get("value", "")) if ov_row else None
                if None not in (oc_val, of_val, ov_val):
                    tol = 1e-3
                    if abs(oc_val - expected_scores[0]) <= tol and abs(of_val - expected_scores[1]) <= tol and abs(ov_val - expected_scores[2]) <= tol:
                        scores_ok = True
            except Exception:
                scores_ok = False
        scores["metrics_scores_correct"] = 1.0 if scores_ok else 0.0

    # Report checks
    report_path = workspace / "output" / "report" / "ellis_critical_review.md"
    report_text = _read_text(report_path) if report_path.exists() else None
    if report_text is not None:
        # existence and citations: must include references to input files and at least 5 citations
        included_paths = [
            "input/articles/player_legacy.html",
            "input/data/season_stats.json",
            "input/data/community_grants.csv",
            "input/notes/evaluation_criteria.md",
        ]
        cites = sum(report_text.count("input/") for _ in [0])  # count occurrences of "input/"
        has_all_sources = all(path in report_text for path in included_paths)
        if has_all_sources and (report_text.count("input/") >= 5):
            scores["report_exists_and_citations"] = 1.0

        # Executive summary length: first paragraph word count ~120–180 (tolerate 110–200)
        paras = _parse_report_paragraphs(report_text)
        if paras:
            wc = _word_count(paras[0])
            if 110 <= wc <= 200:
                scores["report_exec_summary_length"] = 1.0

        # Methods: mention HTML, CSV, JSON and cross-validate
        rt_low = report_text.lower()
        if ("html" in rt_low and "csv" in rt_low and "json" in rt_low) and (("cross" in rt_low and "validat" in rt_low) or "cross-validate" in rt_low):
            scores["report_methods_description"] = 1.0

        # Scores discussed: presence of tokens
        if ("on_court_score" in report_text) and ("off_court_score" in report_text) and ("overall_score" in report_text):
            scores["report_scores_discussed_and_present"] = 1.0

        # Strengths and limitations: require at least 3 occurrences each
        if (len(re.findall(r"strength", rt_low)) >= 3) and (len(re.findall(r"limitation", rt_low)) >= 3):
            scores["report_strengths_limitations_present"] = 1.0

        # Concluding judgment: look for legacy + off-court and extend/meaningful
        if ("legacy" in rt_low) and ("off-court" in rt_low or "off court" in rt_low) and ("extend" in rt_low or "meaningful" in rt_low or "meaningfully" in rt_low):
            scores["report_concluding_judgment_present"] = 1.0

        # Discrepancies or consistency statement
        if ("discrep" in rt_low) or ("consisten" in rt_low):
            scores["report_discrepancies_or_consistency_statement"] = 1.0

    # Email checks
    email_path = workspace / "output" / "message" / "department_email_draft.txt"
    email_text = _read_text(email_path) if email_path.exists() else None
    to_emails_expected: Optional[set] = None
    if contacts_rows:
        # Filter Sociology department with Role Chair or Faculty
        to_emails_expected = set()
        for row in contacts_rows:
            dept = (row.get("Department") or "").strip()
            role = (row.get("Role") or "").strip()
            email = (row.get("Email") or "").strip()
            if dept == "Sociology" and role in {"Chair", "Faculty"} and email:
                to_emails_expected.add(email)

    if email_text is not None:
        # Headers presence
        has_to = email_text.strip().lower().startswith("to:")
        has_subject = "subject:" in email_text.lower()
        has_body = "body" in email_text.lower()
        has_from = "from:" in email_text.lower()
        if has_to and has_subject and has_body and has_from:
            scores["email_exists_and_headers"] = 1.0

        # Parse lines
        lines = [ln.strip() for ln in email_text.splitlines()]
        to_line = next((ln for ln in lines if ln.lower().startswith("to:")), "")
        subject_line = next((ln for ln in lines if ln.lower().startswith("subject:")), "")
        from_line = next((ln for ln in lines if ln.lower().startswith("from:")), "")
        # Body: lines between 'Body' and 'From:' (case-insensitive)
        body_index = None
        from_index = None
        for i, ln in enumerate(lines):
            if ln.lower().startswith("body"):
                body_index = i
            if ln.lower().startswith("from:"):
                from_index = i
                break
        body_text = ""
        if body_index is not None:
            start = body_index
            # If 'Body:' line, content might be same line after colon
            if ":" in lines[body_index]:
                body_text = lines[body_index].split(":", 1)[1].strip()
                start = body_index + 1
            # Append subsequent lines up to 'From:'
            if from_index is not None and from_index > start:
                body_text = (body_text + "\n" + "\n".join(lines[start:from_index])).strip() if body_text else "\n".join(lines[start:from_index]).strip()
            elif from_index is None:
                body_text = (body_text + "\n" + "\n".join(lines[start + 1:])).strip() if body_text else "\n".join(lines[start + 1:]).strip()

        # Recipients filtered correct
        if to_emails_expected is not None and to_line:
            to_vals = to_line.split(":", 1)[1] if ":" in to_line else ""
            # split by semicolon or comma
            raw_emails = [e.strip() for e in re.split(r"[;,]", to_vals) if e.strip()]
            if set(raw_emails) == to_emails_expected:
                scores["email_recipients_filtered_correct"] = 1.0

        # Subject correctness
        subj_val = subject_line.split(":", 1)[1].strip() if ":" in subject_line else ""
        subj_norm = _normalize_apostrophe(subj_val)
        expected_subj1 = _normalize_apostrophe("Seminar reading: Critical review of Jordan Ellis’s legacy")
        expected_subj2 = _normalize_apostrophe("Seminar reading: Critical review of Jordan Ellis's legacy")
        if subj_norm == expected_subj1 or subj_norm == expected_subj2:
            scores["email_subject_correct"] = 1.0

        # Includes paths to report and metrics
        if "output/report/ellis_critical_review.md" in email_text and "output/structured/ellis_metrics.csv" in email_text:
            scores["email_includes_paths"] = 1.0

        # Body word count 120–180 (tolerate 110–200)
        if body_text:
            wc_body = _word_count(body_text)
            if 110 <= wc_body <= 200:
                scores["email_body_word_count"] = 1.0

        # From line present with Sports Sociology
        if from_line and ("sports sociology" in from_line.lower()):
            scores["email_from_line_present"] = 1.0

        # Scores present numerically in body: must include on_court_score, off_court_score, and overall_score values
        if expected_scores is not None and body_text:
            body_nums = _extract_floats_from_text(body_text)
            # For robustness, also parse percentages accidentally; but we compare with tolerance
            def _contains_value(vals: List[float], target: float, tol: float = 0.01) -> bool:
                return any(abs(v - target) <= tol for v in vals)
            oc_ok = _contains_value(body_nums, expected_scores[0])
            of_ok = _contains_value(body_nums, expected_scores[1])
            ov_ok = _contains_value(body_nums, expected_scores[2])
            if oc_ok and of_ok and ov_ok:
                scores["email_scores_present_numeric"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()