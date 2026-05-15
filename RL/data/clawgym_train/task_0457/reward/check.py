import json
import csv
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def count_words(text: str) -> int:
    # Count tokens of letters/digits/underscores/apostrophes as words
    tokens = re.findall(r"[A-Za-z0-9']+", text)
    return len(tokens)


def contains_placeholders(text: str) -> bool:
    # Matches [TK], [TK ...], case-sensitive
    return re.search(r"\[TK(?:[^\]]*)\]", text) is not None


def no_variants_present(text: str, mapping: Dict[str, str]) -> bool:
    if mapping is None:
        return False
    for variant in mapping.keys():
        if variant in text:
            return False
    return True


def find_bullet_lines(lines: List[str]) -> List[str]:
    return [ln.rstrip("\r\n") for ln in lines if ln.startswith("- ")]


def get_intro_text(lines: List[str]) -> str:
    # After subject line, before the first bullet line
    if not lines:
        return ""
    intro_lines: List[str] = []
    for ln in lines[1:]:
        if ln.startswith("- "):
            break
        intro_lines.append(ln.strip())
    # Remove leading/trailing blank lines in intro
    while intro_lines and intro_lines[0] == "":
        intro_lines.pop(0)
    while intro_lines and intro_lines[-1] == "":
        intro_lines.pop()
    return " ".join([s for s in intro_lines if s != ""])


def sentence_count(text: str) -> int:
    # Count sentences by splitting on punctuation followed by whitespace
    # This avoids counting dots inside filenames (e.g., .md) because they are not followed by whitespace necessarily.
    s = text.strip()
    if not s:
        return 0
    # Normalize multiple spaces
    s = re.sub(r"\s+", " ", s)
    parts = re.split(r"(?<=[\.!?])\s+", s)
    # Filter out empty parts
    parts = [p for p in parts if p.strip()]
    return len(parts)


