import json
import sys
import re
import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_manifest_csv(path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    try:
        rows = {}
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue
                file_name = row.get("file_name", "").strip()
                if file_name:
                    rows[file_name] = {k: (v or "").strip() for k, v in row.items()}
        return rows
    except Exception:
        return None


def word_count(text: str) -> int:
    return len([w for w in re.findall(r"\b\w[\w'-]*\b", text)])


def normalize_label(line: str) -> str:
    s = line.strip()
    s = s.lstrip("#").strip()
    if s.endswith(":"):
        s = s[:-1]
    return s.lower()


def find_sections(text: str, section_names: List[str]) -> Dict[str, str]:
    lines = text.splitlines()
    indices = []
    normalized_targets = {name.lower(): name for name in section_names}
    for idx, line in enumerate(lines):
        lab = normalize_label(line)
        if lab in normalized_targets:
            indices.append((idx, lab))
    sections: Dict[str, str] = {}
    if not indices:
        return sections
    indices.sort()
    for i, (start_idx, lab) in enumerate(indices):
        end_idx = len(lines)
        if i + 1 < len(indices):
            end_idx = indices[i + 1][0]
        content = "\n".join(lines[start_idx + 1:end_idx]).strip()
        sections[lab] = content
    return sections


def extract_bullets(text: str) -> List[str]:
    bullets = []
    for line in text.splitlines():
        if re.match(r"^\s*[-*]\s+", line):
            bullets.append(re.sub(r"^\s*[-*]\s+", "", line).strip())
    return bullets


def extract_numbered_lines(text: str) -> List[str]:
    numbered = []
    for line in text.splitlines():
        if re.match(r"^\s*\d+\.\s+", line):
            numbered.append(line.strip())
    return numbered


def split_sentences(text: str) -> List[str]:
    filtered_lines = []
    for line in text.splitlines():
        if re.match(r"!\[.*\]\(.*\)", line.strip()):
            filtered_lines.append("")
        else:
            filtered_lines.append(line)
    filtered = "\n".join(filtered_lines)
    filtered = re.sub(r"\s+", " ", filtered).strip()
    if not filtered:
        return []
    parts = re.split(r"(?<=[\.\!\?])\s+", filtered)
    sentences = [p.strip() for p in parts if p and p.strip()]
    return sentences


def normalize_quote_line(line: str) -> str:
    s = line.strip()
    s = re.sub(r"^\s*[-*>]\s*", "", s)
    s = s.strip('"\''"“”‘’")
    return s.strip()


def extract_proposed_rewrite_pairs(major_text: str, original_sentences: List[str]) -> List[Tuple[str, str]]:
    originals_set = set([s.strip() for s in original_sentences if s.strip()])
    pairs: List[Tuple[str, str]] = []
    lines = major_text.splitlines()
    for idx, line in enumerate(lines):
        if re.search(r"proposed rewrite\s*:", line, flags=re.IGNORECASE):
            after_colon = line.split(":", 1)[1] if ":" in line else ""
            proposed = after_colon.strip()
            if not proposed:
                j = idx + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    proposed = lines[j].strip()
            found_orig = None
            for back in range(1, 7):
                p = idx - back
                if p < 0:
                    break
                candidate = normalize_quote_line(lines[p])
                if candidate in originals_set:
                    found_orig = candidate
                    break
            if found_orig and proposed:
                pairs.append((found_orig, proposed))
    return pairs


def find_quoted_originals_in_text(major_text: str, original_sentences: List[str]) -> List[str]:
    originals_set = set([s.strip() for s in original_sentences if s.strip()])
    hits = []
    for line in major_text.splitlines():
        candidate = normalize_quote_line(line)
        if candidate in originals_set:
            hits.append(candidate)
    seen = set()
    ordered = []
    for h in hits:
        if h not in seen:
            ordered.append(h)
            seen.add(h)
    return ordered


def parse_rewritten_sentences_from_excerpts(text: str) -> Dict[int, str]:
    lines = text.splitlines()
    out: Dict[int, str] = {}
    for i, line in enumerate(lines):
        m = re.search(r"rewritten sentence\s*(\d+)\s*:", line, flags=re.IGNORECASE)
        if m:
            idx = int(m.group(1))
            content = line.split(":", 1)[1].strip() if ":" in line else ""
            if not content:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    content = lines[j].strip()
            if content:
                out[idx] = content
    return out


def replace_first(text: str, old: str, new: str) -> str:
    pos = text.find(old)
    if pos == -1:
        return text
    return text[:pos] + new + text[pos + len(old):]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "review_file_exists_and_sections": 0.0,
        "review_summary_length_and_labeling": 0.0,
        "review_contextualization_bullets_count_and_content": 0.0,
        "review_major_comments_structure_and_count": 0.0,
        "review_major_comments_quotes_verbatim_from_draft": 0.0,
        "review_proposed_rewrites_presence_and_exactly_two_rewrites_overall": 0.0,
        "review_minor_issues_incorrect_path_and_correction": 0.0,
        "review_cultural_significance_addressed": 0.0,
        "excerpts_file_contains_corrected_figure_line": 0.0,
        "excerpts_contains_two_rewritten_sentences_labels": 0.0,
        "corrected_article_exists_and_path_fixed": 0.0,
        "corrected_article_rewrites_applied_consistently_with_review": 0.0,
        "corrected_article_only_allowed_changes": 0.0,
        "mkdocs_nav_updated_with_entries": 0.0,
        "mkdocs_backup_exists_and_matches": 0.0,
        "colleague_email_references_and_length": 0.0,
        "colleague_email_mentions_corrected_path_and_two_sentences": 0.0,
        "editor_message_bulleted_3_to_5_and_mentions_nav_items": 0.0,
    }

    draft_path = workspace / "input" / "manuscripts" / "article_draft.md"
    manifest_path = workspace / "input" / "assets" / "manifest.csv"
    mkdocs_path = workspace / "input" / "site" / "mkdocs.yml"
    index_md_path = workspace / "input" / "docs" / "index.md"
    email_raw_path = workspace / "input" / "email_draft_raw.txt"

    draft_text = read_text_safe(draft_path)
    manifest = load_manifest_csv(manifest_path)
    mkdocs_text = read_text_safe(mkdocs_path)
    _ = read_text_safe(index_md_path)
    _ = read_text_safe(email_raw_path)

    krater_rel_path = None
    if manifest and "krater.jpg" in manifest:
        krater_rel_path = manifest["krater.jpg"].get("rel_path") or None

    original_image_line = None
    expected_corrected_image_line = None
    if draft_text is not None and krater_rel_path:
        for line in draft_text.splitlines():
            if re.match(r"!\[.*\]\(.*\)", line.strip()):
                original_image_line = line.strip()
                break
        alt_text = None
        if original_image_line:
            m = re.match(r"!\[(.*?)\]\((.*?)\)", original_image_line)
            if m:
                alt_text = m.group(1)
        if alt_text:
            expected_corrected_image_line = f"![{alt_text}]({krater_rel_path})"

    review_path = workspace / "input" / "docs" / "reviews" / "ancient_drinking_customs_peer_review.md"
    review_text = read_text_safe(review_path)
    section_names = ["Summary", "Contextualization", "Major comments", "Minor issues"]

    original_sentences: List[str] = split_sentences(draft_text or "")

    if review_text:
        sections = find_sections(review_text, section_names)
        has_all_sections = all(normalize_label(name) in sections for name in section_names)
        if has_all_sections:
            scores["review_file_exists_and_sections"] = 1.0

        summary_text = sections.get("summary", "")
        if summary_text:
            wc = word_count(summary_text)
            if wc <= 150 and wc > 0:
                scores["review_summary_length_and_labeling"] = 1.0

        context_text = sections.get("contextualization", "")
        bullets = extract_bullets(context_text)
        keywords = ["greek", "roman", "symposia", "symposium", "convivium", "ritual", "economic", "culture", "cultural", "society", "political"]
        bullets_ok = 2 <= len(bullets) <= 3
        keyword_ok = any(any(k in b.lower() for k in keywords) for b in bullets) if bullets else False
        if bullets_ok and keyword_ok:
            scores["review_contextualization_bullets_count_and_content"] = 1.0

        major_text = sections.get("major comments", "")
        numbered = extract_numbered_lines(major_text)
        proposed_pairs = extract_proposed_rewrite_pairs(major_text, original_sentences)
        if len(numbered) >= 3 and len(proposed_pairs) >= 3:
            scores["review_major_comments_structure_and_count"] = 1.0

        quoted_hits = find_quoted_originals_in_text(major_text, original_sentences)
        if len(quoted_hits) >= 3:
            scores["review_major_comments_quotes_verbatim_from_draft"] = 1.0

        minor_text = sections.get("minor issues", "")
        minor_ok = False
        if minor_text and expected_corrected_image_line and original_image_line and krater_rel_path:
            incorrect_path_match = re.search(r"\((.*?)\)", original_image_line)
            incorrect_path = incorrect_path_match.group(1) if incorrect_path_match else None
            if incorrect_path and incorrect_path in minor_text and krater_rel_path in minor_text:
                minor_ok = True
        if minor_ok:
            scores["review_minor_issues_incorrect_path_and_correction"] = 1.0

        low_review = review_text.lower()
        if ("cultural" in low_review and ("significance" in low_review or "broader" in low_review or "society" in low_review or "political" in low_review) and "drink" in low_review):
            scores["review_cultural_significance_addressed"] = 1.0

    excerpts_path = workspace / "input" / "docs" / "excerpts" / "corrected_snippets.md"
    excerpts_text = read_text_safe(excerpts_path)
    rewritten_from_excerpts: Dict[int, str] = {}
    if excerpts_text:
        if expected_corrected_image_line and expected_corrected_image_line in excerpts_text:
            scores["excerpts_file_contains_corrected_figure_line"] = 1.0
        rewritten_from_excerpts = parse_rewritten_sentences_from_excerpts(excerpts_text)
        if 1 in rewritten_from_excerpts and 2 in rewritten_from_excerpts and rewritten_from_excerpts[1].strip() and rewritten_from_excerpts[2].strip():
            scores["excerpts_contains_two_rewritten_sentences_labels"] = 1.0

    if review_text:
        sections = find_sections(review_text, section_names)
        major_text = sections.get("major comments", "")
        proposed_pairs = extract_proposed_rewrite_pairs(major_text, original_sentences)
        proposed_rewrites = [rw for (_, rw) in proposed_pairs]
        if rewritten_from_excerpts and len(rewritten_from_excerpts) == 2:
            if rewritten_from_excerpts.get(1) in proposed_rewrites and rewritten_from_excerpts.get(2) in proposed_rewrites:
                scores["review_proposed_rewrites_presence_and_exactly_two_rewrites_overall"] = 1.0

    corrected_path = workspace / "output" / "manuscripts" / "article_draft_with_corrections.md"
    corrected_text = read_text_safe(corrected_path)
    if corrected_text:
        path_fixed_ok = False
        if krater_rel_path:
            if krater_rel_path in corrected_text and ("/images/krater.jpg" not in corrected_text and "images/krater.jpg" not in corrected_text):
                path_fixed_ok = True
        scores["corrected_article_exists_and_path_fixed"] = 1.0 if path_fixed_ok else 0.0

        applied_pairs: List[Tuple[str, str]] = []
        if review_text:
            sections = find_sections(review_text, section_names)
            major_text = sections.get("major comments", "")
            proposed_pairs = extract_proposed_rewrite_pairs(major_text, original_sentences)
            for orig, new in proposed_pairs:
                if new and new in corrected_text:
                    applied_pairs.append((orig, new))
            seen_new = set()
            uniq_applied = []
            for o, n in applied_pairs:
                if n not in seen_new:
                    uniq_applied.append((o, n))
                    seen_new.add(n)
            applied_pairs = uniq_applied

        rewrites_ok = False
        if len(applied_pairs) == 2 and rewritten_from_excerpts:
            new_set = {n for (_, n) in applied_pairs}
            excerpt_set = {rewritten_from_excerpts.get(1, ""), rewritten_from_excerpts.get(2, "")}
            if new_set == excerpt_set:
                originals_absent = all((o not in corrected_text) for (o, _) in applied_pairs)
                rewrites_ok = originals_absent
        scores["corrected_article_rewrites_applied_consistently_with_review"] = 1.0 if rewrites_ok else 0.0

        only_changes_ok = False
        if draft_text and krater_rel_path:
            expected = draft_text
            expected = expected.replace("](images/krater.jpg)", f"]({krater_rel_path})")
            if len(applied_pairs) == 2:
                tmp = expected
                for (old_s, new_s) in applied_pairs:
                    tmp = replace_first(tmp, old_s, new_s)
                expected = tmp
                if expected == corrected_text:
                    only_changes_ok = True
        scores["corrected_article_only_allowed_changes"] = 1.0 if only_changes_ok else 0.0

    backup_path = workspace / "output" / "site" / "mkdocs.yml.bak"
    backup_text = read_text_safe(backup_path)
    mk_updated_ok = False
    mk_backup_ok = False
    if mkdocs_text:
        need_substrings = [
            "Peer Reviews",
            "reviews/ancient_drinking_customs_peer_review.md",
            "Excerpts",
            "excerpts/corrected_snippets.md",
        ]
        mk_updated_ok = all(sub in mkdocs_text for sub in need_substrings)
    scores["mkdocs_nav_updated_with_entries"] = 1.0 if mk_updated_ok else 0.0
    if backup_text and mkdocs_text:
        need_substrings = [
            "Peer Reviews",
            "reviews/ancient_drinking_customs_peer_review.md",
            "Excerpts",
            "excerpts/corrected_snippets.md",
        ]
        backup_has_entries = all(sub in backup_text for sub in need_substrings)
        mk_backup_ok = backup_has_entries and (backup_text == mkdocs_text)
    scores["mkdocs_backup_exists_and_matches"] = 1.0 if mk_backup_ok else 0.0

    email_path = workspace / "output" / "emails" / "colleague_email.txt"
    email_text = read_text_safe(email_path)
    if email_text:
        wc = word_count(email_text)
        has_paths = ("input/docs/reviews/ancient_drinking_customs_peer_review.md" in email_text
                     and "output/manuscripts/article_draft_with_corrections.md" in email_text)
        early = email_text.strip().splitlines()
        first_two = "\n".join(early[:2]) if early else ""
        courteous = bool(re.search(r"\b(dear|hello|hi)\b", first_two.lower()))
        mentions_sending = bool(re.search(r"\b(send|sending|attached|attach|enclosed|include|including)\b", email_text.lower()))
        if 120 <= wc <= 180 and has_paths and courteous and mentions_sending:
            scores["colleague_email_references_and_length"] = 1.0

        mentions_img = krater_rel_path in email_text if krater_rel_path else False
        mentions_two_sentences = ("two" in email_text.lower() and "sentence" in email_text.lower() and "clarit" in email_text.lower())
        if mentions_img and mentions_two_sentences:
            scores["colleague_email_mentions_corrected_path_and_two_sentences"] = 1.0

    editor_msg_path = workspace / "output" / "messages" / "editor_message.txt"
    editor_text = read_text_safe(editor_msg_path)
    if editor_text:
        bullets = [ln for ln in editor_text.splitlines() if re.match(r"^\s*[-*]\s+", ln)]
        bullet_count_ok = 3 <= len(bullets) <= 5
        has_nav_mentions = all(sub in editor_text for sub in [
            "Peer Reviews", "reviews/ancient_drinking_customs_peer_review.md",
            "Excerpts", "excerpts/corrected_snippets.md"
        ])
        if bullet_count_ok and has_nav_mentions:
            scores["editor_message_bulleted_3_to_5_and_mentions_nav_items"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()