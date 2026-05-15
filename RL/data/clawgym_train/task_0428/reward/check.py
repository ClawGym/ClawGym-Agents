import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return None
                records.append(obj)
        return records
    except Exception:
        return None


def _is_valid_date(date_str: str) -> bool:
    if not isinstance(date_str, str):
        return False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()) if isinstance(s, str) else s


def _split_contributions(s: str) -> List[str]:
    if not isinstance(s, str):
        return []
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p]


def _parse_plain_text_labels(text: str) -> Optional[Dict[str, Any]]:
    lines = [ln.strip() for ln in text.splitlines()]
    data: Dict[str, str] = {}
    mapping = {
        "interviewee:": "interviewee_name",
        "interview date:": "interview_date",
        "birthplace:": "birthplace",
        "occupation:": "occupation",
        "key contributions:": "contributions",
        "summary:": "summary",
    }
    for ln in lines:
        if ":" in ln:
            key_part = ln.split(":", 1)[0].strip().lower() + ":"
            val_part = ln.split(":", 1)[1].strip()
            if key_part in mapping:
                data[mapping[key_part]] = val_part
    required = ["interviewee_name", "interview_date", "birthplace", "occupation", "contributions", "summary"]
    if not all(k in data and data[k].strip() for k in required):
        return None
    rec: Dict[str, Any] = {
        "interviewee_name": _normalize_spaces(data["interviewee_name"]),
        "interview_date": data["interview_date"].strip(),
        "birthplace": _normalize_spaces(data["birthplace"]),
        "occupation": _normalize_spaces(data["occupation"]),
        "contributions": _split_contributions(data["contributions"]),
        "summary": _normalize_spaces(data["summary"]),
    }
    return rec


