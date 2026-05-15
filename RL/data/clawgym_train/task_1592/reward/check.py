import json
import sys
import subprocess
from pathlib import Path
from typing import Optional, Tuple


def _safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _count_bullets(text: str) -> int:
    count = 0
    for line in text.splitlines():
        ls = line.lstrip()
        if ls.startswith("- ") or ls.startswith("* "):
            count += 1
    return count


def _find_lines_starting_with(text: str, prefix: str, case_sensitive: bool = True) -> list:
    matches = []
    for line in text.splitlines():
        check = line
        pref = prefix
        if not case_sensitive:
            check = line.lower()
            pref = prefix.lower()
        if check.startswith(pref):
            matches.append(line)
    return matches


def _run_checker(workspace: Path) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    script = workspace / "tools" / "check_terms.py"
    glossary = workspace / "input" / "glossary.csv"
    handout = workspace / "output" / "handout_es.md"
    if not script.exists() or not glossary.exists() or not handout.exists():
        return None, None, None
    try:
        res = subprocess.run(
            [sys.executable, str(script), str(glossary), str(handout)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return res.returncode, res.stdout, res.stderr
    except Exception:
        return None, None, None


def _contains_no_peanut_terms(text: str) -> bool:
    t = text.lower()
    # Cover English and Spanish terms (with and without accents)
    forbidden = [
        "peanut",
        "peanuts",
        "cacahu",  # covers cacahuate/cacahuetes
        "mani",    # covers maní (without accent)
        "maní",
    ]
    return not any(term in t for term in forbidden)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "handout_es_exists": 0.0,
        "sustainability_line_present_and_single": 0.0,
        "sustainability_line_one_sentence": 0.0,
        "handout_bullet_count_matches": 0.0,
        "checker_passes_on_handout": 0.0,
        "check_report_exists_and_success": 0.0,
        "check_report_matches_current_run": 0.0,
        "email_exists": 0.0,
        "email_greeting_by_name": 0.0,
        "email_bilingual_order_and_emphasis": 0.0,
        "email_exact_three_bullets": 0.0,
        "email_mentions_attachment": 0.0,
        "email_tailored_to_profile": 0.0,
        "email_avoids_peanut_terms": 0.0,
    }

    # Load inputs
    handout_en = _safe_read_text(workspace / "input" / "handout_en.md")
    glossary_csv = _safe_read_text(workspace / "input" / "glossary.csv")
    client = _safe_load_json(workspace / "input" / "client_profile.json")

    # Check handout_es.md
    handout_es_path = workspace / "output" / "handout_es.md"
    handout_es_text = _safe_read_text(handout_es_path)
    if handout_es_text is not None and handout_es_text.strip():
        scores["handout_es_exists"] = 1.0

        # Sustainability line present exactly once, case-sensitive
        lines = _find_lines_starting_with(handout_es_text, "Nota de sostenibilidad:", case_sensitive=True)
        if len(lines) == 1:
            scores["sustainability_line_present_and_single"] = 1.0
            # One-sentence summary check
            content = lines[0][len("Nota de sostenibilidad:"):].strip()
            if content:
                # Count sentence-ending punctuation
                punct_count = sum(content.count(ch) for ch in ".!?")
                # Require at most one sentence-ending punctuation and some length
                if punct_count <= 1 and len(content) >= 5:
                    scores["sustainability_line_one_sentence"] = 1.0

        # Bullet count matches expected (5 + 4 = 9)
        bullet_count = _count_bullets(handout_es_text)
        if bullet_count == 9:
            scores["handout_bullet_count_matches"] = 1.0

        # Run checker
        rc, out, err = _run_checker(workspace)
        if rc == 0 and out and "OK All checks passed for glossary terms and required sustainability line." in out:
            scores["checker_passes_on_handout"] = 1.0

        # Check report file
        report_path = workspace / "output" / "check_report.txt"
        report_text = _safe_read_text(report_path)
        if report_text is not None and report_text.strip():
            # Must contain no lines starting with "ERROR"
            has_error_line = any(line.strip().startswith("ERROR") for line in report_text.splitlines())
            # Should be the stdout from the last successful run: exact success message
            expected_success = "OK All checks passed for glossary terms and required sustainability line."
            success_in_report = report_text.strip() == expected_success
            if not has_error_line and success_in_report:
                scores["check_report_exists_and_success"] = 1.0

            # If we could run checker now, the report should match current stdout exactly
            if rc == 0 and out is not None:
                if report_text.strip() == out.strip():
                    scores["check_report_matches_current_run"] = 1.0

    # Email checks
    email_path = workspace / "output" / "email_to_client.txt"
    email_text = _safe_read_text(email_path)
    if email_text is not None and email_text.strip():
        scores["email_exists"] = 1.0

        # Greet client by name in the first non-empty line
        first_nonempty = None
        for line in email_text.splitlines():
            if line.strip():
                first_nonempty = line
                break
        name_ok = False
        if first_nonempty is not None and client is not None:
            name = client.get("name", "")
            if name:
                # Case-insensitive containment of both first and last name parts if possible
                nm = name.lower()
                parts = [p for p in nm.split() if p]
                first_lower = first_nonempty.lower()
                # Require full name occurrence or both parts present
                if nm in first_lower:
                    name_ok = True
                elif len(parts) >= 2 and (parts[0] in first_lower and parts[-1] in first_lower):
                    name_ok = True
        if name_ok:
            scores["email_greeting_by_name"] = 1.0

        # Exactly three bullet points
        email_bullets = _count_bullets(email_text)
        if email_bullets == 3:
            scores["email_exact_three_bullets"] = 1.0

        # Mentions attachment
        et_lower = email_text.lower()
        if ("adjunt" in et_lower) or ("attach" in et_lower):
            scores["email_mentions_attachment"] = 1.0

        # Bilingual order and emphasis: Spanish (plato equilibrado, sostenible) before English (balanced plate, sustainable)
        etl = email_text.lower()
        pos_es_plate = etl.find("plato equilibrado")
        pos_en_plate = etl.find("balanced plate")
        pos_es_sust = etl.find("sostenible")
        pos_en_sust = etl.find("sustainable")
        if (pos_es_plate >= 0 and pos_en_plate >= 0 and pos_es_sust >= 0 and pos_en_sust >= 0 and
                pos_es_plate < pos_en_plate and pos_es_sust < pos_en_sust):
            scores["email_bilingual_order_and_emphasis"] = 1.0

        # Tailored to profile: vegetarian/lacto-ovo, quick/time, budget/moderate, allergy mention
        tailored_hits = 0
        # Vegetarian pattern
        if ("vegetar" in etl) or ("lacto-ovo" in etl) or ("vegetarian" in etl):
            tailored_hits += 1
        # Time constraints quick prep
        if ("rápid" in etl) or ("quick" in etl) or ("tiempo" in etl) or ("prep" in etl):
            tailored_hits += 1
        # Budget moderate
        if ("presupuesto" in etl) or ("budget" in etl) or ("económ" in etl) or ("moderat" in etl):
            tailored_hits += 1
        # Allergy mention
        if ("alerg" in etl) or ("allerg" in etl):
            tailored_hits += 1
        if tailored_hits == 4:
            scores["email_tailored_to_profile"] = 1.0

        # Avoid recommending peanuts: ensure no peanut terms present at all
        if _contains_no_peanut_terms(email_text):
            scores["email_avoids_peanut_terms"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()