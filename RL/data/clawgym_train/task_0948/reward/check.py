import json
import os
import re
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
    except Exception:
        return None

def parse_csv(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def find_section_bounds(lines, start_heading, next_headings):
    """
    Return (start_index_exclusive, end_index_exclusive) for the section content.
    start_heading should match a full line. next_headings is a list of headings to mark the end.
    """
    try:
        start_idx = None
        for i, line in enumerate(lines):
            if line.strip() == start_heading:
                start_idx = i
                break
        if start_idx is None:
            return None, None
        # find next heading index
        end_idx = len(lines)
        for i in range(start_idx + 1, len(lines)):
            if lines[i].startswith("## "):
                # if this is one of the known next headings or any following section
                # we stop at the first encountered "## " after start
                end_idx = i
                break
        return start_idx + 1, end_idx
    except Exception:
        return None, None

def extract_reading_translation(lines, start_idx, end_idx):
    """
    Within the given range, locate "Reading (JP):" and "Translation (EN):".
    Return dict with keys:
      has_reading_label (bool),
      has_translation_label (bool),
      translation_text (str),
      key_points_count (int)
    Translation text is captured from the line after "Translation (EN):" up to
    before the first bullet "- " line or before a new section heading or end_idx.
    Key points are counted as lines starting with "- " after the translation block and before end_idx.
    """
    sub = lines[start_idx:end_idx]
    has_reading_label = any(line.strip() == "Reading (JP):" for line in sub)
    trans_label_idx = None
    for i, line in enumerate(sub):
        if line.strip() == "Translation (EN):":
            trans_label_idx = i
            break
    has_translation_label = trans_label_idx is not None
    translation_text = ""
    key_points_count = 0
    if has_translation_label:
        # translation starts after label
        t_start = trans_label_idx + 1
        t_end = len(sub)
        # stop translation before first "- " bullet or before next "## " (shouldn't appear inside)
        for j in range(t_start, len(sub)):
            if sub[j].startswith("- "):
                t_end = j
                break
            if sub[j].startswith("## "):
                t_end = j
                break
        # collect translation lines
        translation_text = "\n".join(sub[t_start:t_end]).strip()
        # count key points bullets after t_end until end_idx or until a new section heading
        for j in range(t_end, len(sub)):
            if sub[j].startswith("## "):
                break
            if sub[j].startswith("- "):
                key_points_count += 1
    return {
        "has_reading_label": has_reading_label,
        "has_translation_label": has_translation_label,
        "translation_text": translation_text,
        "key_points_count": key_points_count,
    }

def count_words(text):
    # Count words by splitting on whitespace; filter out empty tokens
    tokens = re.findall(r"\b[\w'-]+\b", text)
    return len(tokens)

def is_non_ascii_present(s):
    return any(ord(ch) > 127 for ch in s)

def normalize_list_casefold(seq):
    # Return list of lowercased, stripped items excluding empties
    return [x.strip().casefold() for x in seq if isinstance(x, str) and x.strip() != ""]

def csv_header_matches(header_row):
    expected = ["word", "furigana", "romaji", "meaning"]
    got = [h.strip().lower() for h in header_row]
    return got == expected

def get_vocab_section_lines(lines):
    start, end = find_section_bounds(lines, "## Vocabulary (10 items)", [])
    if start is None:
        return []
    # end is determined by next "## " heading inside find_section_bounds
    return lines[start:end]

def get_quiz_section_bounds(lines):
    start, end = find_section_bounds(lines, "## Quick quiz (5 questions)", [])
    return start, end

def get_kanji_json_valid(arr):
    if not isinstance(arr, list) or len(arr) != 3:
        return False
    for obj in arr:
        if not isinstance(obj, dict):
            return False
        # required keys
        for key in ["character", "on", "kun", "stroke_count", "compounds", "example"]:
            if key not in obj:
                return False
        # character: non-empty, non-ASCII
        if not isinstance(obj["character"], str) or obj["character"].strip() == "" or not is_non_ascii_present(obj["character"]):
            return False
        # on/kun arrays
        if not isinstance(obj["on"], list) or not isinstance(obj["kun"], list):
            return False
        # stroke_count integer
        if not isinstance(obj["stroke_count"], int):
            return False
        # compounds array length 2
        if not isinstance(obj["compounds"], list) or len(obj["compounds"]) != 2:
            return False
        # example string
        if not isinstance(obj["example"], str) or obj["example"].strip() == "":
            return False
    return True

def check_headings_order(lines):
    required = [
        "## Vocabulary (10 items)",
        "## Grammar pattern of the day",
        "## Kanji focus (3 kanji)",
        "## Reading passage",
        "## Listening/speaking prompt",
        "## Quick quiz (5 questions)",
        "## Cultural note",
    ]
    positions = []
    for req in required:
        pos = None
        for i, line in enumerate(lines):
            if line.strip() == req:
                pos = i
                break
        if pos is None:
            return False
        positions.append(pos)
    # ensure strictly increasing order
    for i in range(1, len(positions)):
        if positions[i] <= positions[i - 1]:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Prepare checks dict with defaults False
    checks = {
        "has_session_md": False,
        "has_vocab_csv": False,
        "has_kanji_json": False,
        "has_metadata_json": False,
        "headings_order_ok": False,
        "vocab_numbering_1_to_10": False,
        "csv_header_ok": False,
        "csv_rows_10": False,
        "kanji_json_valid": False,
        "metadata_valid": False,
        "metadata_counts_match": False,
        "focus_topics_copied": False,
        "avoided_terms_copied": False,
        "focus_topic_woven": False,
        "avoided_terms_absent": False,
        "reading_labels_present": False,
        "translation_word_count_ok": False,
        "reading_key_points_3": False,
        "quiz_structure_ok": False,
        "counts_consistent": False,
    }

    # Load inputs (reference)
    learner_profile_path = os.path.join(input_dir, "learner_profile.json")
    prev_keywords_path = os.path.join(input_dir, "previous_session_keywords.txt")

    learner_profile = read_json(learner_profile_path) or {}
    input_focus_topics = learner_profile.get("focus_topics", [])
    input_focus_topics_norm = normalize_list_casefold(input_focus_topics)

    prev_keywords_lines = read_lines(prev_keywords_path) or []
    input_avoided_terms = [line.strip() for line in prev_keywords_lines if line.strip() != ""]
    input_avoided_norm = normalize_list_casefold(input_avoided_terms)

    # Load outputs
    session_md_path = os.path.join(output_dir, "session.md")
    vocab_csv_path = os.path.join(output_dir, "vocab.csv")
    kanji_json_path = os.path.join(output_dir, "kanji.json")
    metadata_json_path = os.path.join(output_dir, "metadata.json")

    session_text = read_text(session_md_path)
    if session_text is not None:
        checks["has_session_md"] = True
        lines = session_text.splitlines()
        # Headings order
        checks["headings_order_ok"] = check_headings_order(lines)
        # Vocabulary numbering in section
        vocab_lines = get_vocab_section_lines(lines)
        numbers_found = []
        for ln in vocab_lines:
            # exact start with N. (1..10)
            m = re.match(r'^(10|[1-9])\.\s', ln)
            if m:
                numbers_found.append(int(m.group(1)))
        if len(numbers_found) == 10 and sorted(numbers_found) == list(range(1, 11)):
            # also ensure uniqueness and sequential presence
            checks["vocab_numbering_1_to_10"] = True

        # Reading passage checks
        # Bounds of reading passage section
        rp_start, rp_end = find_section_bounds(lines, "## Reading passage", [])
        if rp_start is not None:
            rt_info = extract_reading_translation(lines, rp_start, rp_end)
            checks["reading_labels_present"] = rt_info["has_reading_label"] and rt_info["has_translation_label"]
            # Translation word count between 80 and 200 inclusive
            if rt_info["translation_text"]:
                word_count = count_words(rt_info["translation_text"])
                if 80 <= word_count <= 200:
                    checks["translation_word_count_ok"] = True
            # Exactly 3 key point bullets
            if rt_info["key_points_count"] == 3:
                checks["reading_key_points_3"] = True

        # Quiz structure
        q_start, q_end = get_quiz_section_bounds(lines)
        if q_start is not None:
            quiz_lines = lines[q_start:q_end]
            # Find Q lines
            q_lines = [ln for ln in quiz_lines if re.match(r'^Q[1-5]:', ln)]
            # Ensure exactly one each Q1..Q5
            q_ids = [ln.split(":", 1)[0] for ln in q_lines]
            expected_q = [f"Q{i}" for i in range(1, 6)]
            q_ok = (len(q_lines) == 5) and all(qid in q_ids for qid in expected_q) and len(set(q_ids)) == 5

            # Divider '-----' between last Q and first A
            divider_positions = [i for i, ln in enumerate(quiz_lines) if ln.strip() == "-----"]
            # A lines
            a_lines = [ln for ln in quiz_lines if re.match(r'^A[1-5]:', ln)]
            a_ids = [ln.split(":", 1)[0] for ln in a_lines]
            expected_a = [f"A{i}" for i in range(1, 6)]
            a_ok = (len(a_lines) == 5) and all(aid in a_ids for aid in expected_a) and len(set(a_ids)) == 5

            divider_ok = False
            if q_ok and a_ok and divider_positions:
                # ensure divider appears after all Q lines and before any A line
                last_q_idx = max(i for i, ln in enumerate(quiz_lines) if re.match(r'^Q[1-5]:', ln))
                first_a_idx = min(i for i, ln in enumerate(quiz_lines) if re.match(r'^A[1-5]:', ln))
                # pick any divider that is between
                divider_ok = any(last_q_idx < dpos < first_a_idx for dpos in divider_positions)

            checks["quiz_structure_ok"] = q_ok and a_ok and divider_ok

        # Focus topics woven and avoided terms absent
        sess_lower = session_text.casefold()
        focus_topic_present = False
        for t in input_focus_topics_norm:
            if t and t in sess_lower:
                focus_topic_present = True
                break
        checks["focus_topic_woven"] = focus_topic_present

        avoided_absent = True
        for term in input_avoided_norm:
            if term and term in sess_lower:
                avoided_absent = False
                break
        checks["avoided_terms_absent"] = avoided_absent

    # CSV checks
    csv_rows = parse_csv(vocab_csv_path)
    if csv_rows is not None and len(csv_rows) >= 1:
        checks["has_vocab_csv"] = True
        header_ok = csv_header_matches(csv_rows[0])
        checks["csv_header_ok"] = header_ok
        data_rows = csv_rows[1:]
        checks["csv_rows_10"] = len(data_rows) == 10

    # Kanji JSON checks
    kanji_arr = read_json(kanji_json_path)
    if kanji_arr is not None:
        checks["has_kanji_json"] = True
        checks["kanji_json_valid"] = get_kanji_json_valid(kanji_arr)

    # Metadata checks
    metadata = read_json(metadata_json_path)
    if metadata is not None and isinstance(metadata, dict):
        checks["has_metadata_json"] = True
        # Basic fields validity
        level_ok = metadata.get("level") == "N3"
        vocab_count = metadata.get("vocabulary_count")
        kanji_count = metadata.get("kanji_count")
        quiz_count = metadata.get("quiz_count")
        focus_topics_md = metadata.get("focus_topics")
        avoided_terms_md = metadata.get("avoided_terms")
        format_version = metadata.get("format_version")
        compliance_notes = metadata.get("compliance_notes")

        basic_counts_ok = isinstance(vocab_count, int) and isinstance(kanji_count, int) and isinstance(quiz_count, int)
        focus_topics_ok = isinstance(focus_topics_md, list) and len(focus_topics_md) >= 1
        avoided_terms_ok = isinstance(avoided_terms_md, list) and len(avoided_terms_md) >= 1
        format_version_ok = isinstance(format_version, str)
        compliance_ok = isinstance(compliance_notes, str)

        checks["metadata_valid"] = all([level_ok, basic_counts_ok, focus_topics_ok, avoided_terms_ok, format_version_ok, compliance_ok])

        # Exact required counts
        counts_match = (vocab_count == 10) and (kanji_count == 3) and (quiz_count == 5)
        checks["metadata_counts_match"] = counts_match

        # Compare to input refs (case-insensitive sets)
        md_focus_norm = normalize_list_casefold(focus_topics_md if isinstance(focus_topics_md, list) else [])
        md_avoid_norm = normalize_list_casefold(avoided_terms_md if isinstance(avoided_terms_md, list) else [])

        checks["focus_topics_copied"] = set(md_focus_norm) == set(input_focus_topics_norm) and len(md_focus_norm) == len(set(md_focus_norm)) and len(md_focus_norm) >= 1
        checks["avoided_terms_copied"] = set(md_avoid_norm) == set(input_avoided_norm) and len(md_avoid_norm) == len(set(md_avoid_norm)) and len(md_avoid_norm) >= 1

        # Cross-file counts consistency
        csv_count = None
        if csv_rows is not None and len(csv_rows) >= 1:
            csv_count = len(csv_rows) - 1
        kanji_len = None
        if isinstance(kanji_arr, list):
            kanji_len = len(kanji_arr)
        quiz_ok = checks["quiz_structure_ok"]  # implies 5 Q + 5 A lines

        counts_consistent = True
        if csv_count is None or vocab_count is None or csv_count != vocab_count:
            counts_consistent = False
        if kanji_len is None or kanji_count is None or kanji_len != kanji_count:
            counts_consistent = False
        # quiz_count must be 5 and quiz structure ok
        if quiz_count != 5 or not quiz_ok:
            counts_consistent = False

        checks["counts_consistent"] = counts_consistent

    # Compute reward: fraction of checks passed over total checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # Ensure no-op baseline: if no required outputs exist, reward must be 0.0
    required_outputs_exist = checks["has_session_md"] or checks["has_vocab_csv"] or checks["has_kanji_json"] or checks["has_metadata_json"]
    if not required_outputs_exist:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print exactly one JSON object with "reward" first
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()