import csv
import json
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None


def _sha256_bytes(path: Path) -> Optional[str]:
    try:
        data = path.read_bytes()
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return None


def _is_iso8601(s: Any) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        datetime.fromisoformat(t)
        return True
    except Exception:
        return False


def _normalize_term(term: str) -> str:
    t = term.lower()
    t = t.replace(" ", "_")
    t = re.sub(r"[^a-z0-9_]", "", t)
    return t


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the provided config: supports top-level keys with either:
    - scalar values (int or string)
    - lists with '- item' lines
    Does not support nested dicts beyond this.
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    result: Dict[str, Any] = {}
    current_key: Optional[str] = None
    current_list: Optional[List[Any]] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n\r")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current_key is not None and current_list is not None and re.match(r"^\s*-\s+", line):
            item = re.sub(r"^\s*-\s+", "", line).strip()
            if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                item = item[1:-1]
            current_list.append(item)
            continue
        m_list = re.match(r"^([A-Za-z0-9_]+):\s*$", stripped)
        m_kv = re.match(r"^([A-Za-z0-9_]+):\s*(.+)\s*$", stripped)
        if m_list:
            if current_key is not None and current_list is not None:
                result[current_key] = current_list
            current_key = m_list.group(1)
            current_list = []
        elif m_kv:
            if current_key is not None and current_list is not None:
                result[current_key] = current_list
            key = m_kv.group(1)
            val = m_kv.group(2)
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            if re.fullmatch(r"[+-]?\d+", val):
                try:
                    result[key] = int(val)
                except Exception:
                    result[key] = val
            else:
                result[key] = val
            current_key = None
            current_list = None
        else:
            return None
    if current_key is not None and current_list is not None:
        result[current_key] = current_list
    return result


def _expected_csv_header(config: Dict[str, Any]) -> Optional[List[str]]:
    try:
        base_cols = [
            "url",
            "domain",
            "title",
            "saved_html_path",
            "word_count",
            "positive_total",
            "negative_total",
            "ratio_pos_to_neg",
        ]
        pos_terms = config.get("positive_terms", [])
        neg_terms = config.get("negative_terms", [])
        if not isinstance(pos_terms, list) or not isinstance(neg_terms, list):
            return None
        term_cols = []
        for t in pos_terms:
            term_cols.append(f"term_{_normalize_term(str(t))}")
        for t in neg_terms:
            term_cols.append(f"term_{_normalize_term(str(t))}")
        return base_cols + term_cols
    except Exception:
        return None


def _csv_to_numeric(val: str) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        return None


def _csv_to_float(val: str) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _within_tolerance(a: float, b: float, tol: float = 1e-3) -> bool:
    return abs(a - b) <= tol


def _find_readme(workspace: Path) -> Optional[Path]:
    candidates = ["README", "README.md", "README.txt", "Readme.md", "readme.md", "readme"]
    for name in candidates:
        p = workspace / name
        if p.exists() and p.is_file():
            return p
    return None


