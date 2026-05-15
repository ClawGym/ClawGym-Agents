import json
import sys
import subprocess
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def count_words(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def extract_markdown_headings_sections(text: str) -> Dict[str, List[str]]:
    lines = text.splitlines()
    sections: Dict[str, List[str]] = {}
    current_heading: Optional[str] = None
    for line in lines:
        m = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
        if m:
            current_heading = m.group(1).strip()
            sections[current_heading] = []
        else:
            if current_heading is not None:
                sections[current_heading].append(line)
    return sections


def find_section_case_insensitive(sections: Dict[str, List[str]], name: str) -> Optional[Tuple[str, List[str]]]:
    target = name.strip().lower()
    for h, content in sections.items():
        if h.strip().lower() == target:
            return h, content
    return None


def count_list_items(lines: List[str]) -> int:
    count = 0
    for ln in lines:
        if re.match(r"^\s*[-*]\s+", ln):
            count += 1
        elif re.match(r"^\s*\d+\.\s+", ln):
            count += 1
    return count


def contains_any(text: str, phrases: List[str]) -> bool:
    low = text.lower()
    for p in phrases:
        if p.lower() in low:
            return True
    return False


def run_validator(workspace: Path, synthesis: Path, sources: Path, tool: Path) -> Tuple[bool, str, str, int]:
    if not tool.exists() or not synthesis.exists() or not sources.exists():
        return False, "", "", 1
    try:
        res = subprocess.run(
            [sys.executable, str(tool), str(synthesis), str(sources)],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            timeout=15,
        )
        ok = (res.returncode == 0) and ("OK:" in res.stdout) and ("ERROR:" not in res.stdout)
        return ok, res.stdout, res.stderr, res.returncode
    except Exception:
        return False, "", "", 1


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "synthesis_required_sections": 0.0,
        "synthesis_core_arguments_count": 0.0,
        "synthesis_word_count": 0.0,
        "synthesis_validator_recheck": 0.0,
        "synthesis_validation_log_ok": 0.0,
        "synthesis_annotated_references": 0.0,
        "synthesis_non_promotional_language": 0.0,
        "artist_statement_headings_preserved": 0.0,
        "artist_statement_removed_sales_language": 0.0,
        "artist_statement_length_reduction": 0.0,
        "gallery_reply_word_count": 0.0,
        "gallery_reply_declines_licensing": 0.0,
        "gallery_reply_suggests_alternative": 0.0,
        "gallery_reply_respectful_tone": 0.0,
    }

    synth_path = workspace / "outputs" / "synthesis.md"
    sources_path = workspace / "data" / "sources.csv"
    tool_path = workspace / "tools" / "validate_quotes.py"
    log_path = workspace / "outputs" / "validation.log"

    artist_in_path = workspace / "docs" / "artist_statement.md"
    artist_out_path = workspace / "outputs" / "artist_statement_edited.md"

    email_in_path = workspace / "docs" / "gallery_email_draft.txt"
    email_out_path = workspace / "outputs" / "gallery_reply_email.txt"

    synth_text = read_text_safe(synth_path)
    if synth_text is not None:
        sections = extract_markdown_headings_sections(synth_text)
        required_section_names = ["Summary", "Core Arguments", "Counterpoints", "Annotated References"]
        has_all = True
        for sec in required_section_names:
            if find_section_case_insensitive(sections, sec) is None:
                has_all = False
                break
        scores["synthesis_required_sections"] = 1.0 if has_all else 0.0

        core_section = find_section_case_insensitive(sections, "Core Arguments")
        if core_section is not None:
            _, core_lines = core_section
            items = count_list_items(core_lines)
            scores["synthesis_core_arguments_count"] = 1.0 if 3 <= items <= 5 else 0.0
        else:
            scores["synthesis_core_arguments_count"] = 0.0

        wcount = count_words(synth_text)
        if 500 <= wcount <= 800:
            scores["synthesis_word_count"] = 1.0
        elif 450 <= wcount <= 850:
            scores["synthesis_word_count"] = 0.5
        else:
            scores["synthesis_word_count"] = 0.0

        promo_terms = [
            "buy", "shop", "sale", "discount", "order now", "order", "pricing",
            "subscribe", "sign up", "for sale", "on sale", "limited time offer"
        ]
        has_promo = contains_any(synth_text, promo_terms)
        scores["synthesis_non_promotional_language"] = 1.0 if not has_promo else 0.0

        ann = find_section_case_insensitive(sections, "Annotated References")
        if ann is not None:
            _, ann_lines = ann
            ann_text = "\n".join(ann_lines)
            ann_items = count_list_items(ann_lines)
            citations_in_ann = re.findall(r"\[source:([A-Za-z0-9]+)\]", ann_text)
            if ann_items >= 3 and len(citations_in_ann) >= 2:
                scores["synthesis_annotated_references"] = 1.0
            else:
                scores["synthesis_annotated_references"] = 0.0
        else:
            scores["synthesis_annotated_references"] = 0.0

    ok, stdout, stderr, rc = run_validator(workspace, synth_path, sources_path, tool_path)
    scores["synthesis_validator_recheck"] = 1.0 if ok else 0.0

    log_text = read_text_safe(log_path)
    if log_text is not None:
        has_error_lines = any(line.strip().startswith("ERROR:") for line in log_text.splitlines())
        ok_line = "OK: All quotes validated and citation counts satisfied." in log_text
        if ok_line and not has_error_lines:
            scores["synthesis_validation_log_ok"] = 1.0
        else:
            scores["synthesis_validation_log_ok"] = 0.0
    else:
        scores["synthesis_validation_log_ok"] = 0.0

    original_artist_text = read_text_safe(artist_in_path)
    edited_artist_text = read_text_safe(artist_out_path)
    if original_artist_text is not None and edited_artist_text is not None:
        orig_h2 = []
        for line in original_artist_text.splitlines():
            m = re.match(r"^\s{0,3}##\s+(.*)$", line)
            if m:
                orig_h2.append(m.group(1).strip())
        ed_h2 = []
        for line in edited_artist_text.splitlines():
            m = re.match(r"^\s{0,3}##\s+(.*)$", line)
            if m:
                ed_h2.append(m.group(1).strip())
        preserved = all(h in ed_h2 for h in orig_h2)
        scores["artist_statement_headings_preserved"] = 1.0 if preserved else 0.0

        banned_phrases = [
            "prints are available", "prints", "commission", "commissions",
            "brand collaborations", "product placements", "licensed",
            "shop", "posters", "pricing", "sizes", "contact me to book", "inquire"
        ]
        has_banned = contains_any(edited_artist_text, banned_phrases)
        scores["artist_statement_removed_sales_language"] = 1.0 if not has_banned else 0.0

        orig_wc = count_words(original_artist_text)
        ed_wc = count_words(edited_artist_text)
        ratio = ed_wc / orig_wc if orig_wc > 0 else 1.0
        if 0.70 <= ratio <= 0.85:
            scores["artist_statement_length_reduction"] = 1.0
        elif 0.60 <= ratio <= 0.90:
            scores["artist_statement_length_reduction"] = 0.5
        else:
            scores["artist_statement_length_reduction"] = 0.0

    email_text = read_text_safe(email_out_path)
    if email_text is not None:
        wc = count_words(email_text)
        if 120 <= wc <= 180:
            scores["gallery_reply_word_count"] = 1.0
        elif 110 <= wc <= 190:
            scores["gallery_reply_word_count"] = 0.5
        else:
            scores["gallery_reply_word_count"] = 0.0

        low = email_text.lower()
        has_licens = "licens" in low
        neg_terms = ["decline", "cannot", "can't", "not able", "won't", "do not", "not interested", "unable", "no longer able"]
        has_neg = any(t in low for t in neg_terms)
        commercial_terms = ["commercial", "merchandis", "product", "retail", "sell", "merch"]
        mentions_commercial = any(t in low for t in commercial_terms)
        scores["gallery_reply_declines_licensing"] = 1.0 if (has_licens and has_neg and mentions_commercial) else 0.0

        alt_terms = [
            "studio visit", "visit the studio", "exhibition", "conversation",
            "non-commercial", "public program", "talk", "discussion", "curatorial"
        ]
        has_alt = any(t in low for t in alt_terms)
        scores["gallery_reply_suggests_alternative"] = 1.0 if has_alt else 0.0

        banned_tone = [
            "absolutely not", "do not contact me again", "hard no", "slap on",
            "pick something else", "cease and desist", "lawsuit", "sue", "legal threat", "legal action", "lawyer"
        ]
        has_bad_tone = any(t in low for t in banned_tone)
        scores["gallery_reply_respectful_tone"] = 1.0 if not has_bad_tone else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()