import json
import sys
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_csv_safe(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def load_jsonl_annotations(path: Path) -> Optional[Dict[str, Dict[str, int]]]:
    try:
        annotations: Dict[str, Dict[str, int]] = {}
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                doc_id = obj.get("doc_id")
                label_counts = obj.get("label_counts")
                if isinstance(doc_id, str) and isinstance(label_counts, dict):
                    clean_counts: Dict[str, int] = {}
                    for k, v in label_counts.items():
                        try:
                            clean_counts[str(k)] = int(v)
                        except Exception:
                            return None
                    annotations[doc_id] = clean_counts
                else:
                    return None
        return annotations
    except Exception:
        return None


def compute_expected_stats(meta_rows: List[Dict[str, Any]], annos: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
    meta_by_id: Dict[str, Dict[str, Any]] = {}
    for row in meta_rows:
        doc_id = row.get("doc_id")
        if not isinstance(doc_id, str):
            continue
        split = row.get("split")
        num_pages_raw = row.get("num_pages")
        dpi_raw = row.get("dpi")
        has_handwriting_raw = row.get("has_handwriting")
        lang = row.get("lang")
        try:
            num_pages = int(num_pages_raw)
        except Exception:
            num_pages = None
        try:
            dpi = int(dpi_raw)
        except Exception:
            dpi = None
        has_handwriting = None
        if isinstance(has_handwriting_raw, str):
            if has_handwriting_raw.strip().lower() in ("true", "false"):
                has_handwriting = has_handwriting_raw.strip().lower() == "true"
        elif isinstance(has_handwriting_raw, bool):
            has_handwriting = has_handwriting_raw
        meta_by_id[doc_id] = {
            "split": split,
            "num_pages": num_pages,
            "dpi": dpi,
            "has_handwriting": has_handwriting,
            "lang": lang,
        }

    meta_ids = set(meta_by_id.keys())
    anno_ids = set(annos.keys())

    only_in_metadata = sorted(list(meta_ids - anno_ids))
    only_in_annotations = sorted(list(anno_ids - meta_ids))
    intersect_ids = sorted(list(meta_ids & anno_ids))

    total_docs = len(intersect_ids)
    total_pages = 0
    split_doc_counts: Dict[str, int] = {}
    split_page_counts: Dict[str, int] = {}
    label_totals: Dict[str, int] = {}
    docs_with_handwriting = 0
    languages: Dict[str, int] = {}
    dpi_counts: Dict[str, int] = {}

    for did in intersect_ids:
        m = meta_by_id.get(did, {})
        split = m.get("split")
        num_pages = m.get("num_pages") or 0
        dpi = m.get("dpi")
        has_hw = m.get("has_handwriting")
        lang = m.get("lang")

        total_pages += num_pages

        if isinstance(split, str):
            split_doc_counts[split] = split_doc_counts.get(split, 0) + 1
            split_page_counts[split] = split_page_counts.get(split, 0) + int(num_pages)

        if isinstance(dpi, int):
            dpi_counts[str(dpi)] = dpi_counts.get(str(dpi), 0) + 1

        if isinstance(has_hw, bool) and has_hw:
            docs_with_handwriting += 1

        if isinstance(lang, str):
            languages[lang] = languages.get(lang, 0) + 1

        lc = annos.get(did, {})
        for k, v in lc.items():
            label_totals[k] = label_totals.get(k, 0) + int(v)

    avg_pages_per_doc = float(total_pages) / total_docs if total_docs > 0 else 0.0
    handwriting_percentage_ratio = float(docs_with_handwriting) / total_docs if total_docs > 0 else 0.0
    handwriting_percentage_percent = handwriting_percentage_ratio * 100.0

    expected = {
        "total_docs": total_docs,
        "total_pages": total_pages,
        "avg_pages_per_doc": avg_pages_per_doc,
        "split_doc_counts": split_doc_counts,
        "split_page_counts": split_page_counts,
        "label_totals": label_totals,
        "handwriting": {
            "docs_with_handwriting": docs_with_handwriting,
            "percentage_ratio": handwriting_percentage_ratio,
            "percentage_percent": handwriting_percentage_percent,
        },
        "languages": languages,
        "dpi_counts": dpi_counts,
        "doc_id_mismatches": {
            "only_in_metadata": only_in_metadata,
            "only_in_annotations": only_in_annotations,
        },
    }
    return expected


def approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def dict_ints_equal(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    try:
        if set(a.keys()) != set(b.keys()):
            return False
        for k in a:
            if int(a[k]) != int(b[k]):
                return False
        return True
    except Exception:
        return False


def value_token_present(text: str, number: float, allow_percent: bool = False) -> bool:
    patterns = []
    try:
        fnum = float(number)
        if fnum.is_integer():
            iv = str(int(round(fnum)))
            patterns.append(rf"\b{re.escape(iv)}\b")
        else:
            sval = f"{fnum}"
            if "e" in sval or "E" in sval:
                sval = f"{fnum:f}".rstrip("0").rstrip(".")
            sval = sval.rstrip("0").rstrip(".") if "." in sval else sval
            patterns.append(rf"\b{re.escape(sval)}\b")
    except Exception:
        return False

    for pat in patterns:
        if re.search(pat, text):
            return True
        if allow_percent:
            if re.search(pat + r"\s*%", text):
                return True
    return False


def find_section(text: str, header: str) -> Optional[str]:
    pattern = re.compile(rf"(?mi)^\s*#+\s*{re.escape(header)}\s*$")
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    start = matches[0].end()
    next_heading = re.search(r"(?m)^\s*#+\s+.+$", text[start:])
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end]


def count_bullets(text: str) -> int:
    lines = text.splitlines()
    count = 0
    for ln in lines:
        if re.match(r"^\s*[-*]\s+", ln) or re.match(r"^\s*\d+\.\s+", ln):
            count += 1
    return count


def phase_subsections(text: str) -> List[str]:
    subsections = []
    for m in re.finditer(r"(?mi)^\s*#+\s*.*phase.*$", text):
        start = m.end()
        next_m = re.search(r"(?m)^\s*#+\s+.+$", text[start:])
        end = start + next_m.start() if next_m else len(text)
        subsections.append(text[start:end])
    return subsections


def parse_json_file(path: Path) -> Tuple[bool, Optional[dict]]:
    data = load_json_safe(path)
    if isinstance(data, dict):
        return True, data
    return False, None


def grade_dataset_stats(workspace: Path) -> Dict[str, float]:
    scores: Dict[str, float] = {
        "summary_file_parse": 0.0,
        "summary_total_docs": 0.0,
        "summary_total_pages": 0.0,
        "summary_avg_pages_per_doc": 0.0,
        "summary_split_doc_counts": 0.0,
        "summary_split_page_counts": 0.0,
        "summary_label_totals": 0.0,
        "summary_handwriting": 0.0,
        "summary_languages": 0.0,
        "summary_dpi_counts": 0.0,
        "summary_doc_id_mismatches": 0.0,
    }
    meta_path = workspace / "input" / "metadata.csv"
    anno_path = workspace / "input" / "annotations.jsonl"
    stats_path = workspace / "outputs" / "summary" / "dataset_stats.json"

    meta_rows = parse_csv_safe(meta_path) or []
    annos = load_jsonl_annotations(anno_path) or {}

    expected = compute_expected_stats(meta_rows, annos)

    ok, stats = parse_json_file(stats_path)
    if not ok or stats is None:
        return scores

    scores["summary_file_parse"] = 1.0

    td = stats.get("total_docs")
    if isinstance(td, int) and td == expected["total_docs"]:
        scores["summary_total_docs"] = 1.0

    tp = stats.get("total_pages")
    if isinstance(tp, int) and tp == expected["total_pages"]:
        scores["summary_total_pages"] = 1.0

    apd = stats.get("avg_pages_per_doc")
    if isinstance(apd, (int, float)) and approx_equal(float(apd), expected["avg_pages_per_doc"], tol=1e-6):
        scores["summary_avg_pages_per_doc"] = 1.0

    sdc = stats.get("split_doc_counts")
    if isinstance(sdc, dict) and dict_ints_equal(sdc, expected["split_doc_counts"]):
        scores["summary_split_doc_counts"] = 1.0

    spc = stats.get("split_page_counts")
    if isinstance(spc, dict) and dict_ints_equal(spc, expected["split_page_counts"]):
        scores["summary_split_page_counts"] = 1.0

    lt = stats.get("label_totals")
    if isinstance(lt, dict) and dict_ints_equal(lt, expected["label_totals"]):
        scores["summary_label_totals"] = 1.0

    hw = stats.get("handwriting")
    if isinstance(hw, dict):
        docs_hw = hw.get("docs_with_handwriting")
        percent_val = hw.get("percentage")
        docs_ok = isinstance(docs_hw, int) and docs_hw == expected["handwriting"]["docs_with_handwriting"]
        percent_ok = False
        if isinstance(percent_val, (int, float)):
            if approx_equal(float(percent_val), expected["handwriting"]["percentage_ratio"], tol=1e-6) or \
               approx_equal(float(percent_val), expected["handwriting"]["percentage_percent"], tol=1e-6):
                percent_ok = True
        if docs_ok and percent_ok:
            scores["summary_handwriting"] = 1.0

    langs = stats.get("languages")
    if isinstance(langs, dict) and dict_ints_equal(langs, expected["languages"]):
        scores["summary_languages"] = 1.0

    dpi_counts = stats.get("dpi_counts")
    if isinstance(dpi_counts, dict):
        norm = {str(k): v for k, v in dpi_counts.items()}
        if dict_ints_equal(norm, expected["dpi_counts"]):
            scores["summary_dpi_counts"] = 1.0

    mm = stats.get("doc_id_mismatches")
    if isinstance(mm, dict):
        only_meta = mm.get("only_in_metadata")
        only_anno = mm.get("only_in_annotations")
        try:
            if isinstance(only_meta, list) and isinstance(only_anno, list):
                if sorted(only_meta) == expected["doc_id_mismatches"]["only_in_metadata"] and \
                   sorted(only_anno) == expected["doc_id_mismatches"]["only_in_annotations"]:
                    scores["summary_doc_id_mismatches"] = 1.0
        except Exception:
            pass

    return scores


def plan_checks(workspace: Path) -> Dict[str, float]:
    scores: Dict[str, float] = {
        "plan_sections_present": 0.0,
        "plan_data_summary_numbers_match_stats_json": 0.0,
        "plan_phased_plan_structure": 0.0,
        "plan_risks_mitigations": 0.0,
        "plan_objectives_cover_constraints": 0.0,
    }
    plan_path = workspace / "outputs" / "plan" / "experiment_plan.md"
    stats_path = workspace / "outputs" / "summary" / "dataset_stats.json"

    plan_text = read_text_safe(plan_path)
    if not plan_text:
        return scores

    sections = {
        "Objectives": find_section(plan_text, "Objectives"),
        "Data Summary": find_section(plan_text, "Data Summary"),
        "Phased Plan": find_section(plan_text, "Phased Plan"),
        "Risks & Mitigations": find_section(plan_text, "Risks & Mitigations"),
    }
    if all(sections.values()):
        scores["plan_sections_present"] = 1.0

    stats = load_json_safe(stats_path)
    if isinstance(stats, dict) and sections.get("Data Summary"):
        data_sec = sections["Data Summary"]
        matched = True

        td = stats.get("total_docs")
        if not (isinstance(td, int) and value_token_present(data_sec, td, allow_percent=False)):
            matched = False

        tp = stats.get("total_pages")
        if not (isinstance(tp, int) and value_token_present(data_sec, tp, allow_percent=False)):
            matched = False

        hw = stats.get("handwriting")
        if isinstance(hw, dict):
            dwh = hw.get("docs_with_handwriting")
            perc = hw.get("percentage")
            dwh_ok = isinstance(dwh, int) and value_token_present(data_sec, dwh, allow_percent=False)
            perc_ok = isinstance(perc, (int, float)) and value_token_present(data_sec, float(perc), allow_percent=True)
            if not (dwh_ok and perc_ok):
                matched = False
        else:
            matched = False

        lt = stats.get("label_totals")
        if isinstance(lt, dict):
            table_ct = lt.get("table")
            if not (isinstance(table_ct, int) and value_token_present(data_sec, table_ct, allow_percent=False)):
                matched = False
        else:
            matched = False

        langs = stats.get("languages")
        if isinstance(langs, dict):
            for code, cnt in langs.items():
                code_pat = re.compile(re.escape(str(code)), re.IGNORECASE)
                cnt_pat = re.compile(rf"\b{re.escape(str(int(cnt)))}\b")
                found_pair = False
                for m in code_pat.finditer(data_sec):
                    start = m.start()
                    window = data_sec[max(0, start - 30): start + 30]
                    if cnt_pat.search(window):
                        found_pair = True
                        break
                if not found_pair:
                    for m in cnt_pat.finditer(data_sec):
                        start = m.start()
                        window = data_sec[max(0, start - 30): start + 30]
                        if code_pat.search(window):
                            found_pair = True
                            break
                if not found_pair:
                    matched = False
                    break
        else:
            matched = False

        if matched:
            scores["plan_data_summary_numbers_match_stats_json"] = 1.0

    if sections.get("Phased Plan"):
        pp = sections["Phased Plan"]
        phases = phase_subsections(pp)
        if len(phases) >= 3:
            per_phase_ok = 0
            for ph in phases:
                tasks = count_bullets(ph)
                has_deliverable = re.search(r"(?i)\bdeliverable\b", ph) is not None
                if tasks >= 2 and has_deliverable:
                    per_phase_ok += 1
            if per_phase_ok >= 3:
                scores["plan_phased_plan_structure"] = 1.0

    if sections.get("Risks & Mitigations"):
        rm = sections["Risks & Mitigations"]
        bullets = count_bullets(rm)
        mitigations = len(re.findall(r"(?i)\bmitigation\b", rm))
        if bullets >= 3 and mitigations >= 3:
            scores["plan_risks_mitigations"] = 1.0

    if sections.get("Objectives"):
        obj = sections["Objectives"]
        hit = 0
        if re.search(r"(?i)\bhandwriting\b", obj):
            hit += 1
        if re.search(r"(?i)\btable\b", obj):
            hit += 1
        if re.search(r"(?i)\b2\s*weeks?\b", obj):
            hit += 1
        if re.search(r"(?i)\bGPU\b", obj) or re.search(r"(?i)\b12\s*GB\b", obj):
            hit += 1
        if re.search(r"(?i)\blanguage|multilingual\b", obj):
            hit += 1
        if re.search(r"(?i)no\s+new\s+manual\s+annotations", obj):
            hit += 1
        if hit >= 2:
            scores["plan_objectives_cover_constraints"] = 1.0

    return scores


def email_checks(workspace: Path) -> Dict[str, float]:
    scores: Dict[str, float] = {
        "email_exists_and_length": 0.0,
        "email_references_files_and_next_steps": 0.0,
        "email_includes_numbers_from_stats": 0.0,
        "email_questions_count": 0.0,
        "email_salutation_prof_lee": 0.0,
    }
    email_path = workspace / "outputs" / "communication" / "advisor_email.txt"
    stats_path = workspace / "outputs" / "summary" / "dataset_stats.json"

    email_text = read_text_safe(email_path)
    if not email_text:
        return scores

    words = re.findall(r"\b\w+\b", email_text)
    if len(words) <= 180:
        scores["email_exists_and_length"] = 1.0

    refs_ok = False
    if ("outputs/summary/dataset_stats.json" in email_text and
            "outputs/plan/experiment_plan.md" in email_text):
        next_steps = re.search(r"(?i)next steps", email_text) is not None
        phase_ref = re.search(r"(?i)\bphased plan\b", email_text) is not None or re.search(r"(?i)\bphase\b", email_text) is not None
        if next_steps and phase_ref:
            refs_ok = True
    if refs_ok:
        scores["email_references_files_and_next_steps"] = 1.0

    stats = load_json_safe(stats_path)
    if isinstance(stats, dict):
        used_flags = {
            "total_docs": False,
            "total_pages": False,
            "docs_with_handwriting": False,
            "percentage": False,
            "label_tables": False,
            "language_counts": False,
        }

        td = stats.get("total_docs")
        if isinstance(td, int) and value_token_present(email_text, td, allow_percent=False):
            used_flags["total_docs"] = True

        tp = stats.get("total_pages")
        if isinstance(tp, int) and value_token_present(email_text, tp, allow_percent=False):
            used_flags["total_pages"] = True

        hw = stats.get("handwriting")
        if isinstance(hw, dict):
            dwh = hw.get("docs_with_handwriting")
            if isinstance(dwh, int):
                for m in re.finditer(rf"\b{re.escape(str(dwh))}\b", email_text):
                    start = m.start()
                    window = email_text[max(0, start - 30): start + 30]
                    if re.search(r"(?i)handwriting", window):
                        used_flags["docs_with_handwriting"] = True
                        break
            perc = hw.get("percentage")
            if isinstance(perc, (int, float)) and value_token_present(email_text, float(perc), allow_percent=True):
                used_flags["percentage"] = True

        lt = stats.get("label_totals")
        if isinstance(lt, dict):
            tv = lt.get("table")
            if isinstance(tv, int):
                for m in re.finditer(rf"\b{re.escape(str(tv))}\b", email_text):
                    start = m.start()
                    window = email_text[max(0, start - 30): start + 30]
                    if re.search(r"(?i)table", window):
                        used_flags["label_tables"] = True
                        break

        langs = stats.get("languages")
        if isinstance(langs, dict) and len(langs) > 0:
            lang_pair_found = False
            for code, cnt in langs.items():
                code_pat = re.compile(re.escape(str(code)), re.IGNORECASE)
                cnt_pat = re.compile(rf"\b{re.escape(str(int(cnt)))}\b")
                found_pair = False
                for m in code_pat.finditer(email_text):
                    start = m.start()
                    window = email_text[max(0, start - 30): start + 30]
                    if cnt_pat.search(window):
                        found_pair = True
                        break
                if not found_pair:
                    for m in cnt_pat.finditer(email_text):
                        start = m.start()
                        window = email_text[max(0, start - 30): start + 30]
                        if code_pat.search(window):
                            found_pair = True
                            break
                if found_pair:
                    lang_pair_found = True
                    break
            if lang_pair_found:
                used_flags["language_counts"] = True

        count_match = sum(1 for v in used_flags.values() if v)
        if count_match >= 3:
            scores["email_includes_numbers_from_stats"] = 1.0

    q_count = email_text.count("?")
    if 2 <= q_count <= 3:
        scores["email_questions_count"] = 1.0

    if re.search(r"(?i)prof\.?\s+lee", email_text) and (re.search(r"(?i)\bhi\b", email_text) or re.search(r"(?i)\bdear\b", email_text)):
        scores["email_salutation_prof_lee"] = 1.0

    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {}

    scores.update(grade_dataset_stats(workspace))
    scores.update(plan_checks(workspace))
    scores.update(email_checks(workspace))

    for k, v in list(scores.items()):
        try:
            fv = float(v)
            if fv < 0.0 or fv > 1.0:
                scores[k] = 0.0
            else:
                scores[k] = fv
        except Exception:
            scores[k] = 0.0

    return scores


def main() -> None:
    workspace_arg = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_arg)
    # Enforce a stable key order expected by the harness
    grade_keys = [
        "summary_file_parse",
        "summary_total_docs",
        "summary_total_pages",
        "summary_avg_pages_per_doc",
        "summary_split_doc_counts",
        "summary_split_page_counts",
        "summary_label_totals",
        "summary_handwriting",
        "summary_languages",
        "summary_dpi_counts",
        "summary_doc_id_mismatches",
        "plan_sections_present",
        "plan_data_summary_numbers_match_stats_json",
        "plan_phased_plan_structure",
        "plan_risks_mitigations",
        "plan_objectives_cover_constraints",
        "email_exists_and_length",
        "email_references_files_and_next_steps",
        "email_includes_numbers_from_stats",
        "email_questions_count",
        "email_salutation_prof_lee",
    ]
    ordered = {k: float(result.get(k, 0.0)) for k in grade_keys}
    print(json.dumps(ordered, indent=2))


if __name__ == "__main__":
    main()