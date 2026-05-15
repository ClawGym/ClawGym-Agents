import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, []
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, []


def parse_priorities(path: Path):
    headers, rows = load_csv_dicts(path)
    if not headers or "keyword" not in headers or "weight" not in headers:
        return None
    priorities = {}
    for r in rows:
        try:
            kw = (r.get("keyword") or "").strip()
            wt = float(r.get("weight"))
            if kw:
                priorities[kw] = wt
        except Exception:
            return None
    return priorities


def parse_iso_datetime(value: str):
    if not value:
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        pass
    fmts = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def find_line_with_tokens(text: str, include_tokens):
    lines = text.splitlines()
    for line in lines:
        l = line.lower()
        if all(tok.lower() in l for tok in include_tokens):
            return True
    return False


def contains_any(text: str, tokens):
    tl = text.lower()
    return any(tok.lower() in tl for tok in tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "logs_present_analysis": 0.0,
        "network_analysis_floyd_line": 0.0,
        "network_analysis_dor_line": 0.0,
        "download_dirs_exist": 0.0,
        "floyd_sitemap_attempt_recorded_or_file": 0.0,
        "dor_robots_attempt_recorded_or_file": 0.0,
        "dor_sitemap_attempt_recorded_or_file": 0.0,
        "urls_csv_structure": 0.0,
        "urls_csv_domain_netloc_consistency": 0.0,
        "flagged_csv_structure": 0.0,
        "flagged_keywords_and_scoring": 0.0,
        "flagged_rows_have_matches": 0.0,
        "top20_structure": 0.0,
        "top20_ranking_correctness": 0.0,
        "summary_required_content": 0.0,
    }

    logs_dir = workspace / "logs"
    network_log = logs_dir / "network_check.txt"
    errors_log = logs_dir / "errors.log"

    floyd_dir = workspace / "data" / "downloaded" / "floyd"
    dor_dir = workspace / "data" / "downloaded" / "dor"

    urls_csv = workspace / "data" / "processed" / "urls.csv"
    flagged_csv = workspace / "data" / "processed" / "flagged.csv"

    top20_csv = workspace / "reports" / "top20.csv"
    summary_md = workspace / "reports" / "summary.md"

    priorities_csv = workspace / "input" / "priorities.csv"

    network_text = read_text_safe(network_log) if network_log.exists() else ""
    errors_text = read_text_safe(errors_log) if errors_log.exists() else ""

    domains_present = ("floydcountyga.gov" in network_text) and ("dor.georgia.gov" in network_text)
    analysis_tokens = ["http", "status", "ping", "curl", "reachable", "unreachable", "exit code", "exit_code", "success", "failure"]
    analysis_present = contains_any(network_text, analysis_tokens)

    if network_log.exists() and errors_log.exists() and domains_present and analysis_present:
        scores["logs_present_analysis"] = 1.0

    floyd_line = find_line_with_tokens(network_text, ["floydcountyga.gov"]) and contains_any(
        "\n".join([l for l in network_text.splitlines() if "floydcountyga.gov" in l]),
        analysis_tokens,
    )
    if floyd_line:
        scores["network_analysis_floyd_line"] = 1.0

    dor_line = find_line_with_tokens(network_text, ["dor.georgia.gov"]) and contains_any(
        "\n".join([l for l in network_text.splitlines() if "dor.georgia.gov" in l]),
        analysis_tokens,
    )
    if dor_line:
        scores["network_analysis_dor_line"] = 1.0

    if floyd_dir.is_dir() and dor_dir.is_dir():
        scores["download_dirs_exist"] = 1.0

    floyd_sitemap = floyd_dir / "sitemap.xml"
    floyd_attempt_logged = False
    if errors_text:
        floyd_attempt_logged = find_line_with_tokens(errors_text, ["floyd", "sitemap"])
    if floyd_sitemap.exists() or floyd_attempt_logged:
        scores["floyd_sitemap_attempt_recorded_or_file"] = 1.0

    dor_robots = dor_dir / "robots.txt"
    dor_robots_logged = False
    if errors_text:
        dor_robots_logged = find_line_with_tokens(errors_text, ["dor", "robots"])
    if dor_robots.exists() or dor_robots_logged:
        scores["dor_robots_attempt_recorded_or_file"] = 1.0

    dor_sitemap = dor_dir / "sitemap.xml"
    dor_sitemap_logged = False
    if errors_text:
        dor_sitemap_logged = find_line_with_tokens(errors_text, ["dor", "sitemap"])
    if dor_sitemap.exists() or dor_sitemap_logged:
        scores["dor_sitemap_attempt_recorded_or_file"] = 1.0

    urls_headers, urls_rows = load_csv_dicts(urls_csv)
    if urls_headers == ["domain", "url", "lastmod", "source_file"]:
        scores["urls_csv_structure"] = 1.0

    if urls_headers:
        total = len(urls_rows)
        if total == 0:
            scores["urls_csv_domain_netloc_consistency"] = 1.0
        else:
            consistent = 0
            for r in urls_rows:
                dom = (r.get("domain") or "").strip()
                url = (r.get("url") or "").strip()
                try:
                    netloc = urlparse(url).netloc
                except Exception:
                    netloc = ""
                if dom == netloc or netloc.endswith(dom):
                    consistent += 1
            scores["urls_csv_domain_netloc_consistency"] = consistent / total if total > 0 else 0.0

    flagged_headers, flagged_rows = load_csv_dicts(flagged_csv)
    if flagged_headers == ["domain", "url", "matched_keywords", "score", "lastmod"]:
        scores["flagged_csv_structure"] = 1.0

    priorities = parse_priorities(priorities_csv) if priorities_csv.exists() else None
    if priorities is not None and flagged_headers:
        total = len(flagged_rows)
        if total == 0:
            scores["flagged_keywords_and_scoring"] = 1.0
            scores["flagged_rows_have_matches"] = 1.0
        else:
            correct = 0
            matched_nonempty = 0
            for r in flagged_rows:
                url = (r.get("url") or "").lower()
                mk_field = r.get("matched_keywords") or ""
                score_str = (r.get("score") or "").strip()
                try:
                    score_val = float(score_str)
                except Exception:
                    score_val = None
                expected_matches = set()
                for kw, wt in priorities.items():
                    if kw.lower() in url:
                        expected_matches.add(kw)
                expected_score = sum(priorities[kw] for kw in expected_matches)
                provided_set = set()
                if mk_field.strip():
                    provided_set = set([s.strip() for s in mk_field.split(";") if s.strip()])
                if expected_matches and expected_matches == provided_set and score_val is not None and abs(score_val - expected_score) < 1e-6:
                    correct += 1
                if expected_matches:
                    matched_nonempty += 1
            scores["flagged_keywords_and_scoring"] = (correct / total) if total > 0 else 0.0
            scores["flagged_rows_have_matches"] = (matched_nonempty / total) if total > 0 else 0.0

    top20_headers, top20_rows = load_csv_dicts(top20_csv)
    if top20_headers:
        required_cols = {"domain", "url", "score", "lastmod"}
        if required_cols.issubset(set(top20_headers)):
            scores["top20_structure"] = 1.0

    if flagged_headers and top20_headers and priorities is not None:
        try:
            def row_to_tuple(r):
                d = r.get("domain") or ""
                u = r.get("url") or ""
                s_str = (r.get("score") or "").strip()
                try:
                    s_val = float(s_str)
                except Exception:
                    s_val = float("-inf")
                lm = r.get("lastmod") or ""
                lm_dt = parse_iso_datetime(lm)
                return (d, u, s_val, lm_dt if lm_dt is not None else None)

            flagged_tuples = [row_to_tuple(r) for r in flagged_rows]

            def sort_key(t):
                score = t[2]
                lm_dt = t[3] if t[3] is not None else datetime.min
                return (-score, -lm_dt.timestamp())

            expected_sorted = sorted(flagged_tuples, key=sort_key)
            expected_top = expected_sorted[: min(20, len(expected_sorted))]
            expected_pairs = [(d, u) for (d, u, _, _) in expected_top]

            top_pairs = []
            for r in top20_rows:
                d = r.get("domain") or ""
                u = r.get("url") or ""
                top_pairs.append((d, u))

            if len(expected_pairs) == 0 and len(top_pairs) == 0:
                scores["top20_ranking_correctness"] = 1.0
            elif len(expected_pairs) > 0:
                compare_len = min(len(expected_pairs), len(top_pairs))
                if compare_len == 0:
                    scores["top20_ranking_correctness"] = 0.0
                else:
                    matches = sum(1 for i in range(compare_len) if expected_pairs[i] == top_pairs[i])
                    length_ok = len(top_pairs) <= 20 and len(top_pairs) <= len(expected_pairs)
                    scores["top20_ranking_correctness"] = (matches / compare_len) * (1.0 if length_ok else 0.0)
        except Exception:
            scores["top20_ranking_correctness"] = 0.0

    summary_text = read_text_safe(summary_md) if summary_md.exists() else ""
    if summary_text:
        has_domains = ("floydcountyga.gov" in summary_text) and ("dor.georgia.gov" in summary_text)
        has_reachability = contains_any(summary_text, ["reachable", "unreachable"])
        has_downloads = contains_any(summary_text, ["download", "downloaded"]) and contains_any(summary_text, ["file", "files"])
        has_total_urls = contains_any(summary_text, ["total"]) and contains_any(summary_text, ["url", "urls"])
        has_flagged = contains_any(summary_text, ["flagged"])
        has_keywords = contains_any(summary_text, ["keyword", "keywords"])
        has_errors_ref = contains_any(summary_text, ["errors.log", "logs/errors.log"])
        has_status = contains_any(summary_text, ["non-2xx", "2xx", "status"])
        if all([has_domains, has_reachability, has_downloads, has_total_urls, has_flagged, has_keywords, has_errors_ref, has_status]):
            scores["summary_required_content"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()