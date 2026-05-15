import json
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return None, f"read_error:{e}"
    try:
        return json.loads(text), None
    except Exception as e:
        return None, f"json_error:{e}"


def _load_jsonl_safe(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        return None, f"read_error:{e}"
    data = []
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                return None, f"jsonl_line_not_object:{i}"
            data.append(obj)
        except Exception as e:
            return None, f"jsonl_parse_error_line_{i}:{e}"
    return data, None


def _count_words(s: str) -> int:
    return len(re.findall(r"\b\w+\b", s))


def _extract_disclaimer(guidelines_text: str) -> Optional[str]:
    for line in guidelines_text.splitlines():
        m = re.search(r"Crisis Disclaimer \(exact text to include\):\s*(.+)$", line.strip())
        if m:
            return m.group(1).strip()
    return None


def _parse_carousel_slides(md_text: str) -> Tuple[bool, Dict[int, str]]:
    pattern = re.compile(r"(?im)^(?:\s*#{1,6}\s*)?slide\s*([1-5])\s*[:\-]\s*", re.IGNORECASE | re.MULTILINE)
    matches = list(pattern.finditer(md_text))
    slides: Dict[int, str] = {}
    if not matches:
        return False, slides
    for idx, m in enumerate(matches):
        num_str = m.group(1)
        try:
            slide_num = int(num_str)
        except ValueError:
            continue
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(md_text)
        content = md_text[start:end].strip()
        slides[slide_num] = content
    expected_nums = set(range(1, 6))
    if set(slides.keys()) != expected_nums:
        return False, slides
    return True, slides


def _compute_counts_from_journal(entries: List[Dict[str, Any]]) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, List[str]]]:
    stressor_counts: Dict[str, int] = {}
    coping_counts: Dict[str, int] = {}
    notes_by_stressor: Dict[str, List[str]] = {}
    for e in entries:
        stressors = e.get("stressors", []) or []
        coping = e.get("coping_used", []) or []
        notes = e.get("notes", "") or ""
        for s in stressors:
            if isinstance(s, str):
                stressor_counts[s] = stressor_counts.get(s, 0) + 1
                notes_by_stressor.setdefault(s, []).append(notes)
        for c in coping:
            if isinstance(c, str):
                coping_counts[c] = coping_counts.get(c, 0) + 1
    return stressor_counts, coping_counts, notes_by_stressor


def _top_n(items: Dict[str, int], n: int) -> List[Tuple[str, int]]:
    sorted_items = sorted(items.items(), key=lambda kv: (-kv[1], kv[0]))
    return sorted_items[:n]


