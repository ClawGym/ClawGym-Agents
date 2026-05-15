import sys
import json
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def count_words(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[\.!\?])\s+", text.strip())
    sentences = []
    for p in parts:
        s = p.strip()
        if s:
            sentences.append(s)
    return sentences


def extract_analysis_section(report_text: str) -> Optional[str]:
    idx = report_text.rfind("Analysis:")
    if idx == -1:
        return None
    after = report_text[idx + len("Analysis:") :].strip()
    return after


def parse_pass_fail_counts(report_text: str) -> Tuple[Optional[int], Optional[int]]:
    passed = None
    failed = None
    for line in report_text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("Passed:"):
            m = re.match(r"^Passed:\s*(\d+)\s*$", line_stripped)
            if m:
                try:
                    passed = int(m.group(1))
                except Exception:
                    passed = None
        if line_stripped.startswith("Failed:"):
            m = re.match(r"^Failed:\s*(\d+)\s*$", line_stripped)
            if m:
                try:
                    failed = int(m.group(1))
                except Exception:
                    failed = None
    return passed, failed


def parse_failure_lines(report_text: str) -> Dict[str, List[str]]:
    mismatch_lines = []
    invalid_handled_lines = []
    for line in report_text.splitlines():
        ls = line.strip()
        if ls.startswith("Mismatch:"):
            mismatch_lines.append(ls)
        if ls.startswith("Invalid case handled:"):
            invalid_handled_lines.append(ls)
    return {"mismatch": mismatch_lines, "invalid": invalid_handled_lines}


def validate_mismatch_line_format(line: str) -> bool:
    pattern = r"^Mismatch:\s*beats=(\d+)\s+steps=(\d+)\s+expected=(.+)\s+got=(.+)$"
    return re.match(pattern, line) is not None


def validate_invalid_handled_line_format(line: str) -> bool:
    pattern = r"^Invalid case handled:\s*beats=(\d+)\s+steps=(\d+)\s+error contains:\s+(.+)$"
    return re.match(pattern, line) is not None


