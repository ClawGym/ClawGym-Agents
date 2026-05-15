import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _extract_banned_terms(tone_guide_text: str) -> List[str]:
    lines = [ln.rstrip() for ln in tone_guide_text.splitlines()]
    banned: List[str] = []
    capture = False
    for ln in lines:
        low = ln.lower().strip()
        if low.startswith("avoid (anachronisms & modern jargon):"):
            capture = True
            continue
        if capture:
            if low.startswith("- "):
                content = ln[2:].strip()
                # Split comma-separated items
                for raw in [p.strip() for p in content.split(",")]:
                    if not raw:
                        continue
                    # Remove parenthetical clarifiers
                    while "(" in raw and ")" in raw and raw.index("(") < raw.rindex(")"):
                        start = raw.index("(")
                        end = raw.rindex(")")
                        raw = (raw[:start] + raw[end + 1 :]).strip()
                    base = " ".join(raw.split()).lower()
                    if base:
                        banned.append(base)
                    # Handle slash variants cautiously: split when sides look like full words, not single-letter tokens like "A/B test"
                    if "/" in base:
                        sides = [s.strip() for s in base.split("/")]
                        if len(sides) == 2:
                            left, right = sides
                            # Only split into alternates when both sides look like full words (length>=3 or contain space)
                            if (len(left) >= 3 or " " in left) and (len(right) >= 3 or " " in right):
                                # Reconstruct alternates if applicable (e.g., "social media/socials")
                                # If base includes a space before the slash, left is multi-word; right likely stands alone.
                                # Add left and right as separate banned entries.
                                banned.append(left)
                                banned.append(right)
            else:
                # End of bullet list
                break
    # Deduplicate and normalize
    seen = set()
    unique: List[str] = []
    for term in banned:
        t = " ".join(term.split())
        if t and t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _get_scene_lines(scene_text: str) -> List[str]:
    return scene_text.splitlines()


def _get_dialogue_map(lines: List[str]) -> Dict[int, Tuple[str, str]]:
    d: Dict[int, Tuple[str, str]] = {}
    for idx, raw in enumerate(lines, start=1):
        if raw.startswith("Lila:"):
            d[idx] = ("Lila", raw)
        elif raw.startswith("Jack:"):
            d[idx] = ("Jack", raw)
    return d


def _find_banned_in_line(text: str, banned_terms: List[str]) -> List[str]:
    low = text.lower()
    hits: List[str] = []
    for term in banned_terms:
        t = term.strip()
        if not t:
            continue
        if t in low:
            hits.append(term)
    return hits


def _compute_required_flagged_lines(
    scene_lines: List[str], banned_terms: List[str]
) -> Dict[int, List[str]]:
    required: Dict[int, List[str]] = {}
    dialogue = _get_dialogue_map(scene_lines)
    for ln, (_spk, full) in dialogue.items():
        hits = _find_banned_in_line(full, banned_terms)
        if hits:
            required[ln] = hits
    return required


