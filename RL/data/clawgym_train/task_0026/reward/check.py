import json
import csv
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    try:
        text = _safe_read_text(path)
        if not text.strip():
            return None
        return json.loads(text)
    except Exception:
        return None


def _safe_load_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _host_endswith_domain(url: str, domain_pattern: str) -> bool:
    try:
        parsed = urlparse(url if re.match(r"^[a-zA-Z]+://", url) else "http://" + url)
        host = parsed.hostname or ""
        host = host.lower()
        dp = (domain_pattern or "").lower()
        if not host or not dp:
            return False
        return host == dp or host.endswith("." + dp)
    except Exception:
        return False


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    t = s.strip()
    if t.endswith("Z"):
        t_try = t[:-1] + "+00:00"
    else:
        t_try = t
    try:
        datetime.fromisoformat(t_try)
        return True
    except Exception:
        return False


def _coerce_int(val):
    if isinstance(val, int):
        return val
    if isinstance(val, float) and val.is_integer():
        return int(val)
    if isinstance(val, str):
        try:
            return int(val.strip())
        except Exception:
            return None
    return None


def _is_relative_subpath(base: Path, rel: str) -> bool:
    if not isinstance(rel, str) or not rel:
        return False
    if rel.startswith("/") or rel.startswith("\\"):
        return False
    if any(part == ".." for part in Path(rel).parts):
        return False
    target = base / rel
    try:
        if target.exists():
            try:
                target_res = target.resolve()
                base_res = base.resolve()
                return base_res in target_res.parents or target_res == base_res or target_res.parent == base_res or str(target_res).startswith(str(base_res) + str(Path.sep))
            except Exception:
                return str(target).startswith(str(base) + str(Path.sep))
        else:
            return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "resources_dir_exists": 0.0,
        "search_results_json_valid": 0.0,
        "search_results_entries_count_matches_input": 0.0,
        "search_results_candidates_domain_match": 0.0,
        "manifest_json_valid": 0.0,
        "manifest_entries_count_matches_input": 0.0,
        "manifest_candidates_len_top_1_3": 0.0,
        "manifest_selected_url_in_candidates": 0.0,
        "manifest_selected_url_domain_match": 0.0,
        "manifest_candidates_domain_match": 0.0,
        "manifest_download_paths_exist_and_relative": 0.0,
        "downloads_count_matches_input": 0.0,
        "manifest_command_used_valid": 0.0,
        "manifest_detection_method_valid": 0.0,
        "manifest_stderr_excerpt_length_ok": 0.0,
        "manifest_exit_codes_numeric": 0.0,
        "manifest_timestamp_iso8601": 0.0,
        "ext_matches_expected_flag_correct": 0.0,
        "cross_file_consistency_manifest_vs_input": 0.0,
        "cross_file_consistency_search_results_vs_input": 0.0,
        "manifest_search_engine_and_query_match_search_results": 0.0,
        "download_log_exists": 0.0,
        "download_log_contains_timestamp": 0.0,
    }

    input_csv_path = workspace / "input" / "resources.csv"
    out_resources_dir = workspace / "output" / "resources"
    search_results_path = workspace / "output" / "search_results.json"
    manifest_path = workspace / "output" / "manifest.json"
    log_path = workspace / "output" / "logs" / "download.log"

    csv_rows = _safe_load_csv(input_csv_path)
    expected_count = 0
    if csv_rows is not None:
        filtered_rows = []
        for row in csv_rows:
            org = (row.get("organization") or "").strip()
            dom = (row.get("domain_pattern") or "").strip()
            title = (row.get("title_query") or "").strip()
            exp_ext = (row.get("expected_ext") or "").strip()
            if org or dom or title or exp_ext:
                filtered_rows.append({
                    "organization": org,
                    "domain_pattern": dom,
                    "title_query": title,
                    "expected_ext": exp_ext
                })
        csv_rows = filtered_rows
        expected_count = len(csv_rows)
    else:
        csv_rows = []

    if out_resources_dir.is_dir():
        scores["resources_dir_exists"] = 1.0

    search_results = _safe_load_json(search_results_path)
    manifest = _safe_load_json(manifest_path)

    search_results_valid = False
    search_candidates_domain_total = 0
    search_candidates_domain_ok = 0
    if isinstance(search_results, list):
        all_ok = True
        for item in search_results:
            if not isinstance(item, dict):
                all_ok = False
                break
            for key in ["organization", "domain_pattern", "title_query", "search_engine", "search_query", "candidates"]:
                if key not in item:
                    all_ok = False
                    break
            if not all_ok:
                break
            if not isinstance(item.get("organization"), str):
                all_ok = False
                break
            if not isinstance(item.get("domain_pattern"), str):
                all_ok = False
                break
            if not isinstance(item.get("title_query"), str):
                all_ok = False
                break
            if not isinstance(item.get("search_engine"), str) or not item.get("search_engine").strip():
                all_ok = False
                break
            if not isinstance(item.get("search_query"), str) or not item.get("search_query").strip():
                all_ok = False
                break
            candidates = item.get("candidates")
            if not isinstance(candidates, list) or len(candidates) == 0:
                all_ok = False
                break
            domp = item.get("domain_pattern") or ""
            for cand in candidates:
                if not isinstance(cand, str):
                    all_ok = False
                    break
                search_candidates_domain_total += 1
                if _host_endswith_domain(cand, domp):
                    search_candidates_domain_ok += 1
            if not all_ok:
                break
        if all_ok:
            search_results_valid = True

    scores["search_results_json_valid"] = 1.0 if search_results_valid else 0.0

    if search_results_valid and expected_count > 0:
        scores["search_results_entries_count_matches_input"] = 1.0 if len(search_results) == expected_count else 0.0
    else:
        scores["search_results_entries_count_matches_input"] = 0.0

    if search_candidates_domain_total > 0:
        scores["search_results_candidates_domain_match"] = search_candidates_domain_ok / float(search_candidates_domain_total)
    else:
        scores["search_results_candidates_domain_match"] = 0.0

    manifest_valid = False
    if isinstance(manifest, list):
        all_ok = True
        for item in manifest:
            if not isinstance(item, dict):
                all_ok = False
                break
            required_fields = [
                "organization",
                "domain_pattern",
                "title_query",
                "expected_ext",
                "search_engine",
                "search_query",
                "candidates",
                "selected_url",
                "download_path",
                "command_used",
                "primary_exit_code",
                "fallback_used",
                "final_exit_code",
                "stderr_excerpt",
                "mime_type",
                "detection_method",
                "ext_matches_expected",
                "timestamp",
            ]
            for key in required_fields:
                if key not in item:
                    all_ok = False
                    break
            if not all_ok:
                break
            if not isinstance(item.get("organization"), str):
                all_ok = False
                break
            if not isinstance(item.get("domain_pattern"), str):
                all_ok = False
                break
            if not isinstance(item.get("title_query"), str):
                all_ok = False
                break
            if not isinstance(item.get("expected_ext"), str):
                all_ok = False
                break
            if not (isinstance(item.get("search_engine"), str) and item.get("search_engine").strip()):
                all_ok = False
                break
            if not (isinstance(item.get("search_query"), str) and item.get("search_query").strip()):
                all_ok = False
                break
            if not isinstance(item.get("candidates"), list) or len(item.get("candidates")) == 0:
                all_ok = False
                break
            if not isinstance(item.get("selected_url"), str):
                all_ok = False
                break
            if not isinstance(item.get("download_path"), str):
                all_ok = False
                break
            if not isinstance(item.get("command_used"), str):
                all_ok = False
                break
            if not isinstance(item.get("stderr_excerpt"), str):
                all_ok = False
                break
            if not isinstance(item.get("mime_type"), str):
                all_ok = False
                break
            if not isinstance(item.get("detection_method"), str):
                all_ok = False
                break
            if not isinstance(item.get("ext_matches_expected"), bool):
                all_ok = False
                break
            if not isinstance(item.get("fallback_used"), bool):
                all_ok = False
                break
            if not isinstance(item.get("timestamp"), str):
                all_ok = False
                break
        if all_ok:
            manifest_valid = True

    scores["manifest_json_valid"] = 1.0 if manifest_valid else 0.0

    if manifest_valid and expected_count > 0:
        scores["manifest_entries_count_matches_input"] = 1.0 if len(manifest) == expected_count else 0.0
    else:
        scores["manifest_entries_count_matches_input"] = 0.0

    if manifest_valid:
        total = len(manifest)
        ok = sum(1 for item in manifest if isinstance(item.get("candidates"), list) and 1 <= len(item.get("candidates")) <= 3)
        scores["manifest_candidates_len_top_1_3"] = ok / float(total) if total > 0 else 0.0

        ok = 0
        for item in manifest:
            cands = item.get("candidates", [])
            selected = item.get("selected_url", "")
            if isinstance(cands, list) and isinstance(selected, str) and selected in cands:
                ok += 1
        scores["manifest_selected_url_in_candidates"] = ok / float(total) if total > 0 else 0.0

        ok = 0
        for item in manifest:
            if _host_endswith_domain(item.get("selected_url", ""), item.get("domain_pattern", "")):
                ok += 1
        scores["manifest_selected_url_domain_match"] = ok / float(total) if total > 0 else 0.0

        total_c = 0
        ok_c = 0
        for item in manifest:
            domp = item.get("domain_pattern") or ""
            cands = item.get("candidates") or []
            for cand in cands:
                total_c += 1
                if _host_endswith_domain(cand, domp):
                    ok_c += 1
        scores["manifest_candidates_domain_match"] = (ok_c / float(total_c)) if total_c > 0 else 0.0

        ok = 0
        for item in manifest:
            dp = item.get("download_path", "")
            file_ok = False
            if isinstance(dp, str) and dp:
                if _is_relative_subpath(out_resources_dir, dp):
                    full_path = out_resources_dir / dp
                    if full_path.is_file():
                        file_ok = True
            if file_ok:
                ok += 1
        scores["manifest_download_paths_exist_and_relative"] = ok / float(total) if total > 0 else 0.0

        ok = 0
        for item in manifest:
            cmd = (item.get("command_used") or "").strip().lower()
            if cmd in {"curl", "wget"}:
                ok += 1
        scores["manifest_command_used_valid"] = ok / float(total) if total > 0 else 0.0

        ok = 0
        for item in manifest:
            dm = (item.get("detection_method") or "").strip().lower()
            if dm in {"file", "fallback"}:
                ok += 1
        scores["manifest_detection_method_valid"] = ok / float(total) if total > 0 else 0.0

        ok = 0
        for item in manifest:
            se = item.get("stderr_excerpt", "")
            if isinstance(se, str) and len(se) <= 300:
                ok += 1
        scores["manifest_stderr_excerpt_length_ok"] = ok / float(total) if total > 0 else 0.0

        ok = 0
        for item in manifest:
            p = _coerce_int(item.get("primary_exit_code"))
            f = _coerce_int(item.get("final_exit_code"))
            if p is not None and f is not None:
                ok += 1
        scores["manifest_exit_codes_numeric"] = ok / float(total) if total > 0 else 0.0

        ok = 0
        for item in manifest:
            ts = item.get("timestamp", "")
            if _is_iso8601(ts):
                ok += 1
        scores["manifest_timestamp_iso8601"] = ok / float(total) if total > 0 else 0.0

        ok = 0
        for item in manifest:
            dp = item.get("download_path", "")
            ext_matches_flag = item.get("ext_matches_expected", False)
            actual_ext = ""
            if isinstance(dp, str) and dp:
                p = Path(dp)
                actual_ext = p.suffix.lower().lstrip(".")
            expected_ext = (item.get("expected_ext") or "").lower().lstrip(".")
            expected_flag = (actual_ext == expected_ext) if expected_ext else False
            if isinstance(ext_matches_flag, bool) and (ext_matches_flag == expected_flag):
                ok += 1
        scores["ext_matches_expected_flag_correct"] = ok / float(total) if total > 0 else 0.0

    manifest_index = {}
    if isinstance(manifest, list):
        for item in manifest:
            key = ((item.get("organization") or "").strip(),
                   (item.get("domain_pattern") or "").strip(),
                   (item.get("title_query") or "").strip())
            manifest_index.setdefault(key, []).append(item)
    search_index = {}
    if isinstance(search_results, list):
        for item in search_results:
            key = ((item.get("organization") or "").strip(),
                   (item.get("domain_pattern") or "").strip(),
                   (item.get("title_query") or "").strip())
            search_index.setdefault(key, []).append(item)

    if expected_count > 0:
        ok = 0
        for row in csv_rows:
            key = (row["organization"], row["domain_pattern"], row["title_query"])
            items = manifest_index.get(key) or []
            found = False
            for it in items:
                if (it.get("expected_ext") or "").strip().lower() == (row.get("expected_ext") or "").strip().lower():
                    found = True
                    break
            if found:
                ok += 1
        scores["cross_file_consistency_manifest_vs_input"] = ok / float(expected_count)
    else:
        scores["cross_file_consistency_manifest_vs_input"] = 0.0

    if expected_count > 0:
        ok = 0
        for row in csv_rows:
            key = (row["organization"], row["domain_pattern"], row["title_query"])
            if key in search_index and len(search_index[key]) > 0:
                ok += 1
        scores["cross_file_consistency_search_results_vs_input"] = ok / float(expected_count)
    else:
        scores["cross_file_consistency_search_results_vs_input"] = 0.0

    if expected_count > 0:
        ok = 0
        for row in csv_rows:
            key = (row["organization"], row["domain_pattern"], row["title_query"])
            m_items = manifest_index.get(key) or []
            s_items = search_index.get(key) or []
            if not m_items or not s_items:
                continue
            m = m_items[0]
            s = s_items[0]
            if (m.get("search_engine") == s.get("search_engine")) and (m.get("search_query") == s.get("search_query")):
                ok += 1
        scores["manifest_search_engine_and_query_match_search_results"] = ok / float(expected_count)
    else:
        scores["manifest_search_engine_and_query_match_search_results"] = 0.0

    if out_resources_dir.is_dir() and expected_count > 0:
        file_count = sum(1 for p in out_resources_dir.rglob("*") if p.is_file())
        scores["downloads_count_matches_input"] = 1.0 if file_count == expected_count else 0.0
    else:
        scores["downloads_count_matches_input"] = 0.0

    if log_path.is_file():
        scores["download_log_exists"] = 1.0
        content = _safe_read_text(log_path)
        ts_pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        if ts_pattern.search(content or ""):
            scores["download_log_contains_timestamp"] = 1.0
        else:
            scores["download_log_contains_timestamp"] = 0.0
    else:
        scores["download_log_exists"] = 0.0
        scores["download_log_contains_timestamp"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()