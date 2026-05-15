import json
import csv
import hashlib
import sys
import re
from pathlib import Path
from urllib.parse import urlparse


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _safe_read_bytes(path: Path):
    try:
        return path.read_bytes()
    except Exception:
        return None


def _compute_sha256_hex(path: Path) -> str:
    data = _safe_read_bytes(path)
    if data is None:
        return ""
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            rows = [dict(r) for r in rdr]
        return rows
    except Exception:
        return None


def _load_jsonl(path: Path):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None
    objs = []
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                return None
            objs.append(obj)
        except Exception:
            return None
    return objs


def _is_hex64(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if len(s) != 64:
        return False
    return re.fullmatch(r"[0-9a-fA-F]{64}", s) is not None


def _validate_url_used(url: str, source: str, identifier: str) -> bool:
    if not isinstance(url, str) or not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = parsed.netloc.lower()
    path = parsed.path
    def _path_equals(p, expected):
        return p == expected or (p == expected + "/")
    if source == "NCBI_Gene":
        if host not in {"ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"}:
            return False
        if not _path_equals(path, f"/gene/{identifier}"):
            return False
        return True
    elif source == "UniProtKB":
        if host not in {"uniprot.org", "www.uniprot.org"}:
            return False
        if not _path_equals(path, f"/uniprotkb/{identifier}"):
            return False
        return True
    elif source == "GeneOntology":
        if host != "amigo.geneontology.org":
            return False
        if not _path_equals(path, f"/amigo/term/{identifier}"):
            return False
        return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_jsonl_exists_and_parse": 0.0,
        "summary_record_count_matches_input": 0.0,
        "summary_schema_validity": 0.0,
        "url_used_matches_expected_pattern": 0.0,
        "download_status_and_http_status_validity": 0.0,
        "success_records_have_saved_html_and_hash_match": 0.0,
        "error_records_fields_and_lengths_correct": 0.0,
        "summary_char_len_consistency": 0.0,
        "logs_download_log_exists_and_contains_urls": 0.0,
        "methods_md_exists_and_describes_process": 0.0,
        "methods_md_reports_success_and_failure_counts": 0.0,
    }

    targets_path = workspace / "input" / "targets.csv"
    targets = _load_csv_dicts(targets_path)
    expected_pairs = []
    if targets:
        for row in targets:
            src = row.get("source")
            ident = row.get("identifier")
            if isinstance(src, str) and isinstance(ident, str):
                expected_pairs.append((src, ident))

    summary_path = workspace / "outputs" / "extract" / "summary.jsonl"
    summary_records = _load_jsonl(summary_path)
    if summary_records is None:
        scores["summary_jsonl_exists_and_parse"] = 0.0
    else:
        scores["summary_jsonl_exists_and_parse"] = 1.0

        if expected_pairs:
            if len(summary_records) == len(expected_pairs):
                seen = {(rec.get("source"), rec.get("identifier")) for rec in summary_records}
                if set(expected_pairs) == seen:
                    scores["summary_record_count_matches_input"] = 1.0
                else:
                    scores["summary_record_count_matches_input"] = 0.0
            else:
                scores["summary_record_count_matches_input"] = 0.0
        else:
            scores["summary_record_count_matches_input"] = 0.0

        required_keys = [
            "source",
            "identifier",
            "url_used",
            "download_status",
            "http_status",
            "html_size_bytes",
            "html_sha256",
            "title_text",
            "heading_text",
            "meta_description",
            "summary_text",
            "summary_char_len",
            "error_message",
        ]
        valid_schema_count = 0
        for rec in summary_records:
            has_all = all(k in rec for k in required_keys)
            if not has_all:
                continue
            ok = True
            ok = ok and isinstance(rec.get("source"), str)
            ok = ok and isinstance(rec.get("identifier"), str)
            ok = ok and (isinstance(rec.get("url_used"), str) and len(rec.get("url_used")) > 0)
            ok = ok and rec.get("download_status") in {"ok", "error"}
            http_status = rec.get("http_status")
            ok = ok and (http_status is None or isinstance(http_status, int))
            ok = ok and isinstance(rec.get("html_size_bytes"), int) and rec.get("html_size_bytes") >= 0
            html_sha = rec.get("html_sha256")
            ok = ok and (html_sha is None or _is_hex64(html_sha))
            for fld in ["title_text", "heading_text", "meta_description", "summary_text", "error_message"]:
                v = rec.get(fld)
                if v is not None and not isinstance(v, str):
                    ok = False
                    break
            ok = ok and isinstance(rec.get("summary_char_len"), int) and rec.get("summary_char_len") >= 0
            if ok:
                valid_schema_count += 1
        if summary_records:
            scores["summary_schema_validity"] = valid_schema_count / len(summary_records)
        else:
            scores["summary_schema_validity"] = 0.0

        url_valid_count = 0
        matched_records = 0
        for rec in summary_records:
            src = rec.get("source")
            ident = rec.get("identifier")
            url_used = rec.get("url_used")
            if isinstance(src, str) and isinstance(ident, str) and isinstance(url_used, str):
                matched_records += 1
                if _validate_url_used(url_used, src, ident):
                    url_valid_count += 1
        if matched_records > 0:
            scores["url_used_matches_expected_pattern"] = url_valid_count / matched_records

        ds_valid_count = 0
        for rec in summary_records:
            ds = rec.get("download_status")
            http_status = rec.get("http_status")
            if ds == "ok":
                if isinstance(http_status, int) and 200 <= http_status <= 299:
                    ds_valid_count += 1
            elif ds == "error":
                if http_status is None or not (200 <= http_status <= 299):
                    ds_valid_count += 1
        if summary_records:
            scores["download_status_and_http_status_validity"] = ds_valid_count / len(summary_records)

        scl_ok = 0
        for rec in summary_records:
            st = rec.get("summary_text")
            scl = rec.get("summary_char_len")
            if st is None:
                if scl == 0:
                    scl_ok += 1
            elif isinstance(st, str) and isinstance(scl, int):
                if scl == len(st):
                    scl_ok += 1
        if summary_records:
            scores["summary_char_len_consistency"] = scl_ok / len(summary_records)

        ok_recs = [r for r in summary_records if r.get("download_status") == "ok"]
        sr_ok_count = 0
        total_ok = len(ok_recs)
        for rec in ok_recs:
            src = rec.get("source")
            ident = rec.get("identifier")
            html_size = rec.get("html_size_bytes")
            sha = rec.get("html_sha256")
            file_path = workspace / "data" / "raw" / str(src) / f"{ident}.html"
            file_bytes = _safe_read_bytes(file_path)
            if file_bytes is None:
                continue
            size_matches = (len(file_bytes) == html_size)
            sha_matches = (_compute_sha256_hex(file_path) == (sha or ""))
            if size_matches and sha_matches and html_size > 0 and isinstance(sha, str) and _is_hex64(sha):
                sr_ok_count += 1
        scores["success_records_have_saved_html_and_hash_match"] = (sr_ok_count / total_ok) if total_ok > 0 else 1.0

        err_recs = [r for r in summary_records if r.get("download_status") == "error"]
        err_ok_count = 0
        for rec in err_recs:
            html_size = rec.get("html_size_bytes")
            sha = rec.get("html_sha256")
            title = rec.get("title_text")
            heading = rec.get("heading_text")
            meta = rec.get("meta_description")
            summ = rec.get("summary_text")
            scl = rec.get("summary_char_len")
            errmsg = rec.get("error_message")
            conds = [
                html_size == 0,
                sha is None,
                title is None,
                heading is None,
                meta is None,
                summ is None,
                scl == 0,
                isinstance(errmsg, str) and len(errmsg.strip()) > 0,
            ]
            if all(conds):
                err_ok_count += 1
        scores["error_records_fields_and_lengths_correct"] = (err_ok_count / len(err_recs)) if err_recs else 1.0

    log_path = workspace / "logs" / "download.log"
    if log_path.exists() and log_path.is_file():
        log_text = _safe_read_text(log_path)
        if log_text:
            if summary_records:
                urls = [rec.get("url_used") for rec in summary_records if isinstance(rec.get("url_used"), str)]
                if urls:
                    contains_count = sum(1 for u in urls if u in log_text)
                    scores["logs_download_log_exists_and_contains_urls"] = contains_count / len(urls)
            else:
                scores["logs_download_log_exists_and_contains_urls"] = 0.0
        else:
            scores["logs_download_log_exists_and_contains_urls"] = 0.0
    else:
        scores["logs_download_log_exists_and_contains_urls"] = 0.0

    methods_path = workspace / "outputs" / "METHODS.md"
    if methods_path.exists() and methods_path.is_file():
        methods_text = _safe_read_text(methods_path).lower()
        has_domains = all(x in methods_text for x in ["ncbi.nlm.nih.gov", "uniprot.org", "amigo.geneontology.org"])
        has_paths = all(x in methods_text for x in ["/gene", "/uniprotkb", "/amigo/term"])
        mentions_status = ("status" in methods_text or "http" in methods_text)
        mentions_retry = ("retry" in methods_text or "retri" in methods_text)
        if has_domains and has_paths and mentions_status and mentions_retry:
            scores["methods_md_exists_and_describes_process"] = 1.0
        else:
            scores["methods_md_exists_and_describes_process"] = 0.0

        if summary_records:
            succ = sum(1 for r in summary_records if r.get("download_status") == "ok")
            fail = sum(1 for r in summary_records if r.get("download_status") == "error")
            mtext = methods_text
            has_succ_num = str(succ) in mtext
            has_fail_num = str(fail) in mtext
            has_succ_word = any(w in mtext for w in ["success", "succeeded", "ok"])
            has_fail_word = any(w in mtext for w in ["fail", "failed", "error"])
            if has_succ_num and has_fail_num and has_succ_word and has_fail_word:
                scores["methods_md_reports_success_and_failure_counts"] = 1.0
            else:
                scores["methods_md_reports_success_and_failure_counts"] = 0.0
        else:
            scores["methods_md_reports_success_and_failure_counts"] = 0.0
    else:
        scores["methods_md_exists_and_describes_process"] = 0.0
        scores["methods_md_reports_success_and_failure_counts"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()