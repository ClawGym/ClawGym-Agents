import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[dict]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[dict]]:
    out = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                out.append(obj)
        return out
    except Exception:
        return None


def _tokenize_basic(text: str) -> List[str]:
    # Lowercase, treat hyphens as separators (replace with spaces),
    # ignore apostrophes (remove), remove other punctuation, split on whitespace.
    if not isinstance(text, str):
        return []
    s = text.lower()
    s = s.replace("-", " ")
    s = s.replace("’", "'")
    s = s.replace("‘", "'")
    s = s.replace("`", "'")
    s = s.replace("'", "")  # ignore apostrophes
    cleaned = []
    for ch in s:
        if ch.isalnum() or ch.isspace():
            cleaned.append(ch)
    s2 = "".join(cleaned)
    tokens = s2.split()
    return tokens


def _count_keywords(text: str, keywords: List[str]) -> Dict[str, int]:
    tokens = _tokenize_basic(text)
    counts: Dict[str, int] = {k: 0 for k in keywords}
    for t in tokens:
        if t in counts:
            counts[t] += 1
    return counts


def _load_keywords(workspace: Path) -> Optional[List[str]]:
    kw_csv = workspace / "input" / "keywords.csv"
    rows = _load_csv_dicts(kw_csv)
    if rows is None:
        return None
    try:
        with kw_csv.open("r", encoding="utf-8", newline="") as f:
            header_line = f.readline()
    except Exception:
        return None
    header = [h.strip().lower() for h in header_line.strip().split(",")] if header_line else []
    if "keyword" not in header:
        return None
    keywords = []
    for r in rows:
        if "keyword" not in r:
            return None
        v = (r["keyword"] or "").strip().lower()
        if v:
            keywords.append(v)
    if not keywords:
        return None
    return keywords


