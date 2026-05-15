import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Tuple, List, Dict, Optional, Any


ORIGINAL_CONFIG = {
    "title": "Birth Resources by Nana Doula",
    "disclaimer_text": "",
    "required_metadata": ["title", "author", "updated"],
    "topics": [
        "birth plan",
        "postpartum hemorrhage",
        "skin-to-skin contact"
    ],
    "organizations": [
        "who.int",
        "cdc.gov",
        "acog.org"
    ],
    "build": {
        "output_dir": "dist"
    }
}


def _safe_read_text(path: Path) -> Tuple[str, str]:
    try:
        return path.read_text(encoding="utf-8"), ""
    except Exception as e:
        return "", f"{e}"


def _safe_load_json(path: Path) -> Tuple[Optional[Any], str]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), ""
    except Exception as e:
        return None, f"{e}"


def _safe_load_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], str, Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, "", list(reader.fieldnames) if reader.fieldnames is not None else []
    except Exception as e:
        return None, f"{e}", None


def _parse_iso8601(s: str) -> bool:
    try:
        st = s
        if s.endswith("Z"):
            st = s[:-1] + "+00:00"
        datetime.fromisoformat(st)
        return True
    except Exception:
        return False


def _list_article_files(workspace: Path) -> List[Path]:
    articles_dir = workspace / "input" / "articles"
    if not articles_dir.exists():
        return []
    return sorted(articles_dir.glob("*.md"))


def _parse_front_matter(md_text: str) -> Dict[str, bool]:
    fm: Dict[str, bool] = {}
    lines = md_text.splitlines()
    if not lines:
        return fm
    if lines[0].strip() != "---":
        return fm
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return fm
    block = lines[1:end_idx]
    for line in block:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _sep, _val = line.partition(":")
            key = key.strip().strip('"').strip("'")
            if key:
                fm[key] = True
    return fm


