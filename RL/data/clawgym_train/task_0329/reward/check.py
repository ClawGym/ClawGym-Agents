import json
import sys
import re
import csv
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from urllib.parse import urlparse
from datetime import datetime
import subprocess


def _read_text(path: Path) -> Optional[str]:
    try:
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        if not path.exists() or not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        if not path.exists() or not path.is_file():
            return None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _file_nonempty(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def _strip_quotes(val: str) -> str:
    val = val.strip()
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    return val


def _parse_kv(line: str) -> Optional[Tuple[str, str]]:
    # Parse YAML-like "key: value" on a single line.
    if ":" not in line:
        return None
    key, val = line.split(":", 1)
    key = key.strip()
    val = _strip_quotes(val.strip())
    if not key:
        return None
    return key, val


def _parse_sources_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser tailored to the provided file structure.
    Supports:
      keywords:
        - item
      sources:
        - slug: ...
          organization: ...
          domain: ...
          title_hint: ...
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    state = None  # None, "keywords", "sources"
    keywords: List[str] = []
    sources: List[Dict[str, str]] = []
    current_item: Optional[Dict[str, str]] = None

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if not line.startswith(" ") and stripped.startswith("keywords:"):
            state = "keywords"
            continue
        if not line.startswith(" ") and stripped.startswith("sources:"):
            state = "sources"
            continue

        if state == "keywords":
            lstr = line.lstrip()
            if lstr.startswith("- "):
                item = _strip_quotes(lstr[2:].strip())
                keywords.append(item)
            else:
                # Unexpected format; fail parsing
                return None
        elif state == "sources":
            lstr = line.lstrip()
            if lstr.startswith("- "):
                # starting a new item, possibly with a first key
                if current_item:
                    sources.append(current_item)
                current_item = {}
                after_dash = lstr[2:].strip()
                if after_dash:
                    kv = _parse_kv(after_dash)
                    if kv:
                        k, v = kv
                        current_item[k] = v
                    else:
                        # Unexpected after dash
                        return None
            else:
                # continuation key: value
                if current_item is None:
                    return None
                kv = _parse_kv(lstr)
                if kv:
                    k, v = kv
                    current_item[k] = v
                else:
                    return None
        else:
            # Unexpected content before any top-level key
            return None

    if state == "sources" and current_item:
        sources.append(current_item)

    # Validate basic structure
    if not isinstance(keywords, list) or not isinstance(sources, list):
        return None
    # Ensure each source has required fields
    for s in sources:
        for req in ["slug", "organization", "domain", "title_hint"]:
            if req not in s or not isinstance(s[req], str):
                return None

    return {"keywords": keywords, "sources": sources}


def _is_iso_like(ts: str) -> bool:
    if not isinstance(ts, str) or not ts:
        return False
    s = ts.strip()
    # Accept 'Z' timezone or +HH:MM offsets
    # Try to parse with datetime.fromisoformat, normalizing Z
    try:
        if s.endswith("Z"):
            s_mod = s[:-1] + "+00:00"
        else:
            s_mod = s
        datetime.fromisoformat(s_mod)
        return True
    except Exception:
        # Fallback regex check
        iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$")
        return bool(iso_re.match(s))


def _tokenize_word_count(text: str) -> int:
    if not text:
        return 0
    # Count sequences of alphanumerics and apostrophes as words
    return len(re.findall(r"\b[A-Za-z0-9']+\b", text))


def _count_currency_tokens(text: str) -> int:
    if not text:
        return 0
    # Match $ followed by numbers with optional commas/decimals and optional scale word
    pattern = re.compile(r"\$\s*\d[\d,]*(?:\.\d+)?(?:\s*(?:million|billion|trillion))?", re.IGNORECASE)
    return len(pattern.findall(text))


def _count_years(text: str) -> int:
    if not text:
        return 0
    pattern = re.compile(r"\b(?:19|20)\d{2}\b")
    return len(pattern.findall(text))


def _compute_metrics(text: str, keywords: List[str]) -> Dict[str, Any]:
    lc = text.lower() if text else ""
    total_word_count = _tokenize_word_count(text or "")
    currency_count = _count_currency_tokens(text or "")
    year_count = _count_years(text or "")
    hits = {}
    for kw in keywords:
        k = kw if isinstance(kw, str) else str(kw)
        hits[k] = (k.lower() in lc)
    return {
        "total_word_count": total_word_count,
        "currency_count": currency_count,
        "year_count": year_count,
        "keyword_hits": hits,
    }


def _get_host(url: str) -> Optional[str]:
    try:
        p = urlparse(url)
        if not p.scheme or not p.netloc:
            return None
        return p.netloc.lower()
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Initialize all scores to 0.0
    scores = {
        "raw_html_files_exist": 0.0,
        "extracted_text_files_exist": 0.0,
        "summary_json_presence_and_structure": 0.0,
        "retrieved_url_https_and_domain": 0.0,
        "keyword_hits_coverage_and_values": 0.0,
        "summary_metrics_match_extracted_text": 0.0,
        "summary_csv_consistency_with_json": 0.0,
        "validator_script_exists": 0.0,
        "validation_log_exists": 0.0,
        "validator_exits_successfully": 0.0,
    }

    # Parse input YAML
    yaml_path = workspace / "input" / "sources.yaml"
    parsed = _parse_sources_yaml(yaml_path)
    if not parsed:
        # Cannot proceed; return zeros
        return scores

    keywords: List[str] = parsed.get("keywords", [])
    sources: List[Dict[str, str]] = parsed.get("sources", [])
    slugs = [s["slug"] for s in sources]

    if not slugs:
        return scores

    # Check raw and extracted files existence
    raw_ok = 0
    ext_ok = 0
    for s in sources:
        slug = s["slug"]
        raw_path = workspace / "workspace" / "raw" / f"{slug}.html"
        ext_path = workspace / "workspace" / "extracted" / f"{slug}.txt"
        if _file_nonempty(raw_path):
            raw_ok += 1
        if _file_nonempty(ext_path):
            ext_ok += 1
    scores["raw_html_files_exist"] = raw_ok / len(slugs)
    scores["extracted_text_files_exist"] = ext_ok / len(slugs)

    # Load summary.json
    summary_json_path = workspace / "workspace" / "report" / "summary.json"
    summary = _read_json(summary_json_path)
    records_by_slug: Dict[str, Dict[str, Any]] = {}
    json_loaded = isinstance(summary, list)
    if json_loaded:
        for rec in summary:
            if isinstance(rec, dict) and "slug" in rec and isinstance(rec["slug"], str):
                records_by_slug[rec["slug"]] = rec

    # Presence and structure: check records exist for all slugs and required fields/types
    struct_hits = 0
    retrieved_url_hits = 0
    keyword_cov_hits = 0
    if json_loaded:
        for s in sources:
            slug = s["slug"]
            rec = records_by_slug.get(slug)
            if not isinstance(rec, dict):
                continue
            # Required fields
            required_fields = [
                "slug",
                "organization",
                "retrieved_url",
                "retrieved_at",
                "total_word_count",
                "currency_count",
                "year_count",
                "keyword_hits",
            ]
            if not all(k in rec for k in required_fields):
                # missing some
                pass
            else:
                # Types and values
                org_ok = isinstance(rec["organization"], str) and rec["organization"] == s["organization"]
                slug_ok = isinstance(rec["slug"], str) and rec["slug"] == slug
                url_ok = isinstance(rec["retrieved_url"], str) and rec["retrieved_url"].startswith("https://")
                ts_ok = isinstance(rec["retrieved_at"], str) and _is_iso_like(rec["retrieved_at"])
                tw_ok = isinstance(rec["total_word_count"], int) and rec["total_word_count"] >= 0
                cc_ok = isinstance(rec["currency_count"], int) and rec["currency_count"] >= 0
                yc_ok = isinstance(rec["year_count"], int) and rec["year_count"] >= 0
                kh_ok = isinstance(rec["keyword_hits"], dict)
                if slug_ok and org_ok and url_ok and ts_ok and tw_ok and cc_ok and yc_ok and kh_ok:
                    struct_hits += 1

                # retrieved_url domain check
                domain = s["domain"].lower()
                retrieved_url = rec.get("retrieved_url", "")
                host = _get_host(retrieved_url) or ""
                if isinstance(retrieved_url, str) and retrieved_url.startswith("https://") and host.endswith(domain):
                    retrieved_url_hits += 1

                # keyword coverage and boolean values
                kh = rec.get("keyword_hits")
                if isinstance(kh, dict):
                    all_present = True
                    all_bool = True
                    for kw in keywords:
                        if kw not in kh:
                            all_present = False
                            break
                        if not isinstance(kh[kw], bool):
                            all_bool = False
                            break
                    if all_present and all_bool:
                        keyword_cov_hits += 1

    scores["summary_json_presence_and_structure"] = struct_hits / len(slugs) if len(slugs) else 0.0
    scores["retrieved_url_https_and_domain"] = retrieved_url_hits / len(slugs) if len(slugs) else 0.0
    scores["keyword_hits_coverage_and_values"] = keyword_cov_hits / len(slugs) if len(slugs) else 0.0

    # Metrics recomputation from extracted text
    metric_match_hits = 0
    for s in sources:
        slug = s["slug"]
        rec = records_by_slug.get(slug)
        if not isinstance(rec, dict):
            continue
        ext_path = workspace / "workspace" / "extracted" / f"{slug}.txt"
        ext_text = _read_text(ext_path)
        if ext_text is None:
            continue
        recomputed = _compute_metrics(ext_text, keywords)
        try:
            tw_match = rec.get("total_word_count") == recomputed["total_word_count"]
            cc_match = rec.get("currency_count") == recomputed["currency_count"]
            yc_match = rec.get("year_count") == recomputed["year_count"]
            kh = rec.get("keyword_hits")
            kh_match = isinstance(kh, dict) and all(k in kh and isinstance(kh[k], bool) and (kh[k] == recomputed["keyword_hits"][k]) for k in keywords)
            if tw_match and cc_match and yc_match and kh_match:
                metric_match_hits += 1
        except Exception:
            pass
    scores["summary_metrics_match_extracted_text"] = metric_match_hits / len(slugs) if len(slugs) else 0.0

    # CSV consistency check
    csv_path = workspace / "workspace" / "report" / "summary.csv"
    csv_rows = _read_csv_dicts(csv_path)
    csv_hits = 0
    if isinstance(csv_rows, list) and json_loaded:
        # Ensure required columns
        required_cols = ["slug", "total_word_count", "currency_count", "year_count"]
        fieldnames = csv_rows[0].keys() if csv_rows else []
        has_required = all(col in fieldnames for col in required_cols)
        if has_required:
            # Build map from slug -> row dict (use last occurrence if duplicates)
            csv_by_slug: Dict[str, Dict[str, str]] = {}
            for row in csv_rows:
                rslug = row.get("slug", "")
                if isinstance(rslug, str):
                    csv_by_slug[rslug] = row
            for s in sources:
                slug = s["slug"]
                row = csv_by_slug.get(slug)
                rec = records_by_slug.get(slug)
                if not row or not isinstance(rec, dict):
                    continue
                try:
                    tw_csv = int(row.get("total_word_count", ""))
                    cc_csv = int(row.get("currency_count", ""))
                    yc_csv = int(row.get("year_count", ""))
                except Exception:
                    continue
                tw_ok = tw_csv == rec.get("total_word_count")
                cc_ok = cc_csv == rec.get("currency_count")
                yc_ok = yc_csv == rec.get("year_count")
                if tw_ok and cc_ok and yc_ok:
                    csv_hits += 1
    scores["summary_csv_consistency_with_json"] = csv_hits / len(slugs) if len(slugs) else 0.0

    # Validator script existence
    validate_script = workspace / "tests" / "validate.py"
    scores["validator_script_exists"] = 1.0 if validate_script.exists() and validate_script.is_file() else 0.0

    # Validation log existence
    validation_log = workspace / "workspace" / "tests" / "validation.log"
    scores["validation_log_exists"] = 1.0 if _file_nonempty(validation_log) else 0.0

    # Run validator to check exit code success (deterministic)
    validator_success = 0.0
    if validate_script.exists() and validate_script.is_file():
        try:
            # Run with working directory set to workspace root
            proc = subprocess.run(
                [sys.executable, str(validate_script)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            if proc.returncode == 0:
                validator_success = 1.0
        except Exception:
            validator_success = 0.0
    scores["validator_exits_successfully"] = validator_success

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()