def _extract_chapter_labels_from_text(txt: str) -> List[str]:
    labels = []
    for line in txt.splitlines():
        if line.startswith("CHAPTER"):
            labels.append(line.rstrip("\r\n"))
    return labels


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "downloads_wikipedia_biodiversity_html": 0.0,
        "downloads_wikipedia_ecology_html": 0.0,
        "downloads_gutenberg_origin_text": 0.0,
        "extracted_wikipedia_biodiversity_jsonl_valid": 0.0,
        "extracted_wikipedia_ecology_jsonl_valid": 0.0,
        "extracted_gutenberg_chapters_jsonl_valid": 0.0,
        "keyword_counts_csv_structure": 0.0,
        "keyword_counts_csv_counts_match": 0.0,
        "summary_json_correct": 0.0,
        "report_includes_sources_and_segment_counts": 0.0,
        "report_includes_top_three_keywords": 0.0,
    }

    # File paths
    biod_html = workspace / "downloads" / "wikipedia" / "biodiversity.html"
    ecol_html = workspace / "downloads" / "wikipedia" / "ecology.html"
    guten_txt = workspace / "downloads" / "gutenberg" / "origin_of_species.txt"

    biod_jsonl = workspace / "extracted" / "wikipedia" / "biodiversity_sections.jsonl"
    ecol_jsonl = workspace / "extracted" / "wikipedia" / "ecology_sections.jsonl"
    guten_jsonl = workspace / "extracted" / "gutenberg" / "origin_of_species_chapters.jsonl"

    counts_csv = workspace / "output" / "keyword_counts.csv"
    summary_json = workspace / "output" / "summary.json"
    report_md = workspace / "REPORT.md"

    # Check downloads: Wikipedia HTML
    biod_html_text = _read_text(biod_html)
    ecol_html_text = _read_text(ecol_html)
    if biod_html_text and "<html" in biod_html_text.lower():
        scores["downloads_wikipedia_biodiversity_html"] = 1.0
    if ecol_html_text and "<html" in ecol_html_text.lower():
        scores["downloads_wikipedia_ecology_html"] = 1.0

    # Check Gutenberg text
    guten_text = _read_text(guten_txt)
    if guten_text and "chapter" in guten_text and "CHAPTER" in guten_text:
        scores["downloads_gutenberg_origin_text"] = 1.0

    # Load extracted JSONL files
    biod_sections = _load_jsonl(biod_jsonl)
    ecol_sections = _load_jsonl(ecol_jsonl)
    guten_chapters = _load_jsonl(guten_jsonl)

    # Validate wikipedia biodiversity sections JSONL
    valid_biod = False
    if biod_sections is not None and len(biod_sections) > 0:
        try:
            valid = True
            for rec in biod_sections:
                if not isinstance(rec.get("title"), str) or not isinstance(rec.get("section"), str) or not isinstance(rec.get("text"), str):
                    valid = False
                    break
                if rec.get("title") != "Biodiversity":
                    valid = False
                    break
                if rec.get("section", "").strip() == "":
                    valid = False
                    break
                if rec.get("text", "").strip() == "":
                    valid = False
                    break
            valid_biod = valid
        except Exception:
            valid_biod = False
    if valid_biod:
        scores["extracted_wikipedia_biodiversity_jsonl_valid"] = 1.0

    # Validate wikipedia ecology sections JSONL
    valid_ecol = False
    if ecol_sections is not None and len(ecol_sections) > 0:
        try:
            valid = True
            for rec in ecol_sections:
                if not isinstance(rec.get("title"), str) or not isinstance(rec.get("section"), str) or not isinstance(rec.get("text"), str):
                    valid = False
                    break
                if rec.get("title") != "Ecology":
                    valid = False
                    break
                if rec.get("section", "").strip() == "":
                    valid = False
                    break
                if rec.get("text", "").strip() == "":
                    valid = False
                    break
            valid_ecol = valid
        except Exception:
            valid_ecol = False
    if valid_ecol:
        scores["extracted_wikipedia_ecology_jsonl_valid"] = 1.0

    # Validate gutenberg chapters JSONL and labels match raw text markers
    valid_guten = False
    if guten_chapters is not None and len(guten_chapters) > 0 and isinstance(guten_text, str):
        try:
            for rec in guten_chapters:
                if not isinstance(rec.get("chapter"), str) or not isinstance(rec.get("text"), str):
                    valid_guten = False
                    break
                if not rec.get("chapter", "").startswith("CHAPTER"):
                    valid_guten = False
                    break
                if rec.get("text", "").strip() == "":
                    valid_guten = False
                    break
            else:
                labels_from_jsonl = [rec["chapter"] for rec in guten_chapters]
                labels_from_text = _extract_chapter_labels_from_text(guten_text)
                if len(labels_from_text) > 0 and set(labels_from_jsonl) == set(labels_from_text):
                    valid_guten = True
                else:
                    valid_guten = False
        except Exception:
            valid_guten = False
    if valid_guten:
        scores["extracted_gutenberg_chapters_jsonl_valid"] = 1.0

    # Load keywords
    keywords = _load_keywords(workspace)
    expected_counts: Dict[Tuple[str, str, str], int] = {}
    expected_totals: Dict[str, Dict[str, int]] = {}
    have_all_inputs = keywords is not None and valid_biod and valid_ecol and valid_guten

    if have_all_inputs:
        kws = keywords or []
        # Wikipedia Biodiversity
        src_biod = "wikipedia:Biodiversity"
        expected_totals[src_biod] = {k: 0 for k in kws}
        for rec in biod_sections:
            seg = rec["section"]
            counts = _count_keywords(rec["text"], kws)
            for k, v in counts.items():
                expected_counts[(src_biod, seg, k)] = v
                expected_totals[src_biod][k] += v
        # Wikipedia Ecology
        src_ecol = "wikipedia:Ecology"
        expected_totals[src_ecol] = {k: 0 for k in kws}
        for rec in ecol_sections:
            seg = rec["section"]
            counts = _count_keywords(rec["text"], kws)
            for k, v in counts.items():
                expected_counts[(src_ecol, seg, k)] = v
                expected_totals[src_ecol][k] += v
        # Gutenberg OriginOfSpecies
        src_guten = "gutenberg:OriginOfSpecies"
        expected_totals[src_guten] = {k: 0 for k in kws}
        for rec in guten_chapters:
            seg = rec["chapter"]
            counts = _count_keywords(rec["text"], kws)
            for k, v in counts.items():
                expected_counts[(src_guten, seg, k)] = v
                expected_totals[src_guten][k] += v

    # Validate keyword_counts.csv structure and counts
    csv_rows = _load_csv_dicts(counts_csv)
    csv_header_ok = False
    csv_counts_match = False
    if csv_rows is not None:
        try:
            with counts_csv.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline()
        except Exception:
            header_line = ""
        header = [h.strip() for h in header_line.strip().split(",")] if header_line else []
        if header == ["source", "segment", "keyword", "count"]:
            csv_header_ok = True

        if csv_header_ok and have_all_inputs:
            got_map: Dict[Tuple[str, str, str], int] = {}
            unique_ok = True
            try:
                for r in csv_rows:
                    src = (r.get("source") or "").strip()
                    seg = (r.get("segment") or "").strip()
                    kw = (r.get("keyword") or "").strip().lower()
                    cnt_raw = (r.get("count") or "").strip()
                    if src == "" or seg == "" or kw == "" or cnt_raw == "":
                        unique_ok = False
                        break
                    try:
                        cnt = int(cnt_raw)
                    except Exception:
                        unique_ok = False
                        break
                    key = (src, seg, kw)
                    if key in got_map:
                        unique_ok = False
                        break
                    got_map[key] = cnt
                if not unique_ok:
                    csv_counts_match = False
                else:
                    if set(got_map.keys()) != set(expected_counts.keys()):
                        csv_counts_match = False
                    else:
                        equal = True
                        for k, v in expected_counts.items():
                            if got_map.get(k) != v:
                                equal = False
                                break
                        csv_counts_match = equal
            except Exception:
                csv_counts_match = False

    if csv_header_ok:
        scores["keyword_counts_csv_structure"] = 1.0
    if csv_counts_match:
        scores["keyword_counts_csv_counts_match"] = 1.0

    # Validate summary.json correctness
    summary = _load_json(summary_json)
    summary_ok = False
    if summary is not None and have_all_inputs:
        try:
            expected_sources = {"wikipedia:Biodiversity", "wikipedia:Ecology", "gutenberg:OriginOfSpecies"}
            if set(summary.keys()) == expected_sources:
                all_match = True
                for src, totals in expected_totals.items():
                    got = summary.get(src)
                    if not isinstance(got, dict):
                        all_match = False
                        break
                    if set(got.keys()) != set(totals.keys()):
                        all_match = False
                        break
                    for kw, expected_val in totals.items():
                        gv = got.get(kw)
                        if not isinstance(gv, int):
                            all_match = False
                            break
                        if gv != expected_val:
                            all_match = False
                            break
                    if not all_match:
                        break
                summary_ok = all_match
            else:
                summary_ok = False
        except Exception:
            summary_ok = False
    if summary_ok:
        scores["summary_json_correct"] = 1.0

    # REPORT.md checks
    report_text = _read_text(report_md)
    report_sources_and_counts_ok = False
    report_top_keywords_ok = False
    if report_text is not None and isinstance(report_text, str) and report_text.strip():
        expected_segments_counts: Dict[str, int] = {}
        if have_all_inputs:
            expected_segments_counts["Biodiversity"] = len(biod_sections or [])
            expected_segments_counts["Ecology"] = len(ecol_sections or [])
            expected_segments_counts["Origin of Species"] = len(guten_chapters or [])

        def _has_number_near_marker(text: str, marker_lower: str, expected_num: int) -> bool:
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if marker_lower in line.lower():
                    block = "\n".join(lines[i:i+3])
                    nums = re.findall(r"\b\d+\b", block)
                    for n in nums:
                        try:
                            if int(n) == expected_num:
                                return True
                        except Exception:
                            pass
            return False

        try:
            has_biod = "biodiversity" in report_text.lower()
            has_ecol = "ecology" in report_text.lower()
            has_origin = ("origin of species" in report_text.lower()) or ("originofspecies" in report_text.lower())
            sources_present = has_biod and has_ecol and has_origin

            counts_correct = False
            if have_all_inputs and sources_present:
                biod_ok = _has_number_near_marker(report_text, "biodiversity", expected_segments_counts["Biodiversity"])
                ecol_ok = _has_number_near_marker(report_text, "ecology", expected_segments_counts["Ecology"])
                origin_ok = _has_number_near_marker(report_text, "origin of species", expected_segments_counts["Origin of Species"])
                counts_correct = biod_ok and ecol_ok and origin_ok

            report_sources_and_counts_ok = sources_present and (counts_correct if have_all_inputs else True)
        except Exception:
            report_sources_and_counts_ok = False

        if have_all_inputs:
            try:
                def _top_three(totals: Dict[str, int]) -> List[str]:
                    items = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
                    top = [k for k, v in items[:3]]
                    return top

                top_biod = _top_three(expected_totals.get("wikipedia:Biodiversity", {}))
                top_ecol = _top_three(expected_totals.get("wikipedia:Ecology", {}))
                top_guten = _top_three(expected_totals.get("gutenberg:OriginOfSpecies", {}))

                def _all_keywords_present(text: str, kws: List[str]) -> bool:
                    tl = text.lower()
                    return all(k.lower() in tl for k in kws)

                ok_biod = _all_keywords_present(report_text, top_biod) if top_biod else False
                ok_ecol = _all_keywords_present(report_text, top_ecol) if top_ecol else False
                ok_guten = _all_keywords_present(report_text, top_guten) if top_guten else False
                report_top_keywords_ok = ok_biod and ok_ecol and ok_guten
            except Exception:
                report_top_keywords_ok = False
        else:
            report_top_keywords_ok = False

    if report_sources_and_counts_ok:
        scores["report_includes_sources_and_segment_counts"] = 1.0
    if report_top_keywords_ok:
        scores["report_includes_top_three_keywords"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()