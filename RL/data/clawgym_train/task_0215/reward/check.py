import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="latin-1")
        except Exception:
            return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _normalize_quotes(s: str) -> str:
    # Normalize smart quotes/apostrophes to straight ASCII for easier matching
    return s.replace("\u2019", "'").replace("\u2018", "'").replace("\u2014", "—")


def _find_section_span(text: str, label: str, alt_labels: Optional[List[str]] = None) -> Tuple[int, int]:
    """
    Returns (start_index, end_index) for the section labeled by label or any alt label.
    End index is the start of the next label or end of text.
    Case-insensitive search.
    """
    norm_text = _normalize_quotes(text)
    labels = [label]
    if alt_labels:
        labels.extend(alt_labels)
    # Build a case-insensitive search by scanning for exact label occurrences
    indices = []
    for lab in labels:
        idx = norm_text.lower().find(lab.lower())
        if idx != -1:
            indices.append((idx, lab))
    if not indices:
        return (-1, -1)
    start = min(i[0] for i in indices)
    # Determine the next section start
    # Known section labels
    all_labels = ["Issues Found", "Must-Fix List", "Risk Notes", "What we're doing", "What we’re doing"]
    # Find positions of all labels after start
    next_positions = []
    for lab in all_labels:
        pos = norm_text.lower().find(lab.lower(), start + 1)
        if pos != -1:
            next_positions.append(pos)
    end = min(next_positions) if next_positions else len(norm_text)
    return (start, end)


def _extract_lines_after_label(text: str, label_patterns: List[str]) -> List[str]:
    """
    Find the first occurrence of any label in label_patterns (case-insensitive),
    and return lines from that point to the end.
    """
    norm_text = _normalize_quotes(text)
    lower = norm_text.lower()
    pos = -1
    for pat in label_patterns:
        p = lower.find(pat.lower())
        if p != -1:
            pos = p
            break
    if pos == -1:
        return []
    after = norm_text[pos:].splitlines()
    return after


def _extract_bullet_items(section_text: str) -> List[str]:
    bullets = []
    for line in section_text.splitlines():
        if re.match(r"^\s*([-*]|\d+[\.\)])\s+", line):
            bullets.append(line.strip())
    return bullets


def _parse_sources(sources: Any) -> Tuple[bool, List[Dict[str, Any]], str]:
    """
    Validate sources.json structure.
    Returns (is_valid, items, error_reason)
    """
    if not isinstance(sources, list) or len(sources) == 0:
        return (False, [], "not a non-empty list")
    validated: List[Dict[str, Any]] = []
    for i, item in enumerate(sources, start=1):
        if not isinstance(item, dict):
            return (False, [], f"item {i} not a dict")
        required_fields = ["title", "publisher", "url", "access_date", "principle_summaries", "search_queries"]
        for f in required_fields:
            if f not in item:
                return (False, [], f"missing field {f} in item {i}")
        if not isinstance(item["title"], str) or not item["title"].strip():
            return (False, [], f"title invalid in item {i}")
        if not isinstance(item["publisher"], str) or not item["publisher"].strip():
            return (False, [], f"publisher invalid in item {i}")
        if not isinstance(item["url"], str) or not item["url"].strip():
            return (False, [], f"url invalid in item {i}")
        if not isinstance(item["search_queries"], str) or not item["search_queries"].strip():
            return (False, [], f"search_queries invalid in item {i}")
        # access_date format
        if not isinstance(item["access_date"], str):
            return (False, [], f"access_date not a string in item {i}")
        try:
            datetime.strptime(item["access_date"], "%Y-%m-%d")
        except Exception:
            return (False, [], f"access_date format invalid in item {i}")
        # principle_summaries
        ps = item["principle_summaries"]
        if not isinstance(ps, list) or not (1 <= len(ps) <= 3):
            return (False, [], f"principle_summaries invalid length in item {i}")
        for s in ps:
            if not isinstance(s, str) or not s.strip():
                return (False, [], f"principle_summaries contains invalid entry in item {i}")
        validated.append(item)
    return (True, validated, "")


