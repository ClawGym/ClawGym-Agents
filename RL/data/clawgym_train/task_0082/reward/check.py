import csv
import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            return path.read_text(encoding="latin-1", errors="replace")
        except Exception:
            return None


def _safe_file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except Exception:
        return 0


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict]]:
    try:
        records: List[Dict] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        return None
                    records.append(obj)
                except Exception:
                    return None
        return records
    except Exception:
        return None


def _parse_int(value) -> Optional[int]:
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                return None
            return int(value)
        return None
    except Exception:
        return None


def _is_iso_date(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _hostname_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if host is None:
            return None
        return host.lower()
    except Exception:
        return None


def _endswith_any(text: str, suffixes: List[str]) -> bool:
    t = text.lower()
    for s in suffixes:
        if t.endswith(s.lower()):
            return True
    return False


class _VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._texts: List[str] = []
        self._skip_stack: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "noscript", "head"):
            self._skip_stack.append(tag.lower())

    def handle_endtag(self, tag):
        if self._skip_stack and self._skip_stack[-1] == tag.lower():
            self._skip_stack.pop()

    def handle_data(self, data):
        if not self._skip_stack:
            if data and data.strip():
                self._texts.append(data.strip())

    def get_text(self) -> str:
        return " ".join(self._texts)


def _extract_visible_text_from_html(html: str) -> str:
    parser = _VisibleTextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    return parser.get_text()


def _parse_bool_cell(value: str) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in ("true", "t", "yes", "y", "1"):
        return True
    if v in ("false", "f", "no", "n", "0"):
        return False
    return None


def _compute_word_count_from_snapshot(snapshot_path: Path) -> Optional[int]:
    try:
        suffix = snapshot_path.suffix.lower()
        if suffix in (".pdf",):
            # For PDFs, per spec the prototype may set word count to 0 if text extraction isn't reliable.
            return 0
        if suffix not in (".html", ".htm"):
            return None
        txt = _safe_read_text(snapshot_path)
        if txt is None:
            return None
        visible = _extract_visible_text_from_html(txt)
        words = re.findall(r"\S+", visible)
        return len(words)
    except Exception:
        return None


