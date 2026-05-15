import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        return text, None
    except Exception as e:
        return None, str(e)


def load_json_safe(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except Exception as e:
        return None, str(e)


def split_sentences(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def count_words(sentence: str) -> int:
    tokens = re.findall(r"[A-Za-z']+", sentence)
    return len(tokens)


def compute_readability(text: str) -> dict:
    sentences = split_sentences(text)
    results = []
    total_words = 0
    for idx, s in enumerate(sentences, start=1):
        wc = count_words(s)
        total_words += wc
        is_long = wc > 22
        results.append({
            'index': idx,
            'text': s,
            'word_count': wc,
            'is_long': is_long
        })
    total_sentences = len(results)
    avg_len = (total_words / total_sentences) if total_sentences else 0.0
    return {
        'total_sentences': total_sentences,
        'total_words': total_words,
        'avg_sentence_length': avg_len,
        'sentences': results
    }


def expected_stdout(metrics: dict) -> str:
    lines = []
    lines.append(f"Total sentences: {metrics['total_sentences']}")
    lines.append(f"Total words: {metrics['total_words']}")
    avg = metrics['avg_sentence_length']
    lines.append(f"Average sentence length (words): {avg:.2f}")
    for r in metrics['sentences']:
        lines.append(f"Sentence {r['index']}: {r['word_count']} words")
    return "\n".join(lines) + "\n"


def expected_stderr(metrics: dict) -> str:
    warnings = []
    for r in metrics['sentences']:
        if r['is_long']:
            warnings.append(f"WARNING: Sentence {r['index']} has {r['word_count']} words (>22)")
    if warnings:
        return "\n".join(warnings) + "\n"
    else:
        return ""


def normalize_newlines(s: str) -> str:
    # Normalize line endings to '\n' and strip trailing spaces on each line
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    # Ensure trailing newline if non-empty original had a newline
    return s


def parse_markdown_sections(md_text: str) -> Dict[str, str]:
    """
    Extract sections by headings. A heading is a line starting with optional up to 6 '#'
    followed by a title. We normalize the title by stripping trailing colon and whitespace,
    converting curly apostrophes to straight ones, and lowercasing.
    Returns a dict mapping normalized title to content text (until next heading or end).
    """
    lines = md_text.splitlines()
    sections = {}
    current_title = None
    current_buffer: List[str] = []

    def norm_title(t: str) -> str:
        t = t.strip()
        t = re.sub(r'^\s*#{0,6}\s*', '', t)  # remove leading hashes/spaces
        t = t.strip()
        t = t[:-1] if t.endswith(':') else t
        t = t.strip()
        t = t.replace('\u2019', "'")  # curly apostrophe to straight
        return t.lower()

    for line in lines:
        # Check if this line is a heading
        if re.match(r'^\s{0,3}#{0,6}\s*\S', line):
            title = norm_title(line)
            if current_title is not None:
                sections[current_title] = "\n".join(current_buffer).strip()
            current_title = title
            current_buffer = []
        else:
            if current_title is not None:
                current_buffer.append(line)
    if current_title is not None:
        sections[current_title] = "\n".join(current_buffer).strip()
    return sections


def find_section_content(sections: Dict[str, str], candidates: List[str]) -> Optional[str]:
    # Normalize candidates similarly to section keys
    norm_candidates = [c.replace('\u2019', "'").lower() for c in candidates]
    for key, content in sections.items():
        for cand in norm_candidates:
            if key == cand:
                return content
    return None


def count_sentences_freeform(text: str) -> int:
    # Count sentences by occurrences of ., !, ? that likely end a sentence.
    # Split on punctuation followed by whitespace or end.
    sentences = [s for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s]
    return len(sentences)


def extract_bullet_count(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if re.match(r'^\s*[-*+]\s+', line):
            count += 1
        elif re.match(r'^\s*\d+\.\s+', line):
            count += 1
    return count


def tokenize_words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z']+", text)


def extract_ints(text: str) -> List[int]:
    return [int(x) for x in re.findall(r'\b\d+\b', text)]


def top_n_longest_sentences(metrics: dict, n: int = 3) -> List[dict]:
    sentences = metrics['sentences']
    # Sort by word_count desc, then index asc for determinism
    sorted_s = sorted(sentences, key=lambda r: (-r['word_count'], r['index']))
    return sorted_s[:n]


def words_ge_length(text: str, min_len: int) -> List[str]:
    tokens = re.findall(r"[A-Za-z]+", text.lower())
    return [w for w in tokens if len(w) >= min_len]


def unique_case_insensitive_words_ge_length(text: str, min_len: int) -> List[str]:
    tokens = re.findall(r"[A-Za-z]+", text.lower())
    uniq = []
    seen = set()
    for w in tokens:
        if len(w) >= min_len and w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "readability_json_matches_expected": 0.0,
        "readability_stdout_matches_expected": 0.0,
        "readability_stderr_matches_expected": 0.0,
        "feedback_sections_present": 0.0,
        "summary_sentence_count": 0.0,
        "answers_cover_all_questions": 0.0,
        "answers_reference_sentence_numbers": 0.0,
        "longest_sentences_section_includes_top3": 0.0,
        "warnings_section_lists_trigger_indices": 0.0,
        "hard_words_section_correct": 0.0,
        "summary_json_schema_valid": 0.0,
        "summary_json_longest_match": 0.0,
        "summary_json_warning_count_match": 0.0,
        "email_subject_and_length": 0.0,
        "email_mentions_required_elements": 0.0,
    }

    # Paths
    chapter_path = workspace / "input" / "chapter1.txt"
    questions_path = workspace / "input" / "author_questions.txt"
    read_json_path = workspace / "output" / "readability.json"
    read_stdout_path = workspace / "output" / "readability_stdout.txt"
    read_stderr_path = workspace / "output" / "readability_stderr.txt"
    feedback_path = workspace / "output" / "feedback_report.md"
    summary_json_path = workspace / "output" / "readability_summary.json"
    email_path = workspace / "output" / "email_to_author.txt"

    # Load source chapter for recomputation
    chapter_text, err_ch = read_text_safe(chapter_path)
    if chapter_text is None:
        # Cannot proceed with tool comparisons; leave related scores at 0.0
        expected_metrics = None
    else:
        expected_metrics = compute_readability(chapter_text)

    # Check readability.json correctness
    read_json, err_rj = load_json_safe(read_json_path)
    if expected_metrics is not None and read_json is not None:
        # Compare totals
        try:
            totals_ok = (
                read_json.get('total_sentences') == expected_metrics['total_sentences'] and
                read_json.get('total_words') == expected_metrics['total_words'] and
                abs(read_json.get('avg_sentence_length', -1.0) - expected_metrics['avg_sentence_length']) < 1e-9
            )
            # Compare sentences list
            rj_sentences = read_json.get('sentences')
            sent_ok = isinstance(rj_sentences, list) and len(rj_sentences) == len(expected_metrics['sentences'])
            if sent_ok:
                for exp, got in zip(expected_metrics['sentences'], rj_sentences):
                    if not (got.get('index') == exp['index'] and
                            got.get('text') == exp['text'] and
                            got.get('word_count') == exp['word_count'] and
                            bool(got.get('is_long')) == exp['is_long']):
                        sent_ok = False
                        break
            if totals_ok and sent_ok:
                scores["readability_json_matches_expected"] = 1.0
        except Exception:
            pass

    # Check stdout correctness
    read_stdout_text, _ = read_text_safe(read_stdout_path)
    if expected_metrics is not None and read_stdout_text is not None:
        exp_out = normalize_newlines(expected_stdout(expected_metrics))
        got_out = normalize_newlines(read_stdout_text)
        if exp_out == got_out:
            scores["readability_stdout_matches_expected"] = 1.0

    # Check stderr correctness
    read_stderr_text, _ = read_text_safe(read_stderr_path)
    if expected_metrics is not None and read_stderr_text is not None:
        exp_err = normalize_newlines(expected_stderr(expected_metrics))
        got_err = normalize_newlines(read_stderr_text)
        if exp_err == got_err:
            scores["readability_stderr_matches_expected"] = 1.0

    # Parse feedback report
    feedback_text, _ = read_text_safe(feedback_path)
    sections = {}
    if feedback_text is not None:
        sections = parse_markdown_sections(feedback_text)

    # Required section names (accept curly or straight apostrophes variants)
    required_sections_variants = {
        "summary as a kid": ["Summary as a kid"],
        "answers to the author's questions": ["Answers to the author's questions", "Answers to the author’s questions"],
        "longest sentences and kid-friendly rewrites": ["Longest sentences and kid-friendly rewrites"],
        "warnings from the tool": ["Warnings from the tool"],
        "hard words i noticed": ["Hard words I noticed"],
    }

    # Count how many required sections present
    present = 0
    for norm_key, variants in required_sections_variants.items():
        content = find_section_content(sections, variants)
        if content is not None:
            present += 1
    if required_sections_variants:
        scores["feedback_sections_present"] = present / float(len(required_sections_variants))

    # Summary section sentence count
    summary_content = find_section_content(sections, required_sections_variants["summary as a kid"])
    if summary_content is not None:
        n_sent = count_sentences_freeform(summary_content)
        if 2 <= n_sent <= 4:
            scores["summary_sentence_count"] = 1.0

    # Answers to questions
    answers_content = find_section_content(sections, required_sections_variants["answers to the author's questions"])
    questions_text, _ = read_text_safe(questions_path)
    if answers_content is not None and questions_text is not None:
        questions = [ln for ln in questions_text.splitlines() if ln.strip().startswith("- ")]
        num_questions = len(questions)
        ans_count = extract_bullet_count(answers_content)
        cover_ratio = 0.0
        if num_questions > 0:
            cover_ratio = min(ans_count / float(num_questions), 1.0)
        scores["answers_cover_all_questions"] = cover_ratio
        # references to sentence numbers like "Sentence 3"
        if re.search(r'\bSentence\s+\d+\b', answers_content, flags=re.IGNORECASE):
            scores["answers_reference_sentence_numbers"] = 1.0

    # Longest sentences in feedback: ensure top 3 originals present
    if expected_metrics is not None:
        top3 = top_n_longest_sentences(expected_metrics, 3)
        top3_indices = [r['index'] for r in top3]
        longest_content = find_section_content(sections, required_sections_variants["longest sentences and kid-friendly rewrites"])
        found = 0
        if longest_content is not None:
            for r in top3:
                # Must mention "Sentence X" and include the exact original text
                idx = r['index']
                txt = r['text']
                has_idx = re.search(rf'\bSentence\s+{idx}\b', longest_content, flags=re.IGNORECASE) is not None
                has_original = txt in longest_content
                if has_idx and has_original:
                    found += 1
        if found:
            scores["longest_sentences_section_includes_top3"] = found / 3.0

    # Warnings section: list numbers and count
    warnings_content = find_section_content(sections, required_sections_variants["warnings from the tool"])
    if warnings_content is not None and expected_metrics is not None:
        expected_warning_indices = [r['index'] for r in expected_metrics['sentences'] if r['is_long']]
        exp_set = set(expected_warning_indices)
        nums = set(extract_ints(warnings_content))
        if exp_set.issubset(nums):
            scores["warnings_section_lists_trigger_indices"] = 1.0

    # Hard words section: unique words >= 12 letters
    hard_content = find_section_content(sections, required_sections_variants["hard words i noticed"])
    if hard_content is not None and chapter_text is not None:
        expected_hard = set(unique_case_insensitive_words_ge_length(chapter_text, 12))
        listed_hard = set(unique_case_insensitive_words_ge_length(hard_content, 12))
        if listed_hard == expected_hard:
            scores["hard_words_section_correct"] = 1.0

    # Summary JSON validation
    summary_json, _ = load_json_safe(summary_json_path)
    if summary_json is not None:
        schema_ok = True
        if not isinstance(summary_json, dict):
            schema_ok = False
        else:
            longest = summary_json.get("longest_sentences")
            warn_count = summary_json.get("warning_count")
            if not (isinstance(longest, list) and len(longest) == 3 and isinstance(warn_count, int)):
                schema_ok = False
            else:
                for item in longest:
                    if not isinstance(item, dict):
                        schema_ok = False
                        break
                    if not all(k in item for k in ("index", "word_count", "original", "simplified")):
                        schema_ok = False
                        break
                    if not (isinstance(item["index"], int) and isinstance(item["word_count"], int)
                            and isinstance(item["original"], str) and isinstance(item["simplified"], str)
                            and len(item["simplified"].strip()) > 0):
                        schema_ok = False
                        break
        if schema_ok:
            scores["summary_json_schema_valid"] = 1.0

    # Summary JSON longest match and warning count match
    if summary_json is not None and expected_metrics is not None and scores["summary_json_schema_valid"] == 1.0:
        top3 = top_n_longest_sentences(expected_metrics, 3)
        expected_triplets = [(r['index'], r['word_count'], r['text']) for r in top3]
        got_triplets = [(it['index'], it['word_count'], it['original']) for it in summary_json["longest_sentences"]]
        # We require exact set equality disregarding order? The task says the top three must exactly match the three longest.
        # We'll accept any order but exact same 3 items.
        if set(expected_triplets) == set(got_triplets):
            # Also ensure simplified texts are indeed simpler: shorter word count
            simpler_ok = True
            for it in summary_json["longest_sentences"]:
                orig_wc = count_words(it["original"])
                simp_wc = count_words(it["simplified"])
                if not (simp_wc < orig_wc and simp_wc > 0):
                    simpler_ok = False
                    break
            if simpler_ok:
                scores["summary_json_longest_match"] = 1.0
        # warning_count match
        expected_warning_count = sum(1 for r in expected_metrics['sentences'] if r['is_long'])
        if summary_json.get("warning_count") == expected_warning_count:
            scores["summary_json_warning_count_match"] = 1.0

    # Email checks
    email_text, _ = read_text_safe(email_path)
    if email_text is not None:
        lines = email_text.splitlines()
        subject_ok = False
        length_ok = False
        body_text = ""
        if lines:
            subject_line = lines[0].strip()
            subject_ok = subject_line.lower().startswith("subject:") and ("kid beta feedback" in subject_line.lower()) and ("chapter 1" in subject_line.lower())
            body_text = "\n".join(lines[1:]).strip()
        # Count words in body
        body_tokens = tokenize_words(body_text)
        if 120 <= len(body_tokens) <= 180:
            length_ok = True
        # Aggregate
        subj_len_score = 0.0
        if subject_ok and length_ok:
            subj_len_score = 1.0
        elif subject_ok or length_ok:
            subj_len_score = 0.5
        else:
            subj_len_score = 0.0
        scores["email_subject_and_length"] = subj_len_score

        # Required elements in email body
        conditions = []
        # mentions attachments
        conditions.append("output/feedback_report.md" in body_text)
        conditions.append("output/readability_summary.json" in body_text)
        # mentions liked
        conditions.append(re.search(r'\bliked\b', body_text, flags=re.IGNORECASE) is not None)
        # mentions confused/confusing
        conditions.append(re.search(r'\bconfus', body_text, flags=re.IGNORECASE) is not None)
        # mentions at least one or two long sentences by index, e.g., "Sentence 3" or "Sentence 7"
        has_sentence_ref = re.search(r'\bSentence\s+\d+\b', body_text, flags=re.IGNORECASE) is not None
        conditions.append(has_sentence_ref)
        # Score as ratio of satisfied conditions
        satisfied = sum(1 for c in conditions if c)
        scores["email_mentions_required_elements"] = satisfied / float(len(conditions))

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()