def _compute_missing_metadata(workspace: Path, required_fields: List[str]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for path in _list_article_files(workspace):
        text, _ = _safe_read_text(path)
        fm = _parse_front_matter(text)
        missing = [fld for fld in required_fields if fld not in fm]
        result[path.name] = sorted(missing)
    return result


def _get_expected_dist_files(workspace: Path, output_dir_name: Optional[str] = None) -> List[Path]:
    cfg_path = workspace / "input" / "config.json"
    cfg, _ = _safe_load_json(cfg_path)
    if isinstance(cfg, dict):
        outdir = cfg.get("build", {}).get("output_dir", "dist")
    else:
        outdir = output_dir_name or "dist"
    outdir_path = workspace / outdir
    expected: List[Path] = []
    for art in _list_article_files(workspace):
        expected.append(outdir_path / (art.stem + ".txt"))
    return expected


def _build_script_uses_disclaimer_heuristic(build_text: str) -> bool:
    # Must reference disclaimer_text from cfg and write it before body to output
    lower = build_text.lower()
    # Look for access to cfg['disclaimer_text'] or cfg.get('disclaimer_text')
    disclaimer_access = re.search(r"cfg\s*\[\s*['\"]disclaimer_text['\"]\s*\]", build_text) or re.search(
        r"cfg\.get\(\s*['\"]disclaimer_text['\"]", build_text
    )
    # Extract all write calls
    writes = re.findall(r"fout\.write\((.*?)\)", build_text, flags=re.DOTALL)
    writes_lower = [w.lower() for w in writes]
    # Check ordering: disclaimer before body
    concatenates = any(("disclaimer" in w and "body" in w and w.find("disclaimer") < w.find("body")) for w in writes_lower)
    two_writes_in_order = False
    if len(writes_lower) >= 2:
        if "disclaimer" in writes_lower[0] and "body" in writes_lower[1]:
            two_writes_in_order = True
    return bool(disclaimer_access and (concatenates or two_writes_in_order))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_disclaimer_present_and_quality": 0.0,
        "config_fields_intact": 0.0,
        "build_script_uses_disclaimer_text": 0.0,
        "built_files_exist": 0.0,
        "built_files_begin_with_disclaimer": 0.0,
        "validator_script_presence_and_intent": 0.0,
        "metadata_report_matches_computed": 0.0,
        "disclaimer_report_matches_files": 0.0,
        "external_resources_queries_complete_and_structured": 0.0,
        "summary_csv_counts_consistent": 0.0,
    }

    # Load config
    cfg_path = workspace / "input" / "config.json"
    cfg, _ = _safe_load_json(cfg_path)
    disclaimer_nonempty = False
    if isinstance(cfg, dict):
        disclaimer = cfg.get("disclaimer_text", "")
        if isinstance(disclaimer, str) and disclaimer.strip():
            dlow = disclaimer.strip().lower()
            educ = "educat" in dlow
            not_medical_advice_phrase = "not medical advice" in dlow
            has_components = all(x in dlow for x in ("not", "substitute", "medical", "advice"))
            if educ and (not_medical_advice_phrase or has_components):
                scores["config_disclaimer_present_and_quality"] = 1.0
                disclaimer_nonempty = True
        # Check other fields intact ONLY in the context of having set a non-empty disclaimer_text
        if disclaimer_nonempty:
            intact = True
            for key, expected in ORIGINAL_CONFIG.items():
                if key == "disclaimer_text":
                    continue
                actual = cfg.get(key, None)
                if actual != expected:
                    intact = False
                    break
            scores["config_fields_intact"] = 1.0 if intact else 0.0

    # Check build script update (static heuristic)
    build_script = workspace / "input" / "build_pages.py"
    build_text, _ = _safe_read_text(build_script)
    if build_text:
        if _build_script_uses_disclaimer_heuristic(build_text):
            scores["build_script_uses_disclaimer_text"] = 1.0

    # Built files existence and disclaimer prefix
    expected_dist_files = _get_expected_dist_files(workspace)
    if expected_dist_files:
        all_exist = all(p.exists() for p in expected_dist_files)
        scores["built_files_exist"] = 1.0 if all_exist else 0.0
        if isinstance(cfg, dict) and isinstance(cfg.get("disclaimer_text", ""), str) and cfg.get("disclaimer_text", ""):
            if all_exist:
                disc_text = cfg.get("disclaimer_text", "")
                all_have = True
                for p in expected_dist_files:
                    content, _ = _safe_read_text(p)
                    if not content.startswith(disc_text):
                        all_have = False
                        break
                scores["built_files_begin_with_disclaimer"] = 1.0 if all_have else 0.0

    # Validator script presence and intent
    validator = workspace / "tests" / "validate_site.py"
    vtext, _ = _safe_read_text(validator)
    if vtext:
        mentions_builder = ("input/build_pages.py" in vtext) or ("build_pages" in vtext)
        mentions_reports = all(s in vtext for s in [
            "reports/metadata_report.json",
            "reports/disclaimer_check.json",
            "reports/external_resources.json",
            "reports/summary.csv"
        ])
        mentions_query_pattern = ("site:" in vtext) and ("guidelines childbirth" in vtext)
        mentions_http = ("http://" in vtext) or ("https://" in vtext)
        rebuilds_dist = ("dist" in vtext) and ("subprocess" in vtext or "os.system" in vtext or "run(" in vtext.lower())
        if mentions_builder and mentions_reports and mentions_query_pattern and mentions_http and rebuilds_dist:
            scores["validator_script_presence_and_intent"] = 1.0

    # Load reports and validate against workspace data
    required_fields: List[str] = []
    if isinstance(cfg, dict):
        r = cfg.get("required_metadata")
        if isinstance(r, list):
            required_fields = r
    expected_missing = _compute_missing_metadata(workspace, required_fields) if required_fields else {}

    # metadata_report.json
    metadata_report_path = workspace / "reports" / "metadata_report.json"
    metadata_report, _ = _safe_load_json(metadata_report_path)
    metadata_ok = False
    if isinstance(metadata_report, list) and expected_missing:
        report_map: Dict[str, List[str]] = {}
        try:
            for item in metadata_report:
                if not isinstance(item, dict):
                    raise ValueError("report item not dict")
                fname = item.get("filename")
                missing = item.get("missing_fields")
                if not isinstance(fname, str) or not isinstance(missing, list):
                    raise ValueError("bad fields")
                base = Path(fname).name
                report_map[base] = sorted([str(x) for x in missing])
            if set(report_map.keys()) == set(expected_missing.keys()):
                consistent = True
                for k, v in expected_missing.items():
                    if report_map.get(k, None) != v:
                        consistent = False
                        break
                metadata_ok = consistent
        except Exception:
            metadata_ok = False
    scores["metadata_report_matches_computed"] = 1.0 if metadata_ok else 0.0

    # disclaimer_check.json
    disclaimer_report_path = workspace / "reports" / "disclaimer_check.json"
    disclaimer_report, _ = _safe_load_json(disclaimer_report_path)
    disclaimer_ok = False
    if isinstance(disclaimer_report, list) and expected_dist_files:
        rep_map: Dict[str, bool] = {}
        try:
            for item in disclaimer_report:
                if not isinstance(item, dict):
                    raise ValueError("report item not dict")
                fname = item.get("filename")
                has_disclaimer = item.get("has_disclaimer")
                if not isinstance(fname, str) or not isinstance(has_disclaimer, bool):
                    raise ValueError("bad fields")
                base = Path(fname).name
                rep_map[base] = has_disclaimer
            expected_basenames = [p.name for p in expected_dist_files]
            if set(rep_map.keys()) == set(expected_basenames):
                all_match = True
                disc_text = cfg.get("disclaimer_text", "") if isinstance(cfg, dict) else ""
                for p in expected_dist_files:
                    content, _ = _safe_read_text(p)
                    actual = content.startswith(disc_text) if disc_text else False
                    if rep_map.get(p.name, None) != actual:
                        all_match = False
                        break
                disclaimer_ok = all_match
        except Exception:
            disclaimer_ok = False
    scores["disclaimer_report_matches_files"] = 1.0 if disclaimer_ok else 0.0

    # external_resources.json
    ext_report_path = workspace / "reports" / "external_resources.json"
    ext_report, _ = _safe_load_json(ext_report_path)
    ext_ok = False
    if isinstance(ext_report, dict) and isinstance(cfg, dict):
        engine = ext_report.get("engine")
        queried_at = ext_report.get("queried_at")
        queries = ext_report.get("queries")
        if isinstance(engine, str) and engine.strip() and isinstance(queries, list) and isinstance(queried_at, str):
            ts_ok = _parse_iso8601(queried_at)
            topics = cfg.get("topics", [])
            orgs = cfg.get("organizations", [])
            expected_pairs = {(t, d) for t in topics for d in orgs}
            seen_pairs = set()
            structured_ok = True
            try:
                for q in queries:
                    if not isinstance(q, dict):
                        structured_ok = False
                        break
                    topic = q.get("topic")
                    domain = q.get("domain")
                    query_str = q.get("query")
                    results = q.get("results")
                    if not isinstance(topic, str) or not isinstance(domain, str) or not isinstance(query_str, str) or not isinstance(results, list):
                        structured_ok = False
                        break
                    expected_query = f"site:{domain} {topic} guidelines childbirth"
                    if query_str != expected_query:
                        structured_ok = False
                        break
                    if not (0 <= len(results) <= 3):
                        structured_ok = False
                        break
                    for r in results:
                        if not isinstance(r, dict):
                            structured_ok = False
                            break
                        title = r.get("title")
                        url = r.get("url")
                        if not isinstance(title, str) or not isinstance(url, str):
                            structured_ok = False
                            break
                    if not structured_ok:
                        break
                    seen_pairs.add((topic, domain))
                if structured_ok and ts_ok and seen_pairs == expected_pairs:
                    ext_ok = True
            except Exception:
                ext_ok = False
    scores["external_resources_queries_complete_and_structured"] = 1.0 if ext_ok else 0.0

    # summary.csv
    summary_csv_path = workspace / "reports" / "summary.csv"
    rows, rows_err, headers = _safe_load_csv_dicts(summary_csv_path)
    summary_ok = False
    if isinstance(rows, list) and rows and headers:
        if len(rows) == 1:
            row = rows[0]
            required_cols = [
                "total_articles",
                "articles_with_complete_metadata",
                "articles_with_disclaimer",
                "total_query_pairs",
                "query_pairs_with_results",
            ]
            if all(col in row for col in required_cols):
                total_articles = len(_list_article_files(workspace))
                complete_meta = 0
                if required_fields:
                    missing_map = _compute_missing_metadata(workspace, required_fields)
                    complete_meta = sum(1 for v in missing_map.values() if len(v) == 0)
                built_files = _get_expected_dist_files(workspace)
                disc_text = cfg.get("disclaimer_text", "") if isinstance(cfg, dict) else ""
                articles_with_disclaimer = 0
                for p in built_files:
                    content, _ = _safe_read_text(p)
                    if disc_text and content.startswith(disc_text):
                        articles_with_disclaimer += 1
                total_query_pairs = 0
                if isinstance(cfg, dict):
                    total_query_pairs = len(cfg.get("topics", [])) * len(cfg.get("organizations", []))
                ext = ext_report if isinstance(ext_report, dict) else None
                query_pairs_with_results = 0
                if ext and isinstance(ext.get("queries"), list):
                    for q in ext["queries"]:
                        res = q.get("results", [])
                        if isinstance(res, list) and len(res) >= 1:
                            query_pairs_with_results += 1
                try:
                    ok = (
                        int(row["total_articles"]) == total_articles and
                        int(row["articles_with_complete_metadata"]) == complete_meta and
                        int(row["articles_with_disclaimer"]) == articles_with_disclaimer and
                        int(row["total_query_pairs"]) == total_query_pairs and
                        int(row["query_pairs_with_results"]) == query_pairs_with_results
                    )
                    summary_ok = ok
                except Exception:
                    summary_ok = False
    scores["summary_csv_counts_consistent"] = 1.0 if summary_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()