import json
import sys
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            return path.read_bytes().decode("utf-8", errors="replace")
        except Exception:
            return None


def load_json(path: Path):
    try:
        content = read_text(path)
        if content is None:
            return None
        return json.loads(content)
    except Exception:
        return None


def is_hex_sha256(s: str) -> bool:
    return isinstance(s, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", s or ""))


def parse_iso8601_utc(s: str):
    if not isinstance(s, str):
        return None
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return None
        if dt.utcoffset() != timezone.utc.utcoffset(dt):
            return None
        return dt
    except Exception:
        return None


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "@" in host:
            host = host.split("@", 1)[-1]
        if ":" in host:
            host = host.split(":", 1)[0]
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def allowed_domain(domain: str) -> bool:
    if not isinstance(domain, str):
        return False
    d = domain.lower()
    if d.endswith(".gov") or d.endswith(".edu") or d.endswith(".org"):
        return True
    if d.endswith("europa.eu") or d.endswith("iso.org") or d.endswith("oecd.org"):
        return True
    return False


def count_words(text: str) -> int:
    if not isinstance(text, str) or not text:
        return 0
    return len([t for t in text.split() if t.strip()])


def find_ingest_log_line(lines, basename: str):
    res = None
    for line in lines:
        if basename in line:
            res = line
    return res


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_file_exists": 0.0,
        "report_top_level_fields_valid": 0.0,
        "report_queries_count_and_order": 0.0,
        "report_query_results_structure": 0.0,
        "urls_count_limit_per_query": 0.0,
        "allowlist_domain_enforced": 0.0,
        "raw_files_exist_and_sha256_match": 0.0,
        "text_files_exist_and_word_count_consistency": 0.0,
        "paths_structure_correctness": 0.0,
        "state_file_exists_and_contains_entry": 0.0,
        "state_sha256_and_processed_at_valid": 0.0,
        "state_report_sha256_consistency": 0.0,
        "ingest_log_exists_and_contains_entry": 0.0,
        "ingest_log_counts_consistency": 0.0,
    }

    reports_dir = workspace / "outputs" / "reports"
    report_path = reports_dir / "example_keywords.json"
    report = None
    if report_path.exists():
        report = load_json(report_path)
        if isinstance(report, dict):
            scores["report_file_exists"] = 1.0

    expected_keywords_rel = "watch_keywords/example_keywords.txt"
    if report:
        top_ok = True
        src = report.get("source_keywords_file")
        if not isinstance(src, str):
            top_ok = False
        else:
            norm = src.lstrip("./")
            if not norm.endswith(expected_keywords_rel):
                top_ok = False
        pat = report.get("processed_at")
        dt = parse_iso8601_utc(pat) if isinstance(pat, str) else None
        if dt is None:
            top_ok = False
        fsha = report.get("file_sha256")
        if not is_hex_sha256(fsha or ""):
            top_ok = False
        q = report.get("queries")
        if not isinstance(q, list):
            top_ok = False
        if top_ok:
            scores["report_top_level_fields_valid"] = 1.0

    if report and isinstance(report.get("queries"), list):
        keyword_file_path = workspace / expected_keywords_rel
        src_report_path = None
        if isinstance(report.get("source_keywords_file"), str):
            src_candidate = workspace / report["source_keywords_file"]
            src_candidate2 = workspace / report["source_keywords_file"].lstrip("./")
            if src_candidate.exists():
                src_report_path = src_candidate
            elif src_candidate2.exists():
                src_report_path = src_candidate2
        if src_report_path is None:
            src_report_path = keyword_file_path

        lines = []
        if src_report_path.exists():
            raw = read_text(src_report_path) or ""
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        queries_field = report["queries"]
        queries_ok = True
        if len(lines) != len(queries_field):
            queries_ok = False
        else:
            for i, entry in enumerate(queries_field):
                if not isinstance(entry, dict) or "query" not in entry or not isinstance(entry["query"], str):
                    queries_ok = False
                    break
                if entry["query"].strip() != lines[i]:
                    queries_ok = False
                    break
        if queries_ok:
            scores["report_queries_count_and_order"] = 1.0

    total_results = 0
    structure_ok = True
    limit_ok = True
    allowlist_ok = True
    raw_ok = True
    text_ok = True
    paths_ok = True

    if report and isinstance(report.get("queries"), list):
        for q_entry in report["queries"]:
            if not isinstance(q_entry, dict):
                structure_ok = False
                continue
            results = q_entry.get("results")
            if not isinstance(results, list):
                structure_ok = False
                continue
            urls = []
            for res in results:
                if not isinstance(res, dict):
                    structure_ok = False
                    continue
                url = res.get("url")
                domain = res.get("domain")
                http_status = res.get("http_status")
                content_type = res.get("content_type")
                title = res.get("title")
                word_count = res.get("word_count")
                raw_path = res.get("raw_path")
                text_path = res.get("text_path")
                sha256_raw = res.get("sha256_raw")

                if not (isinstance(url, str) and url):
                    structure_ok = False
                if not (isinstance(domain, str) and domain):
                    structure_ok = False
                if not (http_status is None or isinstance(http_status, int)):
                    structure_ok = False
                if not (content_type is None or isinstance(content_type, str)):
                    structure_ok = False
                if not (title is None or isinstance(title, str)):
                    structure_ok = False
                if not (isinstance(word_count, int) and word_count >= 0):
                    structure_ok = False
                if not (isinstance(raw_path, str) and isinstance(text_path, str)):
                    structure_ok = False
                if not is_hex_sha256(sha256_raw or ""):
                    structure_ok = False

                if isinstance(url, str) and isinstance(domain, str):
                    derived = extract_domain(url)
                    dom_norm = domain.lower().strip()
                    if dom_norm.startswith("www."):
                        dom_norm = dom_norm[4:]
                    if derived != dom_norm:
                        structure_ok = False
                    if not allowed_domain(derived):
                        allowlist_ok = False

                if isinstance(raw_path, str):
                    try:
                        rp = (workspace / raw_path).resolve()
                        if "outputs/raw/" not in str(Path(raw_path).as_posix()):
                            paths_ok = False
                        if not rp.exists():
                            raw_ok = False
                        else:
                            ext = rp.suffix.lower()
                            if ext not in [".html", ".pdf", ".bin"]:
                                paths_ok = False
                            comp = compute_sha256(rp)
                            if comp.lower() != (sha256_raw or "").lower():
                                raw_ok = False
                    except Exception:
                        raw_ok = False
                        paths_ok = False
                    if "outputs/raw/example_keywords/" not in str(Path(raw_path).as_posix()):
                        paths_ok = False

                if isinstance(text_path, str):
                    try:
                        tp = (workspace / text_path).resolve()
                        if "outputs/text/" not in str(Path(text_path).as_posix()):
                            paths_ok = False
                        if not tp.exists():
                            text_ok = False
                        else:
                            if tp.suffix.lower() != ".txt":
                                paths_ok = False
                            text_content = read_text(tp)
                            if text_content is None:
                                text_ok = False
                            else:
                                calc_wc = count_words(text_content)
                                if isinstance(word_count, int):
                                    if calc_wc != word_count:
                                        text_ok = False
                    except Exception:
                        text_ok = False
                        paths_ok = False
                    if "outputs/text/example_keywords/" not in str(Path(text_path).as_posix()):
                        paths_ok = False

                try:
                    raw_name = Path(raw_path).name if isinstance(raw_path, str) else None
                    text_name = Path(text_path).name if isinstance(text_path, str) else None
                    if raw_name and text_name:
                        raw_rank = raw_name.split(".")[0]
                        text_rank = text_name.split(".")[0]
                        if not raw_rank.isdigit() or not text_rank.isdigit() or raw_rank != text_rank:
                            paths_ok = False
                except Exception:
                    paths_ok = False

                urls.append(url)

            total_results += len(results)
            if len(results) > 5:
                limit_ok = False
            if len(set(urls)) != len(urls):
                limit_ok = False

    if report:
        if structure_ok:
            scores["report_query_results_structure"] = 1.0
        if limit_ok:
            scores["urls_count_limit_per_query"] = 1.0
        if total_results == 0:
            scores["allowlist_domain_enforced"] = 1.0
        else:
            if allowlist_ok:
                scores["allowlist_domain_enforced"] = 1.0
        if total_results == 0 or raw_ok:
            scores["raw_files_exist_and_sha256_match"] = 1.0 if (total_results == 0 or raw_ok) else 0.0
        if total_results == 0 or text_ok:
            scores["text_files_exist_and_word_count_consistency"] = 1.0 if (total_results == 0 or text_ok) else 0.0
        if total_results == 0 or paths_ok:
            scores["paths_structure_correctness"] = 1.0 if (total_results == 0 or paths_ok) else 0.0

    state_path = workspace / "outputs" / "state" / "processed.json"
    state = None
    entry_key_used = None
    if state_path.exists():
        state = load_json(state_path)
    if isinstance(state, dict):
        if "example_keywords.txt" in state:
            entry_key_used = "example_keywords.txt"
        else:
            if expected_keywords_rel in state:
                entry_key_used = expected_keywords_rel
            else:
                candidates = []
                for k in state.keys():
                    if isinstance(k, str) and k.endswith(expected_keywords_rel):
                        candidates.append(k)
                if len(candidates) == 1:
                    entry_key_used = candidates[0]
        if entry_key_used is not None:
            scores["state_file_exists_and_contains_entry"] = 1.0

    if state and entry_key_used is not None:
        val = state.get(entry_key_used)
        has_sha = False
        sha_value = None
        has_processed_at = False
        if isinstance(val, dict):
            for k, v in val.items():
                if isinstance(k, str) and "sha256" in k.lower() and isinstance(v, str) and is_hex_sha256(v):
                    has_sha = True
                    sha_value = v
                if isinstance(k, str) and "processed_at" in k.lower() and isinstance(v, str) and parse_iso8601_utc(v):
                    has_processed_at = True
        scores["state_sha256_and_processed_at_valid"] = 1.0 if (has_sha and has_processed_at) else 0.0
        if report and "file_sha256" in report and isinstance(report["file_sha256"], str) and is_hex_sha256(report["file_sha256"]):
            if has_sha and sha_value and sha_value.lower() == report["file_sha256"].lower():
                scores["state_report_sha256_consistency"] = 1.0

    log_path = workspace / "outputs" / "logs" / "ingest.log"
    if log_path.exists():
        text = read_text(log_path) or ""
        lines = text.splitlines()
        line = find_ingest_log_line(lines, "example_keywords.txt")
        if line:
            scores["ingest_log_exists_and_contains_entry"] = 1.0
            queries_cnt = 0
            total_urls_cnt = 0
            if report and isinstance(report.get("queries"), list):
                queries_cnt = len(report["queries"])
                total_urls_cnt = 0
                for q in report["queries"]:
                    if isinstance(q, dict) and isinstance(q.get("results"), list):
                        total_urls_cnt += len(q["results"])
            ints = [int(m) for m in re.findall(r"\b\d+\b", line)]
            has_queries_num = (queries_cnt in ints) if queries_cnt else True
            has_urls_num = (total_urls_cnt in ints) if total_urls_cnt else True
            if has_queries_num and has_urls_num:
                scores["ingest_log_counts_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()