def _find_tool_code_files(workspace: Path) -> List[Path]:
    exts = [".py", ".sh", ".js", ".ts", ".rb", ".go", ".java"]
    files: List[Path] = []
    for p in workspace.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            rel = p.relative_to(workspace)
            parts = rel.parts
            if len(parts) >= 1 and (parts[0].lower() in {"output", "config"}):
                continue
            files.append(p)
    return files


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "articles_csv_exists_and_header": 0.0,
        "csv_rows_fields_valid_and_ratio": 0.0,
        "saved_html_paths_valid_and_exist": 0.0,
        "stats_json_exists_and_fields": 0.0,
        "stats_config_sha256_matches": 0.0,
        "stats_config_values_echo": 0.0,
        "stats_page_counts_consistent": 0.0,
        "stats_average_word_count_by_domain": 0.0,
        "stats_term_totals_and_overall_totals": 0.0,
        "run_log_exists_and_mentions": 0.0,
        "html_snapshots_count_matches_csv": 0.0,
        "readme_with_instructions": 0.0,
        "tool_code_references_config": 0.0,
    }

    config_path = workspace / "config" / "scrape_config.yaml"
    output_dir = workspace / "output"
    articles_csv = output_dir / "articles.csv"
    stats_json = output_dir / "stats.json"
    run_log = output_dir / "run.log"
    pages_dir = output_dir / "pages"

    config = _parse_simple_yaml(config_path) if config_path.exists() else None
    config_sha = _sha256_bytes(config_path) if config_path.exists() else None

    csv_data = _safe_read_csv(articles_csv)
    expected_header = _expected_csv_header(config) if config else None
    if csv_data and expected_header:
        header, rows = csv_data
        if header == expected_header:
            scores["articles_csv_exists_and_header"] = 1.0

    if csv_data and expected_header:
        header, rows = csv_data
        ok = True
        term_cols = [c for c in header if c.startswith("term_")]
        for row in rows:
            required_fields = ["url", "domain", "title", "saved_html_path", "word_count", "positive_total", "negative_total", "ratio_pos_to_neg"]
            if any(f not in row for f in required_fields):
                ok = False
                break
            wc = _csv_to_numeric(row["word_count"])
            pos_tot = _csv_to_numeric(row["positive_total"])
            neg_tot = _csv_to_numeric(row["negative_total"])
            ratio_val = _csv_to_float(row["ratio_pos_to_neg"])
            if wc is None or wc < 0 or pos_tot is None or pos_tot < 0 or neg_tot is None or neg_tot < 0 or ratio_val is None or ratio_val < 0:
                ok = False
                break
            for tc in term_cols:
                tv = _csv_to_numeric(row.get(tc, ""))
                if tv is None or tv < 0:
                    ok = False
                    break
            if not ok:
                break
            denom = max(1, neg_tot)
            expected_ratio = round(pos_tot / denom, 3)
            if not _within_tolerance(ratio_val, expected_ratio, tol=0.0005):
                ok = False
                break
        if ok:
            scores["csv_rows_fields_valid_and_ratio"] = 1.0

    if csv_data and expected_header:
        header, rows = csv_data
        ok = True
        for row in rows:
            shp = row.get("saved_html_path", "")
            dom = row.get("domain", "")
            shp_path = Path(shp)
            if shp_path.is_absolute():
                ok = False
                break
            if len(shp_path.parts) >= 1 and shp_path.parts[0].lower() == "output":
                ok = False
                break
            if len(shp_path.parts) < 2 or shp_path.parts[0] != dom or not shp_path.suffix.lower() == ".html":
                ok = False
                break
            actual_path = pages_dir / shp_path
            if not actual_path.exists() or not actual_path.is_file():
                ok = False
                break
        if ok:
            scores["saved_html_paths_valid_and_exist"] = 1.0

    stats = _safe_load_json(stats_json)
    if stats and isinstance(stats, dict):
        required_fields = [
            "run_timestamp",
            "config_sha256",
            "domains_used",
            "topics_used",
            "positive_terms_used",
            "negative_terms_used",
            "max_pages_per_domain_used",
            "pages_downloaded_total",
            "pages_downloaded_by_domain",
            "average_word_count_by_domain",
            "term_totals",
            "positive_total",
            "negative_total",
        ]
        if all(k in stats for k in required_fields) and _is_iso8601(stats.get("run_timestamp")):
            scores["stats_json_exists_and_fields"] = 1.0

    if stats and isinstance(stats, dict) and config_sha:
        if stats.get("config_sha256") == config_sha:
            scores["stats_config_sha256_matches"] = 1.0

    if stats and config:
        ok = True
        if stats.get("domains_used") != config.get("allowed_domains"):
            ok = False
        if stats.get("topics_used") != config.get("topics"):
            ok = False
        if stats.get("positive_terms_used") != config.get("positive_terms"):
            ok = False
        if stats.get("negative_terms_used") != config.get("negative_terms"):
            ok = False
        if stats.get("max_pages_per_domain_used") != config.get("max_pages_per_domain"):
            ok = False
        if ok:
            scores["stats_config_values_echo"] = 1.0

    csv_counts_by_domain: Dict[str, int] = {}
    csv_word_counts_by_domain: Dict[str, List[int]] = {}
    csv_term_totals: Dict[str, int] = {}
    csv_overall_pos_total = 0
    csv_overall_neg_total = 0
    if csv_data and expected_header:
        header, rows = csv_data
        term_cols = [c for c in header if c.startswith("term_")]
        for t in term_cols:
            csv_term_totals[t.replace("term_", "", 1)] = 0
        for row in rows:
            dom = row.get("domain", "")
            csv_counts_by_domain[dom] = csv_counts_by_domain.get(dom, 0) + 1
            wc = _csv_to_numeric(row.get("word_count", "0")) or 0
            csv_word_counts_by_domain.setdefault(dom, []).append(wc)
            for t in term_cols:
                n = _csv_to_numeric(row.get(t, "0"))
                if n is None:
                    n = 0
                key = t.replace("term_", "", 1)
                csv_term_totals[key] = csv_term_totals.get(key, 0) + n
            pt = _csv_to_numeric(row.get("positive_total", "0")) or 0
            nt = _csv_to_numeric(row.get("negative_total", "0")) or 0
            csv_overall_pos_total += pt
            csv_overall_neg_total += nt

    if stats and isinstance(stats, dict) and config and csv_data:
        header, rows = csv_data
        ok = True
        pages_downloaded_total = stats.get("pages_downloaded_total")
        pages_by_domain = stats.get("pages_downloaded_by_domain", {})
        allowed_domains = config.get("allowed_domains", [])
        if not isinstance(pages_downloaded_total, int) or pages_downloaded_total < 0:
            ok = False
        if pages_downloaded_total != len(rows):
            ok = False
        if not isinstance(pages_by_domain, dict):
            ok = False
        else:
            for dom in allowed_domains:
                if dom not in pages_by_domain:
                    ok = False
                    break
                if pages_by_domain.get(dom) != csv_counts_by_domain.get(dom, 0):
                    ok = False
                    break
            if sum(pages_by_domain.values()) != pages_downloaded_total:
                ok = False
        if ok:
            scores["stats_page_counts_consistent"] = 1.0

    if stats and isinstance(stats, dict) and config and csv_data:
        ok = True
        awc = stats.get("average_word_count_by_domain", {})
        if not isinstance(awc, dict):
            ok = False
        else:
            for dom in config.get("allowed_domains", []):
                expected = 0.0
                if dom in csv_word_counts_by_domain and len(csv_word_counts_by_domain[dom]) > 0:
                    lst = csv_word_counts_by_domain[dom]
                    expected = sum(lst) / len(lst)
                reported = awc.get(dom, 0.0)
                try:
                    reported_f = float(reported)
                except Exception:
                    ok = False
                    break
                if not _within_tolerance(reported_f, expected, tol=0.01):
                    ok = False
                    break
        if ok:
            scores["stats_average_word_count_by_domain"] = 1.0

    if stats and isinstance(stats, dict) and config and csv_data and expected_header:
        ok = True
        term_totals = stats.get("term_totals")
        if not isinstance(term_totals, dict):
            ok = False
        else:
            expected_terms = []
            for t in config.get("positive_terms", []):
                expected_terms.append(_normalize_term(str(t)))
            for t in config.get("negative_terms", []):
                expected_terms.append(_normalize_term(str(t)))
            for nt in expected_terms:
                if nt not in term_totals:
                    ok = False
                    break
                if term_totals.get(nt) != csv_term_totals.get(nt, 0):
                    ok = False
                    break
        if ok:
            pos_all = stats.get("positive_total")
            neg_all = stats.get("negative_total")
            if pos_all != csv_overall_pos_total or neg_all != csv_overall_neg_total:
                ok = False
        if ok:
            scores["stats_term_totals_and_overall_totals"] = 1.0

    log_text = _safe_read_text(run_log)
    if log_text is not None and config:
        lt = log_text.lower()
        ok = True
        for dom in config.get("allowed_domains", []):
            if dom.lower() not in lt:
                ok = False
                break
        keywords = ["sitemap", "candidate", "filtered", "downloaded", "skipped"]
        if not any(k in lt for k in keywords):
            ok = False
        if ok:
            scores["run_log_exists_and_mentions"] = 1.0

    if csv_data:
        header, rows = csv_data
        ok = True
        count_existing = 0
        for row in rows:
            shp = row.get("saved_html_path", "")
            actual_path = pages_dir / Path(shp)
            if actual_path.exists() and actual_path.is_file():
                count_existing += 1
        if count_existing == len(rows):
            scores["html_snapshots_count_matches_csv"] = 1.0

    readme = _find_readme(workspace)
    if readme:
        txt = _safe_read_text(readme) or ""
        lt = txt.lower()
        cond_config = "config/scrape_config.yaml" in lt or "scrape_config.yaml" in lt
        cond_output = "output" in lt
        cond_run = "python" in lt or "run" in lt or "command" in lt or "cli" in lt
        if cond_config and cond_output and cond_run:
            scores["readme_with_instructions"] = 1.0

    code_files = _find_tool_code_files(workspace)
    found_ref = False
    for cf in code_files:
        txt = _safe_read_text(cf)
        if txt is None:
            continue
        lt = txt.lower()
        if "scrape_config.yaml" in lt or ("yaml" in lt and "config" in lt):
            found_ref = True
            break
    if found_ref:
        scores["tool_code_references_config"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()