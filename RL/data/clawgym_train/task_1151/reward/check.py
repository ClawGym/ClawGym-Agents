import json
import csv
import sys
import hashlib
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlparse


def safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        text = safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def safe_load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None


def sha256_file(path: Path):
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest(), path.stat().st_size
    except Exception:
        return None, None


class AssetHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.matches = []  # list of tuples (url, line)

    @staticmethod
    def _attrs_to_dict(attrs):
        return {k.lower(): v for k, v in attrs if v is not None}

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        attrs_dict = self._attrs_to_dict(attrs)
        line, _ = self.getpos()
        if tag_l == "link":
            rel = attrs_dict.get("rel", "")
            href = attrs_dict.get("href")
            if href and isinstance(rel, str) and "stylesheet" in rel.lower():
                if href.lower().startswith("http://") or href.lower().startswith("https://"):
                    self.matches.append((href, line))
        elif tag_l == "script":
            src = attrs_dict.get("src")
            if src and (src.lower().startswith("http://") or src.lower().startswith("https://")):
                self.matches.append((src, line))


def discover_expected_assets(input_dir: Path):
    expected = {}  # url -> { "files": {path_str: [lines...] } }
    total_found = 0
    html_files = []
    if input_dir.exists():
        html_files = sorted([p for p in input_dir.rglob("*.html") if p.is_file()])
    for fpath in html_files:
        text = safe_read_text(fpath)
        if text is None:
            continue
        parser = AssetHTMLParser()
        try:
            parser.feed(text)
        except Exception:
            continue
        for url, line in parser.matches:
            total_found += 1
            info = expected.setdefault(url, {"files": {}})
            file_key = str(fpath.as_posix())
            info["files"].setdefault(file_key, []).append(line)
    return expected, total_found, html_files


def normalize_path_match(path_str: str):
    p = path_str.replace("\\", "/")
    return p


def endswith_any(path_str: str, candidates):
    p = normalize_path_match(path_str)
    for c in candidates:
        if p.endswith(c):
            return True
    return False


def parse_summary_txt(path: Path):
    content = safe_read_text(path)
    if content is None:
        return None
    result = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        try:
            ival = int(val)
            result[key] = ival
        except Exception:
            result[key] = val
    return result


def load_json_records(path: Path):
    data = safe_load_json(path)
    if not isinstance(data, list):
        return None
    for item in data:
        if not isinstance(item, dict):
            return None
    return data