def bjorklund_euclidean_pattern(beats: int, steps: int) -> Optional[str]:
    if steps <= 0 or beats < 0 or beats > steps:
        return None
    if beats == 0:
        return "0" * steps
    if beats == steps:
        return "1" * steps

    counts = []
    remainders = []
    divisor = steps - beats
    remainders.append(beats)
    level = 0
    while True:
        counts.append(divisor // remainders[level])
        remainders.append(divisor % remainders[level])
        divisor = remainders[level]
        level += 1
        if remainders[level] <= 1:
            break
    counts.append(divisor)

    def build(lvl: int) -> List[int]:
        if lvl == -1:
            return [0]
        elif lvl == -2:
            return [1]
        else:
            seq = []
            for _ in range(counts[lvl]):
                seq += build(lvl - 1)
            if remainders[lvl] != 0:
                seq += build(lvl - 2)
            return seq

    sequence = build(level)
    if len(sequence) != steps:
        if len(sequence) < steps:
            sequence = (sequence * ((steps // len(sequence)) + 1))[:steps]
        else:
            sequence = sequence[:steps]
    return "".join("1" if x == 1 else "0" for x in sequence)


def is_rotation(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    return b in (a + a)


def load_test_cases(input_dir: Path) -> Optional[dict]:
    path = input_dir / "test_cases.json"
    data = load_json(path)
    if not isinstance(data, dict):
        return None
    cases = data.get("cases")
    if not isinstance(cases, list):
        return None
    return data


def load_lesson_patterns(input_dir: Path) -> Optional[dict]:
    path = input_dir / "lesson_patterns.json"
    data = load_json(path)
    if not isinstance(data, dict):
        return None
    patterns = data.get("patterns")
    if not isinstance(patterns, list):
        return None
    return data


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "report_exists": 0.0,
        "report_pass_fail_lines_present": 0.0,
        "report_all_cases_passed": 0.0,
        "report_failure_lines_format": 0.0,
        "report_analysis_section_quality": 0.0,
        "report_invalid_error_phrase_present": 0.0,
        "generated_patterns_structure": 0.0,
        "generated_patterns_match_rotations": 0.0,
        "generated_patterns_complete": 0.0,
        "rewrite_exists": 0.0,
        "rewrite_word_limit": 0.0,
        "rewrite_definition_sentence": 0.0,
        "rewrite_avoids_jargon": 0.0,
        "rewrite_supportive_tone": 0.0,
        "rewrite_call_to_action": 0.0,
    }

    artifacts_dir = workspace / "artifacts"
    output_dir = workspace / "output"
    input_dir = workspace / "input"

    test_cases_data = load_test_cases(input_dir)
    lesson_patterns_data = load_lesson_patterns(input_dir)

    report_path = artifacts_dir / "test_report.txt"
    report_text = read_text_file(report_path)
    if report_text is not None:
        scores["report_exists"] = 1.0
        passed_cnt, failed_cnt = parse_pass_fail_counts(report_text)
        if passed_cnt is not None and failed_cnt is not None:
            scores["report_pass_fail_lines_present"] = 1.0
        if test_cases_data and isinstance(test_cases_data.get("cases"), list):
            total_cases = len(test_cases_data["cases"])
            if passed_cnt == total_cases and failed_cnt == 0:
                scores["report_all_cases_passed"] = 1.0
        parsed_failures = parse_failure_lines(report_text)
        mismatch_lines = parsed_failures["mismatch"]
        invalid_handled_lines = parsed_failures["invalid"]
        failure_format_ok = True
        for ml in mismatch_lines:
            if not validate_mismatch_line_format(ml):
                failure_format_ok = False
                break
        if failure_format_ok:
            for il in invalid_handled_lines:
                if not validate_invalid_handled_line_format(il):
                    failure_format_ok = False
                    break
        if failure_format_ok:
            if failed_cnt is None:
                scores["report_failure_lines_format"] = 1.0
            else:
                if failed_cnt == 0:
                    if len(mismatch_lines) == 0:
                        scores["report_failure_lines_format"] = 1.0
                else:
                    if (len(mismatch_lines) + len(invalid_handled_lines)) == failed_cnt:
                        scores["report_failure_lines_format"] = 1.0
        analysis = extract_analysis_section(report_text)
        if analysis is not None:
            sentences = split_sentences(analysis)
            sentence_count = len(sentences)
            contains_phrase = "beats must be <= steps" in analysis
            if 2 <= sentence_count <= 4 and contains_phrase:
                scores["report_analysis_section_quality"] = 1.0
        if "beats must be <= steps" in report_text:
            scores["report_invalid_error_phrase_present"] = 1.0

    gen_patterns_path = output_dir / "generated_patterns.json"
    gen_data = load_json(gen_patterns_path)
    structure_ok = False
    match_rotations_ok = False
    complete_ok = False
    if isinstance(gen_data, list):
        all_struct_ok = True
        mapping: Dict[Tuple[int, int], str] = {}
        for item in gen_data:
            if not isinstance(item, dict):
                all_struct_ok = False
                break
            beats = item.get("beats")
            steps = item.get("steps")
            pattern = item.get("pattern")
            if not isinstance(beats, int) or not isinstance(steps, int) or not isinstance(pattern, str):
                all_struct_ok = False
                break
            if len(pattern) != steps:
                all_struct_ok = False
                break
            if any(ch not in "01" for ch in pattern):
                all_struct_ok = False
                break
            if pattern.count("1") != beats:
                all_struct_ok = False
                break
            mapping[(beats, steps)] = pattern
        if all_struct_ok:
            structure_ok = True
        if lesson_patterns_data and isinstance(lesson_patterns_data.get("patterns"), list):
            expected_pairs = [(p.get("beats"), p.get("steps")) for p in lesson_patterns_data["patterns"]]
            if all(isinstance(b, int) and isinstance(s, int) and (b, s) in mapping for b, s in expected_pairs):
                complete_ok = True
        if structure_ok:
            all_match = True
            for (b, s), pat in mapping.items():
                canon = bjorklund_euclidean_pattern(b, s)
                if canon is None:
                    all_match = False
                    break
                if not (pat == canon or is_rotation(canon, pat)):
                    all_match = False
                    break
            if all_match:
                match_rotations_ok = True

    scores["generated_patterns_structure"] = 1.0 if structure_ok else 0.0
    scores["generated_patterns_match_rotations"] = 1.0 if match_rotations_ok else 0.0
    scores["generated_patterns_complete"] = 1.0 if complete_ok else 0.0

    rewrite_path = output_dir / "message_rewrite.md"
    rewrite_text = read_text_file(rewrite_path)
    if rewrite_text is not None:
        scores["rewrite_exists"] = 1.0
        if count_words(rewrite_text) <= 160:
            scores["rewrite_word_limit"] = 1.0
        sentences = split_sentences(rewrite_text)
        def_sent_ok = False
        for sent in sentences:
            low = sent.lower()
            if ("euclidean rhythm" in low or "euclidean rhythms" in low) and (" is " in low or " are " in low):
                if count_words(sent) <= 30:
                    def_sent_ok = True
                    break
        if def_sent_ok:
            scores["rewrite_definition_sentence"] = 1.0
        jargon_terms = [
            "bjorklund",
            "variance",
            "sequence-construction",
            "polyrhythms",
            "mathy",
            "maximal evenness",
        ]
        text_low = rewrite_text.lower()
        if not any(term in text_low for term in jargon_terms):
            scores["rewrite_avoids_jargon"] = 1.0
        supportive_words = [
            "fun", "excited", "curious", "explore", "play", "easy", "simple",
            "let's", "lets", "you can", "great", "awesome", "cool", "encouraging",
            "no pressure", "friendly", "try"
        ]
        support_count = sum(1 for w in supportive_words if w in text_low)
        if support_count >= 2:
            scores["rewrite_supportive_tone"] = 1.0
        imperative_words = ["try", "load", "play", "enter", "use", "paste", "import", "sequence", "experiment", "jam"]
        cta_ok = False
        for sent in sentences:
            low = sent.lower()
            if ("daw" in low or "step sequencer" in low or "sequencer" in low) and "pattern" in low:
                if any(w in low for w in imperative_words):
                    cta_ok = True
                    break
        if cta_ok:
            scores["rewrite_call_to_action"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()