import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _safe_read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            return header
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_parse_jsonl_notes(path: Path) -> Optional[Tuple[Dict[str, int], List[str]]]:
    notes_map: Dict[str, int] = {}
    note_ids: List[str] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return None
                _id = obj.get("id")
                if not isinstance(_id, str):
                    return None
                relevance = obj.get("relevance", 0)
                try:
                    rel_val = int(relevance)
                except Exception:
                    return None
                notes_map[_id] = rel_val
                note_ids.append(_id)
        return notes_map, note_ids
    except Exception:
        return None


def _parse_int(val: Any) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        try:
            # sometimes strings may have whitespace
            return int(str(val).strip())
        except Exception:
            return None


def _parse_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        try:
            return float(str(val).strip())
        except Exception:
            return None


def _compute_expected_ranking(bib_rows: List[Dict[str, str]], notes_map: Dict[str, int]) -> Optional[List[Dict[str, Any]]]:
    # Required columns in bibliography
    required_cols = {"id", "author", "year", "title", "type", "topic", "citations"}
    if not all(col in bib_rows[0] for col in required_cols):
        return None

    # Filter rows: topic includes "natural law", type is book or article, year >= 1990
    filtered = []
    for row in bib_rows:
        topic = (row.get("topic") or "").strip()
        type_val = (row.get("type") or "").strip()
        year = _parse_int(row.get("year"))
        citations = _parse_int(row.get("citations"))

        if year is None or citations is None:
            return None

        if "natural law" not in topic.lower():
            continue
        if type_val.lower() not in {"book", "article"}:
            continue
        if year < 1990:
            continue

        _id = (row.get("id") or "").strip()
        author = (row.get("author") or "").strip()
        title = (row.get("title") or "").strip()

        relevance = notes_map.get(_id, 0)
        rank_score = citations + 2 * relevance

        filtered.append({
            "id": _id,
            "author": author,
            "year": year,
            "title": title,
            "type": type_val,
            "topic": topic,
            "citations": citations,
            "relevance": relevance,
            "rank_score": float(rank_score),  # keep as float for comparison robustness
        })

    # Sort: desc rank_score; tie-breakers: higher citations, newer year, author asc
    filtered.sort(key=lambda r: (-r["rank_score"], -r["citations"], -r["year"], r["author"]))

    # Add rank (1-based)
    for idx, r in enumerate(filtered):
        r["rank"] = idx + 1

    return filtered


def _load_top_sources_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _safe_read_csv(path)
    if rows is None:
        return None
    # Expected columns:
    required_cols = ["id", "author", "year", "title", "type", "topic", "citations", "relevance", "rank_score", "rank"]
    # Convert and normalize types
    norm_rows: List[Dict[str, Any]] = []
    for row in rows:
        try:
            _id = (row.get("id") or "").strip()
            author = (row.get("author") or "").strip()
            title = (row.get("title") or "").strip()
            type_val = (row.get("type") or "").strip()
            topic = (row.get("topic") or "").strip()
            year = _parse_int(row.get("year"))
            citations = _parse_int(row.get("citations"))
            relevance = _parse_int(row.get("relevance"))
            rank_score = _parse_float(row.get("rank_score"))
            rank = _parse_int(row.get("rank"))
        except Exception:
            return None
        if None in (year, citations, relevance, rank_score, rank):
            return None
        norm_rows.append({
            "id": _id,
            "author": author,
            "year": year,
            "title": title,
            "type": type_val,
            "topic": topic,
            "citations": citations,
            "relevance": relevance,
            "rank_score": float(rank_score),
            "rank": rank
        })
    return norm_rows


def _extract_refs_from_text(text: str) -> List[str]:
    return re.findall(r"\[ref:([A-Za-z0-9_\-]+)\]", text)


def _find_heading_indices(lines: List[str], heading_text: str) -> Optional[Tuple[int, int]]:
    # Find line index of a heading matching "Top sources (1990–present)"
    heading_pattern = re.compile(r"^\s{0,3}#{1,6}\s*" + re.escape(heading_text) + r"\s*$")
    start_idx = None
    for i, line in enumerate(lines):
        if heading_pattern.match(line.strip()):
            start_idx = i
            break
    if start_idx is None:
        return None
    # Section ends at next heading (any level)
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if re.match(r"^\s{0,3}#{1,6}\s+", lines[j].strip()):
            end_idx = j
            break
    return (start_idx, end_idx)


def _collect_bullet_lines(lines: List[str], start: int, end: int) -> List[str]:
    bullets = []
    for i in range(start + 1, end):
        line = lines[i].rstrip("\n")
        if re.match(r"^\s*-\s+.*", line):
            bullets.append(line.strip())
    return bullets