def _iso_date_valid(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _contains_banned_terms(text: str) -> bool:
    banned = ["disorder", "diagnosis", "treatment plan"]
    t = text.lower()
    return any(b in t for b in banned)


def _has_url(text: str) -> bool:
    return bool(re.search(r"(https?://|www\.)", text, re.IGNORECASE))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    input_dir = workspace / "input"
    output_dir = workspace / "output"

    scores: Dict[str, float] = {
        "summary_parsed_and_schema": 0.0,
        "summary_total_entries_correct": 0.0,
        "summary_top_stressors_correct": 0.0,
        "summary_top_stressors_quotes_valid": 0.0,
        "summary_coping_activities_correct": 0.0,
        "resources_parsed_and_schema": 0.0,
        "resources_ids_valid": 0.0,
        "resources_fields_values_valid": 0.0,
        "resources_search_queries_present": 0.0,
        "carousel_title_and_structure": 0.0,
        "carousel_slide1_word_limit": 0.0,
        "carousel_slide2_stressors_and_word_limit": 0.0,
        "carousel_slide3_copings_and_word_limit": 0.0,
        "carousel_slide4_resources_and_tags_and_word_limit": 0.0,
        "carousel_slide5_disclaimer_and_word_limit": 0.0,
        "carousel_no_banned_terms": 0.0,
        "carousel_no_urls": 0.0,
        "cross_stressor_coping_consistency": 0.0,
        "cross_resource_references": 0.0,
    }

    journal_path = input_dir / "journal_entries.jsonl"
    guidelines_path = input_dir / "community_guidelines.md"

    journal_entries, _ = _load_jsonl_safe(journal_path) if journal_path.exists() else (None, "missing")
    guidelines_text = _read_text_safe(guidelines_path) if guidelines_path.exists() else None
    disclaimer_text = _extract_disclaimer(guidelines_text) if guidelines_text else None

    expected_total_entries = None
    expected_top3_stressors: List[Tuple[str, int]] = []
    expected_top2_copings: List[Tuple[str, int]] = []
    notes_by_stressor: Dict[str, List[str]] = {}
    all_stressor_names: set = set()
    all_coping_names: set = set()
    if journal_entries is not None:
        expected_total_entries = len(journal_entries)
        stressor_counts, coping_counts, notes_by_stressor = _compute_counts_from_journal(journal_entries)
        all_stressor_names = set(stressor_counts.keys())
        all_coping_names = set(coping_counts.keys())
        expected_top3_stressors = _top_n(stressor_counts, 3)
        expected_top2_copings = _top_n(coping_counts, 2)

    summary_path = output_dir / "summary.json"
    summary_obj, _ = _load_json_safe(summary_path) if summary_path.exists() else (None, "missing")

    if isinstance(summary_obj, dict):
        has_fields = (
            "total_entries" in summary_obj
            and "top_stressors" in summary_obj
            and isinstance(summary_obj.get("top_stressors"), list)
            and "coping_activities" in summary_obj
            and isinstance(summary_obj.get("coping_activities"), list)
        )
        if has_fields:
            ts = summary_obj.get("top_stressors", [])
            ca = summary_obj.get("coping_activities", [])
            if isinstance(ts, list) and isinstance(ca, list) and len(ts) == 3 and len(ca) == 2:
                ts_schema_ok = True
                for item in ts:
                    if not (isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("count"), int) and isinstance(item.get("sample_quote"), str)):
                        ts_schema_ok = False
                        break
                ca_schema_ok = True
                for item in ca:
                    if not (isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("count"), int)):
                        ca_schema_ok = False
                        break
                if ts_schema_ok and ca_schema_ok:
                    scores["summary_parsed_and_schema"] = 1.0

        if expected_total_entries is not None and isinstance(summary_obj.get("total_entries"), int):
            if summary_obj.get("total_entries") == expected_total_entries:
                scores["summary_total_entries_correct"] = 1.0

        if expected_top3_stressors and isinstance(summary_obj.get("top_stressors"), list):
            provided = summary_obj["top_stressors"]
            provided_map = {it["name"]: it["count"] for it in provided if isinstance(it, dict) and "name" in it and "count" in it}
            expected_map = dict(expected_top3_stressors)
            names_match = set(provided_map.keys()) == set(expected_map.keys())
            counts_match = all(provided_map.get(n) == c for n, c in expected_map.items())
            lowercase_names = all(n == n.lower() for n in provided_map.keys())
            names_exist_in_input = all(n in all_stressor_names for n in provided_map.keys())
            if names_match and counts_match and lowercase_names and names_exist_in_input:
                scores["summary_top_stressors_correct"] = 1.0

            quotes_ok = True
            if notes_by_stressor:
                for it in provided:
                    n = it.get("name")
                    q = it.get("sample_quote", "")
                    if not isinstance(q, str) or not q.strip():
                        quotes_ok = False
                        break
                    if _count_words(q) > 20:
                        quotes_ok = False
                        break
                    notes_list = notes_by_stressor.get(n, [])
                    found = False
                    q_norm = q.strip()
                    for note in notes_list:
                        if isinstance(note, str) and q_norm.lower() in note.lower():
                            found = True
                            break
                    if not found:
                        quotes_ok = False
                        break
            else:
                quotes_ok = False
            if quotes_ok:
                scores["summary_top_stressors_quotes_valid"] = 1.0

        if expected_top2_copings and isinstance(summary_obj.get("coping_activities"), list):
            provided = summary_obj["coping_activities"]
            provided_map = {it["name"]: it["count"] for it in provided if isinstance(it, dict) and "name" in it and "count" in it}
            expected_map = dict(expected_top2_copings)
            names_match = set(provided_map.keys()) == set(expected_map.keys())
            counts_match = all(provided_map.get(n) == c for n, c in expected_map.items())
            lowercase_names = all(n == n.lower() for n in provided_map.keys())
            names_exist_in_input = all(n in all_coping_names for n in provided_map.keys())
            if names_match and counts_match and lowercase_names and names_exist_in_input:
                scores["summary_coping_activities_correct"] = 1.0

    resources_path = output_dir / "resources.json"
    resources_obj, _ = _load_json_safe(resources_path) if resources_path.exists() else (None, "missing")
    resources_list: List[Dict[str, Any]] = []
    resources_by_id: Dict[str, Dict[str, Any]] = {}
    if isinstance(resources_obj, dict):
        res_list = resources_obj.get("resources")
        search_queries = resources_obj.get("search_queries")
        if isinstance(res_list, list) and isinstance(search_queries, list):
            scores["resources_parsed_and_schema"] = 1.0
            resources_list = res_list
            if len(search_queries) >= 1 and all(isinstance(q, str) and q.strip() for q in search_queries):
                scores["resources_search_queries_present"] = 1.0

            ids = [r.get("id") for r in resources_list if isinstance(r, dict)]
            if len(resources_list) == 3 and set(ids) == {"R1", "R2", "R3"}:
                scores["resources_ids_valid"] = 1.0
                resources_by_id = {r["id"]: r for r in resources_list if isinstance(r, dict) and "id" in r}

            fields_ok = True
            allowed_support_types = {"hotline", "peer support", "program", "therapy locator"}
            allowed_source_cat = {"government", "nonprofit"}
            if len(resources_list) == 3:
                for r in resources_list:
                    if not isinstance(r, dict):
                        fields_ok = False
                        break
                    for key in ["id", "organization", "resource_name", "audience", "support_type", "contact", "description", "source_org_category", "last_checked"]:
                        if key not in r:
                            fields_ok = False
                            break
                    if not fields_ok:
                        break
                    if not (isinstance(r.get("organization"), str) and r["organization"].strip()):
                        fields_ok = False
                        break
                    if not (isinstance(r.get("resource_name"), str) and r["resource_name"].strip()):
                        fields_ok = False
                        break
                    if r.get("audience") != "first responders/EMS":
                        fields_ok = False
                        break
                    if r.get("support_type") not in allowed_support_types:
                        fields_ok = False
                        break
                    if not (isinstance(r.get("contact"), str) and r["contact"].strip()):
                        fields_ok = False
                        break
                    if not (isinstance(r.get("description"), str) and r["description"].strip() and len(r["description"]) <= 300):
                        fields_ok = False
                        break
                    if r.get("source_org_category") not in allowed_source_cat:
                        fields_ok = False
                        break
                    lc = r.get("last_checked")
                    if not (isinstance(lc, str) and _iso_date_valid(lc)):
                        fields_ok = False
                        break
            else:
                fields_ok = False
            if fields_ok:
                scores["resources_fields_values_valid"] = 1.0

    carousel_path = output_dir / "carousel.md"
    carousel_text = _read_text_safe(carousel_path) if carousel_path.exists() else None

    title_ok = False
    slides_ok = False
    slides: Dict[int, str] = {}
    if isinstance(carousel_text, str):
        title_ok = "EMT Stress Support: You're Not Alone" in carousel_text
        slides_ok, slides = _parse_carousel_slides(carousel_text)
        if title_ok and slides_ok:
            scores["carousel_title_and_structure"] = 1.0

        if slides_ok:
            s1 = slides.get(1, "")
            if _count_words(s1) <= 60 and _count_words(s1) > 0:
                scores["carousel_slide1_word_limit"] = 1.0

            s2 = slides.get(2, "")
            s2_ok = False
            if summary_obj and isinstance(summary_obj.get("top_stressors"), list) and len(summary_obj["top_stressors"]) == 3:
                names = [it.get("name") for it in summary_obj["top_stressors"]]
                if all(isinstance(n, str) for n in names):
                    contains_all = all(n in s2 for n in names)
                    if contains_all and _count_words(s2) <= 60 and _count_words(s2) > 0:
                        s2_ok = True
            if s2_ok:
                scores["carousel_slide2_stressors_and_word_limit"] = 1.0

            s3 = slides.get(3, "")
            s3_ok = False
            if summary_obj and isinstance(summary_obj.get("coping_activities"), list) and len(summary_obj["coping_activities"]) == 2:
                names = [it.get("name") for it in summary_obj["coping_activities"]]
                if all(isinstance(n, str) for n in names):
                    contains_all = all(n in s3 for n in names)
                    if contains_all and _count_words(s3) <= 60 and _count_words(s3) > 0:
                        s3_ok = True
            if s3_ok:
                scores["carousel_slide3_copings_and_word_limit"] = 1.0

            s4 = slides.get(4, "")
            slide4_ok = False
            if resources_by_id and set(resources_by_id.keys()) == {"R1", "R2", "R3"}:
                tags_present = all(f"[{rid}]" in s4 for rid in ["R1", "R2", "R3"])
                resources_present = True
                for rid, r in resources_by_id.items():
                    rn = r.get("resource_name", "")
                    ct = r.get("contact", "")
                    if not (isinstance(rn, str) and rn and rn in s4):
                        resources_present = False
                        break
                    if not (isinstance(ct, str) and ct and ct in s4):
                        resources_present = False
                        break
                if tags_present and resources_present and _count_words(s4) <= 60 and _count_words(s4) > 0:
                    slide4_ok = True
            if slide4_ok:
                scores["carousel_slide4_resources_and_tags_and_word_limit"] = 1.0

            s5 = slides.get(5, "")
            slide5_ok = False
            if isinstance(disclaimer_text, str) and disclaimer_text:
                if disclaimer_text in s5:
                    preface = s5.split(disclaimer_text, 1)[0].strip()
                    if _count_words(preface) <= 60:
                        slide5_ok = True
            if slide5_ok:
                scores["carousel_slide5_disclaimer_and_word_limit"] = 1.0

            if not _contains_banned_terms(carousel_text):
                scores["carousel_no_banned_terms"] = 1.0

            if not _has_url(carousel_text):
                scores["carousel_no_urls"] = 1.0

    cross_names_ok = False
    if slides and isinstance(summary_obj, dict):
        s2 = slides.get(2, "")
        s3 = slides.get(3, "")
        ts = summary_obj.get("top_stressors")
        ca = summary_obj.get("coping_activities")
        if isinstance(ts, list) and isinstance(ca, list) and len(ts) == 3 and len(ca) == 2:
            stressor_names = [it.get("name") for it in ts]
            coping_names = [it.get("name") for it in ca]
            if all(isinstance(n, str) for n in stressor_names + coping_names):
                if all(n in s2 for n in stressor_names) and all(n in s3 for n in coping_names):
                    cross_names_ok = True
    if cross_names_ok:
        scores["cross_stressor_coping_consistency"] = 1.0

    cross_resources_ok = False
    if slides and resources_by_id:
        s4 = slides.get(4, "")
        if s4 is not None:
            tags = re.findall(r"\[(R[1-3])\]", s4)
            tags_set = set(tags)
            if {"R1", "R2", "R3"}.issubset(tags_set) and set(resources_by_id.keys()) == {"R1", "R2", "R3"}:
                cross_resources_ok = True
    if cross_resources_ok:
        scores["cross_resource_references"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()