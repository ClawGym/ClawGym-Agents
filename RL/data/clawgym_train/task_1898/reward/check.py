import sys
import json
import csv
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(r) for r in reader]
            return headers, rows
    except Exception:
        return None, None


def _safe_float(s: str) -> Optional[float]:
    if s is None:
        return None
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(s))
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def _contains_all(text: str, tokens: List[str]) -> bool:
    t = text.lower()
    return all(tok.lower() in t for tok in tokens)


def _find_first_block(text: str, start_marker: str, end_marker: Optional[str] = None) -> Optional[str]:
    idx = text.find(start_marker)
    if idx == -1:
        return None
    end_idx = len(text)
    if end_marker:
        nxt = text.find(end_marker, idx + len(start_marker))
        if nxt != -1:
            end_idx = nxt
    return text[idx:end_idx]


def _compute_expected_from_inputs(workspace: Path) -> Dict[str, object]:
    expected = {
        "case_wins_since_2022": None,
        "mgmt4800_avg_last3yrs": None,
        "spring2024_mgmt7990_sections_led": None,
        "current_titles": None,
        "award_2021": None,
        "jom_publications_2023_2024": None,
    }

    # CSV metrics
    course_csv = workspace / "input" / "course_outcomes.csv"
    headers, rows = _load_csv(course_csv)
    if headers and rows is not None:
        # years present in file
        try:
            years_sorted_desc = sorted({int(r.get("year", "0")) for r in rows if str(r.get("year", "")).isdigit()}, reverse=True)
        except Exception:
            years_sorted_desc = []
        years_top3 = set(years_sorted_desc[:3])

        # MGMT 4800 average across last three academic years represented (filter by those years)
        ratings = []
        for r in rows:
            try:
                year = int(r.get("year", "0"))
            except Exception:
                continue
            if r.get("course_code", "").strip() == "MGMT 4800" and year in years_top3:
                val = _safe_float(r.get("avg_rating", ""))
                if val is not None:
                    ratings.append(val)
        if ratings:
            expected["mgmt4800_avg_last3yrs"] = sum(ratings) / len(ratings)

        # Case wins since 2022 for Dr. Allen Amason
        wins = 0
        any_case_field = "case_competition_wins" in headers
        if any_case_field:
            for r in rows:
                try:
                    year = int(r.get("year", "0"))
                except Exception:
                    continue
                if year >= 2022 and r.get("instructor", "").strip() == "Dr. Allen Amason":
                    try:
                        wins += int(str(r.get("case_competition_wins", "0")).strip() or "0")
                    except Exception:
                        pass
            expected["case_wins_since_2022"] = wins

        # Spring 2024 MGMT 7990 sections led by Dr. Allen Amason
        sections = set()
        for r in rows:
            try:
                year = int(r.get("year", "0"))
            except Exception:
                continue
            if (
                r.get("course_code", "").strip() == "MGMT 7990"
                and r.get("term", "").strip() == "Spring"
                and year == 2024
                and r.get("instructor", "").strip() == "Dr. Allen Amason"
            ):
                sections.add(r.get("section", "").strip())
        expected["spring2024_mgmt7990_sections_led"] = len(sections)

    # HTML metrics
    faculty_html_path = workspace / "input" / "faculty_profiles.html"
    html = _read_text(faculty_html_path)
    if html:
        # isolate Dr. Allen C. Amason block
        block = _find_first_block(html, '<h1>Dr. Allen C. Amason</h1>', '<div class="faculty">')
        if block is None:
            block = html  # fallback to entire html
        # titles
        m_titles = re.search(r'<p class="titles">\s*(.*?)\s*</p>', block, re.IGNORECASE | re.DOTALL)
        if m_titles:
            titles = re.sub(r"\s+", " ", m_titles.group(1)).strip()
            expected["current_titles"] = titles
        # awards list
        awards = re.findall(
            r'<li>\s*<span class="year">\s*(\d{4})\s*</span>\s*(.*?)\s*</li>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # find 2021 award text
        award_2021 = None
        for yr, text in awards:
            if yr.strip() == "2021":
                award_2021 = re.sub(r"\s+", " ", text).strip()
                break
        expected["award_2021"] = award_2021

        # publications: count Journal of Management in 2023-2024
        pubs = re.findall(
            r'<li>\s*<span class="year">\s*(\d{4})\s*</span>\s*(.*?)\s*</li>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        jom_count = 0
        for yr, text in pubs:
            try:
                y = int(yr.strip())
            except Exception:
                continue
            if y in (2023, 2024) and "Journal of Management" in text:
                jom_count += 1
        expected["jom_publications_2023_2024"] = jom_count

    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "evidence_summary_file_and_columns": 0.0,
        "evidence_summary_claim_coverage": 0.0,
        "evidence_summary_computed_values_correct": 0.0,
        "evidence_summary_statuses_correct": 0.0,
        "evidence_summary_timeframes_present": 0.0,
        "evidence_summary_titles_and_awards_correct": 0.0,
        "critique_has_executive_summary": 0.0,
        "critique_covers_claims_with_judgments": 0.0,
        "critique_references_sources_and_years": 0.0,
        "critique_proposes_corrections_for_errors": 0.0,
        "critique_concluding_constructive_note": 0.0,
        "email_subject_references_feature": 0.0,
        "email_summarizes_corrections_and_attachment": 0.0,
        "email_tone_appreciative": 0.0,
    }

    # Expected computations
    expected = _compute_expected_from_inputs(workspace)

    # Evidence summary checks
    evidence_path = workspace / "output" / "evidence_summary.csv"
    headers, rows = _load_csv(evidence_path)
    required_cols = [
        "claim_id",
        "claim_text",
        "evidence_source",
        "metric_or_fact",
        "computed_value",
        "timeframe_assessed",
        "status",
        "notes",
    ]
    if headers and rows is not None:
        if all(col in headers for col in required_cols):
            scores["evidence_summary_file_and_columns"] = 1.0

        # Define claim patterns and expectations
        claim_specs = [
            {
                "id": "1",
                "tokens": ["since 2022", "case competitions"],
                "source": "course_outcomes.csv",
                "expected_value": expected.get("case_wins_since_2022"),
                "expected_status": "contradicted",
                "timeframe_tokens": ["since 2022"],
                "value_type": "int",
            },
            {
                "id": "2",
                "tokens": ["strategic management", "averaged", "three academic years"],
                "source": "course_outcomes.csv",
                "expected_value": expected.get("mgmt4800_avg_last3yrs"),
                "expected_status": "contradicted",
                "timeframe_tokens": ["last three"],
                "value_type": "float",
            },
            {
                "id": "3",
                "tokens": ["spring 2024", "mba capstone", "sections"],
                "source": "course_outcomes.csv",
                "expected_value": expected.get("spring2024_mgmt7990_sections_led"),
                "expected_status": "contradicted",
                "timeframe_tokens": ["spring 2024"],
                "value_type": "int",
            },
            {
                "id": "4",
                "tokens": ["dean", "college of business"],
                "source": "faculty_profiles.html",
                "expected_value": expected.get("current_titles"),
                "expected_status": "contradicted",
                "timeframe_tokens": ["current"],
                "value_type": "text",
            },
            {
                "id": "5",
                "tokens": ["2021", "outstanding educator award", "southern management association"],
                "source": "faculty_profiles.html",
                "expected_value": expected.get("award_2021"),
                "expected_status": "contradicted",
                "timeframe_tokens": ["2021"],
                "value_type": "text",
            },
            {
                "id": "6",
                "tokens": ["past two years", "two articles", "journal of management"],
                "source": "faculty_profiles.html",
                "expected_value": expected.get("jom_publications_2023_2024"),
                "expected_status": "contradicted",
                "timeframe_tokens": ["2023", "2024"],
                "value_type": "int",
            },
            {
                "id": "7",
                "tokens": ["directs", "institute for leadership"],
                "source": "faculty_profiles.html",
                "expected_value": expected.get("current_titles"),
                "expected_status": "supported",
                "timeframe_tokens": ["current"],
                "value_type": "text",
            },
        ]

        # Normalize evidence rows
        def normalize_row(r: Dict[str, str]) -> Dict[str, str]:
            return {k: (v if v is not None else "") for k, v in r.items()}

        rows = [normalize_row(r) for r in rows]

        # Coverage: find at least one row per claim using either claim_id match or token match on claim_text
        matched_rows: Dict[str, Dict[str, str]] = {}
        for spec in claim_specs:
            # Try by claim_id
            candidates = [r for r in rows if r.get("claim_id", "").strip() == spec["id"]]
            # If none, try by tokens in claim_text
            if not candidates:
                candidates = [
                    r for r in rows if _contains_all(r.get("claim_text", ""), spec["tokens"])
                ]
            if candidates:
                matched_rows[spec["id"]] = candidates[0]

        coverage_frac = len(matched_rows) / len(claim_specs) if claim_specs else 0.0
        scores["evidence_summary_claim_coverage"] = coverage_frac

        # Computed values correctness
        numeric_claim_ids = {"1", "2", "3", "6"}
        num_correct = 0
        num_total = 0
        for spec in claim_specs:
            cid = spec["id"]
            if cid not in matched_rows:
                continue
            row = matched_rows[cid]
            if cid in numeric_claim_ids:
                num_total += 1
                expected_val = spec["expected_value"]
                cv = row.get("computed_value", "")
                got = _safe_float(cv)
                if expected_val is None or got is None:
                    # cannot verify -> treat as incorrect
                    continue
                # Allow small tolerance for averages
                tol = 0.01 if spec["value_type"] == "float" else 0.0
                if abs(float(expected_val) - float(got)) <= (tol + 1e-9):
                    num_correct += 1
        scores["evidence_summary_computed_values_correct"] = (num_correct / num_total) if num_total > 0 else 0.0

        # Titles/awards/directorship correctness (textual)
        text_checks_total = 0
        text_checks_pass = 0
        for spec in claim_specs:
            cid = spec["id"]
            if cid not in matched_rows:
                continue
            if spec["value_type"] != "text":
                continue
            row = matched_rows[cid]
            text_checks_total += 1
            cv = row.get("computed_value", "")
            if cid == "4":
                # Expect current title string to include 'Department Head' or 'Director, Institute for Leadership', and not 'Dean'
                if cv and ("Department Head" in cv or "Director, Institute for Leadership" in cv):
                    text_checks_pass += 1
            elif cid == "5":
                # Expect Distinguished Service Award in 2021
                if cv and ("Distinguished Service Award" in cv):
                    text_checks_pass += 1
            elif cid == "7":
                if cv and ("Institute for Leadership" in cv or "Director, Institute for Leadership" in cv):
                    text_checks_pass += 1
        scores["evidence_summary_titles_and_awards_correct"] = (text_checks_pass / text_checks_total) if text_checks_total > 0 else 0.0

        # Status correctness
        status_total = 0
        status_pass = 0
        for spec in claim_specs:
            cid = spec["id"]
            if cid not in matched_rows:
                continue
            status_total += 1
            st = matched_rows[cid].get("status", "").strip().lower()
            if st == spec["expected_status"]:
                status_pass += 1
        scores["evidence_summary_statuses_correct"] = (status_pass / status_total) if status_total > 0 else 0.0

        # Timeframe present
        tf_total = 0
        tf_pass = 0
        for spec in claim_specs:
            cid = spec["id"]
            if cid not in matched_rows:
                continue
            tf_total += 1
            tf = matched_rows[cid].get("timeframe_assessed", "").lower()
            # heuristic checks
            ok = False
            if cid == "1":
                ok = ("since 2022" in tf) or ("2022" in tf and ("2023" in tf or "2024" in tf))
            elif cid == "2":
                ok = ("last three" in tf) or (("2022" in tf and "2023" in tf) or ("2023" in tf and "2024" in tf))
            elif cid == "3":
                ok = ("spring 2024" in tf)
            elif cid == "4":
                ok = ("current" in tf)
            elif cid == "5":
                ok = ("2021" in tf)
            elif cid == "6":
                ok = (("2023" in tf and "2024" in tf) or "past two years" in tf)
            elif cid == "7":
                ok = ("current" in tf) or ("ongoing" in tf)
            if ok:
                tf_pass += 1
        scores["evidence_summary_timeframes_present"] = (tf_pass / tf_total) if tf_total > 0 else 0.0

    # Critique report checks
    critique_path = workspace / "output" / "critique_report.md"
    critique = _read_text(critique_path)
    if critique:
        # Executive summary at start
        first_nonempty = ""
        for line in critique.splitlines():
            if line.strip():
                first_nonempty = line.strip()
                break
        if first_nonempty and re.search(r"executive", first_nonempty, flags=re.IGNORECASE):
            scores["critique_has_executive_summary"] = 1.0

        # Define claim phrases and expected statuses
        claim_phrases = {
            "1": ["Since 2022", "case competitions"],
            "2": ["Strategic Management course", "averaged", "three academic years"],
            "3": ["Spring 2024", "MBA capstone", "sections"],
            "4": ["Dean", "College of Business"],
            "5": ["2021", "Outstanding Educator Award", "Southern Management Association"],
            "6": ["past two years", "Journal of Management"],
            "7": ["directs", "Institute for Leadership"],
        }
        expected_status = {
            "1": "contradicted",
            "2": "contradicted",
            "3": "contradicted",
            "4": "contradicted",
            "5": "contradicted",
            "6": "contradicted",
            "7": "supported",
        }

        # Coverage with judgments
        covered = 0
        for cid, tokens in claim_phrases.items():
            pattern_ok = True
            for tok in tokens:
                if re.search(re.escape(tok), critique, flags=re.IGNORECASE) is None:
                    pattern_ok = False
                    break
            if not pattern_ok:
                continue
            # Find first occurrence index of first token to scan around
            m_anchor = re.search(re.escape(tokens[0]), critique, flags=re.IGNORECASE)
            idx = m_anchor.start() if m_anchor else 0
            window = critique[idx: idx + 800]
            if re.search(r"\b(supported|partially supported|contradicted|unclear)\b", window, flags=re.IGNORECASE):
                # Check expected status appears
                if re.search(rf"\b{re.escape(expected_status[cid])}\b", window, flags=re.IGNORECASE):
                    covered += 1
        scores["critique_covers_claims_with_judgments"] = covered / 7.0

        # References to sources and years/fields
        refs_ok = 0
        refs_total = 3
        if "course_outcomes.csv" in critique:
            refs_ok += 1
        if "faculty_profiles.html" in critique:
            refs_ok += 1
        # Presence of specific fields/years references
        if any(s in critique for s in ["MGMT 4800", "MGMT 7990", "2021", "2023", "2024", "Spring 2024"]):
            refs_ok += 1
        scores["critique_references_sources_and_years"] = refs_ok / refs_total

        # Proposes corrected wording for errors (claims contradicted: 1-6)
        corrections = 0
        total_err_claims = 6
        for cid in ["1", "2", "3", "4", "5", "6"]:
            tokens = claim_phrases[cid]
            m_anchor = re.search(re.escape(tokens[0]), critique, flags=re.IGNORECASE)
            if not m_anchor:
                continue
            idx = m_anchor.start()
            window = critique[idx: idx + 1000]
            if re.search(r"\b(proposed|suggested|revised|correction)\b", window, flags=re.IGNORECASE):
                corrections += 1
        scores["critique_proposes_corrections_for_errors"] = corrections / total_err_claims if total_err_claims > 0 else 0.0

        # Concluding constructive note
        tail = critique[-500:] if len(critique) > 500 else critique
        if (re.search(r"Dr\.?\s+Amason", tail) and re.search(r"(leadership|integrity|commitment|contribution|excellence|proud|celebrat)", tail, flags=re.IGNORECASE)):
            scores["critique_concluding_constructive_note"] = 1.0

    # Email checks
    email_path = workspace / "output" / "email_to_editor.txt"
    email_txt = _read_text(email_path)
    if email_txt:
        lines = email_txt.splitlines()
        subject_line = ""
        for line in lines:
            if re.match(r"^\s*subject\s*:", line, flags=re.IGNORECASE):
                subject_line = line
                break
        if subject_line:
            subj = subject_line.split(":", 1)[1] if ":" in subject_line else ""
            if re.search(r"alumni", subj, flags=re.IGNORECASE) and (re.search(r"amason", subj, flags=re.IGNORECASE) or re.search(r"allen", subj, flags=re.IGNORECASE)):
                scores["email_subject_references_feature"] = 1.0

        # Summarizes corrections and references attachment
        bullets = [ln for ln in lines if re.match(r"^\s*[-\*\u2022]\s+", ln)]
        attach_ref = "critique_report.md" in email_txt
        if len(bullets) >= 2 and attach_ref:
            scores["email_summarizes_corrections_and_attachment"] = 1.0

        # Appreciative tone
        if re.search(r"\b(thank|appreciate|grateful|proud)\b", email_txt, flags=re.IGNORECASE):
            scores["email_tone_appreciative"] = 1.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    # Preserve insertion order of keys to match expected grading keys order
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()