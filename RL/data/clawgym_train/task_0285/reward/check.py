import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _format_one_decimal(value: float) -> str:
    return f"{value:.1f}"


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _compute_expected_from_input(input_csv: Path) -> Optional[Dict[str, Dict[str, object]]]:
    rows = _read_csv(input_csv)
    if not rows:
        return None
    row2022 = next((r for r in rows if r.get("Year") == "2022"), None)
    row2023 = next((r for r in rows if r.get("Year") == "2023"), None)
    if not row2022 or not row2023:
        return None

    indicators = [
        ("Mammogram_Rate", "N_Mammogram", "Mammogram uptake (women 50–74)"),
        ("Cervical_Screening_Rate", "N_Cervical", "Cervical cancer screening (Pap or HPV test, women 21–65)"),
        ("HPV_Vaccination_Rate", "N_HPV", "HPV vaccination initiation (girls 13–17)"),
    ]

    expected: Dict[str, Dict[str, object]] = {}
    for key, n_key, preferred_name in indicators:
        r22 = _safe_float(row2022.get(key, ""))
        r23 = _safe_float(row2023.get(key, ""))
        n23 = row2023.get(n_key, "")
        if r22 is None or r23 is None:
            return None
        try:
            n23_int = int(n23)
        except Exception:
            return None
        change = r23 - r22
        change_rounded = float(_format_one_decimal(change))
        direction = "no change"
        if change_rounded > 0:
            direction = "increased"
        elif change_rounded < 0:
            direction = "decreased"
        noteworthy = (abs(change_rounded) >= 1.5) and (n23_int >= 850)
        expected[key] = {
            "Indicator_Key": key,
            "Indicator_Name": preferred_name,
            "Rate_2022": _format_one_decimal(r22),
            "Rate_2023": _format_one_decimal(r23),
            "Change_pp_2022_to_2023": _format_one_decimal(change_rounded),
            "N_2023": str(n23_int),
            "Direction": direction,
            "Noteworthy": "true" if noteworthy else "false",
            "ChangeRoundedFloat": change_rounded,
        }
    return expected


