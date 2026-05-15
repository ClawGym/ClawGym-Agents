import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


EXPECTED_SUMMARY_HEADER = [
    "batch_id",
    "input_file",
    "theme",
    "page_index",
    "source_url",
    "source_domain",
    "local_html_path",
    "local_text_path",
    "html_sha256",
    "text_word_count",
    "retrieved_at_iso",
    "search_results_html_path",
]

ALLOWED_DOMAIN_SUFFIXES = [
    "gov.uk",
    "justice.gov.uk",
    "parliament.uk",
    "justiceinspectorates.gov.uk",
    "police.uk",
    "nhs.uk",
]


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        content = _safe_read_text(path)
        if content is None:
            return None
        return json.loads(content)
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


def _is_iso_datetime(val: str) -> bool:
    if not isinstance(val, str) or not val:
        return False
    try:
        v = val.replace("Z", "+00:00") if val.endswith("Z") else val
        datetime.fromisoformat(v)
        return True
    except Exception:
        return False


def _count_words_in_file(path: Path) -> Optional[int]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        words = text.split()
        return len(words)
    except Exception:
        return None


def _parse_csv_strict(path: Path) -> Tuple[bool, Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return (False, None)
            if header != EXPECTED_SUMMARY_HEADER:
                return (False, None)
        with path.open("r", encoding="utf-8", newline="") as f:
            dict_reader = csv.DictReader(f)
            # Ensure DictReader field order matches expected
            if list(dict_reader.fieldnames or []) != EXPECTED_SUMMARY_HEADER:
                return (False, None)
            rows: List[Dict[str, str]] = []
            for row in dict_reader:
                rows.append(row)
            return (True, rows)
    except Exception:
        return (False, None)


def _themes_from_input(path: Path) -> Optional[List[str]]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        lines = [ln.strip() for ln in text.splitlines()]
        themes = [ln for ln in lines if ln.strip() != ""]
        return themes
    except Exception:
        return None


def _normalize_domain(d: str) -> str:
    d = (d or "").strip().lower()
    if d.startswith("www."):
        d = d[4:]
    return d


def _path_from_string(workspace: Path, p: str) -> Path:
    try:
        ps = (p or "").strip()
        p_obj = Path(ps)
        if p_obj.is_absolute():
            return p_obj
        return (workspace / p_obj).resolve()
    except Exception:
        return (workspace / (p or "")).resolve()


def _endswith_pathlike(value: str, tail: str) -> bool:
    if not isinstance(value, str):
        return False
    v = value.replace("\\", "/").lower()
    t = tail.replace("\\", "/").lower()
    return v.endswith(t)


def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        child_resolved = child.resolve()
        parent_resolved = parent.resolve()
        return str(child_resolved).startswith(str(parent_resolved) + str(Path("/")))
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "batch_dir_exists": 0.0,
        "subdirs_exist": 0.0,
        "state_file_valid_for_batch": 0.0,
        "search_dir_has_one_html_per_theme": 0.0,
        "summary_csv_header_valid": 0.0,
        "summary_rows_equal_text_files": 0.0,
        "summary_paths_exist_fraction": 0.0,
        "summary_html_sha256_match_fraction": 0.0,
        "summary_text_word_count_match_fraction": 0.0,
        "retrieved_at_iso_valid_fraction": 0.0,
        "source_domain_allowed_and_matches_url_fraction": 0.0,
        "per_theme_max_three_pages_and_indices_valid": 0.0,
        "batch_and_input_fields_correct_fraction": 0.0,
        "search_results_paths_exist_in_rows_fraction": 0.0,
        "log_present_when_themes_without_pages": 0.0,
        "watcher_script_present": 0.0,
    }

    # Expected batch and input
    batch_id = "seed_queries"
    input_file_rel = "watch/seed_queries.txt"
    input_file_path = workspace / input_file_rel

    # Load themes; if file missing or unreadable, None
    themes_opt = _themes_from_input(input_file_path)
    themes: List[str] = themes_opt if themes_opt is not None else []

    # Paths
    outputs_dir = workspace / "outputs"
    batch_dir = outputs_dir / batch_id
    search_dir = batch_dir / "search"
    pages_dir = batch_dir / "pages"
    text_dir = batch_dir / "text"
    summary_csv = batch_dir / "summary.csv"
    log_path = batch_dir / "log.txt"
    state_file = outputs_dir / "state" / "processed_batches.json"

    # Directory structure checks
    if batch_dir.is_dir():
        scores["batch_dir_exists"] = 1.0
    if all([search_dir.is_dir(), pages_dir.is_dir(), text_dir.is_dir()]):
        scores["subdirs_exist"] = 1.0

    # State file validation: accept reasonable schema variants
    state_ok = 0.0
    if state_file.is_file():
        data = _load_json(state_file)
        entries: List[Dict[str, Any]] = []
        if isinstance(data, list):
            entries = [e for e in data if isinstance(e, dict)]
        elif isinstance(data, dict):
            for key in ("batches", "processed", "entries", "items"):
                if key in data and isinstance(data[key], list):
                    entries = [e for e in data[key] if isinstance(e, dict)]
                    break
            if not entries and all(isinstance(v, dict) for v in data.values()):
                entries = list(data.values())
        # function to get theme count from an entry
        def _get_theme_count(e: Dict[str, Any]) -> Optional[int]:
            for k in ("themes_count", "theme_count", "themes_processed", "themes_len", "count", "num_themes"):
                v = e.get(k)
                if isinstance(v, int):
                    return v
            return None
        found = False
        for e in entries:
            bid = e.get("batch_id")
            # input_file may be under various keys; try common ones
            ip = e.get("input_file") or e.get("input_path") or e.get("source_input") or e.get("input")
            processed_at = e.get("processed_at") or e.get("processed_at_iso") or e.get("timestamp")
            themes_count = _get_theme_count(e)
            if bid == batch_id and _endswith_pathlike(str(ip or ""), input_file_rel):
                if _is_iso_datetime(str(processed_at or "")) and isinstance(themes_count, int):
                    if themes_opt is not None and themes_count == len(themes):
                        found = True
                        break
        state_ok = 1.0 if found else 0.0
    scores["state_file_valid_for_batch"] = state_ok

    # Search dir has one html per theme (only if themes are known)
    search_ok = 0.0
    if themes_opt is not None and search_dir.is_dir():
        html_files = [p for p in search_dir.glob("*.html") if p.is_file()]
        if len(html_files) == len(themes) and len(themes) > 0:
            search_ok = 1.0
    scores["search_dir_has_one_html_per_theme"] = search_ok

    # Summary CSV parsing and structure
    header_ok, rows = _parse_csv_strict(summary_csv) if summary_csv.is_file() else (False, None)
    scores["summary_csv_header_valid"] = 1.0 if header_ok else 0.0
    if not header_ok or rows is None:
        rows = []

    # Summary rows equal text files count (only award if any items exist)
    text_files_count = 0
    if text_dir.is_dir():
        text_files_count = len([p for p in text_dir.glob("*.txt") if p.is_file()])
    if (len(rows) > 0 or text_files_count > 0) and len(rows) == text_files_count:
        scores["summary_rows_equal_text_files"] = 1.0

    # Paths existence fraction and other per-row validations
    total_rows = len(rows)
    if total_rows > 0:
        paths_ok_count = 0
        hashes_ok_count = 0
        words_ok_count = 0
        retrieved_iso_ok_count = 0
        source_domain_ok_count = 0
        batch_input_ok_count = 0
        search_results_ref_ok_count = 0

        for r in rows:
            # Resolve paths
            local_html_str = r.get("local_html_path", "")
            local_text_str = r.get("local_text_path", "")
            search_results_html_str = r.get("search_results_html_path", "")

            local_html_path = _path_from_string(workspace, local_html_str)
            local_text_path = _path_from_string(workspace, local_text_str)
            search_results_html_path = _path_from_string(workspace, search_results_html_str)

            html_exists = local_html_path.is_file()
            text_exists = local_text_path.is_file()
            search_exists = search_results_html_path.is_file()
            # Also ensure files are under expected batch subdirs
            pages_under_correct = html_exists and _is_subpath(local_html_path, pages_dir)
            text_under_correct = text_exists and _is_subpath(local_text_path, text_dir)
            search_under_correct = search_exists and _is_subpath(search_results_html_path, search_dir)
            if pages_under_correct and text_under_correct and search_under_correct:
                paths_ok_count += 1

            # Hash check
            expected_sha = r.get("html_sha256", "")
            actual_sha = _sha256_file(local_html_path) if html_exists else None
            if actual_sha is not None and isinstance(expected_sha, str) and expected_sha == actual_sha:
                hashes_ok_count += 1

            # Word count check
            wc_str = r.get("text_word_count", "")
            try:
                expected_wc = int(wc_str)
            except Exception:
                expected_wc = None
            actual_wc = _count_words_in_file(local_text_path) if text_exists else None
            if expected_wc is not None and actual_wc is not None and expected_wc == actual_wc:
                words_ok_count += 1

            # retrieved_at_iso
            if _is_iso_datetime(str(r.get("retrieved_at_iso", ""))):
                retrieved_iso_ok_count += 1

            # source domain vs url and allowed suffix
            src_url = r.get("source_url", "")
            src_domain = _normalize_domain(str(r.get("source_domain", "")))
            try:
                parsed = urlparse(src_url)
                netloc = parsed.netloc.lower()
                netloc_norm = netloc[4:] if netloc.startswith("www.") else netloc
                suffix_ok = any(netloc_norm.endswith(sfx) for sfx in ALLOWED_DOMAIN_SUFFIXES)
                domain_match = (src_domain == netloc_norm)
                if suffix_ok and domain_match:
                    source_domain_ok_count += 1
            except Exception:
                pass

            # batch_id and input_file correctness
            bid = r.get("batch_id", "")
            ip = r.get("input_file", "")
            bid_ok = (bid == batch_id)
            ip_ok = _endswith_pathlike(str(ip), input_file_rel)
            if bid_ok and ip_ok:
                batch_input_ok_count += 1

            # search results html referenced exists and under search dir
            if search_under_correct:
                search_results_ref_ok_count += 1

        scores["summary_paths_exist_fraction"] = paths_ok_count / total_rows if total_rows else 0.0
        scores["summary_html_sha256_match_fraction"] = hashes_ok_count / total_rows if total_rows else 0.0
        scores["summary_text_word_count_match_fraction"] = words_ok_count / total_rows if total_rows else 0.0
        scores["retrieved_at_iso_valid_fraction"] = retrieved_iso_ok_count / total_rows if total_rows else 0.0
        scores["source_domain_allowed_and_matches_url_fraction"] = source_domain_ok_count / total_rows if total_rows else 0.0
        scores["batch_and_input_fields_correct_fraction"] = batch_input_ok_count / total_rows if total_rows else 0.0
        scores["search_results_paths_exist_in_rows_fraction"] = search_results_ref_ok_count / total_rows if total_rows else 0.0

    # Per-theme constraints: at most 3 pages per theme and valid indices 1..3
    if rows and len(rows) > 0:
        per_theme_ok = True
        theme_to_rows: Dict[str, List[Dict[str, str]]] = {}
        for r in rows:
            theme_to_rows.setdefault(r.get("theme", ""), []).append(r)
        for _, rlist in theme_to_rows.items():
            if len(rlist) > 3:
                per_theme_ok = False
                break
            for r in rlist:
                try:
                    pi = int(r.get("page_index", ""))
                    if pi < 1 or pi > 3:
                        per_theme_ok = False
                        break
                except Exception:
                    per_theme_ok = False
                    break
            if not per_theme_ok:
                break
        scores["per_theme_max_three_pages_and_indices_valid"] = 1.0 if per_theme_ok else 0.0
    else:
        scores["per_theme_max_three_pages_and_indices_valid"] = 0.0

    # Log presence when themes without pages: only evaluate if themes are known
    if themes_opt is not None and len(themes) > 0:
        themes_with_rows = set([r.get("theme", "") for r in rows]) if rows else set()
        missing_themes = [t for t in themes if t not in themes_with_rows]
        if missing_themes:
            scores["log_present_when_themes_without_pages"] = 1.0 if log_path.is_file() else 0.0
        else:
            scores["log_present_when_themes_without_pages"] = 1.0 if (batch_dir.is_dir() and log_path.exists() or True) else 1.0
    else:
        # Cannot evaluate without known themes
        scores["log_present_when_themes_without_pages"] = 0.0

    # Watcher script presence: detect any .py file referencing watch/ or state path
    watcher_detected = False
    patterns = [
        "watch/",
        "watch\\",
        "outputs/state/processed_batches.json",
        "processed_batches.json",
        "outputs/state",
    ]
    for py in workspace.rglob("*.py"):
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if any(pat in content for pat in patterns):
            watcher_detected = True
            break
    scores["watcher_script_present"] = 1.0 if watcher_detected else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()