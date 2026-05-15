import json
import re
import sys
import subprocess
from pathlib import Path
from typing import Optional, Tuple


def read_text_file(path: Path) -> Optional[str]:
    try:
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def first_nonempty_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return None


def last_nonempty_line(text: str) -> Optional[str]:
    lines = text.splitlines()
    for line in reversed(lines):
        s = line.strip()
        if s:
            return s
    return None


def has_subject_line(text: str) -> bool:
    line = first_nonempty_line(text or "")
    if not line:
        return False
    if not line.lower().startswith("subject:"):
        return False
    # Ensure non-empty subject after colon
    after = line.split(":", 1)[1].strip() if ":" in line else ""
    return len(after) > 0


def contains_ci(text: str, needle: str) -> bool:
    return needle.lower() in (text or "").lower()


def regex_search_ci(pattern: str, text: str) -> bool:
    return re.search(pattern, text or "", flags=re.IGNORECASE) is not None


def count_memorable_support_references(text: str) -> int:
    t = (text or "").lower()

    # Reference 1: "Dr. Patel called on Sunday to check in after discharge."
    ref_call_discharge = ("sunday" in t) and ("discharge" in t) and (
        ("called" in t) or ("call" in t) or ("check in" in t)
    )

    # Reference 2: "Nurse Maria built a simple pain scale chart for Leo."
    ref_pain_scale_chart = ("pain scale" in t) and (
        ("chart" in t) or ("built" in t) or ("made" in t) or ("created" in t) or ("drew" in t) or ("diagram" in t)
    )

    # Reference 3: "The team cheered Leo during his first hallway lap."
    ref_cheered_hallway_lap = (re.search(r"\bcheer\w*\b", t) is not None) and ("hallway" in t) and ("lap" in t)

    return sum([1 if ref_call_discharge else 0,
                1 if ref_pain_scale_chart else 0,
                1 if ref_cheered_hallway_lap else 0])