def _extract_meta_content(html: str, name: str) -> Optional[str]:
    meta_pattern = re.compile(
        r'<meta\b[^>]*\bname=["\']' + re.escape(name) + r'["\'][^>]*\bcontent=["\'](.*?)["\']',
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = meta_pattern.search(html)
    if m:
        return _normalize_spaces(m.group(1))
    return None


def _extract_p_summary(html: str) -> Optional[str]:
    m = re.search(r'<p\b[^>]*class=["\']summary["\'][^>]*>(.*?)</p>', html, flags=re.IGNORECASE | re.DOTALL)
    if m:
        content = m.group(1)
        content = re.sub(r"<[^>]+>", " ", content)
        return _normalize_spaces(content)
    return None


def _parse_html_meta(text: str) -> Optional[Dict[str, Any]]:
    interviewee = _extract_meta_content(text, "interviewee")
    interview_date = _extract_meta_content(text, "interview_date")
    birthplace = _extract_meta_content(text, "birthplace")
    occupation = _extract_meta_content(text, "occupation")
    contributions_raw = _extract_meta_content(text, "contributions")
    summary = _extract_p_summary(text)
    if not all([interviewee, interview_date, birthplace, occupation, contributions_raw, summary]):
        return None
    rec: Dict[str, Any] = {
        "interviewee_name": interviewee,
        "interview_date": interview_date,
        "birthplace": birthplace,
        "occupation": occupation,
        "contributions": _split_contributions(contributions_raw),
        "summary": summary,
    }
    return rec


def _extract_dl_value(html: str, term: str) -> Optional[str]:
    pattern = re.compile(
        r"<dt>\s*" + re.escape(term) + r"\s*</dt>\s*<dd>\s*(.*?)\s*</dd>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(html)
    if m:
        content = m.group(1)
        content = re.sub(r"<[^>]+>", " ", content)
        return _normalize_spaces(content)
    return None


def _parse_html_dl(text: str) -> Optional[Dict[str, Any]]:
    interviewee = _extract_dl_value(text, "Interviewee")
    interview_date = _extract_dl_value(text, "Interview Date")
    birthplace = _extract_dl_value(text, "Birthplace")
    occupation = _extract_dl_value(text, "Occupation")
    contributions_raw = _extract_dl_value(text, "Key Contributions")
    summary = _extract_p_summary(text)
    if not all([interviewee, interview_date, birthplace, occupation, contributions_raw, summary]):
        return None
    rec: Dict[str, Any] = {
        "interviewee_name": interviewee,
        "interview_date": interview_date,
        "birthplace": birthplace,
        "occupation": occupation,
        "contributions": _split_contributions(contributions_raw),
        "summary": summary,
    }
    return rec


def _parse_transcript_file(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    if path.suffix.lower() == ".txt":
        return _parse_plain_text_labels(text)
    elif path.suffix.lower() == ".html":
        rec = _parse_html_meta(text)
        if rec is not None:
            return rec
        return _parse_html_dl(text)
    else:
        return None


def _list_transcript_files(incoming_dir: Path) -> List[Path]:
    files: List[Path] = []
    if not incoming_dir.exists():
        return []
    for p in sorted(incoming_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in {".txt", ".html"}:
            files.append(p)
    return files


def _normalize_rel_path(path: Path, workspace: Path) -> str:
    try:
        rel = path.relative_to(workspace)
    except Exception:
        rel = Path(str(path))
    return str(rel).replace("\\", "/")


def _parse_run_log_lines(path: Path) -> List[Tuple[str, str, str]]:
    entries: List[Tuple[str, str, str]] = []
    if not path.exists():
        return entries
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                m = re.match(r"^(\d{4}-\d{2}-\d{2}T[0-9:\.\+\-Z]+)\s+(added|updated)\s+([A-Za-z0-9._\-]+)", s, flags=re.IGNORECASE)
                if m:
                    ts = m.group(1)
                    action = m.group(2).lower()
                    _id = m.group(3)
                    entries.append((ts, action, _id))
    except Exception:
        return []
    return entries


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    incoming_dir = workspace / "input" / "incoming"
    output_dir = workspace / "output"
    interviews_jsonl = output_dir / "interviews.jsonl"
    run_log = output_dir / "run.log"
    validation_report = output_dir / "validation_report.txt"

    scores: Dict[str, float] = {
        "interviews_jsonl_exists": 0.0,
        "interviews_jsonl_parseable": 0.0,
        "interviews_jsonl_unique_ids": 0.0,
        "records_count_matches_incoming": 0.0,
        "ids_match_filenames": 0.0,
        "fields_presence_and_nonempty": 0.0,
        "interview_dates_valid_format": 0.0,
        "source_paths_correct": 0.0,
        "content_extraction_matches_sources": 0.0,
        "run_log_exists": 0.0,
        "run_log_has_entries_for_all_ids": 0.0,
        "run_log_entries_valid_format": 0.0,
        "validation_report_exists": 0.0,
        "validation_report_indicates_success": 0.0,
    }

    incoming_files = _list_transcript_files(incoming_dir)
    incoming_ids = [p.stem for p in incoming_files]
    incoming_id_set = set(incoming_ids)

    if interviews_jsonl.exists():
        scores["interviews_jsonl_exists"] = 1.0
    records = _load_jsonl(interviews_jsonl) if interviews_jsonl.exists() else None
    if records is not None:
        scores["interviews_jsonl_parseable"] = 1.0

    record_id_list: List[str] = []
    record_by_id: Dict[str, Dict[str, Any]] = {}
    if records is not None:
        ok_unique = True
        seen = set()
        for rec in records:
            rid = rec.get("id")
            if not isinstance(rid, str):
                ok_unique = False
                break
            record_id_list.append(rid)
            if rid in seen:
                ok_unique = False
            seen.add(rid)
            record_by_id[rid] = rec
        if ok_unique:
            scores["interviews_jsonl_unique_ids"] = 1.0

        if set(record_id_list) == incoming_id_set:
            scores["records_count_matches_incoming"] = 1.0

        if all(rid in incoming_id_set for rid in record_id_list):
            scores["ids_match_filenames"] = 1.0

        required_fields = ["id", "interviewee_name", "interview_date", "birthplace", "occupation", "contributions", "summary", "source_path"]
        fields_ok = True
        dates_ok = True
        for rid, rec in record_by_id.items():
            for k in required_fields:
                if k not in rec:
                    fields_ok = False
                    break
                if k == "contributions":
                    if not isinstance(rec[k], list) or any((not isinstance(x, str) or not x.strip()) for x in rec[k]):
                        fields_ok = False
                        break
                else:
                    if not isinstance(rec[k], str) or not rec[k].strip():
                        fields_ok = False
                        break
            if not fields_ok:
                break
            if not _is_valid_date(rec.get("interview_date", "")):
                dates_ok = False
        if fields_ok:
            scores["fields_presence_and_nonempty"] = 1.0
        if dates_ok and fields_ok:
            scores["interview_dates_valid_format"] = 1.0

        src_ok = True
        for f in incoming_files:
            rid = f.stem
            rec = record_by_id.get(rid)
            if rec is None:
                src_ok = False
                break
            expected_rel = _normalize_rel_path(f, workspace)
            got_rel = str(rec.get("source_path", ""))
            got_rel_norm = got_rel.replace("\\", "/").strip()
            if got_rel_norm != expected_rel:
                src_ok = False
                break
        if src_ok and records is not None:
            scores["source_paths_correct"] = 1.0

        extraction_ok = True
        if incoming_files:
            for f in incoming_files:
                expected = _parse_transcript_file(f)
                if expected is None:
                    extraction_ok = False
                    break
                rid = f.stem
                rec = record_by_id.get(rid)
                if rec is None:
                    extraction_ok = False
                    break
                if _normalize_spaces(rec.get("interviewee_name", "")) != expected["interviewee_name"]:
                    extraction_ok = False
                    break
                if rec.get("interview_date", "") != expected["interview_date"]:
                    extraction_ok = False
                    break
                if _normalize_spaces(rec.get("birthplace", "")) != expected["birthplace"]:
                    extraction_ok = False
                    break
                if _normalize_spaces(rec.get("occupation", "")) != expected["occupation"]:
                    extraction_ok = False
                    break
                got_contrib = [_normalize_spaces(x) for x in rec.get("contributions", []) if isinstance(x, str)]
                if got_contrib != expected["contributions"]:
                    extraction_ok = False
                    break
                if _normalize_spaces(rec.get("summary", "")) != expected["summary"]:
                    extraction_ok = False
                    break
        else:
            extraction_ok = (len(record_id_list) == 0)
        if extraction_ok and records is not None:
            scores["content_extraction_matches_sources"] = 1.0

    if run_log.exists():
        scores["run_log_exists"] = 1.0
    entries = _parse_run_log_lines(run_log) if run_log.exists() else []
    ids_to_check: List[str] = list(record_by_id.keys()) if record_by_id else incoming_ids
    if ids_to_check:
        per_id_ok = True
        for rid in ids_to_check:
            found = any(e[2] == rid for e in entries)
            if not found:
                per_id_ok = False
                break
        if per_id_ok and run_log.exists():
            scores["run_log_has_entries_for_all_ids"] = 1.0
    else:
        if run_log.exists():
            scores["run_log_has_entries_for_all_ids"] = 1.0

    if entries:
        fmt_ok = True
        for ts, action, _rid in entries:
            ts_norm = ts.replace("Z", "+00:00")
            try:
                datetime.fromisoformat(ts_norm)
            except Exception:
                fmt_ok = False
                break
            if action not in {"added", "updated"}:
                fmt_ok = False
                break
        if fmt_ok:
            scores["run_log_entries_valid_format"] = 1.0

    if validation_report.exists():
        try:
            content = validation_report.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            content = ""
        if content:
            scores["validation_report_exists"] = 1.0
            lc = content.lower()
            if (("success" in lc) or ("passed" in lc) or ("ok" in lc)) and ("fail" not in lc and "error" not in lc):
                scores["validation_report_indicates_success"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()