def parse_word_counts_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames
    except Exception:
        return None, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "synopsis_file_exists": 0.0,
        "synopsis_word_count_range": 0.0,
        "synopsis_no_placeholders": 0.0,
        "synopsis_contains_title_author": 0.0,
        "synopsis_canonical_names_replaced": 0.0,
        "pitch_letter_file_exists": 0.0,
        "pitch_letter_word_count_range": 0.0,
        "pitch_letter_no_placeholders": 0.0,
        "pitch_letter_contains_title_author": 0.0,
        "pitch_letter_contains_word_count_numeric": 0.0,
        "pitch_letter_contains_comps": 0.0,
        "pitch_letter_canonical_names_replaced": 0.0,
        "email_file_exists": 0.0,
        "email_subject_line_valid": 0.0,
        "email_intro_references_attachments": 0.0,
        "email_intro_sentence_count_2_to_3": 0.0,
        "email_exact_three_bullets": 0.0,
        "email_bullets_content_correct": 0.0,
        "validation_script_exists": 0.0,
        "validation_script_has_args": 0.0,
        "validation_report_exists": 0.0,
        "validation_report_fields_present": 0.0,
        "validation_report_values_consistent": 0.0,
        "word_counts_csv_exists": 0.0,
        "word_counts_csv_structure_correct": 0.0,
        "word_counts_csv_counts_in_range": 0.0,
        "word_counts_csv_counts_match_recomputed": 0.0,
    }

    # Load inputs
    metadata = load_json_safe(workspace / "input" / "metadata.json")
    canonical = load_json_safe(workspace / "input" / "canonical_names.json")

    title = metadata.get("title") if isinstance(metadata, dict) else None
    author = metadata.get("author") if isinstance(metadata, dict) else None
    genre = metadata.get("genre") if isinstance(metadata, dict) else None
    manuscript_count = metadata.get("manuscript_word_count") if isinstance(metadata, dict) else None

    # Paths
    synopsis_path = workspace / "output" / "synopsis_final.md"
    pitch_path = workspace / "output" / "pitch_letter_final.md"
    email_path = workspace / "output" / "email_to_editor.txt"
    validation_script_path = workspace / "scripts" / "validate_package.py"
    validation_report_path = workspace / "output" / "validation_report.json"
    word_counts_csv_path = workspace / "output" / "word_counts.csv"

    # Read outputs
    synopsis_text = read_text_safe(synopsis_path)
    pitch_text = read_text_safe(pitch_path)
    email_text = read_text_safe(email_path)

    # Synopsis checks
    if synopsis_text is not None:
        scores["synopsis_file_exists"] = 1.0
        syn_wc = count_words(synopsis_text)
        if 270 <= syn_wc <= 300:
            scores["synopsis_word_count_range"] = 1.0
        if not contains_placeholders(synopsis_text):
            scores["synopsis_no_placeholders"] = 1.0
        # Title and author presence
        if isinstance(title, str) and isinstance(author, str):
            if (title in synopsis_text) and (author in synopsis_text):
                scores["synopsis_contains_title_author"] = 1.0
        # Canonical names replacement (no variants present)
        if isinstance(canonical, dict) and canonical:
            if no_variants_present(synopsis_text, canonical):
                scores["synopsis_canonical_names_replaced"] = 1.0

    # Pitch letter checks
    if pitch_text is not None:
        scores["pitch_letter_file_exists"] = 1.0
        pitch_wc = count_words(pitch_text)
        if 150 <= pitch_wc <= 180:
            scores["pitch_letter_word_count_range"] = 1.0
        if not contains_placeholders(pitch_text):
            scores["pitch_letter_no_placeholders"] = 1.0
        if isinstance(title, str) and isinstance(author, str):
            if (title in pitch_text) and (author in pitch_text):
                scores["pitch_letter_contains_title_author"] = 1.0
        if isinstance(manuscript_count, int):
            if str(manuscript_count) in pitch_text:
                scores["pitch_letter_contains_word_count_numeric"] = 1.0
        # Comps presence
        if ("Bluebird Nights" in pitch_text) and ("The Fallen Orchard" in pitch_text):
            scores["pitch_letter_contains_comps"] = 1.0
        # Canonical names replaced
        if isinstance(canonical, dict) and canonical:
            if no_variants_present(pitch_text, canonical):
                scores["pitch_letter_canonical_names_replaced"] = 1.0

    # Email checks
    if email_text is not None:
        scores["email_file_exists"] = 1.0
        email_lines = email_text.splitlines()
        if email_lines:
            subj = email_lines[0].strip()
            if subj.startswith("Subject: "):
                # Must include exact title and author
                if isinstance(title, str) and isinstance(author, str):
                    if (title in subj) and (author in subj):
                        scores["email_subject_line_valid"] = 1.0
            # Intro references and sentence count
            intro = get_intro_text(email_lines)
            if intro:
                # References attachments by name
                if ("synopsis_final.md" in intro) and ("pitch_letter_final.md" in intro):
                    scores["email_intro_references_attachments"] = 1.0
                sc = sentence_count(intro)
                if 2 <= sc <= 3:
                    scores["email_intro_sentence_count_2_to_3"] = 1.0
            # Bullets
            bullets = find_bullet_lines(email_lines)
            if len(bullets) == 3:
                scores["email_exact_three_bullets"] = 1.0
                # Validate bullet contents
                expected = set()
                if isinstance(genre, str):
                    expected.add(f"- Genre: {genre}")
                if isinstance(manuscript_count, int):
                    expected.add(f"- Manuscript word count: {manuscript_count}")
                expected.add("- Comps: Bluebird Nights; The Fallen Orchard")
                if expected and set(bullets) == expected:
                    scores["email_bullets_content_correct"] = 1.0

    # Validation script checks
    if validation_script_path.exists() and validation_script_path.is_file():
        scores["validation_script_exists"] = 1.0
        vs_text = read_text_safe(validation_script_path) or ""
        has_args = ("argparse" in vs_text) and ("--input_dir" in vs_text) and ("--output_dir" in vs_text)
        if has_args:
            scores["validation_script_has_args"] = 1.0

    # Validation report checks
    validation_report = load_json_safe(validation_report_path)
    if isinstance(validation_report, dict):
        scores["validation_report_exists"] = 1.0
        # Required fields
        required_fields = {
            "canonical_names_ok": bool,
            "synopsis_word_count": int,
            "pitch_letter_word_count": int,
            "placeholders_ok": bool,
            "title_author_present": bool,
            "comps_ok": bool,
            "email_bullets_ok": bool,
            "overall_pass": bool,
        }
        types_ok = True
        for k, t in required_fields.items():
            if k not in validation_report:
                types_ok = False
                break
            if not isinstance(validation_report[k], t):
                types_ok = False
                break
        if types_ok:
            scores["validation_report_fields_present"] = 1.0

        # Compute our own booleans to compare with report
        # canonical_names_ok across both outputs
        our_canonical_ok = False
        if isinstance(canonical, dict) and canonical and isinstance(synopsis_text, str) and isinstance(pitch_text, str):
            our_canonical_ok = no_variants_present(synopsis_text, canonical) and no_variants_present(pitch_text, canonical)
        # placeholders_ok across outputs and email
        placeholders_ok = True
        for t in (synopsis_text, pitch_text, email_text):
            if isinstance(t, str) and contains_placeholders(t):
                placeholders_ok = False
                break
        # title_author_present across both outputs
        title_author_present = False
        if isinstance(title, str) and isinstance(author, str) and isinstance(synopsis_text, str) and isinstance(pitch_text, str):
            title_author_present = (title in synopsis_text and author in synopsis_text and
                                    title in pitch_text and author in pitch_text)
        # comps_ok (in pitch letter)
        comps_ok = isinstance(pitch_text, str) and ("Bluebird Nights" in pitch_text) and ("The Fallen Orchard" in pitch_text)
        # email_bullets_ok (exact three bullets and correct content)
        email_bullets_ok = False
        if isinstance(email_text, str):
            lines = email_text.splitlines()
            bullets = find_bullet_lines(lines)
            if len(bullets) == 3:
                expected = set()
                if isinstance(genre, str):
                    expected.add(f"- Genre: {genre}")
                if isinstance(manuscript_count, int):
                    expected.add(f"- Manuscript word count: {manuscript_count}")
                expected.add("- Comps: Bluebird Nights; The Fallen Orchard")
                if expected and set(bullets) == expected:
                    email_bullets_ok = True
        # word counts
        syn_wc_calc = count_words(synopsis_text) if isinstance(synopsis_text, str) else None
        pitch_wc_calc = count_words(pitch_text) if isinstance(pitch_text, str) else None
        overall_pass = (our_canonical_ok and placeholders_ok and title_author_present and comps_ok and email_bullets_ok)
        if isinstance(syn_wc_calc, int) and 270 <= syn_wc_calc <= 300 and isinstance(pitch_wc_calc, int) and 150 <= pitch_wc_calc <= 180:
            overall_pass = overall_pass and True
        else:
            overall_pass = False

        consistent = True
        # Compare to report values if present and types valid
        if scores["validation_report_fields_present"] == 1.0:
            consistent = (
                (validation_report["canonical_names_ok"] == our_canonical_ok) and
                (isinstance(syn_wc_calc, int) and validation_report["synopsis_word_count"] == syn_wc_calc) and
                (isinstance(pitch_wc_calc, int) and validation_report["pitch_letter_word_count"] == pitch_wc_calc) and
                (validation_report["placeholders_ok"] == placeholders_ok) and
                (validation_report["title_author_present"] == title_author_present) and
                (validation_report["comps_ok"] == comps_ok) and
                (validation_report["email_bullets_ok"] == email_bullets_ok) and
                (validation_report["overall_pass"] == overall_pass)
            )
        if consistent:
            scores["validation_report_values_consistent"] = 1.0

    # word_counts.csv checks
    rows, headers = parse_word_counts_csv(word_counts_csv_path)
    if rows is not None and headers is not None:
        scores["word_counts_csv_exists"] = 1.0
        # structure: has file and words columns, exactly two rows for the two files
        has_cols = ("file" in headers) and ("words" in headers)
        correct_files = False
        counts_in_range = False
        counts_match = False
        if has_cols and len(rows) == 2:
            files_set = set(r.get("file", "") for r in rows)
            correct_files = files_set == {"synopsis_final.md", "pitch_letter_final.md"}
            # Validate ranges based on reported numbers
            try:
                syn_row = next(r for r in rows if r.get("file") == "synopsis_final.md")
                pitch_row = next(r for r in rows if r.get("file") == "pitch_letter_final.md")
                syn_words_reported = int(syn_row.get("words", ""))
                pitch_words_reported = int(pitch_row.get("words", ""))
                counts_in_range = (270 <= syn_words_reported <= 300) and (150 <= pitch_words_reported <= 180)
                # Compare to recomputed counts if we have texts
                syn_wc_calc = count_words(synopsis_text) if isinstance(synopsis_text, str) else None
                pitch_wc_calc = count_words(pitch_text) if isinstance(pitch_text, str) else None
                counts_match = (
                    isinstance(syn_wc_calc, int) and isinstance(pitch_wc_calc, int) and
                    syn_words_reported == syn_wc_calc and pitch_words_reported == pitch_wc_calc
                )
            except Exception:
                correct_files = False
                counts_in_range = False
                counts_match = False
        if has_cols and correct_files:
            scores["word_counts_csv_structure_correct"] = 1.0
        if counts_in_range:
            scores["word_counts_csv_counts_in_range"] = 1.0
        if counts_match:
            scores["word_counts_csv_counts_match_recomputed"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()