import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set


ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="latin-1")
        except Exception:
            return None


def _safe_load_json_file(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        try:
            with path.open("r", encoding="latin-1", newline="") as f:
                reader = csv.DictReader(f)
                rows = [dict(r) for r in reader]
                return rows
        except Exception:
            return None


def _normalize_title(s: str) -> str:
    s = s.strip().lower()
    # Remove punctuation (ASCII) and various dashes
    s = re.sub(r"[\s\-–—_]+", " ", s)
    s = re.sub(r"[^\w\s]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _split_semicolons(s: str) -> List[str]:
    return [part.strip() for part in s.split(";") if part.strip()]


def _casefold_list(xs: List[str]) -> List[str]:
    return [x.strip().casefold() for x in xs]


def _authors_equal(set_a: List[str], set_b: List[str]) -> bool:
    return set(_casefold_list(set_a)) == set(_casefold_list(set_b))


def _publishers_equal(set_a: List[str], set_b: List[str]) -> bool:
    return set(_casefold_list(set_a)) == set(_casefold_list(set_b))


def _extract_books_api_payload(js: Any) -> Optional[Dict[str, Any]]:
    # Attempt to locate the book object in Books API JSON
    if not isinstance(js, dict):
        return None
    book_obj = None
    # Case 1: keys like "ISBN:978..."
    isbn_keys = [k for k in js.keys() if isinstance(k, str) and k.startswith("ISBN:")]
    if isbn_keys:
        # Prefer the exact one if there is a single key; else pick first deterministically
        isbn_keys.sort()
        candidate = js.get(isbn_keys[0])
        if isinstance(candidate, dict):
            book_obj = candidate
    # Case 2: object is the book itself (has 'title' or other fields)
    if book_obj is None:
        if any(k in js for k in ("title", "authors", "publish_date", "publish_year", "number_of_pages", "publishers")):
            book_obj = js
    if not isinstance(book_obj, dict):
        return None

    # Extract fields
    title = None
    if isinstance(book_obj.get("title"), str):
        title = book_obj.get("title", "").strip() or None

    authors: List[str] = []
    raw_authors = book_obj.get("authors")
    if isinstance(raw_authors, list):
        for a in raw_authors:
            if isinstance(a, dict) and isinstance(a.get("name"), str):
                name = a.get("name", "").strip()
                if name:
                    authors.append(name)
            elif isinstance(a, str):
                name = a.strip()
                if name:
                    authors.append(name)

    publishers: List[str] = []
    raw_publishers = book_obj.get("publishers")
    if isinstance(raw_publishers, list):
        for p in raw_publishers:
            if isinstance(p, dict) and isinstance(p.get("name"), str):
                nm = p.get("name", "").strip()
                if nm:
                    publishers.append(nm)
            elif isinstance(p, str):
                nm = p.strip()
                if nm:
                    publishers.append(nm)

    number_of_pages = None
    nop = book_obj.get("number_of_pages")
    if isinstance(nop, int):
        number_of_pages = nop
    elif isinstance(nop, str):
        try:
            number_of_pages = int(nop.strip())
        except Exception:
            number_of_pages = None

    publish_years: Set[int] = set()
    # from publish_year list
    py = book_obj.get("publish_year")
    if isinstance(py, list):
        for item in py:
            if isinstance(item, int):
                publish_years.add(item)
            elif isinstance(item, str):
                m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", item)
                if m:
                    try:
                        publish_years.add(int(m.group(0)))
                    except Exception:
                        pass
    # from publish_date string
    pd = book_obj.get("publish_date")
    if isinstance(pd, str):
        years = re.findall(r"\b(1[89]\d{2}|20\d{2})\b", pd)
        for y in years:
            try:
                publish_years.add(int(y))
            except Exception:
                pass

    return {
        "title": title,
        "authors": authors,
        "publishers": publishers,
        "number_of_pages": number_of_pages,
        "publish_years": sorted(publish_years),
    }


def _load_input_seed(workspace: Path) -> Optional[List[Dict[str, str]]]:
    seed_path = workspace / "input" / "seed_star_wars_books.csv"
    rows = _read_csv_rows(seed_path)
    return rows


def _find_script_file(scripts_dir: Path) -> Optional[Path]:
    if not scripts_dir.exists() or not scripts_dir.is_dir():
        return None
    candidates: List[Path] = []
    for p in scripts_dir.rglob("*"):
        if p.is_file() and (p.suffix in {".sh", ".py"} or p.name.lower().startswith("run")):
            candidates.append(p)
    if not candidates:
        return None
    candidates.sort()
    return candidates[0]


def _load_processed_csv(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    proc_path = workspace / "data" / "processed" / "reading_arcs.csv"
    try:
        with proc_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, None
            f.seek(0)
            dict_reader = csv.DictReader(f)
            rows = [dict(r) for r in dict_reader]
            return rows, header
    except Exception:
        try:
            with proc_path.open("r", encoding="latin-1", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header is None:
                    return None, None
                f.seek(0)
                dict_reader = csv.DictReader(f)
                rows = [dict(r) for r in dict_reader]
                return rows, header
        except Exception:
            return None, None


def _cover_files_for_isbn(workspace: Path, isbn: str) -> List[Path]:
    cover_dir = workspace / "assets" / "covers"
    results: List[Path] = []
    if not cover_dir.exists():
        return results
    for p in cover_dir.iterdir():
        if p.is_file() and p.name.startswith(isbn + ".") and p.suffix.lower() in ALLOWED_IMAGE_EXTS:
            results.append(p)
    results.sort()
    return results


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "raw_json_files_complete": 0.0,
        "cover_images_complete": 0.0,
        "processed_csv_structure": 0.0,
        "processed_rows_match_input": 0.0,
        "fetched_fields_consistency": 0.0,
        "cover_image_path_consistency": 0.0,
        "source_field_correct": 0.0,
        "match_confidence_correct": 0.0,
        "arcs_summary_correct": 0.0,
        "missing_log_covers_and_json": 0.0,
        "script_exists": 0.0,
        "script_references_endpoints": 0.0,
        "script_references_paths_and_seed": 0.0,
    }

    # Load input seed
    seed_rows = _load_input_seed(workspace)
    if not seed_rows:
        # Without input seed, we cannot verify much; keep zeros except script checks
        pass

    # Script checks
    scripts_dir = workspace / "scripts"
    script_file = _find_script_file(scripts_dir)
    if script_file and script_file.exists():
        scores["script_exists"] = 1.0
        content = _safe_read_text(script_file) or ""
        # Endpoints
        ep_score = 0.0
        has_books_api = ("openlibrary.org/api/books" in content) or ("api/books" in content and "openlibrary.org" in content)
        has_covers_service = ("covers.openlibrary.org" in content)
        if has_books_api and has_covers_service:
            ep_score = 1.0
        scores["script_references_endpoints"] = ep_score
        # Paths & seed references
        paths_score = 0.0
        required_path_tokens = [
            "data/raw", "data/processed", "assets/covers", "logs"
        ]
        has_paths = all(tok in content for tok in required_path_tokens)
        has_seed = ("input/seed_star_wars_books.csv" in content) or ("seed_star_wars_books.csv" in content)
        has_outputs = ("reading_arcs.csv" in content and "arcs_summary.json" in content)
        if has_paths and has_seed and has_outputs:
            paths_score = 1.0
        scores["script_references_paths_and_seed"] = paths_score
    else:
        scores["script_exists"] = 0.0
        scores["script_references_endpoints"] = 0.0
        scores["script_references_paths_and_seed"] = 0.0

    # If we have seed, proceed with file-based checks
    if seed_rows:
        # Expected ISBNs and input mapping
        input_by_isbn: Dict[str, Dict[str, str]] = {}
        for r in seed_rows:
            isbn = (r.get("isbn13") or "").strip()
            if isbn:
                input_by_isbn[isbn] = {
                    "arc_name": r.get("arc_name", "").strip(),
                    "canon_or_legends": r.get("canon_or_legends", "").strip(),
                    "title": r.get("title", "").strip(),
                    "author": r.get("author", "").strip(),
                    "isbn13": isbn,
                }

        isbns = list(input_by_isbn.keys())

        # Raw JSON completeness and parseability
        raw_dir = workspace / "data" / "raw" / "openlibrary"
        raw_present_count = 0
        raw_parseable_count = 0
        for isbn in isbns:
            jf = raw_dir / f"{isbn}.json"
            if jf.exists() and jf.is_file():
                raw_present_count += 1
                js = _safe_load_json_file(jf)
                if js is not None:
                    raw_parseable_count += 1
        if isbns:
            # We weight based on parseability (must exist and parse)
            scores["raw_json_files_complete"] = raw_parseable_count / len(isbns)
        else:
            scores["raw_json_files_complete"] = 0.0

        # Cover images completeness
        cover_ok = 0
        for isbn in isbns:
            covers = _cover_files_for_isbn(workspace, isbn)
            if len(covers) >= 1:
                cover_ok += 1
        if isbns:
            scores["cover_images_complete"] = cover_ok / len(isbns)
        else:
            scores["cover_images_complete"] = 0.0

        # Processed CSV structure and rows
        processed_rows, processed_header = _load_processed_csv(workspace)
        required_header = [
            "isbn13",
            "arc_name",
            "canon_or_legends",
            "input_title",
            "input_author",
            "fetched_title",
            "fetched_authors",
            "publish_year",
            "number_of_pages",
            "publishers",
            "cover_image_path",
            "source",
            "match_confidence",
        ]
        if processed_header == required_header and processed_rows is not None:
            scores["processed_csv_structure"] = 1.0
        else:
            scores["processed_csv_structure"] = 0.0

        # processed_rows_match_input
        if processed_rows is not None and processed_rows:
            # Check row count and presence by ISBN
            by_isbn_processed: Dict[str, Dict[str, str]] = {}
            for r in processed_rows:
                by_isbn_processed[(r.get("isbn13") or "").strip()] = {k: (v if isinstance(v, str) else "" ) for k, v in r.items()}

            present_count = 0
            input_fields_match = 0
            for isbn in isbns:
                pr = by_isbn_processed.get(isbn)
                if pr:
                    present_count += 1
                    # Check input fields mapping
                    inp = input_by_isbn[isbn]
                    if (pr.get("arc_name", "").strip() == inp["arc_name"]
                        and pr.get("canon_or_legends", "").strip() == inp["canon_or_legends"]
                        and pr.get("input_title", "").strip() == inp["title"]
                        and pr.get("input_author", "").strip() == inp["author"]):
                        input_fields_match += 1
            if isbns:
                # Weight both presence and input field exact matching
                scores["processed_rows_match_input"] = (0.5 * (present_count / len(isbns)) +
                                                        0.5 * (input_fields_match / len(isbns)))
            else:
                scores["processed_rows_match_input"] = 0.0
        else:
            scores["processed_rows_match_input"] = 0.0

        # fetched_fields_consistency, cover_image_path_consistency, source_field_correct, match_confidence_correct
        fetched_total_checks = 0
        fetched_correct = 0

        cover_path_total = 0
        cover_path_correct = 0

        source_total = 0
        source_correct = 0

        match_conf_total = 0
        match_conf_correct = 0

        if processed_rows:
            for r in processed_rows:
                isbn = (r.get("isbn13") or "").strip()
                if not isbn or isbn not in input_by_isbn:
                    continue
                # Load raw json
                raw_path = raw_dir / f"{isbn}.json"
                js = _safe_load_json_file(raw_path) if raw_path.exists() else None
                payload = _extract_books_api_payload(js) if js is not None else None

                # Fetched title
                ft_csv = (r.get("fetched_title") or "").strip()
                if payload:
                    exp_title = payload.get("title") or ""
                else:
                    exp_title = ""
                fetched_total_checks += 1
                if ft_csv == exp_title:
                    fetched_correct += 1

                # Fetched authors
                fa_csv = (r.get("fetched_authors") or "").strip()
                fa_list_csv = _split_semicolons(fa_csv)
                exp_authors = payload.get("authors") if payload else []
                fetched_total_checks += 1
                if _authors_equal(fa_list_csv, exp_authors):
                    fetched_correct += 1

                # Publish year
                py_csv = (r.get("publish_year") or "").strip()
                exp_years = set(payload.get("publish_years", [])) if payload else set()
                fetched_total_checks += 1
                if py_csv == "":
                    # correct only if no available years
                    if not exp_years:
                        fetched_correct += 1
                else:
                    try:
                        py_val = int(py_csv)
                        if not exp_years or py_val in exp_years:
                            fetched_correct += 1
                    except Exception:
                        # malformed year string
                        pass

                # Number of pages
                nop_csv = (r.get("number_of_pages") or "").strip()
                exp_nop = payload.get("number_of_pages") if payload else None
                fetched_total_checks += 1
                if nop_csv == "":
                    if exp_nop is None:
                        fetched_correct += 1
                else:
                    try:
                        nop_val = int(nop_csv)
                        if exp_nop is not None and nop_val == int(exp_nop):
                            fetched_correct += 1
                    except Exception:
                        pass

                # Publishers
                pub_csv = (r.get("publishers") or "").strip()
                pub_csv_list = _split_semicolons(pub_csv)
                exp_publishers = payload.get("publishers") if payload else []
                fetched_total_checks += 1
                if _publishers_equal(pub_csv_list, exp_publishers):
                    fetched_correct += 1

                # Cover image path consistency
                cover_path_total += 1
                cip = (r.get("cover_image_path") or "").strip()
                covers = _cover_files_for_isbn(workspace, isbn)
                if covers:
                    # Must have a relative path under assets/covers exactly pointing to one of the files
                    valid_paths = {str(Path("assets") / "covers" / covers[i].name) for i in range(len(covers))}
                    if cip in valid_paths:
                        cover_path_correct += 1
                else:
                    # If no cover present, field should be blank
                    if cip == "":
                        cover_path_correct += 1

                # Source field
                source_total += 1
                src = (r.get("source") or "").strip()
                if src == "Open Library":
                    source_correct += 1

                # Match confidence
                match_conf_total += 1
                mc = (r.get("match_confidence") or "").strip()
                input_title = input_by_isbn[isbn]["title"]
                if ft_csv:
                    n_input = _normalize_title(input_title)
                    n_ft = _normalize_title(ft_csv)
                    exp_mc = "exact_title" if n_input == n_ft else "other"
                else:
                    exp_mc = "other"
                if mc == exp_mc:
                    match_conf_correct += 1

        # Assign scores
        scores["fetched_fields_consistency"] = (fetched_correct / fetched_total_checks) if fetched_total_checks else 0.0
        scores["cover_image_path_consistency"] = (cover_path_correct / cover_path_total) if cover_path_total else 0.0
        scores["source_field_correct"] = (source_correct / source_total) if source_total else 0.0
        scores["match_confidence_correct"] = (match_conf_correct / match_conf_total) if match_conf_total else 0.0

        # arcs_summary correctness
        arcs_summary_path = workspace / "data" / "processed" / "arcs_summary.json"
        arcs_summary = _safe_load_json_file(arcs_summary_path)
        # Build expected from processed CSV (if available), else from input (with limited fields)
        expected_map: Dict[str, Dict[str, Any]] = {}
        if processed_rows:
            for r in processed_rows:
                arc = (r.get("arc_name") or "").strip()
                if not arc:
                    continue
                canon = (r.get("canon_or_legends") or "").strip()
                nop = (r.get("number_of_pages") or "").strip()
                pages_val = None
                try:
                    pages_val = int(nop) if nop != "" else None
                except Exception:
                    pages_val = None
                if arc not in expected_map:
                    expected_map[arc] = {
                        "canon_or_legends": canon,
                        "book_count": 0,
                        "total_pages_available": 0,
                        "is_trilogy": False,
                    }
                expected_map[arc]["book_count"] += 1
                if pages_val is not None:
                    expected_map[arc]["total_pages_available"] += pages_val
            for arc in list(expected_map.keys()):
                expected_map[arc]["is_trilogy"] = expected_map[arc]["book_count"] == 3
        elif seed_rows:
            # Fallback: compute counts from input (pages sum will be 0)
            for r in seed_rows:
                arc = (r.get("arc_name") or "").strip()
                canon = (r.get("canon_or_legends") or "").strip()
                if arc not in expected_map:
                    expected_map[arc] = {
                        "canon_or_legends": canon,
                        "book_count": 0,
                        "total_pages_available": 0,
                        "is_trilogy": False,
                    }
                expected_map[arc]["book_count"] += 1
            for arc in list(expected_map.keys()):
                expected_map[arc]["is_trilogy"] = expected_map[arc]["book_count"] == 3

        if isinstance(arcs_summary, dict) and expected_map:
            # Compare keys exact
            arcs = sorted(expected_map.keys())
            as_keys = sorted(arcs_summary.keys())
            if arcs == as_keys:
                correct_arcs = 0
                for arc in arcs:
                    rec = arcs_summary.get(arc, {})
                    if not isinstance(rec, dict):
                        continue
                    canon = rec.get("canon_or_legends")
                    bc = rec.get("book_count")
                    tpa = rec.get("total_pages_available")
                    it = rec.get("is_trilogy")
                    try:
                        # Coerce types
                        bc_i = int(bc)
                        tpa_i = int(tpa)
                        it_b = True if it is True or (isinstance(it, str) and it.lower() in {"true", "1"}) else False
                    except Exception:
                        continue
                    if (str(canon) == expected_map[arc]["canon_or_legends"]
                        and bc_i == expected_map[arc]["book_count"]
                        and tpa_i == expected_map[arc]["total_pages_available"]
                        and it_b == expected_map[arc]["is_trilogy"]):
                        correct_arcs += 1
                if arcs:
                    scores["arcs_summary_correct"] = correct_arcs / len(arcs)
                else:
                    scores["arcs_summary_correct"] = 0.0
            else:
                scores["arcs_summary_correct"] = 0.0
        else:
            scores["arcs_summary_correct"] = 0.0

        # Missing logs check
        logs_dir = workspace / "logs"
        missing_log_path = logs_dir / "missing.txt"
        missing_isbns: Set[str] = set()
        for isbn in isbns:
            jf = raw_dir / f"{isbn}.json"
            covers = _cover_files_for_isbn(workspace, isbn)
            if (not jf.exists()) or (not covers):
                missing_isbns.add(isbn)

        if not missing_isbns:
            # If nothing missing, accept as correct even if file absent or empty
            scores["missing_log_covers_and_json"] = 1.0
        else:
            # Need to ensure missing.txt exists and includes all missing ISBNs
            if missing_log_path.exists():
                text = _safe_read_text(missing_log_path) or ""
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                found_isbns = set()
                for ln in lines:
                    # Extract ISBN-like 13-digit numbers
                    m = re.findall(r"\b\d{13}\b", ln)
                    for tok in m:
                        found_isbns.add(tok)
                covered = len([i for i in missing_isbns if i in found_isbns])
                scores["missing_log_covers_and_json"] = covered / len(missing_isbns) if missing_isbns else 1.0
            else:
                scores["missing_log_covers_and_json"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()