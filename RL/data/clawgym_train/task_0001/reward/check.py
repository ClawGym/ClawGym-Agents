import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_safe(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = []
            for row in reader:
                # Normalize keys by ensuring headers presence
                rows.append({k: row.get(k, "") for k in headers})
            return headers, rows
    except Exception:
        return None, None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s.strip())
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s.strip())
    except Exception:
        return None


def _parse_date_yyyy_mm_dd(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _compute_expected_from_input(input_csv_path: Path) -> Optional[Dict]:
    headers, rows = _load_csv_safe(input_csv_path)
    if headers is None or rows is None:
        return None

    # Filter criteria
    filtered = []
    for row in rows:
        degree_level = row.get("degree_level", "")
        program_name = row.get("program_name", "")
        language = row.get("language", "")
        country = row.get("country", "")
        tuition = _parse_float(row.get("tuition_usd", ""))
        lab_hours = _parse_float(row.get("lab_hours_per_week", ""))
        research_project = row.get("research_project", "")
        scholarship_available = row.get("scholarship_available", "")
        deadline = _parse_date_yyyy_mm_dd(row.get("deadline", ""))
        gpa_min = _parse_float(row.get("gpa_min", ""))
        ielts_min = _parse_float(row.get("ielts_min", ""))

        if degree_level != "BSc":
            continue
        if "biochem" not in program_name.lower():
            continue
        if language != "English":
            continue
        if country == "Egypt":
            continue
        if tuition is None or tuition > 10000:
            continue
        if deadline is None or deadline < _parse_date_yyyy_mm_dd("2025-03-01"):
            continue
        if gpa_min is None or gpa_min > 3.6:
            continue
        if ielts_min is None or ielts_min > 6.5:
            continue
        if research_project != "yes":
            continue

        # Compute rank_score
        lab_component = lab_hours if lab_hours is not None else 0.0
        tuition_component = max(0.0, (10000.0 - (tuition if tuition is not None else 0.0)) / 1000.0)
        scholarship_component = 5.0 if scholarship_available == "yes" else 0.0
        research_component = 3.0 if research_project == "yes" else 0.0
        deadline_component = 2.0 if (deadline is not None and deadline >= _parse_date_yyyy_mm_dd("2025-05-01")) else 0.0
        rank_score = lab_component + tuition_component + scholarship_component + research_component + deadline_component

        filtered.append((row, rank_score))

    # Sort by rank_score desc, tuition_usd asc, university asc
    def sort_key(item):
        row, rank = item
        tuition_val = _parse_float(row.get("tuition_usd", "")) or float("inf")
        university = row.get("university", "")
        return (-rank, tuition_val, university)

    filtered_sorted = sorted(filtered, key=sort_key)

    expected_ids_in_order = [str(item[0].get("id", "")).strip() for item in filtered_sorted]
    expected_ids_set = set(expected_ids_in_order)
    expected_rank_by_id = {str(item[0].get("id", "")).strip(): item[1] for item in filtered_sorted}
    expected_university_by_id = {str(item[0].get("id", "")).strip(): item[0].get("university", "") for item in filtered_sorted}

    # Expected top 3 university names
    top3_universities = [item[0].get("university", "") for item in filtered_sorted[:3]]

    return {
        "headers": headers,
        "rows": rows,
        "filtered_sorted": filtered_sorted,
        "expected_ids_in_order": expected_ids_in_order,
        "expected_ids_set": expected_ids_set,
        "expected_rank_by_id": expected_rank_by_id,
        "top3_universities": top3_universities,
        "expected_university_by_id": expected_university_by_id,
    }


def _sentence_split(text: str) -> List[str]:
    # Split on ., !, ? preserving simple sentence boundaries
    # Newlines are treated as whitespace
    simplified = re.sub(r'\s+', ' ', text.strip())
    if not simplified:
        return []
    sentences = re.split(r'(?<=[.!?])\s+', simplified)
    # Remove empty
    return [s for s in sentences if s.strip()]


def _paragraph_blocks(text: str) -> List[str]:
    # Split into paragraphs separated by one or more blank lines
    lines = text.splitlines()
    paragraphs = []
    current = []
    for line in lines:
        if line.strip() == "":
            if current:
                paragraphs.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append("\n".join(current))
    return [p for p in paragraphs if p.strip() != ""]


def _word_count(text: str) -> int:
    tokens = re.findall(r"\b[\w/&'-]+\b", text)
    return len(tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "filtered_csv_present_and_parseable": 0.0,
        "output_columns_requirements": 0.0,
        "original_fields_unchanged": 0.0,
        "filtered_contains_expected_rows": 0.0,
        "rank_score_is_numeric": 0.0,
        "rank_score_values_correct": 0.0,
        "filtered_sorted_correctly": 0.0,
        "top3_present_single_line": 0.0,
        "top3_names_expected": 0.0,
        "top3_matches_output_csv": 0.0,
        "revised_email_present": 0.0,
        "email_single_paragraph": 0.0,
        "email_under_160_words": 0.0,
        "email_mentions_name": 0.0,
        "email_mentions_origin_phrase": 0.0,
        "email_mentions_gpa": 0.0,
        "email_mentions_ielts": 0.0,
        "email_mentions_fall_2025": 0.0,
        "email_mentions_budget_phrase": 0.0,
        "email_mentions_biochem_research": 0.0,
        "email_includes_top3_universities_sentence": 0.0,
        "email_avoids_slang_apologies": 0.0,
    }

    input_csv_path = workspace / "input" / "programs.csv"
    expected = _compute_expected_from_input(input_csv_path)
    if expected is None:
        # Without input, we cannot compute expected artifacts; keep related scores at 0.0
        expected_ids_set = set()
        expected_ids_in_order = []
        expected_rank_by_id = {}
        expected_top3 = []
        expected_headers = []
        original_rows_by_id = {}
    else:
        expected_ids_set = expected["expected_ids_set"]
        expected_ids_in_order = expected["expected_ids_in_order"]
        expected_rank_by_id = expected["expected_rank_by_id"]
        expected_top3 = expected["top3_universities"]
        expected_headers = expected["headers"]
        original_rows_by_id = {str(r.get("id", "")).strip(): r for r in expected["rows"]}

    # Check filtered_ranked_programs.csv
    output_csv_path = workspace / "output" / "filtered_ranked_programs.csv"
    out_headers, out_rows = _load_csv_safe(output_csv_path)
    if out_headers is not None and out_rows is not None:
        scores["filtered_csv_present_and_parseable"] = 1.0

        # Columns requirement: all original columns plus rank_score
        has_all_original = False
        has_rank_score = "rank_score" in (out_headers or [])
        if expected is not None:
            if all(col in out_headers for col in expected_headers) and has_rank_score:
                has_all_original = True
        else:
            # Without expected headers, minimally require rank_score
            has_all_original = has_rank_score
        scores["output_columns_requirements"] = 1.0 if has_all_original else 0.0

        # Check id set matches expected and sorting
        out_ids_in_order = [str(r.get("id", "")).strip() for r in out_rows]
        out_ids_set = set(out_ids_in_order)

        if expected is not None and out_ids_set == expected_ids_set:
            scores["filtered_contains_expected_rows"] = 1.0
        else:
            scores["filtered_contains_expected_rows"] = 0.0

        # Check original fields unchanged for rows available
        data_integrity_ok = True
        if expected is not None:
            for r in out_rows:
                rid = str(r.get("id", "")).strip()
                if rid in original_rows_by_id:
                    orig = original_rows_by_id[rid]
                    for col in expected_headers:
                        if r.get(col, "") != orig.get(col, ""):
                            data_integrity_ok = False
                            break
                    if not data_integrity_ok:
                        break
                else:
                    # unexpected id exists; integrity fails
                    data_integrity_ok = False
                    break
        else:
            data_integrity_ok = False
        scores["original_fields_unchanged"] = 1.0 if data_integrity_ok else 0.0

        # rank_score numeric and correctness
        rank_numeric_count = 0
        total_count = len(out_rows)
        rank_correct_count = 0
        if total_count > 0:
            for r in out_rows:
                val = r.get("rank_score", "")
                f = _parse_float(val)
                if f is not None:
                    rank_numeric_count += 1
                # Check correctness if expected available and id within expected set
                rid = str(r.get("id", "")).strip()
                if expected is not None and rid in expected_rank_by_id:
                    exp = expected_rank_by_id[rid]
                    if f is not None and abs(f - exp) <= 1e-6:
                        rank_correct_count += 1
            # Numeric proportion across all rows
            scores["rank_score_is_numeric"] = float(rank_numeric_count) / float(total_count)
            if expected is not None:
                # Correctness proportion across expected rows only
                expected_rows_in_output = [r for r in out_rows if str(r.get("id", "")).strip() in expected_ids_set]
                denom = len(expected_rows_in_output)
                if denom > 0:
                    scores["rank_score_values_correct"] = float(
                        sum(
                            1
                            for r in expected_rows_in_output
                            if _parse_float(r.get("rank_score", "")) is not None
                            and abs(_parse_float(r.get("rank_score", "")) - expected_rank_by_id[str(r.get("id", "")).strip()]) <= 1e-6
                        )
                    ) / float(denom)
                else:
                    scores["rank_score_values_correct"] = 0.0
            else:
                scores["rank_score_values_correct"] = 0.0
        else:
            scores["rank_score_is_numeric"] = 0.0
            scores["rank_score_values_correct"] = 0.0

        # Sorting correctness
        if expected is not None:
            scores["filtered_sorted_correctly"] = 1.0 if out_ids_in_order == expected_ids_in_order else 0.0
        else:
            scores["filtered_sorted_correctly"] = 0.0
    else:
        # CSV missing or invalid: leave all related zeros
        pass

    # Check top3_university_names.txt
    top3_path = workspace / "output" / "top3_university_names.txt"
    top3_text = _read_text_safe(top3_path)
    top3_present_single_line = 0.0
    top3_names_expected = 0.0
    top3_matches_output_csv = 0.0
    if top3_text is not None:
        # Check single line (after stripping surrounding whitespace)
        stripped = top3_text.strip()
        if stripped != "" and "\n" not in stripped and "\r" not in stripped:
            top3_present_single_line = 1.0
        # Parse names by semicolon
        parts = [p.strip() for p in stripped.split(";") if p.strip() != ""]
        if len(parts) == 3:
            if expected is not None:
                if parts == expected_top3:
                    top3_names_expected = 1.0
        # Cross-check with CSV output order if available
        if out_rows is not None and len(out_rows) >= 3:
            out_first3 = [out_rows[0].get("university", ""), out_rows[1].get("university", ""), out_rows[2].get("university", "")]
            if parts == out_first3:
                top3_matches_output_csv = 1.0

    scores["top3_present_single_line"] = top3_present_single_line
    scores["top3_names_expected"] = top3_names_expected
    scores["top3_matches_output_csv"] = top3_matches_output_csv

    # Check revised_email.txt
    email_path = workspace / "output" / "revised_email.txt"
    email_text = _read_text_safe(email_path)
    if email_text is not None:
        scores["revised_email_present"] = 1.0

        # Single paragraph
        paragraphs = _paragraph_blocks(email_text)
        scores["email_single_paragraph"] = 1.0 if len(paragraphs) == 1 else 0.0

        # Word count under 160
        wc = _word_count(email_text)
        scores["email_under_160_words"] = 1.0 if (0 < wc < 160) else 0.0

        text_norm = email_text.strip()

        # Required facts
        scores["email_mentions_name"] = 1.0 if ("Omar Hassan" in text_norm) else 0.0
        # Origin phrase
        scores["email_mentions_origin_phrase"] = 1.0 if ("Alexandria, Egypt" in text_norm) else 0.0
        # GPA
        scores["email_mentions_gpa"] = 1.0 if ("GPA 3.6/4.0" in text_norm or "GPA: 3.6/4.0" in text_norm) else 0.0
        # IELTS
        # Require "IELTS 6.5" phrase to be explicit
        scores["email_mentions_ielts"] = 1.0 if ("IELTS 6.5" in text_norm or "IELTS: 6.5" in text_norm) else 0.0
        # Fall 2025 exact
        scores["email_mentions_fall_2025"] = 1.0 if ("Fall 2025" in text_norm) else 0.0
        # Budget phrase exact
        scores["email_mentions_budget_phrase"] = 1.0 if ("USD 10,000 per year" in text_norm) else 0.0
        # Interest in biochemistry research: require both words present
        if re.search(r"\bbiochemistry\b", text_norm, flags=re.IGNORECASE) and re.search(r"\bresearch\b", text_norm, flags=re.IGNORECASE):
            scores["email_mentions_biochem_research"] = 1.0
        else:
            scores["email_mentions_biochem_research"] = 0.0

        # Include top3 universities from top3 file, in one sentence, exactly in that order, separated by semicolons
        includes_top3 = 0.0
        if top3_text is not None:
            top3_str = top3_text.strip()
            parts = [p.strip() for p in top3_str.split(";") if p.strip() != ""]
            if len(parts) == 3:
                # Build regex allowing optional spaces around semicolons, preserve exact order and names
                # Escape names for regex
                n1 = re.escape(parts[0])
                n2 = re.escape(parts[1])
                n3 = re.escape(parts[2])
                pattern = re.compile(n1 + r"\s*;\s*" + n2 + r"\s*;\s*" + n3)
                sentences = _sentence_split(email_text)
                for s in sentences:
                    if pattern.search(s):
                        includes_top3 = 1.0
                        break
        scores["email_includes_top3_universities_sentence"] = includes_top3

        # Avoid slang/apologies
        tokens = re.findall(r"\b[a-zA-Z']+\b", email_text.lower())
        token_set = set(tokens)
        disallowed = {"sorry", "lol", "gonna", "wanna", "kinda", "hiya", "thx"}
        contains_apolog = any(tok.startswith("apolog") for tok in token_set)
        contains_hi_word = "hi" in token_set  # only exact "hi"
        contains_disallowed = (len(token_set.intersection(disallowed)) > 0) or contains_apolog or contains_hi_word
        scores["email_avoids_slang_apologies"] = 1.0 if not contains_disallowed else 0.0
    else:
        # Revised email missing; leave related zeros
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) >= 2 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()