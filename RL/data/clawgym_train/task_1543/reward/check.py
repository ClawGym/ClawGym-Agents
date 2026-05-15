import json
import sys
import re
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


def _normalize_tag(tag: str, synonyms: Dict[str, str]) -> str:
    t = tag.strip().lower()
    return synonyms.get(t, t)


def _parse_notes_md(content: str, synonyms: Dict[str, str]) -> List[Dict[str, Any]]:
    notes: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            if current:
                notes.append(current)
            current = {"title": line[3:].strip(), "tags": [], "draft_summary": ""}
        elif line.lower().startswith("keywords:") and current is not None:
            val = line.split(":", 1)[1]
            tags = [_normalize_tag(t, synonyms) for t in val.split(",")]
            tags = sorted({t for t in tags if t})
            current["tags"] = tags
        elif line.lower().startswith("draft summary:") and current is not None:
            current["draft_summary"] = line.split(":", 1)[1].strip()
    if current:
        notes.append(current)
    return notes


def _expected_index_and_rough(notes: List[Dict[str, Any]], categories: List[str]) -> Tuple[Dict[str, Any], List[str]]:
    index_notes = []
    for n in notes:
        index_notes.append(
            {
                "title": n["title"],
                "tags": n["tags"],
                "has_draft_summary": bool(n.get("draft_summary", "")),
                "config_categories": categories,
            }
        )
    expected_index = {"notes": index_notes}

    lines = ["Rough Summaries", "---------------"]
    for i, n in enumerate(notes, 1):
        prefix = f"{i}. {n['title']}: "
        if n.get("draft_summary", ""):
            lines.append(prefix + n["draft_summary"])
        else:
            lines.append(prefix + "No draft summary provided.")
    return expected_index, lines


def _json_equal_for_required_fields(actual_notes: List[Dict[str, Any]], expected_notes: List[Dict[str, Any]]) -> bool:
    if len(actual_notes) != len(expected_notes):
        return False
    for a, e in zip(actual_notes, expected_notes):
        for key in ["title", "tags", "has_draft_summary", "config_categories"]:
            if key not in a:
                return False
            if a[key] != e[key]:
                return False
    return True


def _split_sentences_generic(text: str) -> List[str]:
    parts = [p.strip() for p in re.split(r"[.!?]", text)]
    non_empty = [p for p in parts if p]
    return non_empty


