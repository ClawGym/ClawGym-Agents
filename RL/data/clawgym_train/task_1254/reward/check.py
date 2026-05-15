import json
import sys
import re
import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(row)
            return rows
    except Exception:
        return None


def _parse_yaml_rubric(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser tailored to the provided rubric.yaml structure.
    Returns dict with keys: version, weights (dict), must_haves (list), scoring_scale, notes.
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    result: Dict[str, Any] = {"weights": {}, "must_haves": []}
    i = 0
    current_section = None
    while i < len(lines):
        line = lines[i].rstrip("\n")
        # Top-level key:
        m = re.match(r"^([a-zA-Z0-9_]+):\s*(.*)$", line)
        if m and not line.startswith("  "):
            key = m.group(1)
            rest = m.group(2)
            current_section = key
            # Handle scalar immediate values
            if key not in ("weights", "must_haves"):
                val = rest.strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                elif val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                result[key] = val if val != "" else None
            i += 1
            continue
        # Inside sections
        if current_section == "weights":
            wm = re.match(r"^\s{2}([a-zA-Z0-9_]+):\s*([0-9]*\.?[0-9]+)\s*$", line)
            if wm:
                wkey = wm.group(1)
                try:
                    wval = float(wm.group(2))
                except Exception:
                    return None
                result["weights"][wkey] = wval
                i += 1
                continue
        if current_section == "must_haves":
            lm = re.match(r"^\s{2}-\s*(.+?)\s*$", line)
            if lm:
                item = lm.group(1)
                result["must_haves"].append(item)
                i += 1
                continue
        i += 1
    return result


def _extract_headings(md_text: str) -> List[str]:
    headings = []
    for line in md_text.splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading:
                headings.append(heading)
    return headings


def _averages_by_primer_type(rows: List[Dict[str, str]]) -> Optional[Dict[str, float]]:
    if rows is None:
        return None
    agg: Dict[str, Tuple[float, int]] = {}
    for row in rows:
        try:
            primer_type = row["primer_type"].strip()
            rating = float(row["adhesion_rating_1to5"])
        except Exception:
            return None
        if primer_type not in agg:
            agg[primer_type] = (rating, 1)
        else:
            s, c = agg[primer_type]
            agg[primer_type] = (s + rating, c + 1)
    averages: Dict[str, float] = {}
    for k, (s, c) in agg.items():
        averages[k] = round(s / c, 4)
    return averages


def _find_section(text: str, section_name: str) -> Optional[str]:
    """
    Finds section text starting from a line that matches section_name (case-insensitive)
    and returns content until the next top-level heading of same or higher level.
    """
    lines = text.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        if re.match(r"^\s*#{1,6}\s+.*$", line):
            heading_text = line.lstrip("#").strip().lower()
            if section_name.lower() in heading_text:
                start_idx = idx
                break
    if start_idx is None:
        return None
    level = len(lines[start_idx]) - len(lines[start_idx].lstrip("#"))
    collected = []
    for j in range(start_idx + 1, len(lines)):
        l = lines[j]
        if re.match(r"^\s*#{1,6}\s+.*$", l):
            lvl = len(l) - len(l.lstrip("#"))
            if lvl <= level:
                break
        collected.append(l)
    return "\n".join(collected).strip()


def _get_block_after_label(text: str, label: str) -> Optional[str]:
    lc_text = text.lower()
    pos = lc_text.find(label.lower())
    if pos == -1:
        return None
    after = text[pos:]
    lines = after.splitlines()
    collected = []
    for i, line in enumerate(lines[1:], start=1):
        if re.match(r"^\s*#{1,6}\s+.*$", line):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _parse_scores_for_guide(block_text: str, criteria: List[str]) -> Tuple[Dict[str, float], Optional[float]]:
    scores: Dict[str, float] = {}
    for crit in criteria:
        pattern = re.compile(rf"{re.escape(crit)}[^0-9]*([0-5](?:\.\d+)?)", re.IGNORECASE)
        m = pattern.search(block_text)
        if m:
            try:
                val = float(m.group(1))
                if 0.0 <= val <= 5.0:
                    scores[crit] = val
            except Exception:
                pass
    total = None
    mt = re.search(r"(weighted\s+total|total\s*\(weighted\))\s*[:\-]\s*([0-9]+(?:\.\d+)?)", block_text, re.IGNORECASE)
    if mt:
        try:
            total = float(mt.group(2))
        except Exception:
            total = None
    return scores, total


def _split_guides_blocks(section_text: str) -> Dict[str, str]:
    if not section_text:
        return {}
    blocks: Dict[str, str] = {}
    lc = section_text.lower()
    pos_a = lc.find("guide a")
    pos_b = lc.find("guide b")
    if pos_a == -1 and pos_b == -1:
        return {}
    indices = []
    if pos_a != -1:
        indices.append(("A", pos_a))
    if pos_b != -1:
        indices.append(("B", pos_b))
    indices.sort(key=lambda x: x[1])
    for idx, (label, start) in enumerate(indices):
        end = indices[idx + 1][1] if idx + 1 < len(indices) else len(section_text)
        blocks[label] = section_text[start:end]
    return blocks


def _parse_must_haves_compliance(section_text: str, must_haves: List[str]) -> Dict[str, Dict[str, Dict[str, str]]]:
    res: Dict[str, Dict[str, Dict[str, str]]] = {"A": {}, "B": {}}
    guide_blocks = _split_guides_blocks(section_text or "")
    for guide in ("A", "B"):
        block = guide_blocks.get(guide, "")
        for mh in must_haves:
            pattern = re.compile(rf"{re.escape(mh)}\s*[:\-]\s*(Pass|Fail)\b(.*)", re.IGNORECASE)
            m = pattern.search(block)
            if m:
                result = m.group(1).title()
                justification = m.group(2).strip()
                res[guide][mh] = {"result": "Pass" if result == "Pass" else "Fail", "justification": justification}
    return res


def _expected_must_have_result(guide_text: str, mh: str) -> Optional[bool]:
    if guide_text is None:
        return None
    lower = guide_text.lower()
    if mh == "avoid_plastic_cement_for_metal":
        if "avoid plastic cement" in lower or ("plastic cement" in lower and "will not bond" in lower):
            return True
        if "plastic cement works well" in lower or ("plastic cement" in lower and "works well" in lower):
            return False
        if ("cyanoacrylate" in lower or "ca" in lower) and "plastic cement" in lower:
            if "does not dissolve pewter" in lower or "will not bond" in lower:
                return True
        return None
    if mh == "call_out_cure_time_over_12h_for_etching":
        etch_present = "etching" in lower or "self-etch" in lower
        cure_matches = re.findall(r"([0-9]+)\s*hour", lower)
        hours = [int(h) for h in cure_matches] if cure_matches else []
        if etch_present and any(h >= 12 for h in hours):
            return True
        if etch_present and any(h < 12 for h in hours):
            return False
        if any(h >= 12 for h in hours) and "prim" in lower:
            return True
        return False if any(h < 12 for h in hours) else None
    return None


def _find_numbers_in_line(line: str) -> List[float]:
    nums = []
    for m in re.finditer(r"([0-9]+(?:\.[0-9]+)?)", line):
        try:
            nums.append(float(m.group(1)))
        except Exception:
            continue
    return nums


def _section_contains_headings(section_text: str, headings: List[str]) -> bool:
    if not section_text:
        return False
    lc = section_text.lower()
    for h in headings:
        if h.strip() and h.lower() in lc:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "rubric_weights_updated": 0.0,
        "rubric_must_haves_updated": 0.0,
        "rubric_scoring_scale_and_notes_preserved": 0.0,
        "critique_summary_present_and_focus_metal": 0.0,
        "critique_scoring_summary_numbers_valid": 0.0,
        "critique_must_haves_compliance_consistent_with_guides": 0.0,
        "evidence_notes_csv_averages_reported": 0.0,
        "evidence_notes_guide_citations_present": 0.0,
        "recommendations_each_guide_count": 0.0,
        "highlights_json_entries_complete_and_valid": 0.0,
    }

    # Paths
    config_path = workspace / "config" / "rubric.yaml"
    guide_a_path = workspace / "input" / "guide_a.md"
    guide_b_path = workspace / "input" / "guide_b.md"
    csv_path = workspace / "input" / "photos_notes.csv"
    draft_review_path = workspace / "input" / "draft_review.md"
    critique_path = workspace / "outputs" / "critique.md"
    highlights_path = workspace / "outputs" / "highlights.json"

    # Load files
    config = _parse_yaml_rubric(config_path) if config_path.exists() else None
    guide_a = _read_text(guide_a_path) if guide_a_path.exists() else None
    guide_b = _read_text(guide_b_path) if guide_b_path.exists() else None
    draft_review = _read_text(draft_review_path) if draft_review_path.exists() else None
    critique = _read_text(critique_path) if critique_path.exists() else None
    highlights = _load_json(highlights_path) if highlights_path.exists() else None
    csv_rows = _read_csv_dicts(csv_path) if csv_path.exists() else None
    averages = _averages_by_primer_type(csv_rows) if csv_rows is not None else None

    # Expected configuration updates
    expected_weights = {
        "surface_prep_clarity": 0.20,
        "primer_evidence": 0.20,
        "metal_specifics": 0.35,
        "safety_practices": 0.10,
        "adhesive_and_jointing": 0.10,
        "tool_list_completeness": 0.05,
    }
    other_originals = {
        "paint_layering_detail": 0.15,
        "weathering_guidance": 0.10,
    }
    expected_must_haves = ["avoid_plastic_cement_for_metal", "call_out_cure_time_over_12h_for_etching"]

    # Check rubric weights updated
    weights_updated = False
    if config and isinstance(config.get("weights"), dict):
        weights = config["weights"]
        ok_updated = all(weights.get(k) == v for k, v in expected_weights.items())
        ok_others_intact = all(k in weights and abs(weights.get(k) - v) < 1e-9 for k, v in other_originals.items())
        if ok_updated and ok_others_intact:
            scores["rubric_weights_updated"] = 1.0
            weights_updated = True

    # Check must_haves updated
    musts_updated = False
    if config and isinstance(config.get("must_haves"), list):
        mh_list = config["must_haves"]
        has_both = all(mh in mh_list for mh in expected_must_haves)
        if has_both:
            scores["rubric_must_haves_updated"] = 1.0
            musts_updated = True

    # Check scoring_scale and notes preserved, only if weights were correctly updated (to avoid awarding points on scaffold)
    if config and weights_updated:
        ss_present = "scoring_scale" in config and isinstance(config.get("scoring_scale"), str) and config.get("scoring_scale") != ""
        notes_present = "notes" in config and isinstance(config.get("notes"), str) and config.get("notes") != ""
        scores["rubric_scoring_scale_and_notes_preserved"] = 1.0 if ss_present and notes_present else 0.0

    # Critique summary present and focus on metal-specific suitability
    if critique:
        top_lines = critique.splitlines()
        summary_lines = []
        for line in top_lines:
            if re.match(r"^\s*#{1,6}\s+.*$", line):
                if "scoring summary" in line.lower():
                    break
                continue
            summary_lines.append(line)
        text_block = "\n".join(summary_lines).strip()
        paragraphs = [p for p in re.split(r"\n\s*\n", text_block) if p.strip()]
        para_ok = 1 <= len(paragraphs) <= 2
        focus_terms = sum(1 for t in ("metal", "pewter", "white-metal") if t in text_block.lower())
        mentions_guides = ("guide a" in text_block.lower()) and ("guide b" in text_block.lower())
        scores["critique_summary_present_and_focus_metal"] = 1.0 if para_ok and focus_terms >= 1 and mentions_guides else 0.0

    # Scoring Summary numbers valid: parse raw scores and recompute weighted totals
    criteria_keys = list(expected_weights.keys())
    if critique and config and "weights" in config and isinstance(config["weights"], dict):
        weights = config["weights"]
        scoring_section = _find_section(critique, "Scoring Summary")
        if not scoring_section:
            scoring_section = _get_block_after_label(critique, "Scoring Summary")
        if scoring_section:
            guide_blocks = _split_guides_blocks(scoring_section)
            recompute_ok_count = 0
            for guide_label in ("A", "B"):
                block = guide_blocks.get(guide_label, "")
                scores_dict, reported_total = _parse_scores_for_guide(block, criteria_keys)
                if len(scores_dict) == len(criteria_keys) and reported_total is not None:
                    recomputed = 0.0
                    for k in criteria_keys:
                        raw = scores_dict.get(k, 0.0)
                        wt = weights.get(k, 0.0)
                        recomputed += raw * wt
                    if abs(recomputed - reported_total) <= 0.05:
                        recompute_ok_count += 1
            if recompute_ok_count == 2:
                scores["critique_scoring_summary_numbers_valid"] = 1.0
            elif recompute_ok_count == 1:
                scores["critique_scoring_summary_numbers_valid"] = 0.5
            else:
                scores["critique_scoring_summary_numbers_valid"] = 0.0

    # Must-haves compliance consistent with guides
    if critique and guide_a and guide_b and config and isinstance(config.get("must_haves"), list):
        must_section = _find_section(critique, "Must-haves")
        if not must_section:
            must_section = _find_section(critique, "Must-haves compliance")
        if not must_section:
            must_section = _get_block_after_label(critique, "Must-haves")
        if not must_section:
            must_section = _get_block_after_label(critique, "Must-haves compliance")
        if must_section:
            comp = _parse_must_haves_compliance(must_section, expected_must_haves)
            total_checks = 0
            correct_checks = 0
            a_headings = _extract_headings(guide_a)
            b_headings = _extract_headings(guide_b)
            for guide_label, guide_text in (("A", guide_a), ("B", guide_b)):
                for mh in expected_must_haves:
                    total_checks += 1
                    stated = comp.get(guide_label, {}).get(mh)
                    if not stated:
                        continue
                    expected = _expected_must_have_result(guide_text, mh)
                    if expected is None:
                        continue
                    stated_pass = stated.get("result") == ("Pass" if expected else "Fail")
                    justification = stated.get("justification", "")
                    has_heading = _section_contains_headings(justification, a_headings if guide_label == "A" else b_headings)
                    has_snippet = len(justification.strip()) >= 10
                    if stated_pass and has_heading and has_snippet:
                        correct_checks += 1
            if total_checks > 0:
                scores["critique_must_haves_compliance_consistent_with_guides"] = correct_checks / total_checks
            else:
                scores["critique_must_haves_compliance_consistent_with_guides"] = 0.0

    # Evidence notes CSV averages reported
    if critique and averages:
        evidence_section = _find_section(critique, "Evidence")
        if not evidence_section:
            evidence_section = _find_section(critique, "Evidence notes")
        if not evidence_section:
            evidence_section = _get_block_after_label(critique, "Evidence")
        if not evidence_section:
            evidence_section = _get_block_after_label(critique, "Evidence notes")
        covered = 0
        total = len(averages)
        if evidence_section:
            lines = evidence_section.splitlines()
            for primer_type, avg in averages.items():
                found = False
                for line in lines:
                    if primer_type.lower() in line.lower():
                        nums = _find_numbers_in_line(line)
                        for n in nums:
                            if abs(n - avg) <= 0.05:
                                found = True
                                break
                        if found:
                            break
                if found:
                    covered += 1
        scores["evidence_notes_csv_averages_reported"] = (covered / total) if total > 0 else 0.0

    # Evidence notes include guide citations by section heading
    if critique and guide_a and guide_b:
        ev_section = _find_section(critique, "Evidence")
        if not ev_section:
            ev_section = _find_section(critique, "Evidence notes")
        a_heads = _extract_headings(guide_a)
        b_heads = _extract_headings(guide_b)
        a_ok = _section_contains_headings(ev_section or "", a_heads)
        b_ok = _section_contains_headings(ev_section or "", b_heads)
        scores["evidence_notes_guide_citations_present"] = 1.0 if a_ok and b_ok else 0.0

    # Recommendations: at least 3 for each guide
    if critique:
        rec_section = _find_section(critique, "Recommendations")
        if not rec_section:
            rec_section = _get_block_after_label(critique, "Recommendations")
        count_a = 0
        count_b = 0
        if rec_section:
            blocks = _split_guides_blocks(rec_section)
            block_a = blocks.get("A", rec_section)
            block_b = blocks.get("B", rec_section)
            for line in block_a.splitlines():
                if re.match(r"^\s*[-*]\s+", line):
                    count_a += 1
            for line in block_b.splitlines():
                if re.match(r"^\s*[-*]\s+", line):
                    count_b += 1
        ok_a = 1.0 if count_a >= 3 else 0.0
        ok_b = 1.0 if count_b >= 3 else 0.0
        scores["recommendations_each_guide_count"] = (ok_a + ok_b) / 2.0

    # Highlights JSON validation
    if highlights and guide_a and guide_b:
        entries = highlights if isinstance(highlights, list) else []
        a_heads = _extract_headings(guide_a)
        b_heads = _extract_headings(guide_b)
        criteria_keys = list(expected_weights.keys())
        required_pairs = [(g, c) for g in ("A", "B") for c in criteria_keys]
        pair_covered = {pair: False for pair in required_pairs}
        for e in entries:
            if not isinstance(e, dict):
                continue
            g = e.get("guide")
            c = e.get("criterion")
            section = e.get("section")
            snippet = e.get("snippet", "")
            if g not in ("A", "B"):
                continue
            if c not in criteria_keys:
                continue
            heads = a_heads if g == "A" else b_heads
            if section not in heads:
                continue
            g_text = guide_a if g == "A" else guide_b
            if not snippet or snippet.strip() == "":
                continue
            if snippet not in g_text:
                continue
            pair_covered[(g, c)] = True
        coverage = sum(1 for v in pair_covered.values() if v)
        total_needed = len(required_pairs)
        scores["highlights_json_entries_complete_and_valid"] = (coverage / total_needed) if total_needed > 0 else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()