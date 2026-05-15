import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _iso_date_ok(s: str) -> bool:
    try:
        try:
            datetime.fromisoformat(s)
            return True
        except Exception:
            if s.endswith("Z"):
                datetime.fromisoformat(s[:-1])
                return True
            return False
    except Exception:
        return False


def _extract_numeric_strings_from_site_yaml(text: str) -> List[str]:
    values = set()
    for m in re.finditer(r"\b\d+(?:\.\d+)?\b", text):
        values.add(m.group(0))
    return list(values)


def _get_heading_min_length_from_config(text: Optional[str]) -> int:
    if not text:
        return 6
    m = re.search(r"heading_min_length:\s*(\d+)", text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return 6
    return 6


def _find_allowed_domains_in_config(text: Optional[str]) -> List[str]:
    if not text:
        return []
    domains = []
    in_block = False
    for line in text.splitlines():
        if re.match(r"^\s*allowed_domains\s*:\s*$", line):
            in_block = True
            continue
        if in_block:
            if re.match(r"^\s*-\s+(.+)$", line):
                dom = re.sub(r"^\s*-\s+", "", line).strip()
                domains.append(dom)
                continue
            if re.match(r"^\S", line):
                break
            if re.match(r"^\s*[A-Za-z0-9_]+\s*:", line):
                break
    return [d for d in (dom.strip() for dom in domains) if d]


def _count_sources_ids_in_config(text: Optional[str]) -> int:
    if not text:
        return 0
    return len(re.findall(r"^\s*id\s*:\s*.+$", text, flags=re.MULTILINE))


def _config_contains_source_ids(text: Optional[str], ids: List[str]) -> bool:
    if not text:
        return False
    ok = True
    for sid in ids:
        pattern = r"^\s*id\s*:\s*" + re.escape(sid) + r"\s*$"
        if not re.search(pattern, text, flags=re.MULTILINE):
            ok = False
    return ok


def _extract_section(md_text: str, title: str, all_titles: List[str]) -> Optional[str]:
    lower = md_text.lower()
    title_lower = title.lower()
    start = lower.find(title_lower)
    if start == -1:
        m = re.search(r"^\s{0,3}#{1,6}\s+" + re.escape(title_lower) + r"\s*$", lower, flags=re.MULTILINE)
        if m:
            start = m.start()
        else:
            return None
    next_positions = []
    for other in all_titles:
        if other.lower() == title_lower:
            continue
        pos = lower.find(other.lower(), start + 1)
        if pos != -1:
            next_positions.append(pos)
    end = min(next_positions) if next_positions else len(md_text)
    return md_text[start:end].strip()


def _get_bmp_list(workspace: Path) -> Optional[List[Dict[str, str]]]:
    path = workspace / "input" / "bmp_candidates.csv"
    rows = _parse_csv_safe(path)
    if rows is None:
        return None
    result = []
    for r in rows:
        if "bmp_id" in r and "name" in r:
            result.append({"bmp_id": r["bmp_id"], "name": r["name"]})
    return result


def _compute_heading_words(headings_map: Dict[str, List[str]], min_len: int) -> set:
    words = set()
    for lst in headings_map.values():
        for h in lst:
            for w in re.findall(r"[A-Za-z]{%d,}" % max(min_len, 6), h):
                words.add(w.lower())
    return words


def _find_chunk_for_bmp(section_text: str, bmp_name: str, bmp_id: str) -> Optional[str]:
    idx_name = section_text.lower().find(bmp_name.lower())
    idx_id = section_text.lower().find(bmp_id.lower())
    idx = idx_name if (idx_name != -1 and (idx_id == -1 or idx_name < idx_id)) else idx_id
    if idx == -1:
        return None
    chunk = section_text[idx: idx + 1200]
    return chunk


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "resources_dir_present": 0.0,
        "config_sources_present_in_input": 0.0,
        "updated_config_copy_present": 0.0,
        "allowed_domains_cover_sources": 0.0,
        "csv_has_two_sources": 0.0,
        "sources_csv_structure_and_sha256": 0.0,
        "domains_compliance_gov_and_epa": 0.0,
        "headings_json_structure": 0.0,
        "headings_min_length_respected": 0.0,
        "report_has_all_sections": 0.0,
        "site_summary_includes_three_values": 0.0,
        "sources_overview_mentions_ids": 0.0,
        "method_section_present": 0.0,
        "bmp_assessments_per_bmp": 0.0,
        "bmp_assessments_cite_sources_and_site": 0.0,
        "bmp_assessments_include_heading_terms": 0.0,
        "recommendation_section_selects_bmp": 0.0,
    }

    resources_dir = workspace / "web_resources"
    out_sources_csv = workspace / "out" / "data" / "sources.csv"
    out_headings_json = workspace / "out" / "data" / "extracted_headings.json"
    out_review_md = workspace / "out" / "review" / "bmp_suitability.md"
    config_input = workspace / "input" / "config.yml"
    config_updated_copy = workspace / "out" / "config" / "updated_config.yml"
    project_site_yaml = workspace / "input" / "project_site.yaml"

    if resources_dir.exists() and resources_dir.is_dir():
        scores["resources_dir_present"] = 1.0

    config_input_text = _read_text_safe(config_input)
    config_updated_copy_text = _read_text_safe(config_updated_copy)

    heading_min_len = _get_heading_min_length_from_config(config_input_text)

    config_sources_id_count = _count_sources_ids_in_config(config_input_text) if config_input_text else 0
    if config_input_text and config_sources_id_count >= 2:
        scores["config_sources_present_in_input"] = 1.0

    if config_updated_copy_text and _count_sources_ids_in_config(config_updated_copy_text) >= 2:
        scores["updated_config_copy_present"] = 1.0

    csv_rows = _parse_csv_safe(out_sources_csv)
    csv_structure_ok = False
    sha_ok_all = False
    domains_cover_ok = False
    epa_ok = False
    gov_other_ok = False
    extension_match_ok = False
    if csv_rows is not None and len(csv_rows) > 0:
        required_cols = ["id", "title", "publisher", "domain", "url", "local_path", "file_type", "sha256", "access_date"]
        header_ok = True
        try:
            with out_sources_csv.open("r", encoding="utf-8") as f:
                header_line = f.readline()
                header_ok = all(col in header_line for col in required_cols)
        except Exception:
            header_ok = False
        csv_structure_ok = header_ok

        if len(csv_rows) == 2:
            scores["csv_has_two_sources"] = 1.0

        sha_all = True
        ext_all = True
        for r in csv_rows:
            if "access_date" in r and r["access_date"]:
                if not _iso_date_ok(r["access_date"]):
                    sha_all = False
            lp = r.get("local_path", "")
            fpath = (workspace / lp).resolve()
            try:
                parts = fpath.parts
            except Exception:
                parts = ()
            if not fpath.exists() or "web_resources" not in parts:
                sha_all = False
            else:
                sha = _sha256_file(fpath)
                if not sha or r.get("sha256", "").lower() != sha.lower():
                    sha_all = False
            ft = r.get("file_type", "").lower().strip()
            suffix = fpath.suffix.lower()
            if ft == "pdf" and suffix != ".pdf":
                ext_all = False
            if ft == "html" and suffix not in [".html", ".htm"]:
                ext_all = False
        sha_ok_all = sha_all
        extension_match_ok = ext_all

        domains = [r.get("domain", "").strip().lower() for r in csv_rows]
        epa_ok = any(d == "epa.gov" for d in domains)
        gov_other_ok = any(d.endswith(".gov") and d != "epa.gov" for d in domains)

        allowed = _find_allowed_domains_in_config(config_input_text)
        domains_cover_ok = all(d in allowed for d in domains)

    if csv_structure_ok and sha_ok_all and extension_match_ok:
        scores["sources_csv_structure_and_sha256"] = 1.0

    if domains_cover_ok:
        scores["allowed_domains_cover_sources"] = 1.0

    if epa_ok and gov_other_ok:
        scores["domains_compliance_gov_and_epa"] = 1.0

    headings_obj = _load_json_safe(out_headings_json)
    headings_map: Dict[str, List[str]] = {}
    if isinstance(headings_obj, list):
        structure_ok = True
        for item in headings_obj:
            if not isinstance(item, dict):
                structure_ok = False
                break
            if "id" not in item or "headings" not in item:
                structure_ok = False
                break
            if not isinstance(item["id"], str):
                structure_ok = False
                break
            if not isinstance(item["headings"], list):
                structure_ok = False
                break
            headings_map[item["id"]] = [str(h) for h in item["headings"]]
        if structure_ok:
            scores["headings_json_structure"] = 1.0

    headings_len_ok = False
    if csv_rows is not None and isinstance(headings_obj, list):
        all_ids = [r.get("id", "") for r in csv_rows if "id" in r]
        ids_present = all((sid in headings_map and isinstance(headings_map[sid], list) and len(headings_map[sid]) >= 1) for sid in all_ids)
        length_ok = True
        for sid in all_ids:
            hs = headings_map.get(sid, [])
            if not hs:
                length_ok = False
                break
            for h in hs:
                if len(h.strip()) < heading_min_len:
                    length_ok = False
                    break
            if not length_ok:
                break
        if ids_present and length_ok:
            headings_len_ok = True
    if headings_len_ok:
        scores["headings_min_length_respected"] = 1.0

    md_text = _read_text_safe(out_review_md) or ""
    section_titles = [
        "Site summary",
        "Sources overview",
        "Method",
        "BMP assessments",
        "Recommendation",
    ]
    sections_found = all((out_review_md.exists() and (_extract_section(md_text, t, section_titles) is not None)) for t in section_titles)
    if sections_found:
        scores["report_has_all_sections"] = 1.0

    site_text = _read_text_safe(project_site_yaml) or ""
    site_numbers = _extract_numeric_strings_from_site_yaml(site_text)
    site_section = _extract_section(md_text, "Site summary", section_titles) if md_text else None
    if site_section:
        found_nums = set()
        for n in site_numbers:
            if re.search(r"\b" + re.escape(n) + r"\b", site_section):
                found_nums.add(n)
        if len(found_nums) >= 3:
            scores["site_summary_includes_three_values"] = 1.0

    ids_from_csv: List[str] = []
    if csv_rows is not None:
        ids_from_csv = [r.get("id", "") for r in csv_rows if r.get("id")]
    else:
        ids_from_csv = re.findall(r"^\s*id\s*:\s*(\S+)\s*$", config_input_text or "", flags=re.MULTILINE)
    sources_section = _extract_section(md_text, "Sources overview", section_titles) if md_text else None
    if sources_section and len(ids_from_csv) >= 2:
        if all((sid in sources_section) for sid in ids_from_csv[:2]):
            scores["sources_overview_mentions_ids"] = 1.0

    method_section = _extract_section(md_text, "Method", section_titles) if md_text else None
    if method_section and len(method_section.strip()) >= 50:
        scores["method_section_present"] = 1.0

    bmp_list = _get_bmp_list(workspace) or []
    assessments_section = _extract_section(md_text, "BMP assessments", section_titles) if md_text else None
    heading_words = _compute_heading_words(headings_map, heading_min_len) if headings_map else set()

    if assessments_section and bmp_list:
        per_bmp_presence = True
        per_bmp_citations = True
        per_bmp_heading_terms = True
        for bmp in bmp_list:
            bmp_id = bmp["bmp_id"]
            bmp_name = bmp["name"]
            chunk = _find_chunk_for_bmp(assessments_section, bmp_name, bmp_id)
            if not chunk:
                per_bmp_presence = False
                per_bmp_citations = False
                per_bmp_heading_terms = False
                break
            if not re.search(r"\b(Suitable|Conditionally suitable|Unsuitable)\b", chunk, flags=re.IGNORECASE):
                per_bmp_presence = False
            sentence_marks = re.findall(r"[\.!\?]", chunk)
            if not (2 <= len(sentence_marks) <= 6):
                per_bmp_presence = False
            cite_ok = False
            if ids_from_csv:
                for sid in ids_from_csv:
                    if sid and sid in chunk:
                        cite_ok = True
                        break
            site_num_ok = any(re.search(r"\b" + re.escape(n) + r"\b", chunk) for n in site_numbers)
            if not (cite_ok and site_num_ok):
                per_bmp_citations = False
            heading_term_ok = False
            if heading_words:
                words_in_chunk = {w.lower() for w in re.findall(r"[A-Za-z]{2,}", chunk)}
                if words_in_chunk & heading_words:
                    heading_term_ok = True
            else:
                heading_term_ok = False
            if not heading_term_ok:
                per_bmp_heading_terms = False

        if per_bmp_presence:
            scores["bmp_assessments_per_bmp"] = 1.0
        if per_bmp_citations:
            scores["bmp_assessments_cite_sources_and_site"] = 1.0
        if per_bmp_heading_terms:
            scores["bmp_assessments_include_heading_terms"] = 1.0

    recommendation_section = _extract_section(md_text, "Recommendation", section_titles) if md_text else None
    if recommendation_section and bmp_list:
        mentions_any = any((bmp["name"] in recommendation_section or bmp["bmp_id"] in recommendation_section) for bmp in bmp_list)
        if mentions_any and len(recommendation_section.strip()) >= 50:
            scores["recommendation_section_selects_bmp"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()