def _validate_tone_review_schema(
    review_data: Any,
    scene_lines: List[str],
) -> Tuple[float, Dict[int, Dict[str, Any]], float, float]:
    allowed_issues = {"modern_jargon", "too_verbose", "unclear", "tone_shift"}
    if not isinstance(review_data, list):
        return 0.0, {}, 0.0, 0.0

    entries_by_line: Dict[int, Dict[str, Any]] = {}
    total_entries = len(review_data)
    if total_entries == 0:
        # Empty array shape is valid, but no quality signals available
        return 1.0, {}, 0.0, 0.0

    issues_valid_count = 0
    rewrite_valid_count = 0
    structure_ok = True

    dialogue_map = _get_dialogue_map(scene_lines)

    for obj in review_data:
        if not isinstance(obj, dict):
            structure_ok = False
            continue
        req_fields = {"line_number", "speaker", "original", "issues", "rewrite", "rationale"}
        if set(obj.keys()) != req_fields:
            structure_ok = False
            continue
        line_number = obj.get("line_number")
        speaker = obj.get("speaker")
        original = obj.get("original")
        issues = obj.get("issues")
        rewrite = obj.get("rewrite")
        rationale = obj.get("rationale")

        if not isinstance(line_number, int):
            structure_ok = False
            continue
        if speaker not in ("Lila", "Jack"):
            structure_ok = False
            continue
        if not isinstance(original, str):
            structure_ok = False
            continue
        if not isinstance(issues, list) or len(issues) == 0 or not all(isinstance(x, str) for x in issues):
            structure_ok = False
            continue
        if not isinstance(rewrite, str) or "\n" in rewrite:
            structure_ok = False
            continue
        if not isinstance(rationale, str) or not rationale.strip():
            structure_ok = False
            continue

        if line_number not in dialogue_map:
            structure_ok = False
            continue
        spk_at_line, original_at_line = dialogue_map[line_number]
        if spk_at_line != speaker:
            structure_ok = False
            continue
        if original_at_line != original:
            structure_ok = False
            continue

        issues_set = set(issues)
        valid_issues_flag = issues_set.issubset(allowed_issues)

        low_rat = rationale.lower()
        rationale_ok = any(
            k in low_rat
            for k in [
                "avoid",
                "tone guide",
                "guide",
                "editorial",
                "notes",
                "mid-century",
                "midcentury",
                "anachronism",
            ]
        )
        if not rationale_ok:
            for anchor in [
                "a/b test",
                "socials",
                "metrics",
                "pivot",
                "synergy",
                "iterate",
                "feedback loop",
                "disrupt",
                "sticky",
            ]:
                if anchor in low_rat:
                    rationale_ok = True
                    break

        if valid_issues_flag and rationale_ok:
            issues_valid_count += 1

        rewrite_label_ok = rewrite.startswith(f"{speaker}:")
        if rewrite_label_ok:
            rewrite_valid_count += 1

        entries_by_line[line_number] = obj

    structure_score = 1.0 if structure_ok else 0.0
    issues_valid_score = (issues_valid_count / total_entries) if total_entries > 0 else 0.0
    rewrite_valid_score = (rewrite_valid_count / total_entries) if total_entries > 0 else 0.0
    return structure_score, entries_by_line, issues_valid_score, rewrite_valid_score


def _rewrite_banned_free_score(
    entries_by_line: Dict[int, Dict[str, Any]],
    banned_terms: List[str],
) -> float:
    if not entries_by_line:
        return 0.0
    total = len(entries_by_line)
    clean = 0
    for obj in entries_by_line.values():
        rewrite = obj.get("rewrite", "")
        low = rewrite.lower()
        has_banned = any(term in low for term in banned_terms if term)
        if not has_banned:
            clean += 1
    return clean / total if total > 0 else 0.0


def _issues_jargon_tagging_score(
    entries_by_line: Dict[int, Dict[str, Any]],
    scene_lines: List[str],
    banned_terms: List[str],
) -> float:
    if not entries_by_line:
        return 0.0
    count = 0
    ok = 0
    for ln, obj in entries_by_line.items():
        count += 1
        issues = obj.get("issues", [])
        issues_set = set(issues) if isinstance(issues, list) else set()
        original = obj.get("original", "")
        original_low = original.lower()
        contains_banned = any(term in original_low for term in banned_terms)
        if contains_banned:
            if "modern_jargon" in issues_set:
                ok += 1
        else:
            ok += 1
    return ok / count if count > 0 else 0.0


def _apply_rewrites_to_scene(
    scene_lines: List[str],
    entries_by_line: Dict[int, Dict[str, Any]],
) -> List[str]:
    revised = list(scene_lines)
    for ln, obj in entries_by_line.items():
        idx = ln - 1
        if 0 <= idx < len(revised):
            revised[idx] = obj.get("rewrite", "")
    return revised


