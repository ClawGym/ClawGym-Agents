import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                return None
            rows = [row for row in reader]
            return fieldnames, rows
    except Exception:
        return None


def _parse_yaml_orgs(path: Path) -> Optional[List[Dict[str, str]]]:
    # Minimal parser for the known structure of input/orgs.yaml
    # Expects:
    # organizations:
    #   - name: ...
    #     domain: ...
    try:
        text = _read_text(path)
        if text is None:
            return None
        orgs: List[Dict[str, str]] = []
        current: Dict[str, str] = {}
        in_list = False
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("organizations:"):
                in_list = True
                continue
            if not in_list:
                continue
            # entry start marker
            if stripped.startswith("- "):
                # start a new record
                if current:
                    # if previous had both fields, append
                    if "name" in current and "domain" in current:
                        orgs.append({"name": current["name"], "domain": current["domain"]})
                current = {}
                # may have "- name: X" on same line
                kv = stripped[2:]
                if ":" in kv:
                    k, v = kv.split(":", 1)
                    key = k.strip()
                    val = v.strip()
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    if val.startswith("'") and val.endswith("'"):
                        val = val[1:-1]
                    current[key] = val
                continue
            # indented key: value
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                key = k.strip()
                val = v.strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                if val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                current[key] = val
        if current and "name" in current and "domain" in current:
            orgs.append({"name": current["name"], "domain": current["domain"]})
        return orgs
    except Exception:
        return None


def _is_iso8601_z(s: str) -> bool:
    # Strict Zulu time like 2023-05-01T12:30:45Z
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", s))


