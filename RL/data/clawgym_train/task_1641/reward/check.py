import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _tokenize_words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9]+", text.lower())


def _extract_headings_with_spans(text: str) -> List[Tuple[str, int]]:
    headings = []
    for i, line in enumerate(text.splitlines()):
        m = re.match(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", line)
        if m:
            title = m.group(1).strip()
            headings.append((title, i))
    return headings


def _sections_map(text: str) -> Dict[str, str]:
    lines = text.splitlines()
    headings = _extract_headings_with_spans(text)
    sections = {}
    for idx, (title, start_line) in enumerate(headings):
        end_line = len(lines)
        if idx + 1 < len(headings):
            end_line = headings[idx + 1][1]
        content = "\n".join(lines[start_line + 1:end_line]).strip()
        sections[title] = content
    return sections


def _count_bullets(section_text: str) -> int:
    count = 0
    for line in section_text.splitlines():
        if re.match(r"^\s*[-*]\s+", line):
            count += 1
    return count


def _split_paragraphs(text: str) -> List[str]:
    paras = []
    current = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                paras.append("\n".join(current).strip())
                current = []
        else:
            current.append(line)
    if current:
        paras.append("\n".join(current).strip())
    return paras


def _word_count(text: str) -> int:
    return len(_tokenize_words(text))


def _find_5gram_overlap(notes_text: str, target_text: str) -> List[Tuple[str, int]]:
    notes_tokens = _tokenize_words(notes_text)
    target_tokens = _tokenize_words(target_text)
    if len(notes_tokens) < 5 or len(target_tokens) < 5:
        return []
    notes_ngrams = set()
    for i in range(len(notes_tokens) - 4):
        gram = tuple(notes_tokens[i:i+5])
        notes_ngrams.add(gram)
    overlaps = []
    for j in range(len(target_tokens) - 4):
        gram = tuple(target_tokens[j:j+5])
        if gram in notes_ngrams:
            overlaps.append((" ".join(gram), j))
    return overlaps


def _load_rules(workspace: Path) -> Optional[Dict]:
    cfg = workspace / "config" / "style_rules.json"
    return _load_json_safe(cfg)


def _check_avoid_terms(text: str, rules: Dict) -> Dict:
    avoid_terms = rules.get("avoid_terms", [])
    text_norm = text.lower()
    found = set()
    for term in avoid_terms:
        t = str(term).lower()
        if t and t in text_norm:
            found.add(term)
    violations = sorted(found, key=lambda x: x.lower())
    return {"violations": violations, "ok": len(violations) == 0}


def _import_tone_checker(workspace: Path):
    tools_dir = workspace / "tools"
    if tools_dir.exists():
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))
        try:
            import tone_checker  # type: ignore
            return tone_checker
        except Exception:
            return None
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_contains_new_terms": 0.0,
        "config_retains_existing_terms": 0.0,
        "config_valid_json_after_update": 0.0,
        "revised_messages_sections_present": 0.0,
        "revised_messages_length_constraints": 0.0,
        "revised_messages_avoid_terms_clean": 0.0,
        "status_summary_structure": 0.0,
        "status_summary_summary_paragraph_single": 0.0,
        "status_summary_bullet_counts": 0.0,
        "status_summary_word_count": 0.0,
        "status_summary_paraphrase_no_5gram": 0.0,
        "status_summary_avoid_terms_clean": 0.0,
        "email_structure_subject_and_greeting": 0.0,
        "email_paragraph_count": 0.0,
        "email_needs_from_editor_present": 0.0,
        "email_avoid_terms_clean": 0.0,
        "tests_flagging_sample_implemented": 0.0,
        "tests_outputs_are_clean_implemented": 0.0,
    }

    # Load rules
    rules = _load_rules(workspace)
    if rules is None:
        rules = {"avoid_terms": []}

    # Check config updates: must include new terms in addition to existing entries
    expected_existing = {"outrage", "brutal", "terrorist"}
    expected_new = {"slammed", "shocking"}
    avoid_terms_list = [str(t) for t in rules.get("avoid_terms", [])]
    avoid_terms_lower = {t.lower() for t in avoid_terms_list}

    has_new = expected_new.issubset(avoid_terms_lower)
    has_existing = expected_existing.issubset(avoid_terms_lower)

    if has_new:
        scores["config_contains_new_terms"] = 1.0
    if has_new and has_existing:
        scores["config_retains_existing_terms"] = 1.0
        # Consider JSON valid after update only if it's valid JSON and includes updates
        # We already parsed JSON successfully; tie validity to presence of required terms to avoid baseline credit.
        scores["config_valid_json_after_update"] = 1.0

    # Prepare tone checker for consistent rule application
    tone_checker = _import_tone_checker(workspace)

    def check_text(text: str) -> Dict:
        if tone_checker is not None:
            try:
                return tone_checker.check_text(text, rules)  # type: ignore
            except Exception:
                return _check_avoid_terms(text, rules)
        return _check_avoid_terms(text, rules)

    # Deliverable 1: outputs/revised_messages.md
    revised_path = workspace / "outputs" / "revised_messages.md"
    revised_text = _read_text_safe(revised_path) or ""
    if revised_text:
        sections = _sections_map(revised_text)
        push_title = next((t for t in sections.keys() if t.strip().lower() == "rewritten push"), None)
        social_title = next((t for t in sections.keys() if t.strip().lower() == "rewritten social"), None)
        if push_title and social_title:
            push_content = sections.get(push_title, "").strip()
            social_content = sections.get(social_title, "").strip()
            if push_content and social_content:
                scores["revised_messages_sections_present"] = 1.0
                # Length constraints: <= 240 characters each and non-empty
                if len(push_content) <= 240 and len(social_content) <= 240:
                    scores["revised_messages_length_constraints"] = 1.0
                # Avoid terms clean for both
                if check_text(push_content).get("ok", False) and check_text(social_content).get("ok", False):
                    scores["revised_messages_avoid_terms_clean"] = 1.0

    # Deliverable 2: outputs/status_summary.md
    summary_path = workspace / "outputs" / "status_summary.md"
    status_text = _read_text_safe(summary_path) or ""
    if status_text:
        # Structure: "Summary", "Key Developments", "Risks & Caveats" in order
        headings = _extract_headings_with_spans(status_text)
        titles_in_order = [t for t, _ in headings]
        lower_titles = [t.strip().lower() for t in titles_in_order]
        try:
            idx_summary = lower_titles.index("summary")
            idx_keys = lower_titles.index("key developments")
            idx_risks = lower_titles.index("risks & caveats")
            if idx_summary < idx_keys < idx_risks:
                scores["status_summary_structure"] = 1.0
        except ValueError:
            pass

        sections = _sections_map(status_text)
        summary_content = None
        keys_content = None
        risks_content = None
        for title, content in sections.items():
            tl = title.strip().lower()
            if tl == "summary":
                summary_content = content.strip()
            elif tl == "key developments":
                keys_content = content.strip()
            elif tl == "risks & caveats":
                risks_content = content.strip()

        if summary_content is not None:
            paras = _split_paragraphs(summary_content)
            if len(paras) == 1 and paras[0]:
                scores["status_summary_summary_paragraph_single"] = 1.0

        if keys_content is not None and risks_content is not None:
            keys_bullets = _count_bullets(keys_content)
            risks_bullets = _count_bullets(risks_content)
            if 3 <= keys_bullets <= 5 and 2 <= risks_bullets <= 3:
                scores["status_summary_bullet_counts"] = 1.0

        # Word count 150–220 excluding headings
        non_heading_lines = []
        for line in status_text.splitlines():
            if re.match(r"^\s{0,3}#{1,6}\s*", line):
                continue
            non_heading_lines.append(line)
        wc = _word_count("\n".join(non_heading_lines))
        if 150 <= wc <= 220:
            scores["status_summary_word_count"] = 1.0

        # Avoid terms clean
        if check_text(status_text).get("ok", False):
            scores["status_summary_avoid_terms_clean"] = 1.0

        # Paraphrase: no copied sequences ≥ 5 consecutive words from input/notes.md
        notes_path = workspace / "input" / "notes.md"
        notes_text = _read_text_safe(notes_path) or ""
        if notes_text:
            overlaps = _find_5gram_overlap(notes_text, status_text)
            if len(overlaps) == 0:
                scores["status_summary_paraphrase_no_5gram"] = 1.0

    # Deliverable 3: outputs/email_to_editor.md
    email_path = workspace / "outputs" / "email_to_editor.md"
    email_text = _read_text_safe(email_path) or ""
    if email_text:
        lines = email_text.splitlines()
        # Must start with "Subject: "
        if len(lines) > 0 and lines[0].startswith("Subject: "):
            # Greeting: first non-empty line after subject starts with Hi/Hello/Dear
            greeting_ok = False
            greeting_idx = None
            for i in range(1, len(lines)):
                if lines[i].strip() == "":
                    continue
                if re.match(r"^(Hi|Hello|Dear)\b", lines[i].strip(), flags=re.IGNORECASE):
                    greeting_ok = True
                    greeting_idx = i
                break
            if greeting_ok:
                scores["email_structure_subject_and_greeting"] = 1.0

            # Paragraphs: 2–3 short paragraphs after greeting
            body_lines = lines[greeting_idx + 1 :] if greeting_idx is not None else lines[1:]
            body_text = "\n".join(body_lines).strip()
            paras = [p for p in _split_paragraphs(body_text) if p.strip() != ""]
            if 2 <= len(paras) <= 3:
                scores["email_paragraph_count"] = 1.0

            # One paragraph should include what is needed from editor: keywords present
            need_keywords = {"decision", "timing", "clearance"}
            need_ok = False
            for p in paras:
                pl = p.lower()
                if any(kw in pl for kw in need_keywords):
                    need_ok = True
                    break
            if need_ok:
                scores["email_needs_from_editor_present"] = 1.0

        # Avoid terms clean
        if check_text(email_text).get("ok", False):
            scores["email_avoid_terms_clean"] = 1.0

    # Tests: tests/test_tone_checker.py should be implemented
    tests_path = workspace / "tests" / "test_tone_checker.py"
    tests_text = _read_text_safe(tests_path) or ""
    if tests_text:
        has_test_flagging = bool(re.search(r"def\s+test_flagging_sample\s*\(", tests_text))
        has_test_outputs = bool(re.search(r"def\s+test_outputs_are_clean\s*\(", tests_text))
        placeholders_removed = "Replace with real assertions" not in tests_text

        contains_slammed = re.search(r"slammed", tests_text, flags=re.IGNORECASE) is not None
        contains_shocking = re.search(r"shocking", tests_text, flags=re.IGNORECASE) is not None
        uses_check_text = "check_text" in tests_text

        if has_test_flagging and placeholders_removed and contains_slammed and contains_shocking and uses_check_text:
            scores["tests_flagging_sample_implemented"] = 1.0

        references_outputs = (
            "outputs/revised_messages.md" in tests_text
            and "outputs/status_summary.md" in tests_text
            and "outputs/email_to_editor.md" in tests_text
        )
        zero_violation_patterns = [
            r"len\(\s*result\s*\[\s*['\"]violations['\"]\s*\]\s*\)\s*==\s*0",
            r"assertEqual\(\s*len\(\s*result\s*\[\s*['\"]violations['\"]\s*\]\s*\)\s*,\s*0",
            r"assertTrue\(\s*result\s*\[\s*['\"]ok['\"]\s*\]\s*\)",
        ]
        zero_assert_present = any(re.search(p, tests_text) for p in zero_violation_patterns)
        if has_test_outputs and placeholders_removed and references_outputs and uses_check_text and zero_assert_present:
            scores["tests_outputs_are_clean_implemented"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()