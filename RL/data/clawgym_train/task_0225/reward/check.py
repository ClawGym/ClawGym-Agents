import json
import sys
import re
import hashlib
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone
from html import unescape


def _safe_read_text(path: Path, encoding: str = "utf-8") -> str | None:
    try:
        return path.read_text(encoding=encoding)
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _safe_load_jsonl(path: Path):
    try:
        lines = _safe_read_text(path)
        if lines is None:
            return None
        items = []
        for ln in lines.splitlines():
            if not ln.strip():
                continue
            try:
                obj = json.loads(ln)
            except Exception:
                return None
            if not isinstance(obj, dict):
                return None
            items.append(obj)
        return items
    except Exception:
        return None


def _is_executable(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
        return bool(mode & 0o111)
    except Exception:
        return False


def _parse_config(yaml_text: str) -> dict | None:
    if yaml_text is None:
        return None
    lines = yaml_text.splitlines()
    data = {
        "keywords": [],
        "state_judiciary_regex": None,
        "federal_required_domain": None,
        "selection": {"min_federal": None, "min_state": None, "max_total": None},
    }
    i = 0
    n = len(lines)

    def _strip_quotes(s: str) -> str:
        s = s.strip()
        if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
            return s[1:-1]
        return s

    while i < n:
        line = lines[i]
        if re.match(r'^\s*keywords\s*:\s*$', line):
            i += 1
            while i < n and re.match(r'^\s*-\s+', lines[i]):
                kw = lines[i].split("-", 1)[1].strip()
                kw = _strip_quotes(kw)
                if kw:
                    data["keywords"].append(kw)
                i += 1
            continue
        m = re.match(r'^\s*state_judiciary_regex\s*:\s*(.+)$', line)
        if m:
            data["state_judiciary_regex"] = _strip_quotes(m.group(1))
            i += 1
            continue
        m = re.match(r'^\s*federal_required_domain\s*:\s*(.+)$', line)
        if m:
            data["federal_required_domain"] = _strip_quotes(m.group(1))
            i += 1
            continue
        if re.match(r'^\s*selection\s*:\s*$', line):
            i += 1
            while i < n and re.match(r'^\s{2,}\S', lines[i]):
                m1 = re.match(r'^\s*min_federal\s*:\s*(\d+)\s*$', lines[i])
                m2 = re.match(r'^\s*min_state\s*:\s*(\d+)\s*$', lines[i])
                m3 = re.match(r'^\s*max_total\s*:\s*(\d+)\s*$', lines[i])
                if m1:
                    data["selection"]["min_federal"] = int(m1.group(1))
                if m2:
                    data["selection"]["min_state"] = int(m2.group(1))
                if m3:
                    data["selection"]["max_total"] = int(m3.group(1))
                i += 1
            continue
        i += 1
    if not data["state_judiciary_regex"]:
        data["state_judiciary_regex"] = r'^([a-z0-9.-]*courts?[a-z0-9.-]*)\.gov$'
    if not data["federal_required_domain"]:
        data["federal_required_domain"] = 'uscourts.gov'
    sel = data["selection"]
    if sel["min_federal"] is None:
        sel["min_federal"] = 1
    if sel["min_state"] is None:
        sel["min_state"] = 1
    if sel["max_total"] is None:
        sel["max_total"] = 4
    return data


def _is_iso8601_utc(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    try:
        if s.endswith("Z"):
            candidate = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(candidate)
            return dt.tzinfo is not None and dt.utcoffset() == timezone.utc.utcoffset(dt)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                return False
            return dt.utcoffset() == timezone.utc.utcoffset(dt)
    except Exception:
        pats = ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"]
        for pat in pats:
            try:
                datetime.strptime(s, pat)
                return True
            except Exception:
                continue
    return False


def _extract_visible_text(html: str) -> str:
    if not isinstance(html, str):
        return ""
    html_no_ss = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    html_no_comments = re.sub(r"(?is)<!--.*?-->", " ", html_no_ss)
    text = re.sub(r"(?is)<[^>]+>", " ", html_no_comments)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _compute_word_count(text: str) -> int:
    if not text:
        return 0
    tokens = re.findall(r"\S+", text)
    return len(tokens)


def _compute_keyword_hits(text: str, keywords: list) -> dict:
    hits = {}
    for kw in keywords:
        try:
            pattern = re.compile(rf"\b{re.escape(kw)}\b", flags=re.IGNORECASE)
            count = len(pattern.findall(text))
        except re.error:
            count = 0
        hits[kw] = int(count)
    return hits


def _has_pdf_links(html: str) -> bool:
    if not isinstance(html, str):
        return False
    html_clean = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    links = re.findall(r'(?is)<a [^>]*href\s*=\s*["\']([^"\']+)["\']', html_clean)
    for href in links:
        if ".pdf" in href.lower():
            return True
    return False


def _sha256_file(path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "runner_script_exists_and_references_fetch": 0.0,
        "fetch_script_exists": 0.0,
        "policies_jsonl_exists_and_well_formed": 0.0,
        "policies_count_within_limits": 0.0,
        "federal_and_state_presence": 0.0,
        "domain_category_alignment": 0.0,
        "domain_matches_source_url": 0.0,
        "local_html_paths_valid": 0.0,
        "keyword_hits_recomputed_match": 0.0,
        "has_pdf_links_recomputed_match": 0.0,
        "word_count_consistency": 0.0,
        "manifest_exists_and_well_formed": 0.0,
        "manifest_digests_match_files": 0.0,
        "manifest_covers_policies": 0.0,
        "no_duplicate_records": 0.0,
    }

    cfg_path = workspace / "input" / "config.yaml"
    cfg_text = _safe_read_text(cfg_path)
    cfg = _parse_config(cfg_text) if cfg_text is not None else None

    state_regex_str = (cfg or {}).get("state_judiciary_regex") or r'^([a-z0-9.-]*courts?[a-z0-9.-]*)\.gov$'
    federal_domain = (cfg or {}).get("federal_required_domain") or "uscourts.gov"
    selection = (cfg or {}).get("selection") or {"min_federal": 1, "min_state": 1, "max_total": 4}
    min_federal = selection.get("min_federal", 1)
    min_state = selection.get("min_state", 1)
    max_total = selection.get("max_total", 4)
    cfg_keywords = (cfg or {}).get("keywords") or []

    run_sh = workspace / "scripts" / "run.sh"
    if run_sh.exists() and run_sh.is_file() and _is_executable(run_sh):
        run_text = _safe_read_text(run_sh) or ""
        if "fetch_policies.py" in run_text:
            scores["runner_script_exists_and_references_fetch"] = 1.0

    fetch_py = workspace / "scripts" / "fetch_policies.py"
    if fetch_py.exists() and fetch_py.is_file():
        scores["fetch_script_exists"] = 1.0

    policies_path = workspace / "outputs" / "structured" / "policies.jsonl"
    policies = _safe_load_jsonl(policies_path)

    policies_structure_ok = True
    if policies is None:
        policies_structure_ok = False
    else:
        for rec in policies:
            required_keys = [
                "source_url",
                "domain",
                "category",
                "page_title",
                "word_count",
                "keyword_hits",
                "has_pdf_links",
                "local_html_path",
                "fetched_at",
            ]
            if any(k not in rec for k in required_keys):
                policies_structure_ok = False
                break
            if not isinstance(rec["source_url"], str):
                policies_structure_ok = False
                break
            if not isinstance(rec["domain"], str):
                policies_structure_ok = False
                break
            if rec["category"] not in ("federal", "state"):
                policies_structure_ok = False
                break
            if not (rec["page_title"] is None or isinstance(rec["page_title"], str)):
                policies_structure_ok = False
                break
            if not isinstance(rec["word_count"], int) or rec["word_count"] < 0:
                policies_structure_ok = False
                break
            if not isinstance(rec["keyword_hits"], dict):
                policies_structure_ok = False
                break
            if not all(isinstance(k, str) and isinstance(v, int) and v >= 0 for k, v in rec["keyword_hits"].items()):
                policies_structure_ok = False
                break
            if not isinstance(rec["has_pdf_links"], bool):
                policies_structure_ok = False
                break
            if not isinstance(rec["local_html_path"], str):
                policies_structure_ok = False
                break
            if not isinstance(rec["fetched_at"], str) or not _is_iso8601_utc(rec["fetched_at"]):
                policies_structure_ok = False
                break
    if policies_structure_ok:
        scores["policies_jsonl_exists_and_well_formed"] = 1.0

    if policies:
        total = len(policies)
        if 2 <= total <= max_total:
            scores["policies_count_within_limits"] = 1.0

    federal_ok = False
    state_ok = False
    if policies:
        for rec in policies:
            dom = rec.get("domain", "").lower()
            cat = rec.get("category")
            if cat == "federal" and dom.endswith(federal_domain.lower()):
                federal_ok = True
            if cat == "state":
                if re.fullmatch(state_regex_str, dom) is not None:
                    state_ok = True
        if federal_ok and state_ok and (min_federal <= 1) and (min_state <= 1):
            scores["federal_and_state_presence"] = 1.0

    if policies:
        align_ok = True
        for rec in policies:
            dom = rec.get("domain", "").lower()
            cat = rec.get("category")
            if cat == "federal":
                if not dom.endswith(federal_domain.lower()):
                    align_ok = False
                    break
            elif cat == "state":
                if re.fullmatch(state_regex_str, dom) is None:
                    align_ok = False
                    break
            else:
                align_ok = False
                break
        if align_ok:
            scores["domain_category_alignment"] = 1.0

    if policies:
        dom_match_ok = True
        for rec in policies:
            src = rec.get("source_url", "")
            dom = rec.get("domain", "")
            try:
                host = urlparse(src).netloc
            except Exception:
                dom_match_ok = False
                break
            if host.lower() != dom.lower():
                dom_match_ok = False
                break
        if dom_match_ok:
            scores["domain_matches_source_url"] = 1.0

    if policies:
        paths_ok = True
        for rec in policies:
            lp = rec.get("local_html_path", "")
            if not isinstance(lp, str):
                paths_ok = False
                break
            raw_dir = workspace / "outputs" / "raw"
            file_path = workspace / lp
            try:
                file_path_resolved = file_path.resolve()
                raw_dir_resolved = raw_dir.resolve()
            except Exception:
                file_path_resolved = file_path
                raw_dir_resolved = raw_dir
            try:
                if raw_dir_resolved not in file_path_resolved.parents and file_path_resolved != raw_dir_resolved:
                    paths_ok = False
                    break
            except Exception:
                paths_ok = False
                break
            if not file_path.exists() or not file_path.is_file():
                paths_ok = False
                break
            if not lp.lower().endswith(".html"):
                paths_ok = False
                break
        if paths_ok:
            scores["local_html_paths_valid"] = 1.0

    if policies and cfg_keywords:
        kw_ok = True
        for rec in policies:
            lp = rec.get("local_html_path", "")
            html_path = workspace / lp
            html_text = _safe_read_text(html_path)
            if html_text is None:
                kw_ok = False
                break
            vis = _extract_visible_text(html_text)
            recomputed = _compute_keyword_hits(vis, cfg_keywords)
            rec_hits = rec.get("keyword_hits", {})
            if set(rec_hits.keys()) != set(cfg_keywords):
                kw_ok = False
                break
            mismatch = any(int(rec_hits.get(k, -1)) != int(v) for k, v in recomputed.items())
            if mismatch:
                kw_ok = False
                break
        if kw_ok:
            scores["keyword_hits_recomputed_match"] = 1.0

    if policies:
        pdf_ok = True
        for rec in policies:
            lp = rec.get("local_html_path", "")
            html_path = workspace / lp
            html_text = _safe_read_text(html_path)
            if html_text is None:
                pdf_ok = False
                break
            rec_val = rec.get("has_pdf_links")
            recomputed = _has_pdf_links(html_text)
            if rec_val is not True and rec_val is not False:
                pdf_ok = False
                break
            if bool(rec_val) != bool(recomputed):
                pdf_ok = False
                break
        if pdf_ok:
            scores["has_pdf_links_recomputed_match"] = 1.0

    if policies:
        wc_ok = True
        for rec in policies:
            lp = rec.get("local_html_path", "")
            html_path = workspace / lp
            html_text = _safe_read_text(html_path)
            if html_text is None:
                wc_ok = False
                break
            vis = _extract_visible_text(html_text)
            comp_wc = _compute_word_count(vis)
            rec_wc = rec.get("word_count")
            if not isinstance(rec_wc, int):
                wc_ok = False
                break
            tol = max(50, int(0.1 * max(comp_wc, 1)))
            if abs(rec_wc - comp_wc) > tol:
                wc_ok = False
                break
        if wc_ok:
            scores["word_count_consistency"] = 1.0

    manifest_path = workspace / "outputs" / "structured" / "manifest.json"
    manifest = _safe_load_json(manifest_path)
    manifest_structure_ok = True
    if not isinstance(manifest, list):
        manifest_structure_ok = False
    else:
        for item in manifest:
            if not isinstance(item, dict):
                manifest_structure_ok = False
                break
            required_keys = ["source_url", "local_html_path", "category", "fetched_at", "sha256"]
            if any(k not in item for k in required_keys):
                manifest_structure_ok = False
                break
            if not isinstance(item["source_url"], str):
                manifest_structure_ok = False
                break
            if not isinstance(item["local_html_path"], str):
                manifest_structure_ok = False
                break
            if item["category"] not in ("federal", "state"):
                manifest_structure_ok = False
                break
            if not isinstance(item["fetched_at"], str) or not _is_iso8601_utc(item["fetched_at"]):
                manifest_structure_ok = False
                break
            sha = item.get("sha256")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha or ""):
                manifest_structure_ok = False
                break
    if manifest_structure_ok:
        scores["manifest_exists_and_well_formed"] = 1.0

    if manifest_structure_ok:
        digests_ok = True
        for item in manifest:
            lp = item["local_html_path"]
            fp = workspace / lp
            if not fp.exists() or not fp.is_file():
                digests_ok = False
                break
            actual = _sha256_file(fp)
            if actual is None:
                digests_ok = False
                break
            if actual.lower() != item["sha256"].lower():
                digests_ok = False
                break
        if digests_ok:
            scores["manifest_digests_match_files"] = 1.0

    if policies and isinstance(manifest, list):
        covers_ok = True
        idx = {(m.get("source_url"), m.get("local_html_path")): m for m in manifest if isinstance(m, dict)}
        for rec in policies:
            key = (rec.get("source_url"), rec.get("local_html_path"))
            m = idx.get(key)
            if not m:
                covers_ok = False
                break
            if m.get("category") != rec.get("category"):
                covers_ok = False
                break
            if m.get("fetched_at") != rec.get("fetched_at"):
                covers_ok = False
                break
            fp = workspace / rec.get("local_html_path", "")
            if not fp.exists():
                covers_ok = False
                break
        if covers_ok:
            scores["manifest_covers_policies"] = 1.0

    if policies:
        srcs = [rec.get("source_url") for rec in policies]
        locs = [rec.get("local_html_path") for rec in policies]
        if len(srcs) == len(set(srcs)) and len(locs) == len(set(locs)):
            scores["no_duplicate_records"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()