def _compute_sha256_bytes(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _parse_bool_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    sl = s.strip().lower()
    if sl == "true":
        return True
    if sl == "false":
        return False
    return None


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _filename_timestamp_match(page_type: str, filename: str) -> bool:
    # Expect format: {page_type}-{YYYYMMDDTHHMMSSZ}.html
    m = re.fullmatch(rf"{re.escape(page_type)}-(\d{{8}}T\d{{6}}Z)\.html", filename)
    return m is not None


def _orgs_index(orgs: List[Dict[str, str]]) -> Dict[Tuple[str, str], Dict[str, str]]:
    return {(o["name"], o["domain"]): o for o in orgs}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "pipeline_script_present": 0.0,
        "pages_csv_structure_valid": 0.0,
        "pages_csv_row_counts_and_page_types": 0.0,
        "pages_csv_saved_paths_and_hashes_valid": 0.0,
        "features_csv_structure_and_counts_valid": 0.0,
        "features_csv_risk_score_formula_valid": 0.0,
        "cross_file_has_flags_consistent": 0.0,
        "risk_ranking_csv_present_and_sorted": 0.0,
        "low_risk_csv_present_and_filtered_sorted": 0.0,
        "summary_md_present_and_consistent": 0.0,
        "logs_run_log_present_and_contains_required_info": 0.0,
    }

    # Check script presence
    script_path = workspace / "scripts" / "analyze_sites.py"
    if script_path.is_file():
        scores["pipeline_script_present"] = 1.0

    # Load orgs from input
    orgs_yaml_path = workspace / "input" / "orgs.yaml"
    orgs = _parse_yaml_orgs(orgs_yaml_path) or []
    orgs_count = len(orgs)
    orgs_by_name_domain = _orgs_index(orgs)

    # Validate pages.csv
    pages_csv_path = workspace / "data" / "processed" / "pages.csv"
    pages_header_rows = _read_csv_dicts(pages_csv_path)
    pages_rows: List[Dict[str, str]] = []
    if pages_header_rows is not None:
        pages_header, pages_rows = pages_header_rows
        expected_pages_header = [
            "org_name",
            "domain",
            "page_type",
            "source_url",
            "http_status",
            "retrieved_at_iso8601",
            "saved_path",
            "sha256",
            "size_bytes",
            "word_count",
        ]
        structure_ok = pages_header == expected_pages_header
        # Validate field types and presence
        basic_fields_ok = True
        per_org_page_types: Dict[Tuple[str, str], set] = {}
        saved_paths_ok_all = True
        page_types_set_ok = True
        urls_https_ok = True
        timestamps_ok = True
        statuses_ok = True
        sizes_ok = True
        rows_count_ok = False
        one_each_ok = False
        sha_ok = True
        wordcount_ok = True
        org_name_domain_set_ok = True

        for row in pages_rows:
            org_name = row.get("org_name", "")
            domain = row.get("domain", "")
            page_type = row.get("page_type", "")
            source_url = row.get("source_url", "")
            http_status = row.get("http_status", "")
            retrieved = row.get("retrieved_at_iso8601", "")
            saved_path = row.get("saved_path", "")
            sha256 = row.get("sha256", "")
            size_bytes = row.get("size_bytes", "")
            word_count = row.get("word_count", "")

            # Basic field presence
            if any(v is None for v in [org_name, domain, page_type, source_url, http_status, retrieved, saved_path, sha256, size_bytes, word_count]):
                basic_fields_ok = False

            # Page type check
            if page_type not in {"home", "policy", "donate"}:
                page_types_set_ok = False

            # Ensure org references exist in orgs list if provided
            if orgs_count > 0 and (org_name, domain) not in orgs_by_name_domain:
                org_name_domain_set_ok = False

            # Group per org
            key = (org_name, domain)
            per_org_page_types.setdefault(key, set()).add(page_type)

            # Source URL must be https
            if not source_url.lower().startswith("https://"):
                urls_https_ok = False

            # http_status int
            if _safe_int(http_status) is None:
                statuses_ok = False

            # timestamp
            if not _is_iso8601_z(retrieved):
                timestamps_ok = False

            # size bytes int
            size_val = _safe_int(size_bytes)
            if size_val is None or size_val < 0:
                sizes_ok = False

            # word_count int
            wc_val = _safe_int(word_count)
            if wc_val is None or wc_val < 0:
                wordcount_ok = False

            # saved path and sha validation
            if saved_path.strip() == "":
                # If missing, sha must be empty, size_bytes should be 0
                if sha256.strip() != "":
                    sha_ok = False
                if size_val is None or size_val != 0:
                    sizes_ok = False
            else:
                # Path must exist and be under data/raw/
                sp = workspace / saved_path
                if not sp.is_file():
                    saved_paths_ok_all = False
                # check starts with data/raw/
                if not saved_path.replace("\\", "/").startswith("data/raw/"):
                    saved_paths_ok_all = False
                # filename conforms to pattern
                fname = sp.name
                if not _filename_timestamp_match(page_type, fname):
                    saved_paths_ok_all = False
                # sha and size must match file
                actual_sha = _compute_sha256_bytes(sp) if sp.exists() else None
                if not sha256 or actual_sha is None or sha256 != actual_sha:
                    sha_ok = False
                try:
                    actual_size = sp.stat().st_size if sp.exists() else None
                except Exception:
                    actual_size = None
                if actual_size is None or size_val != actual_size:
                    sizes_ok = False

        # Check count and one of each page_type per org (if orgs list known)
        if orgs_count > 0:
            rows_count_ok = len(pages_rows) == 3 * orgs_count
            one_each_ok = True
            for o in orgs:
                key = (o["name"], o["domain"])
                pts = per_org_page_types.get(key, set())
                if pts != {"home", "policy", "donate"}:
                    one_each_ok = False
                    break

        if structure_ok and basic_fields_ok and page_types_set_ok and urls_https_ok and timestamps_ok and statuses_ok and wordcount_ok and org_name_domain_set_ok:
            scores["pages_csv_structure_valid"] = 1.0
        else:
            scores["pages_csv_structure_valid"] = 0.0

        if rows_count_ok and one_each_ok:
            scores["pages_csv_row_counts_and_page_types"] = 1.0
        else:
            scores["pages_csv_row_counts_and_page_types"] = 0.0

        if saved_paths_ok_all and sizes_ok and sha_ok:
            scores["pages_csv_saved_paths_and_hashes_valid"] = 1.0
        else:
            scores["pages_csv_saved_paths_and_hashes_valid"] = 0.0
    else:
        # Missing or unreadable pages.csv -> leave scores at 0.0
        pass

    # Validate features.csv
    features_csv_path = workspace / "data" / "processed" / "features.csv"
    features_header_rows = _read_csv_dicts(features_csv_path)
    features_rows: List[Dict[str, str]] = []
    features_by_org: Dict[Tuple[str, str], Dict[str, str]] = {}
    if features_header_rows is not None:
        features_header, features_rows = features_header_rows
        expected_features_header = [
            "org_name",
            "domain",
            "has_home",
            "has_policy",
            "has_donate",
            "unique_trackers",
            "total_tracker_hits",
            "policy_keywords_present",
            "processors_found",
            "risk_score",
        ]
        structure_ok = features_header == expected_features_header
        counts_ok = len(features_rows) == orgs_count if orgs_count > 0 else False

        types_ok = True
        risk_formula_ok = True
        for row in features_rows:
            org_name = row.get("org_name", "")
            domain = row.get("domain", "")
            has_home = _parse_bool_str(row.get("has_home", ""))
            has_policy = _parse_bool_str(row.get("has_policy", ""))
            has_donate = _parse_bool_str(row.get("has_donate", ""))
            unique_trackers = _safe_int(row.get("unique_trackers", ""))
            total_tracker_hits = _safe_int(row.get("total_tracker_hits", ""))
            policy_keywords_present = _safe_int(row.get("policy_keywords_present", ""))
            processors_found = row.get("processors_found", "")
            risk_score_val = _safe_int(row.get("risk_score", ""))

            # type checks
            if None in [has_home, has_policy, has_donate, unique_trackers, total_tracker_hits, policy_keywords_present, risk_score_val]:
                types_ok = False
            else:
                if unique_trackers < 0 or total_tracker_hits < 0 or policy_keywords_present < 0 or risk_score_val < 0:
                    types_ok = False

            # risk score formula
            if processors_found.strip() == "":
                processors_count = 0
            else:
                processors_count = len([p for p in processors_found.split(";") if p.strip() != ""])
            penalty = 5 if (has_policy is False) else 0
            computed = 3 * (unique_trackers or 0) + 1 * (total_tracker_hits or 0) + 2 * (policy_keywords_present or 0) + 1 * processors_count + penalty
            if risk_score_val != computed:
                risk_formula_ok = False

            features_by_org[(org_name, domain)] = row

        if structure_ok and counts_ok and types_ok:
            scores["features_csv_structure_and_counts_valid"] = 1.0
        else:
            scores["features_csv_structure_and_counts_valid"] = 0.0

        if risk_formula_ok:
            scores["features_csv_risk_score_formula_valid"] = 1.0
        else:
            scores["features_csv_risk_score_formula_valid"] = 0.0
    else:
        # leave zeros
        pass

    # Cross-file consistency of has_home, has_policy, has_donate
    if pages_header_rows is not None and features_header_rows is not None and orgs_count > 0:
        _, pages_rows = pages_header_rows
        has_flags_ok = True
        # Define "has_page" as: row exists with page_type and saved_path non-empty and http_status in 200..399
        pages_by_org_type: Dict[Tuple[str, str, str], Dict[str, str]] = {}
        for row in pages_rows:
            key = (row.get("org_name", ""), row.get("domain", ""), row.get("page_type", ""))
            pages_by_org_type[key] = row
        for o in orgs:
            key_home = (o["name"], o["domain"], "home")
            key_policy = (o["name"], o["domain"], "policy")
            key_donate = (o["name"], o["domain"], "donate")

            def got(k: Tuple[str, str, str]) -> bool:
                r = pages_by_org_type.get(k)
                if not r:
                    return False
                sp = r.get("saved_path", "").strip() != ""
                hs = _safe_int(r.get("http_status", ""))
                hs_ok = hs is not None and 200 <= hs < 400
                return sp and hs_ok

            expect = {
                "has_home": got(key_home),
                "has_policy": got(key_policy),
                "has_donate": got(key_donate),
            }
            fr = features_by_org.get((o["name"], o["domain"]))
            if not fr:
                has_flags_ok = False
                break
            for fld in ["has_home", "has_policy", "has_donate"]:
                val = _parse_bool_str(fr.get(fld, ""))
                if val is None or val != expect[fld]:
                    has_flags_ok = False
                    break
            if not has_flags_ok:
                break
        scores["cross_file_has_flags_consistent"] = 1.0 if has_flags_ok else 0.0
    else:
        # Cannot validate without both files and orgs
        scores["cross_file_has_flags_consistent"] = 0.0

    # Validate risk_ranking.csv
    ranking_path = workspace / "reports" / "risk_ranking.csv"
    ranking_header_rows = _read_csv_dicts(ranking_path)
    if ranking_header_rows is not None and features_header_rows is not None and orgs_count > 0:
        ranking_header, ranking_rows = ranking_header_rows
        expected_ranking_header = ["rank", "org_name", "domain", "risk_score"]
        header_ok = ranking_header == expected_ranking_header
        set_ok = True
        sort_ok = True
        rank_seq_ok = True
        rs_match_features = True

        # Set equality
        features_keys = set(features_by_org.keys())
        ranking_keys = {(r.get("org_name", ""), r.get("domain", "")) for r in ranking_rows}
        if features_keys != ranking_keys:
            set_ok = False

        # Risk scores match and sorted non-increasing
        prev = None
        for idx, r in enumerate(ranking_rows, start=1):
            r_rank = _safe_int(r.get("rank", ""))
            r_score = _safe_int(r.get("risk_score", ""))
            if r_rank != idx:
                rank_seq_ok = False
            if r_score is None:
                rs_match_features = False
                continue
            f = features_by_org.get((r.get("org_name", ""), r.get("domain", "")))
            if not f:
                rs_match_features = False
                continue
            f_score = _safe_int(f.get("risk_score", ""))
            if f_score != r_score:
                rs_match_features = False
            if prev is not None and r_score > prev:
                sort_ok = False
            prev = r_score

        if header_ok and set_ok and sort_ok and rank_seq_ok and rs_match_features:
            scores["risk_ranking_csv_present_and_sorted"] = 1.0
        else:
            scores["risk_ranking_csv_present_and_sorted"] = 0.0
    else:
        scores["risk_ranking_csv_present_and_sorted"] = 0.0

    # Validate low_risk.csv
    low_risk_path = workspace / "reports" / "low_risk.csv"
    low_risk_header_rows = _read_csv_dicts(low_risk_path)
    if low_risk_header_rows is not None and features_header_rows is not None and orgs_count > 0:
        low_header, low_rows = low_risk_header_rows
        expected_low_header = ["org_name", "domain", "risk_score"]
        header_ok = low_header == expected_low_header

        # Build expected set from features
        low_expected = {(k[0], k[1]) for k, v in features_by_org.items() if _safe_int(v.get("risk_score", "")) is not None and _safe_int(v.get("risk_score", "")) <= 8}
        low_actual = {(r.get("org_name", ""), r.get("domain", "")) for r in low_rows}
        set_ok = low_expected == low_actual

        # Sorted ascending by risk_score and all <= 8
        sort_ok = True
        prev = None
        all_leq_8 = True
        for r in low_rows:
            rs = _safe_int(r.get("risk_score", ""))
            if rs is None or rs > 8:
                all_leq_8 = False
            if prev is not None and rs is not None and prev is not None and rs < prev:
                # ascending order violated
                pass
            prev = rs
        # Ascending means non-decreasing
        prev = None
        for r in low_rows:
            rs = _safe_int(r.get("risk_score", ""))
            if rs is None:
                sort_ok = False
                break
            if prev is not None and rs < prev:
                sort_ok = False
                break
            prev = rs

        if header_ok and set_ok and sort_ok and all_leq_8:
            scores["low_risk_csv_present_and_filtered_sorted"] = 1.0
        else:
            scores["low_risk_csv_present_and_filtered_sorted"] = 0.0
    else:
        scores["low_risk_csv_present_and_filtered_sorted"] = 0.0

    # Validate summary.md
    summary_path = workspace / "reports" / "summary.md"
    summary_text = _read_text(summary_path)
    if summary_text is not None and features_header_rows is not None and ranking_header_rows is not None and orgs_count > 0:
        # Require timestamp of run (ISO8601 Z) present
        ts_present = bool(re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", summary_text))

        # total orgs analyzed number present
        total_present = str(orgs_count) in summary_text

        # how many had a policy page
        num_policy = sum(1 for v in features_by_org.values() if _parse_bool_str(v.get("has_policy", "")) is True)
        policy_present = str(num_policy) in summary_text

        # top 3 highest-risk orgs (name and score)
        _, ranking_rows = ranking_header_rows
        top3 = ranking_rows[:3] if len(ranking_rows) >= 3 else ranking_rows
        top3_ok = True
        for r in top3:
            name = r.get("org_name", "")
            score = r.get("risk_score", "")
            if name not in summary_text or str(score) not in summary_text:
                top3_ok = False
                break

        # top 3 lowest-risk orgs (name and score)
        # Build lowest by ascending features risk_score
        features_sorted_asc = sorted(features_by_org.items(), key=lambda kv: _safe_int(kv[1].get("risk_score", "")) or 0)
        low3 = features_sorted_asc[:3]
        low3_ok = True
        for (name, domain), v in low3:
            score = v.get("risk_score", "")
            if name not in summary_text or str(score) not in summary_text:
                low3_ok = False
                break

        if ts_present and total_present and policy_present and top3_ok and low3_ok:
            scores["summary_md_present_and_consistent"] = 1.0
        else:
            scores["summary_md_present_and_consistent"] = 0.0
    else:
        scores["summary_md_present_and_consistent"] = 0.0

    # Validate logs/run.log
    log_path = workspace / "logs" / "run.log"
    log_text = _read_text(log_path)
    if log_text is not None and orgs_count > 0:
        has_command = "scripts/analyze_sites.py" in log_text
        # Expect start and end time messages somewhere
        has_start = ("start" in log_text.lower()) or ("begin" in log_text.lower())
        has_end = ("end" in log_text.lower()) or ("finished" in log_text.lower()) or ("complete" in log_text.lower())
        # Contains each org name
        orgs_listed = all(o["name"] in log_text for o in orgs)
        # Mentions outputs
        outputs_mentioned = all(p in log_text for p in ["pages.csv", "features.csv", "risk_ranking.csv", "low_risk.csv", "summary.md"])
        if has_command and has_start and has_end and orgs_listed and outputs_mentioned:
            scores["logs_run_log_present_and_contains_required_info"] = 1.0
        else:
            scores["logs_run_log_present_and_contains_required_info"] = 0.0
    else:
        scores["logs_run_log_present_and_contains_required_info"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()