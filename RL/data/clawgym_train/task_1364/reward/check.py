import json
import re
import sys
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple


def _load_json_safe(p: Path) -> Optional[dict]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_bytes_safe(p: Path) -> Optional[bytes]:
    try:
        return p.read_bytes()
    except Exception:
        return None


def _read_text_safe(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _compute_sha256_hex(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _first_line_from_bytes(data: bytes) -> str:
    if not data:
        return ""
    line = data.split(b"\n", 1)[0]
    if line.endswith(b"\r"):
        line = line[:-1]
    for enc in ("utf-8", "latin-1"):
        try:
            return line.decode(enc)
        except Exception:
            continue
    return ""


def _is_probably_html(data: bytes) -> bool:
    if not data:
        return False
    head = data[:4096].lower()
    for tag in (b"<html", b"<!doctype html", b"<head", b"<title", b"</html"):
        if tag in head:
            return True
    return False


def _parse_iso8601_loose(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        s2 = s.replace("Z", "+00:00")
        datetime.fromisoformat(s2)
        return True
    except Exception:
        try:
            datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            return True
        except Exception:
            return False


def _downloader_analysis(downloader_path: Path, expected_rfc_number: Optional[int]) -> Tuple[float, float, float]:
    content = _read_text_safe(downloader_path) or ""
    has_rfc_editor = "rfc-editor.org" in content
    has_rfc_path = "/rfc/" in content
    has_txt = ".txt" in content
    has_info = "/info/" in content

    has_specific_rfc_txt = False
    if expected_rfc_number is not None:
        if f"rfc{expected_rfc_number}.txt" in content:
            has_specific_rfc_txt = True
        if re.search(rf"/rfc/.*rfc{expected_rfc_number}\.txt", content):
            has_specific_rfc_txt = True

    url_score = 0.0
    if has_rfc_editor and has_rfc_path and has_txt and not has_info:
        url_score = 1.0
    elif has_rfc_editor and has_rfc_path and has_txt:
        url_score = 0.5

    read_full = False
    if re.search(r"\.read\(\s*\)", content):
        read_full = True
    if "shutil.copyfileobj" in content:
        read_full = True
    reads_small_only = False
    small_read_matches = re.findall(r"\.read\(\s*(\d+)\s*\)", content)
    if small_read_matches and not read_full:
        if all(int(n) <= 65536 for n in small_read_matches):
            reads_small_only = True
    read_score = 1.0 if read_full and not reads_small_only else (0.0 if reads_small_only else (1.0 if read_full else 0.0))

    writes_binary = bool(re.search(r"open\(\s*[^,]+,\s*['\"]wb['\"]", content))
    write_bin_score = 1.0 if writes_binary else 0.0

    if has_specific_rfc_txt and url_score < 1.0:
        url_score = min(1.0, url_score + 0.5)

    return url_score, read_score, write_bin_score


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "text_file_exists": 0.0,
        "text_file_plaintext_rfc_signature": 0.0,
        "metadata_json_valid": 0.0,
        "metadata_fields_and_domain": 0.0,
        "metadata_checksum_and_size_match_file": 0.0,
        "metadata_first_line_matches_file": 0.0,
        "report_exists_with_sections": 0.0,
        "report_verification_matches_metadata": 0.0,
        "downloader_uses_plain_text_url": 0.0,
        "downloader_reads_full_content": 0.0,
        "downloader_writes_binary_mode": 0.0,
    }

    cfg_path = workspace / "input" / "config.json"
    cfg = _load_json_safe(cfg_path)
    rfc_number = None
    out_text_path = None
    out_meta_path = None
    report_path = None
    if cfg and isinstance(cfg, dict):
        rfc_number = cfg.get("rfc_number")
        out_text_path = cfg.get("output_text_path")
        out_meta_path = cfg.get("output_metadata_path")
        report_path = cfg.get("report_path")

    out_text_file = workspace / out_text_path if out_text_path else None
    out_meta_file = workspace / out_meta_path if out_meta_path else None
    report_file = workspace / report_path if report_path else None

    text_bytes = None
    if out_text_file and out_text_file.is_file():
        text_bytes = _read_bytes_safe(out_text_file)
        if text_bytes is not None:
            if len(text_bytes) > 0:
                scores["text_file_exists"] = 1.0
            else:
                scores["text_file_exists"] = 0.0
            not_html = not _is_probably_html(text_bytes)
            head = (text_bytes[:8192] or b"").decode("utf-8", errors="ignore")
            has_rfc_id = ("RFC 8259" in head) or ("Request for Comments: 8259" in head)
            has_title = ("JavaScript Object Notation (JSON) Data Interchange Format" in head) or ("JSON Data Interchange Format" in head) or ("JavaScript Object Notation" in head)
            if not_html and (has_rfc_id or has_title):
                scores["text_file_plaintext_rfc_signature"] = 1.0
            elif not_html:
                scores["text_file_plaintext_rfc_signature"] = 0.5
            else:
                scores["text_file_plaintext_rfc_signature"] = 0.0
        else:
            scores["text_file_exists"] = 0.0
            scores["text_file_plaintext_rfc_signature"] = 0.0
    else:
        scores["text_file_exists"] = 0.0
        scores["text_file_plaintext_rfc_signature"] = 0.0

    meta = None
    if out_meta_file and out_meta_file.is_file():
        meta = _load_json_safe(out_meta_file)
        if isinstance(meta, dict):
            scores["metadata_json_valid"] = 1.0
            has_fields = (
                "rfc_number" in meta
                and "source_domain" in meta
                and "bytes_downloaded" in meta
                and "sha256_hex" in meta
                and "first_line_text" in meta
                and "downloaded_at_iso8601" in meta
            )
            field_score = 0.0
            if has_fields:
                rfc_ok = (rfc_number is None) or (meta.get("rfc_number") == rfc_number)
                domain_ok = meta.get("source_domain") == "rfc-editor.org"
                iso_ok = _parse_iso8601_loose(meta.get("downloaded_at_iso8601"))
                field_score = 1.0 if (rfc_ok and domain_ok and iso_ok) else 0.0
            scores["metadata_fields_and_domain"] = field_score

            if text_bytes is not None:
                size_match = isinstance(meta.get("bytes_downloaded"), int) and meta.get("bytes_downloaded") == len(text_bytes)
                sha_hex = meta.get("sha256_hex")
                sha_calc = _compute_sha256_hex(text_bytes)
                sha_match = isinstance(sha_hex, str) and sha_hex.lower() == sha_calc
                scores["metadata_checksum_and_size_match_file"] = 1.0 if (size_match and sha_match) else 0.0

                first_line = _first_line_from_bytes(text_bytes)
                fl_match = isinstance(meta.get("first_line_text"), str) and meta.get("first_line_text") == first_line
                scores["metadata_first_line_matches_file"] = 1.0 if fl_match else 0.0
            else:
                scores["metadata_checksum_and_size_match_file"] = 0.0
                scores["metadata_first_line_matches_file"] = 0.0
        else:
            scores["metadata_json_valid"] = 0.0
    else:
        scores["metadata_json_valid"] = 0.0

    if report_file and report_file.is_file():
        rpt = _read_text_safe(report_file) or ""
        required_sections = ["Summary", "Root cause", "Fix", "Verification", "Next steps"]
        sections_ok = all(sec.lower() in rpt.lower() for sec in required_sections)
        scores["report_exists_with_sections"] = 1.0 if sections_ok else 0.0

        ver_ok = False
        if isinstance(meta, dict):
            sha = str(meta.get("sha256_hex", "")).lower()
            size_str = str(meta.get("bytes_downloaded", ""))
            if sha and size_str and (sha in rpt.lower()) and (size_str in rpt):
                ver_ok = True
        scores["report_verification_matches_metadata"] = 1.0 if ver_ok else 0.0
    else:
        scores["report_exists_with_sections"] = 0.0
        scores["report_verification_matches_metadata"] = 0.0

    downloader_path = workspace / "input" / "downloader.py"
    url_score = 0.0
    read_score = 0.0
    write_bin_score = 0.0
    if downloader_path.is_file():
        url_score, read_score, write_bin_score = _downloader_analysis(downloader_path, rfc_number if isinstance(rfc_number, int) else None)
    scores["downloader_uses_plain_text_url"] = url_score
    scores["downloader_reads_full_content"] = read_score
    scores["downloader_writes_binary_mode"] = write_bin_score

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()