def _compare_files_exact(expected_lines: List[str], actual_text: str) -> bool:
    actual_lines = actual_text.splitlines()
    return expected_lines == actual_lines


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "tone_review_json_structure": 0.0,
        "tone_review_covers_banned_jargon_lines": 0.0,
        "tone_review_issues_and_rationale_quality": 0.0,
        "tone_review_rewrites_preserve_speaker_and_avoid_banned": 0.0,
        "scene_revised_integrates_rewrites_exactly": 0.0,
        "pitch_email_word_count": 0.0,
        "pitch_email_required_facts": 0.0,
        "pitch_email_comp_and_midcentury_reference": 0.0,
    }

    # Paths
    scene_path = workspace / "input" / "scene.md"
    tone_guide_path = workspace / "input" / "tone_guide.md"
    editorial_notes_path = workspace / "input" / "editorial_notes.txt"
    _ = _read_text(editorial_notes_path)  # Read to ensure availability; not strictly required for deterministic checks.

    tone_review_path = workspace / "output" / "tone_review.json"
    scene_revised_path = workspace / "output" / "scene_revised.md"
    pitch_rewritten_path = workspace / "output" / "pitch_email_rewritten.txt"

    # Read inputs
    scene_text = _read_text(scene_path)
    tone_guide_text = _read_text(tone_guide_path)

    scene_lines: List[str] = []
    banned_terms: List[str] = []
    required_flagged: Dict[int, List[str]] = {}

    if scene_text is not None and tone_guide_text is not None:
        scene_lines = _get_scene_lines(scene_text)
        banned_terms = _extract_banned_terms(tone_guide_text)
        banned_terms = [" ".join(t.split()) for t in banned_terms]
        required_flagged = _compute_required_flagged_lines(scene_lines, banned_terms)

        # Load tone_review.json and validate
        tone_review_data = _load_json(tone_review_path)
        if tone_review_data is not None:
            structure_score, entries_by_line, issues_valid_score, rewrite_label_score = _validate_tone_review_schema(
                tone_review_data, scene_lines
            )
            scores["tone_review_json_structure"] = structure_score
            scores["tone_review_issues_and_rationale_quality"] = issues_valid_score

            # Coverage of banned-jargon lines
            required_count = len(required_flagged)
            if required_count > 0:
                covered = 0
                for ln in required_flagged:
                    if ln in entries_by_line:
                        issues = entries_by_line[ln].get("issues", [])
                        if isinstance(issues, list) and "modern_jargon" in issues:
                            covered += 1
                scores["tone_review_covers_banned_jargon_lines"] = covered / required_count
            else:
                scores["tone_review_covers_banned_jargon_lines"] = 1.0

            # Rewrites: label preserved and avoid banned terms
            banned_free_score = _rewrite_banned_free_score(entries_by_line, banned_terms)
            if entries_by_line:
                scores["tone_review_rewrites_preserve_speaker_and_avoid_banned"] = (rewrite_label_score + banned_free_score) / 2.0
            else:
                if len(required_flagged) == 0:
                    scores["tone_review_rewrites_preserve_speaker_and_avoid_banned"] = 1.0

            # Scene integration exactness
            scene_revised_text = _read_text(scene_revised_path)
            if scene_revised_text is not None:
                expected_revised_lines = _apply_rewrites_to_scene(scene_lines, entries_by_line)
                if _compare_files_exact(expected_revised_lines, scene_revised_text):
                    scores["scene_revised_integrates_rewrites_exactly"] = 1.0

            # Strengthen issues tagging quality with modern_jargon tagging check
            if entries_by_line:
                scores["tone_review_issues_and_rationale_quality"] = min(
                    1.0,
                    (
                        scores["tone_review_issues_and_rationale_quality"]
                        + _issues_jargon_tagging_score(entries_by_line, scene_lines, banned_terms)
                    )
                    / 2.0,
                )

    # Pitch email checks (independent)
    pitch_text = _read_text(pitch_rewritten_path)
    if pitch_text is not None:
        # Word count
        words = [w for w in pitch_text.strip().split() if w]
        wc = len(words)
        if 130 <= wc <= 180:
            scores["pitch_email_word_count"] = 1.0

        # Required facts
        facts_total = 5
        facts_ok = 0
        low = pitch_text.lower()
        # Title
        if "starlight on madison" in low:
            facts_ok += 1
        # Word count numeric 82,000
        if ("82,000" in pitch_text) or ("82000" in pitch_text):
            facts_ok += 1
        # Era
        if ("1959–1961" in pitch_text) or ("1959-1961" in pitch_text):
            facts_ok += 1
        # Protagonists
        if "lila hart" in low:
            facts_ok += 1
        if "jack fallon" in low:
            facts_ok += 1
        scores["pitch_email_required_facts"] = facts_ok / facts_total

        # Comp and mid-century reference
        comp_hits = 0
        if "the dud avocado" in low:
            comp_hits += 1
        if ("mid-century" in low) or ("midcentury" in low):
            comp_hits += 1
        scores["pitch_email_comp_and_midcentury_reference"] = comp_hits / 2.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    # Preserve key insertion order from the scores dict
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()