import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def word_count(text: str) -> int:
    words = re.findall(r"\b\w+(?:[-']\w+)?\b", text)
    return len(words)


def parse_yaml_priorities(yaml_text: Optional[str]) -> List[str]:
    if not yaml_text:
        return []
    lines = yaml_text.splitlines()
    priorities: List[str] = []
    in_list = False
    base_indent = None
    for i, line in enumerate(lines):
        if not in_list:
            if re.match(r"^\s*priorities\s*:\s*$", line):
                in_list = True
                # Determine base indent from next non-empty line if possible
                continue
        else:
            if re.match(r"^\s*-\s+", line):
                # Record indent for first item
                if base_indent is None:
                    m = re.match(r"^(\s*)-\s+(.*)$", line)
                    if m:
                        base_indent = len(m.group(1))
                        priorities.append(m.group(2).strip())
                    else:
                        continue
                else:
                    m = re.match(r"^\s*-\s+(.*)$", line)
                    if m:
                        priorities.append(m.group(1).strip())
            else:
                # If we've started reading list items and encounter a non-list line at same or lower indent, stop
                if base_indent is not None:
                    # If the line starts with more indent and a dash, still part of list; else break
                    if not re.match(r"^\s*-\s+", line):
                        break
    return priorities


def extract_sections(memo_text: str, headings: List[str]) -> Tuple[Dict[str, str], List[str]]:
    sections: Dict[str, str] = {}
    lines = memo_text.splitlines()
    header_lines: List[str] = []
    # Capture the first four non-empty lines as header lines (expected Title, Author, Date, Decision ID)
    for line in lines:
        if line.strip():
            header_lines.append(line.rstrip("\n"))
        if len(header_lines) >= 4:
            break

    # Build section map
    current_heading: Optional[str] = None
    buffer: List[str] = []
    heading_set = set(headings)
    for line in lines:
        stripped = line.strip()
        if stripped in heading_set:
            if current_heading is not None:
                sections[current_heading] = "\n".join(buffer).strip()
                buffer = []
            current_heading = stripped
        else:
            if current_heading is not None:
                buffer.append(line)
    if current_heading is not None:
        sections[current_heading] = "\n".join(buffer).strip()
    return sections, header_lines


def get_bullets(section_text: str) -> List[str]:
    bullets: List[str] = []
    for line in section_text.splitlines():
        s = line.lstrip()
        if s.startswith("- ") or s.startswith("* ") or s.startswith("• "):
            bullets.append(s)
    return bullets


def find_quotes(text: str) -> List[str]:
    quotes: List[str] = []
    # double quotes
    quotes += re.findall(r'"([^"]+)"', text)
    # single quotes
    quotes += re.findall(r"'([^']+)'", text)
    # curly quotes
    quotes += re.findall(r"“([^”]+)”", text)
    quotes += re.findall(r"‘([^’]+)’", text)
    # Deduplicate while preserving order
    seen = set()
    result = []
    for q in quotes:
        if q not in seen:
            seen.add(q)
            result.append(q)
    return result


def find_paths_in_parentheses(text: str) -> List[str]:
    return re.findall(r"\(([^)]+)\)", text)


def quote_within_word_limit(q: str, max_words: int = 20) -> bool:
    return word_count(q) <= max_words


def contains_recommendation_phrase(text: str) -> bool:
    t = text.lower()
    if "enroll with conditions" in t:
        return True
    if "do not enroll" in t:
        return True
    # If plain 'enroll' occurs but not 'do not enroll'
    if re.search(r"\benroll\b", t) and "do not enroll" not in t:
        return True
    return False


def section_contains_sources(section_text: str, required_paths: List[str]) -> bool:
    present = set()
    for p in find_paths_in_parentheses(section_text):
        if p in required_paths:
            present.add(p)
    return all(rp in present for rp in required_paths)


def find_priority_lines(section_text: str, priority: str) -> List[str]:
    lines = section_text.splitlines()
    hits = []
    for i, line in enumerate(lines):
        if priority.lower() in line.lower():
            # include this line and possibly the next line to allow justification across a wrapped line
            hits.append(line)
            if i + 1 < len(lines):
                hits.append(lines[i + 1])
    return hits


def has_file_reference(text: str, files: List[str]) -> bool:
    for p in find_paths_in_parentheses(text):
        if p in files:
            return True
    return False


def extract_exec_summary_text(sections: Dict[str, str], heading: str) -> str:
    if heading not in sections:
        return ""
    # Exec summary is the text under the heading until next heading; we've already isolated
    return sections[heading].strip()


def parse_email_questions(lines: List[str]) -> List[str]:
    questions: List[str] = []
    for line in lines:
        s = line.strip()
        if re.match(r"^(?:\d+[\.\)])\s+", s):
            questions.append(s)
    return questions


