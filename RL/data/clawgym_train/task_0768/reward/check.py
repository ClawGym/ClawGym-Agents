import sys
import json
import re
import hashlib
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urlparse


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl(path: Path):
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None
    items = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            return None
        items.append(obj)
    return items if items else None


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _is_iso_date_or_year(value: str) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip()
    if re.fullmatch(r"\d{4}", v):
        return True
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        try:
            y, m, d = v.split("-")
            date(int(y), int(m), int(d))
            return True
        except Exception:
            return False
    return False


def _is_iso_timestamp(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        datetime.fromisoformat(v)
        return True
    except Exception:
        return False


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _clean_site_token(token: str) -> str:
    t = token.strip()
    t = t.strip("()[]{}")
    t = t.strip(",.;")
    t = _strip_quotes(t)
    return t.strip()


def _parse_config_search_yml(text: str):
    if not text:
        return None
    allowed_domains = []
    queries = []
    output = {}
    section = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("allowed_domains:"):
            section = "allowed_domains"
            continue
        if stripped.startswith("queries:"):
            section = "queries"
            continue
        if stripped.startswith("output:"):
            section = "output"
            continue
        if section in ("allowed_domains", "queries") and stripped.startswith("-"):
            item = stripped[1:].strip()
            item = _strip_quotes(item)
            if section == "allowed_domains":
                if item:
                    allowed_domains.append(item)
            else:
                if item or item == "":
                    queries.append(item)
            continue
        if section == "output" and ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = _strip_quotes(val.strip())
            output[key] = val
            continue
    return {"allowed_domains": allowed_domains, "queries": queries, "output": output}


def _parse_targets_eo_numbers(text: str):
    if not text:
        return None
    nums = []
    for line in text.splitlines():
        m = re.search(r"\beo_number\s*:\s*(\d+)\b", line)
        if m:
            try:
                nums.append(int(m.group(1)))
            except Exception:
                return None
    if not nums:
        return None
    return nums


def _get_netloc(url: str) -> str:
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        if ":" in host:
            host = host.split(":", 1)[0]
        return host
    except Exception:
        return ""


def _domain_allowed(host: str, allowed_roots: list) -> bool:
    h = (host or "").lower()
    for r in allowed_roots or []:
        rr = (r or "").lower()
        if not rr:
            continue
        if h == rr or h.endswith("." + rr):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_allowed_domains_unchanged": 0.0,
        "config_output_paths_unchanged": 0.0,
        "config_queries_count_and_presence": 0.0,
        "config_queries_site_restricted_valid": 0.0,
        "scripts_directory_and_code_present": 0.0,
        "manifest_exists_and_structure": 0.0,
        "manifest_records_match_targets": 1.0 * 0.0,
        "docs_files_exist_and_named_correctly": 0.0,
        "manifest_file_metadata_valid": 0.0,
        "manifest_source_fields_valid": 0.0,
        "search_log_exists_and_structure": 0.0,
        "search_log_queries_match_config": 0.0,
        "search_log_candidates_domains_allowed": 0.0,
        "search_log_per_eo_coverage": 0.0,
    }

    expected_allowed_domains = ["archives.gov", "federalregister.gov"]
    expected_output = {
        "docs_dir": "output/docs",
        "manifest": "output/eo_manifest.json",
        "search_log": "output/search_log.jsonl",
    }

    targets_yaml_path = workspace / "input" / "targets.yaml"
    targets_text = _read_text(targets_yaml_path)
    targets_numbers = _parse_targets_eo_numbers(targets_text) if targets_text else None

    config_yaml_path = workspace / "config" / "search.yml"
    config_text = _read_text(config_yaml_path)
    config = _parse_config_search_yml(config_text) if config_text else None

    queries_populated = False
    queries_site_ok = False

    if config and isinstance(config.get("queries"), list) and targets_numbers:
        queries = config["queries"]
        # count and presence: must equal number of targets and each be non-empty string and contain EO number
        if len(queries) == len(targets_numbers) and all(isinstance(q, str) and q.strip() for q in queries):
            target_set = set(targets_numbers)
            numbers_in_queries = set()
            for q in queries:
                for eo in target_set:
                    if str(eo) in q:
                        numbers_in_queries.add(eo)
            if numbers_in_queries == target_set:
                queries_populated = True
                scores["config_queries_count_and_presence"] = 1.0

    if queries_populated and config:
        # only award domain/output settings intact when queries are properly populated (prevents baseline credit)
        if config.get("allowed_domains") == expected_allowed_domains:
            scores["config_allowed_domains_unchanged"] = 1.0
        if config.get("output") == expected_output:
            scores["config_output_paths_unchanged"] = 1.0

    if queries_populated and config and isinstance(config.get("queries"), list) and config.get("allowed_domains"):
        queries = config["queries"]
        allowed_roots = config["allowed_domains"]
        all_ok = True
        for q in queries:
            if not isinstance(q, str) or not q.strip():
                all_ok = False
                break
            sites = re.findall(r"(?<!\w)site:([^\s]+)", q)
            if not sites:
                all_ok = False
                break
            for s in sites:
                s_clean = _clean_site_token(s)
                if not _domain_allowed(s_clean, allowed_roots):
                    all_ok = False
                    break
            if not all_ok:
                break
        if all_ok:
            queries_site_ok = True
            scores["config_queries_site_restricted_valid"] = 1.0

    scripts_dir = workspace / "scripts"
    if scripts_dir.exists() and scripts_dir.is_dir():
        py_files = list(scripts_dir.rglob("*.py"))
        if len(py_files) >= 1:
            scores["scripts_directory_and_code_present"] = 1.0

    manifest_path = workspace / expected_output["manifest"]
    manifest = _load_json(manifest_path)

    if isinstance(manifest, list) and len(manifest) > 0:
        required_fields = {
            "eo_number": int,
            "title": str,
            "publication_date": str,
            "issuing_president": (str, type(None)),
            "source_url": str,
            "source_domain": str,
            "source_type": str,
            "downloaded_file_path": str,
            "sha256": str,
            "byte_size": int,
            "retrieved_at": str,
        }
        struct_ok = True
        for rec in manifest:
            if not isinstance(rec, dict):
                struct_ok = False
                break
            for k, typ in required_fields.items():
                if k not in rec or not isinstance(rec[k], typ):
                    struct_ok = False
                    break
            if not struct_ok:
                break
            if not rec["title"].strip():
                struct_ok = False
                break
            if not re.fullmatch(r"[0-9a-fA-F]{64}", rec["sha256"] or ""):
                struct_ok = False
                break
            if not isinstance(rec["byte_size"], int) or rec["byte_size"] <= 0:
                struct_ok = False
                break
            if not _is_iso_timestamp(rec["retrieved_at"]):
                struct_ok = False
                break
            if not _is_iso_date_or_year(rec["publication_date"]):
                struct_ok = False
                break
            if isinstance(rec["issuing_president"], str) and not rec["issuing_president"].strip():
                struct_ok = False
                break
            if rec["source_type"] not in ("html", "pdf"):
                struct_ok = False
                break
            dpath = rec["downloaded_file_path"]
            if not dpath or Path(dpath).is_absolute():
                struct_ok = False
                break
        if struct_ok:
            scores["manifest_exists_and_structure"] = 1.0

    if isinstance(manifest, list) and targets_numbers:
        manifest_eos = []
        valid = True
        for rec in manifest:
            eo = rec.get("eo_number")
            if not isinstance(eo, int):
                valid = False
                break
            manifest_eos.append(eo)
        if valid and set(manifest_eos) == set(targets_numbers) and len(manifest_eos) == len(targets_numbers):
            scores["manifest_records_match_targets"] = 1.0

    docs_ok = True
    if isinstance(manifest, list) and config:
        docs_dir = config["output"]["docs_dir"]
        for rec in manifest:
            eo = rec.get("eo_number")
            dpath = rec.get("downloaded_file_path")
            stype = rec.get("source_type")
            if not isinstance(eo, int) or not isinstance(dpath, str) or not isinstance(stype, str):
                docs_ok = False
                break
            ext = ".html" if stype == "html" else ".pdf" if stype == "pdf" else None
            if ext is None:
                docs_ok = False
                break
            expected_rel = f"{docs_dir}/EO_{eo}{ext}"
            if dpath != expected_rel:
                docs_ok = False
                break
            fpath = workspace / dpath
            if not fpath.exists() or not fpath.is_file():
                docs_ok = False
                break
        if docs_ok and targets_numbers and len(manifest) == len(targets_numbers):
            scores["docs_files_exist_and_named_correctly"] = 1.0
    elif isinstance(manifest, list) and not config:
        docs_ok = False

    meta_ok = True
    if isinstance(manifest, list) and config:
        docs_dir = config["output"]["docs_dir"]
        for rec in manifest:
            dpath = rec.get("downloaded_file_path")
            stype = rec.get("source_type")
            sha = rec.get("sha256")
            bsize = rec.get("byte_size")
            if not isinstance(dpath, str):
                meta_ok = False
                break
            fpath = workspace / dpath
            if not fpath.exists() or not fpath.is_file():
                meta_ok = False
                break
            if not dpath.startswith(docs_dir + "/"):
                meta_ok = False
                break
            suffix = fpath.suffix.lower()
            if stype == "html" and suffix != ".html":
                meta_ok = False
                break
            if stype == "pdf" and suffix != ".pdf":
                meta_ok = False
                break
            try:
                actual_size = fpath.stat().st_size
            except Exception:
                meta_ok = False
                break
            if actual_size != bsize or actual_size <= 0:
                meta_ok = False
                break
            actual_sha = _compute_sha256(fpath)
            if not isinstance(sha, str) or sha.lower() != actual_sha.lower():
                meta_ok = False
                break
        if meta_ok:
            scores["manifest_file_metadata_valid"] = 1.0
    elif isinstance(manifest, list):
        meta_ok = False

    source_ok = True
    if isinstance(manifest, list) and config:
        allowed_roots = config["allowed_domains"]
        for rec in manifest:
            src_url = rec.get("source_url")
            src_domain = (rec.get("source_domain") or "").lower()
            host = _get_netloc(src_url)
            if not host:
                source_ok = False
                break
            if not _domain_allowed(host, allowed_roots):
                source_ok = False
                break
            # Consistency between recorded domain and URL host
            if not (host == src_domain or host.endswith("." + src_domain) or src_domain.endswith("." + host)):
                source_ok = False
                break
        if source_ok:
            scores["manifest_source_fields_valid"] = 1.0
    elif isinstance(manifest, list):
        source_ok = False

    search_log_path = workspace / expected_output["search_log"]
    search_log = _load_jsonl(search_log_path)
    if isinstance(search_log, list) and len(search_log) > 0:
        structure_ok = True
        for entry in search_log:
            if not isinstance(entry, dict):
                structure_ok = False
                break
            needed = ("eo_number", "query", "search_engine", "timestamp", "candidates")
            if any(k not in entry for k in needed):
                structure_ok = False
                break
            if not isinstance(entry.get("eo_number"), int):
                structure_ok = False
                break
            if not isinstance(entry.get("query"), str) or not entry.get("query").strip():
                structure_ok = False
                break
            if not isinstance(entry.get("search_engine"), str) or not entry.get("search_engine").strip():
                structure_ok = False
                break
            if not isinstance(entry.get("candidates"), list) or len(entry.get("candidates")) == 0:
                structure_ok = False
                break
            if not _is_iso_timestamp(entry.get("timestamp")):
                structure_ok = False
                break
            for cand in entry.get("candidates"):
                if not isinstance(cand, dict):
                    structure_ok = False
                    break
                for ck in ("title", "url", "domain"):
                    if ck not in cand or not isinstance(cand[ck], str) or not cand[ck].strip():
                        structure_ok = False
                        break
                if not structure_ok:
                    break
            if not structure_ok:
                break
        if structure_ok:
            scores["search_log_exists_and_structure"] = 1.0

        if config and isinstance(config.get("queries"), list) and queries_populated:
            configured_queries = set([q for q in config["queries"] if isinstance(q, str)])
            log_queries = [e.get("query") for e in search_log if isinstance(e, dict) and isinstance(e.get("query"), str)]
            # Require that every configured query appears at least once in the log
            if configured_queries and configured_queries.issubset(set(log_queries)):
                scores["search_log_queries_match_config"] = 1.0

        if config and isinstance(config.get("allowed_domains"), list):
            allowed_roots = config["allowed_domains"]
            cand_ok = True
            for entry in search_log:
                for cand in entry.get("candidates", []):
                    url = cand.get("url", "")
                    dom = (cand.get("domain", "") or "").lower()
                    host = _get_netloc(url)
                    if not host:
                        cand_ok = False
                        break
                    if not (host == dom or host.endswith("." + dom) or dom.endswith("." + host)):
                        cand_ok = False
                        break
                    if not _domain_allowed(host, allowed_roots):
                        cand_ok = False
                        break
                if not cand_ok:
                    break
            if cand_ok:
                scores["search_log_candidates_domains_allowed"] = 1.0

        if targets_numbers and config and queries_site_ok:
            eo_set = set(targets_numbers)
            coverage = {eo: False for eo in eo_set}
            allowed_roots = config["allowed_domains"]
            for entry in search_log:
                eo = entry.get("eo_number")
                q = entry.get("query", "")
                if eo in eo_set:
                    sites = re.findall(r"(?<!\w)site:([^\s]+)", q)
                    ok_sites = False
                    if sites:
                        ok_sites = True
                        for s in sites:
                            s_clean = _clean_site_token(s)
                            if not _domain_allowed(s_clean, allowed_roots):
                                ok_sites = False
                                break
                    if (str(eo) in q) and ok_sites:
                        coverage[eo] = True
            if all(coverage.values()):
                scores["search_log_per_eo_coverage"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()