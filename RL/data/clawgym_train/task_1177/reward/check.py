import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def is_int(n: Any) -> bool:
    try:
        return isinstance(n, int) or (isinstance(n, float) and float(n).is_integer())
    except Exception:
        return False


def parse_marked_sections(lines: List[str], headings: List[str]) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {h: [] for h in headings}
    current: Optional[str] = None
    heading_set = set(headings)
    for line in lines:
        stripped = line.strip()
        if stripped in heading_set:
            current = stripped
            continue
        if current is not None:
            sections[current].append(line.rstrip("\n"))
    return sections


def extract_numbers_from_dict(d: Dict[str, Any]) -> List[int]:
    nums: List[int] = []
    for v in d.values():
        if isinstance(v, int):
            nums.append(v)
        elif isinstance(v, float) and float(v).is_integer():
            nums.append(int(v))
        elif isinstance(v, list):
            for e in v:
                if isinstance(e, int):
                    nums.append(e)
                elif isinstance(e, float) and float(e).is_integer():
                    nums.append(int(e))
        elif isinstance(v, dict):
            nums.extend(extract_numbers_from_dict(v))
    return nums


def count_sentences(text: str) -> int:
    # Simple sentence terminator split
    parts = re.split(r"[.!?]+", text)
    return len([p for p in parts if p.strip()])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "critique_json_exists": 0.0,
        "critique_json_structure": 0.0,
        "critique_includes_required_criteria": 0.0,
        "report_md_exists": 0.0,
        "report_md_sections_present": 0.0,
        "rehearsal_notes_exists": 0.0,
        "rehearsal_notes_sections_present": 0.0,
        "rehearsal_notes_strengths_count": 0.0,
        "rehearsal_notes_improvements_count": 0.0,
        "rehearsal_notes_action_items_count_and_time": 0.0,
        "notes_grounded_in_critique": 0.0,
        "personal_note_length_and_theme": 0.0,
        "troubleshooting_log_exists": 0.0,
        "troubleshooting_log_contains_error_and_fix": 0.0,
        "config_weights_sum_to_one": 0.0,
        "config_contains_valid_criteria_keys": 0.0,
        "overall_score_weighted_consistency": 0.0,
    }

    # Paths
    critique_path = workspace / "out" / "critique.json"
    report_path = workspace / "out" / "report.md"
    notes_path = workspace / "out" / "notes" / "rehearsal_notes.md"
    troubleshooting_path = workspace / "out" / "debug" / "troubleshooting.md"
    config_path = workspace / "config" / "rubric.json"

    # Load artifacts
    critique = load_json(critique_path) if critique_path.exists() else None
    has_outputs = critique is not None and isinstance(critique, dict)
    if has_outputs:
        scores["critique_json_exists"] = 1.0

    # Validate critique structure
    if has_outputs:
        overall_ok = "overall_score" in critique and is_int(critique["overall_score"]) and 0 <= int(critique["overall_score"]) <= 100
        criteria_ok = isinstance(critique.get("criteria"), list)
        names_present = False
        per_criterion_ok = True
        evidence_ok = True
        if criteria_ok:
            names = set()
            for c in critique["criteria"]:
                if not isinstance(c, dict):
                    per_criterion_ok = False
                    break
                if "name" not in c or "score" not in c or "comments" not in c:
                    per_criterion_ok = False
                    break
                if not is_int(c["score"]) or not (0 <= int(c["score"]) <= 100):
                    per_criterion_ok = False
                    break
                if "evidence" in c and c["evidence"] is not None and not isinstance(c["evidence"], dict):
                    evidence_ok = False
                    break
                names.add(str(c.get("name", "")).strip().lower())
            names_present = {"emotion", "pacing", "clarity"}.issubset(names)
        if overall_ok and criteria_ok and per_criterion_ok and evidence_ok:
            scores["critique_json_structure"] = 1.0
        if names_present:
            scores["critique_includes_required_criteria"] = 1.0

    # report.md checks
    report_text = read_text(report_path) if report_path.exists() else None
    if report_text is not None:
        scores["report_md_exists"] = 1.0
        has_overall = bool(re.search(r"Overall Score:\s*\d+\s*/\s*100", report_text))
        has_strengths = "Strengths:" in report_text
        has_improve = "Areas to Improve:" in report_text
        mentions_criteria = any(k in report_text for k in ["Emotion", "Pacing", "Clarity", "emotion", "pacing", "clarity"])
        if has_overall and has_strengths and has_improve and mentions_criteria:
            scores["report_md_sections_present"] = 1.0

    # rehearsal notes checks
    notes_text = read_text(notes_path) if notes_path.exists() else None
    if notes_text is not None:
        scores["rehearsal_notes_exists"] = 1.0
        lines = notes_text.splitlines()
        headings = [
            "Strengths:",
            "Areas to Improve:",
            "Action Items for Next Rehearsal:",
            "Personal Note (Dakota Fanning inspiration):",
        ]
        sections = parse_marked_sections(lines, headings)
        has_all_sections = all(h in sections for h in headings)
        if has_all_sections:
            scores["rehearsal_notes_sections_present"] = 1.0

        def count_items(section_lines: List[str]) -> int:
            cnt = 0
            for ln in section_lines:
                s = ln.strip()
                if not s:
                    continue
                if s.startswith("-") or s.startswith("*") or s:
                    cnt += 1
            return cnt

        strengths_cnt = count_items(sections.get("Strengths:", []))
        improvements_cnt = count_items(sections.get("Areas to Improve:", []))
        if strengths_cnt >= 3:
            scores["rehearsal_notes_strengths_count"] = 1.0
        if improvements_cnt >= 3:
            scores["rehearsal_notes_improvements_count"] = 1.0

        # Action items: at least 5 with time estimates like "10 min"
        action_lines = [ln.strip() for ln in sections.get("Action Items for Next Rehearsal:", []) if ln.strip()]
        time_pattern = re.compile(r"\b\d+\s*(min|mins|minute|minutes)\b", re.IGNORECASE)
        with_time = [ln for ln in action_lines if time_pattern.search(ln)]
        if len(action_lines) >= 5 and len(with_time) >= 5:
            scores["rehearsal_notes_action_items_count_and_time"] = 1.0

        # Grounding in critique: mention criteria and at least one numeric evidence value
        grounded_ok = False
        if has_outputs:
            all_numbers: List[int] = []
            crit_list = critique.get("criteria", []) if isinstance(critique.get("criteria"), list) else []
            for c in crit_list:
                ev = c.get("evidence")
                if isinstance(ev, dict):
                    all_numbers.extend(extract_numbers_from_dict(ev))
            ov = critique.get("overall_score")
            if is_int(ov):
                all_numbers.append(int(ov))
            num_strings = set(str(abs(int(n))) for n in all_numbers if is_int(n))
            lower_text = notes_text.lower()
            mentions_criteria = sum(1 for k in ["emotion", "pacing", "clarity"] if k in lower_text) >= 2
            mentions_number = any(ns in notes_text for ns in num_strings) if num_strings else False
            if mentions_criteria and mentions_number:
                grounded_ok = True
        if grounded_ok:
            scores["notes_grounded_in_critique"] = 1.0

        # Personal note checks: 2–3 sentences and thematic mention
        pn_lines = sections.get("Personal Note (Dakota Fanning inspiration):", [])
        pn_text = " ".join([ln.strip() for ln in pn_lines if ln.strip()])
        if pn_text:
            sent_count = count_sentences(pn_text)
            theme_ok = any(k in pn_text for k in ["Dakota", "Fanning"]) and any(
                kw in pn_text.lower() for kw in ["subtle", "clarity", "clear", "nuance", "nuanced"]
            )
            criteria_ref = any(kw in pn_text.lower() for kw in ["emotion", "pacing", "clarity"])
            if 2 <= sent_count <= 3 and theme_ok and criteria_ref:
                scores["personal_note_length_and_theme"] = 1.0

    # troubleshooting log checks
    troubleshoot_text = read_text(troubleshooting_path) if troubleshooting_path.exists() else None
    if troubleshoot_text is not None:
        scores["troubleshooting_log_exists"] = 1.0
        lt = troubleshoot_text.lower()
        # Must include an error snippet
        has_error_snippet = any(k in lt for k in ["traceback", "keyerror", "valueerror", "error:"])
        # Must include root cause explanation
        has_root_cause = "root cause" in lt or "cause" in lt
        # Must include an exact change description and where it was made
        has_change_verbs = any(k in lt for k in ["changed", "modified", "updated", "fix", "fixed"])
        mentions_target_file = any(k in lt for k in ["config/rubric.json", "scripts/evaluate.py"])
        # Must reference the problematic keys (weights/weight or emotion_keywords/emotional_keywords)
        mentions_keys_issue = ("emotional_keywords" in lt or "emotion_keywords" in lt) or ("weights" in lt or "weight" in lt)
        if has_error_snippet and has_root_cause and has_change_verbs and mentions_target_file and mentions_keys_issue:
            scores["troubleshooting_log_contains_error_and_fix"] = 1.0

    # Config rubric checks (only meaningful if outputs exist)
    cfg = load_json(config_path) if config_path.exists() else None
    if has_outputs and cfg is not None and isinstance(cfg, dict):
        # Accept either 'weights' or 'weight' as students may choose to modify either config or script
        weights_obj = None
        if isinstance(cfg.get("weights"), dict):
            weights_obj = cfg.get("weights")
        elif isinstance(cfg.get("weight"), dict):
            weights_obj = cfg.get("weight")
        if isinstance(weights_obj, dict):
            keys = ["emotion", "pacing", "clarity"]
            if all(k in weights_obj for k in keys):
                try:
                    total_w = float(weights_obj["emotion"]) + float(weights_obj["pacing"]) + float(weights_obj["clarity"])
                    if abs(total_w - 1.0) <= 1e-6:
                        scores["config_weights_sum_to_one"] = 1.0
                except Exception:
                    pass

        # Validate criteria keys presence (accept either emotion_keywords or emotional_keywords)
        crit = cfg.get("criteria")
        valid_criteria = False
        if isinstance(crit, dict):
            has_emotion = ("emotion_keywords" in crit and isinstance(crit.get("emotion_keywords"), list)) or \
                          ("emotional_keywords" in crit and isinstance(crit.get("emotional_keywords"), list))
            pacing = crit.get("pacing")
            clarity = crit.get("clarity")
            has_pacing = isinstance(pacing, dict) and "short_sentence_threshold" in pacing and "long_sentence_threshold" in pacing
            has_clarity = isinstance(clarity, dict) and isinstance(clarity.get("filler_words"), list)
            if has_emotion and has_pacing and has_clarity:
                valid_criteria = True
        if valid_criteria:
            scores["config_contains_valid_criteria_keys"] = 1.0

    # Overall score consistency check using config weights and critique scores (only if both exist)
    if has_outputs and cfg is not None and isinstance(cfg, dict):
        crit_scores: Dict[str, int] = {}
        if isinstance(critique.get("criteria"), list):
            for c in critique["criteria"]:
                if isinstance(c, dict) and "name" in c and is_int(c.get("score")):
                    name = str(c["name"]).lower().strip()
                    if name in {"emotion", "pacing", "clarity"}:
                        crit_scores[name] = int(c["score"])
        weights_obj = cfg.get("weights") if isinstance(cfg.get("weights"), dict) else cfg.get("weight")
        if isinstance(weights_obj, dict) and all(k in weights_obj for k in ["emotion", "pacing", "clarity"]) and len(crit_scores) >= 3:
            try:
                we = float(weights_obj["emotion"])
                wp = float(weights_obj["pacing"])
                wc = float(weights_obj["clarity"])
                overall_expected = we * crit_scores["emotion"] + wp * crit_scores["pacing"] + wc * crit_scores["clarity"]
                overall_expected_int = int(round(overall_expected))
                overall_present = int(critique.get("overall_score")) if is_int(critique.get("overall_score")) else None
                if overall_present is not None and overall_present == overall_expected_int:
                    scores["overall_score_weighted_consistency"] = 1.0
            except Exception:
                pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()