def _classify_sources_for_topics(items: List[Dict[str, Any]]) -> Tuple[int, bool]:
    """
    Returns (crisis_count, has_fact_checking)
    crisis_count: count of items that outline best practices for crisis/apology statements.
    has_fact_checking: True if at least one item addresses fact-checking/substantiating claims.
    """
    crisis_count = 0
    has_fact = False
    for it in items:
        text_parts = [it.get("title", ""), " ".join(it.get("principle_summaries", []))]
        combined = " ".join(text_parts).lower()
        # Crisis/apology guidance
        if any(k in combined for k in ["crisis", "apology", "apolog", "public statement", "press statement", "communication", "incident response"]):
            crisis_count += 1
        # Fact-checking/substantiation
        if any(k in combined for k in ["fact", "verify", "verification", "substantiat", "accuracy", "evidence", "corroborat"]):
            has_fact = True or has_fact
    return crisis_count, has_fact


def _collect_source_refs(text: str) -> List[int]:
    refs = re.findall(r"\[S(\d+)\]", text)
    return [int(x) for x in refs]


def _get_issues_section(text: str) -> str:
    start, end = _find_section_span(text, "Issues Found", [])
    if start == -1:
        return ""
    return text[start:end]


def _get_section_by_label(text: str, label: str) -> str:
    start, end = _find_section_span(text, label, [])
    if start == -1:
        return ""
    return text[start:end]


def _has_apology_opening(text: str) -> bool:
    norm = _normalize_quotes(text).strip()
    # Consider first 250 chars to detect early apology
    start_segment = norm[:250].lower()
    if "apolog" in start_segment and "employee" in start_segment and "commun" in start_segment:
        return True
    # Alternatively, check first sentence
    first_sentence = re.split(r"[.\n]", norm, maxsplit=1)[0].lower()
    return ("apolog" in first_sentence and "employee" in first_sentence and "commun" in first_sentence)