def run_spanish_lint(workspace: Path, spanish_path: Path, linter_path: Path) -> Tuple[bool, Optional[str]]:
    if not linter_path.exists() or not linter_path.is_file():
        return (False, None)
    if not spanish_path.exists() or not spanish_path.is_file():
        # We can still run the linter; it will error and produce output,
        # but the task requires using the Spanish file. If absent, treat as failure.
        return (False, None)
    try:
        proc = subprocess.run(
            [sys.executable, str(linter_path), str(spanish_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(workspace),
            timeout=10,
        )
        output = proc.stdout
        # Even if return code non-zero, we evaluate stdout for WARNINGS
        return (True, output)
    except Exception:
        return (False, None)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    outputs_dir = workspace / "outputs"
    input_dir = workspace / "input"

    english_path = outputs_dir / "email_thankyou_en.txt"
    spanish_path = outputs_dir / "email_thankyou_es.txt"
    runclub_path = outputs_dir / "message_runclub.txt"
    spanish_lint_log_path = outputs_dir / "spanish_lint.log"

    visit_summary_path = input_dir / "visit_summary.txt"
    run_club_notes_path = input_dir / "run_club_notes.md"
    spanish_linter_path = input_dir / "spanish_lint.py"

    en_text = read_text_file(english_path)
    es_text = read_text_file(spanish_path)
    rc_text = read_text_file(runclub_path)
    lint_log_text = read_text_file(spanish_lint_log_path)

    # Load input details (informative; checks mostly rely on explicit requirements)
    visit_text = read_text_file(visit_summary_path)
    run_notes_text = read_text_file(run_club_notes_path)

    scores = {
        # English email checks
        "english_file_exists": 0.0,
        "english_subject_line_present": 0.0,
        "english_mentions_required_names": 0.0,
        "english_mentions_6_west": 0.0,
        "english_references_memorable_support": 0.0,
        "english_mentions_riverfront_training": 0.0,
        "english_mentions_leo_run_walks": 0.0,
        "english_asks_drop_off_card_next_week": 0.0,
        "english_thanks_6_west_team": 0.0,
        # Spanish email checks
        "spanish_file_exists": 0.0,
        "spanish_has_formal_greeting": 0.0,
        "spanish_includes_equipo_de_pediatria": 0.0,
        "spanish_avoids_informal_pronouns": 0.0,
        "spanish_mentions_names_and_ward": 0.0,
        "spanish_mentions_riverfront_10k": 0.0,
        "spanish_contains_gratitude": 0.0,
        "spanish_uses_formal_usted_tone": 0.0,
        "spanish_lint_log_exists": 0.0,
        "spanish_lint_log_clean": 0.0,
        "spanish_lint_recomputed_clean": 0.0,
        "spanish_lint_log_matches_tool": 0.0,
        # Run club message checks
        "runclub_file_exists": 0.0,
        "runclub_contains_date_time_location": 0.0,
        "runclub_contains_route_details": 0.0,
        "runclub_contains_pace": 0.0,
        "runclub_mentions_cause": 0.0,
        "runclub_mentions_gratitude_and_link_later": 0.0,
        "runclub_does_not_include_link": 0.0,
    }

    # English checks
    if en_text is not None and en_text.strip():
        scores["english_file_exists"] = 1.0
        if has_subject_line(en_text):
            scores["english_subject_line_present"] = 1.0

        en_lower = en_text.lower()

        # Names
        if "dr. a. patel" in en_lower and "nurse maria" in en_lower:
            scores["english_mentions_required_names"] = 1.0

        # 6 West
        if "6 west" in en_lower:
            scores["english_mentions_6_west"] = 1.0

        # Memorable support references: require >= 2 references
        ref_count = count_memorable_support_references(en_text)
        if ref_count >= 2:
            scores["english_references_memorable_support"] = 1.0

        # Riverfront 10K training mention
        if ("riverfront 10k" in en_lower) and (re.search(r"\btrain\w*\b", en_lower) is not None):
            scores["english_mentions_riverfront_training"] = 1.0

        # Leo run-walks in the park
        if ("leo" in en_lower) and ("run" in en_lower) and ("walk" in en_lower) and ("park" in en_lower):
            scores["english_mentions_leo_run_walks"] = 1.0

        # Ask if it's okay to drop off a handwritten thank-you card next week
        has_card_phrase = ("thank-you card" in en_lower) or ("thank you card" in en_lower)
        if ("drop off" in en_lower) and ("handwritten" in en_lower) and has_card_phrase and ("next week" in en_lower):
            scores["english_asks_drop_off_card_next_week"] = 1.0

        # Thank the "6 West" team
        if ("6 west" in en_lower) and ("team" in en_lower) and (re.search(r"\bthank\w*\b", en_lower) is not None):
            scores["english_thanks_6_west_team"] = 1.0

    # Spanish checks
    if es_text is not None and es_text.strip():
        scores["spanish_file_exists"] = 1.0
        es_lower = es_text.lower()

        # Greeting with "Estimado/Estimada"
        if re.search(r"(?i)estimad[oa]", es_text) is not None:
            scores["spanish_has_formal_greeting"] = 1.0

        # Include phrase "equipo de pediatría"
        if re.search(r"(?i)equipo de pediatría", es_text) is not None:
            scores["spanish_includes_equipo_de_pediatria"] = 1.0

        # Avoid informal pronouns
        if re.search(r"(?i)\b(tu|tú|vos)\b", es_text) is None:
            scores["spanish_avoids_informal_pronouns"] = 1.0

        # Mentions names and ward
        if ("patel" in es_lower) and ("maria" in es_lower) and ("6 west" in es_lower):
            scores["spanish_mentions_names_and_ward"] = 1.0

        # Mentions Riverfront 10K (faithful translation should preserve this string)
        if "riverfront 10k" in es_lower:
            scores["spanish_mentions_riverfront_10k"] = 1.0

        # Contains explicit gratitude
        if re.search(r"(?i)\b(gracias|agradezco|agradecimiento|agradecidos?)\b", es_text) is not None:
            scores["spanish_contains_gratitude"] = 1.0

        # Uses usted/ustedes tone (explicitly present)
        if re.search(r"(?i)\b(usted|ustedes)\b", es_text) is not None:
            scores["spanish_uses_formal_usted_tone"] = 1.0

    # Spanish linter log checks
    if lint_log_text is not None and lint_log_text.strip():
        scores["spanish_lint_log_exists"] = 1.0
        last_line = last_nonempty_line(lint_log_text) or ""
        if last_line.strip() == "WARNINGS: 0":
            scores["spanish_lint_log_clean"] = 1.0

    # Re-run linter and compare
    lint_success, live_output = run_spanish_lint(workspace, spanish_path, spanish_linter_path)
    if lint_success and live_output is not None:
        live_last = (last_nonempty_line(live_output) or "").strip()
        if live_last == "WARNINGS: 0":
            scores["spanish_lint_recomputed_clean"] = 1.0
        # Compare saved log to live output
        if lint_log_text is not None:
            # Normalize endings for comparison
            saved = lint_log_text.replace("\r\n", "\n").strip()
            live = live_output.replace("\r\n", "\n").strip()
            if saved == live:
                scores["spanish_lint_log_matches_tool"] = 1.0

    # Run club message checks
    if rc_text is not None and rc_text.strip():
        scores["runclub_file_exists"] = 1.0
        rc_lower = rc_text.lower()

        # Date/time/location
        has_date = "2025-04-06" in rc_text
        has_time = "8:00 AM".lower() in rc_lower
        has_location = ("riverside park" in rc_lower) and ("north gate" in rc_lower)
        if has_date and has_time and has_location:
            scores["runclub_contains_date_time_location"] = 1.0

        # Route details: 6 miles easy along the river loop; optional strides
        has_distance = ("6 miles" in rc_lower) or (("6" in rc_lower) and ("mile" in rc_lower))
        has_river_loop = ("river" in rc_lower) and ("loop" in rc_lower)
        has_strides = ("strides" in rc_lower)
        if has_distance and has_river_loop and has_strides:
            scores["runclub_contains_route_details"] = 1.0

        # Pace details: Conversational (9:30–11:00 min/mile)
        has_pace_numbers = ("9:30" in rc_text) and ("11:00" in rc_text)
        has_min_mile = ("min/mile" in rc_lower) or (("min" in rc_lower) and ("mile" in rc_lower))
        if has_pace_numbers and has_min_mile:
            scores["runclub_contains_pace"] = 1.0

        # Cause: Benefiting City Children's Hospital pediatric surgery unit
        has_cause_hospital = ("city children's hospital" in rc_lower)
        has_cause_unit = ("pediatric surgery" in rc_lower)
        if has_cause_hospital and has_cause_unit:
            scores["runclub_mentions_cause"] = 1.0

        # Gratitude to hospital team and mention fundraiser link later
        mentions_gratitude = (re.search(r"\b(grateful|gratitude|thanks|thank you)\b", rc_lower) is not None) or ("thank" in rc_lower)
        mentions_hospital = ("hospital" in rc_lower)
        link_later = ("fundraiser" in rc_lower) and ("link" in rc_lower) and (
            ("later" in rc_lower) or ("pending" in rc_lower) or ("share" in rc_lower)
        )
        if mentions_gratitude and mentions_hospital and link_later:
            scores["runclub_mentions_gratitude_and_link_later"] = 1.0

        # Ensure no actual URL present
        has_url = ("http://" in rc_lower) or ("https://" in rc_lower) or ("www." in rc_lower)
        scores["runclub_does_not_include_link"] = 0.0 if has_url else 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()