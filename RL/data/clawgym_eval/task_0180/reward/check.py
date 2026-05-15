import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl_questions(path: Path) -> Optional[List[Dict[str, str]]]:
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                # require id and text
                if not isinstance(obj, dict):
                    return None
                if "id" not in obj or "text" not in obj:
                    return None
                if not isinstance(obj["id"], str) or not isinstance(obj["text"], str):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def _load_contacts_csv(path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            expected_cols = {"department", "name", "email"}
            if set(reader.fieldnames) != expected_cols:
                # Allow at least superset with required columns
                if not expected_cols.issubset(set(reader.fieldnames)):
                    return None
            contacts = {}
            for row in reader:
                dept = row.get("department")
                if dept is None:
                    return None
                contacts[dept] = row
            return contacts
    except Exception:
        return None


def _normalize_category_key(heading: str) -> str:
    s = heading.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    return s


def _normalize_answer_text(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in s.split("\n")]
    # strip leading/trailing empty lines
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _parse_markdown_sections(md_path: Path, base_root: Path) -> List[Dict[str, str]]:
    text = _read_text(md_path)
    if text is None:
        return []
    # Capture sections starting with lines that start with "## "
    # We'll gather heading and content until next "## " or EOF
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections = []
    current_heading = None
    current_content_lines: List[str] = []
    for line in lines:
        if line.startswith("## "):
            # flush previous
            if current_heading is not None:
                content = _normalize_answer_text("\n".join(current_content_lines))
                rel_path = str(md_path.relative_to(base_root))
                sections.append({
                    "heading": current_heading,
                    "answer": content,
                    "source_file": rel_path,
                })
            current_heading = line[3:].strip()
            current_content_lines = []
        else:
            if current_heading is not None:
                current_content_lines.append(line)
    # flush last
    if current_heading is not None:
        content = _normalize_answer_text("\n".join(current_content_lines))
        rel_path = str(md_path.relative_to(base_root))
        sections.append({
            "heading": current_heading,
            "answer": content,
            "source_file": rel_path,
        })
    return sections


def _scan_policies(policies_dir: Path, workspace_root: Path) -> List[Dict[str, str]]:
    if not policies_dir.exists():
        return []
    md_files = sorted([p for p in policies_dir.rglob("*.md") if p.is_file()])
    all_sections: List[Dict[str, str]] = []
    for md in md_files:
        all_sections.extend(_parse_markdown_sections(md, workspace_root))
    return all_sections


def _match_questions_to_sections(sections: List[Dict[str, str]], questions: List[Dict[str, str]]) -> Dict[str, List[str]]:
    # rules mapping heading -> match criteria (list of substrings to search)
    # Explicit deterministic rules per spec
    rules: Dict[str, List[str]] = {
        "Severance": ["severance"],
        "Notice Period": ["notice"],
        "Eligibility": ["eligible", "eligibility"],
        "Mental Health Support": ["mental health"],
        "COBRA Coverage": ["cobra"],
        "Employee Assistance Program (EAP)": ["employee assistance program", "eap"],
    }
    # Build heading -> set of keywords (lowercased)
    rule_map: Dict[str, List[str]] = {k: [kw.lower() for kw in v] for k, v in rules.items()}
    # Build a quick map of actual headings present in sections that are in rules
    present_headings = {sec["heading"]: True for sec in sections}
    # Prepare assignments: heading -> list of question texts (in file order)
    assignments: Dict[str, List[str]] = {sec["heading"]: [] for sec in sections}
    for q in questions:
        qtext = q["text"]
        qlower = qtext.lower()
        candidates: List[str] = []
        for heading, keywords in rule_map.items():
            if heading not in present_headings:
                continue
            for kw in keywords:
                if kw in qlower:
                    candidates.append(heading)
                    break
        if not candidates:
            # leave unmatched and exclude from outputs
            continue
        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            # choose the section whose heading text appears earliest in the question text
            # compute position (case-insensitive) of heading text in question
            min_pos = None
            chosen = None
            for heading in candidates:
                idx = qlower.find(heading.lower())
                if idx == -1:
                    # treat as very large; we still consider in tie-breaker
                    idx = 10**9
                if (min_pos is None) or (idx < min_pos) or (idx == min_pos and heading < chosen):
                    min_pos = idx
                    chosen = heading
            if chosen is None:
                # fallback deterministic by lexicographic
                chosen = sorted(candidates)[0]
        assignments[chosen].append(qtext)
    # Filter only for headings that have at least one question
    return {h: qs for h, qs in assignments.items() if len(qs) > 0}


def _derive_contact_email(source_file_basename: str, contacts: Dict[str, Dict[str, str]]) -> Optional[str]:
    basename_lower = source_file_basename.lower()
    if "layoffs" in basename_lower:
        dept = "Employee Relations"
    elif "benefits" in basename_lower:
        dept = "Benefits"
    else:
        return None
    row = contacts.get(dept)
    if not row:
        return None
    email = row.get("email")
    if not isinstance(email, str):
        return None
    return email


def _compute_expected_categories(workspace: Path) -> Optional[List[Dict[str, object]]]:
    # Load inputs
    questions_path = workspace / "input" / "feedback" / "questions.jsonl"
    contacts_path = workspace / "input" / "resources" / "contacts.csv"
    policies_dir = workspace / "input" / "policies"
    draft_path = workspace / "input" / "templates" / "Comms_Draft.md"
    # Ensure basic inputs readable
    questions = _load_jsonl_questions(questions_path)
    contacts = _load_contacts_csv(contacts_path)
    if questions is None or contacts is None:
        return None
    sections = _scan_policies(policies_dir, workspace)
    # sections objects: {"heading", "answer", "source_file"}
    # match questions
    assignments = _match_questions_to_sections(sections, questions)
    # Build expected categories
    categories: List[Dict[str, object]] = []
    for sec in sections:
        heading = sec["heading"]
        if heading not in assignments:
            continue
        answer = sec["answer"]
        source_file = sec["source_file"]
        category_key = _normalize_category_key(heading)
        basename = Path(source_file).name
        contact_email = _derive_contact_email(basename, contacts)
        if contact_email is None:
            # if mapping failed, keep None-like to fail checks
            contact_email = ""
        categories.append({
            "category_key": category_key,
            "source_file": source_file,
            "answer": answer,
            "questions": assignments[heading],
            "contact_email": contact_email,
        })
    return categories


def _load_student_faq(workspace: Path) -> Optional[dict]:
    faq_path = workspace / "output" / "faq.json"
    return _load_json(faq_path)


def _categories_by_key(categories: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    m: Dict[str, Dict[str, object]] = {}
    for c in categories:
        key = c.get("category_key")
        if isinstance(key, str):
            # last wins if duplicate
            m[key] = c
    return m


def _validate_faq_structure(faq: dict) -> Tuple[bool, Optional[List[Dict[str, object]]]]:
    # Validate structure: {"categories": [ {category_key, source_file, answer, questions, contact_email} ]}
    if not isinstance(faq, dict):
        return False, None
    if "categories" not in faq or not isinstance(faq["categories"], list):
        return False, None
    cats = faq["categories"]
    for item in cats:
        if not isinstance(item, dict):
            return False, None
        for k in ["category_key", "source_file", "answer", "questions", "contact_email"]:
            if k not in item:
                return False, None
        if not isinstance(item["category_key"], str):
            return False, None
        if not isinstance(item["source_file"], str):
            return False, None
        if not isinstance(item["answer"], str):
            return False, None
        if not isinstance(item["questions"], list) or not all(isinstance(q, str) for q in item["questions"]):
            return False, None
        if not isinstance(item["contact_email"], str):
            return False, None
    return True, cats


def _build_bullet_lines_from_categories(categories: List[Dict[str, object]]) -> List[str]:
    lines = []
    for c in categories:
        category_key = c.get("category_key", "")
        source_file = c.get("source_file", "")
        questions = c.get("questions", [])
        try:
            q_count = len(questions)
        except Exception:
            q_count = 0
        basename = Path(str(source_file)).name
        contact_email = c.get("contact_email", "")
        line = f"- {category_key}: {q_count} questions; source: {basename}; contact: {contact_email}"
        lines.append(line)
    return lines


def _replace_placeholder_with_lines(draft_text: str, lines: List[str]) -> Optional[str]:
    # Replace exact line "<!-- FAQ_SUMMARY -->" with bullet lines
    draft_lines = draft_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    placeholder = "<!-- FAQ_SUMMARY -->"
    if placeholder not in draft_lines:
        return None
    out_lines = []
    for ln in draft_lines:
        if ln == placeholder:
            out_lines.extend(lines)
        else:
            out_lines.append(ln)
    return "\n".join(out_lines)


def _extract_bullet_lines_after_marker(updated_text: str) -> Optional[List[str]]:
    # After the line "Top Questions (auto-generated will be inserted below):", capture consecutive lines starting with "- "
    lines = updated_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    marker = "Top Questions (auto-generated will be inserted below):"
    if marker not in lines:
        return None
    idx = lines.index(marker)
    bullets: List[str] = []
    for j in range(idx + 1, len(lines)):
        if lines[j].startswith("- "):
            bullets.append(lines[j])
        else:
            # stop at first non-bullet
            break
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outputs_present": 0.0,
        "faq_json_structure_valid": 0.0,
        "faq_categories_count": 0.0,
        "category_keys_correct": 0.0,
        "source_file_paths_correct": 0.0,
        "answers_content_correct": 0.0,
        "questions_assignment_correct": 0.0,
        "contact_emails_correct": 0.0,
        "only_categories_with_questions": 0.0,
        "comms_placeholder_replaced": 0.0,
        "comms_summary_matches_faq": 0.0,
        "comms_summary_matches_expected_categories": 0.0,
        "comms_preserves_other_content": 0.0,
    }

    output_dir = workspace / "output"
    faq_path = output_dir / "faq.json"
    comms_updated_path = output_dir / "Comms_Updated.md"
    draft_path = workspace / "input" / "templates" / "Comms_Draft.md"

    # Check outputs present
    if faq_path.exists() and comms_updated_path.exists():
        scores["outputs_present"] = 1.0

    # Load and validate student faq structure
    student_faq = _load_student_faq(workspace)
    valid_structure = False
    student_categories: Optional[List[Dict[str, object]]] = None
    if student_faq is not None:
        valid_structure, student_categories = _validate_faq_structure(student_faq)
    if valid_structure and student_categories is not None:
        scores["faq_json_structure_valid"] = 1.0

    # Compute expected categories from inputs
    expected_categories = _compute_expected_categories(workspace)

    # Content checks only if structure and expected are available
    if valid_structure and student_categories is not None and expected_categories is not None:
        student_map = _categories_by_key(student_categories)
        expected_map = _categories_by_key(expected_categories)

        # categories count
        if len(student_map) == len(expected_map):
            scores["faq_categories_count"] = 1.0

        # category keys correctness (set equality, no duplicates)
        student_keys = set(student_map.keys())
        expected_keys = set(expected_map.keys())
        # Detect duplicates by comparing lengths
        no_student_dupes = (len(student_keys) == len(student_categories))
        if student_keys == expected_keys and no_student_dupes:
            scores["category_keys_correct"] = 1.0

        # source_file_paths_correct
        sf_ok = True
        if student_keys != expected_keys:
            sf_ok = False
        else:
            for k in expected_keys:
                if student_map[k].get("source_file") != expected_map[k].get("source_file"):
                    sf_ok = False
                    break
        scores["source_file_paths_correct"] = 1.0 if sf_ok else 0.0

        # answers_content_correct with normalization
        ans_ok = True
        if student_keys != expected_keys:
            ans_ok = False
        else:
            for k in expected_keys:
                stud_ans = student_map[k].get("answer", "")
                exp_ans = expected_map[k].get("answer", "")
                if not isinstance(stud_ans, str) or not isinstance(exp_ans, str):
                    ans_ok = False
                    break
                if _normalize_answer_text(stud_ans) != _normalize_answer_text(exp_ans):
                    ans_ok = False
                    break
        scores["answers_content_correct"] = 1.0 if ans_ok else 0.0

        # questions_assignment_correct
        qa_ok = True
        if student_keys != expected_keys:
            qa_ok = False
        else:
            for k in expected_keys:
                stud_qs = student_map[k].get("questions", [])
                exp_qs = expected_map[k].get("questions", [])
                if not isinstance(stud_qs, list) or not isinstance(exp_qs, list):
                    qa_ok = False
                    break
                if stud_qs != exp_qs:
                    qa_ok = False
                    break
        scores["questions_assignment_correct"] = 1.0 if qa_ok else 0.0

        # contact_emails_correct
        ce_ok = True
        if student_keys != expected_keys:
            ce_ok = False
        else:
            for k in expected_keys:
                if student_map[k].get("contact_email") != expected_map[k].get("contact_email"):
                    ce_ok = False
                    break
        scores["contact_emails_correct"] = 1.0 if ce_ok else 0.0

        # only_categories_with_questions (ensure none with empty list)
        only_nonempty = True
        for c in student_categories:
            qs = c.get("questions", [])
            if not isinstance(qs, list) or len(qs) == 0:
                only_nonempty = False
                break
        scores["only_categories_with_questions"] = 1.0 if only_nonempty else 0.0

    # Comms checks
    draft_text = _read_text(draft_path)
    updated_text = _read_text(comms_updated_path)
    if valid_structure and student_categories is not None and draft_text is not None and updated_text is not None:
        # Build expected updated from student's faq.json categories (preserve their order)
        bullet_lines_from_student = _build_bullet_lines_from_categories(student_categories)
        expected_updated_from_student = _replace_placeholder_with_lines(draft_text, bullet_lines_from_student)
        # comms_placeholder_replaced and preserves content and summary matches faq
        if expected_updated_from_student is not None and expected_updated_from_student == updated_text:
            scores["comms_placeholder_replaced"] = 1.0
            scores["comms_summary_matches_faq"] = 1.0
            scores["comms_preserves_other_content"] = 1.0

    # Comms summary matches expected categories (content correctness against inputs, order-insensitive)
    if updated_text is not None and expected_categories is not None:
        extracted_bullets = _extract_bullet_lines_after_marker(updated_text)
        if extracted_bullets is not None:
            expected_bullets = _build_bullet_lines_from_categories(expected_categories)
            # Compare as sets ignoring order
            if set(extracted_bullets) == set(expected_bullets) and len(extracted_bullets) == len(expected_bullets):
                scores["comms_summary_matches_expected_categories"] = 1.0
            else:
                scores["comms_summary_matches_expected_categories"] = 0.0
        else:
            scores["comms_summary_matches_expected_categories"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()