def _parse_trend_summary(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _read_csv(path)
    return rows


def _extract_between_markers(text: str, start_marker: str, end_marker: str) -> Optional[Tuple[str, str, str]]:
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return None
    before = text[: start_idx + len(start_marker)]
    middle = text[start_idx + len(start_marker) : end_idx]
    after = text[end_idx:]
    return before, middle, after


def _get_brief_bullets(middle_text: str) -> List[str]:
    lines = [ln.strip() for ln in middle_text.strip().splitlines()]
    bullets = [ln for ln in lines if ln.startswith("-") or ln.startswith("*")]
    return bullets


def _find_indicator_in_text(text: str, preferred_names: Dict[str, str]) -> Optional[str]:
    for k, name in preferred_names.items():
        if name in text:
            return k
    return None


def _extract_signed_pp_change(text: str) -> Optional[str]:
    # Look for signed pp change in parentheses for brief, or general pp for email
    # General extractor returns the signed number string with one decimal if present
    m = re.search(r"\(([+-]\d+(?:\.\d)?)\s*pp\)", text)
    if m:
        return m.group(1)
    # fallback for email style without parentheses
    m2 = re.search(r"([+-]\d+(?:\.\d)?)\s*pp\b", text)
    if m2:
        return m2.group(1)
    return None


def _extract_direction(text: str) -> Optional[str]:
    for d in ["increased", "decreased", "no change"]:
        if d in text:
            return d
    return None


def _extract_percent_values(text: str) -> List[str]:
    # Return list of decimal numbers (one decimal) that are followed by %
    return re.findall(r"(\d{1,3}\.\d)\s*%", text)


def _extract_n_value(text: str) -> Optional[int]:
    # Match patterns like N_2023: 1085, N=1085, N 1085, N_2023=1085
    m = re.search(r"\bN(?:_?2023)?\s*[:=]?\s*(\d{1,6})\b", text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "trend_summary_exists": 0.0,
        "trend_summary_columns_exact": 0.0,
        "trend_summary_rows_and_keys": 0.0,
        "trend_summary_values_correct": 0.0,
        "trend_summary_directions_and_flags": 0.0,
        "brief_updated_exists": 0.0,
        "brief_structure_preserved": 0.0,
        "brief_bullets_count_and_selection": 0.0,
        "brief_bullets_content_numbers_match": 0.0,
        "email_polished_exists": 0.0,
        "email_word_count_under_120": 0.0,
        "email_two_hyphen_bullets": 0.0,
        "email_bullets_match_noteworthy_changes": 0.0,
        "email_references_updated_brief": 0.0,
        "email_one_sentence_opener": 0.0,
    }

    # Paths
    input_csv = workspace / "input" / "screening_rates.csv"
    input_brief = workspace / "input" / "brief_draft.md"
    output_trend = workspace / "output" / "trend_summary.csv"
    output_brief = workspace / "output" / "updated_brief.md"
    output_email = workspace / "output" / "email_polished.txt"

    expected = _compute_expected_from_input(input_csv)
    preferred_names = {
        "Mammogram_Rate": "Mammogram uptake (women 50–74)",
        "Cervical_Screening_Rate": "Cervical cancer screening (Pap or HPV test, women 21–65)",
        "HPV_Vaccination_Rate": "HPV vaccination initiation (girls 13–17)",
    }

    # A) trend_summary.csv checks
    if output_trend.exists():
        scores["trend_summary_exists"] = 1.0
        parsed = _parse_trend_summary(output_trend)
        if parsed is not None and len(parsed) >= 0:
            # columns exact
            expected_cols = [
                "Indicator_Key",
                "Indicator_Name",
                "Rate_2022",
                "Rate_2023",
                "Change_pp_2022_to_2023",
                "N_2023",
                "Direction",
                "Noteworthy (true/false)",
            ]
            # csv.DictReader fieldnames
            try:
                with output_trend.open(newline="", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    header = next(reader, [])
            except Exception:
                header = []

            if header == expected_cols:
                scores["trend_summary_columns_exact"] = 1.0

            # rows and keys
            keys_present = set()
            if parsed is not None:
                for row in parsed:
                    k = row.get("Indicator_Key", "")
                    if k:
                        keys_present.add(k)
            if keys_present == {"Mammogram_Rate", "Cervical_Screening_Rate", "HPV_Vaccination_Rate"} and len(parsed) == 3:
                scores["trend_summary_rows_and_keys"] = 1.0

            # values correctness
            values_ok = True
            dir_note_ok = True
            if expected is not None and parsed is not None:
                # map by key
                out_map = {r.get("Indicator_Key", ""): r for r in parsed}
                for k, exp in expected.items():
                    r = out_map.get(k)
                    if not r:
                        values_ok = False
                        dir_note_ok = False
                        break
                    # Indicator_Name
                    if r.get("Indicator_Name") != exp["Indicator_Name"]:
                        values_ok = False
                    # Rate_2022 and Rate_2023 exact one decimal as recorded
                    if r.get("Rate_2022") != exp["Rate_2022"]:
                        values_ok = False
                    if r.get("Rate_2023") != exp["Rate_2023"]:
                        values_ok = False
                    # Change rounded one decimal
                    if r.get("Change_pp_2022_to_2023") != exp["Change_pp_2022_to_2023"]:
                        values_ok = False
                    # N_2023
                    if r.get("N_2023") != exp["N_2023"]:
                        values_ok = False
                    # Direction
                    if r.get("Direction") != exp["Direction"]:
                        dir_note_ok = False
                    # Noteworthy string true/false (case-insensitive)
                    out_note = r.get("Noteworthy (true/false)", "")
                    if out_note.lower() != exp["Noteworthy"]:
                        dir_note_ok = False
            else:
                values_ok = False
                dir_note_ok = False

            if values_ok:
                scores["trend_summary_values_correct"] = 1.0
            if dir_note_ok:
                scores["trend_summary_directions_and_flags"] = 1.0

    # B) updated_brief.md checks
    if output_brief.exists():
        scores["brief_updated_exists"] = 1.0
        out_text = _read_text(output_brief) or ""
        in_text = _read_text(input_brief) or ""
        markers = ("<!-- START KEY TRENDS -->", "<!-- END KEY TRENDS -->")
        ext_out = _extract_between_markers(out_text, markers[0], markers[1])
        ext_in = _extract_between_markers(in_text, markers[0], markers[1])
        if ext_out and ext_in:
            before_out, middle_out, after_out = ext_out
            before_in, _, after_in = ext_in
            if before_out == before_in and after_out == after_in:
                scores["brief_structure_preserved"] = 1.0

            # bullet checks
            bullets = _get_brief_bullets(middle_out)
            # Expected noteworthy ordering (by absolute change descending)
            noteworthy_sorted: List[str] = []
            if expected:
                sorted_items = sorted(
                    expected.items(),
                    key=lambda kv: abs(kv[1]["ChangeRoundedFloat"]),
                    reverse=True,
                )
                for k, v in sorted_items:
                    if v["Noteworthy"] == "true":
                        noteworthy_sorted.append(k)

            # Count and selection check
            sel_ok = False
            if expected is not None:
                max_bullets = min(2, len(noteworthy_sorted))
                if len(bullets) <= 2 and len(bullets) == max_bullets:
                    # ensure correct selected indicators in order
                    order_ok = True
                    for i, b in enumerate(bullets):
                        ind = _find_indicator_in_text(b, preferred_names)
                        if ind is None:
                            order_ok = False
                            break
                        if i < len(noteworthy_sorted):
                            if ind != noteworthy_sorted[i]:
                                order_ok = False
                                break
                    sel_ok = order_ok
            if sel_ok:
                scores["brief_bullets_count_and_selection"] = 1.0

            # Content numbers check
            content_ok = True
            if expected is not None and sel_ok:
                for i, b in enumerate(bullets):
                    ind = _find_indicator_in_text(b, preferred_names)
                    if ind is None:
                        content_ok = False
                        break
                    exp_row = expected[ind]
                    # direction
                    dir_word = _extract_direction(b)
                    if dir_word != exp_row["Direction"]:
                        content_ok = False
                    # signed pp change in parentheses, one decimal, must match exactly
                    ch = _extract_signed_pp_change(b)
                    if ch is None:
                        content_ok = False
                    else:
                        # must have exactly one decimal place
                        if not re.match(r"^[+-]\d+\.\d$", ch):
                            content_ok = False
                        if ch != exp_row["Change_pp_2022_to_2023"] or (ch[0] != "-" and not ch.startswith("+")):
                            # Ensure exact match including sign. If positive must include +
                            if ch != exp_row["Change_pp_2022_to_2023"]:
                                content_ok = False
                    # from-to percentages with one decimal: first must be 2022, second 2023
                    percents = _extract_percent_values(b)
                    if len(percents) < 2:
                        content_ok = False
                    else:
                        if percents[0] != exp_row["Rate_2022"] or percents[1] != exp_row["Rate_2023"]:
                            content_ok = False
                    # N_2023 present and correct
                    n_val = _extract_n_value(b)
                    try:
                        n_expected = int(str(exp_row["N_2023"]))
                    except Exception:
                        n_expected = None
                    if n_val is None or n_expected is None or n_val != n_expected:
                        content_ok = False
            else:
                content_ok = False

            if content_ok:
                scores["brief_bullets_content_numbers_match"] = 1.0

    # C) email_polished.txt checks
    if output_email.exists():
        scores["email_polished_exists"] = 1.0
        email_txt = _read_text(output_email) or ""
        # word count
        words = re.findall(r"\b\w+\b", email_txt)
        if len(words) <= 120:
            scores["email_word_count_under_120"] = 1.0
        # reference to updated brief
        if "output/updated_brief.md" in email_txt:
            scores["email_references_updated_brief"] = 1.0
        # bullets
        lines = [ln.rstrip("\n") for ln in email_txt.splitlines()]
        bullet_lines = [ln for ln in lines if ln.strip().startswith("- ")]
        if len(bullet_lines) == 2:
            scores["email_two_hyphen_bullets"] = 1.0

        # opener one sentence: text before first bullet should contain exactly one sentence end (.!?)
        pre_bullets_text = ""
        for ln in lines:
            if ln.strip().startswith("- "):
                break
            pre_bullets_text += (ln + " ")
        # remove extra spaces
        pre_bullets_text = pre_bullets_text.strip()
        if pre_bullets_text:
            # Count sentence terminators . ! ?
            # Ignore commas and greetings; just ensure exactly one sentence end marker appears
            sent_count = len(re.findall(r"[\.!\?]", pre_bullets_text))
            if sent_count == 1:
                scores["email_one_sentence_opener"] = 1.0

        # bullets content against noteworthy changes
        bullets_ok = False
        if expected is not None and len(bullet_lines) == 2:
            # Identify top noteworthy indicators (up to 2)
            top_noteworthy = [k for k, v in sorted(expected.items(), key=lambda kv: abs(kv[1]["ChangeRoundedFloat"]), reverse=True) if v["Noteworthy"] == "true"][:2]
            if len(top_noteworthy) == 2:
                both_match = True
                seen_inds = set()
                for b in bullet_lines:
                    ind = _find_indicator_in_text(b, preferred_names)
                    if ind is None or ind not in top_noteworthy:
                        both_match = False
                        break
                    seen_inds.add(ind)
                    # Must include signed pp number that matches expected change rounded (one decimal)
                    ch = _extract_signed_pp_change(b)
                    if ch is None:
                        both_match = False
                        break
                    # enforce one decimal place
                    if not re.match(r"^[+-]\d+\.\d$", ch):
                        both_match = False
                        break
                    if ch != expected[ind]["Change_pp_2022_to_2023"]:
                        both_match = False
                        break
                if both_match and seen_inds == set(top_noteworthy):
                    bullets_ok = True
        if bullets_ok:
            scores["email_bullets_match_noteworthy_changes"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()