def normalize_csv_field(value):
    if value is None:
        return None
    v = value.strip()
    if v == "":
        return None
    return v


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "run_audit_sh_invokes_script": 0.0,
        "assets_audit_json_valid": 0.0,
        "json_records_field_set_exact": 0.0,
        "json_unique_urls_match": 0.0,
        "json_referenced_by_complete": 0.0,
        "json_first_seen_line_correct": 0.0,
        "assets_audit_csv_matches_json": 0.0,
        "summary_txt_counts_correct": 0.0,
        "downloads_files_match_json": 0.0,
        "run_log_has_required_entries": 0.0,
    }

    input_dir = workspace / "input" / "templates"
    expected_map, expected_total_found, html_files = discover_expected_assets(input_dir)
    expected_urls = set(expected_map.keys())

    scripts_dir = workspace / "scripts"
    script_candidates = []
    if scripts_dir.exists():
        for ext in ["", ".py", ".js", ".sh"]:
            p = scripts_dir / f"audit_assets{ext}"
            if p.exists() and p.is_file():
                script_candidates.append(p)
    if not script_candidates and scripts_dir.exists():
        for p in scripts_dir.iterdir():
            if p.is_file() and p.name.startswith("audit_assets."):
                script_candidates.append(p)
    if script_candidates:
        scores["script_present"] = 1.0

    run_sh = workspace / "run_audit.sh"
    if run_sh.exists() and run_sh.is_file():
        content = safe_read_text(run_sh) or ""
        lines = [ln for ln in content.splitlines() if ln.strip() and not ln.strip().startswith("#!")]
        non_comment_lines = [ln for ln in lines if not ln.strip().startswith("#")]
        if len(non_comment_lines) == 1:
            line = non_comment_lines[0]
            line_norm = line.replace("\\", "/")
            has_script = "scripts/audit_assets" in line_norm
            has_input = "input/templates" in line_norm
            has_output = " output" in line or line.strip().endswith(" output") or " output " in f" {line} "
            if has_script and has_input and has_output:
                scores["run_audit_sh_invokes_script"] = 1.0

    report_dir = workspace / "output" / "report"
    logs_dir = workspace / "output" / "logs"
    downloads_dir = workspace / "output" / "downloads"

    json_path = report_dir / "assets_audit.json"
    csv_path = report_dir / "assets_audit.csv"
    summary_path = report_dir / "summary.txt"
    run_log_path = logs_dir / "run.log"

    json_records = None
    if json_path.exists():
        json_records = load_json_records(json_path)
    if isinstance(json_records, list):
        scores["assets_audit_json_valid"] = 1.0

    required_fields = [
        "original_url",
        "host",
        "referenced_by",
        "first_seen_line",
        "status",
        "http_status",
        "final_url",
        "content_type",
        "bytes",
        "sha256",
    ]
    allowed_statuses = {"ok", "fail", "skipped_large"}

    def is_hex(s):
        try:
            int(s, 16)
            return True
        except Exception:
            return False

    fields_ok = False
    unique_url_set_from_json = set()
    referenced_by_map_from_json = {}
    first_seen_line_map_from_json = {}
    status_map_from_json = {}
    if isinstance(json_records, list):
        fields_ok = True
        seen_urls = set()
        for rec in json_records:
            rec_keys = set(rec.keys())
            if rec_keys != set(required_fields):
                fields_ok = False
                break
            original_url = rec.get("original_url")
            host = rec.get("host")
            referenced_by = rec.get("referenced_by")
            first_seen_line = rec.get("first_seen_line")
            status = rec.get("status")
            http_status = rec.get("http_status")
            final_url = rec.get("final_url")
            content_type = rec.get("content_type")
            bytes_val = rec.get("bytes")
            sha256_val = rec.get("sha256")

            if not isinstance(original_url, str):
                fields_ok = False
                break
            if original_url in seen_urls:
                fields_ok = False
                break
            seen_urls.add(original_url)

            try:
                parsed = urlparse(original_url)
                expected_host = parsed.netloc
            except Exception:
                fields_ok = False
                break
            if host != expected_host:
                fields_ok = False
                break

            if not isinstance(referenced_by, list):
                fields_ok = False
                break
            for rb in referenced_by:
                if not isinstance(rb, str):
                    fields_ok = False
                    break
            if not isinstance(first_seen_line, int) or first_seen_line < 1:
                fields_ok = False
                break
            if status not in allowed_statuses:
                fields_ok = False
                break
            if http_status is not None and not isinstance(http_status, int):
                fields_ok = False
                break
            if final_url is not None and not isinstance(final_url, str):
                fields_ok = False
                break
            if content_type is not None and not isinstance(content_type, str):
                fields_ok = False
                break
            if bytes_val is not None and not isinstance(bytes_val, int):
                fields_ok = False
                break
            if sha256_val is not None:
                if not isinstance(sha256_val, str) or len(sha256_val) != 64 or not is_hex(sha256_val):
                    fields_ok = False
                    break
            if status == "ok":
                if sha256_val is None or bytes_val is None:
                    fields_ok = False
                    break

            unique_url_set_from_json.add(original_url)
            referenced_by_map_from_json[original_url] = referenced_by
            first_seen_line_map_from_json[original_url] = first_seen_line
            status_map_from_json[original_url] = status

    if fields_ok and isinstance(json_records, list):
        scores["json_records_field_set_exact"] = 1.0

    if isinstance(json_records, list):
        if expected_urls == unique_url_set_from_json:
            scores["json_unique_urls_match"] = 1.0

    referenced_by_ok = False
    if isinstance(json_records, list) and expected_urls == unique_url_set_from_json:
        rb_ok = True
        for url, files_info in expected_map.items():
            expected_paths = set(files_info["files"].keys())
            json_rb = referenced_by_map_from_json.get(url, [])
            matched_expected = set()
            for rb in json_rb:
                for end in expected_paths:
                    if endswith_any(rb, [end]):
                        matched_expected.add(end)
            if matched_expected != expected_paths or len(json_rb) != len(expected_paths):
                rb_ok = False
                break
        referenced_by_ok = rb_ok
    if referenced_by_ok:
        scores["json_referenced_by_complete"] = 1.0

    fsl_ok = False
    if isinstance(json_records, list) and expected_urls == unique_url_set_from_json:
        fsl_ok = True
        for url, files_info in expected_map.items():
            min_line = None
            for lines in files_info["files"].values():
                for ln in lines:
                    if min_line is None or ln < min_line:
                        min_line = ln
            reported = first_seen_line_map_from_json.get(url)
            if reported != min_line:
                fsl_ok = False
                break
    if fsl_ok:
        scores["json_first_seen_line_correct"] = 1.0

    csv_ok = False
    if csv_path.exists() and isinstance(json_records, list):
        csv_rows = safe_load_csv_dicts(csv_path)
        if isinstance(csv_rows, list):
            try:
                json_map = {rec["original_url"]: rec for rec in json_records}
                csv_map = {}
                for row in csv_rows:
                    ou = row.get("original_url")
                    if ou is None:
                        raise ValueError("missing original_url in CSV")
                    if ou in csv_map:
                        raise ValueError("duplicate original_url in CSV")
                    csv_map[ou] = row
                if set(json_map.keys()) == set(csv_map.keys()):
                    consistent = True
                    for url, jrec in json_map.items():
                        crec = csv_map[url]
                        if (crec.get("host") or "").strip() != jrec["host"]:
                            consistent = False
                            break
                        rb_csv_raw = normalize_csv_field(crec.get("referenced_by"))
                        if rb_csv_raw is None:
                            rb_list_csv = []
                        else:
                            rb_list_csv = [s.strip() for s in rb_csv_raw.split(";") if s.strip()]
                        rb_json = jrec["referenced_by"]
                        if len(rb_list_csv) != len(rb_json):
                            consistent = False
                            break
                        for jrb in rb_json:
                            if not any(endswith_any(jrb, [normalize_path_match(crb)]) or endswith_any(crb, [normalize_path_match(jrb)]) for crb in rb_list_csv):
                                consistent = False
                                break
                        if not consistent:
                            break

                        try:
                            fsl_csv = int(crec.get("first_seen_line")) if normalize_csv_field(crec.get("first_seen_line")) is not None else None
                        except Exception:
                            fsl_csv = None
                        if fsl_csv != jrec["first_seen_line"]:
                            consistent = False
                            break

                        if (crec.get("status") or "").strip() != jrec["status"]:
                            consistent = False
                            break

                        http_csv_raw = normalize_csv_field(crec.get("http_status"))
                        if http_csv_raw is None:
                            http_csv = None
                        else:
                            try:
                                http_csv = int(http_csv_raw)
                            except Exception:
                                consistent = False
                                break
                        if http_csv != jrec["http_status"]:
                            consistent = False
                            break

                        final_csv = normalize_csv_field(crec.get("final_url"))
                        if final_csv != jrec["final_url"]:
                            consistent = False
                            break

                        ctype_csv = normalize_csv_field(crec.get("content_type"))
                        if ctype_csv != jrec["content_type"]:
                            consistent = False
                            break

                        bytes_csv_raw = normalize_csv_field(crec.get("bytes"))
                        if bytes_csv_raw is None:
                            bytes_csv = None
                        else:
                            try:
                                bytes_csv = int(bytes_csv_raw)
                            except Exception:
                                consistent = False
                                break
                        if bytes_csv != jrec["bytes"]:
                            consistent = False
                            break

                        sha_csv = normalize_csv_field(crec.get("sha256"))
                        if sha_csv != jrec["sha256"]:
                            consistent = False
                            break

                    if consistent:
                        csv_ok = True
            except Exception:
                csv_ok = False
    if csv_ok:
        scores["assets_audit_csv_matches_json"] = 1.0

    summary_ok = False
    if summary_path.exists() and isinstance(json_records, list):
        summary = parse_summary_txt(summary_path)
        if isinstance(summary, dict):
            keys_needed = ["total_urls_found", "unique_urls", "ok_count", "fail_count", "skipped_large_count"]
            if all(k in summary for k in keys_needed):
                uniq = len(json_records)
                ok_count = sum(1 for rec in json_records if rec.get("status") == "ok")
                fail_count = sum(1 for rec in json_records if rec.get("status") == "fail")
                skipped_count = sum(1 for rec in json_records if rec.get("status") == "skipped_large")
                if summary.get("unique_urls") == uniq and summary.get("ok_count") == ok_count and summary.get("fail_count") == fail_count and summary.get("skipped_large_count") == skipped_count:
                    if summary.get("total_urls_found") == expected_total_found:
                        if (ok_count + fail_count + skipped_count) == uniq:
                            summary_ok = True
    if summary_ok:
        scores["summary_txt_counts_correct"] = 1.0

    downloads_ok = False
    if isinstance(json_records, list):
        ok_items = [rec for rec in json_records if rec.get("status") == "ok"]
        if not ok_items:
            downloads_ok = True
        else:
            if downloads_dir.exists():
                host_files = {}
                for host_dir in downloads_dir.iterdir() if downloads_dir.exists() else []:
                    if host_dir.is_dir():
                        host = host_dir.name
                        file_hashes = []
                        for f in host_dir.rglob("*"):
                            if f.is_file():
                                h, sz = sha256_file(f)
                                if h is not None and sz is not None:
                                    file_hashes.append((h, sz))
                        host_files[host] = file_hashes
                consistent = True
                for rec in ok_items:
                    host = rec.get("host")
                    sha = rec.get("sha256")
                    bts = rec.get("bytes")
                    found = False
                    for h, sz in host_files.get(host, []):
                        if h == sha and sz == bts:
                            found = True
                            break
                    if not found:
                        consistent = False
                        break
                downloads_ok = consistent
            else:
                downloads_ok = False
    if downloads_ok:
        scores["downloads_files_match_json"] = 1.0

    runlog_ok = False
    if run_log_path.exists():
        content = safe_read_text(run_log_path) or ""
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        lower = "\n".join(lines).lower()
        has_start = "start" in lower
        has_end = "end" in lower

        files_scanned_ok = False
        uniq_count_ok = False

        expected_files_count = len(html_files)
        expected_unique_urls_count = len(expected_urls)

        for ln in lines:
            ln_l = ln.lower()
            if ("html" in ln_l and "file" in ln_l and "scan" in ln_l):
                nums = []
                for tok in ln.replace(",", " ").split():
                    try:
                        nums.append(int(tok))
                    except Exception:
                        pass
                if nums and (expected_files_count in nums):
                    files_scanned_ok = True
            if ("unique" in ln_l and "url" in ln_l and ("count" in ln_l or "total" in ln_l or ":" in ln_l)):
                nums = []
                for tok in ln.replace(",", " ").split():
                    try:
                        nums.append(int(tok))
                    except Exception:
                        pass
                if nums and (expected_unique_urls_count in nums):
                    uniq_count_ok = True

        if has_start and has_end and files_scanned_ok and uniq_count_ok:
            runlog_ok = True
    if runlog_ok:
        scores["run_log_has_required_entries"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()