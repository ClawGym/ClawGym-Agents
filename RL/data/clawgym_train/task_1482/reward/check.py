import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Tuple, Optional, Dict


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_csv_safe(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = list(reader)
        return header, rows
    except Exception:
        return None, None


def _extract_section_block_lines(text: str, header_label: str) -> List[str]:
    """
    Extract lines in the section following a header line matching header_label (case-insensitive).
    Stops at the next markdown header or a clear section delimiter.
    """
    if text is None:
        return []
    lines = text.splitlines()
    header_label_lc = header_label.strip().lower()
    start_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("#"):
            low = low.lstrip("#").strip().lower()
        if low.startswith(header_label_lc):
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    block = []
    for j in range(start_idx, len(lines)):
        next_line = lines[j]
        nxt = next_line.strip()
        if nxt.startswith("#"):
            break
        if (nxt.endswith(":") and not nxt.startswith("- ")) and nxt.lower().strip(":") not in ["error analysis", "refactor summary"]:
            break
        block.append(next_line)
    return block


def _word_count_space_split(text: str) -> int:
    # Matches the logic in the original script: split by single space and filter out empty tokens.
    if text == "":
        return 0
    parts = text.split(" ")
    return len([w for w in parts if w != ""])


def _sentence_count(text: str) -> int:
    # Count characters that are sentence terminators .!?
    return sum(1 for ch in text if ch in ".!?")


def _compute_expected_metrics(cfg: dict, input_rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, int]]]:
    if cfg is None:
        return None
    # Determine which text column key to use based on config keys present
    if "text_column" in cfg:
        text_col = cfg.get("text_column")
    elif "textCol" in cfg:
        text_col = cfg.get("textCol")
    else:
        return None
    if not isinstance(text_col, str) or not text_col:
        return None
    do_lower = bool(cfg.get("lowercase", False))
    expected = {}
    try:
        for row in input_rows:
            if text_col not in row:
                return None
            t = row[text_col]
            if do_lower:
                t = t.lower()
            chars = len(t)
            words = _word_count_space_split(t)
            sents = _sentence_count(t)
            expected[row.get("id", "")] = {"chars": chars, "words": words, "sentences": sents}
        return expected
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "output_csv_exists": 0.0,
        "output_csv_header_correct": 0.0,
        "output_csv_row_count_matches_input": 0.0,
        "output_contains_all_input_ids": 0.0,
        "output_values_are_ints": 0.0,
        "output_metrics_correct": 0.0,
        "summary_py_has_compute_metrics": 0.0,
        "compute_metrics_has_docstring": 0.0,
        "compute_metrics_returns_required_keys": 0.0,
        "summary_py_uses_compute_metrics": 0.0,
        "readme_includes_exact_command": 0.0,
        "code_review_has_required_sections": 0.0,
        "code_review_error_mentions_keyerror": 0.0,
        "code_review_error_mentions_misaligned_keys": 0.0,
        "code_review_refactor_bullets_count": 0.0,
        "code_review_refactor_mentions_compute_metrics": 0.0,
        "email_subject_line_present": 0.0,
        "email_bullet_count_exactly_three": 0.0,
        "email_body_word_count_leq_180": 0.0,
        "email_mentions_brody_at_most_once": 0.0,
        "config_and_code_alignment": 0.0,
    }

    # Paths
    src_summary = workspace / "src" / "summary.py"
    cfg_path = workspace / "config" / "app.json"
    input_csv_path = workspace / "input" / "data" / "speeches.csv"
    output_csv_path = workspace / "output" / "summary.csv"
    readme_path = workspace / "docs" / "README.md"
    code_review_path = workspace / "output" / "code_review.md"
    email_polished_path = workspace / "output" / "email_polished.txt"

    # Load input and output CSVs
    out_header, out_rows = _parse_csv_safe(output_csv_path)
    if out_header is not None and out_rows is not None:
        scores["output_csv_exists"] = 1.0
        expected_header = ["id", "chars", "words", "sentences"]
        if out_header == expected_header:
            scores["output_csv_header_correct"] = 1.0
        in_header, in_rows = _parse_csv_safe(input_csv_path)
        if in_header is not None and in_rows is not None:
            if len(out_rows) == len(in_rows):
                scores["output_csv_row_count_matches_input"] = 1.0
            out_ids = [r.get("id", "") for r in out_rows]
            in_ids = [r.get("id", "") for r in in_rows]
            try:
                if sorted(out_ids) == sorted(in_ids):
                    scores["output_contains_all_input_ids"] = 1.0
            except Exception:
                pass
            # Validate numeric fields are non-negative integers for all rows
            try:
                all_ints = True
                for r in out_rows:
                    for k in ["chars", "words", "sentences"]:
                        v = r.get(k, "")
                        if isinstance(v, str):
                            if not re.fullmatch(r"\d+", v.strip()):
                                all_ints = False
                                break
                        else:
                            _ = int(v)
                    if not all_ints:
                        break
                if all_ints:
                    scores["output_values_are_ints"] = 1.0
            except Exception:
                pass

            # Metrics correctness check using config logic
            cfg = _load_json_safe(cfg_path)
            expected = _compute_expected_metrics(cfg or {}, in_rows)
            if expected is not None:
                try:
                    ok = True
                    for r in out_rows:
                        rid = r.get("id", "")
                        if rid not in expected:
                            ok = False
                            break
                        try:
                            chars_ok = int(r.get("chars", -1)) == int(expected[rid]["chars"])
                            words_ok = int(r.get("words", -1)) == int(expected[rid]["words"])
                            sents_ok = int(r.get("sentences", -1)) == int(expected[rid]["sentences"])
                        except Exception:
                            ok = False
                            break
                        if not (chars_ok and words_ok and sents_ok):
                            ok = False
                            break
                    if ok:
                        scores["output_metrics_correct"] = 1.0
                except Exception:
                    pass

    # Source code checks
    summary_text = _read_text_safe(src_summary)
    if summary_text is not None:
        # compute_metrics def presence
        def_match = re.search(r"def\s+compute_metrics\s*\(\s*text\s*(?::\s*str)?\s*\)\s*:", summary_text)
        if def_match:
            scores["summary_py_has_compute_metrics"] = 1.0
            # Docstring immediately following the def line
            after_def = summary_text[def_match.end():def_match.end() + 400]
            if re.search(r'^\s*(?:\"\"\"|\'\'\')', after_def, flags=re.MULTILINE):
                scores["compute_metrics_has_docstring"] = 1.0
            # Function block contains required keys in return
            # Naively slice function block to next def or EOF
            after = summary_text[def_match.end():]
            next_def = re.search(r"^\s*def\s+\w+\s*\(", after, flags=re.MULTILINE)
            func_block = summary_text[def_match.start(): def_match.end() + (next_def.start() if next_def else len(after))]
            if ("return" in func_block and
                re.search(r"[\'\"]chars[\'\"]", func_block) and
                re.search(r"[\'\"]words[\'\"]", func_block) and
                re.search(r"[\'\"]sentences[\'\"]", func_block)):
                scores["compute_metrics_returns_required_keys"] = 1.0

        # Usage check: ensure a call to compute_metrics exists somewhere (not the def)
        if re.search(r"(?<!def\s)compute_metrics\s*\(", summary_text):
            scores["summary_py_uses_compute_metrics"] = 1.0

    # README must include the exact command
    readme_text = _read_text_safe(readme_path)
    exact_cmd = "python src/summary.py --config config/app.json --input input/data/speeches.csv --out output/summary.csv"
    if readme_text is not None:
        if exact_cmd in readme_text:
            scores["readme_includes_exact_command"] = 1.0

    # code_review.md checks
    review_text = _read_text_safe(code_review_path)
    if review_text is not None:
        has_error_section = bool(re.search(r"^\s*#*\s*Error analysis\s*:?\s*$", review_text, flags=re.IGNORECASE | re.MULTILINE))
        has_refactor_section = bool(re.search(r"^\s*#*\s*Refactor summary\s*:?\s*$", review_text, flags=re.IGNORECASE | re.MULTILINE))
        if has_error_section and has_refactor_section:
            scores["code_review_has_required_sections"] = 1.0

        error_block = _extract_section_block_lines(review_text, "Error analysis")
        error_text = "\n".join(error_block) if error_block else ""
        if re.search(r"\bKeyError\b", error_text):
            scores["code_review_error_mentions_keyerror"] = 1.0
        if ("text_column" in error_text) and ("textCol" in error_text):
            scores["code_review_error_mentions_misaligned_keys"] = 1.0

        refactor_block = _extract_section_block_lines(review_text, "Refactor summary")
        if refactor_block:
            bullet_lines = [ln for ln in refactor_block if ln.strip().startswith("- ")]
            if 3 <= len(bullet_lines) <= 5:
                scores["code_review_refactor_bullets_count"] = 1.0
            refactor_text = "\n".join(refactor_block)
            if re.search(r"\bcompute_metrics\b", refactor_text):
                scores["code_review_refactor_mentions_compute_metrics"] = 1.0

    # Email checks
    email_text = _read_text_safe(email_polished_path)
    if email_text is not None:
        email_lines = email_text.splitlines()
        if email_lines:
            if email_lines[0].startswith("Subject:"):
                scores["email_subject_line_present"] = 1.0
            body_lines = email_lines[1:]
            bullet_count = sum(1 for ln in body_lines if ln.startswith("- "))
            if bullet_count == 3:
                scores["email_bullet_count_exactly_three"] = 1.0
            body_text = "\n".join(body_lines)
            words = re.findall(r"\b\w[\w'.-]*\b", body_text)
            if len(words) <= 180:
                scores["email_body_word_count_leq_180"] = 1.0
            brody_mentions = len(re.findall(r"\bbrody\b", body_text, flags=re.IGNORECASE))
            if brody_mentions <= 1:
                scores["email_mentions_brody_at_most_once"] = 1.0

    # Config and code alignment: check that config contains at least one of the keys that code expects for text column
    cfg = _load_json_safe(cfg_path)
    if summary_text is not None and cfg is not None:
        code_refs_text_keys = set()
        if re.search(r"cfg\[['\"]text_column['\"]\]", summary_text) or re.search(r"cfg\.get\(\s*['\"]text_column['\"]", summary_text):
            code_refs_text_keys.add("text_column")
        if re.search(r"cfg\[['\"]textCol['\"]\]", summary_text) or re.search(r"cfg\.get\(\s*['\"]textCol['\"]", summary_text):
            code_refs_text_keys.add("textCol")
        if code_refs_text_keys:
            if set(cfg.keys()).intersection(code_refs_text_keys):
                scores["config_and_code_alignment"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()