import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _is_markdown_heading_line(s: str) -> bool:
    st = s.strip()
    return st.startswith("#")


def _normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _parse_config_selected_themes(config_path: Path) -> Optional[List[str]]:
    cfg = _safe_load_json(config_path)
    if not isinstance(cfg, dict):
        return None
    st = cfg.get("selected_themes")
    if not isinstance(st, list):
        return None
    themes: List[str] = []
    for t in st:
        if isinstance(t, str):
            themes.append(t.strip().lower())
        else:
            return None
    return themes


TAG_LINE_RE = re.compile(r'^#tags:\s*\[(.*?)\]\s*$', re.MULTILINE)
QUOTE_LINE_RE = re.compile(r'^-\s*QUOTE:\s*\"(.*?)\"\s*$', re.MULTILINE)
TITLE_RE = re.compile(r'^Title:\s*(.*)\s*$', re.MULTILINE)
EPISODE_RE = re.compile(r'^Episode:\s*(.*)\s*$', re.MULTILINE)


def _parse_tags(text: str) -> List[str]:
    m = TAG_LINE_RE.search(text)
    if not m:
        return []
    raw = m.group(1)
    tags = [t.strip() for t in raw.split(',') if t.strip()]
    return tags


def _find_quotes_with_line_numbers(text: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        m = QUOTE_LINE_RE.match(line)
        if m:
            results.append({'quote': m.group(1), 'line_no': idx})
    return results


def _parse_title(text: str) -> str:
    m = TITLE_RE.search(text)
    return m.group(1).strip() if m else ''


def _parse_episode(text: str) -> str:
    m = EPISODE_RE.search(text)
    return m.group(1).strip() if m else ''


def _collect_expected_quotes(notes_dir: Path, selected_themes: List[str], workspace_root: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not notes_dir.exists() or not notes_dir.is_dir():
        return out
    for path in sorted(notes_dir.rglob("*.md")):
        text = _safe_read_text(path)
        if text is None:
            continue
        file_tags = _parse_tags(text)
        quotes = _find_quotes_with_line_numbers(text)
        title = _parse_title(text)
        episode = _parse_episode(text)
        relevant = sorted(set(t for t in file_tags if t in selected_themes))
        for q in quotes:
            q_tags = relevant
            if not q_tags:
                continue
            try:
                rel = str(path.relative_to(workspace_root))
            except Exception:
                rel = str(path)
            out.append({
                'episode': episode,
                'title': title,
                'quote': q['quote'],
                'tags': q_tags,
                'source_file': rel,
                'line_no': q['line_no']
            })
    def episode_key(e: Dict[str, Any]):
        try:
            return (int(e.get('episode', 0)), e.get('line_no', 0))
        except ValueError:
            return (e.get('episode', ''), e.get('line_no', 0))
    out.sort(key=episode_key)
    return out


def _load_quotes_used(path: Path) -> Optional[List[Dict[str, Any]]]:
    data = _safe_load_json(path)
    if not isinstance(data, list):
        return None
    validated: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            return None
        if not all(k in item for k in ("episode", "title", "quote", "tags", "source_file", "line_no")):
            return None
        if not isinstance(item["episode"], str):
            return None
        if not isinstance(item["title"], str):
            return None
        if not isinstance(item["quote"], str):
            return None
        if not isinstance(item["tags"], list) or not all(isinstance(t, str) for t in item["tags"]):
            return None
        if not isinstance(item["source_file"], str):
            return None
        if not isinstance(item["line_no"], int):
            return None
        validated.append(item)
    return validated


def _find_section_indices(lines: List[str], heading_name: str) -> Optional[int]:
    target = heading_name.strip()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == target:
            return idx
        if stripped.startswith("#"):
            stripped2 = stripped.lstrip("#").strip()
            if stripped2 == target:
                return idx
    return None


def _extract_body_text(essay_text: str) -> str:
    lines = essay_text.splitlines()
    start_idx = 0
    # Assume body starts after the outline, but outline isn't strictly formatted; treat entire doc as body until Sources/Appendix
    end_idx_candidates = []
    si = _find_section_indices(lines, "Sources")
    if si is not None:
        end_idx_candidates.append(si)
    ai = _find_section_indices(lines, "Appendix: Quotes Used")
    if ai is not None:
        end_idx_candidates.append(ai)
    if end_idx_candidates:
        end_idx = min(end_idx_candidates)
        return "\n".join(lines[start_idx:end_idx])
    return essay_text


def _extract_section_block(lines: List[str], section_heading: str) -> List[str]:
    start = _find_section_indices(lines, section_heading)
    if start is None:
        return []
    content_lines: List[str] = []
    for idx in range(start + 1, len(lines)):
        l = lines[idx]
        if _is_markdown_heading_line(l):
            break
        stripped = l.strip()
        if stripped in ("Sources", "Appendix: Quotes Used"):
            break
        content_lines.append(l)
    while content_lines and content_lines[-1].strip() == "":
        content_lines.pop()
    return content_lines


def _extract_cited_quotes_from_body(body_text: str) -> List[Tuple[str, str, str]]:
    pattern = re.compile(r'"([^"\n]+)"\s*\[\s*Episode\s+(\d+)\s*:\s*([^\]]+?)\s*\]')
    results: List[Tuple[str, str, str]] = []
    for m in pattern.finditer(body_text):
        quote = m.group(1).strip()
        ep = m.group(2).strip()
        title = m.group(3).strip()
        results.append((quote, ep, title))
    return results


def _word_count(text: str) -> int:
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def _lower_words_set(text: str) -> set:
    return set(w.lower() for w in re.findall(r"[A-Za-z]+", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "quotes_used_json_valid": 0.0,
        "quotes_used_json_matches_expected": 0.0,
        "essay_exists_and_length_700_900": 0.0,
        "outline_lists_three_themes_top": 0.0,
        "quotes_citations_from_json": 0.0,
        "at_least_four_distinct_quotes": 0.0,
        "per_theme_quote_coverage": 0.0,
        "no_reused_quotes_in_body": 0.0,
        "sources_section_lists_unique_episodes": 0.0,
        "appendix_lists_used_quotes_with_themes": 0.0,
    }

    notes_dir = workspace / "notes"
    config_path = workspace / "config" / "themes.json"
    quotes_json_path = workspace / "output" / "quotes_used.json"
    essay_path = workspace / "output" / "essay.md"

    themes = _parse_config_selected_themes(config_path)

    quotes_used = _load_quotes_used(quotes_json_path)
    if quotes_used is not None:
        scores["quotes_used_json_valid"] = 1.0

    expected_quotes: List[Dict[str, Any]] = []
    if isinstance(themes, list) and themes:
        expected_quotes = _collect_expected_quotes(notes_dir, themes, workspace)

    if quotes_used is not None and expected_quotes:
        try:
            def norm_list(lst: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                return [
                    {
                        "episode": item["episode"],
                        "title": item["title"],
                        "quote": item["quote"],
                        "tags": list(item["tags"]),
                        "source_file": item["source_file"],
                        "line_no": item["line_no"],
                    }
                    for item in lst
                ]
            if norm_list(quotes_used) == norm_list(expected_quotes):
                scores["quotes_used_json_matches_expected"] = 1.0
        except Exception:
            pass

    essay_text = _safe_read_text(essay_path)
    if essay_text is not None:
        body_text = _extract_body_text(essay_text)
        wc = _word_count(body_text)
        if 700 <= wc <= 900:
            scores["essay_exists_and_length_700_900"] = 1.0

        # Outline check in first 15 non-empty lines
        non_empty_top: List[str] = []
        for line in essay_text.splitlines():
            if line.strip():
                non_empty_top.append(line)
            if len(non_empty_top) >= 15:
                break
        top_blob = "\n".join(non_empty_top)
        words_set = _lower_words_set(top_blob)
        if {"memory", "surveillance", "identity"}.issubset(words_set):
            scores["outline_lists_three_themes_top"] = 1.0

        cited = _extract_cited_quotes_from_body(body_text)

        quote_to_records: Dict[str, List[Dict[str, Any]]] = {}
        if quotes_used is not None:
            for rec in quotes_used:
                quote_to_records.setdefault(rec["quote"], []).append(rec)

        valid_all = True
        used_quote_texts: List[str] = []
        used_episode_title_pairs: set = set()
        used_tags_union: set = set()
        for (qtext, ep, title) in cited:
            used_quote_texts.append(qtext)
            used_episode_title_pairs.add((ep, title))
            recs = quote_to_records.get(qtext)
            if not recs:
                valid_all = False
                continue
            if not any((rec.get("episode") == ep and rec.get("title") == title) for rec in recs):
                valid_all = False
                continue
            for rec in recs:
                if rec.get("episode") == ep and rec.get("title") == title:
                    for t in rec.get("tags", []):
                        used_tags_union.add(t.lower())
        if cited and valid_all:
            scores["quotes_citations_from_json"] = 1.0

        if len(set(used_quote_texts)) >= 4:
            scores["at_least_four_distinct_quotes"] = 1.0

        if len(used_quote_texts) > 0 and len(set(used_quote_texts)) == len(used_quote_texts):
            scores["no_reused_quotes_in_body"] = 1.0

        if {"memory", "surveillance", "identity"}.issubset(used_tags_union):
            scores["per_theme_quote_coverage"] = 1.0

        lines = essay_text.splitlines()
        sources_block = _extract_section_block(lines, "Sources")
        if sources_block:
            src_pairs: set = set()
            pat = re.compile(r'\bEpisode\s+(\d+)\s*:\s*(.+)\s*$')
            for line in sources_block:
                m = pat.search(line)
                if m:
                    ep = m.group(1).strip()
                    title = m.group(2).strip()
                    src_pairs.add((ep, title))
            if used_episode_title_pairs and src_pairs == used_episode_title_pairs:
                scores["sources_section_lists_unique_episodes"] = 1.0

        appendix_block = _extract_section_block(lines, "Appendix: Quotes Used")
        if appendix_block and quotes_used is not None and cited:
            quote_to_records_map: Dict[str, List[Dict[str, Any]]] = {}
            for rec in quotes_used:
                quote_to_records_map.setdefault(rec["quote"], []).append(rec)
            expected_tags_by_quote: Dict[str, set] = {}
            for (qtext, ep, title) in cited:
                for rec in quote_to_records_map.get(qtext, []):
                    if rec.get("episode") == ep and rec.get("title") == title:
                        expected_tags_by_quote[qtext] = set(t.lower() for t in rec.get("tags", []))
                        break
            appendix_ok = True
            for qtext, tags_expected in expected_tags_by_quote.items():
                found_line = None
                for l in appendix_block:
                    if qtext in l:
                        found_line = l
                        break
                if not found_line:
                    appendix_ok = False
                    break
                present = set()
                lwr = found_line.lower()
                for th in ("memory", "surveillance", "identity"):
                    if re.search(r'\b' + re.escape(th) + r'\b', lwr):
                        present.add(th)
                if present != tags_expected:
                    appendix_ok = False
                    break
            if appendix_ok and expected_tags_by_quote:
                scores["appendix_lists_used_quotes_with_themes"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()