def _contains_hedging(text: str) -> bool:
    t = text.lower()
    hedges = [
        "i think",
        "maybe",
        "i guess",
        "i'm not",
        "not sure",
        "probably",
        "might",
        "perhaps",
        "seems",
        "appears",
        "i suspect",
    ]
    return any(h in t for h in hedges)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "analysis_log_has_command": 0.0,
        "analysis_log_has_keyerror_line": 0.0,
        "analysis_log_explains_cause_and_fix": 0.0,
        "config_categories_present_and_correct": 0.0,
        "config_synonyms_preserved_after_fix": 0.0,
        "notes_index_json_exists_valid": 0.0,
        "notes_index_matches_expected": 0.0,
        "rough_summaries_header_correct": 0.0,
        "rough_summaries_items_match_expected": 0.0,
        "rewritten_summaries_numbering_and_titles_match": 0.0,
        "rewritten_summaries_one_sentence_max_25_words": 0.0,
        "rewritten_summaries_no_hedging": 0.0,
    }

    # Paths
    config_path = workspace / "config" / "tag_rules.json"
    organize_script_path = workspace / "scripts" / "organize_notes.py"
    notes_md_path = workspace / "input" / "notes" / "beliefs_and_values.md"
    analysis_log_path = workspace / "output" / "analysis_log.txt"
    notes_index_path = workspace / "output" / "notes_index.json"
    rough_summaries_path = workspace / "output" / "rough_summaries.md"
    rewritten_summaries_path = workspace / "output" / "rewritten_summaries.md"

    # Load inputs/outputs
    config_data = _load_json(config_path)
    notes_md = _read_text(notes_md_path)
    analysis_log_text = _read_text(analysis_log_path)
    notes_index_json = _load_json(notes_index_path)
    rough_summaries_text = _read_text(rough_summaries_path)
    rewritten_summaries_text = _read_text(rewritten_summaries_path)

    # Analysis log checks
    if analysis_log_text is not None:
        lines = [l.rstrip("\r\n") for l in analysis_log_text.splitlines()]
        cmd_present = any(re.match(r"^\s*(python|python3)\b.*\bscripts/organize_notes\.py\b", ln) for ln in lines)
        if cmd_present:
            scores["analysis_log_has_command"] = 1.0

        keyerr_present = any(("KeyError" in ln and "categories" in ln) for ln in lines)
        if keyerr_present:
            scores["analysis_log_has_keyerror_line"] = 1.0

        explanation_lines = []
        for ln in lines:
            if re.match(r"^\s*(python|python3)\b.*\bscripts/organize_notes\.py\b", ln):
                continue
            if ("KeyError" in ln and "categories" in ln):
                continue
            explanation_lines.append(ln)
        explanation_text = " ".join(explanation_lines).strip()
        sentence_candidates = [s.strip() for s in re.split(r"[.!?]", explanation_text) if s.strip()]
        sentences_count = len(sentence_candidates)
        mentions_cause = ("config" in explanation_text.lower() and "category" in explanation_text.lower() and "categories" in explanation_text.lower())
        mentions_fix = any(w in explanation_text.lower() for w in ["rename", "renamed", "change", "changed", "fix", "fixed", "align", "aligned"])
        if 2 <= sentences_count <= 3 and mentions_cause and mentions_fix:
            scores["analysis_log_explains_cause_and_fix"] = 1.0

    # Config checks
    categories_list: Optional[List[str]] = None
    synonyms_dict: Dict[str, str] = {}
    if isinstance(config_data, dict):
        cats = config_data.get("categories")
        if isinstance(cats, list) and all(isinstance(x, str) for x in cats):
            required_categories = {"beliefs", "motivation", "mindset", "values"}
            if required_categories.issubset(set(cats)):
                scores["config_categories_present_and_correct"] = 1.0
            categories_list = cats
        syn = config_data.get("tag_synonyms")
        if isinstance(syn, dict):
            synonyms_dict = {str(k): str(v) for k, v in syn.items()}
        else:
            synonyms_dict = {}

        # Award "synonyms preserved" only when categories key exists (i.e., fix applied)
        if categories_list is not None and isinstance(synonyms_dict, dict):
            required_syn = {
                "growth mindset": "growth-mindset",
                "fixed mindset": "fixed-mindset",
                "self-judgment": "self-criticism",
                "belief": "beliefs",
            }
            preserved = all(synonyms_dict.get(k) == v for k, v in required_syn.items())
            if preserved:
                scores["config_synonyms_preserved_after_fix"] = 1.0

    # Compute expected outputs where possible
    expected_index: Optional[Dict[str, Any]] = None
    expected_rough_lines: Optional[List[str]] = None
    parsed_notes: Optional[List[Dict[str, Any]]] = None

    if notes_md is not None and categories_list is not None:
        parsed_notes = _parse_notes_md(notes_md, synonyms_dict)
        expected_index, expected_rough_lines = _expected_index_and_rough(parsed_notes, categories_list)

    # notes_index.json structure check
    if isinstance(notes_index_json, dict):
        notes_arr = notes_index_json.get("notes")
        if isinstance(notes_arr, list):
            valid = True
            for item in notes_arr:
                if not isinstance(item, dict):
                    valid = False
                    break
                if not all(k in item for k in ["title", "tags", "has_draft_summary", "config_categories"]):
                    valid = False
                    break
                if not isinstance(item.get("title"), str):
                    valid = False
                    break
                if not isinstance(item.get("tags"), list) or not all(isinstance(t, str) for t in item.get("tags")):
                    valid = False
                    break
                if not isinstance(item.get("has_draft_summary"), bool):
                    valid = False
                    break
                if not isinstance(item.get("config_categories"), list) or not all(isinstance(c, str) for c in item.get("config_categories")):
                    valid = False
                    break
            if valid:
                scores["notes_index_json_exists_valid"] = 1.0

    # notes_index.json matches expected
    if expected_index is not None and isinstance(notes_index_json, dict) and "notes" in notes_index_json:
        if _json_equal_for_required_fields(notes_index_json.get("notes", []), expected_index.get("notes", [])):
            scores["notes_index_matches_expected"] = 1.0

    # rough_summaries checks
    if rough_summaries_text is not None:
        rough_lines = [l.rstrip("\r\n") for l in rough_summaries_text.splitlines()]
        if len(rough_lines) >= 2:
            if rough_lines[0] == "Rough Summaries" and rough_lines[1] == "---------------":
                scores["rough_summaries_header_correct"] = 1.0
        if expected_rough_lines is not None:
            if rough_lines == expected_rough_lines:
                scores["rough_summaries_items_match_expected"] = 1.0

    # rewritten_summaries checks
    if rewritten_summaries_text is not None:
        rewrite_lines_all = [l.rstrip("\r\n") for l in rewritten_summaries_text.splitlines()]
        item_pattern = re.compile(r"^\s*(\d+)\.\s+(.+?):\s+(.*\S)\s*$")
        item_lines = []
        for ln in rewrite_lines_all:
            m = item_pattern.match(ln)
            if m:
                item_lines.append(ln)
        titles_expected: List[str] = []
        if expected_rough_lines is not None:
            for ln in expected_rough_lines[2:]:
                m = item_pattern.match(ln)
                if m:
                    titles_expected.append(m.group(2))
        elif notes_md is not None:
            # Fall back to titles parsed from notes (without requiring config fix) for numbering-title validation only
            parsed = _parse_notes_md(notes_md, {})  # titles unaffected by synonyms
            titles_expected = [n["title"] for n in parsed]

        numbering_titles_ok = False
        if titles_expected and len(item_lines) == len(titles_expected):
            numbering_titles_ok = True
            for i, (ln, expected_title) in enumerate(zip(item_lines, titles_expected), 1):
                m = item_pattern.match(ln)
                if not m:
                    numbering_titles_ok = False
                    break
                num = int(m.group(1))
                title = m.group(2)
                if num != i or title != expected_title:
                    numbering_titles_ok = False
                    break
        if numbering_titles_ok:
            scores["rewritten_summaries_numbering_and_titles_match"] = 1.0

        sentence_length_ok = False
        no_hedging_ok = False
        if numbering_titles_ok:
            sentence_length_ok = True
            no_hedging_ok = True
            for ln in item_lines:
                m = item_pattern.match(ln)
                if not m:
                    sentence_length_ok = False
                    no_hedging_ok = False
                    break
                text = m.group(3).strip()
                sentences = _split_sentences_generic(text)
                one_sentence = (len(sentences) == 1)
                words = [w for w in re.split(r"\s+", text.strip()) if w]
                if not one_sentence or len(words) > 25:
                    sentence_length_ok = False
                if _contains_hedging(text):
                    no_hedging_ok = False
        if sentence_length_ok:
            scores["rewritten_summaries_one_sentence_max_25_words"] = 1.0
        if no_hedging_ok:
            scores["rewritten_summaries_no_hedging"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()