def quotes_and_paths_from_line(line: str) -> Tuple[List[str], List[str]]:
    return find_quotes(line), [p.strip() for p in find_paths_in_parentheses(line)]


def quotes_match_sources(quotes: List[str], paths: List[str], file_texts: Dict[str, Optional[str]]) -> bool:
    # Return True if at least one (quote, path) pair is valid for given file content
    ok_any = False
    for p in paths:
        if p in file_texts and file_texts[p]:
            content = file_texts[p]
            for q in quotes:
                if q and content and q in content:
                    ok_any = True
    return ok_any


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Expected input file paths
    brochure_path = workspace / "input" / "wellness_brochure.txt"
    consent_path = workspace / "input" / "consent_form.txt"
    privacy_path = workspace / "input" / "privacy_policy.txt"
    priorities_yaml_path = workspace / "input" / "personal_priorities.yaml"
    original_memo_path = workspace / "input" / "personal_decision_memo.md"

    # Expected outputs
    output_memo_path = workspace / "outputs" / "memo" / "personal_wellness_decision.md"
    output_email_path = workspace / "outputs" / "communications" / "email_to_bioethicist.txt"

    brochure_text = read_text_file(brochure_path)
    consent_text = read_text_file(consent_path)
    privacy_text = read_text_file(privacy_path)
    priorities_yaml = read_text_file(priorities_yaml_path)
    original_memo_text = read_text_file(original_memo_path)
    output_memo_text = read_text_file(output_memo_path)
    output_email_text = read_text_file(output_email_path)

    # Prepare inputs availability map for quote validations
    file_texts = {
        "input/wellness_brochure.txt": brochure_text,
        "input/consent_form.txt": consent_text,
        "input/privacy_policy.txt": privacy_text,
    }

    # Parse priorities from YAML
    priorities_list = parse_yaml_priorities(priorities_yaml)

    # Sections expected in memo
    required_headings = [
        "Executive Summary",
        "Key Benefits",
        "Key Risks & Privacy Considerations",
        "Fit with Personal Priorities",
        "Data Handling Facts",
        "Discrepancies/Questions to Resolve",
        "Recommendation & Next Steps",
    ]

    # Original header lines (Title, Author, Date, Decision ID) from input memo
    original_header_lines: List[str] = []
    if original_memo_text:
        lines = [ln.rstrip("\n") for ln in original_memo_text.splitlines()]
        for line in lines:
            if line.strip():
                original_header_lines.append(line)
            if len(original_header_lines) >= 4:
                break

    scores = {
        # Memo existence and structure
        "memo_file_exists": 1.0 if output_memo_text is not None else 0.0,
        "memo_header_preserved_exact": 0.0,
        "memo_no_todo_placeholders": 0.0,
        "memo_has_all_required_headings": 0.0,
        # Executive summary checks
        "exec_summary_within_120_words": 0.0,
        "exec_summary_contains_clear_recommendation": 0.0,
        # Benefits checks
        "benefits_exactly_three_bullets": 0.0,
        "benefits_each_has_valid_quote_and_source": 0.0,
        # Risks checks
        "risks_exactly_three_bullets": 0.0,
        "risks_each_has_valid_quote_and_source": 0.0,
        # Priorities mapping checks
        "priorities_all_covered": 0.0,
        "priorities_each_has_supports_or_conflicts_and_reference": 0.0,
        # Data handling facts checks
        "data_facts_include_data_types": 0.0,
        "data_facts_include_retention_with_both_sources": 0.0,
        "data_facts_include_third_party_sharing": 0.0,
        # Discrepancies checks
        "discrepancies_include_retention_conflict": 0.0,
        "discrepancies_include_deletion_timeline_conflict": 0.0,
        # Recommendation section
        "recommendation_section_contains_decision": 0.0,
        # Email checks
        "email_file_exists": 1.0 if output_email_text is not None else 0.0,
        "email_subject_exact": 0.0,
        "email_greeting_present": 0.0,
        "email_summary_2_to_3_sentences": 0.0,
        "email_summary_mentions_recommendation_and_tradeoff": 0.0,
        "email_three_numbered_questions": 0.0,
        "email_questions_have_quotes_and_sources": 0.0,
        "email_questions_quotes_match_files": 0.0,
        "email_body_within_250_words": 0.0,
    }

    # If memo exists, perform detailed checks
    if output_memo_text:
        sections, header_lines = extract_sections(output_memo_text, required_headings)

        # Header preserved exact (compare to original's first four non-empty lines)
        if original_header_lines and len(header_lines) >= 4:
            scores["memo_header_preserved_exact"] = 1.0 if header_lines[:4] == original_header_lines[:4] else 0.0
        else:
            scores["memo_header_preserved_exact"] = 0.0

        # No TODO placeholders
        scores["memo_no_todo_placeholders"] = 1.0 if "[TODO" not in output_memo_text else 0.0

        # All required headings present
        has_all = all(h in sections for h in required_headings)
        scores["memo_has_all_required_headings"] = 1.0 if has_all else 0.0

        # Executive Summary
        if "Executive Summary" in sections:
            exec_text = extract_exec_summary_text(sections, "Executive Summary")
            scores["exec_summary_within_120_words"] = 1.0 if word_count(exec_text) <= 120 and word_count(exec_text) > 0 else 0.0
            scores["exec_summary_contains_clear_recommendation"] = 1.0 if contains_recommendation_phrase(exec_text) else 0.0

        # Key Benefits
        if "Key Benefits" in sections:
            benefits_bullets = get_bullets(sections["Key Benefits"])
            scores["benefits_exactly_three_bullets"] = 1.0 if len(benefits_bullets) == 3 else 0.0
            all_ok = True
            for b in benefits_bullets:
                quotes = find_quotes(b)
                parens = find_paths_in_parentheses(b)
                # require brochure source path
                has_source = "input/wellness_brochure.txt" in parens
                # at least one quote within 20 words and contained verbatim in brochure
                quote_ok = False
                if brochure_text:
                    for q in quotes:
                        if quote_within_word_limit(q, 20) and q in brochure_text:
                            quote_ok = True
                            break
                all_ok = all_ok and has_source and quote_ok
            scores["benefits_each_has_valid_quote_and_source"] = 1.0 if (len(benefits_bullets) == 3 and all_ok) else 0.0

        # Key Risks & Privacy Considerations
        if "Key Risks & Privacy Considerations" in sections:
            risks_bullets = get_bullets(sections["Key Risks & Privacy Considerations"])
            scores["risks_exactly_three_bullets"] = 1.0 if len(risks_bullets) == 3 else 0.0
            all_ok = True
            for b in risks_bullets:
                quotes = find_quotes(b)
                parens = find_paths_in_parentheses(b)
                # must include consent or privacy path and quote must be in that source
                # We will validate that at least one (quote, path) matches
                per_bullet_ok = False
                for p in parens:
                    if p in ("input/consent_form.txt", "input/privacy_policy.txt"):
                        src_text = file_texts.get(p)
                        if src_text:
                            for q in quotes:
                                if quote_within_word_limit(q, 20) and q in src_text:
                                    per_bullet_ok = True
                                    break
                    if per_bullet_ok:
                        break
                all_ok = all_ok and per_bullet_ok
            scores["risks_each_has_valid_quote_and_source"] = 1.0 if (len(risks_bullets) == 3 and all_ok) else 0.0

        # Fit with Personal Priorities
        if "Fit with Personal Priorities" in sections and priorities_list:
            section_text = sections["Fit with Personal Priorities"]
            covered_all = True
            refs_all = True
            for pr in priorities_list:
                hits = find_priority_lines(section_text, pr)
                if not hits:
                    covered_all = False
                    refs_all = False
                    continue
                # check supports or conflicts in at least one hit line
                has_label = any(re.search(r"\b(supports|conflicts)\b", h, re.IGNORECASE) for h in hits)
                # check a file reference appears in the hit lines
                has_ref = any(has_file_reference(h, list(file_texts.keys())) for h in hits)
                if not has_label:
                    covered_all = False
                if not has_ref:
                    refs_all = False
            scores["priorities_all_covered"] = 1.0 if covered_all else 0.0
            scores["priorities_each_has_supports_or_conflicts_and_reference"] = 1.0 if (covered_all and refs_all) else 0.0
        elif "Fit with Personal Priorities" in sections and not priorities_list:
            # If no priorities could be parsed, fail both checks
            scores["priorities_all_covered"] = 0.0
            scores["priorities_each_has_supports_or_conflicts_and_reference"] = 0.0

        # Data Handling Facts
        if "Data Handling Facts" in sections:
            dhf = sections["Data Handling Facts"]
            # Data types: expect mentions like steps, heart rate, sleep, questionnaire
            types_present = all(
                any(re.search(rf"\b{kw}\b", line, re.IGNORECASE) for line in dhf.splitlines())
                for kw in ["steps", "heart rate", "sleep", "questionnaire"]
            )
            scores["data_facts_include_data_types"] = 1.0 if types_present else 0.0

            # Retention with both sources (24 months from consent, 36 months from privacy)
            has_24 = "24 months" in dhf
            has_36 = "36 months" in dhf
            has_sources = section_contains_sources(dhf, ["input/consent_form.txt", "input/privacy_policy.txt"])
            scores["data_facts_include_retention_with_both_sources"] = 1.0 if (has_24 and has_36 and has_sources) else 0.0

            # Third-party sharing: expect phrases and at least one source reference
            sharing_keywords = [
                "third", "analytics", "research partners", "academic partners", "pseudonymous", "de-identified"
            ]
            sharing_present = any(k in dhf.lower() for k in sharing_keywords)
            sharing_has_source = any(p in find_paths_in_parentheses(dhf) for p in file_texts.keys())
            scores["data_facts_include_third_party_sharing"] = 1.0 if (sharing_present and sharing_has_source) else 0.0

        # Discrepancies/Questions to Resolve
        if "Discrepancies/Questions to Resolve" in sections:
            disc = sections["Discrepancies/Questions to Resolve"]
            # Retention conflict: 24 vs 36 months with sources
            has_24 = "24 months" in disc
            has_36 = "36 months" in disc
            has_sources = section_contains_sources(disc, ["input/consent_form.txt", "input/privacy_policy.txt"])
            scores["discrepancies_include_retention_conflict"] = 1.0 if (has_24 and has_36 and has_sources) else 0.0

            # Deletion timelines conflict: 45 days vs 30 days with sources
            has_45 = "45 days" in disc
            has_30 = "30 days" in disc
            has_sources_del = section_contains_sources(disc, ["input/consent_form.txt", "input/privacy_policy.txt"])
            scores["discrepancies_include_deletion_timeline_conflict"] = 1.0 if (has_45 and has_30 and has_sources_del) else 0.0

        # Recommendation & Next Steps
        if "Recommendation & Next Steps" in sections:
            rec_text = sections["Recommendation & Next Steps"]
            scores["recommendation_section_contains_decision"] = 1.0 if contains_recommendation_phrase(rec_text) else 0.0

    # Email checks
    if output_email_text:
        email_lines = output_email_text.splitlines()
        # Subject exact on first line
        expected_subject = "Subject: Quick review request: Workplace wellness program choice"
        scores["email_subject_exact"] = 1.0 if (len(email_lines) >= 1 and email_lines[0].strip() == expected_subject) else 0.0

        # Body greeting
        body_lines = email_lines[1:] if len(email_lines) > 1 else []
        # Skip blank lines to find greeting
        idx = 0
        while idx < len(body_lines) and body_lines[idx].strip() == "":
            idx += 1
        greeting_ok = idx < len(body_lines) and body_lines[idx].strip() == "Hi Dr. Rivera,"
        scores["email_greeting_present"] = 1.0 if greeting_ok else 0.0

        # Email body within 250 words (excluding subject)
        body_text = "\n".join(body_lines)
        scores["email_body_within_250_words"] = 1.0 if word_count(body_text) <= 250 and word_count(body_text) > 0 else 0.0

        # Summary 2–3 sentences and mentions tentative recommendation + trade-offs
        summary_ok = 0.0
        tradeoff_ok = 0.0
        if greeting_ok:
            # Gather summary text from the line after greeting until first numbered question line
            summary_lines: List[str] = []
            for j in range(idx + 1, len(body_lines)):
                s = body_lines[j].strip()
                if re.match(r"^\d+[\.\)]\s+", s):
                    break
                summary_lines.append(s)
            summary_text = " ".join([ln for ln in summary_lines if ln])
            # Count sentences: split on . ! ?
            sentences = [s for s in re.split(r"[.!?]+", summary_text) if s.strip()]
            if 2 <= len(sentences) <= 3:
                summary_ok = 1.0
            # Must mention a recommendation phrase and a trade-off keyword
            if contains_recommendation_phrase(summary_text) and any(
                k in summary_text.lower() for k in ["risk", "privacy", "retention", "location", "cost", "time", "trade-off", "tradeoff"]
            ):
                tradeoff_ok = 1.0
        scores["email_summary_2_to_3_sentences"] = summary_ok
        scores["email_summary_mentions_recommendation_and_tradeoff"] = tradeoff_ok

        # Three numbered questions, each with quotes and sources, and quotes match files
        questions = parse_email_questions(body_lines)
        scores["email_three_numbered_questions"] = 1.0 if len(questions) == 3 and all(
            re.match(r"^(1|2|3)[\.\)]\s+", q) for q in questions
        ) else 0.0

        if questions:
            have_quotes_sources_all = True
            quotes_match_all = True
            for q in questions:
                q_quotes, q_paths = quotes_and_paths_from_line(q)
                # must contain at least one quote and one valid source path
                has_quote = len(q_quotes) >= 1
                has_path = any(p in file_texts for p in q_paths)
                if not (has_quote and has_path):
                    have_quotes_sources_all = False
                # quote should appear in the referenced file(s)
                if not quotes_match_sources(q_quotes, q_paths, file_texts):
                    quotes_match_all = False
            scores["email_questions_have_quotes_and_sources"] = 1.0 if have_quotes_sources_all and len(questions) == 3 else 0.0
            scores["email_questions_quotes_match_files"] = 1.0 if quotes_match_all and len(questions) == 3 else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()