def _compute_contains_year(snapshot_path: Path) -> Optional[bool]:
    try:
        suffix = snapshot_path.suffix.lower()
        if suffix in (".pdf",):
            # Assume no reliable extraction; treat as not containing a year.
            return False
        if suffix not in (".html", ".htm"):
            return None
        txt = _safe_read_text(snapshot_path)
        if txt is None:
            return None
        visible = _extract_visible_text_from_html(txt)
        current_year = datetime.now().year
        pattern = re.compile(r"\b(19[9]\d|20\d{2})\b")
        years = pattern.findall(visible)
        for y in years:
            try:
                yi = int(y)
                if 1990 <= yi <= current_year:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "sources_jsonl_present_parseable": 0.0,
        "sources_one_entry_per_intervention": 0.0,
        "sources_required_fields_complete": 0.0,
        "sources_org_name_allowed": 0.0,
        "sources_domain_matches_allowed_hints": 0.0,
        "sources_url_domain_consistent": 0.0,
        "snapshots_exist_and_nonempty": 0.0,
        "summary_csv_present_and_rowcount_match": 0.0,
        "summary_contains_required_columns": 0.0,
        "summary_values_match_sources": 0.0,
        "summary_local_word_count_correct": 0.0,
        "summary_contains_year_correct": 0.0,
        "validator_files_present": 0.0,
        "validator_run_passed": 0.0,
        "validation_report_json_parseable": 0.0,
        "status_report_present": 0.0,
        "status_includes_queries_per_intervention": 0.0,
        "status_includes_file_inventory_sizes": 0.0,
        "status_mentions_limitations_and_next_steps": 0.0,
    }

    # Load inputs
    interventions_csv = workspace / "input" / "interventions.csv"
    allowed_sources_csv = workspace / "input" / "allowed_sources.csv"

    interventions = _read_csv_rows(interventions_csv) or []
    allowed_sources = _read_csv_rows(allowed_sources_csv) or []

    expected_ids: List[int] = []
    expected_labels: Dict[int, str] = {}
    expected_queries: Dict[int, str] = {}
    for row in interventions:
        iid = _parse_int(row.get("intervention_id"))
        if iid is None:
            continue
        expected_ids.append(iid)
        expected_labels[iid] = (row.get("intervention_label") or "").strip()
        expected_queries[iid] = (row.get("search_query") or "").strip()
    expected_ids_set = set(expected_ids)

    allowed_map: Dict[str, List[str]] = {}
    for row in allowed_sources:
        org = (row.get("org_name") or "").strip()
        hint = (row.get("domain_hint") or "").strip()
        if org and hint:
            allowed_map[org] = [h.strip() for h in hint.split("|") if h.strip()]

    # Load sources.jsonl
    sources_path = workspace / "data" / "metadata" / "sources.jsonl"
    sources_records = _load_jsonl(sources_path)
    if sources_records is not None:
        scores["sources_jsonl_present_parseable"] = 1.0

    # Build map by intervention_id
    sources_by_id: Dict[int, Dict] = {}
    duplicates: set = set()
    if sources_records:
        for rec in sources_records:
            iid = _parse_int(rec.get("intervention_id"))
            if iid is None:
                continue
            if iid in sources_by_id:
                duplicates.add(iid)
            else:
                sources_by_id[iid] = rec

    # Check exactly one entry per intervention_id
    if expected_ids and sources_records is not None:
        if len(sources_records) == len(expected_ids) and not duplicates and expected_ids_set == set(sources_by_id.keys()):
            scores["sources_one_entry_per_intervention"] = 1.0

    # Required fields complete
    required_fields = [
        "intervention_id",
        "intervention_label",
        "chosen_source_org",
        "source_url",
        "source_domain",
        "page_title",
        "retrieved_on",
        "snapshot_path",
    ]
    complete_count = 0
    total_count = len(expected_ids)
    org_allowed_count = 0
    domain_allowed_count = 0
    url_domain_consistent_count = 0
    snapshots_ok_count = 0

    for iid in expected_ids:
        rec = sources_by_id.get(iid)
        if not rec:
            continue
        # fields present
        has_all = all(k in rec for k in required_fields)
        # Validate each field
        label_ok = (rec.get("intervention_label") or "").strip() == expected_labels.get(iid, "")
        chosen_org = (rec.get("chosen_source_org") or "").strip()
        source_url = (rec.get("source_url") or "").strip()
        source_domain = (rec.get("source_domain") or "").strip()
        page_title = (rec.get("page_title") or "").strip()
        retrieved_on = (rec.get("retrieved_on") or "").strip()
        snapshot_rel = (rec.get("snapshot_path") or "").strip()

        # Individual validations
        iid_ok = _parse_int(rec.get("intervention_id")) == iid
        url_ok = bool(_hostname_from_url(source_url))
        domain_ok = bool(re.fullmatch(r"[A-Za-z0-9.-]+", source_domain)) and "." in source_domain
        title_ok = len(page_title) > 0
        date_ok = _is_iso_date(retrieved_on)
        snap_ok = snapshot_rel and not snapshot_rel.startswith(("http://", "https://")) and snapshot_rel.startswith("data/raw/") and (snapshot_rel.lower().endswith(".html") or snapshot_rel.lower().endswith(".htm") or snapshot_rel.lower().endswith(".pdf"))
        snap_path = workspace / snapshot_rel if snap_ok else None
        snap_exists = snap_path.exists() and _safe_file_size(snap_path) > 0 if snap_path else False

        if has_all and iid_ok and label_ok and url_ok and domain_ok and title_ok and date_ok and snap_ok:
            complete_count += 1

        # org allowed
        if chosen_org in allowed_map:
            org_allowed_count += 1

        # domain match allowed hints
        if chosen_org in allowed_map and source_domain:
            if _endswith_any(source_domain, allowed_map[chosen_org]):
                domain_allowed_count += 1

        # url vs domain consistency
        url_host = _hostname_from_url(source_url)
        if url_host and source_domain:
            if url_host == source_domain or url_host.endswith("." + source_domain) or source_domain.endswith("." + url_host):
                url_domain_consistent_count += 1

        # snapshots exist and non-empty
        if snap_exists:
            snapshots_ok_count += 1

    if total_count > 0:
        scores["sources_required_fields_complete"] = complete_count / total_count
        scores["sources_org_name_allowed"] = org_allowed_count / total_count
        scores["sources_domain_matches_allowed_hints"] = domain_allowed_count / total_count
        scores["sources_url_domain_consistent"] = url_domain_consistent_count / total_count
        scores["snapshots_exist_and_nonempty"] = snapshots_ok_count / total_count

    # Summary CSV checks
    summary_path = workspace / "data" / "digest" / "interventions_summary.csv"
    summary_rows = _read_csv_rows(summary_path)
    if summary_rows is not None:
        scores["summary_csv_present_and_rowcount_match"] = 1.0 if len(summary_rows) == len(expected_ids) else 0.0

    required_summary_cols = [
        "intervention_id",
        "chosen_source_org",
        "page_title",
        "retrieved_on",
        "source_domain",
        "local_word_count",
        "contains_year",
    ]
    if summary_rows:
        header_ok = all(col in summary_rows[0] for col in required_summary_cols)
        scores["summary_contains_required_columns"] = 1.0 if header_ok else 0.0

    # Build summary map by id
    summary_by_id: Dict[int, Dict[str, str]] = {}
    if summary_rows:
        for r in summary_rows:
            iid = _parse_int(r.get("intervention_id"))
            if iid is not None:
                summary_by_id[iid] = r

    # Compare summary values to sources
    match_values_count = 0
    wordcount_match_count = 0
    contains_year_match_count = 0
    for iid in expected_ids:
        src = sources_by_id.get(iid)
        summ = summary_by_id.get(iid)
        if not src or not summ:
            continue
        # Field matches
        fields_equal = True
        for field in ["chosen_source_org", "page_title", "retrieved_on", "source_domain"]:
            src_val = (src.get(field) or "").strip()
            sum_val = (summ.get(field) or "").strip()
            if src_val != sum_val:
                fields_equal = False
                break
        if fields_equal:
            match_values_count += 1

        # Word count correctness
        snap_rel = (src.get("snapshot_path") or "").strip()
        snap_path = workspace / snap_rel if snap_rel else None
        computed_wc = _compute_word_count_from_snapshot(snap_path) if snap_path and snap_path.exists() else None
        sum_wc_raw = summ.get("local_word_count")
        sum_wc = None
        try:
            if isinstance(sum_wc_raw, str):
                sum_wc = int(sum_wc_raw.strip())
            elif isinstance(sum_wc_raw, (int, float)):
                sum_wc = int(sum_wc_raw)
        except Exception:
            sum_wc = None
        if computed_wc is not None and sum_wc is not None and sum_wc == computed_wc:
            wordcount_match_count += 1

        # contains_year correctness
        computed_year = _compute_contains_year(snap_path) if snap_path and snap_path.exists() else None
        sum_contains_year = _parse_bool_cell(summ.get("contains_year"))
        if computed_year is not None and sum_contains_year is not None and bool(sum_contains_year) == bool(computed_year):
            contains_year_match_count += 1

    if expected_ids:
        scores["summary_values_match_sources"] = match_values_count / len(expected_ids)
        scores["summary_local_word_count_correct"] = wordcount_match_count / len(expected_ids)
        scores["summary_contains_year_correct"] = contains_year_match_count / len(expected_ids)

    # Validator files
    validator_py = workspace / "tests" / "validate.py"
    validate_run_txt = workspace / "tests" / "validate_run.txt"
    validation_report_json = workspace / "tests" / "validation_report.json"
    if validator_py.exists():
        scores["validator_files_present"] = 1.0
    # Validate run output
    run_txt = _safe_read_text(validate_run_txt) if validate_run_txt.exists() else None
    if isinstance(run_txt, str) and "VALIDATION PASSED" in run_txt:
        scores["validator_run_passed"] = 1.0
    # Validation report parseable
    try:
        if validation_report_json.exists():
            with validation_report_json.open("r", encoding="utf-8") as f:
                json.load(f)
            scores["validation_report_json_parseable"] = 1.0
    except Exception:
        pass

    # Status report checks
    status_md = workspace / "report" / "status.md"
    status_text = _safe_read_text(status_md) if status_md.exists() else None
    if status_text is not None:
        scores["status_report_present"] = 1.0

    # Queries per intervention in the report
    if status_text and expected_ids:
        present = 0
        lowtext = status_text.lower()
        for iid in expected_ids:
            q = expected_queries.get(iid, "")
            if q and q.lower() in lowtext:
                present += 1
        scores["status_includes_queries_per_intervention"] = present / len(expected_ids) if expected_ids else 0.0

    # File inventory with sizes
    if status_text:
        # Determine expected created files
        expected_files: List[Path] = []
        # snapshots from sources.jsonl
        if sources_by_id:
            for iid in expected_ids:
                rec = sources_by_id.get(iid)
                if not rec:
                    continue
                snap_rel = (rec.get("snapshot_path") or "").strip()
                if snap_rel:
                    expected_files.append(workspace / snap_rel)
        # fixed targets
        expected_files.extend([
            workspace / "data" / "metadata" / "sources.jsonl",
            workspace / "data" / "digest" / "interventions_summary.csv",
            workspace / "tests" / "validate.py",
            workspace / "tests" / "validation_report.json",
            workspace / "tests" / "validate_run.txt",
        ])
        # Only consider files that exist, as the report should list created files
        existing_files = [p for p in expected_files if p.exists()]
        if existing_files:
            count_ok = 0
            for p in existing_files:
                rel_str = str(p.relative_to(workspace).as_posix())
                size = _safe_file_size(p)
                if rel_str in status_text and str(size) in status_text:
                    count_ok += 1
            scores["status_includes_file_inventory_sizes"] = count_ok / len(existing_files) if existing_files else 0.0

    # Limitations and next steps
    if status_text:
        low = status_text.lower()
        has_limitations = ("limitation" in low) or ("parsing" in low)
        has_next_steps = ("next steps" in low) or ("next step" in low)
        scores["status_mentions_limitations_and_next_steps"] = 1.0 if (has_limitations and has_next_steps) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()