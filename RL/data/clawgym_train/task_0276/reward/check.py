import json
import sys
import hashlib
import re
from datetime import datetime
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


def _file_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _file_size(path: Path) -> Optional[int]:
    try:
        return path.stat().st_size
    except Exception:
        return None


def _parse_iso8601(ts: str) -> bool:
    if not isinstance(ts, str) or not ts.strip():
        return False
    s = ts.strip()
    try:
        # Accept trailing Z as UTC
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def _find_paragraphs(text: str) -> List[str]:
    # Paragraphs are separated by one or more blank lines
    paras: List[str] = []
    current: List[str] = []
    for line in text.splitlines():
        if line.strip():
            current.append(line.strip())
        else:
            if current:
                paras.append(" ".join(current).strip())
                current = []
    if current:
        paras.append(" ".join(current).strip())
    return paras


def _extract_markdown_tables(text: str) -> List[Tuple[List[str], List[List[str]]]]:
    """
    Returns list of tables as (headers, rows), where headers is a list of header strings,
    and rows is a list of lists of cell strings.
    """
    lines = text.splitlines()
    tables: List[Tuple[List[str], List[List[str]]]] = []
    i = 0
    while i < len(lines) - 1:
        line = lines[i]
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        if "|" in line and "|" in next_line:
            # Check if next_line is a separator (hyphens and pipes)
            sep_line = next_line.strip()
            if re.fullmatch(r"\s*\|?[\s:\-\|]+\|?\s*", sep_line):
                # Parse header
                header_cells = [c.strip() for c in line.strip().split("|")]
                if header_cells and header_cells[0] == "":
                    header_cells = header_cells[1:]
                if header_cells and header_cells[-1] == "":
                    header_cells = header_cells[:-1]
                # Now collect rows
                rows: List[List[str]] = []
                j = i + 2
                while j < len(lines):
                    row_line = lines[j]
                    if not row_line.strip():
                        break
                    if "|" not in row_line:
                        break
                    cells = [c.strip() for c in row_line.strip().split("|")]
                    if cells and cells[0] == "":
                        cells = cells[1:]
                    if cells and cells[-1] == "":
                        cells = cells[:-1]
                    rows.append(cells)
                    j += 1
                # Normalize header and rows to same width by padding
                width = len(header_cells)
                norm_rows: List[List[str]] = []
                for r in rows:
                    if len(r) < width:
                        r = r + [""] * (width - len(r))
                    elif len(r) > width:
                        r = r[:width]
                    norm_rows.append(r)
                tables.append((header_cells, norm_rows))
                i = j
                continue
        i += 1
    return tables


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "sepsis_pdf_exists": 0.0,
        "ventilation_pdf_exists": 0.0,
        "manifest_schema_valid": 0.0,
        "manifest_files_integrity": 0.0,
        "brief_exists_and_clean": 0.0,
        "references_replaced_correctly": 0.0,
        "implications_paragraph_valid": 0.0,
        "file_table_correct": 0.0,
    }

    # Expected files
    sepsis_pdf = workspace / "data/guidelines/sepsis_guideline.pdf"
    ventilation_pdf = workspace / "data/guidelines/ventilation_guideline.pdf"
    manifest_path = workspace / "outputs/guidelines_manifest.json"
    brief_path = workspace / "outputs/brief_updated.md"

    # Check PDFs exist and are non-empty
    if sepsis_pdf.is_file() and (_file_size(sepsis_pdf) or 0) > 0:
        scores["sepsis_pdf_exists"] = 1.0
    else:
        scores["sepsis_pdf_exists"] = 0.0

    if ventilation_pdf.is_file() and (_file_size(ventilation_pdf) or 0) > 0:
        scores["ventilation_pdf_exists"] = 1.0
    else:
        scores["ventilation_pdf_exists"] = 0.0

    # Load manifest
    manifest = _load_json(manifest_path)
    manifest_items: List[Dict[str, Any]] = []
    manifest_valid = False
    ids_expected = {"sepsis", "ventilation"}
    expected_paths = {
        "sepsis": "data/guidelines/sepsis_guideline.pdf",
        "ventilation": "data/guidelines/ventilation_guideline.pdf",
    }

    if manifest is not None:
        if isinstance(manifest, list):
            manifest_items = manifest
        elif isinstance(manifest, dict):
            # Accept dict of items: use values if they look like dicts with required fields
            try:
                manifest_items = list(manifest.values())
            except Exception:
                manifest_items = []
        # Validate schema
        if isinstance(manifest_items, list) and len(manifest_items) == 2:
            ids_found = set()
            schema_ok = True
            for item in manifest_items:
                if not isinstance(item, dict):
                    schema_ok = False
                    break
                required_fields = [
                    "id",
                    "source_organization",
                    "document_title",
                    "publication_year",
                    "saved_path",
                    "file_size_bytes",
                    "sha256",
                    "retrieved_at",
                ]
                for f in required_fields:
                    if f not in item:
                        schema_ok = False
                        break
                if not schema_ok:
                    break
                # Types and values
                if item.get("id") not in ids_expected:
                    schema_ok = False
                    break
                ids_found.add(item.get("id"))
                if not (isinstance(item.get("source_organization"), str) and item["source_organization"].strip()):
                    schema_ok = False
                    break
                if not (isinstance(item.get("document_title"), str) and item["document_title"].strip()):
                    schema_ok = False
                    break
                if not isinstance(item.get("publication_year"), int):
                    schema_ok = False
                    break
                if not (1900 <= item["publication_year"] <= 2100):
                    schema_ok = False
                    break
                if not (isinstance(item.get("saved_path"), str) and item["saved_path"].strip()):
                    schema_ok = False
                    break
                # Exact saved_path must match expected
                if item["saved_path"] != expected_paths[item["id"]]:
                    schema_ok = False
                    break
                if not (isinstance(item.get("file_size_bytes"), int) and item["file_size_bytes"] >= 0):
                    schema_ok = False
                    break
                if not (isinstance(item.get("sha256"), str) and re.fullmatch(r"[0-9a-fA-F]{64}", item["sha256"] or "") is not None):
                    schema_ok = False
                    break
                if not (isinstance(item.get("retrieved_at"), str) and _parse_iso8601(item["retrieved_at"])):
                    schema_ok = False
                    break
            if schema_ok and ids_found == ids_expected:
                manifest_valid = True

    scores["manifest_schema_valid"] = 1.0 if manifest_valid else 0.0

    # Check manifest files integrity (file presence, size, sha match)
    files_integrity_ok = False
    if manifest_valid:
        integrity_ok = True
        # Build lookup by id
        by_id: Dict[str, Dict[str, Any]] = {item["id"]: item for item in manifest_items}  # type: ignore
        for id_ in ["sepsis", "ventilation"]:
            item = by_id.get(id_)
            if not item:
                integrity_ok = False
                break
            saved_rel = item["saved_path"]
            saved_path = workspace / saved_rel
            if not saved_path.is_file():
                integrity_ok = False
                break
            actual_size = _file_size(saved_path)
            actual_sha = _file_sha256(saved_path)
            if actual_size is None or actual_sha is None:
                integrity_ok = False
                break
            if actual_size != item["file_size_bytes"]:
                integrity_ok = False
                break
            if actual_sha.lower() != item["sha256"].lower():
                integrity_ok = False
                break
        files_integrity_ok = integrity_ok
    scores["manifest_files_integrity"] = 1.0 if files_integrity_ok else 0.0

    # Brief checks
    brief_text = _read_text(brief_path)
    brief_exists = brief_text is not None
    brief_clean = False
    references_ok = False
    implications_ok = False
    table_ok = False

    if brief_exists and manifest_valid:
        t = brief_text if brief_text is not None else ""
        # No placeholders and no URLs
        no_placeholders = ("{{" not in t and "}}" not in t)
        no_urls = not re.search(r"https?://|www\.", t)
        brief_clean = bool(no_placeholders and no_urls)

        # References replaced correctly
        by_id: Dict[str, Dict[str, Any]] = {item["id"]: item for item in manifest_items}  # type: ignore
        sepsis_title = by_id["sepsis"]["document_title"]
        sepsis_year = by_id["sepsis"]["publication_year"]
        ventilation_title = by_id["ventilation"]["document_title"]
        ventilation_year = by_id["ventilation"]["publication_year"]

        expected_line1 = f"Reference 1 (Sepsis Guideline): {sepsis_title} ({sepsis_year})"
        expected_line2 = f"Reference 2 (Ventilator-Associated Complications Guideline): {ventilation_title} ({ventilation_year})"

        lines = t.splitlines()
        has_line1 = any(line.strip() == expected_line1 for line in lines)
        has_line2 = any(line.strip() == expected_line2 for line in lines)
        references_ok = bool(has_line1 and has_line2)

        # Implications paragraph: single paragraph 50–120 words, references both titles in double quotes
        paras = _find_paragraphs(t)
        # We need a paragraph that includes both titles in quotes
        quote1 = f"\"{sepsis_title}\""
        quote2 = f"\"{ventilation_title}\""
        found_para = False
        for p in paras:
            if quote1 in p and quote2 in p:
                # Count words: split on whitespace
                words = re.findall(r"\b[\w'-]+\b", p)
                wc = len(words)
                if 50 <= wc <= 120:
                    found_para = True
                    break
        implications_ok = found_para

        # File table correct
        tables = _extract_markdown_tables(t)
        expected_pairs = {
            (expected_paths["sepsis"], by_id["sepsis"]["sha256"]),
            (expected_paths["ventilation"], by_id["ventilation"]["sha256"]),
        }
        table_match = False
        for headers, rows in tables:
            norm_headers = [h.strip() for h in headers]
            if len(norm_headers) >= 2 and norm_headers[0] == "file" and norm_headers[1] == "sha256":
                # Filter non-empty rows with at least two columns
                data_pairs = set()
                for r in rows:
                    if len(r) >= 2:
                        data_pairs.add((r[0], r[1]))
                # Must be exactly two rows and match expected set
                if len(data_pairs) == 2 and data_pairs == expected_pairs:
                    table_match = True
                    break
        table_ok = table_match

    scores["brief_exists_and_clean"] = 1.0 if (brief_exists and brief_clean) else 0.0
    scores["references_replaced_correctly"] = 1.0 if (brief_exists and manifest_valid and references_ok) else 0.0
    scores["implications_paragraph_valid"] = 1.0 if (brief_exists and manifest_valid and implications_ok) else 0.0
    scores["file_table_correct"] = 1.0 if (brief_exists and manifest_valid and table_ok) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()