def _actions_bullets_from_revised(text: str) -> List[str]:
    # Normalize quotes to allow matching "we're" vs "we’re"
    norm = _normalize_quotes(text)
    lines = norm.splitlines()
    # Find the index of the label line
    section_label_variants = ["What we're doing", "What we’re doing"]
    label_idx = -1
    for i, line in enumerate(lines):
        l = _normalize_quotes(line).strip().lower()
        if any(l == v.lower() or v.lower() in l for v in section_label_variants):
            label_idx = i
            break
    if label_idx == -1:
        return []
    bullets = []
    for j in range(label_idx + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            # stop at blank line to keep it tight
            if bullets:
                break
            else:
                continue
        if re.match(r"^\s*([-*]|\d+[\.\)])\s+", line):
            bullets.append(line.strip())
        else:
            # If we already started bullets and line is not a bullet, stop
            if bullets:
                break
            # else continue until we hit bullets
            continue
    return bullets


def _actions_match_notes(bullets: List[str]) -> bool:
    # Categories to match:
    # 1) Inspections of equipment and adjacent lines
    # 2) Cooperation with state investigators and updates
    # 3) Free medical assessments and optional community air monitoring with a third-party
    has_inspections = False
    has_coop = False
    has_med_air = False

    for b in bullets:
        bl = b.lower()
        # inspections
        if "inspect" in bl and ("equipment" in bl or "line" in bl or "adjacent" in bl):
            has_inspections = True
        # cooperation with investigators
        if ("cooperat" in bl) and ("investigat" in bl or "state" in bl or "department" in bl):
            has_coop = True
        # medical assessments and/or community air monitoring with third-party
        med = ("medical" in bl and ("assess" in bl or "assessment" in bl or "assessments" in bl))
        air = ("community" in bl and "air" in bl and ("monitor" in bl))
        third = ("third-party" in bl or "third party" in bl)
        if (med and air) or (air and third) or (med and third):
            has_med_air = True
        # Sometimes they may split wording; accept if the bullet contains both "medical" and "monitor"
        if ("medical" in bl and "monitor" in bl and "community" in bl):
            has_med_air = True

    return has_inspections and has_coop and has_med_air


def _no_speculation_superlatives(text: str) -> bool:
    t = text.lower()
    banned_phrases = [
        "sabotage",
        "unmatched",
        "global standards",
        "no risk",
        "normal operations within 90 minutes",
        "90 minutes",
    ]
    # Disallow claim that air quality is safe
    if "air quality" in t and ("safe" in t or "no risk" in t):
        return False
    for b in banned_phrases:
        if b in t:
            return False
    return True


def _cause_handling_ok(text: str) -> bool:
    t = text.lower()
    # If cause mentioned, it must be in context of unknown/under investigation
    for m in re.finditer(r"\bcaus\w*", t):
        start = max(0, m.start() - 60)
        end = min(len(t), m.end() + 60)
        window = t[start:end]
        if ("unknown" not in window) and ("under investigation" not in window) and ("investigat" not in window):
            return False
    # Explicitly disallow definitive cause speculation terms like "sabotage"
    if "sabotage" in t:
        return False
    return True


def _email_has_key_asks(text: str) -> bool:
    t = text.lower()
    # Apology-first framing
    apology_first = ("apology" in t and "first" in t) or ("lead with an apology" in t)
    # Remove unverified/speculative claims
    unverified = any(k in t for k in ["unverified", "speculative", "superlative", "unsubstantiated"])
    # Include three concrete actions (presence of keywords)
    actions = 0
    if "inspect" in t and ("equipment" in t or "line" in t):
        actions += 1
    if "cooperat" in t and ("investigat" in t or "state" in t or "department" in t):
        actions += 1
    if ("medical" in t and "assess" in t) and ("community" in t and "air" in t and "monitor" in t):
        actions += 1
    return apology_first and unverified and (actions >= 3)


def _email_requests_reviews_and_deadline(text: str) -> bool:
    t = text.lower()
    has_ehs = "ehs" in t
    has_legal = "legal" in t
    has_review = "review" in t or "sign-off" in t or "sign off" in t
    mentions_today = "today" in t or "end of day" in t or "eod" in t
    mentions_deadline = ("deadline" in t) or ("sign-off" in t) or ("sign off" in t) or ("end of day" in t) or ("eod" in t)
    return has_ehs and has_legal and has_review and mentions_today and mentions_deadline


def _email_bias_disclosed(text: str) -> bool:
    t = text.lower()
    return ("father" in t) and ("compet" in t) and ("plant" in t)


def _email_tone_neutral(text: str) -> bool:
    t = text.lower()
    banned = ["tbh", "hey", "kinda", "kind of", "comfy", "burn us", "mushy", "—j", "-j", " - j", "— j"]
    for b in banned:
        if b in t:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "sources_json_exists_valid": 0.0,
        "sources_crisis_best_practices_count": 0.0,
        "sources_fact_checking_present": 0.0,
        "critique_sections_present": 0.0,
        "critique_issues_reference_sources": 0.0,
        "critique_issues_quote_draft": 0.0,
        "critique_source_indices_valid": 0.0,
        "revised_has_apology_opening": 0.0,
        "revised_word_count_range": 0.0,
        "revised_contains_required_contacts": 0.0,
        "revised_has_actions_section_three_items": 0.0,
        "revised_actions_match_notes": 0.0,
        "revised_avoids_speculation_and_superlatives": 0.0,
        "revised_cause_handling_correct": 0.0,
        "revised_final_line_date_format": 0.0,
        "email_word_count_range": 0.0,
        "email_includes_key_asks": 0.0,
        "email_requests_ehs_legal_and_deadline": 0.0,
        "email_bias_disclosed_tactfully": 0.0,
        "email_tone_neutral_no_slang": 0.0,
    }

    # Paths
    sources_path = workspace / "outputs" / "sources.json"
    critique_path = workspace / "outputs" / "critique.md"
    revised_path = workspace / "outputs" / "press_statement_revised.md"
    email_path = workspace / "outputs" / "internal_email_rewrite.txt"
    draft_press_path = workspace / "input" / "press_statement_draft.md"
    context_notes_path = workspace / "input" / "context_notes.txt"

    # Load input draft for critique checks
    draft_press_text = _read_text_safe(draft_press_path) or ""

    # Validate sources.json
    sources_json = _load_json_safe(sources_path) if sources_path.exists() else None
    valid_sources = False
    validated_items: List[Dict[str, Any]] = []
    if isinstance(sources_json, list):
        is_valid, items, _ = _parse_sources(sources_json)
        if is_valid:
            valid_sources = True
            validated_items = items
            scores["sources_json_exists_valid"] = 1.0

    # Topic classification counts
    if valid_sources:
        crisis_count, has_fact = _classify_sources_for_topics(validated_items)
        if crisis_count >= 2:
            scores["sources_crisis_best_practices_count"] = 1.0
        if has_fact:
            scores["sources_fact_checking_present"] = 1.0

    # Critique checks
    critique_text = _read_text_safe(critique_path)
    if critique_text:
        ct_norm = _normalize_quotes(critique_text)
        if all(x.lower() in ct_norm.lower() for x in ["issues found", "must-fix list", "risk notes"]):
            scores["critique_sections_present"] = 1.0

        # Issues Found section bullets reference [S#]
        issues_section = _get_issues_section(ct_norm)
        if issues_section:
            bullets = _extract_bullet_items(issues_section)
            if bullets:
                all_have_ref = True
                for b in bullets:
                    if not re.search(r"\[S\d+\]", b):
                        all_have_ref = False
                        break
                if all_have_ref:
                    scores["critique_issues_reference_sources"] = 1.0

        # Each cited S# within range of sources.json
        all_refs = _collect_source_refs(ct_norm)
        if all_refs and valid_sources:
            max_ref = max(all_refs) if all_refs else 0
            if 1 <= max_ref <= len(validated_items) and min(all_refs) >= 1:
                # Ensure no out-of-range reference
                if all(1 <= r <= len(validated_items) for r in all_refs):
                    scores["critique_source_indices_valid"] = 1.0

        # Issues section quotes/references phrases from original draft
        if issues_section:
            # Check for presence of some identifiable phrases from the original draft
            indicative_phrases = [
                "unmatched",
                "sabotage",
                "no risk",
                "resumed normal operations within 90 minutes",
                "global standards",
                "air quality",
            ]
            found = False
            for phrase in indicative_phrases:
                if phrase.lower() in draft_press_text.lower() and phrase.lower() in issues_section.lower():
                    found = True
                    break
            if found:
                scores["critique_issues_quote_draft"] = 1.0

    # Revised public statement checks
    revised_text = _read_text_safe(revised_path)
    if revised_text:
        # Apology opening
        if _has_apology_opening(revised_text):
            scores["revised_has_apology_opening"] = 1.0
        # Word count
        wc = _word_count(revised_text)
        if 160 <= wc <= 220:
            scores["revised_word_count_range"] = 1.0
        # Required contacts
        if ("press@northbridge.com" in revised_text) and ("1-800-555-0199" in revised_text):
            scores["revised_contains_required_contacts"] = 1.0
        # Actions section with exactly three items
        bullets = _actions_bullets_from_revised(revised_text)
        if len(bullets) == 3:
            scores["revised_has_actions_section_three_items"] = 1.0
            if _actions_match_notes(bullets):
                scores["revised_actions_match_notes"] = 1.0
        # Avoid speculation/superlatives
        if _no_speculation_superlatives(revised_text):
            scores["revised_avoids_speculation_and_superlatives"] = 1.0
        # Cause handling
        if _cause_handling_ok(revised_text):
            scores["revised_cause_handling_correct"] = 1.0
        # Final line with date
        last_nonempty = ""
        for line in reversed(revised_text.splitlines()):
            if line.strip():
                last_nonempty = line.strip()
                break
        # Accept em dash or hyphen
        if re.match(r"^Prepared by Northbridge Metals Communications\s+[—-]\s+\d{4}-\d{2}-\d{2}\.$", _normalize_quotes(last_nonempty)):
            scores["revised_final_line_date_format"] = 1.0

    # Internal email rewrite checks
    email_text = _read_text_safe(email_path)
    if email_text:
        wc = _word_count(email_text)
        if 120 <= wc <= 160:
            scores["email_word_count_range"] = 1.0
        if _email_has_key_asks(email_text):
            scores["email_includes_key_asks"] = 1.0
        if _email_requests_reviews_and_deadline(email_text):
            scores["email_requests_ehs_legal_and_deadline"] = 1.0
        if _email_bias_disclosed(email_text):
            scores["email_bias_disclosed_tactfully"] = 1.0
        if _email_tone_neutral(email_text):
            scores["email_tone_neutral_no_slang"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()