def _search_json_for_string(obj: Any, needle: str) -> bool:
    try:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and needle in k:
                    return True
                if _search_json_for_string(v, needle):
                    return True
        elif isinstance(obj, list):
            for item in obj:
                if _search_json_for_string(item, needle):
                    return True
        elif isinstance(obj, str):
            return needle in obj
        else:
            return False
    except Exception:
        return False
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "top_sources_csv_columns": 0.0,
        "top_sources_ranking_exact_match": 0.0,
        "docs_has_top_sources_section": 0.0,
        "docs_top_5_bullets_cover_ranking": 0.0,
        "docs_all_refs_valid": 0.0,
        "validate_script_runs": 0.0,
        "validation_report_orphan_notes_warned": 0.0,
    }

    # Load inputs
    bib_path = workspace / "input" / "bibliography.csv"
    notes_path = workspace / "input" / "notes.jsonl"
    draft_doc_path = workspace / "docs" / "literature_review.md"  # final doc location per spec
    top_sources_path = workspace / "output" / "top_sources.csv"
    validate_script_path = workspace / "scripts" / "validate.py"
    validation_report_path = workspace / "output" / "validation_report.json"

    bib_rows = _safe_read_csv(bib_path) if bib_path.exists() else None
    notes_data = _safe_parse_jsonl_notes(notes_path) if notes_path.exists() else None

    # Compute expected ranking if possible
    expected_ranking: Optional[List[Dict[str, Any]]] = None
    if bib_rows is not None and notes_data is not None:
        expected_ranking = _compute_expected_ranking(bib_rows, notes_data[0])

    # 1) Check output/top_sources.csv columns
    required_header = ["id", "author", "year", "title", "type", "topic", "citations", "relevance", "rank_score", "rank"]
    if top_sources_path.exists():
        header = _safe_read_csv_header(top_sources_path)
        if header is not None and header == required_header:
            scores["top_sources_csv_columns"] = 1.0

    # 2) Check ranking exact match
    if expected_ranking is not None and top_sources_path.exists():
        actual_rows = _load_top_sources_csv(top_sources_path)
        if actual_rows is not None:
            # Compare length
            if len(actual_rows) == len(expected_ranking):
                # Compare row-by-row in order
                match = True
                for exp, act in zip(expected_ranking, actual_rows):
                    # Check id matches
                    if exp["id"] != act["id"]:
                        match = False
                        break
                    # Check fields
                    for key in ["author", "year", "title", "type", "topic", "citations", "relevance", "rank", "rank_score"]:
                        ev = exp[key]
                        av = act[key]
                        if key == "rank_score":
                            # Compare as float within tolerance
                            if abs(float(ev) - float(av)) > 1e-9:
                                match = False
                                break
                        else:
                            if ev != av:
                                match = False
                                break
                    if not match:
                        break
                if match:
                    scores["top_sources_ranking_exact_match"] = 1.0

    # 3) Check docs/literature_review.md section and bullets
    doc_text = _safe_read_text(draft_doc_path) if draft_doc_path.exists() else None
    if doc_text is not None:
        lines = doc_text.splitlines()
        heading_text = "Top sources (1990–present)"  # exact title required
        heading_indices = _find_heading_indices(lines, heading_text)
        if heading_indices is not None:
            scores["docs_has_top_sources_section"] = 1.0
            start, end = heading_indices
            bullets = _collect_bullet_lines(lines, start, end)
            if expected_ranking is not None and len(expected_ranking) >= 5:
                expected_top5 = expected_ranking[:5]
                # Build expected bullet strings
                expected_bullets = []
                for rec in expected_top5:
                    b = f"- {rec['title']} ({rec['year']}) — {rec['author']} [ref:{rec['id']}]"
                    expected_bullets.append(b.strip())
                found_set = set()
                for bline in bullets:
                    if bline.strip() in expected_bullets:
                        found_set.add(bline.strip())
                if all(b in found_set for b in expected_bullets):
                    scores["docs_top_5_bullets_cover_ranking"] = 1.0

        # Check all [ref:...] tokens resolve to bib ids
        if bib_rows is not None:
            bib_ids = { (row.get("id") or "").strip() for row in bib_rows }
            refs = _extract_refs_from_text(doc_text)
            if all(ref in bib_ids for ref in refs):
                scores["docs_all_refs_valid"] = 1.0

    # 4) Run scripts/validate.py and inspect report
    if validate_script_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(validate_script_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            # Validation report must exist after running
            if validation_report_path.exists():
                # We award run score only if script exited with zero and report exists
                if proc.returncode == 0:
                    scores["validate_script_runs"] = 1.0
                # Load report and check that orphan notes warnings include NL999
                try:
                    report = json.loads(validation_report_path.read_text(encoding="utf-8"))
                    if _search_json_for_string(report, "NL999"):
                        scores["validation_report_orphan_notes_warned"] = 1.0
                except Exception:
                    pass
        except Exception:
            # Could not run the script; keep scores as 0.0
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()