import sys
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set


def _read_text_lines(path: Path) -> Optional[List[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        # Keep exact line texts without trailing newline
        return text.splitlines()
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _list_input_files(workspace: Path) -> List[Path]:
    input_dir = workspace / "input"
    if not input_dir.exists() or not input_dir.is_dir():
        return []
    return sorted([p for p in input_dir.rglob("*") if p.is_file()], key=lambda p: p.as_posix())


def _relative_posix(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        return path.as_posix()


def _parse_inventory(path: Path) -> Optional[List[Tuple[str, int]]]:
    lines = _read_text_lines(path)
    if lines is None:
        return None
    entries: List[Tuple[str, int]] = []
    for raw in lines:
        line = raw.strip("\n\r")
        if not line.strip():
            # ignore blank lines
            continue
        parts = line.strip().split()
        if not parts:
            continue
        # last token must be integer line count
        last = parts[-1]
        try:
            count = int(last)
        except ValueError:
            return None
        file_path = " ".join(parts[:-1]).strip()
        if not file_path:
            return None
        entries.append((file_path, count))
    return entries


def _find_keyword_hits_in_file(file_path: Path, keywords: List[str]) -> Dict[int, Set[str]]:
    hits: Dict[int, Set[str]] = {}
    lines = _read_text_lines(file_path)
    if lines is None:
        return hits
    for idx, line in enumerate(lines, start=1):
        lower = line.lower()
        matched = set()
        for kw in keywords:
            if kw.lower() in lower:
                matched.add(kw)
        if matched:
            hits[idx] = matched
    return hits


def _build_expected_from_checklist(workspace: Path) -> Optional[Dict]:
    checklist_path = workspace / "input" / "checklists" / "compliance_checklist.json"
    checklist = _load_json(checklist_path)
    if not isinstance(checklist, dict):
        return None
    categories = checklist.get("categories")
    if not isinstance(categories, list):
        return None

    expected = {
        "requirements": {},  # id -> dict
        "by_category": {},   # category -> list of ids
    }

    for cat in categories:
        if not isinstance(cat, dict):
            return None
        category_name = cat.get("category")
        reqs = cat.get("requirements")
        if not isinstance(category_name, str) or not isinstance(reqs, list):
            return None
        expected["by_category"].setdefault(category_name, [])
        for req in reqs:
            if not isinstance(req, dict):
                return None
            rid = req.get("id")
            desc = req.get("description")
            keywords = req.get("keywords")
            must_list = req.get("must_appear_in")
            if not isinstance(rid, str) or not isinstance(desc, str) or not isinstance(keywords, list) or not isinstance(must_list, list):
                return None
            if rid in expected["requirements"]:
                return None  # duplicate ids, malformed
            # Compute expected evidence lines (unique per file/line) where any keyword appears
            expected_lines: Set[Tuple[str, int, str]] = set()
            for allow in must_list:
                if not isinstance(allow, str):
                    continue
                fpath = workspace / allow
                if fpath.exists() and fpath.is_file():
                    hits = _find_keyword_hits_in_file(fpath, keywords)
                    lines_content = _read_text_lines(fpath) or []
                    for line_no, matched_set in hits.items():
                        # Any match qualifies the line; collect once per line
                        if 1 <= line_no <= len(lines_content):
                            expected_lines.add((allow, line_no, lines_content[line_no - 1]))
            status = "pass" if len(expected_lines) > 0 else "fail"
            expected["requirements"][rid] = {
                "id": rid,
                "category": category_name,
                "description": desc,
                "keywords": keywords,
                "must_appear_in": must_list,
                "expected_status": status,
                "expected_lines": expected_lines,
            }
            expected["by_category"][category_name].append(rid)
    return expected


def _load_extracted_hits(path: Path) -> Optional[List[dict]]:
    data = _load_json(path)
    if not isinstance(data, list):
        return None
    # basic structure validation here, deeper in checks
    return data


def _extract_numbers_from_line(line: str) -> List[int]:
    return [int(x) for x in re.findall(r"\b\d+\b", line)]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "inventory_file_exists": 0.0,
        "inventory_covers_all_input_files": 0.0,
        "inventory_no_extra_paths": 0.0,
        "inventory_no_duplicate_paths": 0.0,
        "inventory_line_counts_correct": 0.0,
        "extracted_hits_file_exists": 0.0,
        "extracted_hits_has_one_object_per_requirement": 0.0,
        "extracted_hits_metadata_fields_match": 0.0,
        "extracted_hits_status_correct_all": 0.0,
        "extracted_hits_evidence_lines_complete_and_exclusive": 0.0,
        "extracted_hits_evidence_fields_valid": 0.0,
        "report_file_exists": 0.0,
        "report_summary_counts_correct": 0.0,
        "report_per_category_breakdown_correct": 0.0,
        "report_missing_requirements_listed_with_targets": 0.0,
    }

    # Prepare expected from checklist
    expected = _build_expected_from_checklist(workspace)

    # Inventory checks
    inventory_path = workspace / "out" / "file_inventory.txt"
    if inventory_path.exists() and inventory_path.is_file():
        scores["inventory_file_exists"] = 1.0
        entries = _parse_inventory(inventory_path)
        input_files = _list_input_files(workspace)
        expected_map: Dict[str, int] = {}
        for f in input_files:
            rel = _relative_posix(f, workspace)
            lines = _read_text_lines(f)
            count = len(lines) if lines is not None else 0
            expected_map[rel] = count
        if entries is not None:
            # Build maps from entries
            seen: Dict[str, int] = {}
            duplicate = False
            for path_str, cnt in entries:
                if path_str in seen:
                    duplicate = True
                seen[path_str] = cnt
            # coverage
            covers_all = all(k in seen for k in expected_map.keys()) and len(expected_map) > 0 or (len(expected_map) == 0 and len(seen) == 0)
            scores["inventory_covers_all_input_files"] = 1.0 if covers_all else 0.0
            # no extra
            no_extra = all(k in expected_map for k in seen.keys())
            scores["inventory_no_extra_paths"] = 1.0 if no_extra else 0.0
            # no duplicate paths
            scores["inventory_no_duplicate_paths"] = 1.0 if not duplicate else 0.0
            # counts
            counts_ok = True
            for k, v in expected_map.items():
                if k not in seen or seen[k] != v:
                    counts_ok = False
                    break
            scores["inventory_line_counts_correct"] = 1.0 if counts_ok and covers_all and no_extra else 0.0
        else:
            # Malformed inventory file
            scores["inventory_covers_all_input_files"] = 0.0
            scores["inventory_no_extra_paths"] = 0.0
            scores["inventory_no_duplicate_paths"] = 0.0
            scores["inventory_line_counts_correct"] = 0.0
    else:
        # file missing, inventory checks remain 0.0
        pass

    # Extracted hits checks
    extracted_path = workspace / "out" / "extracted_hits.json"
    extracted = None
    if extracted_path.exists() and extracted_path.is_file():
        scores["extracted_hits_file_exists"] = 1.0
        extracted = _load_extracted_hits(extracted_path)
    else:
        extracted = None

    if expected is None or extracted is None:
        # If either checklist parse failed or extracted is missing/malformed, all extracted-related checks remain 0.0
        pass
    else:
        reqs_expected = expected["requirements"]
        # has one object per requirement
        ids_expected = set(reqs_expected.keys())
        # Build map by id
        by_id: Dict[str, dict] = {}
        id_duplicate = False
        if isinstance(extracted, list):
            for obj in extracted:
                if not isinstance(obj, dict):
                    id_duplicate = True
                    break
                rid = obj.get("id")
                if not isinstance(rid, str):
                    id_duplicate = True
                    break
                if rid in by_id:
                    id_duplicate = True
                    break
                by_id[rid] = obj

        has_all = (not id_duplicate) and (set(by_id.keys()) == ids_expected)
        scores["extracted_hits_has_one_object_per_requirement"] = 1.0 if has_all else 0.0

        # metadata fields and status and evidence checks only if ids match
        metadata_ok = True
        status_ok = True
        evidence_lines_ok = True
        evidence_fields_ok = True

        if has_all:
            for rid in sorted(ids_expected):
                exp = reqs_expected[rid]
                obj = by_id[rid]
                # metadata fields
                if obj.get("category") != exp["category"] or obj.get("description") != exp["description"]:
                    metadata_ok = False
                status = obj.get("status")
                if status not in ("pass", "fail") or status != exp["expected_status"]:
                    status_ok = False
                evidence = obj.get("evidence")
                if status == "fail":
                    # evidence must be empty array
                    if not isinstance(evidence, list) or len(evidence) != 0:
                        evidence_lines_ok = False
                        evidence_fields_ok = False
                    continue
                # pass case
                if not isinstance(evidence, list):
                    evidence_lines_ok = False
                    evidence_fields_ok = False
                    continue
                # Build expected lines set
                expected_lines: Set[Tuple[str, int, str]] = exp["expected_lines"]
                # Build actual lines set, check fields validity
                actual_lines: Set[Tuple[str, int, str]] = set()
                for ev in evidence:
                    if not isinstance(ev, dict):
                        evidence_fields_ok = False
                        continue
                    fpath = ev.get("file_path")
                    lno = ev.get("line")
                    mkw = ev.get("matched_keyword")
                    ltxt = ev.get("line_text")
                    # Basic type checks
                    if not isinstance(fpath, str) or not isinstance(lno, int) or not isinstance(mkw, str) or not isinstance(ltxt, str):
                        evidence_fields_ok = False
                        continue
                    # file must be in must_appear_in
                    if fpath not in exp["must_appear_in"]:
                        evidence_fields_ok = False
                    # line number positive and within file
                    file_abs = workspace / fpath
                    flines = _read_text_lines(file_abs) or []
                    if lno < 1 or lno > len(flines):
                        evidence_fields_ok = False
                    else:
                        # line_text must match
                        if flines[lno - 1] != ltxt:
                            evidence_fields_ok = False
                        # matched_keyword must be in keywords and appear in this line
                        kws = exp["keywords"]
                        if mkw not in kws:
                            evidence_fields_ok = False
                        else:
                            if mkw.lower() not in flines[lno - 1].lower():
                                evidence_fields_ok = False
                    # Record the line triple
                    actual_lines.add((fpath, lno, ltxt))
                # Evidence lines must be complete and exclusive (one per matching line)
                if actual_lines != expected_lines:
                    evidence_lines_ok = False

        scores["extracted_hits_metadata_fields_match"] = 1.0 if metadata_ok and has_all else 0.0
        scores["extracted_hits_status_correct_all"] = 1.0 if status_ok and has_all else 0.0
        scores["extracted_hits_evidence_lines_complete_and_exclusive"] = 1.0 if evidence_lines_ok and has_all else 0.0
        scores["extracted_hits_evidence_fields_valid"] = 1.0 if evidence_fields_ok and has_all else 0.0

    # Report checks
    report_path = workspace / "out" / "compliance_report.md"
    if report_path.exists() and report_path.is_file():
        scores["report_file_exists"] = 1.0
        report_lines = _read_text_lines(report_path)
    else:
        report_lines = None

    if expected is None or report_lines is None:
        # leave report checks at 0.0
        pass
    else:
        report_text = "\n".join(report_lines)

        # Compute expected counts
        reqs_expected = expected["requirements"]
        total = len(reqs_expected)
        passed = sum(1 for r in reqs_expected.values() if r["expected_status"] == "pass")
        failed = total - passed

        # summary counts
        def _line_has_total_requirements(line: str) -> bool:
            return ("total" in line.lower() and "requirement" in line.lower() and str(total) in line)

        def _line_has_passed_count(line: str) -> bool:
            low = line.lower()
            return ("pass" in low and str(passed) in line)

        def _line_has_failed_count(line: str) -> bool:
            low = line.lower()
            return ("fail" in low and str(failed) in line)

        has_total = any(_line_has_total_requirements(l) for l in report_lines)
        has_passed = any(_line_has_passed_count(l) for l in report_lines)
        has_failed = any(_line_has_failed_count(l) for l in report_lines)
        scores["report_summary_counts_correct"] = 1.0 if has_total and has_passed and has_failed else 0.0

        # per-category breakdown
        categories_ok = True
        for cat, ids in expected["by_category"].items():
            cat_pass = sum(1 for rid in ids if reqs_expected[rid]["expected_status"] == "pass")
            cat_fail = len(ids) - cat_pass
            # find a line that mentions category and includes both numbers and pass/fail words
            found_line = False
            for l in report_lines:
                if cat in l:
                    low = l.lower()
                    if ("pass" in low and "fail" in low and re.search(rf"\b{cat_pass}\b", l) and re.search(rf"\b{cat_fail}\b", l)):
                        found_line = True
                        break
            if not found_line:
                categories_ok = False
                break
        scores["report_per_category_breakdown_correct"] = 1.0 if categories_ok else 0.0

        # missing requirements section
        failed_reqs = [reqs_expected[rid] for rid in reqs_expected if reqs_expected[rid]["expected_status"] == "fail"]
        # If none failed, then we consider the section valid if either a missing section exists and is empty, or no missing section
        # But the task requires the section; we'll require presence of the section line even if none failed, listing none.
        # Determine section start
        section_start_idx = None
        for i, l in enumerate(report_lines):
            if "missing requirements" in l.lower():
                section_start_idx = i
                break
        if section_start_idx is None:
            # if there are failed requirements, this is invalid
            scores["report_missing_requirements_listed_with_targets"] = 1.0 if len(failed_reqs) == 0 else 0.0
        else:
            section_lines = report_lines[section_start_idx:]
            section_text = "\n".join(section_lines)
            all_ok = True
            for req in failed_reqs:
                rid = req["id"]
                desc = req["description"]
                targets = req["must_appear_in"]
                # Find a line containing id and "Add to:" and one of the targets
                found_entry = False
                for idx, l in enumerate(section_lines):
                    if rid in l and "add to:" in l.lower():
                        # check target presence
                        if any(t in l for t in targets):
                            # Check description present in same line or next two lines
                            desc_ok = (desc in l)
                            if not desc_ok:
                                for j in range(1, 3):
                                    if idx + j < len(section_lines) and desc in section_lines[idx + j]:
                                        desc_ok = True
                                        break
                            if desc_ok:
                                found_entry = True
                                break
                if not found_entry:
                    all_ok = False
                    break
            scores["report_missing_requirements_listed_with_targets"] = 1.0 if all_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()