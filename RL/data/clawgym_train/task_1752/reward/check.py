import json
import csv
import hashlib
import sys
from pathlib import Path
from datetime import datetime, date


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(path: Path):
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _compute_sha256(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _parse_iso_datetime(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _parse_iso_date(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        date.fromisoformat(s)
        return True
    except Exception:
        return False


def _extract_reporting_from_config(config_path: Path):
    text = _read_text(config_path)
    if not text:
        return None
    lines = text.splitlines()
    in_reporting = False
    spdx_json = None
    meeting_date = None
    for raw in lines:
        line = raw.rstrip("\n")
        if not line:
            continue
        if line.strip().startswith("#"):
            continue
        # detect top-level "reporting:"
        if not line.startswith(" ") and line.strip() == "reporting:":
            in_reporting = True
            continue
        # break out of reporting when dedented to top-level key
        if in_reporting and (line and not line.startswith(" ") and ":" in line):
            in_reporting = False
        if in_reporting:
            if ":" in line:
                try:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip().strip("'").strip('"')
                    if key == "spdx_json" and val:
                        spdx_json = val
                    if key == "meeting_date" and val:
                        meeting_date = val
                except Exception:
                    pass
    return {"spdx_json": spdx_json, "meeting_date": meeting_date}


def _find_precommit_build_hook(precommit_path: Path):
    text = _read_text(precommit_path)
    if not text:
        return {"has_local_repo": False, "has_hook": False, "has_entry": False, "files_scope_ok": False}
    lines = text.splitlines()
    has_local_repo = any(("repo:" in l and "local" in l) for l in lines)
    has_hook = False
    has_entry = False
    files_scope_ok = False
    for idx, l in enumerate(lines):
        if "id:" in l:
            parts = l.split(":", 1)
            if len(parts) == 2 and parts[0].strip() == "id" and parts[1].strip().strip('"').strip("'") == "build-reports":
                has_hook = True
                window = lines[idx: idx + 15]
                entry_found = False
                files_found = None
                for w in window:
                    if "entry:" in w:
                        p = w.split(":", 1)[1].strip()
                        if p:
                            entry_found = True
                    if "files:" in w:
                        files_found = w.split(":", 1)[1].strip()
                has_entry = entry_found
                if files_found:
                    if "data/" in files_found and "project/config.yaml" in files_found:
                        files_scope_ok = True
                break
    return {"has_local_repo": has_local_repo, "has_hook": has_hook, "has_entry": has_entry, "files_scope_ok": files_scope_ok}


def _parse_date(s: str):
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _compute_turnaround_days(assigned: str, completed: str):
    da = _parse_date(assigned)
    dc = _parse_date(completed)
    if da is None or dc is None:
        return None
    delta = dc - da
    return delta.days


def _load_spdx_licenses(spdx_path: Path):
    data = _load_json(spdx_path)
    if data is None:
        return None, None
    licenses_list = None
    if isinstance(data, dict) and "licenses" in data and isinstance(data["licenses"], list):
        licenses_list = data["licenses"]
    elif isinstance(data, list):
        licenses_list = data
    else:
        return None, None
    license_ids = set()
    for entry in licenses_list:
        if isinstance(entry, dict):
            lic = entry.get("licenseId")
            if isinstance(lic, str):
                license_ids.add(lic)
    return licenses_list, license_ids


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "spdx_json_saved": 0.0,
        "provenance_integrity": 0.0,
        "config_reporting_section": 0.0,
        "provenance_spdx_path_matches_config": 0.0,
        "reviewer_stats_csv_correct": 0.0,
        "section_summary_csv_correct": 0.0,
        "pre_commit_local_hook": 0.0,
    }

    spdx_path = workspace / "external" / "spdx" / "licenses.json"
    provenance_path = workspace / "reports" / "provenance.json"
    reviewer_stats_path = workspace / "reports" / "reviewer_stats.csv"
    section_summary_path = workspace / "reports" / "section_summary.csv"
    config_path = workspace / "project" / "config.yaml"
    precommit_path = workspace / ".pre-commit-config.yaml"
    reviews_csv_path = workspace / "data" / "reviews.csv"
    submissions_jsonl_path = workspace / "data" / "submissions.jsonl"

    licenses_list, license_ids = (None, None)
    if spdx_path.exists():
        licenses_list, license_ids = _load_spdx_licenses(spdx_path)
        if licenses_list is not None and license_ids is not None and len(licenses_list) >= len(license_ids) >= 1:
            scores["spdx_json_saved"] = 1.0

    prov = _load_json(provenance_path) if provenance_path.exists() else None
    prov_ok = False
    if prov and isinstance(prov, dict):
        spdx_json_path_field = prov.get("spdx_json_path")
        sha256_field = prov.get("sha256")
        license_count_field = prov.get("license_count")
        retrieved_at_field = prov.get("retrieved_at")
        path_ok = spdx_json_path_field == "external/spdx/licenses.json"
        sha_ok = sha256_field == _compute_sha256(spdx_path) if sha256_field and spdx_path.exists() else False
        lic_count_ok = False
        if isinstance(license_count_field, int) and licenses_list is not None:
            lic_count_ok = (license_count_field == len(licenses_list))
        retrieved_ok = _parse_iso_datetime(retrieved_at_field)
        prov_ok = all([path_ok, sha_ok, lic_count_ok, retrieved_ok])
    scores["provenance_integrity"] = 1.0 if prov_ok else 0.0

    reporting = _extract_reporting_from_config(config_path) if config_path.exists() else None
    config_ok = False
    if reporting is not None:
        spdx_json_val = reporting.get("spdx_json")
        meeting_date_val = reporting.get("meeting_date")
        spdx_path_ok = (spdx_json_val == "external/spdx/licenses.json")
        meeting_ok = _parse_iso_date(meeting_date_val)
        config_ok = bool(spdx_path_ok and meeting_ok)
    scores["config_reporting_section"] = 1.0 if config_ok else 0.0

    prov_path_match_ok = False
    if prov and reporting and isinstance(prov, dict):
        if prov.get("spdx_json_path") == reporting.get("spdx_json") == "external/spdx/licenses.json":
            prov_path_match_ok = True
    scores["provenance_spdx_path_matches_config"] = 1.0 if prov_path_match_ok else 0.0

    reviewer_stats_ok = False
    exp_reviewer_stats = {}
    headers_src, rows_src = _load_csv_dicts(reviews_csv_path)
    if headers_src and rows_src is not None:
        per_rev_counts = {}
        per_rev_days_sum = {}
        per_rev_comments = {}
        valid_rows = True
        for r in rows_src:
            reviewer_id = r.get("reviewer_id")
            assigned_date = r.get("assigned_date")
            completed_date = r.get("completed_date")
            comments_str = r.get("comments_count")
            if not reviewer_id:
                valid_rows = False
                break
            td = _compute_turnaround_days(assigned_date, completed_date)
            try:
                comments_count = int(comments_str)
            except Exception:
                valid_rows = False
                break
            if td is None:
                valid_rows = False
                break
            per_rev_counts[reviewer_id] = per_rev_counts.get(reviewer_id, 0) + 1
            per_rev_days_sum[reviewer_id] = per_rev_days_sum.get(reviewer_id, 0) + td
            per_rev_comments[reviewer_id] = per_rev_comments.get(reviewer_id, 0) + comments_count
        if valid_rows:
            for rid in per_rev_counts.keys():
                count = per_rev_counts[rid]
                avg = round(per_rev_days_sum[rid] / count, 1)
                total_comments = per_rev_comments.get(rid, 0)
                exp_reviewer_stats[rid] = {
                    "reviewer_id": rid,
                    "reviews_completed": count,
                    "avg_turnaround_days": avg,
                    "total_comments": total_comments,
                }
            headers_out, rows_out = _load_csv_dicts(reviewer_stats_path)
            if headers_out and rows_out is not None:
                expected_headers = ["reviewer_id", "reviews_completed", "avg_turnaround_days", "total_comments"]
                headers_ok = headers_out == expected_headers
                try:
                    out_map = {}
                    for row in rows_out:
                        rid = row.get("reviewer_id")
                        if rid in out_map:
                            headers_ok = False
                            break
                        rc = int(row.get("reviews_completed"))
                        avg_str = row.get("avg_turnaround_days")
                        avg_val = float(avg_str) if avg_str != "" else None
                        tc = int(row.get("total_comments"))
                        out_map[rid] = {
                            "reviewer_id": rid,
                            "reviews_completed": rc,
                            "avg_turnaround_days": round(avg_val, 1) if avg_val is not None else None,
                            "total_comments": tc,
                        }
                    content_ok = (set(out_map.keys()) == set(exp_reviewer_stats.keys()))
                    if content_ok:
                        for rid, exp in exp_reviewer_stats.items():
                            got = out_map.get(rid)
                            if got is None:
                                content_ok = False
                                break
                            if not (
                                got["reviews_completed"] == exp["reviews_completed"]
                                and got["total_comments"] == exp["total_comments"]
                                and abs(got["avg_turnaround_days"] - exp["avg_turnaround_days"]) < 1e-9
                            ):
                                content_ok = False
                                break
                    reviewer_stats_ok = headers_ok and content_ok
                except Exception:
                    reviewer_stats_ok = False
    scores["reviewer_stats_csv_correct"] = 1.0 if reviewer_stats_ok else 0.0

    section_summary_ok = False
    if license_ids is not None and headers_src and rows_src is not None:
        submissions = _load_jsonl(submissions_jsonl_path)
        if submissions is not None:
            ms_to_section = {}
            ms_to_license = {}
            sections_set = set()
            valid_sub = True
            for item in submissions:
                mid = item.get("manuscript_id")
                sec = item.get("section")
                lic = item.get("license")
                if not isinstance(mid, str) or not isinstance(sec, str) or not isinstance(lic, str):
                    valid_sub = False
                    break
                ms_to_section[mid] = sec
                ms_to_license[mid] = lic
                sections_set.add(sec)
            if valid_sub:
                subs_count = {sec: 0 for sec in sections_set}
                valid_license_count = {sec: 0 for sec in sections_set}
                invalid_license_count = {sec: 0 for sec in sections_set}
                for mid, sec in ms_to_section.items():
                    subs_count[sec] += 1
                    if mid in ms_to_license:
                        lic = ms_to_license[mid]
                        if lic in license_ids:
                            valid_license_count[sec] += 1
                        else:
                            invalid_license_count[sec] += 1
                reviews_count = {sec: 0 for sec in sections_set}
                days_sum = {sec: 0 for sec in sections_set}
                for r in rows_src:
                    mid = r.get("manuscript_id")
                    if mid not in ms_to_section:
                        continue
                    sec = ms_to_section[mid]
                    td = _compute_turnaround_days(r.get("assigned_date"), r.get("completed_date"))
                    if td is None:
                        valid_sub = False
                        break
                    reviews_count[sec] += 1
                    days_sum[sec] += td
                if valid_sub:
                    expected_rows = {}
                    for sec in sections_set:
                        revs = reviews_count.get(sec, 0)
                        if revs > 0:
                            avg_days = round(days_sum[sec] / revs, 1)
                            avg_str_expected = avg_days
                        else:
                            avg_str_expected = None
                        expected_rows[sec] = {
                            "section": sec,
                            "submissions": subs_count.get(sec, 0),
                            "reviews": revs,
                            "avg_turnaround_days": avg_str_expected,
                            "valid_license_count": valid_license_count.get(sec, 0),
                            "invalid_license_count": invalid_license_count.get(sec, 0),
                        }
                    headers_out2, rows_out2 = _load_csv_dicts(section_summary_path)
                    if headers_out2 and rows_out2 is not None:
                        expected_headers2 = [
                            "section",
                            "submissions",
                            "reviews",
                            "avg_turnaround_days",
                            "valid_license_count",
                            "invalid_license_count",
                        ]
                        headers_ok2 = headers_out2 == expected_headers2
                        try:
                            out_map2 = {}
                            for row in rows_out2:
                                sec = row.get("section")
                                if sec in out_map2:
                                    headers_ok2 = False
                                    break
                                subs = int(row.get("submissions"))
                                revs = int(row.get("reviews"))
                                avg_field = row.get("avg_turnaround_days")
                                if avg_field == "":
                                    avg_val = None
                                else:
                                    avg_val = round(float(avg_field), 1)
                                valid_l = int(row.get("valid_license_count"))
                                invalid_l = int(row.get("invalid_license_count"))
                                out_map2[sec] = {
                                    "section": sec,
                                    "submissions": subs,
                                    "reviews": revs,
                                    "avg_turnaround_days": avg_val,
                                    "valid_license_count": valid_l,
                                    "invalid_license_count": invalid_l,
                                }
                            content_ok2 = (set(out_map2.keys()) == set(expected_rows.keys()))
                            if content_ok2:
                                for sec, exp_row in expected_rows.items():
                                    got = out_map2.get(sec)
                                    if got is None:
                                        content_ok2 = False
                                        break
                                    avg_ok = False
                                    if exp_row["avg_turnaround_days"] is None:
                                        avg_ok = (got["avg_turnaround_days"] is None)
                                    else:
                                        avg_ok = (
                                            got["avg_turnaround_days"] is not None
                                            and abs(got["avg_turnaround_days"] - exp_row["avg_turnaround_days"]) < 1e-9
                                        )
                                    if not (
                                        got["submissions"] == exp_row["submissions"]
                                        and got["reviews"] == exp_row["reviews"]
                                        and got["valid_license_count"] == exp_row["valid_license_count"]
                                        and got["invalid_license_count"] == exp_row["invalid_license_count"]
                                        and avg_ok
                                    ):
                                        content_ok2 = False
                                        break
                            section_summary_ok = headers_ok2 and content_ok2
                        except Exception:
                            section_summary_ok = False
    scores["section_summary_csv_correct"] = 1.0 if section_summary_ok else 0.0

    hook_info = _find_precommit_build_hook(precommit_path) if precommit_path.exists() else {
        "has_local_repo": False,
        "has_hook": False,
        "has_entry": False,
        "files_scope_ok": False,
    }
    precommit_ok = hook_info["has_local_repo"] and hook_info["has_hook"] and hook_info["has_entry"] and hook_info["files_scope_ok"]
    scores["pre_commit_local_hook"] = 1.0 if precommit_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()